"""Slack, whichever way its updates arrive (Socket Mode, slack_websocket; or the Request URL, slack_webhook): the Web
API calls, the reader of its events, button presses and slash commands (Slack, READER), and the bot that posts into
its channels (SlackBot), with the Block Kit of its messages."""
import hashlib
import html
import json
import re
import time

import requests

from lib import log
from lib import buttons
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
	apps.connections.open), and return the answer, a rate limit waited out once (net.patiently); an error raises
	RuntimeError. logged: as net logs the request."""
	key = 'slackAppToken' if as_app else 'slackBotToken'
	token = getattr(config.env, key)
	if not token:
		raise RuntimeError(f"Slack {method}: needs {key} in finbot.env")
	return net.patiently(lambda: net.ok_answer(net.post('https://slack.com/api/' + method,
		headers={'Authorization': 'Bearer ' + token}, data=data, logged=logged), f"Slack {method}", 'error'))


def try_call(method, **data):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, **data)
	except Exception as e:
		log.warn(f"Slack {method} failed:", net.redact(e))


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
		return inbound.Message(self.service, event['channel'], self.handle(event['user']), self.plain(event['text']),
			'@' + bot_user, event.get('ts', ''), ids=(event['user'],))

	def slash(self, update):
		"""A slash command (/price with 5 7d), as the message that says the same (/price 5 7d), in the channel or DM it
		was sent in. There is no message of it, for ⏳ to show on."""
		text = self.plain(f"{update['command']} {update.get('text') or ''}".strip())
		return inbound.Message(self.service, str(update.get('channel_id') or ''), self.handle(update.get('user_id')),
			text, '', ids=tuple(filter(None, (str(update.get('user_id') or ''),))))

	@staticmethod
	def handle(user_id):
		"""What a reply calls a Slack user: a mention of their id, which Slack shows as their name."""
		return f"<@{user_id or 'unknown'}>"

	@staticmethod
	def plain(text):
		"""Text as written: links and mentions lose their markup (<http://dub.ax|dub.ax> becomes dub.ax, <@QWERTY>
		@QWERTY), and Slack's escapes their meaning (&amp; becomes &)."""
		text = re.sub(r'<((?:https?|mailto):[^|>]*)(?:\|([^>]*))?>', lambda m: m.group(2) or m.group(1), text)
		return html.unescape(re.sub(r'<(@[\w\.]+)>', r'\g<1>', text)) # Slack sends & < > as &amp; &lt; &gt;

	def acknowledge(self, event, text=None, alert=False):
		"""A press refused (alert): the text posted to the presser alone (chat.postEphemeral) once Slack has the press
		(the 200, or the socket's ack, is the acknowledgement of every update); a failure is only logged."""
		if not (alert and isinstance(event, inbound.Press) and event.ids):
			return None
		return inbound.Response(then=lambda: try_call('chat.postEphemeral', channel=event.chat_id, user=event.ids[0],
			text=text))

	def press(self, update):
		"""A button pressed under one of the bot's messages, or UNSUPPORTED for one that is not under a message or
		carries no value."""
		container = update.get('container') or {}
		actions = update.get('actions') or [{}]
		value = actions[0].get('value') if isinstance(actions[0], dict) else None
		if container.get('type') != 'message' or not container.get('message_ts') or not value:
			return inbound.UNSUPPORTED
		user = update.get('user') or {}
		return inbound.Press(self.service, update.get('trigger_id', ''), container.get('channel_id', ''),
			container['message_ts'], value, self.handle(user.get('id')), ids=tuple(filter(None, (str(user.get('id') or
			''),))))


class SlackBot(transports.Transport):
	"""A Slack channel, as the bot: chat.postMessage and the file upload, with slackBotToken."""
	name = 'slack'
	dialect = dialects.SLACK
	WORKING = 'hourglass_flowing_sand' # ⏳: Slack has no typing notice for bots, so a reaction on the message stands in
	CHUNK_GAP = 0.5 # Slack takes about one message a second in a channel
	PRELOAD_CHAT = 'slack_preload_chat'
	working = None # True while ⏳ is on the message, False when putting it there failed

	@property
	def dm(self):
		"""Whether the channel is a direct message: its id starts with D."""
		return self.where.startswith('D')

	def wants(self, photo):
		"""Whether preloading a chart (its PNG bytes) would spare a press its upload: no upload of it in the last
		SLACK_REUSE_SECONDS (earlier_upload)."""
		return self.earlier_upload(digest_of(photo)) is None

	def send_ahead(self, photo):
		"""Upload a chart into this channel, noted as shown by no message: a press within SLACK_REUSE_SECONDS shows it
		(earlier_upload), and shows deletes it a minute after unless a message comes to show it."""
		file_id, _ = self.upload(photo, channel_id=self.where)
		with state.edit(SLACK_CHARTS, {}) as noted:
			kept(noted)['uploads'][file_id] = {'at': time.time(), 'view': None, 'caption': '',
				'digest': digest_of(photo)}

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
		if self.working is None:
			self.working = try_call('reactions.add', channel=self.where, timestamp=self.message,
				name=self.WORKING) is not None

	def typing_done(self):
		"""Take ⏳ off the message again; a failure is only logged."""
		if self.working:
			self.working = False
			try_call('reactions.remove', channel=self.where, timestamp=self.message, name=self.WORKING)

	def post_text(self, text, buttons=None):
		"""chat.postMessage, without link previews, and with buttons (a Block Kit message) where they work: Slack's
		answer. Slack refuses with HTTP 200 and ok false (not_in_channel, say), which raises (call)."""
		blocks = {'blocks': json.dumps(text_blocks(text, buttons))} if buttons and not isinstance(buttons, dict) else {}
		return call('chat.postMessage', channel=self.where, text=text, unfurl_links='false', unfurl_media='false',
			**blocks)

	def post_chart(self, photo, caption, buttons=None):
		"""The chart uploaded into the channel with the report as its message (upload). With period buttons, where they
		work, it goes in a Block Kit message instead (post_blocks), or without them if that fails. Slack's answer;
		raises when a step fails, MaybeSent when the request that posts it timed out."""
		if buttons and not isinstance(buttons, dict):
			try:
				return self.post_blocks(photo, caption, buttons)
			except transports.MaybeSent:
				raise
			except Exception as e:
				log.warn("Slack chart with buttons failed, uploading it without them:", net.redact(e))
		return self.upload(photo, channel_id=self.where, initial_comment=caption)[1]

	def upload(self, photo, **share):
		"""Upload a chart (its PNG bytes) as Slack takes files since it retired files.upload: ask for an upload URL,
		send the bytes there, then complete the upload as a file titled chart, shared as `share` says (channel_id, and
		an initial_comment: a message in the channel), else in no channel, for an image block to show (the bot needs
		the files:write and files:read scopes). (the file's id, Slack's answer to completing it). Raises RuntimeError
		on a refusal; MaybeSent when completing it into a channel, which posts it, timed out."""
		ticket = call('files.getUploadURLExternal', filename='chart.png', length=len(photo))
		r = net.post(ticket['upload_url'], data=photo)
		if r.status_code != 200:
			raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
		try:
			return ticket['file_id'], call('files.completeUploadExternal',
				files=json.dumps([{'id': ticket['file_id'], 'title': 'chart'}]), **share)
		except requests.exceptions.ReadTimeout as e:
			if 'channel_id' in share:
				raise transports.MaybeSent(e) from e
			raise

	def earlier_upload(self, digest):
		"""The file of the chart whose PNG has this digest, uploaded (or shown as the same chart) under
		SLACK_REUSE_SECONDS ago: Slack shows it at once, and it is kept a minute past that (see shows). None when there
		is none."""
		now = time.time()
		found = [(upload['at'], file_id) for file_id, upload in uploads().items()
			if upload.get('digest') == digest and now - upload['at'] < SLACK_REUSE_SECONDS]
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
		file_id, _ = self.upload(data)
		return until_shown(lambda: post(file_id)), file_id, digest

	def post_blocks(self, photo, caption, buttons):
		"""The chart in a Block Kit message, the report above it and the period buttons under it, the chart an earlier
		upload where there is one (showing): Slack's answer. Raises when an upload fails (no message exists yet) or
		Slack refuses; MaybeSent when posting the message timed out (it may have arrived)."""
		def post(file_id):
			"""chat.postMessage of the blocks that show the chart."""
			try:
				return call('chat.postMessage', channel=self.where, text=caption[:SECTION_LIMIT], unfurl_links='false',
					blocks=json.dumps(chart_blocks(caption, buttons, file_id)), unfurl_media='false')
			except requests.exceptions.ReadTimeout as e:
				raise transports.MaybeSent(e) from e
		answer, file_id, digest = self.showing(photo, post)
		if answer.get('ts'):
			self.delete(self.shows(answer['ts'], file_id, caption, buttons, digest))
		return answer

	def reshow(self, message, buttons):
		"""Show a chart message's period again from its upload of under SLACK_REUSE_SECONDS ago (for this message or
		another in its chat), with the report it came with: nothing is drawn or uploaded. True when it did; False when
		there is no such upload, or Slack refuses it (a file deleted outside finbot, say: then it is forgotten)."""
		view, now = self.view(buttons), time.time()
		recent = [(upload['at'], file_id, upload.get('caption')) for file_id, upload in uploads().items()
			if view and upload.get('view') == view and now - upload['at'] < SLACK_REUSE_SECONDS]
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

	def replace_chart(self, message, photo, caption, buttons):
		"""Show another period (or portfolio) in a chart message, in its image block with its caption and buttons: an
		earlier upload of the same chart, else the new chart uploaded (a file cannot be replaced; see showing). A press
		for that period within SLACK_REUSE_SECONDS shows this upload again (reshow). Raises RuntimeError when Slack
		refuses the update."""
		_, file_id, digest = self.showing(photo,
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
				uploads[file_id] = {'at': now, 'view': self.view(buttons), 'caption': caption, 'digest': digest}
			key = f'{self.where} {message}'
			shown.pop(key, None)
			shown[key] = file_id
			for old in list(shown)[:-SLACK_CHARTS_KEPT]: # its message may show the file for good
				uploads.pop(shown.pop(old), None)
			showing = set(shown.values())
			gone = [old for old, upload in uploads.items()
				if old not in showing and now - upload['at'] > SLACK_REUSE_SECONDS + 60]
			for old in gone:
				del uploads[old]
			for upload in uploads.values(): # past reuse, a file shown is kept only to be deleted later
				if now - upload['at'] >= SLACK_REUSE_SECONDS:
					upload.update(view=None, caption=None, digest=None)
		return gone

	def delete(self, files):
		"""Delete uploaded charts that no message shows any more; a failure is only logged (the file stays among the
		bot's files, in no channel)."""
		for file_id in files:
			try_call('files.delete', file=file_id)

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		data = {'channel': self.where, 'ts': message, 'text': text}
		if buttons is not None:
			data['blocks'] = json.dumps(text_blocks(text, buttons))
		try_call('chat.update', logged='debug', **data)


def digest_of(data):
	"""A chart's PNG bytes as a short digest, which tells the same chart again (earlier_upload)."""
	return hashlib.sha1(data).hexdigest()[:20]


def kept(noted):
	"""SLACK_CHARTS's record as shows keeps it, {'shown': {'channel ts': file}, 'uploads': {file: {'at': when uploaded,
	'view', 'caption': its report, 'digest': its PNG's}}}: started anew where it is new, or of an earlier form (the
	{'channel ts': file} of before, or uploads as lists), whose files stay."""
	if set(noted) != {'shown', 'uploads'} or not all(isinstance(upload, dict) for upload in noted['uploads'].values()):
		noted.clear()
		noted.update(shown={}, uploads={})
	return noted


def uploads():
	"""The charts uploaded, as shows notes them (kept): {file id: {'at', 'view', 'caption', 'digest'}}."""
	return kept(state.load(SLACK_CHARTS, {}))['uploads']


SECTION_LIMIT = 3000 # characters of text in a Block Kit section
STYLES = {buttons.OFF: 'danger', buttons.ON: 'primary', buttons.ACTIVE: 'primary'} # a button's style by its look


def section_blocks(text):
	"""Block Kit sections of a message's text, as many as its length needs (none for no text)."""
	return [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': '\n'.join(part)}}
		for part in transports.chunked(text.split('\n'), SECTION_LIMIT) if '\n'.join(part).strip()]


def button_style(button):
	"""The Block Kit style of a button (STYLES): danger (red) for a toggle that is off, primary (green) for one that is
	on or the one shown now; none for the rest."""
	style = STYLES.get(buttons.look(button))
	return {'style': style} if style else {}


def actions_block(row):
	"""A Block Kit row of buttons, the one shown now marked, a toggle green (on) or red (off)."""
	return {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': button.label},
		'value': button.data, 'action_id': button.data, **button_style(button)} for button in row]}


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
