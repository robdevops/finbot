import concurrent.futures
import json
import requests
import sys
from lib.config import *

def setWebhook():
	telegram_url = webhooks['telegram'] + 'setWebhook'
	print("registering", config_telegramOutgoingWebhook, file=sys.stderr)
	params = {'url': config_telegramOutgoingWebhook, "allowed_updates": json.dumps(['message', 'callback_query']), 'secret_token': config_telegramOutgoingToken}
	response = requests.post(telegram_url, params=params, timeout=config_http_timeout)
	print(response.text)

def delWebhook():
	telegram_url = webhooks['telegram'] + 'setWebhook'
	print("deregistering", config_telegramOutgoingWebhook, file=sys.stderr)
	params = {'url': ''} # unsubscribe
	response = requests.post(telegram_url, params=params, timeout=config_http_timeout)
	print(response.text)

def getMe():
	telegram_url = webhooks['telegram'] + 'getMe'
	response = requests.post(telegram_url, timeout=config_http_timeout)
	return response.json()['result']

if config_telegramBotToken:
	delWebhook()
	with concurrent.futures.ThreadPoolExecutor() as executor:
		executor.submit(setWebhook)
		#executor.submit(setMyCommands)
		thread = executor.submit(getMe)
		botName = '@' + thread.result()['username']

def pinChatMessage(chat_id, message_id):
	telegram_url = webhooks['telegram'] + 'pinChatMessage'
	payload = {
		'chat_id': chat_id,
		'message_id': message_id,
		'disable_notification': True # no "pinned a message" notification
	}
	response = requests.post(telegram_url, json=payload, timeout=config_http_timeout)
	output = response.json()
	if not output.get('ok'):
		print("pinChatMessage failed:", output.get('description'), file=sys.stderr)
	return output.get('result')

def answerCallbackQuery(callback_query_id, text=None):
	"""Acknowledge a button press (stops the client's loading spinner)."""
	payload = {'callback_query_id': callback_query_id}
	if text:
		payload['text'] = text
	try:
		requests.post(webhooks['telegram'] + 'answerCallbackQuery', json=payload, timeout=config_http_timeout)
	except Exception as e:
		print("answerCallbackQuery failed:", e, file=sys.stderr)

#def unpinChatMessage():
#	telegram_url = webhooks['telegram'] + 'unpinChatMessage'

