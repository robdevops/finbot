"""Telegram, whichever way its updates arrive (long polling, telegram_longpolling; or the webhook, telegram_webhook):
the Bot API calls, the reader of its updates (Telegram, READER), and the bot that posts into its chats
(TelegramBot)."""
import concurrent.futures
import hashlib
import html
import json
import re
import threading

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


ALBUM = 10 # photos in one sendMediaGroup: Telegram's most
ALBUMS_PER_SECOND = 4 # albums preloaded in a second at most, with no other delay; up to that many in flight
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
				press['data'], who, ids=self.ids(sender))
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
			str(message.get('message_id', '')), ids=self.ids(sender))

	@staticmethod
	def ids(sender):
		"""What the admins setting may call a sender: its user id, and its @username where it has one (never its first
		name, which anyone may take, and which a handle without a username is made of)."""
		return tuple(filter(None, (str(sender.get('id') or ''), '@' + sender['username'] if sender.get('username')
			else '')))

	def acknowledge(self, event, toast=True):
		"""A press: answerCallbackQuery, so that the client's spinner stops and a toast made from the button's data says
		what is coming (buttons.toast: 'Loading 1Y…'); none for a press dropped (toast false), and for one refused
		(toast a text) that text as an alert. A failure is only logged. Nothing goes back with the update."""
		if isinstance(event, inbound.Press) and toast is True:
			answerCallbackQuery(event.press_id, buttons.toast(event.data), alert=buttons.alert(event.data))
		elif isinstance(event, inbound.Press):
			answerCallbackQuery(event.press_id, toast or None, alert=bool(toast))
		return None


class TelegramBot(transports.Transport):
	"""A Telegram chat via the Bot API: HTML, silent, no link previews; charts, buttons, edits, the typing notice."""
	name = 'telegram'
	dialect = dialects.TELEGRAM
	TYPING = (0.5, 4, 18) # "typing…" shows for 5 s at most (sendChatAction), so it is sent again every 4 s
	NO_PREVIEWS = {'is_disabled': True} # link_preview_options, which replaced disable_web_page_preview (Bot API 7.0)
	preload_lock = threading.Lock()
	preload_slots = threading.BoundedSemaphore(ALBUMS_PER_SECOND) # albums in flight at once

	def wants(self, photo):
		"""Whether preloading a chart (its PNG bytes) would spare a press its upload: Telegram has not it (no file id
		kept), with the cache setting on."""
		return bool(config.settings.cache and not cache.read(photo_file(photo), PHOTO_SECONDS))

	def retry_after(self, error):
		"""The seconds Telegram's 429 asks to wait ("Too Many Requests: retry after 5"), or None for another failure."""
		found = re.search(r'retry after (\d+)', str(error))
		return float(found.group(1)) if found else None

	def send_all(self, photos):
		"""Preload charts Telegram lacks as albums of up to ALBUM, one request each, started at most ALBUMS_PER_SECOND
		a second with no other delay and overlapping: an upload takes as long for a few photos as for one (its time is
		latency, not size). A lone chart goes by sendPhoto. False if any failed."""
		chunks = [photos[i:i + ALBUM] for i in range(0, len(photos), ALBUM)]
		def send(chunk):
			"""One album, or a lone chart by sendPhoto."""
			if len(chunk) == 1:
				return self.preload(chunk[0])
			return self.paced(lambda: self.send_album(chunk), 1 / ALBUMS_PER_SECOND)
		with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(chunks), ALBUMS_PER_SECOND)) as pool:
			return all(list(pool.map(send, chunks)))

	def send_album(self, photos):
		"""Send 2 to ALBUM charts (PNG bytes) to this chat silently in one sendMediaGroup, keeping each one's file id
		(the answer has a message for each, in order) with the cache setting on."""
		media = [{'type': 'photo', 'media': f'attach://chart{i}'} for i in range(len(photos))]
		files = {f'chart{i}': (f'chart{i}.png', photo) for i, photo in enumerate(photos)}
		sent = call('sendMediaGroup', data={'chat_id': self.where, 'disable_notification': True,
			'media': json.dumps(media)}, files=files)
		if config.settings.cache:
			for photo, message in zip(photos, sent):
				if sizes := message.get('photo'):
					cache.write(photo_file(photo), sizes[-1]['file_id'])

	def send_ahead(self, photo):
		"""Send a chart to this chat silently, with no caption, for its file id (with_photo keeps it)."""
		with_photo('sendPhoto', photo, lambda known: {'chat_id': self.where, 'disable_notification': True})

	def is_administrator(self, who):
		"""Whether getChatMember says this user id is the creator or an administrator of the group; in a direct
		message, of any group finbot knows. A username (@name) cannot be asked."""
		if not who.isdigit():
			return False
		if not self.where.startswith('-'):
			from lib import jobs # only here: a direct message asks about each group finbot has seen
			return any(TelegramBot(group).administers((who,)) for group in
				(key.partition(':')[2] for key in state.load(jobs.JOBS_FILE, {}) if key.startswith('telegram:-')))
		return call('getChatMember', json={'chat_id': self.where, 'user_id': who}).get('status') in (
			'creator', 'administrator')

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
		photo = image.read() if hasattr(image, 'read') else bytes(image)
		try:
			message = with_photo('sendPhoto', photo, lambda known: data | ({'photo': known} if known else {}))
		except requests.exceptions.ReadTimeout as e:
			log.warn("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e))
			return transports.MAYBE_SENT
		except Exception as e:
			log.warn("Telegram sendPhoto to", self.where, "failed:", net.redact(e))
			return None
		log.info("OK telegram chart to", self.where)
		self.note_view(buttons, message, caption)
		return message

	def edit_chart(self, message, image, caption, buttons=None):
		"""Replace a chart message's image, caption and buttons in place, the image by the file id of its earlier upload
		where there is one (with_photo). Raises RuntimeError when Telegram refuses, unless the message is already so
		(pressing the active period again is harmless); a request that fails on the way is only logged."""
		caption = transports.fit_caption(caption, self.dialect)
		data = {'chat_id': self.where, 'message_id': message}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		if hasattr(image, 'seek'):
			image.seek(0)
		photo = image.read() if hasattr(image, 'read') else bytes(image)
		try:
			edited = with_photo('editMessageMedia', photo, lambda known: data | {'media': json.dumps({'type': 'photo',
				'media': known or 'attach://photo', 'caption': caption, 'parse_mode': 'HTML'})}, quiet=True)
			self.note_view(buttons, edited, caption)
		except RuntimeError as e:
			if not unchanged(e):
				raise
		except Exception as e: # it may have arrived even so: no error line for something the chat may already show
			log.warn("Telegram editMessageMedia failed:", net.redact(e))

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
		data = {'chat_id': self.where, 'message_id': message, 'reply_markup': json.dumps(self.markup(buttons)),
			'media': json.dumps({'type': 'photo', 'media': file_id, 'caption': caption, 'parse_mode': 'HTML'})}
		try:
			call('editMessageMedia', data=data, logged='debug')
		except Exception as e:
			if unchanged(e):
				return True
			log.warn("Telegram editMessageMedia with an earlier upload failed, drawing the chart anew:", net.redact(e))
			return False
		return True

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
