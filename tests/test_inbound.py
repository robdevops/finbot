"""What reaches the bot: webhook requests turned away or taken, Slack's events, presses, slash commands and signatures,
the Slack app's manifest, and user text escaped where it arrives."""
import contextlib, hashlib, hmac, io, json, re, time, types, unittest
from urllib.parse import urlencode
from tests.common import *
from util import slack_manifest


PRESS = {'type': 'block_actions', 'token': 'stok', 'trigger_id': 't1', 'user': {'id': 'U1', 'username': 'rob'},
	'container': {'type': 'message', 'message_ts': '1.5', 'channel_id': 'C1'},
	'actions': [{'action_id': 'c|h|w|T1', 'value': 'c|h|w|T1', 'type': 'button'}]} # a Slack period button pressed


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
			body = json.dumps({'callback_query': {'id': '1', 'from': sender, 'data': 'c|h|y|T1',
				'message': {'message_id': 9, 'chat': {'id': 55}}}}).encode()
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.main(wsgi_environ('/telegram', body, **secret), lambda *a, **k: None)
			self.assertIn(f'Telegram button {who} chat 55 c|h|y|T1', err.getvalue())

	def test_a_press_is_acknowledged_once_before_the_worker_gets_it(self):
		"""bot.take acknowledges a press, the one place that does: Telegram's with the toast its data makes, before the
		worker has it; a resent copy is neither acknowledged nor run again. Slack's needs no call: the answer to the
		update is the acknowledgement."""
		order = []
		self.patch(telegram_common, 'answerCallbackQuery',
			lambda cid, text=None, alert=False: order.append(('acknowledged', cid, text)))
		self.patch(worker, 'process_callback', lambda press: order.append(('worker', press.service, press.data)))
		update = {'update_id': 71, 'callback_query': {'id': 'q1', 'from': {'username': 'u'}, 'data': 'c|h|y|T1',
			'message': {'message_id': 9, 'chat': {'id': 55}}}}
		with contextlib.redirect_stderr(io.StringIO()):
			for _ in range(2):
				self.assertEqual(bot.take(telegram_common.READER, update), inbound.OK)
				self.join_workers()
			self.assertEqual(bot.take(slack_common.READER, PRESS), inbound.OK)
		self.join_workers()
		self.assertEqual(order, [('acknowledged', 'q1', 'Loading 1Y…'), ('worker', 'telegram', 'c|h|y|T1'),
			('worker', 'slack', 'c|h|w|T1')])


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
		self.assertEqual(presses, [inbound.Press('slack', 't1', 'C1', '1.5', 'c|h|w|T1', '@rob')])
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
				('.plan buy &lt;BHP&gt;', '.plan buy <BHP>')):
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
		self.assertEqual(presses, [inbound.Press('slack', 't1', 'C1', '1.5', 'c|h|w|T1', '@rob')])

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
	'user_name': 'rob', 'command': '/price', 'text': '5 &amp; 7d', 'response_url': 'https://hooks.slack.com/r/1',
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
		"""/price with 5 &amp; 7d is the message /price 5 & 7d, from <@U1>, in the channel or DM it was sent in, which
		the reply goes to; Slack gets an empty 200 at once. There is no message of it, so no ⏳."""
		self.assertEqual(self.post(SLASH), ('200 OK', b''))
		self.assertEqual(self.post({**SLASH, 'channel_id': 'D1', 'command': '/job', 'text': ''}), ('200 OK', b''))
		self.assertEqual(self.requests, [inbound.Message('slack', 'C1', '<@U1>', '/price 5 & 7d', '', '<@U1>'),
			inbound.Message('slack', 'D1', '<@U1>', '/job', '', '<@U1>')])
		self.assertEqual([worker.read(r.text, r.bot_name)[0].names[0] for r in self.requests], ['price', 'jobs'])
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
				'files:read', 'files:write', 'im:history', 'reactions:write'])

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
		self.assertTrue({'/profile', '/job', '/forwardpe'} <= {c['command'] for c in commands})
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
	"""Replies go out as Telegram HTML: text a user wrote is shown, never read as markup. One stray < in a .plan entry
	made Telegram refuse that reply and every .plan reply after it."""

	def test_a_plan_is_shown_as_text(self):
		"""A .plan entry is shown as text on Telegram and on Slack, escaped once, and a Slack mention stays markup."""
		reply = self.command('.plan buy <cheap> & hold')[0][1]
		self.assertIn('<i>buy &lt;cheap&gt; &amp; hold</i>', reply[0])
		self.assertEqual(self.command('.plan')[0][1], reply) # and the same way again
		self.sent.clear()
		# inbound has unescaped Slack's text
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.plan sell <dear> & run', BOT, 'U'))
		text = '\n'.join(self.sent[0][1])
		self.assertIn('*<@U1>*', text) # a Slack mention stays markup
		self.assertIn('_sell &lt;dear&gt; &amp; run_', text) # escaped once, not twice

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
