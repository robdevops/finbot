"""Telegram's long polling, its pull mode (no telegramOutgoingWebhook): finbot asks for its updates (getUpdates) again
and again, and hands each to the reader (telegram_common.READER) as the webhook would."""
from lib import net
from lib import pull
from lib import telegram_common


class TelegramPoll(pull.Listener):
	"""Telegram's long polling: getUpdates, which Telegram holds open until there are updates or POLL_SECONDS have
	passed, asking for those after the last one taken (offset), which also tells Telegram that one arrived. No webhook
	may be set meanwhile: telegram_common.start deletes it as finbot starts."""
	network = telegram_common.READER
	TOKENS = ('telegramBotToken',)
	WEBHOOK_URL = 'telegramOutgoingWebhook'
	MODE = 'long polling for updates'
	POLL_SECONDS = 50 # how long Telegram may hold a getUpdates open
	READ_SECONDS = 65 # the request's own timeout for the answer: longer than Telegram holds it
	offset = None # the update_id after the last one taken

	def poll(self, take):
		"""One getUpdates: each update to take, in order; then no wait, or the back-off after a failure (a 409 says a
		webhook is set, or another finbot polls with the same token)."""
		params = {'timeout': self.POLL_SECONDS, 'allowed_updates': telegram_common.ALLOWED_UPDATES}
		if self.offset is not None:
			params['offset'] = self.offset
		try:
			updates = telegram_common.call('getUpdates', json=params, timeout=(net.CONNECT_TIMEOUT, self.READ_SECONDS),
				logged=False) # asked again and again: the log would be nothing else
		except Exception as e:
			return self.failed('getUpdates', e)
		self.failures = 0
		for update in updates:
			if isinstance(update.get('update_id'), int):
				self.offset = update['update_id'] + 1 # taken, even if handling it fails: it is not fetched again
			self.hand_on(take, update)
		return 0
