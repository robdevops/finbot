"""Telegram, whichever way its updates arrive (long polling, telegram_longpolling; or the webhook, telegram_webhook):
the Bot API calls, the reader of its updates (Telegram, READER), and the bot that posts into its chats
(TelegramBot)."""
import hashlib
import html
import json
import re

import requests

from lib import log
from lib import buttons
from lib import cache
from lib import config
from lib import dialects
from lib import inbound
from lib import net
from lib import state
from lib import transports


def call(method, **kwargs):
	"""POST a Bot API method and return its result, a rate limit waited out once (net.patiently). Raises RuntimeError
	with Telegram's reason when it is not ok."""
	url = config.env.telegram_api + method
	return net.patiently(lambda: net.ok_answer(net.post(url, **kwargs), f"Telegram {method}", 'description'))['result']


def try_call(method, **kwargs):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, **kwargs)
	except Exception as e:
		log.warn(f"Telegram {method} failed:", net.redact(e))


STYLES = {buttons.ON: 'success', buttons.OFF: 'danger', buttons.ACTIVE: 'primary'} # a button's style by its look
ALLOWED_UPDATES = ['message', 'callback_query'] # what finbot takes, whichever way it arrives: messages, presses
KEYBOARD_FILE = 'finbot_keyboards.json' # chat id -> the version of the command keyboard that DM has (keep_keyboard)
PHOTO_SECONDS = 30 * 86400 # how long a chart's file id is reused: Telegram keeps a bot's files, cleanup the cache file
TELEGRAM_REUSE_SECONDS = 30 * 60 # a period pressed within this long of its upload in a chat shows that upload again
# how Telegram refuses a file id it does not know (another bot's, say)
REFUSED_PHOTO = re.compile(r'file identifier|file reference|file_id|MEDIA_EMPTY', re.I)


def photo_file(photo):
	"""The cache file that holds the file id of a chart (its PNG bytes) uploaded to Telegram: by the chart and the bot,
	whose own uploads alone it shows by id."""
	return f"finbot_telegram_photo_{hashlib.sha1(config.env.telegramBotToken.encode() + photo).hexdigest()[:20]}.json"


def view_file(view):
	"""The cache file of the chart a chat's chart messages showed last for a period (a view: Transport.view): its file
	id and the report that came with it."""
	return f"finbot_telegram_view_{hashlib.sha1(view.encode()).hexdigest()[:20]}.json"


def with_photo(method, photo, data, quiet=False):
	"""call() a method that sends a chart (its PNG bytes, photo), its form data(known): known the file id of the
	chart's earlier upload where there is one (no bytes are sent: a period or portfolio shown again), else None and the
	bytes uploaded, their file id kept for next time (with the cache setting on). An earlier file id that Telegram
	refuses gives way to the upload. Its request is logged at INFO, but by a file id at DEBUG where quiet (a press's
	edit: only an upload is worth noting)."""
	name = photo_file(photo)
	if config.settings.cache and (known := cache.read(name, PHOTO_SECONDS)):
		try:
			return call(method, data=data(known), logged='debug' if quiet else True)
		except RuntimeError as e:
			if not REFUSED_PHOTO.search(str(e)):
				raise
			log.warn(f"Telegram {method} refused an earlier upload of the chart, uploading it again:", net.redact(e))
	result = call(method, data=data(None), files={'photo': ('image.png', photo)})
	sizes = result.get('photo') if isinstance(result, dict) else None
	if sizes and config.settings.cache:
		cache.write(name, sizes[-1]['file_id']) # the largest: the chart as it was sent
	return result


def unchanged(error):
	"""Whether Telegram refused an edit for changing nothing ("message is not modified": a press whose answer looks
	as the message does already, such as Run now's list after a run), which is routine, logged at debug."""
	if 'message is not modified' not in str(error):
		return False
	log.debug("Telegram message not edited: it shows that already")
	return True


def start(commands):
	"""Called once by bot.py as it starts, never on import: the webhook deleted, keeping the updates not delivered yet,
	and in http mode set again (telegramOutgoingWebhook, signed with telegramOutgoingToken), which wakes a stale
	connection on Telegram's side; in pull mode getUpdates takes them (telegram_longpolling). Then the bot's
	@username (getMe: a command in a group may name the bot, /price@finbot) and the command menu (set_commands).
	Raises RuntimeError, or a requests error, when the webhook or the bot's name cannot be had."""
	log.info("telegram: deleting the webhook")
	call('deleteWebhook', json={'drop_pending_updates': False})
	if config.env.telegramOutgoingWebhook: # in the body, never the query string, which a failed request's error (and
		# so the log) would show: the URL's path is a secret
		log.info("telegram: setting the webhook (telegramOutgoingWebhook)")
		call('setWebhook', json={'url': config.env.telegramOutgoingWebhook, 'allowed_updates': ALLOWED_UPDATES,
			'secret_token': config.env.telegramOutgoingToken})
	READER.bot_name = '@' + call('getMe')['username']
	set_commands(commands)


def set_commands(commands):
	"""Make the bot's command menu, in every chat, these slash commands ([(name, description, arguments)], from
	worker.slash_commands), each with its usage, where Telegram's differs. A failure is only logged: typed, a command
	works without the menu."""
	wanted = [{'command': command.name, 'description': command.description[:256]} for command in commands]
	if try_call('getMyCommands') != wanted and try_call('setMyCommands', json={'commands': wanted}) is not None:
		log.info(f"telegram: {len(wanted)} commands in the menu")


def keyboard(texts, per_row=3):
	"""The persistent reply keyboard of a DM: a button for each text (a command, which a press sends as a message),
	alphabetical, per_row to a row."""
	texts = sorted(texts)
	rows = [[{'text': text} for text in texts[i:i + per_row]] for i in range(0, len(texts), per_row)]
	return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}


def keep_keyboard(chat_id, texts):
	"""Give a DM the keyboard of these texts where it has another, or none yet (KEYBOARD_FILE, by a short hash of the
	keyboard): Telegram changes a reply keyboard only with a message, so a short one carries it. A failure is logged,
	and tried again after the next command."""
	given = keyboard(texts)
	version = hashlib.sha1(json.dumps(given, sort_keys=True).encode()).hexdigest()[:8]
	chat = TelegramBot(chat_id)
	if not chat.dm or state.load(KEYBOARD_FILE, {}).get(str(chat_id)) == version:
		return
	if chat.sent('message', lambda: call('sendMessage', json={'chat_id': chat_id, 'text': '⌨️ Keyboard updated',
			'disable_notification': True, 'reply_markup': given})) is not None:
		with state.edit(KEYBOARD_FILE, {}) as versions:
			versions[str(chat_id)] = version


def refresh_keyboards(texts):
	"""As finbot starts, in a thread of its own: each DM that has had a keyboard given this one, where it differs."""
	for chat_id in state.load(KEYBOARD_FILE, {}):
		try:
			keep_keyboard(chat_id, texts)
		except Exception as e:
			log.warn("telegram: the keyboard of", chat_id, "was not refreshed:", e)


def pinChatMessage(chat_id, message_id):
	"""Pin a message, without the "pinned a message" notice. A failure is only logged: the message is there anyway."""
	try_call('pinChatMessage', json={'chat_id': chat_id, 'message_id': message_id, 'disable_notification': True})


def answerCallbackQuery(callback_query_id, text=None, alert=False):
	"""Acknowledge a button press (the client's spinner stops), `text` as a toast, or with `alert` as an alert the
	presser dismisses. A failure is only logged."""
	try_call('answerCallbackQuery', json={'callback_query_id': callback_query_id} | ({'text': text} if text else {}) |
		({'show_alert': True} if alert else {}), logged='debug')


def button_style(button):
	"""Telegram's style of a button (STYLES): success (green) for a toggle that is on, danger (red) for one that is
	off, primary (blue) for the one shown now; none for the rest. A client before February 2026 draws none."""
	style = STYLES.get(buttons.look(button))
	return {'style': style} if style else {}


class Telegram(inbound.Network):
	"""Telegram's updates: messages and button presses."""
	service = 'telegram'
	bot_name = None # the bot's @username, noted as finbot starts (start)
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
			return inbound.Press(self.service, press['id'], str(message['chat']['id']), str(message['message_id']),
				press['data'], self.handle(sender), ids=self.ids(sender))
		if 'message' not in update:
			return inbound.UNSUPPORTED
		message = update['message']
		sender = message['from']
		chat_id = str(message['chat']['id'])
		if 'text' in message:
			text = message['text']
		elif 'photo' in message:
			text = message.get('caption', '')
		elif self.IGNORED & message.keys():
			return inbound.OK
		else:
			log.info("Telegram unhandled: 'message' without 'text/photo'")
			return inbound.UNHANDLED
		return inbound.Message(self.service, chat_id, self.handle(sender), text, self.bot_name,
			str(message.get('message_id', '')), ids=self.ids(sender))

	@staticmethod
	def handle(sender):
		"""What a reply calls a sender: its @username, else @ and its first name escaped (a reply is Telegram HTML)."""
		name = sender.get('username') or html.escape(sender.get('first_name') or 'unknown', quote=False)
		return '@' + name

	@staticmethod
	def ids(sender):
		"""What the admins setting may call a sender: its user id, and its @username where it has one (never its first
		name, which anyone may take, and which a handle without a username is made of)."""
		return tuple(filter(None, (str(sender.get('id') or ''), '@' + sender['username'] if sender.get('username')
			else '')))

	def acknowledge(self, event, text=None, alert=False):
		"""A press: answerCallbackQuery, so that the client's spinner stops, with the text as a toast, or with alert as
		an alert the presser dismisses. A failure is only logged. Nothing goes back with the update."""
		if isinstance(event, inbound.Press):
			answerCallbackQuery(event.press_id, text, alert)
		return None


class TelegramBot(transports.Transport):
	"""A Telegram chat via the Bot API: HTML, silent, no link previews; charts, buttons, edits, the typing notice."""
	name = 'telegram'
	dialect = dialects.TELEGRAM
	TYPING = (0.5, 4, 18) # "typing…" shows for 5 s at most (sendChatAction), so it is sent again every 4 s
	CHUNK_GAP = 0.5 # Telegram takes about one message a second in a chat
	PRELOAD_CHAT = 'telegram_preload_chat'
	NO_PREVIEWS = {'is_disabled': True} # link_preview_options, which replaced disable_web_page_preview (Bot API 7.0)

	@property
	def dm(self):
		"""Whether the chat is a direct message: a person's id is positive, a group's negative."""
		return not self.where.startswith('-')

	def wants(self, photo):
		"""Whether preloading a chart (its PNG bytes) would spare a press its upload: Telegram has not it (no file id
		kept), with the cache setting on."""
		return bool(config.settings.cache and not cache.read(photo_file(photo), PHOTO_SECONDS))

	def send_ahead(self, photo):
		"""Send a chart to this chat silently, with no caption, for its file id (with_photo keeps it)."""
		with_photo('sendPhoto', photo, lambda known: {'chat_id': self.where, 'disable_notification': True})

	def administers(self, ids):
		"""As Transport's in a group; in a direct message, whether so in any group finbot knows (the schedule's chats),
		by each group's own answers, so that a group that could not be asked is asked again at the next message."""
		if not self.dm:
			return super().administers(ids)
		from lib import jobs # only here: a direct message asks about each group finbot has seen
		groups = [TelegramBot(where) for network, where in map(transports.split_key, jobs.current.chats if
			jobs.current else ()) if network == self.name]
		return any(group.administers(ids) for group in groups if not group.dm)

	def is_administrator(self, who):
		"""Whether getChatMember says this user id is the creator or an administrator of the group. A username (@name)
		cannot be asked."""
		return who.isdigit() and call('getChatMember', json={'chat_id': self.where, 'user_id': who}).get('status') in (
			'creator', 'administrator')

	@staticmethod
	def markup(buttons):
		"""Rows of buttons.Button as Telegram's inline keyboard, each in its style (button_style)."""
		return {'inline_keyboard': [[{'text': button.label, 'callback_data': button.data, **button_style(button)}
			for button in row] for row in buttons]}

	def post_text(self, text, buttons=None):
		"""sendMessage: Telegram's message. Raises with Telegram's reason (such as "can't parse entities")."""
		payload = {'chat_id': self.where, 'text': text, 'parse_mode': 'HTML', 'link_preview_options': self.NO_PREVIEWS,
			'disable_notification': True}
		if buttons:
			payload['reply_markup'] = self.markup(buttons)
		return call('sendMessage', json=payload)

	def post_chart(self, photo, caption, buttons=None):
		"""sendPhoto, the report as its caption: Telegram's message. Raises with Telegram's reason; MaybeSent when it
		timed out."""
		data = {'chat_id': self.where, 'caption': caption, 'parse_mode': 'HTML', 'disable_notification': True}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		try:
			message = with_photo('sendPhoto', photo, lambda known: data | ({'photo': known} if known else {}))
		except requests.exceptions.ReadTimeout as e:
			raise transports.MaybeSent(e) from e
		self.note_view(buttons, message, caption)
		return message

	def replace_chart(self, message, photo, caption, buttons):
		"""Replace a chart message's image, caption and buttons in place, the image by the file id of its earlier upload
		where there is one (with_photo). Raises RuntimeError when Telegram refuses, unless the message is already so
		(pressing the active period again is harmless); a request that fails on the way is only logged."""
		data = {'chat_id': self.where, 'message_id': message}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		try:
			edited = with_photo('editMessageMedia', photo, lambda known: data | {'media': json.dumps({
				'type': 'photo', 'media': known or 'attach://photo', 'caption': caption, 'parse_mode': 'HTML'})},
				quiet=True)
		except RuntimeError as e:
			if not unchanged(e):
				raise
			return
		except Exception as e: # it may have arrived even so: no error line for something the chat may already show
			log.warn("Telegram editMessageMedia failed:", net.redact(e))
			return
		self.note_view(buttons, edited, caption)

	def note_view(self, buttons, message, caption):
		"""Note the chart a message shows now (Telegram's answer, message: its photo's file id) for the period its
		buttons mark, with its caption, for the period pressed again in this chat to show it (reshow; cache setting
		on)."""
		view = self.view(buttons)
		sizes = message.get('photo') if isinstance(message, dict) else None
		if view and sizes and config.settings.cache:
			cache.write(view_file(view), [sizes[-1]['file_id'], caption])

	def reshow(self, message, buttons):
		"""Show a chart message's period again from its upload of under TELEGRAM_REUSE_SECONDS ago in this chat (for
		this message or another), by its file id, with the report it came with: nothing is built, drawn or uploaded.
		True when it did, or the message shows it already; False when there is no such upload (or the cache setting is
		off), or Telegram refuses it."""
		view = self.view(buttons)
		earlier = cache.read(view_file(view), TELEGRAM_REUSE_SECONDS) if view and config.settings.cache else None
		if not earlier:
			return False
		file_id, caption = earlier
		return self.edit('editMessageMedia', data={'chat_id': self.where, 'message_id': message,
			'reply_markup': json.dumps(self.markup(buttons)),
			'media': json.dumps({'type': 'photo', 'media': file_id, 'caption': caption, 'parse_mode': 'HTML'})})

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		payload = {'chat_id': self.where, 'message_id': message, 'text': text, 'parse_mode': 'HTML',
			'link_preview_options': self.NO_PREVIEWS}
		if buttons is not None:
			payload['reply_markup'] = self.markup(buttons)
		self.edit('editMessageText', json=payload)

	def edit_buttons(self, message, buttons):
		"""editMessageReplyMarkup: the buttons under a message changed, its text or chart left as it is (no upload).
		True when they show now (see edit)."""
		return self.edit('editMessageReplyMarkup', json={'chat_id': self.where, 'message_id': message,
			'reply_markup': self.markup(buttons)})

	def edit(self, method, **request):
		"""An edit of a message, call(method, **request) logged at DEBUG (a press's routine): True when the message
		shows what it asks for now, as it does when Telegram refuses it for changing nothing (unchanged); False when it
		failed (logged)."""
		try:
			call(method, logged='debug', **request)
		except Exception as e:
			if unchanged(e):
				return True
			log.warn(f"Telegram {method} failed:", net.redact(e))
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
