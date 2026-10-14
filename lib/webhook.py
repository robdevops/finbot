import html
import json
import time
import requests
import re
from itertools import batched
import sys
import traceback

from lib.config import *
from lib import net

def write(service, url, payload_string, chat_id=None, message_id=None, reply_markup=None):
	headers = {'Content-type': 'application/json'}
	payload = {'text': payload_string}
	if 'slack.com' in url:
		headers['unfurl_links'] = 'false'
		headers['unfurl_media'] = 'false'
		if chat_id:
			headers['Authorization'] = 'Bearer ' + config_slackBotToken
			payload['channel'] = chat_id
			if message_id:
				payload['thread_ts'] = message_id
				payload['reply_broadcast'] = 'true'
	elif 'api.telegram.org' in url:
		payload['parse_mode'] = 'HTML'
		payload['disable_web_page_preview'] = 'true'
		payload['disable_notification'] = 'true'
		payload['allow_sending_without_reply'] = 'true'
		payload['reply_to_message_id'] = message_id
		if reply_markup:
			payload['reply_markup'] = reply_markup # keyboard (Telegram only)
	try:
		r = net.post(url, headers=headers, json=payload, timeout=config_http_timeout)
	except Exception as e:
		print("Failure sending to", service + ":", net.redact(e), file=sys.stderr)
		return None
	if r.status_code == 200:
		print(r.status_code, "OK outbound to", service, file=sys.stderr)
		try:
			return r.json()
		except ValueError:
			return {}
	else:
		print(r.status_code, "error outbound to", service, file=sys.stderr)
		return None

def chat_url(service, chat_id):
	"""Outbound URL for posting to a chat."""
	if service == 'slack':
		return 'https://slack.com/api/chat.postMessage'
	if service == 'telegram':
		return webhooks['telegram'] + 'sendMessage?chat_id=' + str(chat_id)
	return webhooks.get(service)

def error_line(e, context=None, limit=200):
	"""One-line, secret-free summary of an exception (or string)."""
	if isinstance(e, BaseException):
		text = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
	else:
		text = str(e)
	text = ' '.join(net.redact(text).split())
	if len(text) > limit:
		text = text[:limit - 1] + '…'
	return f"⚠️ {context}: {text}" if context else f"⚠️ {text}"

def report_error(e, service=None, chat_id=None, context=None):
	"""Send a one-line error summary to the initiating chat, else to every default channel in finbot.env. The line is escaped for
	Telegram (sent as HTML, which refuses a stray < such as the one in <redacted>) and Slack (which asks for the same escapes).
	Never raises: error reporting must not become a second failure."""
	try:
		line = error_line(e, context)
		print(line, file=sys.stderr)
		if isinstance(e, BaseException):
			print(net.redact(''.join(traceback.format_exception(e))), end='', file=sys.stderr) # request errors carry their URL
		if service and chat_id:
			targets = [(service, chat_url(service, chat_id))]
			chat = chat_id
		else:
			targets = []
			for svc, url in webhooks.items():
				if svc == 'telegram':
					if not config_telegramChatID:
						continue
					url = chat_url(svc, config_telegramChatID)
				targets.append((svc, url))
			chat = None
		for svc, url in targets:
			if url:
				try:
					write(svc, url, line if svc == 'discord' else html.escape(line, quote=False), chat)
				except Exception as send_error:
					print("Failed to report error to", svc, ":", send_error, file=sys.stderr)
	except Exception as reporting_error:
		print("Failed to report error:", reporting_error, file=sys.stderr)

def guarded(context, func, *args, exit=True, **kwargs):
	"""Run a scheduled entry point; on failure report one line to the default channel, then exit non-zero (exit=True, for the
	command line) or just return None (exit=False, when the bot runs it in-process). A SystemExit inside counts as a failure."""
	try:
		return func(*args, **kwargs)
	except (Exception, SystemExit) as e:
		report_error(e, context=context)
		if exit:
			sys.exit(1)

def cli(script, job, handler, argv=None):
	"""Command line entry point of a report script: parse its arguments with `job(argv) -> (label, kwargs)`, print the usage on
	a bad argument, else run the handler guarded."""
	try:
		label, kwargs = job(sys.argv[1:] if argv is None else argv)
	except ValueError as e:
		print("Usage:", script, e, file=sys.stderr)
		sys.exit(1)
	guarded(label, handler, **kwargs)

def payload_wrapper(service, url, payload, chat_id=None, message_id=None, reply_markup=None):
	"""Returns a list with the response of each message sent (several if the payload was chunked)."""
	if not payload:
		print(service + ": Nothing to send") # informational
		return None
	payload = [str(line) for line in payload]
	payload_string = '\n'.join(payload)
	print("Preparing outbound to", service, str(len(payload_string)), "bytes")
	print("Payload: " + payload_string) if debug else None
	limit = 2000 if service == 'discord' else 4096
	if len(payload_string) <= limit:
		return [write(service, url, payload_string, chat_id, message_id, reply_markup)]
	print(service, f"payload is over {limit:,} bytes. Splitting.")
	chunks = list(batched(payload, config_chunk_maxlines))
	results = []
	for idx, chunk in enumerate(chunks):
		if idx:
			time.sleep(0.5)
		last = idx == len(chunks) - 1
		results.append(write(service, url, '\n'.join(chunk), chat_id, reply_markup=reply_markup if last else None))
	return results

MARKUP = { # how each service marks text up: style -> service -> (before, after)
	'bold': {'telegram': ('<b>', '</b>'), 'slack': ('*', '*'), 'discord': ('**', '**')},
	'italic': {'telegram': ('<i>', '</i>'), 'slack': ('_', '_'), 'discord': ('_', '_')},
	'strike': {'telegram': ('<s>', '</s>'), 'slack': ('~', '~'), 'discord': ('~~', '~~')},
}

def _styled(style, message, service):
	if service not in MARKUP[style]:
		return message
	before, after = MARKUP[style][service]
	return before + message + after

def bold(message, service):
	return _styled('bold', message, service)

def italic(message, service):
	return _styled('italic', message, service)

italics = italic

def strike(message, service):
	return _styled('strike', message, service)


def fit_caption(caption, limit=1024):
	"""Telegram rejects photo captions over 1024 visible characters. Keep whole lines that fit and say how many were left out."""
	def visible(text):
		return len(re.sub(r'<[^>]+>', '', text))
	if visible(caption) <= limit:
		return caption
	lines = caption.split('\n')
	kept = []
	for line in lines:
		more = len(lines) - len(kept) - 1
		note = f"\n…and {more} more in the chart"
		if visible('\n'.join(kept + [line])) + len(note) > limit:
			break
		kept.append(line)
	return '\n'.join(kept) + f"\n…and {len(lines) - len(kept)} more in the chart"

MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows

def takes_charts(service, reply=True):
	"""Whether a report to `service` can carry a chart image: on Telegram always; on Slack in a reply to a chat (`reply`), uploaded
	into its channel with the bot token, but not in a scheduled report, which goes through the incoming webhook and takes text only;
	never on Discord. Elsewhere a report goes out as text."""
	return service == 'telegram' or (service == 'slack' and reply and bool(config_slackBotToken))

def telegram_photo(chat_id, image_data, caption, message_id=None, reply_markup=None):
	"""sendPhoto, the report as its caption (trimmed to fit). Telegram's answer, MAYBE_SENT, or None if it was refused."""
	url = webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
	data = {
		'disable_notification': True,
		'chat_id': chat_id,
		'caption': fit_caption(caption),
		'parse_mode': 'HTML',
		'disable_web_page_preview': True,
		'allow_sending_without_reply': True,
		'reply_to_message_id': message_id}
	if reply_markup:
		data['reply_markup'] = json.dumps(reply_markup) # inline keyboard (Telegram only)
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	try:
		r = net.post(url, data=data, files={"photo": ('image.png', image_data)}, timeout=config_http_timeout)
	except requests.exceptions.ReadTimeout as e:
		print("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
		return MAYBE_SENT
	except Exception as e:
		print("Telegram sendPhoto failed:", net.redact(e), file=sys.stderr)
		return None
	try:
		output = r.json()
	except ValueError:
		output = {}
	if r.status_code == 200 and output.get('ok'):
		print(r.status_code, "OK telegram sendPhoto", data['caption'])
		return output
	print(r.status_code, "error telegram sendPhoto", output.get('error_code'), output.get('description') or r.text[:300], file=sys.stderr)
	return None

def slack_api(method, **data):
	"""POST a Slack Web API method as the bot, form-encoded, and return its answer. Raises RuntimeError with Slack's error if not ok."""
	r = net.post('https://slack.com/api/' + method, headers={'Authorization': 'Bearer ' + config_slackBotToken}, data=data, timeout=config_http_timeout)
	try:
		output = r.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Slack {method}: {output.get('error') or r.status_code}")
	return output

def slack_photo(chat_id, image_data, caption, message_id=None):
	"""Upload the chart into a Slack channel with the report as its message, the way Slack takes files since it retired files.upload:
	ask for an upload URL, send the bytes there, then complete the upload into the channel (the bot needs the files:write and
	files:read scopes). Slack's answer, MAYBE_SENT, or None if a step failed."""
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	data = image_data.read() if hasattr(image_data, 'read') else bytes(image_data)
	try:
		ticket = slack_api('files.getUploadURLExternal', filename='chart.png', length=len(data))
		r = net.post(ticket['upload_url'], data=data, timeout=config_http_timeout)
		if r.status_code != 200:
			raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
		share = {'files': json.dumps([{'id': ticket['file_id']}]), 'channel_id': chat_id, 'initial_comment': caption}
		if message_id:
			share['thread_ts'] = message_id
		try:
			output = slack_api('files.completeUploadExternal', **share)
		except requests.exceptions.ReadTimeout as e:
			print("Slack files.completeUploadExternal timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
	except Exception as e:
		print("Slack chart upload failed:", net.redact(e), file=sys.stderr)
		return None
	print("OK slack chart upload to", chat_id, file=sys.stderr)
	return output

def sendPhoto(chat_id, image_data, caption, service, message_id=None, reply_markup=None):
	"""The chart, with the report as its caption: on Telegram, or uploaded into the Slack channel of a reply. Where a chart cannot go
	(takes_charts), or the service refuses it, the report is sent as text instead, without the chart's buttons, so it does not vanish
	with its chart; but not after a read timeout on the request that posts it, when the chart may have arrived after all."""
	output = None
	chartable = takes_charts(service, reply=bool(chat_id))
	if service == 'telegram':
		output = telegram_photo(chat_id, image_data, caption, message_id, reply_markup)
	elif chartable:
		output = slack_photo(chat_id, image_data, caption, message_id)
	if output is MAYBE_SENT:
		return None
	if output:
		return output
	if chartable:
		print("chart not sent, sending the report as text", file=sys.stderr)
	return payload_wrapper(service, chat_url(service, chat_id) if chat_id else webhooks.get(service), caption.split('\n'), chat_id, message_id)

def editMessageText(chat_id, message_id, text, reply_markup=None):
	"""Telegram: replace a text message's text and buttons in place. Returns None if it could not be edited."""
	payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
	if reply_markup is not None:
		payload['reply_markup'] = reply_markup
	try:
		output = net.post(webhooks['telegram'] + 'editMessageText', json=payload, timeout=config_http_timeout).json()
	except Exception as e:
		print("Failure executing editMessageText:", net.redact(e), file=sys.stderr)
		return None
	if not output.get('ok'):
		print(output.get('error_code'), output.get('description'), file=sys.stderr)
		return None
	return output

def editMessageMedia(chat_id, message_id, image_data, caption, reply_markup=None):
	"""Telegram: replace a photo message's image and caption in place."""
	url = webhooks['telegram'] + 'editMessageMedia'
	caption = fit_caption(caption)
	media = {'type': 'photo', 'media': 'attach://photo', 'caption': caption, 'parse_mode': 'HTML'}
	data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media)}
	if reply_markup:
		data['reply_markup'] = json.dumps(reply_markup)
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	try:
		r = net.post(url, data=data, files={'photo': ('image.png', image_data)}, timeout=config_http_timeout)
		output = r.json()
	except Exception as e:
		print("Failure executing editMessageMedia:", net.redact(e), file=sys.stderr)
		return None
	if not output.get('ok'):
		description = output.get('description', r.reason)
		if 'not modified' not in description: # pressing the active period again is harmless
			print(output.get('error_code'), description, file=sys.stderr)
			raise RuntimeError(f"Telegram: {description}")
	return output

def pleaseHold(action, service, chat_id):
	"""Telegram's typing notice ("typing…" for a few seconds). worker.TypingIndicator repeats it every 7 seconds while a command
	works, on Telegram only: the other services have no such notice."""
	if service != 'telegram':
		return None
	url = webhooks['telegram'] + "sendChatAction?chat_id=" + str(chat_id)
	data = {
		'chat_id': chat_id,
		'action': action
	}
	try:
		r = net.post(url, data=data, timeout=config_http_timeout)
	except Exception as e:
		print("Typing indicator failed:", net.redact(e), file=sys.stderr)
		return None
	if r.status_code == 200:
		print(r.status_code, "OK typing indicator to", service, file=sys.stderr)
	else:
		print(r.status_code, "error typing indicator to", service, file=sys.stderr)
	return None
