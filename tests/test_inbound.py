"""What reaches the bot: webhook requests turned away or taken, Slack's events, presses, slash commands and signatures,
the Slack app's manifest, and user text escaped where it arrives."""
import contextlib, hashlib, hmac, io, json, re, time, types, unittest
from urllib.parse import urlencode
from tests.common import *
from util import slack_manifest


PRESS = {'type': 'block_actions', 'token': 'stok', 'trigger_id': 't1', 'user': {'id': 'U1', 'username': 'rob'},
	'container': {'type': 'message', 'message_ts': '1.5', 'channel_id': 'C1'},
	'actions': [{'action_id': 'c|c|w|T1', 'value': 'c|c|w|T1', 'type': 'button'}]} # a Slack period button pressed


class WsgiRejections(FinbotCase):
	SECRET = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}

	def request(self, path='/telegram', body=None, headers=None):
		"""(the body, the status) the WSGI handler answers a request with."""
		body = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
		env = wsgi_environ(path, body, **(headers or {}))
		status = []
		with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
			out = bot.main(env, lambda s, *a, **k: status.append(s))
		return b''.join(out), status[-1]

	def test_telegram_requires_the_secret_header(self):
		"""A Telegram update without the secret header, or with a wrong one, is refused and not processed."""
		message = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'text': '.help'}}
		self.assertIn(b'Unauthorized', self.request(body=message)[0])
		self.assertIn(b'Unauthorized',
			self.request(body=message, headers={'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'wrong'})[0])
		self.assertEqual(self.sent, []) # nothing was processed

	def test_an_empty_secret_proves_nothing(self):
		"""With no secret configured, a request carrying an empty one is refused, on Telegram and on Slack."""
		self.env(telegramOutgoingToken='', slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='')
		message = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'text': '.help'}}
		empty = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': ''}
		self.assertEqual(self.request(body=message, headers=empty)[1], '403 Forbidden')
		self.assertEqual(self.request('/slack', {'token': '', 'type': 'url_verification', 'challenge': 'c'})[1],
			'403 Forbidden')
		self.assertEqual((self.sent, self.errors), ([], []))

	def test_unknown_path_is_404(self):
		"""An unknown path is 404."""
		self.assertEqual(self.request(path='/nope')[1], '404 Not Found')

	def test_malformed_body_is_refused_not_a_crash(self):
		"""A body that is not a JSON object is 400 once authenticated, and turned away unread before that."""
		# no secret: turned away before the body is read
		self.assertEqual(self.request(body=b'not json')[1], '403 Forbidden')
		for body in (b'not json', b'', b'[1, 2]', b'7'):
			self.assertEqual(self.request(body=body, headers=self.SECRET)[1], '400 Bad Request', body)
		self.assertEqual(self.errors, [])

	def test_only_the_body_is_read_and_a_huge_one_not_at_all(self):
		"""Only CONTENT_LENGTH bytes are read, since a server need not end the stream there; a body over MAX_BODY is
		refused unread, and a length that is not a number is a bad request."""
		self.patch(worker, 'process_request', lambda *a: None)
		def post(body, length):
			"""(the status, the bytes read) for this body and CONTENT_LENGTH, with more on the stream after it."""
			env = {**wsgi_environ('/telegram', body, **self.SECRET), 'CONTENT_LENGTH': length}
			env['wsgi.input'] = stream = io.BytesIO(body + b'{"the next request": 1}')
			status = []
			with contextlib.redirect_stderr(io.StringIO()):
				bot.main(env, lambda s, *a, **k: status.append(s))
			return status[-1], stream.tell()
		message = {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'text': '.help'}
		update = json.dumps({'message': message}).encode()
		self.assertEqual(post(update, str(len(update))), ('200 OK', len(update)))
		self.assertEqual(post(update, str(bot.MAX_BODY + 1)), ('413 Payload Too Large', 0))
		self.assertEqual(post(update, 'lots'), ('400 Bad Request', 0))

	def test_strangers_cannot_post_into_the_chats(self):
		"""Strangers (wrong paths, no or wrong secrets, malformed bodies) are refused, and nothing reaches the chats."""
		self.env(slackOutgoingWebhook='https://example.com/slack')

		self.env(slackOutgoingToken='stok')

		for path, body, headers, status in (('/', b'', {}, '404 Not Found'),
			('/wp-login.php', b'log=x&pwd=y', {}, '404 Not Found'),
				('/telegram', b'log=x', {}, '403 Forbidden'),
				('/telegram', {'message': {}}, {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'wrong'}, '403 Forbidden'),
				('/slack', b'', {}, '400 Bad Request'), ('/slack', b'token=stok', {}, '400 Bad Request'),
				('/slack', {'type': 'event_callback'}, {}, '403 Forbidden'),
				('/slack', {'token': 'wrong', 'type': 'event_callback'}, {}, '403 Forbidden'),
				('/slack', {'token': 'stok'}, {}, '200 OK')):
			with self.subTest(path=path, body=body):
				self.assertEqual(self.request(path, body, headers)[1], status)
		self.assertEqual(self.errors, []) # nothing reached the chats
		self.assertEqual(self.sent, [])

	def test_a_failure_before_authentication_is_only_logged(self):
		"""A failure while routing, before authentication, is logged and answered 500, never posted to the chats."""
		def broken(*a, **k):
			"""Fail while routing."""
			raise RuntimeError('boom')
		self.patch(bot, 'route', broken) # fails while routing, before the secret is even looked at
		env = wsgi_environ('/telegram', b'{}', **self.SECRET)
		status = []
		with contextlib.redirect_stderr(io.StringIO()) as err:
			bot.main(env, lambda s, *a, **k: status.append(s))
		self.assertEqual((status[-1][:3], self.errors), ('500', []))
		self.assertIn('boom', err.getvalue())

	def test_a_reported_failure_names_the_network_not_its_secret_path(self):
		"""The error line of a failed update names the network, not the webhook's path, which is a secret."""
		self.env(telegramOutgoingWebhook='https://example.com/hook-s3cret')
		broken = {'message': {'message_id': 1, 'from': {'first_name': 'A'}, 'text': '.help'}} # no chat
		self.assertEqual(self.request('/hook-s3cret', broken, self.SECRET)[1], '200 OK')
		self.assertEqual(self.errors, ["⚠️ telegram: KeyError: 'chat'"])

	def test_a_failure_after_authentication_is_reported_once_and_not_retried(self):
		"""A failure on an authenticated update is reported once and answered 200, so Telegram doesn't send it again."""
		broken = {'message': {'message_id': 1, 'from': {'first_name': 'A'}, 'text': '.help'}} # no chat
		# a retry would only fail and report again
		self.assertEqual(self.request(body=broken, headers=self.SECRET)[1], '200 OK')
		self.assertEqual(len(self.errors), 1)
		self.assertIn("KeyError: 'chat'", self.errors[0])

	def test_telegram_edge_updates(self):
		"""Edits, button presses without a message, and messages without text are answered and left alone."""
		secret = self.SECRET
		self.assertEqual(self.request(body={'edited_message': {}}, headers=secret)[0], b'Unsupported')
		self.assertEqual(self.request(body={'callback_query': {'id': '1'}}, headers=secret)[0], b'Unsupported')
		odd = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'new_chat_members': []}}
		self.assertIn(b'Unhandled', self.request(body=odd, headers=secret)[0])

	def test_a_telegram_update_sent_again_runs_once(self):
		"""An update Telegram sends again runs once."""
		calls = []
		self.patch(worker, 'process_request', lambda *a: calls.append(a))
		body = {'update_id': 7,
			'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'text': '.price'}}
		for _ in range(2): # Telegram sends an update again when it got no answer
			self.assertEqual(self.request(body=body, headers=self.SECRET)[1], '200 OK')
		self.join_workers()
		self.assertEqual(len(calls), 1)

	def test_an_update_is_taken_however_it_arrived(self):
		"""Reading an update needs no webhook: one handed over another way (as a pull mode would) reaches the worker as
		from the webhook, Telegram's message and Slack's alike, and a repeat runs once."""
		got = []
		self.patch(worker, 'process_request', got.append)
		message = {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A', 'username': 'a'}, 'text': '.price'}
		event = {'type': 'event_callback', 'event_id': 'Ev9', 'authorizations': [{'user_id': 'UBOT'}],
			'event': {'type': 'message', 'channel': 'C1', 'user': 'U1', 'text': '.trades', 'ts': '1.2'}}
		with contextlib.redirect_stderr(io.StringIO()):
			for _ in range(2):
				self.assertEqual(bot.take(telegram_common.READER, {'update_id': 70, 'message': message}), inbound.OK)
				self.assertEqual(bot.take(slack_common.READER, event), inbound.OK)
		self.join_workers()
		self.assertEqual([(m.service, m.chat_id, m.text) for m in got], [('telegram', '5', '.price'),
			('slack', 'C1', '.trades')])

	def test_button_presses_are_logged(self):
		"""A button press is logged at DEBUG (the routine of a menu) with who pressed it (handle, first name or
		unknown), the chat and the button."""
		self.settings(log_level='DEBUG')
		calls = []
		self.patch(worker, 'process_callback', lambda *a: calls.append(a))
		secret = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
		for sender, who in (({'username': 'rob', 'first_name': 'Rob'}, '@rob'), ({'first_name': 'Ann'}, 'Ann'),
				({}, 'unknown')):
			body = json.dumps({'callback_query': {'id': '1', 'from': sender, 'data': 'c|c|y|T1',
				'message': {'message_id': 9, 'chat': {'id': 55}}}}).encode()
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.main(wsgi_environ('/telegram', body, **secret), lambda *a, **k: None)
			self.assertIn(f'Telegram button {who} chat 55 c|c|y|T1', err.getvalue())

	def test_a_press_is_acknowledged_once_before_the_worker_gets_it(self):
		"""bot.take acknowledges a press, the one place that does: Telegram's with the toast its data makes, before the
		worker has it; a resent copy is neither acknowledged nor run again. Slack's needs no call: the answer to the
		update is the acknowledgement."""
		order = []
		self.patch(telegram_common, 'answerCallbackQuery',
			lambda cid, text=None, alert=False: order.append(('acknowledged', cid, text)))
		self.patch(worker, 'process_callback', lambda press: order.append(('worker', press.service, press.data)))
		update = {'update_id': 71, 'callback_query': {'id': 'q1', 'from': {'username': 'u'}, 'data': 'c|c|y|T1',
			'message': {'message_id': 9, 'chat': {'id': 55}}}}
		with contextlib.redirect_stderr(io.StringIO()):
			for _ in range(2):
				self.assertEqual(bot.take(telegram_common.READER, update), inbound.OK)
				self.join_workers()
			self.assertEqual(bot.take(slack_common.READER, PRESS), inbound.OK)
		self.join_workers()
		self.assertEqual(order, [('acknowledged', 'q1', 'Loading 1Y…'), ('worker', 'telegram', 'c|c|y|T1'),
			('worker', 'slack', 'c|c|w|T1')])


class DoubledMessages(FinbotCase):
	"""The same message from the same person in the same chat within a second is taken once: Telegram's mobile app
	can send a command twice (/start in a new chat), each its own update."""

	def setUp(self):
		"""The real check, and a clock of this test's own."""
		super().setUp()
		self.patch(bot, 'doubled', REAL_DOUBLED)
		self.now = [1000.0]
		self.patch(bot, 'time', types.SimpleNamespace(monotonic=lambda: self.now[0]))

	def send(self, update_id, text='/start', user='rob', chat=55):
		"""Take a Telegram message, as an update of this id arrives."""
		with contextlib.redirect_stderr(io.StringIO()):
			bot.take(telegram_common.READER, {'update_id': update_id, 'message': {'message_id': update_id,
				'chat': {'id': chat}, 'from': {'first_name': 'Rob', 'username': user}, 'text': text}})
		self.join_workers()

	def test_a_message_sent_again_within_a_second_is_taken_once(self):
		"""A second /start within a second is not run again; another person's, another chat's, another text, or one
		over a second later is."""
		self.send(1)
		self.send(2)
		self.assertEqual(len(self.workers), 1)
		self.send(3, user='ann')
		self.send(4, chat=66)
		self.send(5, text='.help')
		self.assertEqual(len(self.workers), 4)
		self.now[0] += 1.5
		self.send(6)
		self.assertEqual(len(self.workers), 5)

	def test_a_discord_slash_command_is_always_answered(self):
		"""A slash command sent again at once still gets its answer: Discord shows an error for an interaction left
		unanswered."""
		command = {'type': 2, 'id': '1', 'token': 't', 'application_id': '9', 'channel_id': '77',
			'member': {'user': {'id': '5', 'username': 'rob'}}, 'data': {'name': 'start'}}
		with contextlib.redirect_stderr(io.StringIO()):
			answers = [bot.take(discord_common.READER, dict(command, id=str(n))) for n in (1, 2)]
		self.assertEqual([json.loads(answer.body) for answer in answers], [{'type': 5}, {'type': 5}])


class RepeatedPresses(FinbotCase):
	"""The same button pressed again on the same message within a minute is dropped: its answer is on show (or on its
	way), or its job has run (Run now)."""

	def setUp(self):
		"""The real check, a clock of this test's own, each press taken and each acknowledgement's toast noted."""
		super().setUp()
		self.patch(worker, 'repeated', REAL_REPEATED)
		self.now = [1000.0]
		self.patch(worker, 'time', types.SimpleNamespace(monotonic=lambda: self.now[0]))
		self.taken, self.toasts = [], []
		self.patch(worker, 'process_callback', lambda press: self.taken.append((press.message_id, press.data)))
		self.patch(telegram_common, 'answerCallbackQuery', lambda cid, text=None, alert=False: self.toasts.append(text))

	def press(self, data, message_id=9):
		"""Press a button under the bot's message in chat 55, as the update arrives: the lines logged."""
		with contextlib.redirect_stderr(io.StringIO()) as err:
			bot.take(telegram_common.READER, {'callback_query': {'id': 'cb', 'from': {'username': 'u'}, 'data': data,
				'message': {'message_id': message_id, 'chat': {'id': 55}}}})
			self.join_workers()
		return err.getvalue().splitlines()

	def test_the_same_button_pressed_again_within_a_minute_is_dropped(self):
		"""Pressed again on the same message within PRESSED seconds, a button is acknowledged without a toast and not
		taken, which is logged; one pressed after another button, another message's, one PRESSED seconds after the
		press taken, or one after that press failed (forget), is taken."""
		run, top = 'm|run|0|3|ab12', 'm|top|0|ab12'
		self.assertEqual(self.press(run), [])
		self.assertEqual(self.press(run), ['Telegram duplicate button press ignored'])
		self.assertEqual((self.taken, self.toasts), ([('9', run)], ['Updating…', None]))
		self.press(top)
		self.press(run)
		self.press(run, message_id=10)
		self.now[0] += worker.PRESSED / 2
		self.press(run, message_id=10)
		self.now[0] += worker.PRESSED / 2 + 1
		self.press(run, message_id=10)
		self.assertEqual(self.taken[1:], [('9', top), ('9', run), ('10', run), ('10', run)])
		worker.forget(inbound.Press('telegram', 'cb', '55', '10', run))
		self.press(run, message_id=10)
		self.assertEqual(self.taken[-1:], [('10', run)])
		self.assertEqual(len(self.taken), 6)


class AdminOnly(FinbotCase):
	"""The commands of admin_only (.jobs, as finbot ships) are the admins' alone (admins: no one, as it ships): someone
	else's gets a refusal, and their press of one of those commands' buttons an alert, neither of them run."""
	REFUSED = "⛔ Only finbot's admins may use .jobs"

	def setUp(self):
		"""The gate as finbot ships it; each press taken and each toast noted."""
		super().setUp()
		self.settings(admin_only=config.Settings.admin_only, admins=config.Settings.admins)
		self.taken, self.toasts, self.update = [], [], 0
		transports._administers.clear()
		self.patch(worker, 'process_callback', lambda press: self.taken.append(press.data))
		self.patch(telegram_common, 'answerCallbackQuery',
			lambda cid, text=None, alert=False: self.toasts.append((text, alert)))

	def take(self, update, sender):
		"""Take a Telegram update of this kind (message or callback_query), from this sender (its 'from'): the lines of
		each message sent back."""
		self.update += 1
		self.sent.clear()
		with contextlib.redirect_stderr(io.StringIO()):
			bot.take(telegram_common.READER, {'update_id': self.update, **{kind: body | {'from': sender}
				for kind, body in update.items()}})
			self.join_workers()
		return [lines for _, lines in self.sent]

	def say(self, text, **sender):
		"""What a Telegram message of this text, from a sender called Rob (and the rest of `sender`), gets back."""
		message = {'message_id': self.update, 'chat': {'id': 55}, 'text': text}
		return self.take({'message': message}, {'first_name': 'Rob', 'id': 7} | sender)

	def test_closed_as_it_ships(self):
		""".jobs is refused to anyone, as no one is an admin; a command not in admin_only is answered."""
		self.assertEqual(self.say('.jobs', username='rob'), [[self.REFUSED]])
		self.assertEqual(self.say('.schedule'), [[self.REFUSED]]) # by any of its names
		self.assertNotIn([self.REFUSED], self.say('.help'))

	def test_an_admin_is_named_by_id_or_telegram_username(self):
		"""An admin is named by network and id, or a Telegram @username, as the log shows them, in any case; a first
		name, which anyone may take (and a handle without a username is made of), never counts."""
		self.settings(admins=('telegram:@Rob_Llama', 'telegram:123', 'slack:<@U0ABC>'))
		answered = [['No schedule is running']] # .jobs, let through: no scheduler runs in a test
		self.assertEqual(self.say('.jobs', username='rob_llama'), answered)
		self.assertEqual(self.say('.jobs', id=123), answered)
		self.assertEqual(self.say('.jobs', first_name='rob_llama'), [[self.REFUSED]])
		self.assertEqual(self.say('.jobs', first_name='@rob_llama'), [[self.REFUSED]])
		self.assertTrue(worker.admin('slack', ('U0ABC',)) and not worker.admin('discord', ('U0ABC',)))

	def test_a_telegram_groups_administrators_are_admins_there(self):
		"""The creator and the administrators of a group are admins in it, asked of getChatMember once in a while; a
		member is not, nor anyone in a direct message, nor where the question fails; the admins setting is as it was."""
		asked = []
		def member(method, **kwargs):
			"""getChatMember: Rob (7) administers the group, Ann (8) created it, anyone else is a member."""
			asked.append(kwargs['json'])
			return {'status': {'7': 'administrator', '8': 'creator'}.get(kwargs['json']['user_id'], 'member')}
		self.patch(telegram_common, 'call', member)
		group = lambda text, **sender: self.take({'message': {'message_id': self.update, 'chat': {'id': -100},
			'text': text}}, {'first_name': 'X', 'id': 7} | sender)
		answered = [['No schedule is running']]
		self.assertEqual(group('.jobs'), answered)
		self.assertEqual(group('.jobs', id=8), answered)
		self.assertEqual(group('.jobs', id=9), [[self.REFUSED]])
		self.assertEqual(asked[0], {'chat_id': '-100', 'user_id': '7'})
		self.assertEqual(group('.jobs'), answered)
		self.assertEqual(len(asked), 3) # Rob's second message is answered from what was asked
		self.assertEqual(self.say('.jobs'), [[self.REFUSED]]) # chat 55 is a person's, and no group is known yet
		self.assertEqual(len(asked), 3)
		from lib import jobs
		jobs.know(['telegram:-100', 'telegram:-200', 'slack:C1'])
		transports._administers.clear() # the earlier answer for this chat is kept for minutes
		self.assertEqual(self.say('.jobs'), answered) # Rob administers a group finbot knows: in a direct message too
		self.assertEqual(self.say('.jobs', id=9), [[self.REFUSED]])
		self.patch(telegram_common, 'call', lambda method, **kwargs: 1 / 0)
		self.assertEqual(group('.jobs', id=10), [[self.REFUSED]])
		self.settings(admins=('telegram:10',))
		self.assertEqual(group('.jobs', id=10), answered)

	def test_a_telegram_username_is_not_asked_about(self):
		"""Only a numeric user id can be asked of getChatMember: a @username is no one's proof."""
		bot = telegram_common.TelegramBot('-100')
		self.patch(telegram_common, 'call', lambda method, **kwargs: {'status': 'creator'})
		self.assertFalse(bot.administers(('@rob',)))
		self.assertTrue(bot.administers(('@rob', '7')))

	def test_a_slack_workspaces_owners_and_admins_are_admins(self):
		"""users.info says a Slack user is an admin, an owner or the primary owner of the workspace: an admin."""
		users = {'U1': {'is_admin': True}, 'U2': {'is_owner': True}, 'U3': {'is_primary_owner': True}, 'U4': {}}
		self.patch(slack_common, 'call', lambda method, **kwargs: {'ok': True, 'user': users[kwargs['user']]})
		bot = slack_common.SlackBot('C1')
		self.assertEqual([bot.administers((who,)) for who in users], [True, True, True, False])

	def test_a_discords_owner_and_administrator_roles_are_admins(self):
		"""The owner of a Discord server, and anyone with a role that has the Administrator permission (the @everyone
		role included), are admins in its channels, and in a direct message if so in any server the bot is in."""
		roles = [{'id': 'G', 'permissions': '1024'}, {'id': 'R1', 'permissions': '8'},
			{'id': 'R2', 'permissions': '2048'}]
		members = {'1': ['R1'], '2': ['R2'], '3': []}
		def answer(method, path, **kwargs):
			"""The REST answers for a channel of server G, owned by 5; channel D is a direct message."""
			if path == '/channels/D':
				return {'id': 'D'}
			if path == '/users/@me/guilds':
				return [{'id': 'G'}]
			return {'/channels/C': {'guild_id': 'G'}, '/guilds/G': {'owner_id': '5', 'roles': roles}}.get(path) or {
				'roles': members[path.rsplit('/', 1)[1]]}
		self.patch(discord_common, 'call', answer)
		bot = discord_common.DiscordBot('C')
		self.assertEqual([bot.administers((who,)) for who in ('1', '2', '3', '5')], [True, False, False, True])
		direct = discord_common.DiscordBot('D')
		self.assertEqual([direct.administers((who,)) for who in ('1', '3', '5')], [True, False, True])
		roles[0]['permissions'] = '8' # @everyone administers
		transports._administers.clear()
		self.assertTrue(bot.administers(('3',)))

	def test_the_setting_names_any_command(self):
		"""admin_only names any command, by any of its names, with or without its . or /."""
		self.settings(admin_only=('/watchlist',))
		self.assertEqual(self.say('.wishlist add T1'), [["⛔ Only finbot's admins may use .watchlist"]])
		self.assertEqual(self.say('.jobs'), [['No schedule is running']])

	def test_a_button_of_an_admins_command_is_theirs_alone(self):
		"""A press of a button of a command only the admins may use (the .jobs menu's) is refused to anyone else with an
		alert, and not run; an admin's is taken, with its own toast; a button of another command is anyone's."""
		press = lambda data, **sender: self.take({'callback_query': {'id': 'q', 'data': data,
			'message': {'message_id': 9, 'chat': {'id': 55}}}}, {'first_name': 'Rob', 'id': 7} | sender)
		press('m|top|0|ab12')
		self.assertEqual((self.taken, self.toasts), ([], [(self.REFUSED, True)]))
		press('c|c|y|T1')
		self.settings(admins=('telegram:7',))
		press('m|top|0|ab12')
		self.assertEqual((self.taken, self.toasts[1:]), (['c|c|y|T1', 'm|top|0|ab12'], [('Loading 1Y…', False),
			('Updating…', False)]))


class SlackEvents(FinbotCase):
	"""Slack sends every message in a subscribed channel, the bot's own posts included."""

	def setUp(self):
		"""Slack commands configured, and the worker replaced by a list of what it would have run."""
		super().setUp()
		self.env(slackOutgoingWebhook='https://example.com/slack')

		self.env(slackOutgoingToken='stok')

		self.requests = []
		self.patch(worker, 'process_request', self.requests.append)

	def event(self, event_id=None, **event):
		"""Post a Slack message event to the WSGI handler and return the status."""
		body = json.dumps({'token': 'stok', 'type': 'event_callback', 'authorizations': [{'user_id': 'UBOT'}],
			'event_id': event_id, 'event': dict({'type': 'message', 'channel': 'C1', 'ts': '1.2'}, **event)}).encode()
		status = []
		with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
			bot.main(wsgi_environ('/slack', body), lambda s, *a, **k: status.append(s))
		self.join_workers()
		return status[-1]

	def press(self, payload):
		"""Post a button press as Slack's interactivity does (a form, the JSON in its payload field): the status."""
		status = []
		with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
			body = urlencode({'payload': json.dumps(payload)}).encode()
			bot.main(wsgi_environ('/slack', body), lambda s, *a, **k: status.append(s))
		self.join_workers()
		return status[-1]

	def test_a_button_press_reaches_the_worker(self):
		"""A period button pressed under a chart reaches the worker, posted to the events URL: the channel, the message
		and the button's value. A press with a wrong token is refused, and one not under a message goes nowhere."""
		presses = []
		self.patch(worker, 'process_callback', presses.append)
		self.assertEqual(self.press(PRESS), '200 OK')
		self.assertEqual(presses, [inbound.Press('slack', 't1', 'C1', '1.5', 'c|c|w|T1', '@rob', ids=('U1',))])
		self.assertEqual(self.press({**PRESS, 'token': 'wrong'}), '403 Forbidden')
		self.assertEqual(self.press({**PRESS, 'container': {'type': 'view', 'view_id': 'V1'}}), '200 OK')
		self.assertEqual(self.press({**PRESS, 'actions': []}), '200 OK')
		self.assertEqual(len(presses), 1)

	def test_the_message_goes_to_the_worker_with_its_ts(self):
		"""A message reaches the worker with its ts, the message's id: finbot puts ⏳ on it while it works."""
		self.assertEqual(self.event(user='U1', text='.price'), '200 OK')
		self.assertEqual(self.requests[0].message_id, '1.2')

	def test_only_people_are_answered(self):
		"""Messages from bots, this bot included, joins, edits and events without a user are not answered; people's
		messages are, with mentions turned into @names."""
		# a webhook report
		for event in ({'subtype': 'bot_message', 'bot_id': 'B1', 'text': "⚠️ /slack: KeyError: 'user'"},
					  {'user': 'UBOT', 'bot_id': 'B2', 'text': '.holdings: Please try again'}, # this bot's own reply
					  {'user': 'UBOT', 'text': '.holdings'},
					  {'subtype': 'channel_join', 'user': 'U1', 'text': '<@U1> has joined the channel'},
					  {'subtype': 'message_changed', 'message': {'text': '.price'}},
					  {'text': '.price'}): # no user at all
			with self.subTest(event=event):
				self.assertEqual(self.event(**event), '200 OK')
		self.assertEqual((self.requests, self.errors), ([], []))
		self.assertEqual(self.event(user='U1', text='.price <@UBOT>'), '200 OK')
		self.assertEqual(self.event(user='U2', subtype='thread_broadcast', text='.trades'), '200 OK')
		self.assertEqual([(r.service, r.chat_id, r.user, r.text, r.bot_name) for r in self.requests],
						 [('slack', 'C1', '<@U1>', '.price @UBOT', '@UBOT'),
						 	('slack', 'C1', '<@U2>', '.trades', '@UBOT')])

	def test_links_and_escapes_lose_their_markup(self):
		"""Each link loses Slack's markup, however many there are (Slack links .AX tickers as domains), and Slack's
		escapes become characters again: .buy &amp; sell runs both reports."""
		for text, expected in (('.compare <http://BHP.AX|BHP.AX> <http://CBA.AX|CBA.AX>', '.compare BHP.AX CBA.AX'),
				('.price <https://example.com>', '.price https://example.com'), ('.buy &amp; sell', '.buy & sell'),
				('.watchlist add &lt;BHP&gt;', '.watchlist add <BHP>')):
			with self.subTest(text=text):
				self.assertEqual(self.event(user='U1', text=text), '200 OK')
				self.assertEqual(self.requests[-1].text, expected)

	def test_a_retried_event_runs_once(self):
		"""An event Slack sends again (same event_id) runs once."""
		for _ in range(2): # Slack resends an event it got no answer to within 3 seconds, with the same event_id
			self.assertEqual(self.event('Ev1', user='U1', text='.price'), '200 OK')
		self.assertEqual(self.event('Ev2', user='U1', text='.price'), '200 OK')
		self.assertEqual(len(self.requests), 2)

	def test_slack_does_not_change_the_telegram_bot_name(self):
		"""A Slack event leaves the Telegram bot's name alone."""
		self.patch(telegram_common.READER, 'bot_name', '@finbot_tg')
		self.event(user='U1', text='.price')
		self.assertEqual(telegram_common.READER.bot_name, '@finbot_tg')


class SlackSigning(FinbotCase):
	"""With slackSigningSecret, a Slack request must carry Slack's signature of its body, made in the last five
	minutes; the verification token is then neither needed nor enough."""

	def setUp(self):
		"""Slack commands with a signing secret, and the worker replaced by a list of what it would have run."""
		super().setUp()
		self.env(slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='stok', slackSigningSecret='sss')
		self.requests = []
		self.patch(worker, 'process_request', self.requests.append)

	def post(self, secret='sss', age=0, token='stok', headers=None, tamper=False):
		"""Post a Slack message event signed with `secret` `age` seconds ago (or with these headers instead) and
		return the status; tamper changes the body after signing."""
		body = json.dumps({'token': token, 'type': 'event_callback', 'authorizations': [{'user_id': 'UBOT'}],
			'event': {'type': 'message', 'channel': 'C1', 'user': 'U1', 'text': '.price'}}).encode()
		timestamp = str(int(time.time()) - age)
		mac = hmac.new(secret.encode(), b'v0:' + timestamp.encode() + b':' + body, hashlib.sha256).hexdigest()
		if headers is None:
			headers = {'HTTP_X_SLACK_REQUEST_TIMESTAMP': timestamp, 'HTTP_X_SLACK_SIGNATURE': 'v0=' + mac}
		env = wsgi_environ('/slack', body.replace(b'.price', b'.trades') if tamper else body, **headers)
		status = []
		with contextlib.redirect_stderr(io.StringIO()):
			bot.main(env, lambda s, *a, **k: status.append(s))
		self.join_workers()
		return status[-1]

	def test_a_button_press_is_signed_over_its_form(self):
		"""A button press is signed like an event, over the form it comes as; altered, it is refused."""
		presses = []
		self.patch(worker, 'process_callback', presses.append)
		body = urlencode({'payload': json.dumps({**PRESS, 'token': 'not needed'})}).encode()
		timestamp = str(int(time.time()))
		mac = hmac.new(b'sss', b'v0:' + timestamp.encode() + b':' + body, hashlib.sha256).hexdigest()
		headers = {'HTTP_X_SLACK_REQUEST_TIMESTAMP': timestamp, 'HTTP_X_SLACK_SIGNATURE': 'v0=' + mac}
		for sent, status in ((body, '200 OK'), (body.replace(b'T1', b'T2'), '403 Forbidden')):
			answers = []
			with contextlib.redirect_stderr(io.StringIO()):
				bot.main(wsgi_environ('/slack', sent, **headers), lambda s, *a, **k: answers.append(s))
			self.join_workers()
			self.assertEqual(answers, [status])
		self.assertEqual(presses, [inbound.Press('slack', 't1', 'C1', '1.5', 'c|c|w|T1', '@rob', ids=('U1',))])

	def test_a_signed_request_is_answered_and_the_token_is_not_needed(self):
		"""A request signed with the secret is answered, whatever token it carries."""
		self.assertEqual([self.post(), self.post(token='wrong')], ['200 OK'] * 2)
		self.assertEqual(len(self.requests), 2)

	def test_unsigned_wrongly_signed_old_or_altered_requests_are_refused(self):
		"""No signature (the right token is not enough), a wrong secret, a timestamp more than five minutes away or
		not a number, and a body changed after signing are all refused."""
		for case in (dict(headers={}), dict(secret='wrong'), dict(age=400), dict(age=-400), dict(tamper=True),
				dict(headers={'HTTP_X_SLACK_REQUEST_TIMESTAMP': 'soon', 'HTTP_X_SLACK_SIGNATURE': 'v0=00'})):
			with self.subTest(**case):
				self.assertEqual(self.post(**case), '403 Forbidden')
		self.assertEqual((self.requests, self.errors), ([], []))


SLASH = {'token': 'stok', 'team_id': 'T1', 'channel_id': 'C1', 'channel_name': 'stocks', 'user_id': 'U1',
	'user_name': 'rob', 'command': '/movers', 'text': '5 &amp; 7d', 'response_url': 'https://hooks.slack.com/r/1',
	'trigger_id': 't9', 'api_app_id': 'A1'} # a Slack slash command, as its form's fields or a socket's payload


class SlackSlashCommands(FinbotCase):
	"""A Slack slash command posted to slackOutgoingWebhook as a form, signed as an event is."""

	def setUp(self):
		"""Slack in HTTP mode with a signing secret, and the worker replaced by a list of what it would have run."""
		super().setUp()
		self.env(slackOutgoingWebhook='https://example.com/slack', slackSigningSecret='sss')
		self.requests = []
		self.patch(worker, 'process_request', self.requests.append)

	def post(self, fields, secret='sss'):
		"""Post the form of a slash command, signed with secret: (the status, the body)."""
		body = urlencode(fields).encode()
		timestamp = str(int(time.time()))
		mac = hmac.new(secret.encode(), b'v0:' + timestamp.encode() + b':' + body, hashlib.sha256).hexdigest()
		env = wsgi_environ('/slack', body, HTTP_X_SLACK_REQUEST_TIMESTAMP=timestamp, HTTP_X_SLACK_SIGNATURE='v0=' + mac)
		status = []
		with contextlib.redirect_stderr(io.StringIO()):
			answer = b''.join(bot.main(env, lambda s, *a, **k: status.append(s)))
		self.join_workers()
		return status[-1], answer

	def test_a_slash_command_is_the_message_that_says_the_same(self):
		"""/movers with 5 &amp; 7d is the message /movers 5 & 7d, from <@U1>, in the channel or DM it was sent in, which
		the reply goes to; Slack gets an empty 200 at once. There is no message of it, so no ⏳."""
		self.assertEqual(self.post(SLASH), ('200 OK', b''))
		self.assertEqual(self.post({**SLASH, 'channel_id': 'D1', 'command': '/job', 'text': ''}), ('200 OK', b''))
		self.assertEqual(self.requests, [inbound.Message('slack', 'C1', '<@U1>', '/movers 5 & 7d', '', '<@U1>',
			ids=('U1',)), inbound.Message('slack', 'D1', '<@U1>', '/job', '', '<@U1>', ids=('U1',))])
		self.assertEqual([worker.read(r.text, r.bot_name)[0].names[0] for r in self.requests], ['movers', 'jobs'])
		self.assertFalse(delivery.reply_to('slack', 'C1', self.requests[0].message_id).shows_typing)

	def test_a_slash_command_unsigned_or_altered_is_refused(self):
		"""A slash command signed with another secret is refused, and none reaches the worker."""
		self.assertEqual(self.post(SLASH, secret='wrong')[0], '403 Forbidden')
		self.assertEqual(self.requests, [])


class SlackManifest(unittest.TestCase):
	"""util/slack_manifest.py: the Slack app's manifest, with the slash commands of the command table."""

	def test_socket_mode_or_http_mode(self):
		"""Without a URL, Socket Mode and no Request URL anywhere; with one, HTTP mode and that URL for the events, the
		buttons and every slash command. Either way: the messages tab for DMs, interactivity, and the scopes that the
		replies, the slash commands, the charts, ⏳ and each event need."""
		socket = slack_manifest.manifest()
		self.assertTrue(socket['settings']['socket_mode_enabled'])
		self.assertNotIn('request_url', json.dumps(socket))
		self.assertNotIn('"url"', json.dumps(socket))
		url = 'https://www.example.com:8443/slack'
		http = slack_manifest.manifest(url=url)
		self.assertFalse(http['settings']['socket_mode_enabled'])
		self.assertEqual((http['settings']['event_subscriptions']['request_url'],
			http['settings']['interactivity']['request_url']), (url, url))
		self.assertTrue(all(command['url'] == url for command in http['features']['slash_commands']))
		for manifest in (socket, http):
			self.assertTrue(manifest['features']['app_home']['messages_tab_enabled'])
			self.assertTrue(manifest['settings']['interactivity']['is_enabled'])
			self.assertEqual(manifest['settings']['event_subscriptions']['bot_events'], ['app_mention', 'message.im'])
			self.assertEqual(manifest['oauth_config']['scopes']['bot'], ['app_mentions:read', 'chat:write', 'commands',
				'files:read', 'files:write', 'im:history', 'reactions:write', 'users:read'])

	def test_every_message_and_the_slash_commands(self):
		"""With every_message the bot hears every message in its channels (not only mentions, which it would then
		answer twice). The slash commands are the command table's, second names included, each named and described
		as Slack allows, and each reads as its command."""
		manifest = slack_manifest.manifest(every_message=True)
		self.assertEqual(manifest['settings']['event_subscriptions']['bot_events'],
			['message.channels', 'message.groups', 'message.im'])
		self.assertIn('channels:history', manifest['oauth_config']['scopes']['bot'])
		self.assertNotIn('app_mentions:read', manifest['oauth_config']['scopes']['bot'])
		commands = manifest['features']['slash_commands']
		self.assertEqual([c['command'] for c in commands], ['/' + command.name for command in worker.slash_commands()])
		names = {c['command'] for c in commands}
		self.assertTrue({'/stock', '/jobs', '/pe'} <= names and not {'/profile', '/job'} & names)
		for command in commands:
			with self.subTest(command=command['command']):
				self.assertRegex(command['command'], r'^/[a-z0-9_]{1,31}$')
				self.assertTrue(0 < len(command['description']) <= 2000)
				self.assertLessEqual(len(command.get('usage_hint', '')), 1000)
				self.assertIsNotNone(worker.read(f"{command['command']} {command.get('usage_hint', '')}", '')[0])

	def test_the_tool_prints_json_and_refuses_a_plain_http_url(self):
		"""The tool prints the manifest as JSON, to paste; a URL that is not HTTPS is refused, as Slack would."""
		with contextlib.redirect_stdout(io.StringIO()) as out:
			self.assertEqual(slack_manifest.main(['--name', 'stockbot']), 0)
		self.assertEqual(json.loads(out.getvalue())['features']['bot_user']['display_name'], 'stockbot')
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertEqual(slack_manifest.main(['--url', 'http://www.example.com/slack']), 2)
		self.assertIn('--url must be https://', err.getvalue())


class UserTextIsEscaped(FinbotCase):
	"""Replies go out as Telegram HTML: text a user wrote is shown, never read as markup."""

	def test_a_telegram_name_is_escaped_where_it_arrives(self):
		"""A Telegram first name is escaped as the update arrives, in the handle and the name."""
		requests = []
		self.patch(worker, 'process_request', requests.append)
		body = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A<b>&'}, 'text': '.hello'}}
		env = wsgi_environ('/telegram', json.dumps(body).encode(), HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='tok')
		with contextlib.redirect_stderr(io.StringIO()):
			bot.main(env, lambda *a, **k: None)
		self.join_workers()
		self.assertEqual((requests[0].user, requests[0].user_name), ('@A&lt;b&gt;&amp;',) * 2) # the handle and the name


if __name__ == '__main__':
	unittest.main()
