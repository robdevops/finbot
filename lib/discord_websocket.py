"""Discord's gateway, its pull mode (no discordOutgoingWebhook): a WebSocket (pull.WebSocket) that the bot identifies on
with its token, whose events read as the interactions endpoint's, for the reader (discord_common.READER); an
interaction's answer is posted to its callback."""
import json
import random
import sys
import threading
import time

from lib import log
from lib import config
from lib import discord_common
from lib import pull

VERSION = '?v=10&encoding=json' # the gateway's API version, and JSON rather than ETF
# messages in servers and in direct messages, and their text: Message Content, a privileged intent, which the app must
# be allowed in the Developer Portal (interactions come whatever the intents)
INTENTS = 1 << 9 | 1 << 12 | 1 << 15
REFUSED = {4004: 'the bot token was refused', 4010: 'an invalid shard', 4011: 'the bot needs sharding',
	4012: 'an invalid API version', 4013: 'invalid intents', 4014: 'the Message Content intent is not allowed: switch'
	' it on in the Developer Portal, under Bot'} # close codes that trying again cannot mend
UNRESUMABLE = (4007, 4009) # close codes after which the session cannot go on: a new one is identified
REFUSED_WAIT = 3600 # seconds after a refusal: identifying 1000 times in a day gets the bot's token reset
SESSIONS_KEPT = 10 # a new session waits while Discord allows no more than this many more today
HELLO_SECONDS = 30 # the wait for Discord's Hello, on a new connection


class DiscordGateway(pull.Listener):
	"""Discord's gateway (API v10), as Slack's Socket Mode, over websocket-client. Hello gives the heartbeat's interval;
	the first beat comes a random part of it later, and each beat's ACK is due before the next, or the connection is
	taken for dead. Then IDENTIFY with the token and the intents, or RESUME a session (READY gives its id and the URL
	to resume it at) from the last event's sequence number, so that Discord sends what was missed. Discord asks for a
	reconnect now and then (op 7), and says when a session cannot go on (op 9). finbot takes the MESSAGE_CREATE and
	INTERACTION_CREATE events, each in a thread of its own, so that the heartbeat never waits on finbot; the gateway
	takes no answers: an interaction's goes to its callback over REST."""
	network = discord_common.READER
	TAKEN = ('MESSAGE_CREATE', 'INTERACTION_CREATE')

	def __init__(self):
		"""A listener with no session yet."""
		self.session = None # (its id, the URL to resume it at), from READY
		self.sequence = None # the last event's, for the heartbeat and RESUME

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for it: Discord's bot token, and no discordOutgoingWebhook."""
		return bool(config.env.discordBotToken and not config.env.discordOutgoingWebhook)

	def describe(self):
		"""The mode, for the log."""
		return 'gateway (no discordOutgoingWebhook)'

	def connect(self, url):
		"""A WebSocket connected to url."""
		return pull.WebSocket(url)

	def poll(self, take):
		"""One connection, until it ends: then another, resuming the session where there is one; after a failure, the
		back-off; after a refusal that trying again cannot mend (the token, the intents), REFUSED_WAIT."""
		try:
			url = self.session[1] if self.session else self.start()
			if not isinstance(url, str): # no session may start yet: the wait
				return url
			connection = self.connect(url.rstrip('/') + '/' + VERSION)
		except Exception as e:
			return self.failed('connecting to the gateway', e)
		try:
			return self.listen(connection, take)
		except pull.Closed as e:
			if e.code in REFUSED:
				log.error(f"discord: the gateway refused finbot ({e.code}: {REFUSED[e.code]}), trying again in an hour")
				return REFUSED_WAIT
			if e.code in UNRESUMABLE:
				self.session = None
			return self.failed('the gateway', e)
		except Exception as e:
			return self.failed('the gateway', e)
		finally:
			connection.close(4000) # not 1000, which would end the session

	def start(self):
		"""The gateway's URL for a new session (GET /gateway/bot), or the seconds to wait first while Discord allows
		few more sessions today."""
		answer = discord_common.call('GET', '/gateway/bot')
		limit = answer.get('session_start_limit') or {}
		if limit.get('remaining', SESSIONS_KEPT + 1) <= SESSIONS_KEPT:
			wait = max(limit.get('reset_after', 0) / 1000, 60)
			log.warn(f"discord: Discord allows {limit.get('remaining')} more sessions today: waiting {wait / 60:.0f}"
				" minutes")
			return wait
		return answer['url']

	def listen(self, connection, take):
		"""Read the gateway until Discord asks for a reconnect (op 7: at once) or ends the session (op 9: after a
		moment, as Discord asks), and return the seconds to wait before the next connection. Raises TimeoutError for a
		connection that misses Hello or a heartbeat's ACK, and pull.Closed when Discord closes it."""
		interval, wait, acked = None, HELLO_SECONDS, True # wait: for Hello, then until the next heartbeat
		while True:
			started = time.monotonic()
			text = connection.receive(wait)
			if text is None: # the wait is over
				if interval is None:
					raise TimeoutError(f'no Hello from Discord in {HELLO_SECONDS} s')
				if not acked:
					raise TimeoutError("Discord did not acknowledge the last heartbeat")
				self.beat(connection)
				wait, acked = interval, False
				continue
			wait = max(0.0, wait - (time.monotonic() - started))
			if not text: # a ping or a pong
				continue
			message = json.loads(text)
			op, data = message.get('op'), message.get('d')
			if op == 10: # Hello
				interval = data['heartbeat_interval'] / 1000
				wait = interval * random.random()
				connection.send(json.dumps(self.resume() if self.session else self.identify()))
			elif op == 11: # the heartbeat's ACK
				acked = True
			elif op == 1: # a heartbeat asked for now
				self.beat(connection)
			elif op == 7:
				log.info('discord: Discord asks for a reconnect, resuming')
				return 0
			elif op == 9:
				if not data: # not resumable
					self.session, self.sequence = None, None
				log.info(f"discord: Discord ended the session, {'resuming' if data else 'starting another'}")
				return random.uniform(1, 5)
			elif op == 0:
				self.dispatch(message, take)

	def dispatch(self, message, take):
		"""An event: its sequence number noted; READY's session kept, and the failures in a row over (or RESUMED's);
		an event finbot takes handed on in a thread of its own."""
		if message.get('s') is not None:
			self.sequence = message['s']
		kind, data = message.get('t'), message.get('d')
		if kind == 'READY':
			self.session = (data['session_id'], data['resume_gateway_url'])
			self.failures = 0
		elif kind == 'RESUMED':
			self.failures = 0
		elif kind in self.TAKEN and isinstance(data, dict):
			threading.Thread(target=self.hand_on, args=(take, data), daemon=True).start()

	def identify(self):
		"""IDENTIFY: a new session, for the bot token and the intents."""
		return {'op': 2, 'd': {'token': config.env.discordBotToken, 'intents': INTENTS,
			'properties': {'os': sys.platform, 'browser': 'finbot', 'device': 'finbot'}}}

	def resume(self):
		"""RESUME: the session READY gave, from the last event seen."""
		return {'op': 6, 'd': {'token': config.env.discordBotToken, 'session_id': self.session[0],
			'seq': self.sequence}}

	def beat(self, connection):
		"""A heartbeat, with the last event's sequence number."""
		connection.send(json.dumps({'op': 1, 'd': self.sequence}))

	def answer(self, update, answer):
		"""Post an interaction's answer to its callback, then start the work waiting on it, if any."""
		path = f"/interactions/{update['id']}/{update['token']}/callback"
		discord_common.call('POST', path, json=json.loads(answer.body), logged='debug')
		if answer.then:
			answer.then()
