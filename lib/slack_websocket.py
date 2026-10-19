"""Slack's Socket Mode, its pull mode (no slackOutgoingWebhook): a WebSocket that the app-level token opens, whose
envelopes carry what Slack would post to the Request URL, for the reader (slack_common.READER)."""
import json

from lib import log
from lib import pull
from lib import slack_common


class SlackSocket(pull.SocketListener):
	"""Slack's Socket Mode: a WebSocket to the URL that apps.connections.open gives for the app-level token
	(slackAppToken). Each event, button press or slash command comes in an envelope, acked at once, before anything
	else (Slack sends again what is not acked within 3 seconds); inside it is what Slack would post to
	slackOutgoingWebhook. Slack closes a socket now and then, saying so first (disconnect), and another is opened at
	once."""
	network = slack_common.READER
	TOKENS = ('slackBotToken', 'slackAppToken')
	WEBHOOK_URL = 'slackOutgoingWebhook'
	MODE = 'Socket Mode'
	PING_SECONDS = 30 # silence this long sends a ping; as long again after it, and the socket is taken for dead
	TAKEN = ('events_api', 'interactive', 'slash_commands') # the envelopes whose payload goes to the reader

	def url(self):
		"""The URL of a new socket, from apps.connections.open."""
		return slack_common.call('apps.connections.open', as_app=True)['url']

	def listen(self, connection, take):
		"""Read envelopes until Slack says it will close the socket (then another opens at once, no wait): each acked,
		then its payload handed on. A ping goes out after PING_SECONDS of silence; as long again with nothing, not even
		the pong, raises TimeoutError."""
		pinged = False
		while True:
			text = connection.receive(self.PING_SECONDS)
			if text is None:
				if pinged:
					raise TimeoutError(f'nothing from Slack for {2 * self.PING_SECONDS} s, even after a ping')
				connection.ping()
				pinged = True
				continue
			pinged = False
			if not text: # a ping or a pong
				continue
			envelope = json.loads(text)
			if envelope.get('envelope_id'):
				connection.send(json.dumps({'envelope_id': envelope['envelope_id']}))
			kind = envelope.get('type')
			if kind == 'hello':
				self.failures = 0
			elif kind == 'disconnect':
				reason = envelope.get('reason') or 'no reason given'
				log.info(f"slack: Slack is closing the socket ({reason}), opening another")
				return 0
			elif kind in self.TAKEN:
				self.hand_on(take, envelope.get('payload') or {})
