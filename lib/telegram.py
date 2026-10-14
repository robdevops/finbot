import json
import sys
from lib.config import *
from lib import net

def call(method, **kwargs):
	"""POST a Bot API method and return its result. Raises RuntimeError with Telegram's description when it answers not ok."""
	response = net.post(webhooks['telegram'] + method, timeout=config_http_timeout, **kwargs)
	try:
		output = response.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Telegram {method}: {output.get('description') or response.status_code}")
	return output['result']

def setWebhook():
	print("registering", config_telegramOutgoingWebhook, file=sys.stderr)
	params = {'url': config_telegramOutgoingWebhook, "allowed_updates": json.dumps(['message', 'callback_query']), 'secret_token': config_telegramOutgoingToken}
	return call('setWebhook', params=params)

def delWebhook():
	print("deregistering", config_telegramOutgoingWebhook, file=sys.stderr)
	return call('setWebhook', params={'url': ''}) # unsubscribe

def getMe():
	return call('getMe')

def register():
	"""Called once by bot.py as it starts, never on import (the job processes and the tests import this module too): unregister and
	register the webhook again, which wakes up a stale connection on Telegram's side, then return the bot's @username. Raises
	RuntimeError, or a requests error, if any of the three calls fails."""
	delWebhook()
	setWebhook()
	return '@' + getMe()['username']

def pinChatMessage(chat_id, message_id):
	telegram_url = webhooks['telegram'] + 'pinChatMessage'
	payload = {
		'chat_id': chat_id,
		'message_id': message_id,
		'disable_notification': True # no "pinned a message" notification
	}
	response = net.post(telegram_url, json=payload, timeout=config_http_timeout)
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
		net.post(webhooks['telegram'] + 'answerCallbackQuery', json=payload, timeout=config_http_timeout)
	except Exception as e:
		print("answerCallbackQuery failed:", net.redact(e), file=sys.stderr)

