"""Telegram's webhook, its HTTP mode (TELEGRAM_OUTGOING_WEBHOOK set): Telegram posts each update to finbot's URL with
the secret header that setWebhook gave it (telegram_common.start), for the reader (telegram_common.READER)."""
from lib import config
from lib import inbound
from lib import telegram_common


class TelegramWebhook(inbound.Webhook):
	"""Telegram posting to TELEGRAM_OUTGOING_WEBHOOK, each update with the secret header that setWebhook gave it."""
	URL = 'TELEGRAM_OUTGOING_WEBHOOK'
	SECRET_HEADERS = ('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN',)
	MISSING = 'TELEGRAM_SECRET_TOKEN'

	def secured(self):
		"""Whether TELEGRAM_SECRET_TOKEN is set: the header must carry it."""
		return bool(config.env.TELEGRAM_SECRET_TOKEN)

	def refuse_unread(self, environ):
		"""The header must carry TELEGRAM_SECRET_TOKEN."""
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if not inbound.same_secret(secret, config.env.TELEGRAM_SECRET_TOKEN):
			return f"Telegram authorisation header {'not present' if secret is None else 'is present but incorrect'}"
		return None


WEBHOOK = TelegramWebhook(telegram_common.READER)
