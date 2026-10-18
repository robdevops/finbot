"""Telegram's webhook, its HTTP mode (telegramOutgoingWebhook set): Telegram posts each update to finbot's URL with
the secret header that setWebhook gave it, for the reader (telegram_common.READER)."""
from urllib.parse import urlparse

from lib import log
from lib import config
from lib import inbound
from lib import telegram_common


def setWebhook():
	"""Have Telegram post messages and button presses to telegramOutgoingWebhook, signed with telegramOutgoingToken. The
	URL goes in the body, never the query string, which a failed request's error (and so the log) would show: its path
	is a secret."""
	log.info("telegram: setting the webhook (telegramOutgoingWebhook)")
	return telegram_common.call('setWebhook', json={'url': config.env.telegramOutgoingWebhook,
		'allowed_updates': ['message', 'callback_query'], 'secret_token': config.env.telegramOutgoingToken})


def register():
	"""Called once by bot.py as it starts, never on import: delete the webhook and set it again, which wakes up a stale
	connection on Telegram's side. Raises RuntimeError, or a requests error, if a call fails."""
	telegram_common.deleteWebhook()
	setWebhook()


class TelegramWebhook(inbound.Webhook):
	"""Telegram posting to telegramOutgoingWebhook, each update with the secret header that setWebhook gave it."""

	def path(self):
		"""The path of telegramOutgoingWebhook."""
		return urlparse(config.env.telegramOutgoingWebhook).path if config.env.telegramOutgoingWebhook else ''

	def refuse_unread(self, environ):
		"""The header must carry telegramOutgoingToken."""
		secret = environ.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN')
		if not inbound.same_secret(secret, config.env.telegramOutgoingToken):
			return f"Telegram authorisation header {'not present' if secret is None else 'is present but incorrect'}"
		return None


WEBHOOK = TelegramWebhook(telegram_common.READER)
