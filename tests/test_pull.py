"""The pull modes: a network without a webhook URL is asked for its updates, which reach the same reader as the
webhook's. Telegram's long polling, Slack's Socket Mode."""
import contextlib, io, json, sys, types, unittest
from urllib.parse import urlencode
from tests.common import *
from lib import pull


def callback_query(update_id, data='c|h|y|T1'):
	"""A Telegram update: a button pressed under message 9 in chat 55."""
	return {'update_id': update_id, 'callback_query': {'id': f'q{update_id}', 'from': {'username': 'rob'},
		'data': data, 'message': {'message_id': 9, 'chat': {'id': 55}}}}


class Stop(Exception):
	"""Raised by a test's fake to end a listener's loop."""


class TelegramPolling(FinbotCase):
	"""getUpdates in a loop: each update handed on in order, the next asked for after it, and failures waited out."""

	def setUp(self):
		"""Telegram in pull mode: a bot token and no webhook URL; telegram.call answers from self.answers."""
		super().setUp()
		self.env(telegramBotToken='123:abc', telegramOutgoingWebhook='')
		self.calls, self.answers = [], []
		def call(method, **kwargs):
			"""Note the call, and give the next answer (an exception is raised)."""
			self.calls.append((method, kwargs))
			answer = self.answers.pop(0)
			if isinstance(answer, Exception):
				raise answer
			return answer
		self.patch(telegram, 'call', call)

	def test_each_update_is_handed_on_in_order_and_the_next_asked_for_after_it(self):
		"""Each update goes to take in order; the next getUpdates asks for those after the last (which also tells
		Telegram it arrived), waits up to 50 seconds for one, and gives the request 65."""
		taken = []
		message = {'update_id': 10, 'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'},
			'text': '.price'}}
		self.answers += [[message, callback_query(11)], []]
		poll = pull.TelegramPoll()
		self.assertEqual(poll.poll(lambda network, update: taken.append((network, update))), 0)
		self.assertEqual(poll.poll(lambda network, update: taken.append((network, update))), 0)
		self.assertEqual(taken, [(inbound.TELEGRAM, message), (inbound.TELEGRAM, callback_query(11))])
		allowed = ['message', 'callback_query']
		self.assertEqual(self.calls, [
			('getUpdates', {'json': {'timeout': 50, 'allowed_updates': allowed}, 'timeout': (5, 65)}),
			('getUpdates', {'json': {'timeout': 50, 'allowed_updates': allowed, 'offset': 12}, 'timeout': (5, 65)})])

	def test_failures_are_waited_out_longer_each_time_and_logged_without_the_token(self):
		"""A failed getUpdates (a 409 when a webhook is set or another finbot polls, the network down) waits 5 seconds,
		then twice as long each time up to a minute; a success starts again from 5. The log never shows the token."""
		conflict = RuntimeError('Telegram getUpdates: Conflict: terminated by other getUpdates request')
		down = ConnectionError("Max retries exceeded with url: /bot123:SECRET-token/getUpdates")
		self.answers += [conflict, down, conflict, conflict, conflict, conflict, [], down]
		poll = pull.TelegramPoll()
		err = io.StringIO()
		with contextlib.redirect_stderr(err):
			waits = [poll.poll(lambda *a: None) for _ in range(8)]
		self.assertEqual(waits, [5, 10, 20, 40, 60, 60, 0, 5])
		self.assertIn('telegram: getUpdates failed, trying again in 5 s: Telegram getUpdates: Conflict', err.getvalue())
		self.assertNotIn('SECRET', err.getvalue())

	def test_an_update_that_fails_is_reported_once_and_not_fetched_again(self):
		"""An update whose handling fails is reported to the default chats, as a failed webhook request is, and the
		ones after it still go; the next getUpdates asks for those after all of them."""
		taken = []
		def take(network, update):
			"""Fail on update 20, note the rest."""
			if update['update_id'] == 20:
				raise KeyError('chat')
			taken.append(update['update_id'])
		self.answers += [[callback_query(20), callback_query(21)], []]
		poll = pull.TelegramPoll()
		poll.poll(take)
		poll.poll(take)
		self.assertEqual(taken, [21])
		self.assertEqual(self.errors, ["⚠️ telegram: KeyError: 'chat'"])
		self.assertEqual(self.calls[1][1]['json']['offset'], 22)

	def test_run_polls_for_good_waiting_as_each_round_says(self):
		"""run() logs the mode, then polls round after round, sleeping what each round returns."""
		rounds, slept = iter([0, 5, 0]), []
		poll = pull.TelegramPoll()
		self.patch(poll, 'poll', lambda take: next(rounds))
		def sleep(seconds):
			"""Note the wait; end the loop after three."""
			slept.append(seconds)
			if len(slept) == 3:
				raise Stop
		self.patch(pull.time, 'sleep', sleep)
		err = io.StringIO()
		with contextlib.redirect_stderr(err), self.assertRaises(Stop):
			poll.run(bot.take)
		self.assertEqual(slept, [0, 5, 0])
		self.assertIn('telegram: long polling for updates (no telegramOutgoingWebhook)', err.getvalue())

	def test_a_listener_for_each_network_without_a_webhook(self):
		"""Telegram is polled with its bot token and no telegramOutgoingWebhook; with the URL, or without a token, it
		is not."""
		self.assertEqual([type(listener) for listener in pull.listeners()], [pull.TelegramPoll])
		self.env(telegramOutgoingWebhook='https://example.com/telegram')
		self.assertEqual(pull.listeners(), [])
		self.env(telegramBotToken='', telegramOutgoingWebhook='')
		self.assertEqual(pull.listeners(), [])

	def test_a_press_polled_for_is_the_press_the_webhook_gets(self):
		"""The same button press, posted to the webhook (http mode) or polled for (pull mode), reaches the worker as the
		same Press, and is acknowledged the same way."""
		presses, toasts = [], []
		self.patch(worker, 'process_callback', presses.append)
		self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: toasts.append(text))
		body = json.dumps(callback_query(80)).encode()
		with contextlib.redirect_stderr(io.StringIO()):
			self.env(telegramOutgoingWebhook='https://example.com/telegram')
			bot.main(wsgi_environ('/telegram', body, HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='tok'), lambda *a: None)
			self.env(telegramOutgoingWebhook='')
			update = callback_query(81)
			update['callback_query']['id'] = 'q80' # the same press, as getUpdates gives it
			self.answers.append([update])
			pull.TelegramPoll().poll(bot.take)
		self.join_workers()
		self.assertEqual(len(presses), 2)
		self.assertEqual(presses[0], presses[1])
		self.assertEqual(toasts, ['Loading 1Y…'] * 2)


SLACK_PRESS = {'type': 'block_actions', 'token': 'stok', 'trigger_id': 't1', 'user': {'id': 'U1', 'username': 'rob'},
	'container': {'type': 'message', 'message_ts': '1.5', 'channel_id': 'C1'},
	'actions': [{'action_id': 'c|h|w|T1', 'value': 'c|h|w|T1', 'type': 'button'}]} # a period button pressed
SLACK_EVENT = {'type': 'event_callback', 'event_id': 'Ev1', 'authorizations': [{'user_id': 'UBOT'}],
	'event': {'type': 'message', 'channel': 'C1', 'user': 'U1', 'text': '.price', 'ts': '1.2'}}


class FakeSocket:
	"""A connection that gives the messages it was made with, a dict sent as JSON, and notes what is sent and when."""

	def __init__(self, messages, log):
		"""messages: what receive() gives in turn (dicts as their JSON, None for a silence); log: a list to note in."""
		self.messages, self.log = list(messages), log

	def receive(self, timeout):
		"""The next message; when there are none left, the socket fails."""
		if not self.messages:
			raise ConnectionError('the test socket has no more')
		message = self.messages.pop(0)
		return json.dumps(message) if isinstance(message, dict) else message

	def send(self, text):
		"""Note an ack."""
		self.log.append(('ack', json.loads(text)['envelope_id']))

	def ping(self):
		"""Note a ping."""
		self.log.append(('ping',))

	def close(self):
		"""Note the close."""
		self.log.append(('close',))


class SlackSocketMode(FinbotCase):
	"""Socket Mode: envelopes acked before anything else, their payloads to the same reader as the webhook's, a socket
	opened again when Slack closes it, and a silent one taken for dead."""

	def setUp(self):
		"""Slack in pull mode: the bot and app-level tokens, no webhook URL; apps.connections.open answers a URL."""
		super().setUp()
		self.env(slackBotToken='xoxb-1', slackAppToken='xapp-1', slackOutgoingWebhook='')
		self.log = []
		self.patch(transports, 'slack_api', lambda method, as_app=False, **data:
			self.log.append((method, as_app)) or {'ok': True, 'url': 'wss://example.com/link'})

	def socket(self, *messages):
		"""A SlackSocket whose connections give these messages."""
		listener = pull.SlackSocket()
		self.patch(listener, 'connect', lambda url: self.log.append(('connect', url)) or FakeSocket(messages, self.log))
		return listener

	def test_each_envelope_is_acked_before_its_payload_is_handed_on(self):
		"""After hello, an event and a button press each get their ack first, then go to take as Slack would post
		them; Slack's disconnect ends the socket, and the next round opens another at once."""
		take = lambda network, update: self.log.append(('take', network.service, update['type']))
		listener = self.socket({'type': 'hello'},
			{'envelope_id': 'e1', 'type': 'events_api', 'payload': SLACK_EVENT},
			{'envelope_id': 'e2', 'type': 'interactive', 'payload': SLACK_PRESS},
			{'type': 'disconnect', 'reason': 'refresh_requested'})
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertEqual(listener.poll(take), 0)
		self.assertEqual(self.log, [('apps.connections.open', True), ('connect', 'wss://example.com/link'),
			('ack', 'e1'), ('take', 'slack', 'event_callback'), ('ack', 'e2'), ('take', 'slack', 'block_actions'),
			('close',)])
		self.assertIn('slack: Slack is closing the socket (refresh_requested), opening another', err.getvalue())

	def test_a_silent_socket_is_pinged_then_taken_for_dead(self):
		"""Silence sends a ping; a pong (or anything) keeps the socket; silence after a ping fails it, and the next
		round waits the back-off."""
		listener = self.socket({'type': 'hello'}, None, '', None, None)
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertEqual(listener.poll(lambda *a: None), 5)
		self.assertEqual([entry for entry in self.log if entry[0] in ('ping', 'close')], [('ping',), ('ping',),
			('close',)])
		self.assertIn('slack: the socket failed, trying again in 5 s: nothing from Slack for 60 s', err.getvalue())

	def test_failures_wait_longer_each_time_and_hello_starts_again(self):
		"""A socket that cannot be opened, or fails, waits longer each time; one that says hello starts again from 5."""
		self.patch(transports, 'slack_api', mock.Mock(side_effect=RuntimeError('Slack apps.connections.open:'
			' invalid_auth')))
		listener = pull.SlackSocket()
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertEqual([listener.poll(lambda *a: None) for _ in range(3)], [5, 10, 20])
		self.assertIn('slack: opening a socket failed, trying again in 5 s: Slack apps.connections.open:'
			' invalid_auth', err.getvalue())
		self.patch(transports, 'slack_api', lambda *a, **k: {'url': 'wss://example.com/link'})
		self.patch(listener, 'connect', lambda url: FakeSocket([{'type': 'hello'}], self.log))
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(listener.poll(lambda *a: None), 5) # the socket failed, after a hello

	def test_a_press_over_the_socket_is_the_press_the_webhook_gets(self):
		"""The same button press, posted to slackOutgoingWebhook (http mode) or sent over the socket, reaches the worker
		as the same Press; an event already taken over one is not run again over the other (its event_id)."""
		presses, messages = [], []
		self.patch(worker, 'process_callback', presses.append)
		self.patch(worker, 'process_request', messages.append)
		self.env(slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='stok')
		with contextlib.redirect_stderr(io.StringIO()):
			body = urlencode({'payload': json.dumps(SLACK_PRESS)}).encode()
			bot.main(wsgi_environ('/slack', body), lambda *a: None)
			bot.main(wsgi_environ('/slack', json.dumps({**SLACK_EVENT, 'token': 'stok'}).encode()), lambda *a: None)
			self.env(slackOutgoingWebhook='')
			self.socket({'type': 'hello'}, {'envelope_id': 'e1', 'type': 'interactive', 'payload': SLACK_PRESS},
				{'envelope_id': 'e2', 'type': 'events_api', 'payload': SLACK_EVENT},
				{'type': 'disconnect', 'reason': 'warning'}).poll(bot.take)
		self.join_workers()
		self.assertEqual(len(presses), 2)
		self.assertEqual(presses[0], presses[1])
		self.assertEqual([m.text for m in messages], ['.price'])

	def test_a_slash_command_over_the_socket_is_the_message_the_webhook_gets(self):
		"""The same slash command, posted to slackOutgoingWebhook as a form (http mode) or sent over the socket (its
		envelope acked first), reaches the worker as the same Message."""
		messages = []
		self.patch(worker, 'process_request', messages.append)
		slash = {'token': 'stok', 'channel_id': 'C1', 'user_id': 'U1', 'user_name': 'rob', 'command': '/forwardpe',
			'text': 'top', 'trigger_id': 't9'}
		self.env(slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='stok')
		with contextlib.redirect_stderr(io.StringIO()):
			bot.main(wsgi_environ('/slack', urlencode(slash).encode()), lambda *a: None)
			self.env(slackOutgoingWebhook='')
			self.socket({'type': 'hello'}, {'envelope_id': 'e1', 'type': 'slash_commands', 'payload': slash},
				{'type': 'disconnect', 'reason': 'warning'}).poll(bot.take)
		self.join_workers()
		self.assertEqual(messages, [inbound.Message('slack', 'C1', '<@U1>', '/forwardpe top', '', '<@U1>')] * 2)
		self.assertIn(('ack', 'e1'), self.log)

	def test_the_websocket_is_imported_only_to_connect_and_read_as_slack_needs(self):
		"""websocket-client is imported when a socket is opened, not before; its frames read as text, '' for a pong,
		None for a timeout, and a close raises ConnectionError."""
		class Timeout(Exception):
			"""websocket-client's timeout."""
		frames = [(1, b'{"type": "hello"}'), (10, b''), Timeout(), (8, b'')]
		class WS:
			"""A websocket-client connection that gives the frames."""
			def settimeout(self, timeout):
				"""Note the timeout."""
				self.timeout = timeout
			def recv_data(self, control_frame=False):
				"""The next frame, with control frames (pings, pongs) too."""
				frame = frames.pop(0)
				if isinstance(frame, Exception):
					raise frame
				return frame
		stub = types.SimpleNamespace(create_connection=lambda url, timeout: WS(), WebSocketTimeoutException=Timeout,
			ABNF=types.SimpleNamespace(OPCODE_TEXT=1, OPCODE_CLOSE=8))
		self.patch(sys, 'modules', {**sys.modules, 'websocket': stub})
		socket = pull.WebSocket('wss://example.com/link')
		self.assertEqual([socket.receive(30) for _ in range(3)], ['{"type": "hello"}', '', None])
		with self.assertRaises(ConnectionError):
			socket.receive(30)

	def test_slack_is_listened_to_with_both_tokens_and_no_webhook(self):
		"""The socket is opened with the bot and app-level tokens and no slackOutgoingWebhook; with the URL (http mode),
		or without either token, it is not."""
		self.env(telegramBotToken='')
		self.assertEqual([type(listener) for listener in pull.listeners()], [pull.SlackSocket])
		for changes in ({'slackOutgoingWebhook': 'https://example.com/slack'}, {'slackAppToken': ''},
				{'slackBotToken': ''}):
			with self.subTest(changes=changes):
				self.env(**changes)
				self.assertEqual(pull.listeners(), [])
				self.env(slackBotToken='xoxb-1', slackAppToken='xapp-1', slackOutgoingWebhook='')


class Backoff(unittest.TestCase):
	"""The wait after failures in a row."""

	def test_it_doubles_from_five_seconds_up_to_a_minute(self):
		"""5, 10, 20, 40, then a minute for good."""
		self.assertEqual([pull.backoff(n) for n in range(1, 8)], [5, 10, 20, 40, 60, 60, 60])


if __name__ == '__main__':
	unittest.main()
