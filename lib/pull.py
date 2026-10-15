"""The pull modes: a network that finbot.env gives no webhook URL is asked for its updates instead, by a listener in a
thread of its own, which hands each update to bot.take(network, update) as the webhook would, so that reading it, the
repeat check and acknowledging a press are the same both ways. Each listener keeps going through failures, waiting
longer after each one in a row (backoff). Telegram's long polling, Slack's Socket Mode and Discord's gateway."""
import asyncio
import json
import sys
import threading
import time

from lib import config
from lib import delivery
from lib import discord
from lib import inbound
from lib import net
from lib import telegram
from lib import transports

BACKOFF = (5, 60) # seconds to wait after a failure: the first, doubled after each further one, up to the second


def backoff(failures):
	"""The seconds to wait after this many failures in a row."""
	first, most = BACKOFF
	return min(most, first * 2 ** (failures - 1))


class Listener:
	"""Updates fetched from a network, for its reader; run() hands them to take() until the process ends."""
	network = None # the reader, an inbound.Network
	failures = 0 # in a row

	def run(self, take):
		"""Fetch and hand on updates for good, waiting as poll() says between rounds."""
		print(f"{self.network.service}: {self.describe()}", file=sys.stderr)
		while True:
			time.sleep(self.poll(take))

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
		print(f"{self.network.service}: {what} failed, trying again in {wait} s:", net.redact(e), file=sys.stderr)
		return wait

	def hand_on(self, take, update):
		"""take(network, update), and its answer delivered where the network must have it: an interaction's, and one
		that work waits on. A failure is reported as bot.main reports one of an authenticated request: the update came
		from the network, so the default chats are told."""
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


class TelegramPoll(Listener):
	"""Telegram's long polling: getUpdates, which Telegram holds open until there are updates or POLL_SECONDS have
	passed, asking for those after the last one taken (offset), which also tells Telegram that one arrived. No webhook
	may be set meanwhile: telegram.register() deletes it as finbot starts."""
	network = inbound.TELEGRAM
	POLL_SECONDS = 50 # how long Telegram may hold a getUpdates open
	READ_SECONDS = 65 # the request's own timeout for the answer: longer than Telegram holds it
	offset = None # the update_id after the last one taken

	def describe(self):
		"""The mode, for the log."""
		return 'long polling for updates (no telegramOutgoingWebhook)'

	def poll(self, take):
		"""One getUpdates: each update to take, in order; then no wait, or the back-off after a failure (a 409 says a
		webhook is set, or another finbot polls with the same token)."""
		params = {'timeout': self.POLL_SECONDS, 'allowed_updates': ['message', 'callback_query']}
		if self.offset is not None:
			params['offset'] = self.offset
		try:
			updates = telegram.call('getUpdates', json=params, timeout=(net.CONNECT_TIMEOUT, self.READ_SECONDS))
		except Exception as e:
			return self.failed('getUpdates', e)
		self.failures = 0
		for update in updates:
			if isinstance(update.get('update_id'), int):
				self.offset = update['update_id'] + 1 # taken, even if handling it fails: it is not fetched again
			self.hand_on(take, update)
		return 0


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


class SlackSocket(Listener):
	"""Slack's Socket Mode: a WebSocket to the URL that apps.connections.open gives for the app-level token
	(slackAppToken). Each event, button press or slash command comes in an envelope, acked at once, before anything
	else (Slack sends again what is not acked within 3 seconds); inside it is what Slack would post to
	slackOutgoingWebhook. Slack closes a socket now and then, saying so first (disconnect), and another is opened at
	once."""
	network = inbound.SLACK
	PING_SECONDS = 30 # silence this long sends a ping; as long again after it, and the socket is taken for dead
	TAKEN = ('events_api', 'interactive', 'slash_commands') # the envelopes whose payload goes to the reader

	def describe(self):
		"""The mode, for the log."""
		return 'Socket Mode (no slackOutgoingWebhook)'

	def open(self):
		"""The URL of a new socket, from apps.connections.open."""
		return transports.slack_api('apps.connections.open', as_app=True)['url']

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
		print(f"slack: Slack is closing the socket ({reason}), opening another", file=sys.stderr)
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


class DiscordGateway(Listener):
	"""Discord's gateway, through discord.py: imported here only, as Discord's pull mode is the one thing that needs it
	(Debian's python3-discord). Its client keeps the connection, reconnecting by itself; finbot takes the raw
	MESSAGE_CREATE and INTERACTION_CREATE events, which read as the interactions endpoint's, each in a thread of its
	own, off the client's event loop. The gateway takes no answers: an interaction's goes to its callback over REST."""
	network = inbound.DISCORD
	TAKEN = ('MESSAGE_CREATE', 'INTERACTION_CREATE')

	def describe(self):
		"""The mode, for the log."""
		return 'gateway (no discordOutgoingWebhook)'

	def poll(self, take):
		"""Run discord.py's client until it stops, which it does only on a failure it does not get over (a token Discord
		refuses, or an intent the app is not allowed): then the back-off."""
		try:
			asyncio.run(self.run_client(take))
		except Exception as e:
			return self.failed('the gateway', e)
		return self.failed('the gateway', 'the client stopped')

	async def run_client(self, take):
		"""Start the client with the bot token, and close it however it ends."""
		client = self.client(take)
		async with client:
			await client.start(config.env.discordBotToken)

	def client(self, take):
		"""discord.py's client, with the intents for messages in servers and DMs, and their text (Message Content, which
		the app must be allowed in the Developer Portal); its raw events go to receive()."""
		import discord as library
		library.VoiceClient.warn_nacl = False # finbot has no voice: no warning that PyNaCl is missing
		intents = library.Intents.default()
		intents.message_content = True
		client = library.Client(intents=intents, enable_debug_events=True)

		@client.event
		async def on_socket_raw_receive(raw):
			"""A gateway message, as it arrived."""
			self.receive(raw, take)

		@client.event
		async def on_ready():
			"""Connected: the failures in a row are over."""
			self.failures = 0
		return client

	def receive(self, raw, take):
		"""A raw gateway message: an event finbot takes goes to hand_on in a thread of its own, so that the client's
		event loop never waits on finbot; the rest is the client's business."""
		try:
			message = json.loads(raw)
		except (TypeError, ValueError):
			return
		if message.get('op') == 0 and message.get('t') in self.TAKEN and isinstance(message.get('d'), dict):
			threading.Thread(target=self.hand_on, args=(take, message['d']), daemon=True).start()

	def answer(self, update, answer):
		"""Post an interaction's answer to its callback, then start the work waiting on it, if any."""
		discord.call('POST', f"/interactions/{update['id']}/{update['token']}/callback", json=json.loads(answer.body))
		if answer.then:
			answer.then()


def listeners():
	"""The listeners finbot.env asks for: each network with its bot token and no webhook URL (Slack's also needs its
	app-level token)."""
	env = config.env
	found = []
	if env.telegramBotToken and not env.telegramOutgoingWebhook:
		found.append(TelegramPoll())
	if env.slackBotToken and env.slackAppToken and not env.slackOutgoingWebhook:
		found.append(SlackSocket())
	if env.discordBotToken and not env.discordOutgoingWebhook:
		found.append(DiscordGateway())
	return found
