#!/usr/bin/env python3

import signal
if __name__ == '__main__':
	signal.signal(signal.SIGHUP, signal.SIG_IGN) # ignored until startup is done (the reload handler is installed last): its default action kills the bot
import gevent.monkey
gevent.monkey.patch_all()
import json, os, re, sys, traceback
from pathlib import Path
from gevent import pywsgi
import threading
from urllib.parse import urlparse

from lib.config import *
from lib import config
from lib import worker
from lib import jobs
from lib import charts
from lib import sharesight
from lib import telegram
from lib import webhook

botName = None # the Telegram bot's @username, from telegram.register() at start
AUTHENTICATED = 'finbot.authenticated' # set in a request's WSGI environ once it has passed its service's check
SLACK_USER_SUBTYPES = (None, 'thread_broadcast') # Slack message subtypes a person writes; the others are bot posts, edits, joins and the like

def main(environ, start_response):
	"""WSGI entry point. Never lets an exception escape. A failure handling an authenticated request is reported as one line to the
	default channel and answered 200, so the service does not retry it into the chat again. Before authentication a failure is only
	logged: a stranger must not be able to post into the chats."""
	try:
		return handle(environ, start_response)
	except Exception as e:
		if environ.get(AUTHENTICATED):
			webhook.report_error(e, context=environ.get('PATH_INFO', 'bot'))
			status = '200 OK'
		else:
			print(f"request to {environ.get('PATH_INFO')!r} failed:", webhook.error_line(e), file=sys.stderr)
			traceback.print_exc()
			status = '500 Internal Server Error'
		try:
			start_response(status, [('Content-type', 'text/plain')], sys.exc_info())
		except Exception:
			pass
		return [b'']

def handle(environ, start_response):
	def print_body():
		try:
			print(f"inbound {uri} ", json.dumps(inbound, indent=4), file=sys.stderr)
		except Exception as e:
			print(e, "raw body: ", inbound, file=sys.stderr)
	def print_headers():
		for item in sorted(environ.items()):
			print(item, file=sys.stderr)
	def reply(status, body=b''):
		start_response(status, [('Content-type', 'application/json')])
		return [body]
	user=''
	userRealName=''
	print_headers() if config_print_headers else None
	# route on the path first, and turn strangers away before reading the body
	uri = environ.get('PATH_INFO', '')
	if config_telegramOutgoingWebhook and uri == urlparse(config_telegramOutgoingWebhook).path:
		service = 'telegram'
	elif config_slackOutgoingWebhook and uri == urlparse(config_slackOutgoingWebhook).path:
		service = 'slack'
	else:
		print("Unknown URI", repr(uri), file=sys.stderr)
		return reply('404 Not Found', b'<h1>404</h1>')
	if service == 'telegram': # Telegram proves itself with a header
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if secret != config_telegramOutgoingToken:
			print_headers()
			print("Fatal: Telegram authorisation header", "not present" if secret is None else "is present but incorrect", file=sys.stderr)
			return reply('403 Forbidden', b'<h1>Unauthorized</h1>')
		environ[AUTHENTICATED] = True
	try:
		inbound = json.loads(environ['wsgi.input'].read())
	except ValueError:
		print(f"[{service}]: request body is not JSON", file=sys.stderr)
		return reply('400 Bad Request', b'<h1>Bad Request</h1>')
	if not isinstance(inbound, dict):
		print(f"[{service}]: request body is not a JSON object", file=sys.stderr)
		return reply('400 Bad Request', b'<h1>Bad Request</h1>')
	#print_body() if debug else None
	if service == 'telegram':
		bot_name = botName
		if "callback_query" in inbound: # chart period buttons
			cq = inbound["callback_query"]
			cq_message = cq.get("message")
			if not cq_message or not cq.get("data"):
				return reply('200 OK', b'Unsupported')
			sender = cq.get("from", {})
			print("[Telegram button]:", '@' + sender["username"] if "username" in sender else sender.get("first_name", "unknown"), "chat", cq_message["chat"]["id"], cq["data"], file=sys.stderr)
			threading.Thread(target=worker.process_callback, args=('telegram', cq["id"], str(cq_message["chat"]["id"]), str(cq_message["message_id"]), cq["data"])).start()
			return reply('200 OK')
		if "message" not in inbound:
			return reply('200 OK', b'Unsupported')
		message_id = str(inbound["message"]["message_id"])
		chat_id = str(inbound["message"]["chat"]["id"])
		if "username" in inbound["message"]["from"]:
			user = userRealname = '@' + inbound["message"]["from"]["username"]
			if len(inbound["message"]["from"]["first_name"]):
				userRealName = inbound["message"]["from"]["first_name"]
		else:
			user = userRealName = '@' + inbound["message"]["from"]["first_name"]
		file_id = None
		if "text" in inbound["message"]:
			message = inbound["message"]["text"]
			print("[Telegram]:", user, message, file=sys.stderr) if debug else None
			#if message.startswith("Upcoming earnings for the next month") and user == telegram.getMe().get('username'):
			#	telegram.pinChatMessage(message_id, chat_id)
			# todo need to return sendMessage to get message_id and chat_id
		elif "photo" in inbound["message"]:
			message = ''
			if "caption" in inbound["message"]:
				message = inbound["message"]["caption"]
			photo = inbound["message"]["photo"][-1]
			file_id = photo["file_id"]
			print("[Telegram photo]:", user, file_id, message)
		elif IGNORED_TELEGRAM_CONTENT & inbound["message"].keys():
			return reply('200 OK') # stickers, GIFs, voice notes and the like: nothing to answer, nothing worth logging
		else:
			print(f"[{service}]: unhandled: 'message' without 'text/photo'", file=sys.stderr)
			return reply('200 OK', b'<h1>Unhandled</h1>')
	else: # Slack puts its token in the body
		if 'token' not in inbound:
			print("warning: Slack authorisation field not present", file=sys.stderr)
			print_body()
			return reply('403 Forbidden', b'<h1>Unauthorized</h1>')
		if inbound['token'] != config_slackOutgoingToken:
			print("Slack auth incorrect", file=sys.stderr)
			print_body()
			return reply('403 Forbidden', b'<h1>Unauthorized</h1>')
		environ[AUTHENTICATED] = True
		print("Incoming Slack request authenticated")
		if 'type' not in inbound:
			print(f"[{service}]: unhandled: no 'type'", file=sys.stderr)
			return reply('200 OK', b'Unhandled')
		if inbound['type'] == 'url_verification':
			response = json.dumps({"challenge": inbound["challenge"]})
			print("replying with", response, file=sys.stderr)
			return reply('200 OK', bytes(response, "utf-8"))
		if inbound['type'] == 'event_callback':
			event = inbound['event']
			bot_user = inbound['authorizations'][0]['user_id'] # QWERTY
			if event.get('bot_id') or event.get('subtype') not in SLACK_USER_SUBTYPES or not event.get('user') or event['user'] == bot_user:
				return reply('200 OK') # not written by a person: answering a bot (this one's replies and webhook reports included) could loop
			if event["type"] not in ('message', 'app_mention') or "text" not in event:
				print(f"[{service}]: unhandled event callback type", event["type"], file=sys.stderr)
				return reply('200 OK', b'<h1>Unhandled</h1>')
			message_id = str(event["ts"])
			message = event['text']
			message = re.sub(r'<http://.*\|([\w\.]+)>', r'\g<1>', message) # <http://dub.ax|dub.ax> becomes dub.ax
			message = re.sub(r'<(@[\w\.]+)>', r'\g<1>', message) # <@QWERTY> becomes @QWERTY
			user = userRealName = '<@' + event['user'] + '>' # ZXCVBN becomes <@ZXCVBN>
			bot_name = '@' + bot_user # QWERTY becomes @QWERTY
			chat_id = event['channel']
			print(f"[{service}]:", user, message, sys.stderr) if debug else None
			# this condition spawns a worker before returning
		else:
			print(f"[{service}]: unhandled 'type'", file=sys.stderr)
			return reply('200 OK', b'<h1>Unhandled</h1>')

	def runWorker():
		worker.process_request(service, chat_id, user, message, bot_name, userRealName, message_id)

	# process in a background thread so we don't keep the requesting client waiting
	t = threading.Thread(target=runWorker)
	t.start()

	# Return an empty response to the client
	return reply('200 OK')

IGNORED_TELEGRAM_CONTENT = {'sticker', 'animation', 'voice', 'video', 'video_note', 'audio', 'document', 'contact', 'location', 'venue', 'poll', 'dice'}

def git_version(checkout=None):
	"""Short hash of the checked-out commit, read straight from the .git directory: no git binary to run, and no "dubious
	ownership" refusal when the service user does not own the checkout. 'unknown' when it cannot be read."""
	try:
		git = Path(checkout or os.path.dirname(os.path.abspath(__file__))) / '.git'
		if git.is_file(): # a linked worktree or submodule: .git is a file saying "gitdir: <path>"
			git = (git.parent / git.read_text().split(':', 1)[1].strip()).resolve()
		common = (git / (git / 'commondir').read_text().strip()).resolve() if (git / 'commondir').is_file() else git # refs of a worktree
		head = (git / 'HEAD').read_text().strip()
		if head.startswith('ref:'):
			ref = head.split(':', 1)[1].strip()
			if (common / ref).is_file():
				head = (common / ref).read_text().strip()
			else: # the branch is only in packed-refs
				packed = (common / 'packed-refs').read_text().splitlines()
				head = next((line.split()[0] for line in packed if line.endswith(' ' + ref)), '')
		return head[:7] if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head) else 'unknown'
	except (OSError, IndexError):
		return 'unknown'

scheduler = None

def reload_all(*args):
	"""SIGHUP: re-read preferences.conf and, if the scheduler is running, schedule.cron. Each reports its own errors; a bad
	preferences.conf leaves the running config untouched."""
	try:
		changes = config.reload()
		for change in changes:
			print('config:', change, file=sys.stderr)
		print(f"config: reloaded {config.preferences_path}, {len(changes)} change{'' if len(changes) == 1 else 's'}", file=sys.stderr)
	except config.ConfigError as e:
		for line in e.errors:
			print('ERROR config:', line, file=sys.stderr)
	if scheduler:
		scheduler.reload()

if __name__ == '__main__':
	print(f'Starting finbot {git_version()}', file=sys.stderr)
	try:
		config.check_startup_environment()
	except config.ConfigError as e:
		for line in e.errors:
			print('ERROR config:', line, file=sys.stderr)
		sys.exit(1)
	for line in config.startup_report():
		print('config:', line, file=sys.stderr)
	if os.getuid() == 0:
		print("Running as superuser. This is not recommended.", file=sys.stderr)
	if config_scheduler: # read before anything else happens: an impossible time in it stops the start
		scheduler = jobs.Scheduler(lambda: data_file('schedule.cron'))
		try:
			if not scheduler.load():
				scheduler = None
		except jobs.ImpossibleTime as e:
			for line in e.lines:
				print('ERROR schedule:', line, file=sys.stderr)
			print('ERROR schedule: finbot will not start until every time in the schedule can come', file=sys.stderr)
			sys.exit(1)
	else:
		print('Scheduled reports are off (scheduler=False)', file=sys.stderr)
	httpd = pywsgi.WSGIServer((config_ip, config_port), main)
	httpd.secure_repr = False if debug else None
	print(f'Opening socket on http://{config_ip}:{config_port}', file=sys.stderr)
	if config_telegramBotToken and config_telegramOutgoingWebhook:
		try:
			botName = telegram.register() # here and only here: the job processes import lib.telegram too
		except Exception as e:
			print('ERROR', webhook.error_line(e, 'telegram webhook'), file=sys.stderr)
			sys.exit(1)
	if config_telegramBotToken:
		threading.Thread(target=charts.refresh_keyboards, daemon=True).start() # update stale DM keyboards in the background
	if config_sharesight_auth.get('client_id'):
		threading.Thread(target=sharesight.keep_warm, daemon=True).start() # keep the portfolio list and holdings report cached, while cache is on
	if scheduler:
		jobs.current = scheduler # for the .jobs chat command
		threading.Thread(target=scheduler.run_forever, daemon=True).start() # the scheduled reports, formerly cron jobs
	gevent.signal_handler(signal.SIGHUP, reload_all) # startup is done. systemctl reload finbot: pick up edited preferences.conf and schedule.cron
	try:
		httpd.serve_forever()
	except OSError as e:
		print(e, file=sys.stderr)
		sys.exit(1)
