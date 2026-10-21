"""Discord's interactions endpoint, its HTTP mode (discordOutgoingWebhook set): Discord posts each interaction to
finbot's URL, signed with the app's Ed25519 key, for the reader (discord_common.READER), and takes the answer as the
HTTP response."""
from lib import config
from lib import discord_common
from lib import inbound


class DiscordInteractions(inbound.Webhook):
	"""Discord posting interactions to discordOutgoingWebhook (the app's Interactions Endpoint URL), each signed with
	the app's Ed25519 key, whose public half is discordPublicKey."""
	URL = 'discordOutgoingWebhook'
	REFUSED = inbound.UNAUTHORIZED # Discord checks that a bad signature gets a 401, and drops a URL answering otherwise
	SECRET_FIELDS = ('token',) # the interaction's token, with which anyone can answer it for 15 minutes

	def refuse(self, environ, body, update):
		"""The request must carry Discord's signature of its timestamp and body under discordPublicKey, checked with
		PyNaCl (imported here only: Discord's http mode is the one thing that needs it)."""
		signature = environ.get('HTTP_X_SIGNATURE_ED25519', '')
		timestamp = environ.get('HTTP_X_SIGNATURE_TIMESTAMP', '')
		if not signature or not timestamp:
			return "Discord signature not present"
		from nacl.exceptions import BadSignatureError
		from nacl.signing import VerifyKey
		try:
			VerifyKey(bytes.fromhex(config.env.discordPublicKey.strip())).verify(timestamp.encode() + body,
				bytes.fromhex(signature))
		except (BadSignatureError, ValueError):
			return ("Discord signature incorrect (expected once or twice when the Interactions Endpoint URL is saved: "
				"Discord sends a bad one on purpose to see a 401; if saving fails, discordPublicKey is not General "
				"Information > Public Key)")
		return None


WEBHOOK = DiscordInteractions(discord_common.READER)
