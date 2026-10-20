"""Discord, whichever way its updates arrive (the gateway, discord_websocket; or the interactions endpoint,
discord_webhook): its REST API as the bot (discordBotToken), with calls that wait out Discord's rate limits and the
slash commands registered as finbot starts; the reader of its interactions and messages (Discord, READER); and the bot
that posts into its channels and DMs (DiscordBot)."""
import json
import re

import requests

from lib import log
from lib import buttons
from lib import config
from lib import dialects
from lib import inbound
from lib import net
from lib import transports


API = 'https://discord.com/api/v10'
SUPPRESS_EMBEDS = 4 # message flag: no link previews
NO_MENTIONS = {'parse': []} # text that looks like @everyone or a mention pings nobody
GUILD, BOT_DM = 0, 1 # where a slash command may be used: in servers, and in a DM with the bot
OPTION = 'arguments' # the name of a slash command's one option: its arguments as text
USER_AGENT = 'DiscordBot (https://github.com/robdevops/finbot, {})' # the form Discord asks of every request's agent


def call(method, path, **kwargs):
	"""A REST call as the bot, its User-Agent naming finbot's commit: Discord's answer as JSON, or None when it is
	empty; a rate limit waited out once, as long as Discord asks (net.patiently). Raises RuntimeError with Discord's
	reason when it refuses, or a requests error."""
	headers = {'Authorization': 'Bot ' + config.env.discordBotToken,
		'User-Agent': USER_AGENT.format(config.git_version()), **kwargs.pop('headers', {})}
	return net.patiently(lambda: answer_of(net.request(method, API + path, headers=headers, **kwargs), method, path))


def answer_of(response, method, path):
	"""Discord's answer to a call as JSON, or None when it is empty (204 No Content). Raises RateLimited for a 429,
	RuntimeError with Discord's reason for another refusal."""
	if response.status_code >= 400:
		said = f"Discord {method} {path}: {response.status_code} {reason(response)}"
		raise net.RateLimited(said, net.retry_after(response)) if response.status_code == 429 else RuntimeError(said)
	try:
		return response.json()
	except ValueError:
		return None


def try_call(method, path, **kwargs):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, path, **kwargs)
	except Exception as e:
		log.warn(f"Discord {method} failed:", net.redact(e))


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
	option = {'type': 3, 'name': OPTION, 'description': fit(arguments), 'required': False, 'autocomplete': completes}
	return {'name': name, 'type': 1, 'description': fit(description), 'contexts': [GUILD, BOT_DM],
		'integration_types': [0], 'options': [option] if arguments else []}

def fit(text, most=100):
	"""A description within Discord's 100 characters: whole where it fits, else cut after the last of its usage lines
	(joined by ' | ') that does."""
	if len(text) <= most:
		return text
	cut = text.rfind(' | ', 0, most + 1)
	return text[:cut] if cut > 0 else text[:most]


def summary(commands):
	"""What of a list of slash commands Discord may differ on from ours, in a form to compare: an answer from Discord
	carries ids and versions besides."""
	return sorted((c['name'], c.get('description'), sorted(c.get('contexts') or []),
		[(o['name'], o.get('description'), o.get('required', False), o.get('autocomplete', False))
			for o in c.get('options') or []]) for c in commands)


def start(commands):
	"""Called once by bot.py as it starts, in both modes: the application's slash commands made these ([(name,
	description, arguments, completes)], from worker.slash_commands), replacing them all only when they differ (Discord
	limits how many may be made in a day), and the bot's user id noted (READER.bot_id): a message that mentions it is
	for the bot. Raises RuntimeError, or a requests error."""
	application = call('GET', '/applications/@me')['id']
	wanted = [command(*entry) for entry in commands]
	path = f'/applications/{application}/commands'
	if summary(call('GET', path) or []) != summary(wanted):
		call('PUT', path, json=wanted)
		log.info(f"discord: {len(wanted)} slash commands registered")
	READER.bot_id = str(call('GET', '/users/@me')['id'])


class Discord(inbound.Network):
	"""Discord's interactions (a slash command, a button pressed, the endpoint's check), which read the same from the
	interactions endpoint and the gateway, and the gateway's messages."""
	service = 'discord'
	bot_id = None # the bot's user id, noted as finbot starts (start): a message mentioning it is for the bot
	PING, COMMAND, COMPONENT, AUTOCOMPLETE = 1, 2, 3, 4 # interaction types
	PONG, MESSAGE, THINKING, LATER, CHOICES = 1, 4, 5, 6, 8 # answers: to the check, a message, "thinking…" until the
	# reply, nothing to see (a press), the suggestions for what is being typed
	EPHEMERAL = 64 # a message's flag: only the person who pressed (or typed) sees it

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
			log.info("Discord: endpoint check (a signed PING) answered")
			return inbound.Response(body=json.dumps({'type': self.PONG}).encode(), interaction=True)
		person = (update.get('member') or {}).get('user') or update.get('user') or {}
		channel = str(update.get('channel_id') or (update.get('channel') or {}).get('id') or '')
		through = f"{update.get('application_id')}/{update['token']}"
		data = update.get('data') or {}
		if kind == self.COMMAND and data.get('name'):
			given = ' '.join(str(option.get('value', '')) for option in data.get('options') or []).strip()
			text = f"/{data['name']} {given}".strip()
			return inbound.Message(self.service, channel, self.handle(person), text, self.bot_name, interaction=through,
				dm=self.dm(update), ids=self.ids(person))
		if kind == self.AUTOCOMPLETE and data.get('name'):
			options = data.get('options') or []
			typed = next((str(option.get('value', '')) for option in options if option.get('focused')), '')
			return inbound.Suggest(self.service, channel, f"/{data['name']} {typed}", through)
		message = update.get('message') or {}
		if kind == self.COMPONENT and data.get('custom_id') and message.get('id'):
			return inbound.Press(self.service, str(update.get('id')), channel, str(message['id']), data['custom_id'],
				self.handle(person), through, ids=self.ids(person))
		return inbound.UNSUPPORTED

	def message(self, update):
		"""A message a person wrote (MESSAGE_CREATE); a mention <@id> reads as @id, as Slack's do. One by a bot (this
		one's replies included) or a webhook is OK: answering a bot could loop."""
		author = update.get('author') or {}
		if author.get('bot') or update.get('webhook_id') or not author.get('id') or 'content' not in update:
			return inbound.OK
		text = re.sub(r'<@!?(\d+)>', r'@\1', update['content'])
		return inbound.Message(self.service, str(update.get('channel_id')), self.handle(author), text, self.bot_name,
			str(update.get('id', '')), dm=self.dm(update), ids=self.ids(author))

	@staticmethod
	def ids(person):
		"""What the admins setting may call a person: their user id."""
		return tuple(filter(None, (str(person.get('id') or ''),)))

	@staticmethod
	def dm(update):
		"""Whether an interaction or a message is in a direct message with the bot: it comes from no server (no
		guild_id, no member)."""
		return not (update.get('guild_id') or update.get('member'))

	@staticmethod
	def handle(person):
		"""What a reply calls someone: a mention of their id (posts ping nobody: NO_MENTIONS)."""
		return f"<@{person.get('id') or 'unknown'}>"

	def acknowledge(self, event, text=None, alert=False):
		"""An interaction's answer, which Discord must have within 3 seconds and before any reply: "thinking…" for a
		slash command, until the reply replaces it; for a press, nothing to see (Discord has no toast), its message
		edited after, or with alert the text in a message that the presser alone sees (a press refused). A gateway
		message needs none."""
		if not event.interaction:
			return None
		if alert:
			told = {'content': text, 'flags': self.EPHEMERAL, 'allowed_mentions': NO_MENTIONS}
			return inbound.Response(body=json.dumps({'type': self.MESSAGE, 'data': told}).encode(), interaction=True)
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

	ADMINISTRATOR = 0x8 # the permission that makes a role an administrator's

	def is_administrator(self, who):
		"""Whether this user owns the server this channel is in, or has a role with the Administrator permission; in a
		direct message, whether so in any server the bot is in."""
		guild = (call('GET', f'/channels/{self.where}') or {}).get('guild_id')
		if guild:
			return self.administers_server(guild, who)
		return any(self.administers_server(server['id'], who) for server in call('GET', '/users/@me/guilds') or ())

	@staticmethod
	def administers_server(guild, who):
		"""Whether this user owns the server (guild id), or has a role in it with the Administrator permission."""
		server = call('GET', f'/guilds/{guild}') or {}
		if str(server.get('owner_id')) == who:
			return True
		roles = set((call('GET', f'/guilds/{guild}/members/{who}') or {}).get('roles') or ())
		return any(int(role.get('permissions') or 0) & DiscordBot.ADMINISTRATOR
			for role in server.get('roles') or () if role.get('id') in roles or role.get('id') == guild)

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
		if buttons:
			extra['components'] = components(buttons)
		return extra

	def post_text(self, text, buttons=None):
		"""Post one message (see post)."""
		return self.post({'content': text, **self.extras(buttons)})

	def post_chart(self, photo, caption, buttons=None):
		"""Post a chart, attached to the report as its message (see post)."""
		attached = {'content': caption, 'attachments': [{'id': 0, 'filename': 'chart.png'}], **self.extras(buttons)}
		return self.post(attached, photo)

	def post(self, payload, photo=None):
		"""Post one message, with a chart where photo (its PNG bytes) is given: a slash command's first replaces its
		"thinking…" and the rest follow it up; otherwise it goes into the channel. Discord's message. Raises when it
		fails; MaybeSent when a chart's post timed out."""
		if self.interaction and not self.answered:
			method, path = 'PATCH', f'/webhooks/{self.interaction}/messages/@original'
		elif self.interaction and not self.pressed:
			method, path = 'POST', f'/webhooks/{self.interaction}'
		else:
			method, path = 'POST', f'/channels/{self.where}/messages'
		try:
			answer = call(method, path, **message_body(payload, photo))
		except requests.exceptions.ReadTimeout as e:
			self.answered = True # it may have arrived
			if photo is not None:
				raise transports.MaybeSent(e) from e
			raise
		self.answered = True
		return answer or {} # an answer without a body is a message sent all the same

	def message_path(self, message):
		"""Where a message is edited: through the press's interaction where there is one (a message that answered a
		slash command can be edited only so), else in the channel as the bot."""
		if self.interaction:
			return f'/webhooks/{self.interaction}/messages/@original'
		return f'/channels/{self.where}/messages/{message}'

	def replace_chart(self, message, photo, caption, buttons):
		"""Replace a chart message's image, caption and buttons in place. Raises RuntimeError when Discord refuses."""
		payload = {'content': caption, 'attachments': [{'id': 0, 'filename': 'chart.png'}],
			'components': components(buttons or [])}
		call('PATCH', self.message_path(message), **message_body(payload, photo), logged='debug')

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged."""
		payload = {'content': text}
		if buttons is not None:
			payload['components'] = components(buttons)
		try_call('PATCH', self.message_path(message), json=payload, logged='debug')

	def edit_buttons(self, message, buttons):
		"""The buttons under a message changed, its text and chart left as they are (an edit that names neither keeps
		them, with no upload): True when they show now; a failure is logged, and False."""
		return try_call('PATCH', self.message_path(message), json={'components': components(buttons)},
			logged='debug') is not None


DISCORD_ROW = 5 # buttons in a row of components, and rows in a message: Discord's limits
STYLES = {buttons.ON: 1, buttons.OFF: 4, buttons.ACTIVE: 1} # a button's style by its look; grey (2) for the rest


def components(buttons):
	"""Rows of buttons.Button as Discord's action rows: a row of at most DISCORD_ROW buttons (a longer one in rows of
	that), and as many rows at most (the buttons past that are left out), a toggle that is on, and the one shown now,
	blurple (Discord's selection colour), one that is off red, and the rest grey. A row of buttons that fits stays a
	row of its own, so a picker's period buttons keep theirs."""
	rows = [row[i:i + DISCORD_ROW] for row in buttons for i in range(0, len(row), DISCORD_ROW)][:DISCORD_ROW]
	return [{'type': 1, 'components': [{'type': 2, 'style': button_style(button), 'label': button.label[:80],
		'custom_id': button.data} for button in row]} for row in rows]


def button_style(button):
	"""The style number of a Discord button: 1 (blurple, its selection colour) for a toggle that is on and the one
	shown now, 4 (red) for a toggle that is off, else 2 (grey)."""
	return STYLES.get(buttons.look(button), 2)


def message_body(payload, photo=None):
	"""A Discord message's request arguments: its JSON; with a chart (its PNG bytes, which a rate-limited call can send
	again), a form of the JSON and the PNG."""
	if photo is None:
		return {'json': payload}
	return {'data': {'payload_json': json.dumps(payload)}, 'files': {'files[0]': ('chart.png', photo, 'image/png')}}


READER = Discord()
