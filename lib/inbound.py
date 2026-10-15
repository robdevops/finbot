"""What the networks send the bot. Reading an update is apart from how it arrives: a class per network reads its updates
(Telegram, Slack, Discord), and a class per way of arriving takes them in (a webhook: the path the network posts to,
how it proves itself, the body), so that another way (a pull mode) can hand its updates to the same reader. An update
becomes a Message to answer, a Press of a button, or a Response the network gets straight back (a challenge, or nothing
to do). The reader also acknowledges an update where the network waits for that, however it arrived: Telegram's press
with a call, Discord's interaction with the answer it must have before any reply."""
import dataclasses
import hashlib
import hmac
import html
import json
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

from lib import buttons
from lib import config
from lib import telegram


@dataclasses.dataclass
class Message:
	"""A chat message to answer (worker.process_request)."""
	service: str
	chat_id: str
	user: str # the sender's handle: whose watchlist add or plan it is
	text: str
	bot_name: str # the bot's @name, which can start a command
	user_name: str # what to call them
	message_id: str = '' # the message itself: Slack shows ⏳ on it while finbot works
	interaction: str = '' # Discord's slash command: its application id and token, to answer through


@dataclasses.dataclass
class Press:
	"""A button pressed under one of the bot's messages (worker.process_callback)."""
	service: str
	press_id: str # the network's id for the press, to answer it
	chat_id: str
	message_id: str
	data: str
	user: str = '' # who pressed it, for the log
	interaction: str = '' # Discord's press: its application id and token, to edit the message pressed through


@dataclasses.dataclass
class Suggest:
	"""A slash command's arguments as they are typed (Discord's autocomplete), to answer at once with what to suggest:
	the message they make so far (/price 5 7), which the suggestions complete."""
	service: str
	chat_id: str
	text: str
	interaction: str = '' # Discord's interaction: its application id and token


@dataclasses.dataclass
class Response:
	"""What the network gets back at once: a status and a body; and the work to start once it has them (`then`), when
	the network must have this answer before any reply (Discord's deferred answer to an interaction). An interaction's
	answer (`interaction`) is the HTTP response on Discord's interactions endpoint, and goes to the interaction's
	callback when it came over the gateway."""
	status: str = '200 OK'
	body: bytes = b''
	then: object = dataclasses.field(default=None, compare=False)
	interaction: bool = False


OK = Response()
UNSUPPORTED = Response(body=b'Unsupported') # an update of a kind the bot takes no part in
UNHANDLED = Response(body=b'<h1>Unhandled</h1>') # a kind it might, which this code does not know
BAD_REQUEST = Response('400 Bad Request', b'<h1>Bad Request</h1>')
FORBIDDEN = Response('403 Forbidden', b'<h1>Unauthorized</h1>')
UNAUTHORIZED = Response('401 Unauthorized', b'<h1>Unauthorized</h1>') # what Discord expects for a bad signature
NOT_FOUND = Response('404 Not Found', b'<h1>404</h1>')
TOO_LARGE = Response('413 Payload Too Large', b'<h1>Payload Too Large</h1>')


SIGNATURE_AGE = 300 # seconds: Slack's limit; an older signed request may be a replay


def same_secret(given, expected):
	"""Whether a secret sent with a request is the one configured, compared in constant time. An empty configured secret
	proves nothing, so it matches nothing."""
	return bool(expected) and given is not None and hmac.compare_digest(given.encode(), expected.encode())


class Network:
	"""How a network's updates read, however they arrive."""
	service = ''

	def update_id(self, update):
		"""The update's id, the same when the network resends it (unanswered in time), or None if it gives none."""
		return None

	def parse(self, update):
		"""What the update (a dict) says: a Message, a Press, or a Response to give straight back."""
		raise NotImplementedError

	def acknowledge(self, event):
		"""Tell the network an update was taken (a Message or a Press), where it waits for that: None when the answer to
		the update says nothing more, or the Response the network must have before any reply. Here None: taking the
		update is the acknowledgement (Slack's is the 200, or the socket's ack)."""
		return None


class Telegram(Network):
	"""Telegram's updates: messages and button presses."""
	service = 'telegram'
	bot_name = None # the bot's @username, from telegram.register() as bot.py starts
	IGNORED = {'sticker', 'animation', 'voice', 'video', 'video_note', 'audio', 'document', 'contact', 'location',
		'venue', 'poll', 'dice'} # nothing to answer, nothing worth logging

	def update_id(self, update):
		"""Telegram's update_id."""
		return update.get('update_id')

	def parse(self, update):
		"""A message (its text, or a photo's caption) or a button press. A first name is escaped as it arrives:
		replies are Telegram HTML, and a name is text, not markup."""
		if 'callback_query' in update: # chart period and job buttons
			press = update['callback_query']
			message = press.get('message')
			if not message or not press.get('data'):
				return UNSUPPORTED
			sender = press.get('from', {})
			who = '@' + sender['username'] if 'username' in sender else sender.get('first_name', 'unknown')
			return Press(self.service, press['id'], str(message['chat']['id']), str(message['message_id']),
				press['data'], who)
		if 'message' not in update:
			return UNSUPPORTED
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
			return OK
		else:
			print("[telegram]: unhandled: 'message' without 'text/photo'", file=sys.stderr)
			return UNHANDLED
		return Message(self.service, chat_id, user, text, self.bot_name, user_name, str(message.get('message_id', '')))

	def acknowledge(self, event):
		"""A press: answerCallbackQuery, so that the client's spinner stops and a toast made from the button's data says
		what is coming (buttons.toast: 'Loading 1Y…'). A failure is only logged. Nothing goes back with the update."""
		if isinstance(event, Press):
			telegram.answerCallbackQuery(event.press_id, buttons.toast(event.data))
		return None


class Slack(Network):
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
			print("replying with", response, file=sys.stderr)
			return Response(body=response.encode())
		if kind == 'block_actions':
			return self.press(update)
		if kind != 'event_callback':
			print(f"[slack]: unhandled 'type' {kind!r}", file=sys.stderr)
			return UNHANDLED
		event = update['event']
		bot_user = update['authorizations'][0]['user_id'] # QWERTY
		if event.get('bot_id') or event.get('subtype') not in self.BY_PEOPLE or not event.get('user') or \
				event['user'] == bot_user:
			return OK # not by a person: answering a bot (this one's replies and webhook reports included) could loop
		if event['type'] not in ('message', 'app_mention') or 'text' not in event:
			print("[slack]: unhandled event callback type", event['type'], file=sys.stderr)
			return UNHANDLED
		user = '<@' + event['user'] + '>' # a mention: Slack shows the name
		return Message(self.service, event['channel'], user, self.plain(event['text']), '@' + bot_user, user,
			event.get('ts', ''))

	def slash(self, update):
		"""A slash command (/price with 5 7d), as the message that says the same (/price 5 7d), in the channel or DM it
		was sent in. There is no message of it, for ⏳ to show on."""
		user = '<@' + str(update.get('user_id') or 'unknown') + '>'
		text = self.plain(f"{update['command']} {update.get('text') or ''}".strip())
		return Message(self.service, str(update.get('channel_id') or ''), user, text, '', user)

	@staticmethod
	def plain(text):
		"""Text as written: links and mentions lose their markup (<http://dub.ax|dub.ax> becomes dub.ax, <@QWERTY>
		@QWERTY), and Slack's escapes their meaning (&amp; becomes &)."""
		text = re.sub(r'<((?:https?|mailto):[^|>]*)(?:\|([^>]*))?>', lambda m: m.group(2) or m.group(1), text)
		return html.unescape(re.sub(r'<(@[\w\.]+)>', r'\g<1>', text)) # Slack sends & < > as &amp; &lt; &gt;

	def press(self, update):
		"""A button pressed under one of the bot's messages (a chart's period buttons), or UNSUPPORTED for one that is
		not under a message or carries no value."""
		container = update.get('container') or {}
		actions = update.get('actions') or [{}]
		value = actions[0].get('value') if isinstance(actions[0], dict) else None
		if container.get('type') != 'message' or not container.get('message_ts') or not value:
			return UNSUPPORTED
		user = update.get('user') or {}
		who = '@' + str(user.get('username') or user.get('id') or 'unknown')
		return Press(self.service, update.get('trigger_id', ''), container.get('channel_id', ''),
			container['message_ts'], value, who)


class Discord(Network):
	"""Discord's interactions (a slash command, a button pressed, the endpoint's check), which read the same from the
	interactions endpoint and the gateway, and the gateway's messages."""
	service = 'discord'
	bot_id = None # the bot's user id, from discord.register() as bot.py starts: a message mentioning it is for the bot
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
			return Response(body=json.dumps({'type': self.PONG}).encode(), interaction=True)
		person = (update.get('member') or {}).get('user') or update.get('user') or {}
		channel = str(update.get('channel_id') or (update.get('channel') or {}).get('id') or '')
		through = f"{update.get('application_id')}/{update['token']}"
		data = update.get('data') or {}
		if kind == self.COMMAND and data.get('name'):
			given = ' '.join(str(option.get('value', '')) for option in data.get('options') or []).strip()
			text = f"/{data['name']} {given}".strip()
			return Message(self.service, channel, f"<@{person.get('id')}>", text, self.bot_name, self.name(person),
				interaction=through)
		if kind == self.AUTOCOMPLETE and data.get('name'):
			options = data.get('options') or []
			typed = next((str(option.get('value', '')) for option in options if option.get('focused')), '')
			return Suggest(self.service, channel, f"/{data['name']} {typed}", through)
		message = update.get('message') or {}
		if kind == self.COMPONENT and data.get('custom_id') and message.get('id'):
			return Press(self.service, str(update.get('id')), channel, str(message['id']), data['custom_id'],
				'@' + str(person.get('username') or person.get('id') or 'unknown'), through)
		return UNSUPPORTED

	def message(self, update):
		"""A message a person wrote (MESSAGE_CREATE); a mention <@id> reads as @id, as Slack's do. One by a bot (this
		one's replies included) or a webhook is OK: answering a bot could loop."""
		author = update.get('author') or {}
		if author.get('bot') or update.get('webhook_id') or not author.get('id') or 'content' not in update:
			return OK
		text = re.sub(r'<@!?(\d+)>', r'@\1', update['content'])
		return Message(self.service, str(update.get('channel_id')), f"<@{author['id']}>", text, self.bot_name,
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
		answer = self.THINKING if isinstance(event, Message) else self.LATER
		return Response(body=json.dumps({'type': answer}).encode(), interaction=True)

	def suggestions(self, choices):
		"""The answer to an autocomplete interaction: the choices, (name shown, value) pairs, 25 at most."""
		choices = [{'name': name, 'value': value} for name, value in choices[:25]]
		return Response(body=json.dumps({'type': self.CHOICES, 'data': {'choices': choices}}).encode(),
			interaction=True)


class Webhook:
	"""Updates a network posts to the bot, for its reader (a Network); subclasses give the path it posts to and how it
	proves itself."""
	REFUSED = FORBIDDEN # the answer to a request that does not prove itself
	def __init__(self, network):
		"""network: the reader of its updates."""
		self.network = network
		self.service = network.service

	def path(self):
		"""The URL path the network posts to, or '' when finbot.env sets none."""
		return ''

	def refuse_unread(self, environ):
		"""Why to turn the request away before its body is read (a secret header missing or wrong), else None."""
		return None

	def decode(self, body):
		"""The update in the request body, a dict. Raises ValueError when the body is not one."""
		update = json.loads(body)
		if not isinstance(update, dict):
			raise ValueError('not a JSON object')
		return update

	def refuse(self, environ, body, update):
		"""Why to refuse the request once read (the body's signature or a secret in it missing or wrong), else None."""
		return None


class TelegramWebhook(Webhook):
	"""Telegram posting to telegramOutgoingWebhook, each update with the secret header that setWebhook gave it."""

	def path(self):
		"""The path of telegramOutgoingWebhook."""
		return urlparse(config.env.telegramOutgoingWebhook).path if config.env.telegramOutgoingWebhook else ''

	def refuse_unread(self, environ):
		"""The header must carry telegramOutgoingToken."""
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if not same_secret(secret, config.env.telegramOutgoingToken):
			return f"Telegram authorisation header {'not present' if secret is None else 'is present but incorrect'}"
		return None


class SlackWebhook(Webhook):
	"""Slack posting events, button presses and slash commands to slackOutgoingWebhook (the app's Request URL for each),
	each request signed with the app's signing secret, and carrying its verification token."""

	def path(self):
		"""The path of slackOutgoingWebhook."""
		return urlparse(config.env.slackOutgoingWebhook).path if config.env.slackOutgoingWebhook else ''

	def refuse(self, environ, body, update):
		"""With slackSigningSecret, the request must carry Slack's signature of its body, made in the last five minutes;
		without it, the body must carry slackOutgoingToken (the older way, which Slack has deprecated)."""
		if config.env.slackSigningSecret:
			return self.signature_problem(environ, body, config.env.slackSigningSecret)
		if 'token' not in update:
			return "Slack authorisation field not present"
		if not same_secret(str(update['token']), config.env.slackOutgoingToken):
			return "Slack auth incorrect"
		return None

	@staticmethod
	def signature_problem(environ, body, secret):
		"""Why the request's signature fails, or None: X-Slack-Signature must be v0= and the HMAC-SHA256, under the
		signing secret, of v0:<X-Slack-Request-Timestamp>:<the body>, and the timestamp within five minutes of now."""
		timestamp = environ.get('HTTP_X_SLACK_REQUEST_TIMESTAMP', '')
		signature = environ.get('HTTP_X_SLACK_SIGNATURE')
		if signature is None or not (timestamp.isascii() and timestamp.isdigit()):
			return "Slack signature not present"
		if abs(time.time() - int(timestamp)) > SIGNATURE_AGE:
			return "Slack signature too old (a replay, or a clock is wrong)"
		signed = b'v0:' + timestamp.encode() + b':' + body
		expected = 'v0=' + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
		return None if same_secret(signature, expected) else "Slack signature incorrect"

	def decode(self, body):
		"""The update: an event comes as JSON, a button press as a form whose `payload` field holds the JSON, and a
		slash command as a form of its fields (command, text, channel_id, user_id and the rest)."""
		if not body.lstrip().startswith(b'{'):
			fields = parse_qs(body.decode('utf-8', 'replace'), keep_blank_values=True)
			if 'command' in fields and 'payload' not in fields:
				return {name: values[0] for name, values in fields.items()}
			body = fields.get('payload', [''])[0].encode()
		return super().decode(body)


class DiscordInteractions(Webhook):
	"""Discord posting interactions to discordOutgoingWebhook (the app's Interactions Endpoint URL), each signed with
	the app's Ed25519 key, whose public half is discordPublicKey."""
	REFUSED = UNAUTHORIZED # Discord checks that a bad signature gets a 401, and drops a URL that answers otherwise

	def path(self):
		"""The path of discordOutgoingWebhook."""
		return urlparse(config.env.discordOutgoingWebhook).path if config.env.discordOutgoingWebhook else ''

	def refuse(self, environ, body, update):
		"""The request must carry Discord's signature of its timestamp and body under discordPublicKey, checked with
		PyNaCl (imported here only: Discord's http mode is the one thing that needs it)."""
		signature = environ.get('HTTP_X_SIGNATURE_ED25519', '')
		timestamp = environ.get('HTTP_X_SIGNATURE_TIMESTAMP', '')
		if not signature or not timestamp:
			return "Discord signature not present"
		from nacl.exceptions import BadSignatureError
		from nacl.signing import VerifyKey
		try:
			VerifyKey(bytes.fromhex(config.env.discordPublicKey)).verify(timestamp.encode() + body,
				bytes.fromhex(signature))
		except (BadSignatureError, ValueError):
			return "Discord signature incorrect"
		return None


TELEGRAM, SLACK, DISCORD = Telegram(), Slack(), Discord() # the readers
WEBHOOKS = (TelegramWebhook(TELEGRAM), SlackWebhook(SLACK), DiscordInteractions(DISCORD))


def route(path):
	"""The webhook whose path this is, or None."""
	return next((hook for hook in WEBHOOKS if hook.path() and path == hook.path()), None)
