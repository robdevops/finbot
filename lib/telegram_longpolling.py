"""Telegram's long polling, its pull mode (no telegramOutgoingWebhook): finbot asks for its updates (getUpdates) again
and again, and hands each to the reader (telegram_common.READER) as the webhook would."""
from lib import config
from lib import net
from lib import pull
from lib import telegram_common


def register():
	"""Called once by bot.py as it starts, never on import: delete any webhook, so that getUpdates may take the
	updates, those not delivered yet included. Raises RuntimeError, or a requests error, if the call fails."""
	telegram_common.deleteWebhook()


class TelegramPoll(pull.Listener):
	"""Telegram's long polling: getUpdates, which Telegram holds open until there are updates or POLL_SECONDS have
	passed, asking for those after the last one taken (offset), which also tells Telegram that one arrived. No webhook
	may be set meanwhile: register() deletes it as finbot starts."""
	network = telegram_common.READER
	POLL_SECONDS = 50 # how long Telegram may hold a getUpdates open
	READ_SECONDS = 65 # the request's own timeout for the answer: longer than Telegram holds it
	offset = None # the update_id after the last one taken

	@staticmethod
	def wanted():
		"""Whether finbot.env asks for it: Telegram's bot token, and no telegramOutgoingWebhook."""
		return bool(config.env.telegramBotToken and not config.env.telegramOutgoingWebhook)

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
			updates = telegram_common.call('getUpdates', json=params, timeout=(net.CONNECT_TIMEOUT, self.READ_SECONDS))
		except Exception as e:
			return self.failed('getUpdates', e)
		self.failures = 0
		for update in updates:
			if isinstance(update.get('update_id'), int):
				self.offset = update['update_id'] + 1 # taken, even if handling it fails: it is not fetched again
			self.hand_on(take, update)
		return 0
