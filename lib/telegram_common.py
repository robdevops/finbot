"""Telegram, whichever way its updates arrive (long polling, telegram_longpolling; or the webhook, telegram_webhook):
the Bot API calls, the reader of its updates (Telegram, READER), and the bot that posts into its chats
(TelegramBot)."""
import html
import json

import requests

from lib import log
from lib import buttons
from lib import config
from lib import dialects
from lib import inbound
from lib import net
from lib import transports


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
		log.warn(f"Telegram {method} failed:", net.redact(e))


def unchanged(error):
	"""Whether Telegram refused an edit for changing nothing ("message is not modified": a press whose answer looks
	as the message does already, such as Run now's list after a run), which is routine, logged at debug."""
	if 'message is not modified' not in str(error):
		return False
	log.debug("Telegram message not edited: it shows that already")
	return True


def deleteWebhook():
	"""Have Telegram stop posting updates. Those not delivered yet are kept, for the webhook set next or getUpdates."""
	log.info("telegram: deleting the webhook")
	return call('deleteWebhook', json={'drop_pending_updates': False})


def bot_name():
	"""The bot's @username, from its own account (getMe): a command in a group may name the bot (/price@finbot)."""
	return '@' + call('getMe')['username']


def set_commands(commands):
	"""Make the bot's command menu, in every chat, these slash commands ([(name, description, arguments)], from
	worker.slash_commands), each with its usage, where Telegram's differs. A failure is only logged: typed, a command
	works without the menu."""
	wanted = [{'command': command.name, 'description': command.description[:256]} for command in commands]
	if try_call('getMyCommands') != wanted and try_call('setMyCommands', json={'commands': wanted}) is not None:
		log.info(f"telegram: {len(wanted)} commands in the menu")


def pinChatMessage(chat_id, message_id):
	"""Pin a message, without the "pinned a message" notice. A failure is only logged: the message is there anyway."""
	try_call('pinChatMessage', json={'chat_id': chat_id, 'message_id': message_id, 'disable_notification': True})


def answerCallbackQuery(callback_query_id, text=None, alert=False):
	"""Acknowledge a button press (the client's spinner stops), `text` as a toast, or with `alert` as an alert the
	person dismisses. A failure is only logged."""
	try_call('answerCallbackQuery', json={'callback_query_id': callback_query_id} | ({'text': text} if text else {}) |
		({'show_alert': True} if alert else {}), logged='debug')


class Telegram(inbound.Network):
	"""Telegram's updates: messages and button presses."""
	service = 'telegram'
	bot_name = None # the bot's @username, from bot_name() as bot.py starts
	IGNORED = {'sticker', 'animation', 'voice', 'video', 'video_note', 'audio', 'document', 'contact', 'location',
		'venue', 'poll', 'dice'} # nothing to answer, nothing worth logging

	def update_id(self, update):
		"""Telegram's update_id."""
		return update.get('update_id')

	def parse(self, update):
		"""A message (its text, or a photo's caption) or a button press. A first name is escaped as it arrives:
		replies are Telegram HTML, and a name is text, not markup."""
		if 'callback_query' in update: # a button of the bot's pressed
			press = update['callback_query']
			message = press.get('message')
			if not message or not press.get('data'):
				return inbound.UNSUPPORTED
			sender = press.get('from', {})
			who = '@' + sender['username'] if 'username' in sender else sender.get('first_name', 'unknown')
			return inbound.Press(self.service, press['id'], str(message['chat']['id']), str(message['message_id']),
				press['data'], who)
		if 'message' not in update:
			return inbound.UNSUPPORTED
		message = update['message']
		sender = message['from']
		chat_id = str(message['chat']['id'])
		first_name = html.escape(sender['first_name'], quote=False)
		if 'username' in sender:
			user = '@' + sender['username']
			user_name = first_name or user # the handle when the first name is blank
		else:
			user = user_name = '@' + first_name
		if 'text' in message:
			text = message['text']
		elif 'photo' in message:
			text = message.get('caption', '')
		elif self.IGNORED & message.keys():
			return inbound.OK
		else:
			log.info("Telegram unhandled: 'message' without 'text/photo'")
			return inbound.UNHANDLED
		return inbound.Message(self.service, chat_id, user, text, self.bot_name, user_name,
			str(message.get('message_id', '')))

	def acknowledge(self, event, toast=True):
		"""A press: answerCallbackQuery, so that the client's spinner stops and a toast made from the button's data says
		what is coming (buttons.toast: 'Loading 1Y…'), but for a press dropped (toast false). A failure is only
		logged. Nothing goes back with the update."""
		if isinstance(event, inbound.Press) and toast:
			answerCallbackQuery(event.press_id, buttons.toast(event.data), alert=buttons.alert(event.data))
		elif isinstance(event, inbound.Press):
			answerCallbackQuery(event.press_id)
		return None


class TelegramBot(transports.Transport):
	"""A Telegram chat via the Bot API: HTML, silent, no link previews; charts, buttons, edits, the typing notice."""
	name = 'telegram'
	dialect = dialects.TELEGRAM
	TYPING = (0.5, 4, 18) # "typing…" shows for 5 s at most (sendChatAction), so it is sent again every 4 s
	NO_PREVIEWS = {'is_disabled': True} # link_preview_options, which replaced disable_web_page_preview (Bot API 7.0)

	@staticmethod
	def markup(buttons):
		"""Rows of buttons.Button as Telegram's inline keyboard ('● ' marks the active one); a markup of Telegram's own
		(the command keyboard) as it is."""
		if isinstance(buttons, dict):
			return buttons
		return {'inline_keyboard': [[{'text': ('● ' if button.active else '') + button.label,
			'callback_data': button.data} for button in row] for row in buttons]}

	def post_text(self, text, buttons=None):
		"""sendMessage: Telegram's message, or None when it refused or failed (logged with Telegram's reason, such as
		"can't parse entities")."""
		payload = {'chat_id': self.where, 'text': text, 'parse_mode': 'HTML', 'link_preview_options': self.NO_PREVIEWS,
			'disable_notification': True}
		if buttons:
			payload['reply_markup'] = self.markup(buttons)
		try:
			message = call('sendMessage', json=payload)
		except Exception as e:
			log.error("Telegram sendMessage to", self.where, "failed:", net.redact(e))
			return None
		log.info("OK telegram message to", self.where)
		return message

	def post_chart(self, image, caption, buttons=None):
		"""sendPhoto, the report as its caption: Telegram's message, MAYBE_SENT, or None when it refused or failed
		(logged with Telegram's reason)."""
		data = {'chat_id': self.where, 'caption': caption, 'parse_mode': 'HTML', 'disable_notification': True}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		try:
			message = call('sendPhoto', data=data, files={'photo': ('image.png', image)})
		except requests.exceptions.ReadTimeout as e:
			log.warn("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e))
			return transports.MAYBE_SENT
		except Exception as e:
			log.warn("Telegram sendPhoto to", self.where, "failed:", net.redact(e))
			return None
		log.info("OK telegram chart to", self.where)
		return message

	def edit_chart(self, message, image, caption, buttons=None):
		"""Replace a chart message's image, caption and buttons in place. Raises RuntimeError when Telegram refuses,
		unless the message is already so (pressing the active period again is harmless); a request that fails on the way
		is only logged."""
		media = {'type': 'photo', 'media': 'attach://photo', 'caption': transports.fit_caption(caption, self.dialect),
			'parse_mode': 'HTML'}
		data = {'chat_id': self.where, 'message_id': message, 'media': json.dumps(media)}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		if hasattr(image, 'seek'):
			image.seek(0)
		try:
			call('editMessageMedia', data=data, files={'photo': ('image.png', image)}, logged='debug')
		except RuntimeError as e:
			if not unchanged(e):
				raise
		except Exception as e: # it may have arrived even so: no error line for something the chat may already show
			log.warn("Telegram editMessageMedia failed:", net.redact(e))

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged, an
		edit that changes nothing (unchanged) as no failure."""
		payload = {'chat_id': self.where, 'message_id': message, 'text': text, 'parse_mode': 'HTML',
			'link_preview_options': self.NO_PREVIEWS}
		if buttons is not None:
			payload['reply_markup'] = self.markup(buttons)
		try:
			call('editMessageText', json=payload, logged='debug')
		except Exception as e:
			if not unchanged(e):
				log.warn("Telegram editMessageText failed:", net.redact(e))

	def edit_buttons(self, message, buttons):
		"""editMessageReplyMarkup: the buttons under a message changed, its text or chart left as it is (no upload).
		True when they show now, as they do when they were so already (unchanged); a failure is logged, and False."""
		try:
			call('editMessageReplyMarkup', json={'chat_id': self.where, 'message_id': message,
				'reply_markup': self.markup(buttons)}, logged='debug')
		except Exception as e:
			if unchanged(e):
				return True
			log.warn("Telegram editMessageReplyMarkup failed:", net.redact(e))
			return False
		return True

	def typing(self):
		"""sendChatAction: "typing…" for a few seconds."""
		try_call('sendChatAction', data={'chat_id': self.where, 'action': 'typing'})

	def pin(self, answers):
		"""Pin the messages that these answers are (Telegram's), last first, so that the first ends up on top, without
		the notification."""
		sent = []
		for answer in answers:
			try:
				sent.append((answer['chat']['id'], answer['message_id']))
			except (KeyError, TypeError):
				log.warn("Unable to pin: unexpected response")
		for chat, message in reversed(sent):
			pinChatMessage(chat, message)


READER = Telegram()
