"""Slack, whichever way its updates arrive (Socket Mode, slack_websocket; or the Request URL, slack_webhook): the Web
API calls, the reader of its events, button presses and slash commands (Slack, READER), and the bot that posts into
its channels (SlackBot), with the Block Kit of its messages."""
import concurrent.futures
import hashlib
import html
import json
import re
import threading
import time

import requests

from lib import log
from lib import config
from lib import dialects
from lib import inbound
from lib import net
from lib import state
from lib import transports


SLACK_CHARTS = 'finbot_slack_charts.json' # Slack's chart messages: the file each shows, and the charts uploaded
SLACK_CHARTS_KEPT = 500 # chart messages noted, newest last: an older one shows its file for good
SLACK_REUSE_SECONDS = 30 * 60 # a period pressed (or the same chart drawn) within this long of its upload shows it again


def call(method, as_app=False, logged=True, **data):
	"""POST a Slack Web API method (form-encoded) as the bot, or with the app-level token (as_app, for Socket Mode's
	apps.connections.open), and return the answer; an error raises RuntimeError. logged: as net logs the request."""
	key = 'slackAppToken' if as_app else 'slackBotToken'
	token = getattr(config.env, key)
	if not token:
		raise RuntimeError(f"Slack {method}: needs {key} in finbot.env")
	r = net.post('https://slack.com/api/' + method, headers={'Authorization': 'Bearer ' + token}, data=data,
		logged=logged)
	try:
		output = r.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Slack {method}: {output.get('error') or r.status_code}")
	return output


class Slack(inbound.Network):
	"""Slack's Events API (messages), its interactivity (a button pressed) and its slash commands."""
	service = 'slack'
	BY_PEOPLE = (None, 'thread_broadcast') # message subtypes a person writes; the rest are bot posts, edits, joins...

	def update_id(self, update):
		"""Slack's event_id (a button press has none)."""
		return update.get('event_id')

	def parse(self, update):
		"""A message a person wrote, a slash command, a button pressed, or the challenge that checks the URL."""
		kind = update.get('type')
		if 'command' in update and kind is None:
			return self.slash(update)
		if kind == 'url_verification':
			response = json.dumps({'challenge': update['challenge']})
			log.info("replying with", response)
			return inbound.Response(body=response.encode())
		if kind == 'block_actions':
			return self.press(update)
		if kind != 'event_callback':
			log.info(f"Slack unhandled 'type' {kind!r}")
			return inbound.UNHANDLED
		event = update['event']
		bot_user = update['authorizations'][0]['user_id'] # QWERTY
		if event.get('bot_id') or event.get('subtype') not in self.BY_PEOPLE or not event.get('user') or \
				event['user'] == bot_user: # not by a person: answering a bot (this one's replies included) could loop
			return inbound.OK
		if event['type'] not in ('message', 'app_mention') or 'text' not in event:
			log.info("Slack unhandled event callback type", event['type'])
			return inbound.UNHANDLED
		user = '<@' + event['user'] + '>' # a mention: Slack shows the name
		return inbound.Message(self.service, event['channel'], user, self.plain(event['text']), '@' + bot_user, user,
			event.get('ts', ''), ids=(event['user'],))

	def slash(self, update):
		"""A slash command (/price with 5 7d), as the message that says the same (/price 5 7d), in the channel or DM it
		was sent in. There is no message of it, for ⏳ to show on."""
		user = '<@' + str(update.get('user_id') or 'unknown') + '>'
		text = self.plain(f"{update['command']} {update.get('text') or ''}".strip())
		return inbound.Message(self.service, str(update.get('channel_id') or ''), user, text, '', user,
			ids=tuple(filter(None, (str(update.get('user_id') or ''),))))

	@staticmethod
	def plain(text):
		"""Text as written: links and mentions lose their markup (<http://dub.ax|dub.ax> becomes dub.ax, <@QWERTY>
		@QWERTY), and Slack's escapes their meaning (&amp; becomes &)."""
		text = re.sub(r'<((?:https?|mailto):[^|>]*)(?:\|([^>]*))?>', lambda m: m.group(2) or m.group(1), text)
		return html.unescape(re.sub(r'<(@[\w\.]+)>', r'\g<1>', text)) # Slack sends & < > as &amp; &lt; &gt;

	def press(self, update):
		"""A button pressed under one of the bot's messages, or UNSUPPORTED for one that is not under a message or
		carries no value."""
		container = update.get('container') or {}
		actions = update.get('actions') or [{}]
		value = actions[0].get('value') if isinstance(actions[0], dict) else None
		if container.get('type') != 'message' or not container.get('message_ts') or not value:
			return inbound.UNSUPPORTED
		user = update.get('user') or {}
		who = '@' + str(user.get('username') or user.get('id') or 'unknown')
		return inbound.Press(self.service, update.get('trigger_id', ''), container.get('channel_id', ''),
			container['message_ts'], value, who, ids=tuple(filter(None, (str(user.get('id') or ''),))))


class SlackBot(transports.Transport):
	"""A Slack channel, as the bot: chat.postMessage and the file upload, with slackBotToken."""
	name = 'slack'
	dialect = dialects.SLACK
	WORKING = 'hourglass_flowing_sand' # ⏳: Slack has no typing notice for bots, so a reaction on the message stands in
	working = None # True while ⏳ is on the message, False when putting it there failed
	preload_lock = threading.Lock()
	preload_slots = threading.BoundedSemaphore(2) # uploads wait on Slack's answers, so two go at once

	def wants(self, photo):
		"""Whether preloading a chart (its PNG bytes) would spare a press its upload: no upload of it in the last
		SLACK_REUSE_SECONDS (earlier_upload)."""
		return self.earlier_upload(digest_of(photo)) is None

	def retry_after(self, error):
		"""Ten seconds for Slack's rate limit ("ratelimited"), which does not say how long; None for another failure."""
		return 10.0 if 'ratelimited' in str(error) else None

	def send_all(self, photos):
		"""Preload charts Slack lacks, two uploads at a time (preload_slots), each starting preload_gap seconds after
		the last. False if any failed."""
		with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
			return all(list(pool.map(self.preload, photos)))

	def send_ahead(self, photo):
		"""Upload a chart into this channel, noted as shown by no message: a press within SLACK_REUSE_SECONDS shows it
		(earlier_upload), and shows deletes it a minute after unless a message comes to show it."""
		file_id = self.upload(photo)
		call('files.completeUploadExternal', files=json.dumps([{'id': file_id, 'title': 'chart'}]),
			channel_id=self.where)
		with state.edit(SLACK_CHARTS, {}) as noted:
			kept(noted)['uploads'][file_id] = [time.time(), None, '', digest_of(photo)]

	def is_administrator(self, who):
		"""Whether users.info says this user is an owner or an admin of the workspace (Slack's channels have no
		administrators of their own; the bot needs the users:read scope)."""
		person = call('users.info', user=who).get('user') or {}
		return bool(person.get('is_admin') or person.get('is_owner') or person.get('is_primary_owner'))

	@property
	def shows_typing(self):
		"""⏳ on the message being answered: a scheduled report answers none."""
		return bool(self.message)

	def typing(self):
		"""Put ⏳ on the message being answered, once (the bot needs the reactions:write scope); a failure is only
		logged, and not tried again."""
		if self.working is not None:
			return
		try:
			call('reactions.add', channel=self.where, timestamp=self.message, name=self.WORKING)
			self.working = True
		except Exception as e:
			self.working = False
			log.warn("Slack reactions.add failed:", net.redact(e))

	def typing_done(self):
		"""Take ⏳ off the message again; a failure is only logged."""
		if not self.working:
			return
		self.working = False
		try:
			call('reactions.remove', channel=self.where, timestamp=self.message, name=self.WORKING)
		except Exception as e:
			log.warn("Slack reactions.remove failed:", net.redact(e))

	def post_text(self, text, buttons=None):
		"""chat.postMessage, without link previews, and with buttons (a Block Kit message) where they work. Slack's
		answer, or None when it failed or refused (logged): Slack refuses with HTTP 200 and ok false (not_in_channel,
		say), so a refusal is read from the answer."""
		if not config.env.slackBotToken:
			log.error(f"ERROR slack: a reply to channel {self.where} needs slackBotToken in finbot.env; not sent")
			return None
		blocks = {}
		if buttons and not isinstance(buttons, dict) and self.takes_buttons:
			blocks['blocks'] = json.dumps(text_blocks(text, buttons))
		try:
			answer = call('chat.postMessage', channel=self.where, text=text, unfurl_links='false',
				unfurl_media='false', **blocks)
		except Exception as e:
			log.error("Slack chat.postMessage to", self.where, "failed:", net.redact(e))
			return None
		log.info("OK slack message to", self.where)
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
				log.warn("Slack chart with buttons failed, uploading it without them:", net.redact(e))
		try:
			share = {'files': json.dumps([{'id': self.upload(data)}]), 'channel_id': self.where,
				'initial_comment': caption}
			try:
				output = call('files.completeUploadExternal', **share)
			except requests.exceptions.ReadTimeout as e:
				log.warn("Slack files.completeUploadExternal timed out, the chart may still arrive:", net.redact(e))
				return transports.MAYBE_SENT
		except Exception as e:
			log.warn("Slack chart upload failed:", net.redact(e))
			return None
		log.info("OK slack chart upload to", self.where)
		return output

	def upload(self, data):
		"""Send a chart's bytes to Slack: the id of the file, not completed yet. Raises RuntimeError on a refusal."""
		ticket = call('files.getUploadURLExternal', filename='chart.png', length=len(data))
		r = net.post(ticket['upload_url'], data=data)
		if r.status_code != 200:
			raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
		return ticket['file_id']

	def unshared(self, data):
		"""Upload a chart as a file that is in no channel, for an image block to show: its id."""
		file_id = self.upload(data)
		call('files.completeUploadExternal', files=json.dumps([{'id': file_id, 'title': 'chart'}]))
		return file_id

	def earlier_upload(self, digest):
		"""The file of the chart whose PNG has this digest, uploaded (or shown as the same chart) under
		SLACK_REUSE_SECONDS ago: Slack shows it at once, and it is kept a minute past that (see shows). None when there
		is none."""
		now = time.time()
		uploads = state.load(SLACK_CHARTS, {}).get('uploads', {})
		found = [(upload[0], file_id) for file_id, upload in uploads.items()
			if upload[3:4] == [digest] and now - upload[0] < SLACK_REUSE_SECONDS]
		return max(found)[1] if found else None

	def showing(self, data, post):
		"""post(file id) of the message that shows a chart (its PNG bytes, data): with an earlier upload of the same
		chart where there is one (nothing is uploaded: a period or portfolio shown again), else, or when Slack will not
		show that one (a file deleted outside finbot), a new upload, tried again while Slack cannot show it yet
		(until_shown). (post's answer, the file's id, the chart's digest)."""
		digest = digest_of(data)
		if earlier := self.earlier_upload(digest):
			try:
				return post(earlier), earlier, digest
			except RuntimeError as e:
				if 'invalid_blocks' not in str(e):
					raise
				log.warn("Slack will not show an earlier upload of the chart, uploading it anew:", net.redact(e))
				self.forget(earlier)
		file_id = self.unshared(data)
		return until_shown(lambda: post(file_id)), file_id, digest

	def post_blocks(self, data, caption, buttons):
		"""The chart in a Block Kit message, the report above it and the period buttons under it, the chart an earlier
		upload where there is one (showing). Slack's answer, or MAYBE_SENT when posting the message timed out (it may
		have arrived); raises RuntimeError when Slack refuses."""
		try:
			answer, file_id, digest = self.showing(data, lambda file_id: call('chat.postMessage', channel=self.where,
				text=caption[:SECTION_LIMIT], blocks=json.dumps(chart_blocks(caption, buttons, file_id)),
				unfurl_links='false', unfurl_media='false'))
		except requests.exceptions.ReadTimeout as e:
			log.warn("Slack chat.postMessage timed out, the chart may still arrive:", net.redact(e))
			return transports.MAYBE_SENT
		if answer.get('ts'):
			self.delete(self.shows(answer['ts'], file_id, caption, buttons, digest))
		return answer

	def reshow(self, message, buttons):
		"""Show a chart message's period again from its upload of under SLACK_REUSE_SECONDS ago (for this message or
		another in its chat), with the report it came with: nothing is drawn or uploaded. True when it did; False when
		there is no such upload, or Slack refuses it (a file deleted outside finbot, say: then it is forgotten)."""
		view, now = self.view(buttons), time.time()
		uploads = state.load(SLACK_CHARTS, {}).get('uploads', {})
		recent = [(upload[0], file_id, upload[2]) for file_id, upload in uploads.items()
			if view and upload[1] == view and now - upload[0] < SLACK_REUSE_SECONDS]
		if not recent:
			return False
		_, file_id, caption = max(recent)
		try:
			call('chat.update', channel=self.where, ts=message, text=caption[:SECTION_LIMIT],
				blocks=json.dumps(chart_blocks(caption, buttons, file_id)), logged='debug')
		except Exception as e:
			log.warn("Slack chat.update with an earlier upload failed, uploading anew:", net.redact(e))
			if 'invalid_blocks' in str(e):
				self.forget(file_id)
			return False
		self.delete(self.shows(message, file_id))
		return True

	def forget(self, file_id):
		"""Show an upload no more: Slack will not show it (a file deleted outside finbot, say)."""
		with state.edit(SLACK_CHARTS, {}) as noted:
			noted.get('uploads', {}).pop(file_id, None)

	def edit_chart(self, message, image, caption, buttons=None):
		"""Show another period (or portfolio) in a chart message, in its image block with its caption and buttons: an
		earlier upload of the same chart, else the new chart uploaded (a file cannot be replaced; see showing). A press
		for that period within SLACK_REUSE_SECONDS shows this upload again (reshow). Raises RuntimeError when Slack
		refuses the update."""
		if hasattr(image, 'seek'):
			image.seek(0)
		_, file_id, digest = self.showing(image.read() if hasattr(image, 'read') else bytes(image),
			lambda file_id: call('chat.update', channel=self.where, ts=message, text=caption[:SECTION_LIMIT],
			blocks=json.dumps(chart_blocks(caption, buttons or [], file_id)), logged='debug'))
		self.delete(self.shows(message, file_id, caption, buttons, digest))

	def shows(self, message, file_id, caption=None, buttons=None, digest=None):
		"""Note that a chart message shows this file now; given its report, that the file was uploaded (or found to be
		the chart drawn, whose PNG has this digest) now for the view its buttons mark (see reshow and earlier_upload).
		The uploads to delete: those no message shows, a minute past their reuse (a press reusing one has that minute
		to show it)."""
		now = time.time()
		with state.edit(SLACK_CHARTS, {}) as noted:
			shown, uploads = kept(noted)['shown'], noted['uploads'] # see kept
			if caption is not None:
				uploads[file_id] = [now, self.view(buttons), caption] + ([digest] if digest else [])
			key = f'{self.where} {message}'
			shown.pop(key, None)
			shown[key] = file_id
			for old in list(shown)[:-SLACK_CHARTS_KEPT]: # its message may show the file for good
				uploads.pop(shown.pop(old), None)
			showing = set(shown.values())
			gone = [old for old, upload in uploads.items()
				if old not in showing and now - upload[0] > SLACK_REUSE_SECONDS + 60]
			for old in gone:
				del uploads[old]
			for upload in uploads.values(): # past reuse, a file shown is kept only to be deleted later
				if now - upload[0] >= SLACK_REUSE_SECONDS:
					upload[1:] = [None, None] # its view, report and digest
		return gone

	def delete(self, files):
		"""Delete uploaded charts that no message shows any more; a failure is only logged (the file stays among the
		bot's files, in no channel)."""
		for file_id in files:
			try:
				call('files.delete', file=file_id)
			except Exception as e:
				log.warn("Slack files.delete failed:", net.redact(e))

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		data = {'channel': self.where, 'ts': message, 'text': text}
		if buttons is not None:
			data['blocks'] = json.dumps(text_blocks(text, buttons))
		try:
			call('chat.update', logged='debug', **data)
		except Exception as e:
			log.warn("Slack chat.update failed:", net.redact(e))


def digest_of(data):
	"""A chart's PNG bytes as a short digest, which tells the same chart again (earlier_upload)."""
	return hashlib.sha1(data).hexdigest()[:20]


def kept(noted):
	"""SLACK_CHARTS's record as shows keeps it, {'shown': {'channel ts': file}, 'uploads': {file: [time, view, report,
	digest]}}: started anew where it is new, or the {'channel ts': file} of before, whose files stay."""
	if set(noted) != {'shown', 'uploads'}:
		noted.clear()
		noted.update(shown={}, uploads={})
	return noted


SECTION_LIMIT = 3000 # characters of text in a Block Kit section


def section_blocks(text):
	"""Block Kit sections of a message's text, as many as its length needs (none for no text)."""
	return [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(part)}}
		for part in transports.chunked(text.split('\n'), SECTION_LIMIT) if '\n'.join(part).strip()]


def actions_block(row):
	"""A Block Kit row of buttons, the one shown now marked."""
	return {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': button.label},
		'value': button.data, 'action_id': button.data, **({'style': 'primary'} if button.active else {})}
		for button in row]}


def chart_blocks(caption, buttons, file_id):
	"""Block Kit for a chart message: the report, the chart (an uploaded file, by its id) and the buttons, a row of
	them to a block."""
	return section_blocks(caption) + [{'type': 'image', 'slack_file': {'id': file_id}, 'alt_text': 'chart'}] + \
		[actions_block(row) for row in buttons if row]


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
			log.info(f"Slack cannot show the chart yet ({e}), trying again in {wait} s")
			time.sleep(wait)
	return post()


READER = Slack()
