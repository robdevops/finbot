import json
import time
import requests
import sys

from lib.config import *
from lib import util

def write(service, url, payload, slackchannel=None, message_id=None):
	headers = {'Content-type': 'application/json'}
	payload = {'text': payload}
	if 'slack.com' in url:
		headers['unfurl_links'] = 'false'
		headers['unfurl_media'] = 'false'
		if slackchannel:
			headers['Authorization'] = 'Bearer ' + config_slackBotToken
			payload['channel'] = slackchannel
			if message_id:
				payload['thread_ts'] = message_id
				payload['reply_broadcast'] = 'true'
	elif 'api.telegram.org' in url:
		payload['parse_mode'] = 'HTML'
		payload['disable_web_page_preview'] = 'true'
		payload['disable_notification'] = 'true'
		payload['allow_sending_without_reply'] = 'true'
		payload['reply_to_message_id'] = message_id
	try:
		r = requests.post(url, headers=headers, json=payload, timeout=config_http_timeout)
	except:
		print("Failure executing request:", url, headers, payload, file=sys.stderr)
		return None
	if r.status_code == 200:
		print(r.status_code, "OK outbound to", service)
	else:
		print(r.status_code, "error outbound to", service, file=sys.stderr)
		return None

def payload_wrapper(service, url, payload, slackchannel=None, message_id=None):
	if not payload:
		print(service + ": Nothing to send")
	else:
		payload_string = '\n'.join(payload)
		print("Preparing outbound to", service, str(len(payload_string)), "bytes")
		if debug:
			print("Payload: " + payload_string)
		def chunkLooper():
			chunks = util.chunker(payload, config_chunk_maxlines)
			for idx, chunk in enumerate(chunks):
				idx > 0 and time.sleep(1)
				payload_chunk = '\n'.join(chunk)
				write(service, url, payload_chunk)
		if service == 'discord' and len(payload_string) > 2000:
			print(service, "payload is over 2,000 bytes. Splitting.")
			chunkLooper()
		elif service != 'discord' and len(payload_string) > 4000:
			print(service, "payload is over 4,000 bytes. Splitting.")
			chunkLooper()
		else:
			write(service, url, payload_string, slackchannel, message_id)

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

def strike(message, service):
	if service == 'telegram':
		message = '<s>' + message + '</s>'
	elif service == 'slack':
		message = '~' + message + '~'
	elif service == 'discord':
		message = '~~' + message + '~~'
	return message

def sendPhoto(chat_id, image_data, caption, service, message_id=None):
	if service == 'telegram':
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
		files = {"photo": ('image.png', image_data)}
	elif service == 'slack':
		url = 'https://slack.com/api/files.upload'
		headers = {'Authorization': 'Bearer ' + config_slackBotToken}
		data = {'channels': chat_id, 'initial_comment': caption}
		if message_id:
			data['thread_ts'] = message_id
			data['reply_broadcast'] = 'true'
		files = {'file': ('image.png', image_data)}
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
	else:
		print(r.status_code, f"error {service} sendPhoto", r.reason, caption, file=sys.stderr)
		return None

