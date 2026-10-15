import json
import sys
from lib import config
from lib import net

def call(method, **kwargs):
	"""POST a Bot API method and return its result. Raises RuntimeError with Telegram's description when it answers not ok."""
	response = net.post(config.env.webhooks['telegram'] + method, timeout=config.prefs.http_timeout, **kwargs)
	try:
		output = response.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Telegram {method}: {output.get('description') or response.status_code}")
	return output['result']

def try_call(method, **kwargs):
	"""call(), for a call whose failure must not stop what the bot is doing: a failure is only logged (and None returned)."""
	try:
		return call(method, **kwargs)
	except Exception as e:
		print(f"Telegram {method} failed:", net.redact(e), file=sys.stderr)

def setWebhook():
	"""Have Telegram post updates (messages and button presses) to telegramOutgoingWebhook, signed with
	telegramOutgoingToken."""
	print("registering", config.env.telegramOutgoingWebhook, file=sys.stderr)
	params = {'url': config.env.telegramOutgoingWebhook, "allowed_updates": json.dumps(['message', 'callback_query']), 'secret_token': config.env.telegramOutgoingToken}
	return call('setWebhook', params=params)

def delWebhook():
	"""Have Telegram stop posting updates."""
	print("deregistering", config.env.telegramOutgoingWebhook, file=sys.stderr)
	return call('setWebhook', params={'url': ''}) # unsubscribe

def getMe():
	"""The bot's own account: its username is the bot's name in chats."""
	return call('getMe')

def register():
	"""Called once by bot.py as it starts, never on import (the job processes and the tests import this module too): unregister and
	register the webhook again, which wakes up a stale connection on Telegram's side, then return the bot's @username. Raises
	RuntimeError, or a requests error, if any of the three calls fails."""
	delWebhook()
	setWebhook()
	return '@' + getMe()['username']

def pinChatMessage(chat_id, message_id):
	"""Pin a message, without the "pinned a message" notification. A failure is only logged: the message is there either way."""
	try_call('pinChatMessage', json={'chat_id': chat_id, 'message_id': message_id, 'disable_notification': True})

def answerCallbackQuery(callback_query_id, text=None):
	"""Acknowledge a button press (stops the client's loading spinner), with `text` as a toast. A failure is only logged."""
	try_call('answerCallbackQuery', json={'callback_query_id': callback_query_id} | ({'text': text} if text else {}))

