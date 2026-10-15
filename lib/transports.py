"""How a message gets to each network: a class per way of posting, made for one destination (a chat, or an incoming
webhook). A transport knows its dialect, what it can carry (charts, buttons, a typing notice) and the network's size
limits; text() and chart() are the same everywhere, and each network posts one message its own way (post_text,
post_chart)."""
import json
import sys
import threading
import time

import requests

from lib import config
from lib import dialects
from lib import net
from lib import state
from lib import telegram

MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows
SUPPRESS_EMBEDS = 4 # Discord message flag: no link previews
SLACK_CHARTS = 'finbot_slack_charts.json' # Slack's chart messages: the file each shows, and the charts uploaded
SLACK_CHARTS_KEPT = 500 # chart messages noted, newest last: an older one shows its file for good
SLACK_REUSE_SECONDS = 15 * 60 # a period pressed within this long of its chart's upload shows that upload again
NO_MENTIONS = {'parse': []} # Discord: text that looks like @everyone or a mention pings nobody


class Transport:
	"""A destination. Subclasses set what it carries and post one message; the base splits and trims, and keeps the
	typing notice going while a command works."""
	name = '' # the network, in logs
	dialect = None
	takes_charts = False # a chart, with the report as its caption
	takes_buttons = False # buttons under a message
	shows_typing = False # a typing notice while a command works
	TYPING = (0.5, 7, 10) # the notice: first after 0.5 s (a quick answer gets none), then every 7 s, 10 times at most
	_notices = None # the thread sending the notices
	_quiet = None # set to stop them

	def __init__(self, where, message=None):
		"""where: the chat id, or the incoming webhook's URL; message: the id of the message being answered, if any."""
		self.where = where
		self.message = message

	def __repr__(self):
		"""<TelegramBot 55>: the kind and where, for logs and test failures."""
		return f'<{type(self).__name__} {self.where}>'

	def start_typing(self):
		"""Show the typing notice while a command works, where the network has one (TYPING says when), until the first
		message goes out or the command ends (end_typing)."""
		if not self.shows_typing or self._notices:
			return
		delay, every, times = self.TYPING
		self._quiet = threading.Event()
		def notices():
			"""The notices, until quiet."""
			if self._quiet.wait(delay):
				return
			for _ in range(times):
				self.typing()
				if self._quiet.wait(every):
					return
		self._notices = threading.Thread(target=notices, daemon=True)
		self._notices.start()

	def stop_typing(self):
		"""Send no more notices, and wait for one on its way: none may arrive after the answer."""
		if self._notices:
			self._quiet.set()
			self._notices.join()

	def end_typing(self):
		"""The command is over: no more notices, and one that lasts until taken off (Slack's ⏳) taken off."""
		self.stop_typing()
		self.typing_done()

	def is_typing(self):
		"""Whether the notices are still going."""
		return bool(self._notices and self._notices.is_alive())

	def text(self, lines, buttons=None):
		"""Post lines of text: one message, or several when they are too long for one, buttons under the last; the
		typing notice stops first. Returns the network's answer for each message (None for one that failed)."""
		self.stop_typing()
		lines = [str(line) for line in lines]
		if not lines:
			return []
		limit = self.dialect.text_limit
		if len('\n'.join(lines)) <= limit:
			return [self.post_text('\n'.join(lines), buttons)]
		chunks = chunked(lines, limit)
		answers = []
		for i, chunk in enumerate(chunks):
			if i:
				time.sleep(0.5) # Telegram takes about one message a second in a chat
			answers.append(self.post_text('\n'.join(chunk), buttons if i == len(chunks) - 1 else None))
		return answers

	def chart(self, image, caption, buttons=None):
		"""Post a chart, the caption under it cut to fit, the typing notice stopped first: the network's answer,
		MAYBE_SENT, or None if it failed."""
		self.stop_typing()
		if hasattr(image, 'seek'):
			image.seek(0)
		return self.post_chart(image, fit_caption(caption, self.dialect), buttons)

	def post_text(self, text, buttons=None):
		"""Post one message. The network's answer, or None when it failed (logged)."""
		raise NotImplementedError

	def post_chart(self, image, caption, buttons=None):
		"""Post one chart with its caption (see chart())."""
		raise NotImplementedError

	def typing(self):
		"""Show the typing notice once, where the network has one."""

	def typing_done(self):
		"""Take the typing notice off, where it lasts until taken off (Slack's ⏳)."""

	def acknowledge(self, press, text=None):
		"""Answer a button press, where the network waits for that (Telegram, with `text` as a toast)."""

	def reshow(self, message, buttons):
		"""Show a chart message's period (the button marked) again as it was posted lately, where the network keeps
		that: True when it did. Here never: each period is drawn and sent anew."""
		return False

	def _post_json(self, url, payload, headers=None):
		"""POST a JSON message: the answer ({} when it is not JSON), or None when the network refused it or failed."""
		try:
			r = net.post(url, headers={'Content-type': 'application/json', **(headers or {})}, json=payload)
		except Exception as e:
			print("Failure sending to", self.name + ":", net.redact(e), file=sys.stderr)
			return None
		if r.status_code != 200:
			print(r.status_code, "error outbound to", self.name, file=sys.stderr)
			return None
		print(r.status_code, "OK outbound to", self.name, file=sys.stderr)
		try:
			return r.json()
		except ValueError:
			return {}


class TelegramBot(Transport):
	"""A Telegram chat via the Bot API: HTML, silent, no link previews; charts, buttons, edits, the typing notice."""
	name = 'telegram'
	dialect = dialects.TELEGRAM
	takes_charts = shows_typing = True

	@property
	def takes_buttons(self):
		"""Buttons only where their presses reach finbot: with telegramOutgoingWebhook, Telegram posts them to it."""
		return bool(config.env.telegramOutgoingWebhook)

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
		payload = {'chat_id': self.where, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True,
			'disable_notification': True}
		if buttons:
			payload['reply_markup'] = self.markup(buttons)
		try:
			message = telegram.call('sendMessage', json=payload)
		except Exception as e:
			print("Telegram sendMessage to", self.where, "failed:", net.redact(e), file=sys.stderr)
			return None
		print("OK telegram message to", self.where, file=sys.stderr)
		return message

	def post_chart(self, image, caption, buttons=None):
		"""sendPhoto, the report as its caption: Telegram's message, MAYBE_SENT, or None when it refused or failed
		(logged with Telegram's reason)."""
		data = {'chat_id': self.where, 'caption': caption, 'parse_mode': 'HTML', 'disable_notification': True}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		try:
			message = telegram.call('sendPhoto', data=data, files={'photo': ('image.png', image)})
		except requests.exceptions.ReadTimeout as e:
			print("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
		except Exception as e:
			print("Telegram sendPhoto to", self.where, "failed:", net.redact(e), file=sys.stderr)
			return None
		print("OK telegram chart to", self.where, file=sys.stderr)
		return message

	def edit_chart(self, message, image, caption, buttons=None):
		"""Replace a chart message's image, caption and buttons in place. Raises RuntimeError when Telegram refuses,
		unless the message is already so (pressing the active period again is harmless); a request that fails on the way
		is only logged."""
		media = {'type': 'photo', 'media': 'attach://photo', 'caption': fit_caption(caption, self.dialect),
			'parse_mode': 'HTML'}
		data = {'chat_id': self.where, 'message_id': message, 'media': json.dumps(media)}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		if hasattr(image, 'seek'):
			image.seek(0)
		try:
			telegram.call('editMessageMedia', data=data, files={'photo': ('image.png', image)})
		except RuntimeError as e:
			if 'not modified' not in str(e):
				raise
		except Exception as e: # it may have arrived even so: no error line for something the chat may already show
			print("Telegram editMessageMedia failed:", net.redact(e), file=sys.stderr)

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		payload = {'chat_id': self.where, 'message_id': message, 'text': text, 'parse_mode': 'HTML',
			'disable_web_page_preview': True}
		if buttons is not None:
			payload['reply_markup'] = self.markup(buttons)
		telegram.try_call('editMessageText', json=payload)

	def typing(self):
		"""sendChatAction: "typing…" for a few seconds."""
		telegram.try_call('sendChatAction', data={'chat_id': self.where, 'action': 'typing'})

	def acknowledge(self, press, text=None):
		"""answerCallbackQuery: the client's spinner stops, and `text` shows as a toast."""
		telegram.answerCallbackQuery(press, text)

	def pin(self, answers):
		"""Pin the messages that these answers are (Telegram's), last first, so that the first ends up on top, without
		the notification."""
		sent = []
		for answer in answers:
			try:
				sent.append((answer['chat']['id'], answer['message_id']))
			except (KeyError, TypeError):
				print("Unable to pin: unexpected response", file=sys.stderr)
		for chat, message in reversed(sent):
			telegram.pinChatMessage(chat, message)


class SlackBot(Transport):
	"""A Slack channel, as the bot: chat.postMessage and the file upload, with slackBotToken."""
	name = 'slack'
	dialect = dialects.SLACK
	WORKING = 'hourglass_flowing_sand' # ⏳: Slack has no typing notice for bots, so a reaction on the message stands in
	working = None # True while ⏳ is on the message, False when putting it there failed

	@property
	def takes_charts(self):
		"""Charts are uploaded with the bot token, so only with one."""
		return bool(config.env.slackBotToken)

	@property
	def shows_typing(self):
		"""⏳ on the message being answered, with the bot token."""
		return bool(self.message and config.env.slackBotToken)

	@property
	def takes_buttons(self):
		"""Buttons only where their presses reach finbot: with the bot token and slackOutgoingWebhook, the URL that the
		app's interactivity posts to as its events do."""
		return bool(config.env.slackBotToken and config.env.slackOutgoingWebhook)

	def typing(self):
		"""Put ⏳ on the message being answered, once (the bot needs the reactions:write scope); a failure is only
		logged, and not tried again."""
		if self.working is not None:
			return
		try:
			slack_api('reactions.add', channel=self.where, timestamp=self.message, name=self.WORKING)
			self.working = True
		except Exception as e:
			self.working = False
			print("Slack reactions.add failed:", net.redact(e), file=sys.stderr)

	def typing_done(self):
		"""Take ⏳ off the message again; a failure is only logged."""
		if not self.working:
			return
		self.working = False
		try:
			slack_api('reactions.remove', channel=self.where, timestamp=self.message, name=self.WORKING)
		except Exception as e:
			print("Slack reactions.remove failed:", net.redact(e), file=sys.stderr)

	def post_text(self, text, buttons=None):
		"""chat.postMessage, without link previews, and with buttons (a Block Kit message) where they work. Slack's
		answer, or None when it failed or refused (logged): Slack refuses with HTTP 200 and ok false (not_in_channel,
		say), so a refusal is read from the answer."""
		if not config.env.slackBotToken:
			print(f"ERROR slack: a reply to channel {self.where} needs slackBotToken in finbot.env; not sent",
				file=sys.stderr)
			return None
		blocks = {}
		if buttons and not isinstance(buttons, dict) and self.takes_buttons:
			blocks['blocks'] = json.dumps(text_blocks(text, buttons))
		try:
			answer = slack_api('chat.postMessage', channel=self.where, text=text, unfurl_links='false',
				unfurl_media='false', **blocks)
		except Exception as e:
			print("Slack chat.postMessage to", self.where, "failed:", net.redact(e), file=sys.stderr)
			return None
		print("OK slack message to", self.where, file=sys.stderr)
		return answer

	def post_chart(self, image, caption, buttons=None):
		"""Upload the chart into the channel with the report as its message, the way Slack takes files since it retired
		files.upload: ask for an upload URL, send the bytes there, then complete the upload into the channel (the bot
		needs the files:write and files:read scopes). With period buttons, where they work, it goes in a Block Kit
		message instead (post_blocks), or without them if that fails. Slack's answer, MAYBE_SENT, or None if a step
		failed."""
		data = image.read() if hasattr(image, 'read') else bytes(image)
		if buttons and not isinstance(buttons, dict) and self.takes_buttons:
			try:
				return self.post_blocks(data, caption, buttons)
			except Exception as e:
				print("Slack chart with buttons failed, uploading it without them:", net.redact(e), file=sys.stderr)
		try:
			share = {'files': json.dumps([{'id': self.upload(data)}]), 'channel_id': self.where,
				'initial_comment': caption}
			try:
				output = slack_api('files.completeUploadExternal', **share)
			except requests.exceptions.ReadTimeout as e:
				print("Slack files.completeUploadExternal timed out, the chart may still arrive:", net.redact(e),
					file=sys.stderr)
				return MAYBE_SENT
		except Exception as e:
			print("Slack chart upload failed:", net.redact(e), file=sys.stderr)
			return None
		print("OK slack chart upload to", self.where, file=sys.stderr)
		return output

	def upload(self, data):
		"""Send a chart's bytes to Slack: the id of the file, not completed yet. Raises RuntimeError on a refusal."""
		ticket = slack_api('files.getUploadURLExternal', filename='chart.png', length=len(data))
		r = net.post(ticket['upload_url'], data=data)
		if r.status_code != 200:
			raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
		return ticket['file_id']

	def unshared(self, data):
		"""Upload a chart as a file that is in no channel, for an image block to show: its id."""
		file_id = self.upload(data)
		slack_api('files.completeUploadExternal', files=json.dumps([{'id': file_id, 'title': 'chart'}]))
		return file_id

	def post_blocks(self, data, caption, buttons):
		"""The chart in a Block Kit message, the report above it and the period buttons under it. Slack's answer, or
		MAYBE_SENT when posting the message timed out (it may have arrived); raises RuntimeError when Slack refuses."""
		file_id = self.unshared(data)
		blocks = chart_blocks(caption, buttons, file_id)
		try:
			answer = until_shown(lambda: slack_api('chat.postMessage', channel=self.where,
				text=caption[:SECTION_LIMIT], blocks=json.dumps(blocks), unfurl_links='false', unfurl_media='false'))
		except requests.exceptions.ReadTimeout as e:
			print("Slack chat.postMessage timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
		if answer.get('ts'):
			self.delete(self.shows(answer['ts'], file_id, caption, buttons))
		return answer

	def reshow(self, message, buttons):
		"""Show a chart message's period again from its upload of under SLACK_REUSE_SECONDS ago (for this message or
		another), with the report it came with: nothing is drawn or uploaded. True when it did; False when there is no
		such upload, or Slack refuses it (a file deleted outside finbot, say)."""
		view, now = marked(buttons), time.time()
		uploads = state.load(SLACK_CHARTS, {}).get('uploads', {})
		recent = [(at, file_id, caption) for file_id, (at, shows, caption) in uploads.items()
			if view and shows == view and now - at < SLACK_REUSE_SECONDS]
		if not recent:
			return False
		_, file_id, caption = max(recent)
		try:
			slack_api('chat.update', channel=self.where, ts=message, text=caption[:SECTION_LIMIT],
				blocks=json.dumps(chart_blocks(caption, buttons, file_id)))
		except Exception as e:
			print("Slack chat.update with an earlier upload failed, uploading anew:", net.redact(e), file=sys.stderr)
			return False
		self.delete(self.shows(message, file_id))
		return True

	def edit_chart(self, message, image, caption, buttons=None):
		"""Show another period in a chart message: the new chart uploaded (a file cannot be replaced) and shown in its
		image block, with its caption and buttons. A press for that period within SLACK_REUSE_SECONDS shows this upload
		again (reshow). Raises RuntimeError when Slack refuses the update."""
		if hasattr(image, 'seek'):
			image.seek(0)
		file_id = self.unshared(image.read() if hasattr(image, 'read') else bytes(image))
		blocks = chart_blocks(caption, buttons or [], file_id)
		until_shown(lambda: slack_api('chat.update', channel=self.where, ts=message, text=caption[:SECTION_LIMIT],
			blocks=json.dumps(blocks)))
		self.delete(self.shows(message, file_id, caption, buttons))

	def shows(self, message, file_id, caption=None, buttons=None):
		"""Note that a chart message shows this file now; given its report, that the file was uploaded now for the
		period its buttons mark (see reshow). The uploads to delete: those no message shows, a minute past their reuse
		(a press reusing one has that minute to show it)."""
		now = time.time()
		with state.edit(SLACK_CHARTS, {}) as noted:
			if set(noted) != {'shown', 'uploads'}: # new, or the {'channel ts': file} of before, whose files stay
				noted.clear()
				noted.update(shown={}, uploads={})
			shown, uploads = noted['shown'], noted['uploads'] # 'channel ts': file; file: [time, period, report]
			if caption is not None:
				uploads[file_id] = [now, marked(buttons), caption]
			key = f'{self.where} {message}'
			shown.pop(key, None)
			shown[key] = file_id
			for old in list(shown)[:-SLACK_CHARTS_KEPT]: # its message may show the file for good
				uploads.pop(shown.pop(old), None)
			showing = set(shown.values())
			gone = [old for old, (at, _, _) in uploads.items()
				if old not in showing and now - at > SLACK_REUSE_SECONDS + 60]
			for old in gone:
				del uploads[old]
			for upload in uploads.values(): # past reuse, a file shown is kept only to be deleted later
				if now - upload[0] >= SLACK_REUSE_SECONDS:
					upload[1:] = [None, None]
		return gone

	def delete(self, files):
		"""Delete uploaded charts that no message shows any more; a failure is only logged (the file stays among the
		bot's files, in no channel)."""
		for file_id in files:
			try:
				slack_api('files.delete', file=file_id)
			except Exception as e:
				print("Slack files.delete failed:", net.redact(e), file=sys.stderr)

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		data = {'channel': self.where, 'ts': message, 'text': text}
		if buttons is not None:
			data['blocks'] = json.dumps(text_blocks(text, buttons))
		try:
			slack_api('chat.update', **data)
		except Exception as e:
			print("Slack chat.update failed:", net.redact(e), file=sys.stderr)


class SlackWebhook(Transport):
	"""A Slack incoming webhook: text only, into the channel it was made for."""
	name = 'slack'
	dialect = dialects.SLACK

	def post_text(self, text, buttons=None):
		"""Post to the webhook, without link previews."""
		return self._post_json(self.where, {'text': text, 'unfurl_links': False, 'unfurl_media': False})


class DiscordWebhook(Transport):
	"""A Discord webhook's native endpoint (the Slack one takes no flags): no previews, no pings, charts attached."""
	name = 'discord'
	dialect = dialects.DISCORD
	takes_charts = True

	def url(self):
		"""The webhook URL that answers with the message posted (200) instead of an empty 204."""
		return self.where + ('&' if '?' in self.where else '?') + 'wait=true'

	def post_text(self, text, buttons=None):
		"""Post the message."""
		return self._post_json(self.url(), {'content': text, 'flags': SUPPRESS_EMBEDS, 'allowed_mentions': NO_MENTIONS})

	def post_chart(self, image, caption, buttons=None):
		"""The chart as an attachment, the report as its message: Discord's answer, MAYBE_SENT, or None if refused."""
		payload = {'content': caption, 'flags': SUPPRESS_EMBEDS, 'allowed_mentions': NO_MENTIONS,
			'attachments': [{'id': 0, 'filename': 'chart.png'}]}
		try:
			r = net.post(self.url(), data={'payload_json': json.dumps(payload)},
				files={'files[0]': ('chart.png', image, 'image/png')})
		except requests.exceptions.ReadTimeout as e:
			print("Discord chart timed out, it may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
		except Exception as e:
			print("Discord chart failed:", net.redact(e), file=sys.stderr)
			return None
		if r.status_code == 200:
			print(r.status_code, "OK discord chart", file=sys.stderr)
			try:
				return r.json() or {}
			except ValueError:
				return {}
		print(r.status_code, "error discord chart", net.redact(r.text[:300]), file=sys.stderr)
		return None


def slack_api(method, **data):
	"""POST a Slack Web API method as the bot (form-encoded) and return the answer; an error raises RuntimeError."""
	if not config.env.slackBotToken:
		raise RuntimeError(f"Slack {method}: needs slackBotToken in finbot.env")
	r = net.post('https://slack.com/api/' + method, headers={'Authorization': 'Bearer ' + config.env.slackBotToken},
		data=data)
	try:
		output = r.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Slack {method}: {output.get('error') or r.status_code}")
	return output


SECTION_LIMIT = 3000 # characters of text in a Block Kit section


def section_blocks(text):
	"""Block Kit sections of a message's text, as many as its length needs (none for no text)."""
	return [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(part)}}
		for part in chunked(text.split('\n'), SECTION_LIMIT) if '\n'.join(part).strip()]


def actions_block(row):
	"""A Block Kit row of buttons, the one shown now marked."""
	return {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': button.label},
		'value': button.data, 'action_id': button.data, **({'style': 'primary'} if button.active else {})}
		for button in row]}


def chart_blocks(caption, buttons, file_id):
	"""Block Kit for a chart message: the report, the chart (an uploaded file, by its id) and the buttons in one
	row."""
	row = [button for line in buttons for button in line]
	return section_blocks(caption) + [{'type': 'image', 'slack_file': {'id': file_id}, 'alt_text': 'chart'}] + \
		([actions_block(row)] if row else [])


def marked(buttons):
	"""The data of the button marked as shown now, which names a chart message's period (None when none is)."""
	return next((button.data for row in buttons or [] for button in row if button.active), None)


def text_blocks(text, buttons):
	"""Block Kit for a message with buttons: the text, then the buttons, a row of them to a block."""
	return section_blocks(text) + [actions_block(row) for row in buttons if row]


def until_shown(post, waits=(1, 2, 4)):
	"""post() of a message that shows a file just uploaded, tried again after each wait (in seconds) while Slack says
	invalid_blocks: a file can take a moment before it can be shown."""
	for wait in waits:
		try:
			return post()
		except RuntimeError as e:
			if 'invalid_blocks' not in str(e):
				raise
			print(f"Slack cannot show the chart yet ({e}), trying again in {wait} s", file=sys.stderr)
			time.sleep(wait)
	return post()


def chunked(lines, limit):
	"""The lines in messages of at most limit characters each, whole lines to a message; a line longer than limit on
	its own is cut short."""
	chunks, current, size = [], [], 0
	for line in lines:
		if len(line) > limit:
			line = line[:limit - 1] + '…'
		if current and size + 1 + len(line) > limit:
			chunks.append(current)
			current, size = [], 0
		size += len(line) + (1 if current else 0)
		current.append(line)
	if current:
		chunks.append(current)
	return chunks


def fit_caption(caption, dialect):
	"""The caption cut to the dialect's caption limit (none for Slack), as the network counts it (Telegram leaves the
	tags out): the whole lines that fit, and how many were left out."""
	limit = dialect.caption_limit
	if limit is None or dialect.visible(caption) <= limit:
		return caption
	lines = caption.split('\n')
	kept = []
	for line in lines:
		note = f"\n…and {len(lines) - len(kept) - 1} more in the chart"
		if dialect.visible('\n'.join(kept + [line])) + len(note) > limit:
			break
		kept.append(line)
	return '\n'.join(kept) + f"\n…and {len(lines) - len(kept)} more in the chart"
