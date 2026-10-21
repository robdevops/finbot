"""Telegram's Bot API: the webhook set or deleted once, as bot.py starts, and the command menu."""
import contextlib, io, os, re, subprocess, unittest
from unittest import mock
from tests.common import *


class TelegramWebhook(FinbotCase):
	"""bot.py sets the webhook once as it starts (or deletes it, for long polling); importing does nothing."""

	def setUp(self):
		"""A Telegram bot with an outgoing webhook configured."""
		super().setUp()
		self.env(telegram_api='https://api.telegram.org/botX/')
		self.env(telegramOutgoingWebhook='https://example.com/telegram')


	def test_start_sets_the_webhook_again_or_deletes_it_and_names_the_bot(self):
		"""start() deletes the webhook, keeping the updates not delivered yet, and sets it again with
		telegramOutgoingWebhook (http mode), or leaves it unset for getUpdates (pull mode); it notes the bot's @name
		and makes the command menu. The log never shows the URL, nor a request's query string (which a failed
		request's error would print): its path is a secret."""
		calls, menus = [], []
		def post(url, **kwargs):
			"""Record the method and what it was given, and answer like Telegram."""
			self.assertNotIn('params', kwargs)
			given = kwargs.get('json')
			calls.append((url.rsplit('/', 1)[1], given.get('url', given) if isinstance(given, dict) else given))
			return Resp({'ok': True, 'result': {'username': 'finbot'} if url.endswith('getMe') else True})
		self.patch(net, 'post', post)
		self.patch(telegram_common, 'set_commands', menus.append)
		self.patch(telegram_common.READER, 'bot_name', None)
		kept = ('deleteWebhook', {'drop_pending_updates': False})
		for hook, expected in (('https://example.com/telegram', [kept, ('setWebhook', 'https://example.com/telegram'),
				('getMe', None)]), ('', [kept, ('getMe', None)])):
			with self.subTest(telegramOutgoingWebhook=hook):
				self.env(telegramOutgoingWebhook=hook)
				calls.clear()
				err = io.StringIO()
				with contextlib.redirect_stderr(err):
					telegram_common.start(['the commands'])
				self.assertEqual((calls, telegram_common.READER.bot_name, menus[-1]),
					(expected, '@finbot', ['the commands']))
				self.assertNotIn('example.com', err.getvalue())

	def test_a_refused_call_raises(self):
		"""A call Telegram refuses raises with its description."""
		self.patch(net, 'post',
			lambda url, **k: Resp({'ok': False, 'description': 'Bad Request: bad webhook: HTTPS url must be provided'}))
		with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as caught:
			telegram_common.start([])
		self.assertIn('HTTPS url must be provided', str(caught.exception))

	def test_a_dms_keyboard_is_given_once_and_again_when_it_changes(self):
		"""A DM is given the command keyboard after a command where it has none, or another (a message carries it:
		Telegram changes a reply keyboard no other way), and not again while it is the same; a group never is; a
		keyboard that did not go is tried again after the next command."""
		sent = []
		def post(url, **kwargs):
			"""Note the method and the chat, and answer as Telegram does."""
			sent.append((url.rsplit('/', 1)[1], kwargs['json']['chat_id']))
			return Resp({'ok': True, 'result': {'message_id': 1}})
		self.patch(net, 'post', post)
		with contextlib.redirect_stderr(io.StringIO()):
			for chat in ('55', '55', '-100'):
				telegram_common.keep_keyboard(chat, ('.price', '.movers'))
			self.assertEqual(sent, [('sendMessage', '55')])
			telegram_common.keep_keyboard('55', ('.price',)) # the keyboard changed
			self.assertEqual(sent[1:], [('sendMessage', '55')])
			self.patch(net, 'post', lambda url, **kwargs: Resp({'ok': False, 'description': 'Forbidden'}, 403))
			telegram_common.keep_keyboard('56', ('.price',))
			self.patch(net, 'post', post)
			telegram_common.keep_keyboard('56', ('.price',))
		self.assertEqual(sent[2:], [('sendMessage', '56')])

	def test_start_and_help_give_a_dm_its_keyboard_again(self):
		"""/start (what Telegram sends as a chat opens, or restarts) and /help give a DM its keyboard again, though it
		has it, so that one that went with the messages a person cleared comes back; any other command only a new
		one; a group never."""
		texts = []
		self.patch(telegram_common, 'call', lambda method, **kwargs: texts.append(kwargs['json']['text']) or {})
		with contextlib.redirect_stderr(io.StringIO()):
			telegram_common.keep_keyboard('55', ('.price',))
			for text in ('.movers', '/start', '/help', '.help', '.movers'):
				self.command(text)
			self.command('/start', chat='-100')
		self.assertEqual([text for text in texts if 'Keyboard' in text], ['⌨️ Keyboard updated', '⌨️ Keyboard updated']
			+ ['⌨️ Keyboard'] * 3)

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
		chat = telegram_common.TelegramBot('5')
		for outcome, raises in ((refused, True), (unchanged, False), (ConnectionError('down'), False),
				(Resp({'ok': True, 'result': True}), False)):
			with self.subTest(outcome=outcome):
				self.patch(net, 'post', answer(outcome))
				with contextlib.redirect_stderr(io.StringIO()):
					if raises:
						with self.assertRaisesRegex(RuntimeError, 'not found'):
							chat.edit_chart('9', io.BytesIO(b'png'), 'caption')
					else:
						chat.edit_chart('9', io.BytesIO(b'png'), 'caption')
					telegram_common.answerCallbackQuery('1', 'Loading…')
					chat.edit_text('9', 'text')
					chat.typing()

	def test_importing_never_calls_telegram(self):
		"""Importing Telegram's modules, and those they work with, makes no request."""
		code = ('import requests\n'
				'def refuse(*a, **k): raise SystemExit("network call on import")\n'
				'requests.Session.request = refuse\n'
				'from lib import telegram_common, telegram_longpolling, telegram_webhook, yahoo, worker, jobs\n'
				'print("quiet")')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data, 'telegramBotToken': '123:abc',
					'telegramOutgoingWebhook': 'https://example.com/telegram'})
		self.assertEqual(out.stdout.split()[-1:], ['quiet'], out.stderr)

	def test_the_command_menu_is_set_only_when_it_differs(self):
		"""The menu is the slash commands, each with its usage, without their second names (/profile, /job: typed, they
		work as any name does), set only when Telegram's menu differs; a failure is only logged."""
		calls, menu = [], []
		def call(method, **kwargs):
			"""Telegram's menu, as getMyCommands and setMyCommands see it."""
			calls.append(method)
			if method == 'setMyCommands':
				menu[:] = kwargs['json']['commands']
				return True
			return list(menu)
		self.patch(telegram_common, 'call', call)
		with contextlib.redirect_stderr(io.StringIO()) as log:
			telegram_common.set_commands(worker.slash_commands())
			telegram_common.set_commands(worker.slash_commands())
		self.assertEqual(calls, ['getMyCommands', 'setMyCommands', 'getMyCommands'])
		self.assertIn(f'telegram: {len(menu)} commands in the menu', log.getvalue())
		names = [entry['command'] for entry in menu]
		self.assertIn({'command': 'ratio',
			'description': 'ratio [SYMBOL] [forward|current|peg] [top|bottom|negative|reverse]'}, menu)
		self.assertEqual([name in names for name in ('stock', 'jobs', 'profile', 'job')], [True, True, False, False])
		self.assertTrue(all(re.fullmatch(r'[a-z0-9_]{1,32}', name) for name in names))
		self.patch(telegram_common, 'call', mock.Mock(side_effect=RuntimeError('Telegram getMyCommands: Unauthorized')))
		with contextlib.redirect_stderr(io.StringIO()) as log:
			telegram_common.set_commands(worker.slash_commands())
		self.assertIn('Telegram setMyCommands failed: Telegram getMyCommands: Unauthorized', log.getvalue())

	def test_the_bot_will_not_start_unregistered_and_never_logs_the_token(self):
		"""bot.py exits when the webhook cannot be registered, and never logs the token."""
		with tempfile.TemporaryDirectory() as data:
			env = {k: v for k, v in bare_environment().items() if 'proxy' not in k.lower()}
			no_jobs(data)
			env.update(DATA_DIR=data, port='0', telegramBotToken='123456:SECRET-token',
				telegramSecretToken='tok',
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
