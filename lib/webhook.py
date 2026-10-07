import json
import time
import requests
import re
from itertools import batched
import sys
import traceback

from lib.config import *
from lib import util

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
		r = requests.post(url, headers=headers, json=payload, timeout=config_http_timeout)
	except:
		print("Failure executing request:", url, headers, payload, file=sys.stderr)
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
	text = re.sub(r'bot\d+:[\w-]+', 'bot<redacted>', text) # Telegram tokens appear in request URLs
	text = re.sub(r'(?i)(token|crumb|auth\w*|key)=[^&\s]+', r'\1=<redacted>', text)
	text = ' '.join(text.split())
	if len(text) > limit:
		text = text[:limit - 1] + '…'
	return f"⚠️ {context}: {text}" if context else f"⚠️ {text}"

def report_error(e, service=None, chat_id=None, context=None):
	"""Send a one-line error summary to the initiating chat, else to every default channel in .env.
	Never raises: error reporting must not become a second failure."""
	try:
		line = error_line(e, context)
		print(line, file=sys.stderr)
		if isinstance(e, BaseException):
			traceback.print_exception(e, file=sys.stderr)
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
					write(svc, url, line, chat)
				except Exception as send_error:
					print("Failed to report error to", svc, ":", send_error, file=sys.stderr)
	except Exception as reporting_error:
		print("Failed to report error:", reporting_error, file=sys.stderr)

def guarded(context, func, *args, **kwargs):
	"""Run a cron entry point; on failure report one line to the default channel and exit non-zero."""
	try:
		return func(*args, **kwargs)
	except Exception as e:
		report_error(e, context=context)
		sys.exit(1)

def payload_wrapper(service, url, payload, chat_id=None, message_id=None, reply_markup=None):
	"""Returns a list with the response of each message sent (several if the payload was chunked)."""
	if not payload:
		print(service + ": Nothing to send") # informational
	else:
		payload = [str(line) for line in payload]
		payload_string = '\n'.join(payload)
		print("Preparing outbound to", service, str(len(payload_string)), "bytes")
		print("Payload: " + payload_string) if debug else None
		def chunkLooper():
			chunks = list(batched(payload, config_chunk_maxlines))
			results = []
			for idx, chunk in enumerate(chunks):
				idx > 0 and time.sleep(0.5)
				payload_chunk = '\n'.join(chunk)
				last = idx == len(chunks) - 1
				results.append(write(service, url, payload_chunk, chat_id, reply_markup=reply_markup if last else None))
			return results
		if service == 'discord' and len(payload_string) > 2000:
			print(service, "payload is over 2,000 bytes. Splitting.")
			return chunkLooper()
		elif service != 'discord' and len(payload_string) > 4096:
			print(service, "payload is over 4,096 bytes. Splitting.")
			return chunkLooper()
		else:
			return [write(service, url, payload_string, chat_id, message_id, reply_markup)]

def bold(message, service):
	if service == 'telegram':
		message = '<b>' + message + '</b>'
	elif service == 'slack':
		message = '*' + message + '*'
	elif service == 'discord':
		message = '**' + message + '**'
	return message

def italic(message, service):
	if service == 'telegram':
		message = '<i>' + message + '</i>'
	elif service == 'slack':
		message = '_' + message + '_'
	elif service == 'discord':
		message = '_' + message + '_'
	return message

italics = italic

def strike(message, service):
	if service == 'telegram':
		message = '<s>' + message + '</s>'
	elif service == 'slack':
		message = '~' + message + '~'
	elif service == 'discord':
		message = '~~' + message + '~~'
	return message

strikethrough = strike

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

def sendPhoto(chat_id, image_data, caption, service, message_id=None, reply_markup=None):
	if service == 'telegram':
		caption = fit_caption(caption)
		url = webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
		headers = {}
		data = {
			'disable_notification': True,
			'chat_id': chat_id,
			'caption': caption,
			'parse_mode': 'HTML',
			'disable_web_page_preview': True,
			'allow_sending_without_reply': True,
			'reply_to_message_id': message_id}
		if reply_markup:
			data['reply_markup'] = json.dumps(reply_markup) # inline keyboard (Telegram only)
		files = {"photo": ('image.png', image_data)}
	elif service == 'slack':
		url = 'https://slack.com/api/files.upload'
		headers = {'Authorization': 'Bearer ' + config_slackBotToken}
		data = {'channels': chat_id, 'initial_comment': caption}
		if message_id:
			data['thread_ts'] = message_id
			data['reply_broadcast'] = 'true'
		files = {'file': ('image.png', image_data)}
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	try:
		r = requests.post(url, data=data, headers=headers, files=files, timeout=config_http_timeout)
	except Exception as e:
	  print("Failure executing request:", url, data, str(e))
	  return None
	if r.status_code == 200:
		print(r.status_code, f"OK {service} sendPhoto", caption)
		output = r.json()
		if not output['ok']:
			if service == 'telegram':
				print(output['error_code'], output['description'], file=sys.stderr)
			elif service == 'slack':
				print(output['error'], file=sys.stderr)
		return output
	else:
		print(r.status_code, f"error {service} sendPhoto", r.reason, r.text[:300], caption, file=sys.stderr)
		return None

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
		r = requests.post(url, data=data, files={'photo': ('image.png', image_data)}, timeout=config_http_timeout)
		output = r.json()
	except Exception as e:
		print("Failure executing editMessageMedia:", str(e), file=sys.stderr)
		return None
	if not output.get('ok'):
		description = output.get('description', r.reason)
		if 'not modified' not in description: # pressing the active period again is harmless
			print(output.get('error_code'), description, file=sys.stderr)
			raise RuntimeError(f"Telegram: {description}")
	return output

def pleaseHold(action, service, chat_id):
	"""typing notify. I am run in a thread and repeated every 5 seconds"""
	if service == 'telegram':
		url = webhooks['telegram'] + "sendChatAction?chat_id=" + str(chat_id)
		headers = {}
		data = {
			'chat_id': chat_id,
			'action': action
		}
		try:
			r = requests.post(url, data=data, headers=headers, timeout=config_http_timeout)
		except Exception as e:
		  print("Failure executing request:", url, data, str(e))
		  return None
		if r.status_code == 200:
			print(r.status_code, "OK typing indicator to", service, file=sys.stderr)
		else:
			print(r.status_code, "error typing indicator to", service, file=sys.stderr)
		return None
	else:
		payload_string = "this might take a moment"
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
		write(service, url, payload_string, chat_id, message_id=None)
