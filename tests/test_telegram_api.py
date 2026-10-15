"""Telegram's Bot API: the webhook set or deleted once, as bot.py starts."""
import contextlib, io, os, subprocess, unittest
from tests.common import *


class TelegramWebhook(FinbotCase):
	"""bot.py registers the webhook once as it starts; importing lib.telegram, as each job does, does nothing."""

	def setUp(self):
		"""A Telegram bot with an outgoing webhook configured."""
		super().setUp()
		self.env(telegram_api='https://api.telegram.org/botX/')
		self.env(telegramOutgoingWebhook='https://example.com/telegram')


	def test_register_sets_the_webhook_again_or_deletes_it_and_names_the_bot(self):
		"""register() deletes the webhook, keeping the updates not delivered yet; sets it again with
		telegramOutgoingWebhook (http mode), or leaves it unset for getUpdates (pull mode); and returns the bot's @name.
		The log never shows the URL: its path is a secret."""
		calls = []
		def post(url, **kwargs):
			"""Record the method and what it was given, and answer like Telegram."""
			calls.append((url.rsplit('/', 1)[1], kwargs.get('params', {}).get('url') or kwargs.get('json')))
			return Resp({'ok': True, 'result': {'username': 'finbot'} if url.endswith('getMe') else True})
		self.patch(telegram.net, 'post', post)
		kept = ('deleteWebhook', {'drop_pending_updates': False})
		for hook, expected in (('https://example.com/telegram', [kept, ('setWebhook', 'https://example.com/telegram'),
				('getMe', None)]), ('', [kept, ('getMe', None)])):
			with self.subTest(telegramOutgoingWebhook=hook):
				self.env(telegramOutgoingWebhook=hook)
				calls.clear()
				err = io.StringIO()
				with contextlib.redirect_stderr(err):
					self.assertEqual(telegram.register(), '@finbot')
				self.assertEqual(calls, expected)
				self.assertNotIn('example.com', err.getvalue())

	def test_a_refused_call_raises(self):
		"""A call Telegram refuses raises with its description."""
		self.patch(telegram.net, 'post',
			lambda url, **k: Resp({'ok': False, 'description': 'Bad Request: bad webhook: HTTPS url must be provided'}))
		with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as caught:
			telegram.register()
		self.assertIn('HTTPS url must be provided', str(caught.exception))

	def test_edits_toasts_and_typing_go_through_call(self):
		"""A chart edit that Telegram refuses is an error (unless nothing changed); a toast, a text edit or a typing
		notice that fails, or an edit lost on the way, is only logged."""
		def answer(outcome):
			"""A net.post that answers with outcome, or raises it."""
			def post(url, **kwargs):
				"""The outcome, or raise it."""
				if isinstance(outcome, Exception):
					raise outcome
				return outcome
			return post
		refused = Resp({'ok': False, 'description': 'Bad Request: message to edit not found'})
		unchanged = Resp({'ok': False,
			'description': 'Bad Request: message is not modified: specified new message content is the same'})
		chat = transports.TelegramBot('5')
		for outcome, raises in ((refused, True), (unchanged, False), (ConnectionError('down'), False),
				(Resp({'ok': True, 'result': True}), False)):
			with self.subTest(outcome=outcome):
				self.patch(telegram.net, 'post', answer(outcome))
				with contextlib.redirect_stderr(io.StringIO()):
					if raises:
						with self.assertRaisesRegex(RuntimeError, 'not found'):
							chat.edit_chart('9', io.BytesIO(b'png'), 'caption')
					else:
						chat.edit_chart('9', io.BytesIO(b'png'), 'caption')
					telegram.answerCallbackQuery('1', 'Loading…')
					chat.edit_text('9', 'text')
					chat.typing()

	def test_importing_never_calls_telegram(self):
		"""Importing the modules a job process uses makes no request."""
		code = ('import requests\n'
				'def refuse(*a, **k): raise SystemExit("network call on import")\n'
				'requests.Session.request = refuse\n'
				'from lib import telegram, yahoo, worker, jobs\n'
				'print("quiet")')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data, 'telegramBotToken': '123:abc',
					'telegramOutgoingWebhook': 'https://example.com/telegram'})
		self.assertEqual(out.stdout.split()[-1:], ['quiet'], out.stderr)

	def test_the_bot_will_not_start_unregistered_and_never_logs_the_token(self):
		"""bot.py exits when the webhook cannot be registered, and never logs the token."""
		skip_if_old_env(self)
		with tempfile.TemporaryDirectory() as data:
			env = {k: v for k, v in bare_environment().items() if 'proxy' not in k.lower()}
			no_jobs(data)
			env.update(DATA_DIR=data, port='0', telegramBotToken='123456:SECRET-token',
				telegramOutgoingToken='tok',
					   telegramOutgoingWebhook='https://example.com/telegram',
					   # unreachable, so the registration fails at once and offline
					   HTTPS_PROXY='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9')
			out = subprocess.run([sys.executable, 'bot.py'], cwd=ROOT, env=env, capture_output=True, text=True,
				timeout=120)
		self.assertEqual(out.returncode, 1, out.stderr)
		self.assertIn('ERROR ⚠️ telegram:', out.stderr)
		self.assertNotIn('SECRET-token', out.stderr + out.stdout)


if __name__ == '__main__':
	unittest.main()
