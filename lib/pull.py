"""The pull modes, whichever network: a network that finbot.env gives no webhook URL is asked for its updates instead,
by a listener in a thread of its own (Telegram's long polling, Slack's Socket Mode and Discord's gateway: in
telegram_longpolling, slack_websocket and discord_websocket), which hands each update to bot.take(network, update) as
the webhook would, so that reading it, the repeat check and acknowledging a press are the same both ways. Each
listener keeps going through failures, waiting longer after each one in a row (backoff). Slack's and Discord's read a
WebSocket."""
import time

from lib import log
from lib import delivery
from lib import net


BACKOFF = (5, 60) # seconds to wait after a failure: the first, doubled after each further one, up to the second


def backoff(failures):
	"""The seconds to wait after this many failures in a row."""
	first, most = BACKOFF
	return min(most, first * 2 ** (failures - 1))


class Closed(ConnectionError):
	"""The server closed the WebSocket, with a close code (None where it gave none) and a reason."""

	def __init__(self, code=None, reason=''):
		"""The close code and the reason, both in the message too."""
		said = f'{code}: {reason}' if reason else f'{code}'
		super().__init__('the server closed the socket' + (f' ({said})' if code else ''))
		self.code, self.reason = code, reason


class WebSocket:
	"""A WebSocket connection, through websocket-client: imported here only, as only Slack's and Discord's pull modes
	need it (Debian's python3-websocket)."""

	def __init__(self, url):
		"""Connect to url, waiting net.CONNECT_TIMEOUT seconds at most for the server."""
		import websocket
		self.library = websocket
		self.ws = websocket.create_connection(url, timeout=net.CONNECT_TIMEOUT)

	def receive(self, timeout):
		"""The next message's text; '' for a ping or a pong, which only say the line is alive; None when nothing came
		within timeout seconds. Raises Closed when the server closes the socket."""
		self.ws.settimeout(timeout)
		try:
			opcode, data = self.ws.recv_data(control_frame=True)
		except self.library.WebSocketTimeoutException:
			return None
		if opcode == self.library.ABNF.OPCODE_CLOSE: # two bytes of close code, then the reason
			raise Closed(int.from_bytes(data[:2], 'big') if len(data) >= 2 else None,
				data[2:].decode('utf-8', 'replace'))
		if opcode == self.library.ABNF.OPCODE_TEXT:
			return data.decode('utf-8') if isinstance(data, bytes) else data
		return ''

	def send(self, text):
		"""Send a text message."""
		self.ws.send(text)

	def ping(self):
		"""Send a ping, which the server answers with a pong."""
		self.ws.ping()

	def close(self, code=1000):
		"""Close the socket with this close code; a goodbye that fails is of no matter."""
		try:
			self.ws.close(status=code, timeout=1)
		except Exception:
			pass


class Listener:
	"""Updates fetched from a network, for its reader; run() hands them to take() until the process ends."""
	network = None # the reader, an inbound.Network
	failures = 0 # in a row

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for this listener: its network's keys set, and no webhook URL."""
		raise NotImplementedError

	def run(self, take):
		"""Fetch and hand on updates for good, waiting as poll() says between rounds. A round that fails in a way poll()
		did not foresee is logged and tried again after the back-off: the network's updates must not stop for good."""
		log.info(f"{self.network.service}: {self.describe()}")
		while True:
			try:
				wait = self.poll(take)
			except Exception as e:
				wait = self.failed('a round', e)
			time.sleep(wait)

	def describe(self):
		"""How it listens, for the log as it starts."""
		return 'listening'

	def poll(self, take):
		"""One round: fetch what there is, hand each update to take(network, update), and return the seconds to wait
		before the next round."""
		raise NotImplementedError

	def failed(self, what, e):
		"""Note a failure in a row, log it, and return the wait before trying again."""
		self.failures += 1
		wait = backoff(self.failures)
		log.warn(f"{self.network.service}: {what} failed, trying again in {wait} s:", net.redact(e))
		return wait

	def hand_on(self, take, update):
		"""take(network, update), and its answer delivered where the network must have it: an interaction's, and one
		that work waits on. A failure is reported as bot.main reports one of an authenticated request: it belongs to no
		chat, so the log has it."""
		try:
			answer = take(self.network, update)
			if getattr(answer, 'interaction', False) or getattr(answer, 'then', None):
				self.answer(update, answer)
		except Exception as e:
			delivery.report_error(e, context=self.network.service)

	def answer(self, update, answer):
		"""Deliver an answer that the network must have (only Discord's interactions have one: DiscordGateway), then
		start the work waiting on it, if any."""
		if answer.then:
			answer.then()
