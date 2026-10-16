"""Slack's Socket Mode, its pull mode (no slackOutgoingWebhook): a WebSocket that the app-level token opens, whose
envelopes carry what Slack would post to the Request URL, for the reader (slack_common.READER)."""
import json

from lib import log
from lib import config
from lib import net
from lib import pull
from lib import slack_common


class WebSocket:
	"""A WebSocket connection, through websocket-client: imported here only, as Slack's pull mode is the one thing that
	needs it (Debian's python3-websocket)."""

	def __init__(self, url):
		"""Connect to url, waiting net.CONNECT_TIMEOUT seconds at most for the server."""
		import websocket
		self.library = websocket
		self.ws = websocket.create_connection(url, timeout=net.CONNECT_TIMEOUT)

	def receive(self, timeout):
		"""The next message's text; '' for a ping or a pong, which only say the line is alive; None when nothing came
		within timeout seconds. Raises ConnectionError when the server closes the socket."""
		self.ws.settimeout(timeout)
		try:
			opcode, data = self.ws.recv_data(control_frame=True)
		except self.library.WebSocketTimeoutException:
			return None
		if opcode == self.library.ABNF.OPCODE_CLOSE:
			raise ConnectionError('the server closed the socket')
		if opcode == self.library.ABNF.OPCODE_TEXT:
			return data.decode('utf-8') if isinstance(data, bytes) else data
		return ''

	def send(self, text):
		"""Send a text message."""
		self.ws.send(text)

	def ping(self):
		"""Send a ping, which the server answers with a pong."""
		self.ws.ping()

	def close(self):
		"""Close the socket; a goodbye that fails is of no matter."""
		try:
			self.ws.close(timeout=1)
		except Exception:
			pass


class SlackSocket(pull.Listener):
	"""Slack's Socket Mode: a WebSocket to the URL that apps.connections.open gives for the app-level token
	(slackAppToken). Each event, button press or slash command comes in an envelope, acked at once, before anything
	else (Slack sends again what is not acked within 3 seconds); inside it is what Slack would post to
	slackOutgoingWebhook. Slack closes a socket now and then, saying so first (disconnect), and another is opened at
	once."""
	network = slack_common.READER
	PING_SECONDS = 30 # silence this long sends a ping; as long again after it, and the socket is taken for dead
	TAKEN = ('events_api', 'interactive', 'slash_commands') # the envelopes whose payload goes to the reader

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for it: Slack's bot token and app-level token, and no slackOutgoingWebhook."""
		env = config.env
		return bool(env.slackBotToken and env.slackAppToken and not env.slackOutgoingWebhook)

	def describe(self):
		"""The mode, for the log."""
		return 'Socket Mode (no slackOutgoingWebhook)'

	def open(self):
		"""The URL of a new socket, from apps.connections.open."""
		return slack_common.call('apps.connections.open', as_app=True)['url']

	def connect(self, url):
		"""A WebSocket connected to url."""
		return WebSocket(url)

	def poll(self, take):
		"""One socket, from opening it to Slack closing it: then another at once; after a failure, the back-off."""
		try:
			connection = self.connect(self.open())
		except Exception as e:
			return self.failed('opening a socket', e)
		try:
			reason = self.listen(connection, take)
		except Exception as e:
			return self.failed('the socket', e)
		finally:
			connection.close()
		log.info(f"slack: Slack is closing the socket ({reason}), opening another")
		return 0

	def listen(self, connection, take):
		"""Read envelopes until Slack says it will close the socket, and return its reason: each acked, then its payload
		handed on. A ping goes out after PING_SECONDS of silence; as long again with nothing, not even the pong, raises
		TimeoutError."""
		pinged = False
		while True:
			text = connection.receive(self.PING_SECONDS)
			if text is None:
				if pinged:
					raise TimeoutError(f'nothing from Slack for {2 * self.PING_SECONDS} s, even after a ping')
				connection.ping()
				pinged = True
				continue
			pinged = False
			if not text: # a ping or a pong
				continue
			envelope = json.loads(text)
			if envelope.get('envelope_id'):
				connection.send(json.dumps({'envelope_id': envelope['envelope_id']}))
			kind = envelope.get('type')
			if kind == 'hello':
				self.failures = 0
			elif kind == 'disconnect':
				return envelope.get('reason') or 'no reason given'
			elif kind in self.TAKEN:
				self.hand_on(take, envelope.get('payload') or {})
