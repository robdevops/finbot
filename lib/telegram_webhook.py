"""Telegram's webhook, its HTTP mode (telegramOutgoingWebhook set): Telegram posts each update to finbot's URL with
the secret header that setWebhook gave it (telegram_common.start), for the reader (telegram_common.READER)."""
from lib import config
from lib import inbound
from lib import telegram_common


class TelegramWebhook(inbound.Webhook):
	"""Telegram posting to telegramOutgoingWebhook, each update with the secret header that setWebhook gave it."""
	URL = 'telegramOutgoingWebhook'
	SECRET_HEADERS = ('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN',)
	MISSING = 'telegramOutgoingToken'

	def secured(self):
		"""Whether telegramOutgoingToken is set: the header must carry it."""
		return bool(config.env.telegramOutgoingToken)

	def refuse_unread(self, environ):
		"""The header must carry telegramOutgoingToken."""
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if not inbound.same_secret(secret, config.env.telegramOutgoingToken):
			return f"Telegram authorisation header {'not present' if secret is None else 'is present but incorrect'}"
		return None


WEBHOOK = TelegramWebhook(telegram_common.READER)
