"""The pull modes: a network that finbot.env gives no webhook URL is asked for its updates instead, by a listener in a
thread of its own, which hands each update to bot.take(network, update) as the webhook would, so that reading it, the
repeat check and acknowledging a press are the same both ways. Each listener keeps going through failures, waiting
longer after each one in a row (backoff)."""
import sys
import time

from lib import config
from lib import delivery
from lib import inbound
from lib import net
from lib import telegram

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
		"""take(network, update), a failure reported as bot.main reports one of an authenticated request: the update
		came from the network, so the default chats are told."""
		try:
			take(self.network, update)
		except Exception as e:
			delivery.report_error(e, context=self.network.service)


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


def listeners():
	"""The listeners finbot.env asks for: each network with its bot token and no webhook URL."""
	found = []
	if config.env.telegramBotToken and not config.env.telegramOutgoingWebhook:
		found.append(TelegramPoll())
	return found
