"""What the networks send the bot, whichever network and however it arrives. Reading an update is apart from how it
arrives: each network has a reader (a Network: telegram_common, slack_common, discord_common), and each way in hands
its updates to it: a webhook (a Webhook: the path the network posts to, how it proves itself, the body; in
telegram_webhook, slack_webhook, discord_webhook) or a pull mode (lib/pull.py). An update becomes a Message to answer,
a Press of a button, a Suggest to complete, or a Response the network gets straight back (a challenge, or nothing to
do). The reader also acknowledges an update where the network waits for that, however it arrived: Telegram's press
with a call, Discord's interaction with the answer it must have before any reply."""
import dataclasses
import hmac
import json


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
	dm: bool = None # whether the chat is a direct message with the bot; None where its key says (jobs.is_dm)


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

	def acknowledge(self, event, toast=True):
		"""Tell the network an update was taken (a Message or a Press; toast false: a press dropped, which shows
		nothing), where it waits for that: None when the answer to the update says nothing more, or the Response the
		network must have before any reply. Here None: taking the update is the acknowledgement (Slack's is the 200,
		or the socket's ack)."""
		return None


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
