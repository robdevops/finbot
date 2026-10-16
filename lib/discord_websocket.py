"""Discord's gateway, its pull mode (no discordOutgoingWebhook), through discord.py: the raw events taken as the
interactions endpoint's, for the reader (discord_common.READER), and an interaction's answer posted to its callback."""
import asyncio
import json
import threading

from lib import config
from lib import discord_common
from lib import pull


class DiscordGateway(pull.Listener):
	"""Discord's gateway, through discord.py: imported here only, as Discord's pull mode is the one thing that needs it
	(Debian's python3-discord). Its client keeps the connection, reconnecting by itself; finbot takes the raw
	MESSAGE_CREATE and INTERACTION_CREATE events, which read as the interactions endpoint's, each in a thread of its
	own, off the client's event loop. The gateway takes no answers: an interaction's goes to its callback over REST."""
	network = discord_common.READER
	TAKEN = ('MESSAGE_CREATE', 'INTERACTION_CREATE')

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for it: Discord's bot token, and no discordOutgoingWebhook."""
		return bool(config.env.discordBotToken and not config.env.discordOutgoingWebhook)

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
		path = f"/interactions/{update['id']}/{update['token']}/callback"
		discord_common.call('POST', path, json=json.loads(answer.body), logged='debug')
		if answer.then:
			answer.then()
