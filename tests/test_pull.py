"""The pull modes: a network without a webhook URL is asked for its updates, which reach the same reader as the
webhook's. Telegram's long polling."""
import contextlib, io, json, unittest
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


class Backoff(unittest.TestCase):
	"""The wait after failures in a row."""

	def test_it_doubles_from_five_seconds_up_to_a_minute(self):
		"""5, 10, 20, 40, then a minute for good."""
		self.assertEqual([pull.backoff(n) for n in range(1, 8)], [5, 10, 20, 40, 60, 60, 60])


if __name__ == '__main__':
	unittest.main()
