#!/usr/bin/env python3

import signal
if __name__ == '__main__':
	signal.signal(signal.SIGHUP, signal.SIG_IGN) # ignored until startup is done (the reload handler is installed last): its default action kills the bot
	signal.signal(signal.SIGUSR1, signal.SIG_IGN) # likewise the cache flush
import gevent.monkey
gevent.monkey.patch_all()
import collections, json, os, re, sys, traceback
from pathlib import Path
from gevent import pywsgi
import threading

from lib import config
from lib import inbound
from lib import worker
from lib import jobs
from lib import sharesight
from lib import net
from lib import telegram
from lib import delivery
from lib import yahoo
from lib import render
from lib.reports import cleanup

AUTHENTICATED = 'finbot.authenticated' # set in a request's WSGI environ once it has passed its network's check
MAX_BODY = 1 << 20 # bytes in a request body, at most: an update from Telegram or Slack takes a few thousand
_updates_seen = collections.OrderedDict() # (service, update id) of the last updates taken, oldest first

def seen_before(service, update_id, keep=1000):
	"""Whether this update was taken already: Telegram's update_id, Slack's event_id. Slack resends an event it got no answer to
	within 3 seconds and Telegram one that failed, and a command must not run twice. An update without an id is never a repeat."""
	if update_id is None:
		return False
	key = (service, update_id)
	if key in _updates_seen:
		return True
	_updates_seen[key] = None
	if len(_updates_seen) > keep:
		_updates_seen.popitem(last=False)
	return False

def main(environ, start_response):
	"""WSGI entry point. Never lets an exception escape. A failure handling an authenticated request is reported as one line to the
	default channel and answered 200, so the service does not retry it into the chat again. Before authentication a failure is only
	logged: a stranger must not be able to post into the chats."""
	try:
		return handle(environ, start_response)
	except Exception as e:
		if environ.get(AUTHENTICATED):
			delivery.report_error(e, context=environ.get('PATH_INFO', 'bot'))
			status = '200 OK'
		else:
			print(f"request to {environ.get('PATH_INFO')!r} failed:", delivery.error_line(e), file=sys.stderr)
			print(net.redact(traceback.format_exc()), end='', file=sys.stderr)
			status = '500 Internal Server Error'
		try:
			start_response(status, [('Content-type', 'text/plain')], sys.exc_info())
		except Exception:
			pass
		return [b'']

def handle(environ, start_response):
	"""Route a request by its path to the network that posts there, turn it away unless it proves it comes from that
	network (before its body is read, when the proof is a header), read the update (CONTENT_LENGTH bytes, up to
	MAX_BODY), turn away repeats, and hand a message or a button press to lib/worker in a thread of its own: the network
	gets its answer at once."""
	def respond(response):
		"""Answer the request: a status line and a body."""
		start_response(response.status, [('Content-type', 'application/json')])
		return [response.body]
	def print_headers():
		"""Log the request headers, Telegram's secret header redacted."""
		for name, value in sorted(environ.items()):
			print((name, '<redacted>' if name == 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' else value), file=sys.stderr)
	if config.prefs.print_headers:
		print_headers()
	path = environ.get('PATH_INFO', '')
	source = inbound.route(path)
	if source is None:
		print("Unknown URI", repr(path), file=sys.stderr)
		return respond(inbound.NOT_FOUND)
	if why := source.refuse_unread(environ): # strangers are turned away before their body is read
		print_headers()
		print("Fatal:", why, file=sys.stderr)
		return respond(inbound.FORBIDDEN)
	length = environ.get('CONTENT_LENGTH') or '0'
	if not length.isdigit() or int(length) > MAX_BODY:
		print(f"[{source.service}]: a body of {length!r} bytes refused unread", file=sys.stderr)
		return respond(inbound.TOO_LARGE if length.isdigit() else inbound.BAD_REQUEST)
	body = environ['wsgi.input'].read(int(length)) # the body and no more: a server need not end the stream there
	try:
		update = source.decode(body)
	except ValueError:
		print(f"[{source.service}]: request body is not a JSON object", file=sys.stderr)
		return respond(inbound.BAD_REQUEST)
	if why := source.refuse(environ, body, update):
		shown = {k: '<redacted>' if k == 'token' else v for k, v in update.items()} # Slack's verification token
		print("warning:", why, file=sys.stderr)
		print(f"inbound {path} ", json.dumps(shown, indent=4, default=str), file=sys.stderr)
		return respond(inbound.FORBIDDEN)
	environ[AUTHENTICATED] = True
	event = source.parse(update)
	if isinstance(event, inbound.Response):
		return respond(event)
	if seen_before(source.service, source.update_id(update)):
		print(f"[{source.service}]: update {source.update_id(update)} seen already, not run again", file=sys.stderr)
		return respond(inbound.OK)
	dispatch(event)
	return respond(inbound.OK)

def dispatch(event):
	"""Hand a message or a button press to lib/worker, in a thread of its own."""
	if isinstance(event, inbound.Press):
		print(f"[{event.service.capitalize()} button]:", event.user, "chat", event.chat_id, event.data, file=sys.stderr)
		target = worker.process_callback
		args = (event.service, event.press_id, event.chat_id, event.message_id, event.data)
	else:
		if config.prefs.debug:
			print(f"[{event.service.capitalize()}]:", event.user, event.text, file=sys.stderr)
		target = worker.process_request
		args = (event.service, event.chat_id, event.user, event.text, event.bot_name, event.user_name)
	threading.Thread(target=target, args=args).start()

def git_version(checkout=None):
	"""Short hash of the checked-out commit, read straight from the .git directory: no git binary to run, and no "dubious
	ownership" refusal when the service user does not own the checkout. 'unknown' when it cannot be read."""
	try:
		git = Path(checkout or config.REPO_DIR) / '.git'
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
_signal_work = threading.Lock() # one signal's work at a time: a second reload waits for the first

def in_thread(work):
	"""A signal handler that runs `work` in a thread of its own and returns at once: a handler must not wait on the
	network, nor on a lock that the code it interrupted may hold."""
	def run():
		"""The work, once any other signal's is done."""
		with _signal_work:
			work()
	return lambda *args: threading.Thread(target=run, daemon=True).start()

def reload_all(*args):
	"""SIGHUP: re-read preferences.conf and, if the scheduler is running, schedule.cron. Each reports its own errors; a bad
	preferences.conf leaves the running config untouched."""
	try:
		changes = config.reload()
		for change in changes:
			print('config:', change, file=sys.stderr)
		print(f"config: reloaded {config.preferences_path}, {len(changes)} change{'' if len(changes) == 1 else 's'}", file=sys.stderr)
	except config.ConfigError as e:
		config.print_errors(e)
	if scheduler:
		scheduler.reload()

def flush_cache(*args):
	"""SIGUSR1 (`systemctl kill -s USR1 finbot`): delete the cache and keep the state (watchlist, seen trades, ratings, schedule).
	Yahoo's cookie and crumb belong together, so they go while nothing is renewing them; the Sharesight caches refill at once."""
	try:
		with yahoo._auth:
			removed = cleanup.run(days=0)
		sharesight.wake()
		print(f"cache: flushed {removed} file{'' if removed == 1 else 's'} from {config.env.cache_dir}", file=sys.stderr)
	except Exception as e:
		print('ERROR', delivery.error_line(e, 'cache flush'), file=sys.stderr)

if __name__ == '__main__':
	print(f'Starting finbot {git_version()}', file=sys.stderr)
	try:
		config.check_startup_environment()
	except config.ConfigError as e:
		config.print_errors(e)
		sys.exit(1)
	for line in config.startup_report():
		print('config:', line, file=sys.stderr)
	for line in config.startup_warnings():
		print('ERROR config:', line, file=sys.stderr)
	if os.getuid() == 0:
		print("Running as superuser. This is not recommended.", file=sys.stderr)
	if config.env.scheduler: # read before anything else happens: an impossible time in it stops the start
		scheduler = jobs.Scheduler(lambda: config.data_file('schedule.cron'))
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
	render.render_off_hub() # charts drawn in a thread of their own: no chat waits while another's chart is drawn
	httpd = pywsgi.WSGIServer((config.env.ip, config.env.port), main)
	httpd.secure_repr = False if config.prefs.debug else None
	print(f'Opening socket on http://{config.env.ip}:{config.env.port}', file=sys.stderr)
	if config.env.telegramBotToken and config.env.telegramOutgoingWebhook:
		try:
			inbound.TELEGRAM.bot_name = telegram.register() # here only: the job processes import lib.telegram too
		except Exception as e:
			print('ERROR', delivery.error_line(e, 'telegram webhook'), file=sys.stderr)
			sys.exit(1)
	if config.env.telegramBotToken:
		threading.Thread(target=worker.refresh_keyboards, daemon=True).start() # stale DM keyboards, in the background
	if config.env.sharesight_auth.get('client_id'):
		threading.Thread(target=sharesight.keep_warm, daemon=True).start() # keep the portfolio list and holdings report cached, while cache is on
	if scheduler:
		jobs.current = scheduler # for the .jobs chat command
		threading.Thread(target=scheduler.run_forever, daemon=True).start() # the scheduled reports, formerly cron jobs
	# Startup is done. systemctl reload finbot: pick up edited preferences.conf and schedule.cron
	gevent.signal_handler(signal.SIGHUP, in_thread(reload_all))
	gevent.signal_handler(signal.SIGUSR1, in_thread(flush_cache)) # systemctl kill -s USR1 finbot: delete the cache
	try:
		httpd.serve_forever()
	except OSError as e:
		print(e, file=sys.stderr)
		sys.exit(1)
