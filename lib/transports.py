"""How a message gets to each network: a class per way of posting, made for one destination (a chat, or an incoming
webhook). A transport knows its dialect, what it can carry (charts, buttons, a typing notice) and the network's size
limits; text() and chart() are the same everywhere, and each network posts one message its own way (post_text,
post_chart)."""
import json
import sys
import time

import requests

from lib import config
from lib import dialects
from lib import net
from lib import telegram

MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows
SUPPRESS_EMBEDS = 4 # Discord message flag: no link previews
NO_MENTIONS = {'parse': []} # Discord: text that looks like @everyone or a mention pings nobody


class Transport:
	"""A destination. Subclasses set what it carries and post one message; the base splits and trims."""
	name = '' # the network, in logs
	dialect = None
	takes_charts = False # a chart, with the report as its caption
	takes_buttons = False # buttons under a message
	shows_typing = False # a typing notice while a command works

	def __init__(self, where, message=None):
		"""where: the chat id, or the incoming webhook's URL; message: the id of the message being answered, if any."""
		self.where = where
		self.message = message

	def __repr__(self):
		"""<TelegramBot 55>: the kind and where, for logs and test failures."""
		return f'<{type(self).__name__} {self.where}>'

	def text(self, lines, buttons=None):
		"""Post lines of text: one message, or several when they are too long for one (then at most chunk_maxlines lines
		each), buttons under the last. Returns the network's answer for each message (None for one that failed)."""
		lines = [str(line) for line in lines]
		if not lines:
			return []
		limit = self.dialect.text_limit
		if len('\n'.join(lines)) <= limit:
			return [self.post_text('\n'.join(lines), buttons)]
		chunks = chunked(lines, limit, config.prefs.chunk_maxlines)
		answers = []
		for i, chunk in enumerate(chunks):
			if i:
				time.sleep(0.5) # Telegram takes about one message a second in a chat
			answers.append(self.post_text('\n'.join(chunk), buttons if i == len(chunks) - 1 else None))
		return answers

	def chart(self, image, caption, buttons=None):
		"""Post a chart, the caption under it cut to fit: the network's answer, MAYBE_SENT, or None if it failed."""
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
		"""Show the typing notice, where the network has one."""

	def typing_done(self):
		"""End the typing notice, where it lasts until ended (Slack's ⏳)."""

	def _post_json(self, url, payload, headers=None):
		"""POST a JSON message: the answer ({} when it is not JSON), or None when the network refused it or failed."""
		try:
			r = net.post(url, headers={'Content-type': 'application/json', **(headers or {})}, json=payload,
				timeout=config.prefs.http_timeout)
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
		"""sendMessage."""
		payload = {'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': 'true',
			'disable_notification': 'true'}
		if buttons:
			payload['reply_markup'] = self.markup(buttons)
		return self._post_json(config.env.webhooks['telegram'] + 'sendMessage?chat_id=' + str(self.where), payload)

	def post_chart(self, image, caption, buttons=None):
		"""sendPhoto, the report as its caption."""
		data = {'disable_notification': True, 'chat_id': self.where, 'caption': caption, 'parse_mode': 'HTML',
			'disable_web_page_preview': True}
		if buttons:
			data['reply_markup'] = json.dumps(self.markup(buttons))
		try:
			r = net.post(config.env.webhooks['telegram'] + 'sendPhoto?chat_id=' + str(self.where), data=data,
				files={'photo': ('image.png', image)}, timeout=config.prefs.http_timeout)
		except requests.exceptions.ReadTimeout as e:
			print("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
		except Exception as e:
			print("Telegram sendPhoto failed:", net.redact(e), file=sys.stderr)
			return None
		try:
			output = r.json()
		except ValueError:
			output = {}
		if r.status_code == 200 and output.get('ok'):
			return output
		print(r.status_code, "error telegram sendPhoto", output.get('error_code'),
			output.get('description') or r.text[:300], file=sys.stderr)
		return None

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

	def pin(self, answers):
		"""Pin the messages these answers are for, last first, so the first ends up on top, without the notification."""
		sent = []
		for answer in answers:
			try:
				sent.append((answer['result']['chat']['id'], answer['result']['message_id']))
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
		"""chat.postMessage, without link previews (Slack reads those flags from the body)."""
		if not config.env.slackBotToken:
			print(f"ERROR slack: a reply to channel {self.where} needs slackBotToken in finbot.env; not sent",
				file=sys.stderr)
			return None
		payload = {'text': text, 'unfurl_links': False, 'unfurl_media': False, 'channel': self.where}
		return self._post_json('https://slack.com/api/chat.postMessage', payload,
			{'Authorization': 'Bearer ' + config.env.slackBotToken})

	def post_chart(self, image, caption, buttons=None):
		"""Upload the chart into the channel with the report as its message, the way Slack takes files since it retired
		files.upload: ask for an upload URL, send the bytes there, then complete the upload into the channel (the bot
		needs the files:write and files:read scopes). Slack's answer, MAYBE_SENT, or None if a step failed."""
		data = image.read() if hasattr(image, 'read') else bytes(image)
		try:
			ticket = slack_api('files.getUploadURLExternal', filename='chart.png', length=len(data))
			r = net.post(ticket['upload_url'], data=data, timeout=config.prefs.http_timeout)
			if r.status_code != 200:
				raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
			share = {'files': json.dumps([{'id': ticket['file_id']}]), 'channel_id': self.where,
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
				files={'files[0]': ('chart.png', image, 'image/png')}, timeout=config.prefs.http_timeout)
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
		data=data, timeout=config.prefs.http_timeout)
	try:
		output = r.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Slack {method}: {output.get('error') or r.status_code}")
	return output


def chunked(lines, limit, max_lines):
	"""The lines in messages of at most max_lines lines and limit characters each, whichever comes first; a line longer
	than limit on its own is cut short."""
	chunks, current, size = [], [], 0
	for line in lines:
		if len(line) > limit:
			line = line[:limit - 1] + '…'
		if current and (len(current) >= max_lines or size + 1 + len(line) > limit):
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
