"""Slack's Request URL, its HTTP mode (slackOutgoingWebhook set): Slack posts each event, button press and slash
command to finbot's URL, signed with the app's signing secret, for the reader (slack_common.READER)."""
import hashlib
import hmac
import time
from urllib.parse import parse_qs

from lib import config
from lib import inbound
from lib import slack_common


SIGNATURE_AGE = 300 # seconds: Slack's limit; an older signed request may be a replay


class SlackWebhook(inbound.Webhook):
	"""Slack posting events, button presses and slash commands to slackOutgoingWebhook (the app's Request URL for each),
	each request signed with the app's signing secret, and carrying its verification token."""
	URL = 'slackOutgoingWebhook'
	SECRET_FIELDS = ('token',) # the verification token
	MISSING = 'slackSigningSecret (or slackOutgoingToken)'

	def secured(self):
		"""Whether slackSigningSecret or slackOutgoingToken is set."""
		return bool(config.env.slackSigningSecret or config.env.slackOutgoingToken)

	def refuse(self, environ, body, update):
		"""With slackSigningSecret, the request must carry Slack's signature of its body, made in the last five minutes;
		without it, the body must carry slackOutgoingToken (the older way, which Slack has deprecated)."""
		if config.env.slackSigningSecret:
			return self.signature_problem(environ, body, config.env.slackSigningSecret)
		if 'token' not in update:
			return "Slack authorisation field not present"
		if not inbound.same_secret(str(update['token']), config.env.slackOutgoingToken):
			return "Slack auth incorrect"
		return None

	@staticmethod
	def signature_problem(environ, body, secret):
		"""Why the request's signature fails, or None: X-Slack-Signature must be v0= and the HMAC-SHA256, under the
		signing secret, of v0:<X-Slack-Request-Timestamp>:<the body>, and the timestamp within five minutes of now."""
		timestamp = environ.get('HTTP_X_SLACK_REQUEST_TIMESTAMP', '')
		signature = environ.get('HTTP_X_SLACK_SIGNATURE')
		if signature is None or not (timestamp.isascii() and timestamp.isdigit()):
			return "Slack signature not present"
		if abs(time.time() - int(timestamp)) > SIGNATURE_AGE:
			return "Slack signature too old (a replay, or a clock is wrong)"
		signed = b'v0:' + timestamp.encode() + b':' + body
		expected = 'v0=' + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
		return None if inbound.same_secret(signature, expected) else "Slack signature incorrect"

	def decode(self, body):
		"""The update: an event comes as JSON, a button press as a form whose `payload` field holds the JSON, and a
		slash command as a form of its fields (command, text, channel_id, user_id and the rest)."""
		if not body.lstrip().startswith(b'{'):
			fields = parse_qs(body.decode('utf-8', 'replace'), keep_blank_values=True)
			if 'command' in fields and 'payload' not in fields:
				return {name: values[0] for name, values in fields.items()}
			body = fields.get('payload', [''])[0].encode()
		return super().decode(body)


WEBHOOK = SlackWebhook(slack_common.READER)
