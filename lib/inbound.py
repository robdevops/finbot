"""What the networks post to the bot: one class per network that sends updates, which knows the path it posts to, how
it proves itself and how to read an update. An update becomes a Message to answer, a Press of a button, or a Response
the network gets straight back (a challenge, or nothing to do)."""
import dataclasses
import hashlib
import hmac
import html
import json
import re
import sys
import time
from urllib.parse import urlparse

from lib import config


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


@dataclasses.dataclass
class Press:
	"""A button pressed under one of the bot's messages (worker.process_callback)."""
	service: str
	press_id: str # the network's id for the press, to answer it
	chat_id: str
	message_id: str
	data: str
	user: str # who pressed it, for the log


@dataclasses.dataclass
class Response:
	"""What the network gets back at once: a status and a body."""
	status: str = '200 OK'
	body: bytes = b''


OK = Response()
UNSUPPORTED = Response(body=b'Unsupported') # an update of a kind the bot takes no part in
UNHANDLED = Response(body=b'<h1>Unhandled</h1>') # a kind it might, which this code does not know
BAD_REQUEST = Response('400 Bad Request', b'<h1>Bad Request</h1>')
FORBIDDEN = Response('403 Forbidden', b'<h1>Unauthorized</h1>')
NOT_FOUND = Response('404 Not Found', b'<h1>404</h1>')
TOO_LARGE = Response('413 Payload Too Large', b'<h1>Payload Too Large</h1>')


SIGNATURE_AGE = 300 # seconds: Slack's limit; an older signed request may be a replay


def same_secret(given, expected):
	"""Whether a secret sent with a request is the one configured, compared in constant time. An empty configured secret
	proves nothing, so it matches nothing."""
	return bool(expected) and given is not None and hmac.compare_digest(given.encode(), expected.encode())


class Webhook:
	"""A network posting updates to the bot; subclasses give its path, how it proves itself and what an update says."""
	service = ''

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

	def update_id(self, update):
		"""The update's id, the same when the network resends it (unanswered in time), or None if it gives none."""
		return None

	def parse(self, update):
		"""What the update says: a Message, a Press, or a Response to give straight back."""
		raise NotImplementedError


class Telegram(Webhook):
	"""Telegram's updates, each sent with the secret header that setWebhook gave it."""
	service = 'telegram'
	bot_name = None # the bot's @username, from telegram.register() as bot.py starts
	IGNORED = {'sticker', 'animation', 'voice', 'video', 'video_note', 'audio', 'document', 'contact', 'location',
		'venue', 'poll', 'dice'} # nothing to answer, nothing worth logging

	def path(self):
		"""The path of telegramOutgoingWebhook."""
		return urlparse(config.env.telegramOutgoingWebhook).path if config.env.telegramOutgoingWebhook else ''

	def refuse_unread(self, environ):
		"""The header must carry telegramOutgoingToken."""
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if not same_secret(secret, config.env.telegramOutgoingToken):
			return f"Telegram authorisation header {'not present' if secret is None else 'is present but incorrect'}"
		return None

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


class Slack(Webhook):
	"""Slack's Events API: each request signed with the app's signing secret, and carrying its verification token."""
	service = 'slack'
	BY_PEOPLE = (None, 'thread_broadcast') # message subtypes a person writes; the rest are bot posts, edits, joins...

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

	def update_id(self, update):
		"""Slack's event_id."""
		return update.get('event_id')

	def parse(self, update):
		"""A message a person wrote, or the challenge that checks the URL. Links and mentions lose their markup:
		<http://dub.ax|dub.ax> becomes dub.ax and <@QWERTY> @QWERTY."""
		kind = update.get('type')
		if kind == 'url_verification':
			response = json.dumps({'challenge': update['challenge']})
			print("replying with", response, file=sys.stderr)
			return Response(body=response.encode())
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
		text = re.sub(r'<http://.*\|([\w\.]+)>', r'\g<1>', event['text'])
		text = re.sub(r'<(@[\w\.]+)>', r'\g<1>', text)
		user = '<@' + event['user'] + '>' # a mention: Slack shows the name
		return Message(self.service, event['channel'], user, text, '@' + bot_user, user, event.get('ts', ''))


TELEGRAM, SLACK = Telegram(), Slack()


def route(path):
	"""The network that posts to this path, or None."""
	return next((source for source in (TELEGRAM, SLACK) if source.path() and path == source.path()), None)
