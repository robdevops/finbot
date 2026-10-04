#!/usr/bin/env python3

import gevent.monkey
gevent.monkey.patch_all()
import json, os, re, sys
from gevent import pywsgi
import threading
from urllib.parse import urlparse

from lib.config import *
from lib import worker
from lib import charts
from lib import webhook
if config_telegramBotToken:
	from lib import telegram
	botName = telegram.botName

def main(environ, start_response):
	"""WSGI entry point. Never lets an exception escape: failures are reported as one line to the default channel."""
	try:
		return handle(environ, start_response)
	except Exception as e:
		webhook.report_error(e, context=environ.get('PATH_INFO', 'bot'))
		try:
			start_response('500 Internal Server Error', [('Content-type', 'text/plain')], sys.exc_info())
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
	request_body = environ['wsgi.input'].read()
	user=''
	userRealName=''
	# prepare response
	status = '200 OK'
	headers = [('Content-type', 'application/json')]
	start_response(status, headers)
	# process request
	uri = environ['PATH_INFO']
	inbound = json.loads(request_body)
	print_headers() if config_print_headers else None
	#print_body() if debug else None
	if config_telegramOutgoingWebhook and uri == urlparse(config_telegramOutgoingWebhook).path:
		service = 'telegram'
		global botName
		if 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' not in environ:
			print_headers()
			print("Fatal:", service, "authorisation header not present", file=sys.stderr)
			return [b'<h1>Unauthorized</h1>']
		if environ['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] != config_telegramOutgoingToken:
			print_headers()
			print("Fatal: Telegram authorisation header is present but incorrect. Expected:", config_telegramOutgoingToken, file=sys.stderr)
			return [b'<h1>Unauthorized</h1>']
		if "callback_query" in inbound: # chart period buttons
			cq = inbound["callback_query"]
			cq_message = cq.get("message")
			if not cq_message or not cq.get("data"):
				return [b'Unsupported']
			threading.Thread(target=worker.process_callback, args=('telegram', cq["id"], str(cq_message["chat"]["id"]), str(cq_message["message_id"]), cq["data"])).start()
			return [b'']
		if "message" not in inbound:
			return [b'Unsupported']
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
		else:
			print(f"[{service}]: unhandled: 'message' without 'text/photo'", file=sys.stderr)
			return [b'<h1>Unhandled</h1>']
	elif config_slackOutgoingWebhook and uri == urlparse(config_slackOutgoingWebhook).path:
		service = 'slack'
		if 'token' not in inbound:
			print("warning: Slack authorisation field not present", file=sys.stderr)
			print_body()
			return [b'<h1>Unauthorized</h1>']
		if inbound['token'] == config_slackOutgoingToken:
			print("Incoming Slack request authenticated")
		else:
			print("Slack auth incorrect. Expected:", config_slackOutgoingToken, "Got:", inbound['token'], file=sys.stderr)
			print_body()
			return [b'<h1>Unauthorized</h1>']
		if 'type' not in inbound:
			print(f"[{service}]: unhandled: no 'type'", file=sys.stderr)
			return [b'Unhandled']
		if inbound['type'] == 'url_verification':
			response = json.dumps({"challenge": inbound["challenge"]})
			print("replying with", response, file=sys.stderr)
			response = bytes(response, "utf-8")
			return [response]
		if inbound['type'] == 'event_callback':
			if inbound["event"]["type"] not in ('message', 'app_mention') or "text" not in inbound['event']:
				print(f"[{service}]: unhandled event callback type", inbound["event"]["type"], file=sys.stderr)
				return [b'<h1>Unhandled</h1>']
			message_id = str(inbound["event"]["ts"])
			message = inbound['event']['text']
			message = re.sub(r'<http://.*\|([\w\.]+)>', r'\g<1>', message) # <http://dub.ax|dub.ax> becomes dub.ax
			message = re.sub(r'<(@[\w\.]+)>', r'\g<1>', message) # <@QWERTY> becomes @QWERTY
			user = userRealName = '<@' + inbound['event']['user'] + '>' # ZXCVBN becomes <@ZXCVBN>
			botName = '@' + inbound['authorizations'][0]['user_id'] # QWERTY becomes @QWERTY
			chat_id = inbound['event']['channel']
			print(f"[{service}]:", user, message, sys.stderr) if debug else None
			# this condition spawns a worker before returning
		else:
			print(f"[{service}]: unhandled 'type'", file=sys.stderr)
			return [b'<h1>Unhandled</h1>']
	else:
		print("Unknown URI", uri, file=sys.stderr)
		status = "404 Not Found"
		start_response(status, headers)
		return [b'<h1>404</h1>']

	def runWorker():
		worker.process_request(service, chat_id, user, message, botName, userRealName, message_id)

	# process in a background thread so we don't keep the requesting client waiting
	t = threading.Thread(target=runWorker)
	t.start()

	# Return an empty response to the client
	return [b'']

if __name__ == '__main__':
	if os.getuid() == 0:
		print("Running as superuser. This is not recommended.", file=sys.stderr)
	httpd = pywsgi.WSGIServer((config_ip, config_port), main)
	httpd.secure_repr = False if debug else None
	print(f'Opening socket on http://{config_ip}:{config_port}', file=sys.stderr)
	if config_telegramBotToken:
		threading.Thread(target=charts.refresh_keyboards, daemon=True).start() # update stale DM keyboards in the background
	try:
		httpd.serve_forever()
	except OSError as e:
		print(e, file=sys.stderr)
		sys.exit(1)
