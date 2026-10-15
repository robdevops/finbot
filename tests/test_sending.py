"""Posting to the networks against their answers and failures: Telegram, Slack (text, charts, Block Kit
buttons) and Discord."""
import contextlib, io, json, threading, unittest
from unittest import mock
from tests.common import *


class TelegramSending(FinbotCase):
	"""A message posted to Telegram against failing endpoints: the real send path, not the base fixture's recorder."""

	def post(self, outcome):
		"""Post 'hi' to a Telegram chat, the request answering with outcome (or raising it)."""
		def fake(url, **kwargs):
			"""The outcome, or raise it."""
			if isinstance(outcome, Exception):
				raise outcome
			return outcome
		self.patch(transports.net, 'post', fake)
		return transports.TelegramBot('5').post_text('hi')

	def test_success_returns_the_message(self):
		"""A sent message returns the message, as Telegram gives it."""
		self.assertEqual(self.post(Resp({'ok': True, 'result': {'message_id': 7}})), {'message_id': 7})

	def test_a_refusal_or_failure_returns_none_and_logs_why(self):
		"""A refused or failed send returns None, and the log has Telegram's reason; a 200 that is not JSON is no
		message either."""
		refusal = Resp({'ok': False, 'error_code': 400, 'description': "Bad Request: can't parse entities"}, 400)
		for outcome in (refusal, Resp(status=429), ConnectionError('down'), Resp(None)):
			with self.subTest(outcome=outcome), contextlib.redirect_stderr(io.StringIO()):
				self.assertIsNone(self.post(outcome))
		self.assertIn("can't parse entities", self.logged(refusal))

	def logged(self, outcome):
		"""What posting with this outcome logs."""
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.post(outcome)
		return log.getvalue()

	def test_a_chart_goes_without_a_parameter_sendphoto_does_not_take(self):
		"""sendPhoto is sent the chat, caption and markup, and no link-preview flag: a photo has no preview."""
		sent = []
		self.patch(transports.net, 'post', lambda url, **kwargs: sent.append((url, kwargs)) or
			Resp({'ok': True, 'result': {'message_id': 8}}))
		self.assertEqual(transports.TelegramBot('5').post_chart(io.BytesIO(b'png'), 'caption'), {'message_id': 8})
		url, kwargs = sent[0]
		self.assertTrue(url.endswith('/sendPhoto'))
		self.assertEqual(kwargs['data'], {'chat_id': '5', 'caption': 'caption', 'parse_mode': 'HTML',
			'disable_notification': True})

	def test_error_line_redacts_secrets_and_truncates(self):
		"""An error line has no token or crumb in it, and is cut to about 200 characters."""
		line = delivery.error_line(RuntimeError('GET /bot123456:ABC-def_1/send?crumb=SECRET&x=1 failed'), 'ctx')
		self.assertNotIn('ABC-def_1', line)
		self.assertNotIn('SECRET', line)
		self.assertTrue(line.startswith('⚠️ ctx: '))
		self.assertLessEqual(len(delivery.error_line('x' * 1000)), 205)

	def test_error_reports_are_escaped_for_telegram_and_slack(self):
		"""An error line is escaped for Telegram's HTML and Slack (the same), and left as it is for Discord."""
		sent = []
		self.patch(transports.Transport, 'text', REAL_TEXT)
		for kind in (transports.TelegramBot, transports.SlackWebhook, transports.DiscordWebhook):
			self.patch(kind, 'post_text', lambda dest, text, buttons=None: sent.append((dest.name, text)))
		self.env(webhooks={'telegram': 'https://api.telegram.org/botX/', 'slack': 'https://hooks.slack.com/x',
			'discord': 'https://discord.com/x/slack'})
		self.env(telegramChatID='5')

		error = RuntimeError("404 for ZZ at https://x/?a=1&crumb=abc; '<' not supported between <urllib3.connection>")
		with contextlib.redirect_stderr(io.StringIO()):
			REAL_REPORT_ERROR(error, context='.compare <b>')
			REAL_REPORT_ERROR(error, transports.TelegramBot('55'), context='.compare')
		texts = dict(sent[:3])
		self.assertIn('crumb=&lt;redacted&gt;', texts['telegram']) # Telegram's HTML parser rejects a bare <redacted>
		self.assertNotIn('<', texts['telegram'] + sent[3][1])
		self.assertIn('.compare &lt;b&gt;: RuntimeError', texts['telegram'])
		self.assertEqual(texts['slack'], texts['telegram'])
		self.assertIn('crumb=<redacted>', texts['discord'])

	def test_report_error_never_raises(self):
		"""report_error survives a failed send."""
		self.patch(transports.Transport, 'text', mock.Mock(side_effect=RuntimeError('send failed')))
		with contextlib.redirect_stderr(io.StringIO()):
			REAL_REPORT_ERROR(ValueError('boom'), transports.TelegramBot('5'))
			REAL_REPORT_ERROR(ValueError('boom'))

	def test_guarded_reports_and_exits_nonzero(self):
		"""guarded reports a failure and exits 1; a success returns its value."""
		reported = []
		self.patch(delivery, 'report_error', lambda e, **k: reported.append(e))
		with self.assertRaises(SystemExit) as raised:
			delivery.guarded('job', lambda: 1 / 0)
		self.assertEqual(raised.exception.code, 1)
		self.assertEqual(len(reported), 1)
		self.assertEqual(delivery.guarded('job', lambda: 'fine'), 'fine')


class ChartDelivery(FinbotCase):
	"""Charts reach Telegram and Slack replies (uploaded); a report whose chart fails still goes, as text."""
	UPLOAD_URL = 'https://files.slack.com/upload/v1/abc'

	def setUp(self):
		"""The real Transport.chart, in place of the fixture's recorder."""
		super().setUp()
		self.patch(transports.Transport, 'chart', REAL_CHART)

	def slack_answers(self, *outcomes):
		"""net.post for the upload steps: the outcomes in turn (an exception is raised). Returns the calls made."""
		calls = []
		def post(url, **kwargs):
			"""Record the call and answer with the next outcome, or raise it."""
			calls.append((url, kwargs))
			outcome = outcomes[len(calls) - 1]
			if isinstance(outcome, Exception):
				raise outcome
			return outcome
		self.patch(transports.net, 'post', post)
		return calls

	def upload_steps(self):
		"""Slack's answers to the three upload steps, each a success."""
		return [Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': 'F1'}), Resp(None, text='OK - 3'),
			Resp({'ok': True, 'files': [{'id': 'F1'}]})]

	def test_where_charts_can_go(self):
		"""Charts always go to Telegram and Discord; Slack gets them as the bot, with the bot token, but not through its
		incoming webhook."""
		self.env(slackBotToken='xoxb-test')

		kinds = (transports.TelegramBot, transports.SlackBot, transports.SlackWebhook, transports.DiscordWebhook)
		self.assertEqual([kind(None).takes_charts for kind in kinds], [True, True, False, True])
		self.env(slackBotToken=False)
		self.assertFalse(transports.SlackBot(None).takes_charts)

	def test_scheduled_reports_go_to_slack_as_the_bot_with_slackChannelID(self):
		"""With slackChannelID and the bot token, scheduled reports reach Slack as the bot in place of the incoming
		webhook, which it does not need; without the token, the webhook carries them."""
		hook = 'https://hooks.slack.com/services/x'
		telegram = config.env.webhooks['telegram']
		self.env(webhooks={'telegram': telegram, 'slack': hook}, telegramChatID='1', slackChannelID='C9',
			slackBotToken='xoxb-test')
		self.assertEqual(list(map(repr, delivery.default_chats())), ['<TelegramBot 1>', '<SlackBot C9>'])
		self.env(slackBotToken='')
		self.assertEqual(list(map(repr, delivery.default_chats())), ['<TelegramBot 1>', f'<SlackWebhook {hook}>'])
		self.env(webhooks={'telegram': telegram}, slackBotToken='xoxb-test')
		self.assertEqual(list(map(repr, delivery.default_chats())), ['<TelegramBot 1>', '<SlackBot C9>'])
		self.env(webhooks={}, telegramChatID='') # the bot alone
		self.assertEqual(list(map(repr, delivery.default_chats())), ['<SlackBot C9>'])

	def test_slack_replies_upload_their_charts(self):
		"""A Slack reply uploads its chart in three steps (bot token), the report as its message, with no text copy."""
		self.env(slackBotToken='xoxb-test')

		for cmd, heading in (('.beta', '*Beta over 1.5'), ('.price', '*≥ 5% at close'), ('.compare T1 T2', '*')):
			with self.subTest(cmd=cmd):
				calls = self.slack_answers(*self.upload_steps())
				self.sent.clear(); self.errors.clear()
				worker.process_request(inbound.Message('slack', 'C1', '<@U1>', cmd, BOT, 'U'))
				self.assertEqual(self.errors, [])
				self.assertEqual([url for url, _ in calls],
					['https://slack.com/api/files.getUploadURLExternal', self.UPLOAD_URL,
															 'https://slack.com/api/files.completeUploadExternal'])
				(_, ticket), (_, upload), (_, share) = calls
				self.assertEqual(ticket['headers'], {'Authorization': 'Bearer xoxb-test'})
				self.assertTrue(upload['data'].startswith(b'\x89PNG')) # the chart's bytes, as the body
				self.assertEqual((ticket['data']['filename'], ticket['data']['length']),
					('chart.png', len(upload['data'])))
				self.assertEqual((share['data']['channel_id'], json.loads(share['data']['files'])),
					('C1', [{'id': 'F1'}]))
				self.assertTrue(share['data']['initial_comment'].startswith(heading),
					share['data']['initial_comment'][:80]) # the report
				# not sent again as text
				self.assertNotIn(share['data']['initial_comment'].split('\n'), [payload for _, payload in self.sent])

	def test_a_slack_upload_that_fails_goes_out_as_text(self):
		"""A Slack upload failing at any step goes as text, but not on a last-step timeout, when it may have arrived."""
		self.env(slackBotToken='xoxb-test')
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))

		good = self.upload_steps()
		slow = transports.requests.exceptions.ReadTimeout('slow')
		text = [('text', ['*Heading*', 'line 2'])]
		for outcomes, expect in (([Resp({'ok': False, 'error': 'missing_scope'})], text),
			([ConnectionError('down')], text),
								 ([good[0], Resp(None, status=500, text='nope')], text),
								 ([good[0], good[1], Resp({'ok': False, 'error': 'not_in_channel'})], text),
								 ([good[0], good[1], slow], []), # it may have been shared after all
								 (good, [])):
			with self.subTest(outcomes=outcomes):
				self.slack_answers(*outcomes)
				self.sent.clear()
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					delivery.deliver(transports.SlackBot('C1'), delivery.Report(['*Heading*', 'line 2'], CHART))
				self.assertEqual(self.sent, expect)

	def test_scheduled_reports_to_slack_carry_charts_only_as_the_bot(self):
		"""Scheduled reports reach Slack's incoming webhook as text; the Slack bot (slackChannelID) and Telegram get
		their charts."""
		self.env(slackBotToken='xoxb-test')

		# an incoming webhook cannot upload
		self.env(webhooks={**config.env.webhooks, 'slack': 'https://hooks.slack.com/services/x'})
		sent = []
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, buttons=None:
			sent.append((dest.name, 'chart')) or {'ok': True})
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None:
			sent.append((dest.name, 'text')) or [])
		for report in (price.run, lambda: performance.run(past_days=7), shorts.run):
			with self.subTest(report=report):
				sent.clear()
				report()
				self.assertEqual(sorted(set(sent)), [('slack', 'text'), ('telegram', 'chart')])
				self.env(slackChannelID='C9') # as the bot, the report's chart goes too
				sent.clear()
				report()
				self.assertEqual(sorted(set(sent)), [('slack', 'chart'), ('telegram', 'chart')])
				self.env(slackChannelID='')

	def test_slack_without_a_bot_token_gets_text_and_no_chart_is_drawn(self):
		"""Without the bot token, Slack replies are text and no chart is drawn for them."""
		self.env(slackBotToken=False)

		def refuse(*a, **k):
			"""Fail: no chart should be drawn."""
			raise AssertionError('a chart was drawn for Slack')
		self.patch(render, 'draw', refuse) # every chart is drawn there
		self.env(webhooks={**config.env.webhooks, 'slack': 'https://hooks.slack.com/services/x'})
		for cmd in ('.beta', '.pie Rob', '.buy', '.sell', '.peg', '.price', '.price top', '.price T1 7d',
				'.performance 7d', '.shorts', '.history T1', '.compare T1 T2'):
			with self.subTest(cmd=cmd):
				self.sent.clear(); self.errors.clear()
				worker.process_request(inbound.Message('slack', 'C1', '<@U1>', cmd, BOT, 'U'))
				self.assertEqual(self.errors, [])
				self.assertTrue(self.sent)
				self.assertEqual({kind for kind, *_ in self.sent}, {'text'})

	def test_the_graph_preference_off_sends_no_chart_anywhere(self):
		"""graph=False means no charts, as the README says; it used to hold back only the price-line charts."""
		self.prefs(graph=False)

		self.env(slackBotToken='xoxb-test')

		posts = []
		self.patch(transports.net, 'post', lambda url, **k: posts.append(url) or Resp({'ok': True, 'result': True}))
		for service, chat in (('telegram', '55'), ('slack', 'C1')):
			for cmd in ('.price', '.price top', '.performance 7d', '.shorts', '.buy', '.peg', '.beta', '.compare T1 T2',
					'.pie Rob'):
				with self.subTest(service=service, cmd=cmd):
					self.sent.clear(); self.errors.clear()
					worker.process_request(inbound.Message(service, chat, '@u', cmd, BOT, 'U'))
					self.assertEqual(self.errors, [])
					self.assertEqual({kind for kind, *_ in self.sent}, {'text'})
		self.assertEqual([url for url in posts if 'sendPhoto' in url or 'files.' in url], [])

	def test_a_chart_telegram_refuses_goes_out_as_text(self):
		"""A chart Telegram refuses or that fails goes as text, but not after a timeout, when it may have arrived."""
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))
		def post(outcome):
			"""A net.post that answers with outcome, or raises it."""
			def fake(url, **kwargs):
				"""The outcome, or raise it."""
				if isinstance(outcome, Exception):
					raise outcome
				return outcome
			return fake
		text = [('text', ['Heading', 'line 2'])]
		for outcome, expect in ((Resp({'ok': False, 'error_code': 400,
			'description': "Bad Request: can't parse entities"}, status=400), text),
								(Resp(None, status=502), text), (ConnectionError('down'), text),
								(transports.requests.exceptions.ReadTimeout('slow'), []), # it may be there
								(Resp({'ok': True, 'result': {'message_id': 1}}), [])):
			with self.subTest(outcome=outcome):
				self.sent.clear()
				self.patch(transports.net, 'post', post(outcome))
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					delivery.deliver(transports.TelegramBot('5'), delivery.Report(['Heading', 'line 2'], CHART, [[]]))
				self.assertEqual(self.sent, expect)


class DiscordWebhook(FinbotCase):
	"""Discord's own webhook endpoint (the Slack-like one takes no flags): no previews, no pings, charts attached."""
	URL = 'https://discord.com/api/webhooks/1/abc'

	def setUp(self):
		"""Discord as the only destination, sent through the real path, its posts recorded."""
		super().setUp()
		self.env(webhooks={'discord': self.URL})
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.posts = []
		self.patch(transports.net, 'post', lambda url, **kwargs: self.posts.append((url, kwargs)) or Resp({'id': '1'}))

	def test_text_goes_to_the_native_endpoint_without_previews_or_pings(self):
		"""Text goes to the native endpoint with ?wait=true, without previews or mentions."""
		transports.DiscordWebhook(self.URL).post_text('hello @everyone')
		url, kwargs = self.posts[0]
		self.assertEqual(url, self.URL + '?wait=true') # without wait Discord answers 204, which counted as a failure
		self.assertEqual(kwargs['json'], {'content': 'hello @everyone', 'flags': 4, 'allowed_mentions': {'parse': []}})

	def test_a_scheduled_report_carries_its_chart(self):
		"""A scheduled Discord report has its chart attached and the report as its message, within 2,000 characters."""
		price.run()
		(url, kwargs), = self.posts
		self.assertEqual(url, self.URL + '?wait=true')
		payload = json.loads(kwargs['data']['payload_json'])
		self.assertEqual((payload['flags'], payload['allowed_mentions'], payload['attachments'][0]['filename']),
			(4, {'parse': []}, 'chart.png'))
		self.assertTrue(payload['content'].startswith('**≥ 5% at close'), payload['content'][:60])
		self.assertLessEqual(len(payload['content']), 2000)
		name, image, kind = kwargs['files']['files[0]']
		self.assertEqual((name, kind), ('chart.png', 'image/png'))
		self.assertTrue(image.read().startswith(b'\x89PNG'))

	def test_a_long_report_is_split_by_size(self):
		"""A long report is split into messages of at most 2,000 characters."""
		line = 'x' * 150
		transports.DiscordWebhook(self.URL).text([line] * 30)
		sizes = [len(kwargs['json']['content']) for _, kwargs in self.posts]
		self.assertGreater(len(sizes), 2)
		self.assertTrue(all(size <= 2000 for size in sizes), sizes) # 20 lines a chunk used to make 3,019 characters

	def test_links_are_masked_links(self):
		"""Links are masked links, brackets and parentheses escaped."""
		self.assertEqual(DISCORD.link('https://x.example/a(b)', 'T[1]'), '[T\\[1\\]](<https://x.example/a%28b%29>)')


class SlackSending(FinbotCase):
	"""Slack replies go through chat.postMessage with the bot token; scheduled reports through the incoming webhook."""

	def setUp(self):
		"""The real send path, its posts recorded."""
		super().setUp()
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.posts = []
		self.patch(transports.net, 'post', lambda url, **kwargs: self.posts.append((url, kwargs)) or Resp({'ok': True}))

	def test_link_previews_are_turned_off_in_the_body(self):
		"""Link previews are turned off in the body, where Slack reads them, for replies and for the webhook."""
		self.env(slackBotToken='xoxb-test')

		transports.SlackBot('C1').post_text('hi')
		transports.SlackWebhook('https://hooks.slack.com/services/T/B/x').post_text('hi')
		(_, reply), (_, hook) = self.posts
		self.assertEqual((reply['data']['unfurl_links'], reply['data']['unfurl_media']), ('false', 'false'))
		self.assertEqual((hook['json']['unfurl_links'], hook['json']['unfurl_media']), (False, False))
		for kwargs in (reply, hook): # they used to go in the headers, where Slack does not look
			self.assertNotIn('unfurl_links', kwargs['headers'])

	def test_a_reply_slack_refuses_is_logged_as_failed(self):
		"""Slack refuses with HTTP 200 and ok false (the bot is not in the channel, say): a failure, logged as one."""
		self.env(slackBotToken='xoxb-test')
		self.patch(transports.net, 'post', lambda url, **kwargs: Resp({'ok': False, 'error': 'not_in_channel'}))
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertIsNone(transports.SlackBot('C1').post_text('hi'))
		self.assertIn('Slack chat.postMessage to C1 failed: Slack chat.postMessage: not_in_channel', err.getvalue())
		self.assertNotIn('OK', err.getvalue())

	def test_a_reply_without_a_bot_token_is_logged_not_sent(self):
		"""A Slack reply without the bot token is logged, once each, and not sent."""
		self.env(slackBotToken=False)

		err = io.StringIO()
		with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
			for cmd in ('.help', '.price', '.compare T1 T2'):
				worker.process_request(inbound.Message('slack', 'C1', '<@U1>', cmd, BOT, 'U'))
		self.assertEqual((self.posts, self.errors), ([], []))
		refusal = 'ERROR slack: a reply to channel C1 needs slackBotToken in finbot.env; not sent'
		self.assertEqual(err.getvalue().count(refusal), 3)

	def test_a_command_at_work_shows_an_hourglass_on_its_message(self):
		"""While a command works, ⏳ is on the message it answers (Slack has no typing notice for bots); it comes off
		once the answer is out, so the answer does not wait for it. Only with that message and the bot token."""
		self.env(slackBotToken='xoxb-test')
		self.patch(transports.Transport, 'TYPING', (0, 7, 10))
		added = threading.Event()
		def post(url, **kwargs):
			"""Record the post; note when ⏳ is on."""
			self.posts.append((url, kwargs))
			if url.endswith('/reactions.add'):
				added.set()
			return Resp({'ok': True})
		self.patch(transports.net, 'post', post)
		help_text = about.prepare_help
		self.patch(about, 'prepare_help', lambda *a: (added.wait(5), help_text(*a))[1]) # a command slow enough for ⏳
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.help', BOT, 'U', '1.2'))
		self.assertEqual([url.rsplit('/', 1)[-1] for url, _ in self.posts],
			['reactions.add', 'chat.postMessage', 'reactions.remove'])
		reaction = {'channel': 'C1', 'timestamp': '1.2', 'name': 'hourglass_flowing_sand'}
		self.assertEqual((self.posts[0][1]['data'], self.posts[2][1]['data']), (reaction, reaction))
		self.assertFalse(transports.SlackBot('C1').shows_typing) # no message to put it on
		self.env(slackBotToken='')
		self.assertFalse(transports.SlackBot('C1', '1.2').shows_typing)

	def test_an_hourglass_slack_refuses_is_tried_once(self):
		"""⏳ that Slack refuses (a missing scope) is logged and not tried again, and nothing is taken off."""
		self.env(slackBotToken='xoxb-test')
		refuse = Resp({'ok': False, 'error': 'missing_scope'})
		self.patch(transports.net, 'post', lambda url, **kwargs: self.posts.append((url, kwargs)) or refuse)
		chat = transports.SlackBot('C1', '1.2')
		with contextlib.redirect_stderr(io.StringIO()) as err:
			chat.typing()
			chat.typing()
			chat.typing_done()
		self.assertEqual([url for url, _ in self.posts], ['https://slack.com/api/reactions.add'])
		self.assertIn('Slack reactions.add failed: Slack reactions.add: missing_scope', err.getvalue())

	def test_the_slack_api_says_what_is_missing(self):
		"""slack_api without the bot token says so (it used to be a TypeError)."""
		self.env(slackBotToken=False)

		with self.assertRaisesRegex(RuntimeError,
				'Slack files.getUploadURLExternal: needs slackBotToken in finbot.env'):
			transports.slack_api('files.getUploadURLExternal', filename='chart.png', length=1) # it was a TypeError
		self.assertEqual(self.posts, [])


class SlackButtons(FinbotCase):
	"""A chart's period buttons on Slack: a Block Kit message (the report, the chart uploaded into no channel, the
	buttons) that a press redraws in place, where the presses reach finbot (the bot token and slackOutgoingWebhook)."""
	UPLOAD_URL = 'https://files.slack.com/upload/v1/abc'

	def setUp(self):
		"""The real send path, its posts recorded and answered as Slack would; no waiting."""
		super().setUp()
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.env(slackBotToken='xoxb-test', slackOutgoingWebhook='https://example.com/slack')
		self.posts, self.refusals, self.waits = [], {}, []
		self.patch(transports.time, 'sleep', self.waits.append)
		def post(url, **kwargs):
			"""Record the post and answer it: a refusal set for the method, while there is one left, else success."""
			self.posts.append((url, kwargs))
			method = url.rsplit('/', 1)[-1]
			if self.refusals.get(method):
				return Resp({'ok': False, 'error': self.refusals[method].pop(0)})
			if url == self.UPLOAD_URL:
				return Resp(None, text='OK - 3')
			return Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': 'F1', 'files': [{'id': 'F1'}],
				'ts': '1.5'})
		self.patch(transports.net, 'post', post)

	def calls(self):
		"""The methods posted, in order (the upload as 'upload')."""
		return ['upload' if url == self.UPLOAD_URL else url.rsplit('/', 1)[-1] for url, _ in self.posts]

	def blocks(self, method):
		"""The blocks of the last call of this method."""
		return json.loads([kwargs for url, kwargs in self.posts if url.endswith('/' + method)][-1]['data']['blocks'])

	def test_a_chart_reply_carries_its_period_buttons(self):
		"""A chart reply is a Block Kit message: the report, the chart (uploaded into no channel, shown by its id) and
		the period buttons, the one shown marked; nothing goes as text."""
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.errors, [])
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.postMessage'])
		self.assertNotIn('channel_id', self.posts[2][1]['data']) # in no channel: the message shows it
		blocks = self.blocks('chat.postMessage')
		self.assertEqual([block['type'] for block in blocks], ['section', 'image', 'actions'])
		self.assertTrue(blocks[0]['text']['text'].startswith('*≥ 5% at close'))
		self.assertEqual(blocks[1]['slack_file'], {'id': 'F1'})
		buttons_shown = blocks[2]['elements']
		self.assertEqual([button['text']['text'] for button in buttons_shown], ['1D', '7D', '1M', '1Y', 'Max'])
		self.assertEqual([button.get('style') for button in buttons_shown], ['primary'] + [None] * 4)
		self.assertEqual(buttons_shown[1]['value'], 'c|l|w|5,0')

	def test_a_press_redraws_the_chart_in_place(self):
		"""A press uploads the chart for that period (a file cannot be replaced) and puts it in the message with
		chat.update, the period pressed now marked; Telegram is not asked to answer the press."""
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|w|5,0'))
		self.assertEqual(self.errors, [])
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.update'])
		update = self.posts[-1][1]['data']
		self.assertEqual((update['channel'], update['ts']), ('C1', '1.5'))
		blocks = self.blocks('chat.update')
		self.assertEqual(blocks[1]['slack_file'], {'id': 'F1'})
		self.assertEqual([button.get('style') for button in blocks[2]['elements']], [None, 'primary'] + [None] * 3)

	def test_a_press_deletes_the_chart_it_replaced(self):
		"""Each press uploads its period's chart and, once the message shows it, deletes the file shown before: no
		chart is reused, so the bot's files do not pile up. The file a press shows is never deleted."""
		uploads = iter(f'F{n}' for n in range(1, 10))
		record = transports.net.post
		def post(url, **kwargs):
			"""Answer as Slack does, with a new file id for each upload."""
			answer = record(url, **kwargs)
			if url.endswith('/files.getUploadURLExternal'):
				return Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': next(uploads)})
			return answer
		self.patch(transports.net, 'post', post)
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U')) # F1, in message 1.5
		for _ in range(2):
			worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|w|5,0')) # F2, then F3
		deleted = [kwargs['data']['file'] for url, kwargs in self.posts if url.endswith('/files.delete')]
		self.assertEqual((deleted, self.errors), (['F1', 'F2'], []))
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F3'})

	def test_a_chart_not_ready_to_show_is_shown_a_moment_later(self):
		"""Slack refusing the blocks of a chart just uploaded (invalid_blocks) is asked again after a wait."""
		self.refusals['chat.postMessage'] = ['invalid_blocks']
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual((self.calls()[-2:], self.waits), (['chat.postMessage', 'chat.postMessage'], [1]))
		self.assertEqual((self.sent, self.errors), ([], []))

	def test_buttons_slack_will_not_show_leave_a_plain_chart(self):
		"""When Slack will not show the chart with its buttons, the chart is uploaded into the channel without them."""
		self.refusals['chat.postMessage'] = ['invalid_blocks'] * 4
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.calls()[-3:], ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal'])
		self.assertEqual(self.posts[-1][1]['data']['channel_id'], 'C1')
		self.assertEqual((self.waits, self.sent, self.errors), ([1, 2, 4], [], []))

	def test_without_slackOutgoingWebhook_a_chart_has_no_buttons(self):
		"""Without slackOutgoingWebhook, no press could reach finbot, so a chart goes without buttons."""
		self.env(slackOutgoingWebhook='')
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal'])
		self.assertEqual(self.posts[-1][1]['data']['channel_id'], 'C1')

	def test_a_long_report_takes_several_sections(self):
		"""A report longer than a section takes holds is split into sections, and an empty one takes none."""
		caption = '\n'.join('x' * 99 for _ in range(70)) # 6,999 characters
		blocks = transports.chart_blocks(caption, [], 'F1')
		self.assertEqual([block['type'] for block in blocks], ['section'] * 3 + ['image'])
		self.assertTrue(all(len(block['text']['text']) <= 3000 for block in blocks[:3]))
		self.assertEqual([block['type'] for block in transports.chart_blocks('', [], 'F1')], ['image'])

	def test_a_chart_message_that_times_out_is_not_posted_again(self):
		"""A chart with its buttons whose chat.postMessage times out may have arrived: no plain copy follows."""
		record = transports.net.post
		def post(url, **kwargs):
			"""Time out on chat.postMessage, as a slow Slack does."""
			if url.endswith('/chat.postMessage'):
				self.posts.append((url, kwargs))
				raise transports.requests.exceptions.ReadTimeout('slow')
			return record(url, **kwargs)
		self.patch(transports.net, 'post', post)
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.postMessage'])
		self.assertEqual(self.errors, [])


if __name__ == '__main__':
	unittest.main()
