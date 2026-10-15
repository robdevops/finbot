import json
import sys
from lib import config
from lib import net

def call(method, **kwargs):
	"""POST a Bot API method and return its result. Raises RuntimeError with Telegram's reason when it is not ok."""
	response = net.post(config.env.telegram_api + method, **kwargs)
	try:
		output = response.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Telegram {method}: {output.get('description') or response.status_code}")
	return output['result']

def try_call(method, **kwargs):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, **kwargs)
	except Exception as e:
		print(f"Telegram {method} failed:", net.redact(e), file=sys.stderr)

def setWebhook():
	"""Have Telegram post messages and button presses to telegramOutgoingWebhook, signed with telegramOutgoingToken. The
	log does not show the URL: its path is a secret."""
	print("telegram: setting the webhook (telegramOutgoingWebhook)", file=sys.stderr)
	params = {'url': config.env.telegramOutgoingWebhook, "allowed_updates": json.dumps(['message', 'callback_query']),
		'secret_token': config.env.telegramOutgoingToken}
	return call('setWebhook', params=params)

def deleteWebhook():
	"""Have Telegram stop posting updates. Those not delivered yet are kept, for the webhook set next or getUpdates."""
	print("telegram: deleting the webhook", file=sys.stderr)
	return call('deleteWebhook', json={'drop_pending_updates': False})

def getMe():
	"""The bot's own account: its username is the bot's name in chats."""
	return call('getMe')

def register():
	"""Called once by bot.py as it starts, never on import (the job processes and the tests import this module too).
	With telegramOutgoingWebhook (http mode): delete the webhook and set it again, which wakes up a stale connection on
	Telegram's side. Without it (pull mode): delete any webhook, so that getUpdates may take the updates, those not
	delivered yet included. Returns the bot's @username. Raises RuntimeError, or a requests error, if a call fails."""
	deleteWebhook()
	if config.env.telegramOutgoingWebhook:
		setWebhook()
	return '@' + getMe()['username']

def pinChatMessage(chat_id, message_id):
	"""Pin a message, without the "pinned a message" notice. A failure is only logged: the message is there anyway."""
	try_call('pinChatMessage', json={'chat_id': chat_id, 'message_id': message_id, 'disable_notification': True})

def answerCallbackQuery(callback_query_id, text=None):
	"""Acknowledge a button press (the client's spinner stops), `text` as a toast. A failure is only logged."""
	try_call('answerCallbackQuery', json={'callback_query_id': callback_query_id} | ({'text': text} if text else {}))

