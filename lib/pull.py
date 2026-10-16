"""The pull modes, whichever network: a network that finbot.env gives no webhook URL is asked for its updates instead,
by a listener in a thread of its own (Telegram's long polling, Slack's Socket Mode and Discord's gateway: in
telegram_longpolling, slack_websocket and discord_websocket), which hands each update to bot.take(network, update) as
the webhook would, so that reading it, the repeat check and acknowledging a press are the same both ways. Each
listener keeps going through failures, waiting longer after each one in a row (backoff)."""
import time

from lib import log
from lib import delivery
from lib import net


BACKOFF = (5, 60) # seconds to wait after a failure: the first, doubled after each further one, up to the second


def backoff(failures):
	"""The seconds to wait after this many failures in a row."""
	first, most = BACKOFF
	return min(most, first * 2 ** (failures - 1))


class Listener:
	"""Updates fetched from a network, for its reader; run() hands them to take() until the process ends."""
	network = None # the reader, an inbound.Network
	failures = 0 # in a row

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for this listener: its network's keys set, and no webhook URL."""
		raise NotImplementedError

	def run(self, take):
		"""Fetch and hand on updates for good, waiting as poll() says between rounds."""
		log.info(f"{self.network.service}: {self.describe()}")
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
		log.warn(f"{self.network.service}: {what} failed, trying again in {wait} s:", net.redact(e))
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
