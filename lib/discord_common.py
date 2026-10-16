"""Discord, whichever way its updates arrive (the gateway, discord_websocket; or the interactions endpoint,
discord_webhook): its REST API as the bot (discordBotToken), with calls that wait out Discord's rate limits and the
slash commands registered as finbot starts; the reader of its interactions and messages (Discord, READER); and the bot
that posts into its channels and DMs (DiscordBot)."""
import json
import re
import time

import requests

from lib import log
from lib import config
from lib import dialects
from lib import inbound
from lib import net
from lib import transports


API = 'https://discord.com/api/v10'
TRIES = 3 # a call that Discord rate-limits is tried this many times at most
LONGEST_WAIT = 10 # seconds: a rate limit asking for longer is waited this long
SUPPRESS_EMBEDS = 4 # message flag: no link previews
NO_MENTIONS = {'parse': []} # text that looks like @everyone or a mention pings nobody
GUILD, BOT_DM = 0, 1 # where a slash command may be used: in servers, and in a DM with the bot
OPTION = 'arguments' # the name of a slash command's one option: its arguments as text
USER_AGENT = 'DiscordBot (https://github.com/robdevops/finbot, {})' # the form Discord asks of every request's agent
version = 'unknown' # finbot's commit, for USER_AGENT: bot.py sets it as it starts


def call(method, path, **kwargs):
	"""A REST call as the bot: Discord's answer as JSON, or None when it is empty. A 429 waits as long as Discord asks
	(LONGEST_WAIT at most) and tries again. Raises RuntimeError with Discord's reason when it refuses, or a requests
	error."""
	headers = {'Authorization': 'Bot ' + config.env.discordBotToken, 'User-Agent': USER_AGENT.format(version),
		**kwargs.pop('headers', {})}
	for attempt in range(1, TRIES + 1):
		r = net.request(method, API + path, headers=headers, **kwargs)
		if r.status_code != 429 or attempt == TRIES:
			break
		time.sleep(min(retry_after(r), LONGEST_WAIT))
	if r.status_code >= 400:
		raise RuntimeError(f"Discord {method} {path}: {r.status_code} {reason(r)}")
	try:
		return r.json()
	except ValueError: # empty: 204 No Content
		return None


def try_call(method, path, **kwargs):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, path, **kwargs)
	except Exception as e:
		log.warn(f"Discord {method} failed:", net.redact(e))


def retry_after(response):
	"""The seconds a rate-limited answer asks to wait (its retry_after), or one when it does not say."""
	try:
		return float(response.json().get('retry_after'))
	except (ValueError, TypeError, AttributeError):
		return 1.0


def reason(response):
	"""Discord's reason for a refusal: its message and code, else the start of the body."""
	try:
		answer = response.json()
		return f"{answer['message']} ({answer.get('code')})"
	except (ValueError, TypeError, KeyError):
		return response.text[:200]


def command(name, description, arguments, completes=False):
	"""A slash command as Discord takes it: a chat command usable in servers and in a DM with the bot, and the arguments
	it takes, if any, as one optional text option that they describe; with completes, Discord asks finbot what to
	suggest as they are typed (an autocomplete interaction)."""
	option = {'type': 3, 'name': OPTION, 'description': arguments[:100], 'required': False, 'autocomplete': completes}
	return {'name': name, 'type': 1, 'description': description[:100], 'contexts': [GUILD, BOT_DM],
		'integration_types': [0], 'options': [option] if arguments else []}


def summary(commands):
	"""What of a list of slash commands Discord may differ on from ours, in a form to compare: an answer from Discord
	carries ids and versions besides."""
	return sorted((c['name'], c.get('description'), sorted(c.get('contexts') or []),
		[(o['name'], o.get('description'), o.get('required', False), o.get('autocomplete', False))
			for o in c.get('options') or []]) for c in commands)


def register(commands):
	"""Called once by bot.py as it starts, in both modes: make the application's slash commands these ([(name,
	description, arguments)], from worker.slash_commands), replacing them all only when they differ (Discord limits how
	many may be made in a day). Returns the bot's user id: a message that mentions it is for the bot. Raises
	RuntimeError, or a requests error."""
	application = call('GET', '/applications/@me')['id']
	wanted = [command(*entry) for entry in commands]
	path = f'/applications/{application}/commands'
	if summary(call('GET', path) or []) != summary(wanted):
		call('PUT', path, json=wanted)
		log.info(f"discord: {len(wanted)} slash commands registered")
	return str(call('GET', '/users/@me')['id'])


class Discord(inbound.Network):
	"""Discord's interactions (a slash command, a button pressed, the endpoint's check), which read the same from the
	interactions endpoint and the gateway, and the gateway's messages."""
	service = 'discord'
	bot_id = None # the bot's user id, from register() as bot.py starts: a message mentioning it is for the bot
	PING, COMMAND, COMPONENT, AUTOCOMPLETE = 1, 2, 3, 4 # interaction types
	PONG, THINKING, LATER, CHOICES = 1, 5, 6, 8 # answers: to the check, "thinking…" until the reply, nothing to see (a
	# press), the suggestions for what is being typed

	def update_id(self, update):
		"""The interaction's id, or the message's."""
		return update.get('id')

	def parse(self, update):
		"""An interaction (it has a token) or a gateway message."""
		return self.interaction(update) if 'token' in update else self.message(update)

	@property
	def bot_name(self):
		"""The bot as a message names it, @ and its user id (Discord's <@id> mention, read as Slack's are)."""
		return f'@{self.bot_id}' if self.bot_id else None

	def interaction(self, update):
		"""The endpoint's check (a PING, answered at once), a slash command as the message it stands for (/price 7d),
		its arguments as they are typed (a Suggest), or a button pressed under one of the bot's messages; anything else,
		UNSUPPORTED."""
		kind = update.get('type')
		if kind == self.PING:
			return inbound.Response(body=json.dumps({'type': self.PONG}).encode(), interaction=True)
		person = (update.get('member') or {}).get('user') or update.get('user') or {}
		channel = str(update.get('channel_id') or (update.get('channel') or {}).get('id') or '')
		through = f"{update.get('application_id')}/{update['token']}"
		data = update.get('data') or {}
		if kind == self.COMMAND and data.get('name'):
			given = ' '.join(str(option.get('value', '')) for option in data.get('options') or []).strip()
			text = f"/{data['name']} {given}".strip()
			return inbound.Message(self.service, channel, f"<@{person.get('id')}>", text, self.bot_name,
				self.name(person), interaction=through)
		if kind == self.AUTOCOMPLETE and data.get('name'):
			options = data.get('options') or []
			typed = next((str(option.get('value', '')) for option in options if option.get('focused')), '')
			return inbound.Suggest(self.service, channel, f"/{data['name']} {typed}", through)
		message = update.get('message') or {}
		if kind == self.COMPONENT and data.get('custom_id') and message.get('id'):
			return inbound.Press(self.service, str(update.get('id')), channel, str(message['id']), data['custom_id'],
				'@' + str(person.get('username') or person.get('id') or 'unknown'), through)
		return inbound.UNSUPPORTED

	def message(self, update):
		"""A message a person wrote (MESSAGE_CREATE); a mention <@id> reads as @id, as Slack's do. One by a bot (this
		one's replies included) or a webhook is OK: answering a bot could loop."""
		author = update.get('author') or {}
		if author.get('bot') or update.get('webhook_id') or not author.get('id') or 'content' not in update:
			return inbound.OK
		text = re.sub(r'<@!?(\d+)>', r'@\1', update['content'])
		return inbound.Message(self.service, str(update.get('channel_id')), f"<@{author['id']}>", text, self.bot_name,
			self.name(author), str(update.get('id', '')))

	@staticmethod
	def name(person):
		"""What to call someone: their display name, else their username."""
		return person.get('global_name') or person.get('username') or 'unknown'

	def acknowledge(self, event):
		"""An interaction's answer, which Discord must have within 3 seconds and before any reply: "thinking…" for a
		slash command, until the reply replaces it; nothing to see for a press, whose message is edited after. A
		gateway message needs none."""
		if not event.interaction:
			return None
		answer = self.THINKING if isinstance(event, inbound.Message) else self.LATER
		return inbound.Response(body=json.dumps({'type': answer}).encode(), interaction=True)

	def suggestions(self, choices):
		"""The answer to an autocomplete interaction: the choices, (name shown, value) pairs, 25 at most."""
		choices = [{'name': name, 'value': value} for name, value in choices[:25]]
		return inbound.Response(body=json.dumps({'type': self.CHOICES, 'data': {'choices': choices}}).encode(),
			interaction=True)


class DiscordBot(transports.Transport):
	"""A Discord channel or DM, as the bot (discordBotToken): no link previews, no pings, charts attached, buttons as
	components, edits in place, the typing notice. A slash command's first message replaces Discord's "thinking…" and
	the rest follow it up, through its interaction; a pressed message is edited through the press's."""
	name = 'discord'
	dialect = dialects.DISCORD

	def __init__(self, where, message=None, interaction='', pressed=False):
		"""As Transport; a press has no "thinking…" to replace, so its new messages go into the channel."""
		super().__init__(where, message, interaction, pressed)
		self.answered = pressed # the slash command's "thinking…" replaced

	@property
	def shows_typing(self):
		"""The typing notice for a command in a message; a slash command shows Discord's "thinking…" instead."""
		return not self.interaction

	def typing(self):
		"""POST /typing: "finbot is typing…" for ten seconds, or until it posts."""
		try_call('POST', f'/channels/{self.where}/typing')

	def typing_done(self):
		"""A slash command over with nothing said: its "thinking…" deleted, or it would show for 15 minutes."""
		if self.interaction and not self.answered:
			self.answered = True
			try_call('DELETE', f'/webhooks/{self.interaction}/messages/@original')

	@staticmethod
	def extras(buttons):
		"""What a message carries besides its text: no link previews, no pings, and its buttons as components."""
		extra = {'flags': SUPPRESS_EMBEDS, 'allowed_mentions': NO_MENTIONS}
		if buttons and not isinstance(buttons, dict):
			extra['components'] = components(buttons)
		return extra

	def post_text(self, text, buttons=None):
		"""Post one message (see post)."""
		return self.post({'content': text, **self.extras(buttons)})

	def post_chart(self, image, caption, buttons=None):
		"""Post a chart, attached to the report as its message (see post)."""
		attached = {'content': caption, 'attachments': [{'id': 0, 'filename': 'chart.png'}], **self.extras(buttons)}
		return self.post(attached, image)

	def post(self, payload, image=None):
		"""Post one message: a slash command's first replaces its "thinking…" and the rest follow it up; otherwise it
		goes into the channel. Discord's message; MAYBE_SENT when a chart's post timed out; None when it failed
		(logged)."""
		if self.interaction and not self.answered:
			method, path = 'PATCH', f'/webhooks/{self.interaction}/messages/@original'
		elif self.interaction and not self.pressed:
			method, path = 'POST', f'/webhooks/{self.interaction}'
		else:
			method, path = 'POST', f'/channels/{self.where}/messages'
		try:
			answer = call(method, path, **message_body(payload, image))
		except requests.exceptions.ReadTimeout as e:
			self.answered = True # it may have arrived
			log.warn("Discord post timed out, it may still arrive:", net.redact(e))
			return transports.MAYBE_SENT if image is not None else None
		except Exception as e:
			log.error("Discord post to", self.where, "failed:", net.redact(e))
			return None
		self.answered = True
		log.info("OK discord message to", self.where)
		return answer or {}

	def message_path(self, message):
		"""Where a message is edited: through the press's interaction where there is one (a message that answered a
		slash command can be edited only so), else in the channel as the bot."""
		if self.interaction:
			return f'/webhooks/{self.interaction}/messages/@original'
		return f'/channels/{self.where}/messages/{message}'

	def edit_chart(self, message, image, caption, buttons=None):
		"""Replace a chart message's image, caption and buttons in place. Raises RuntimeError when Discord refuses."""
		if hasattr(image, 'seek'):
			image.seek(0)
		payload = {'content': transports.fit_caption(caption, self.dialect),
			'attachments': [{'id': 0, 'filename': 'chart.png'}], 'components': components(buttons or [])}
		call('PATCH', self.message_path(message), **message_body(payload, image))

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		payload = {'content': text}
		if buttons is not None:
			payload['components'] = components(buttons)
		try_call('PATCH', self.message_path(message), json=payload)


DISCORD_ROW = 5 # buttons in a row of components, and rows in a message: Discord's limits


def components(buttons):
	"""Rows of buttons.Button as Discord's action rows: DISCORD_ROW buttons to a row and as many rows at most (the
	buttons past that are left out), the one shown now blurple and the rest grey."""
	flat = [button for row in buttons for button in row][:DISCORD_ROW * DISCORD_ROW]
	return [{'type': 1, 'components': [{'type': 2, 'style': 1 if button.active else 2, 'label': button.label[:80],
		'custom_id': button.data} for button in flat[i:i + DISCORD_ROW]]} for i in range(0, len(flat), DISCORD_ROW)]


def message_body(payload, image=None):
	"""A Discord message's request arguments: its JSON; with a chart, a form of the JSON and the PNG (bytes, so that a
	rate-limited call can send it again)."""
	if image is None:
		return {'json': payload}
	data = image.read() if hasattr(image, 'read') else bytes(image)
	return {'data': {'payload_json': json.dumps(payload)}, 'files': {'files[0]': ('chart.png', data, 'image/png')}}


READER = Discord()
