"""Posting to the networks against their answers and failures: Telegram, Slack (text, charts, Block Kit
buttons) and Discord."""
import contextlib, html.parser, io, json, threading, unittest
from unittest import mock
import requests
from tests.common import *
from lib import jobs


class TelegramSending(FinbotCase):
	"""A message posted to Telegram against failing endpoints: the real send path, not the base fixture's recorder."""

	def post(self, outcome):
		"""Post 'hi' to a Telegram chat, the request answering with outcome (or raising it)."""
		def fake(url, **kwargs):
			"""The outcome, or raise it."""
			if isinstance(outcome, Exception):
				raise outcome
			return outcome
		self.patch(net, 'post', fake)
		return telegram_common.TelegramBot('5').post_text('hi')

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

	def test_text_goes_silent_and_without_link_previews(self):
		"""A message goes silent and without link previews, and so does an edit: link_preview_options, which replaced
		disable_web_page_preview in Bot API 7.0."""
		sent = []
		self.patch(net, 'post', lambda url, **kwargs: sent.append((url.rsplit('/', 1)[1], kwargs['json'])) or
			Resp({'ok': True, 'result': {'message_id': 8}}))
		chat = telegram_common.TelegramBot('5')
		chat.post_text('hi')
		chat.edit_text('8', 'edited')
		off = {'is_disabled': True}
		self.assertEqual(sent, [('sendMessage', {'chat_id': '5', 'text': 'hi', 'parse_mode': 'HTML',
			'link_preview_options': off, 'disable_notification': True}), ('editMessageText', {'chat_id': '5',
			'message_id': '8', 'text': 'edited', 'parse_mode': 'HTML', 'link_preview_options': off})])

	def test_buttons_alone_are_changed_with_no_upload(self):
		"""editMessageReplyMarkup changes a message's buttons alone: True once they show, as when they were so already
		(Telegram's "message is not modified"), else False, logged. Slack has no such edit: its message is edited
		whole."""
		sent = []
		self.patch(net, 'post', lambda url, **kwargs: sent.append((url.rsplit('/', 1)[1], kwargs['json'])) or
			Resp({'ok': True, 'result': True}))
		chat = telegram_common.TelegramBot('5')
		self.assertTrue(chat.edit_buttons('8', [[buttons.Button('7D', 'k|c|0|w|0|0|m0|ab12')]]))
		self.assertEqual(sent, [('editMessageReplyMarkup', {'chat_id': '5', 'message_id': '8', 'reply_markup':
			{'inline_keyboard': [[{'text': '7D', 'callback_data': 'k|c|0|w|0|0|m0|ab12'}]]}})])
		for why, shown in (('message is not modified', True), ('message to edit not found', False)):
			with self.subTest(why=why), contextlib.redirect_stderr(io.StringIO()):
				refusal = Resp({'ok': False, 'description': f'Bad Request: {why}'}, 400)
				self.patch(net, 'post', lambda url, **kwargs: refusal)
				self.assertEqual(chat.edit_buttons('8', []), shown)
		self.assertFalse(slack_common.SlackBot('C1').edit_buttons('1.2', []))

	def test_an_edit_that_changes_nothing_is_no_failure(self):
		"""Telegram refuses an edit that changes nothing ("message is not modified": a button pressed again), which each
		edit logs in a few words, never as a failure."""
		refusal = Resp({'ok': False, 'description': 'Bad Request: message is not modified: specified new message content'
			' and reply markup are exactly the same as a current content and reply markup of the message'}, 400)
		self.patch(net, 'post', lambda url, **kwargs: refusal)
		chat = telegram_common.TelegramBot('5')
		for name, edit in (('text', lambda: chat.edit_text('8', 'text')), ('buttons', lambda: chat.edit_buttons('8', [])),
				('chart', lambda: chat.edit_chart('8', io.BytesIO(b'png'), 'caption'))):
			with self.subTest(edit=name), contextlib.redirect_stderr(io.StringIO()) as log:
				edit()
				self.assertEqual(log.getvalue(), 'Telegram duplicate button press ignored\n')

	def test_typing_is_sent_again_before_it_lapses(self):
		""""typing…" shows for 5 seconds at most (sendChatAction), so it is sent again sooner, and shows the whole time
		a command works, for a minute at least."""
		delay, every, times = telegram_common.TelegramBot.TYPING
		self.assertLess(every, 5)
		self.assertGreaterEqual(delay + every * times, 60)

	def test_a_chart_goes_without_a_parameter_sendphoto_does_not_take(self):
		"""sendPhoto is sent the chat, caption and markup, and no link-preview flag: a photo has no preview."""
		sent = []
		self.patch(net, 'post', lambda url, **kwargs: sent.append((url, kwargs)) or
			Resp({'ok': True, 'result': {'message_id': 8}}))
		self.assertEqual(telegram_common.TelegramBot('5').post_chart(io.BytesIO(b'png'), 'caption'), {'message_id': 8})
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
		for kind in (telegram_common.TelegramBot, slack_common.SlackBot, discord_common.DiscordBot):
			self.patch(kind, 'post_text', lambda dest, text, buttons=None: sent.append((dest.name, text)))
		self.env(slackBotToken='xoxb-1', discordBotToken='x')

		error = RuntimeError("404 for ZZ at https://x/?a=1&crumb=abc; '<' not supported between <urllib3.connection>")
		with contextlib.redirect_stderr(io.StringIO()):
			for key in ('telegram:5', 'slack:C9', 'discord:77'):
				REAL_REPORT_ERROR(error, delivery.chat(key), context='.compare <b>')
			REAL_REPORT_ERROR(error, telegram_common.TelegramBot('55'), context='.compare')
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
			REAL_REPORT_ERROR(ValueError('boom'), telegram_common.TelegramBot('5'))
			REAL_REPORT_ERROR(ValueError('boom'))


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
		self.patch(net, 'post', post)
		return calls

	def upload_steps(self):
		"""Slack's answers to the three upload steps, each a success."""
		return [Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': 'F1'}), Resp(None, text='OK - 3'),
			Resp({'ok': True, 'files': [{'id': 'F1'}]})]

	def test_every_bot_takes_charts_and_buttons(self):
		"""Every network's bot takes charts and buttons, whichever way its updates arrive: their presses reach finbot,
		and no setting holds them back."""
		self.env(slackBotToken='', slackAppToken='', slackOutgoingWebhook='', telegramOutgoingWebhook='')
		for kind in (telegram_common.TelegramBot, slack_common.SlackBot, discord_common.DiscordBot):
			with self.subTest(kind=kind.__name__):
				self.assertTrue(kind('1').takes_charts and kind('1').takes_buttons)

	def test_an_error_that_belongs_to_no_chat_goes_only_to_the_log(self):
		"""There are no home chats: an error that belongs to no chat (a system job's, a webhook request's) is logged,
		with nothing posted and no word of a failure to post it."""
		text = mock.Mock()
		self.patch(transports.Transport, 'text', text)
		err = io.StringIO()
		with contextlib.redirect_stderr(err):
			REAL_REPORT_ERROR(ValueError('boom'), context='sharesight_warm')
		self.assertIn('⚠️ sharesight_warm: ValueError: boom', err.getvalue())
		self.assertNotIn('Failed', err.getvalue())
		text.assert_not_called()

	def test_slack_replies_upload_their_charts(self):
		"""A Slack reply whose chart has no buttons uploads it in three steps (bot token), the report as its message,
		with no text copy (a chart with buttons goes in a Block Kit message: SlackButtons)."""
		self.env(slackBotToken='xoxb-test')

		for cmd, heading in (('.beta', '*Beta over 1.5'), ('.pie Rob', '*')):
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
		"""A Slack upload failing at any step, then again with its heading alone, goes as text, but not on a last-step
		timeout, when it may have arrived."""
		self.env(slackBotToken='xoxb-test')
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))

		good = self.upload_steps()
		slow = requests.exceptions.ReadTimeout('slow')
		text = [('text', ['*Heading*', 'line 2'])]
		for outcomes, expect in (([Resp({'ok': False, 'error': 'missing_scope'})], text),
			([ConnectionError('down')], text),
								 ([good[0], Resp(None, status=500, text='nope')], text),
								 ([good[0], good[1], Resp({'ok': False, 'error': 'not_in_channel'})], text),
								 ([good[0], good[1], slow], []), # it may have been shared after all
								 (good, [])):
			with self.subTest(outcomes=outcomes):
				calls = self.slack_answers(*outcomes, *outcomes) # a refused chart is tried again, failing the same way
				self.sent.clear()
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					delivery.deliver(slack_common.SlackBot('C1'), delivery.Report(['*Heading*', 'line 2'], CHART))
				self.assertEqual(self.sent, expect)
				self.assertEqual(len(calls), len(outcomes) * (2 if expect else 1))

	def test_scheduled_reports_carry_their_charts_on_every_network(self):
		"""A scheduled report's chart goes to the job's chat on every network, as its bot."""
		self.env(slackBotToken='xoxb-test', discordBotToken='x')
		sent = []
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, buttons=None:
			sent.append((dest.name, 'chart')) or {'ok': True})
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None:
			sent.append((dest.name, 'text')) or [])
		for report in (price.run, lambda dest: performance.run(dest, past_days=7), shorts.run):
			with self.subTest(report=report):
				sent.clear()
				for key in ('telegram:1', 'slack:C9', 'discord:77'):
					report(scheduled(key))
				self.assertEqual(sorted(set(sent)), [('discord', 'chart'), ('slack', 'chart'), ('telegram', 'chart')])

	def test_the_graph_setting_off_sends_no_chart_anywhere(self):
		"""graph=False means no charts, as doc/configuration.md says; it held back only the price-line charts."""
		self.settings(graph=False)

		self.env(slackBotToken='xoxb-test')

		posts = []
		self.patch(net, 'post', lambda url, **k: posts.append(url) or Resp({'ok': True, 'result': True}))
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
								(requests.exceptions.ReadTimeout('slow'), []), # it may be there
								(Resp({'ok': True, 'result': {'message_id': 1}}), [])):
			with self.subTest(outcome=outcome):
				self.sent.clear()
				self.patch(net, 'post', post(outcome))
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					report = delivery.Report(['Heading', 'line 2'], CHART, [[]])
					delivery.deliver(telegram_common.TelegramBot('5'), report)
				self.assertEqual(self.sent, expect)

	def telegram(self, refused):
		"""net.post as Telegram, refusing each caption refused(caption) is true for: the captions sent, in turn."""
		captions = []
		def post(url, data, **kwargs):
			"""Telegram's answer to sendPhoto: the message, or Bad Request."""
			captions.append(data['caption'])
			if refused(data['caption']):
				return Resp({'ok': False, 'error_code': 400, 'description': 'Bad Request: caption refused'}, status=400)
			return Resp({'ok': True, 'result': {'message_id': len(captions)}})
		self.patch(net, 'post', post)
		return captions

	def test_a_caption_fits_as_telegram_counts_it(self):
		"""A caption is cut to Telegram's 1,024 characters as it counts them: the text its HTML shows (no tags, an
		entity one character), in UTF-16 code units, so each 🔼 counts 2. Counted by code points, a list of thirty
		moves passed for 1,012 and was refused, and the chart went as text."""
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))
		class Shown(html.parser.HTMLParser):
			"""The text an HTML caption shows, as Telegram parses it."""
			def handle_data(self, data):
				"""Keep the text between the tags, its entities read."""
				self.text += data
		def length(caption):
			"""A caption's length as Telegram counts it: its text in UTF-16 code units."""
			shown = Shown()
			shown.text = ''
			shown.feed(caption)
			return sum(2 if ord(char) > 0xFFFF else 1 for char in shown.text)
		self.assertEqual(length('<b>🔼 S&amp;P</b>'), TELEGRAM.visible('<b>🔼 S&amp;P</b>'))
		self.assertEqual(TELEGRAM.visible('<b>🔼 S&amp;P</b> <a href="https://x.co/?a=1&amp;b=2">T1</a>'), 9)
		lines = ['<b>Price alerts 3% (ASX, NASDAQ)</b>'] + [
			f'{"🔼🔻"[i % 2]} Company Number {i:02d} Holdings Lt (<a href="https://finance.yahoo.com/quote/T{i}">T{i}'
			f'</a>) {"+-"[i % 2]}{i % 9 + 3}%' for i in range(40)]
		captions = self.telegram(lambda caption: length(caption) > 1024)
		with contextlib.redirect_stderr(io.StringIO()):
			delivery.deliver(telegram_common.TelegramBot('5'), delivery.Report(lines, CHART))
		self.assertEqual(len(captions), 1) # accepted at once: nothing sent again, nothing as text
		self.assertEqual(self.sent, [])
		self.assertLessEqual(length(captions[0]), 1024)
		self.assertGreater(length(captions[0]), 990) # as many whole lines as fit
		self.assertTrue(captions[0].endswith(' more in the chart'), captions[0][-40:])

	def test_a_chart_refused_with_its_caption_goes_again_with_its_heading(self):
		"""A chart refused with its report as the caption goes again with the heading alone and its buttons, the
		report following as text; refused again, or where the heading was the whole caption, the report goes as text."""
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))
		markup = [[buttons.Button('7D', 'l|3|0|w')]]
		for refused, captions, sent in ((lambda caption: '\n' in caption, ['<b>Heading</b>\nline 2', '<b>Heading</b>'],
				[('text', ['<b>Heading</b>', 'line 2'])]), (lambda caption: True, ['<b>Heading</b>\nline 2',
				'<b>Heading</b>'], [('text', ['<b>Heading</b>', 'line 2'])])):
			with self.subTest(captions=captions):
				self.sent.clear()
				asked = self.telegram(refused)
				with contextlib.redirect_stderr(io.StringIO()):
					delivery.deliver(telegram_common.TelegramBot('5'),
						delivery.Report(['<b>Heading</b>', 'line 2'], CHART, markup))
				self.assertEqual((asked, self.sent), (captions, sent))
		asked = self.telegram(lambda caption: True)
		self.sent.clear()
		with contextlib.redirect_stderr(io.StringIO()):
			delivery.deliver(telegram_common.TelegramBot('5'), delivery.Report(['<b>Heading</b>'], CHART))
		self.assertEqual((asked, self.sent), (['<b>Heading</b>'], [('text', ['<b>Heading</b>'])]))


class DiscordSending(FinbotCase):
	"""A Discord job's channel, as the bot: a scheduled report's chart attached, within Discord's 2,000 characters."""

	def setUp(self):
		"""Discord as the only destination, sent through the real path, its calls recorded."""
		super().setUp()
		self.env(discordBotToken='x')
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.calls = []
		self.patch(net, 'request', lambda method, url, **kwargs: self.calls.append((url, kwargs))
			or Resp({'id': '1'}))

	def test_a_scheduled_report_carries_its_chart(self):
		"""A scheduled Discord report has its chart attached and the report as its message, within 2,000 characters,
		without previews or pings."""
		with contextlib.redirect_stderr(io.StringIO()):
			price.run(scheduled('discord:77'))
		(url, kwargs), = self.calls
		self.assertEqual(url, 'https://discord.com/api/v10/channels/77/messages')
		payload = json.loads(kwargs['data']['payload_json'])
		self.assertEqual((payload['flags'], payload['allowed_mentions'], payload['attachments'][0]['filename']),
			(4, {'parse': []}, 'chart.png'))
		self.assertTrue(payload['content'].startswith('**≥ 5% at close'), payload['content'][:60])
		self.assertLessEqual(len(payload['content']), 2000)
		name, image, kind = kwargs['files']['files[0]']
		self.assertEqual((name, kind), ('chart.png', 'image/png'))
		self.assertTrue(image.startswith(b'\x89PNG'))

	def test_a_long_report_is_split_by_size(self):
		"""A long report is split into messages of at most 2,000 characters."""
		line = 'x' * 150
		with contextlib.redirect_stderr(io.StringIO()):
			discord_common.DiscordBot('77').text([line] * 30)
		sizes = [len(kwargs['json']['content']) for _, kwargs in self.calls]
		self.assertGreater(len(sizes), 2)
		self.assertTrue(all(size <= 2000 for size in sizes), sizes) # 20 lines a chunk used to make 3,019 characters

	def test_links_are_masked_links(self):
		"""Links are masked links, brackets and parentheses escaped."""
		self.assertEqual(DISCORD.link('https://x.example/a(b)', 'T[1]'), '[T\\[1\\]](<https://x.example/a%28b%29>)')


class SlackSending(FinbotCase):
	"""Slack's messages go through chat.postMessage with the bot token, replies and scheduled reports alike."""

	def setUp(self):
		"""The real send path, its posts recorded."""
		super().setUp()
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.posts = []
		self.patch(net, 'post', lambda url, **kwargs: self.posts.append((url, kwargs)) or Resp({'ok': True}))

	def test_link_previews_are_turned_off_in_the_body(self):
		"""Link previews are turned off in the body, where Slack reads them."""
		self.env(slackBotToken='xoxb-test')

		with contextlib.redirect_stderr(io.StringIO()):
			slack_common.SlackBot('C1').post_text('hi')
		(_, reply), = self.posts
		self.assertEqual((reply['data']['unfurl_links'], reply['data']['unfurl_media']), ('false', 'false'))
		self.assertNotIn('unfurl_links', reply['headers']) # they used to go in the headers, where Slack does not look

	def test_a_reply_slack_refuses_is_logged_as_failed(self):
		"""Slack refuses with HTTP 200 and ok false (the bot is not in the channel, say): a failure, logged as one."""
		self.env(slackBotToken='xoxb-test')
		self.patch(net, 'post', lambda url, **kwargs: Resp({'ok': False, 'error': 'not_in_channel'}))
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertIsNone(slack_common.SlackBot('C1').post_text('hi'))
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
		once the answer is out, so the answer does not wait for it. Only with that message."""
		self.env(slackBotToken='xoxb-test')
		self.patch(transports.Transport, 'TYPING', (0, 7, 10))
		added = threading.Event()
		def post(url, **kwargs):
			"""Record the post; note when ⏳ is on."""
			self.posts.append((url, kwargs))
			if url.endswith('/reactions.add'):
				added.set()
			return Resp({'ok': True})
		self.patch(net, 'post', post)
		help_text = about.prepare_help
		self.patch(about, 'prepare_help', lambda *a: (added.wait(5), help_text(*a))[1]) # a command slow enough for ⏳
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.help', BOT, 'U', '1.2'))
		self.assertEqual([url.rsplit('/', 1)[-1] for url, _ in self.posts],
			['reactions.add', 'chat.postMessage', 'reactions.remove'])
		reaction = {'channel': 'C1', 'timestamp': '1.2', 'name': 'hourglass_flowing_sand'}
		self.assertEqual((self.posts[0][1]['data'], self.posts[2][1]['data']), (reaction, reaction))
		self.assertFalse(slack_common.SlackBot('C1').shows_typing) # no message to put it on

	def test_an_hourglass_slack_refuses_is_tried_once(self):
		"""⏳ that Slack refuses (a missing scope) is logged and not tried again, and nothing is taken off."""
		self.env(slackBotToken='xoxb-test')
		refuse = Resp({'ok': False, 'error': 'missing_scope'})
		self.patch(net, 'post', lambda url, **kwargs: self.posts.append((url, kwargs)) or refuse)
		chat = slack_common.SlackBot('C1', '1.2')
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
			slack_common.call('files.getUploadURLExternal', filename='chart.png', length=1) # it was a TypeError
		self.assertEqual(self.posts, [])


class SlackButtons(FinbotCase):
	"""A chart's period buttons on Slack: a Block Kit message (the report, the chart uploaded into no channel, the
	buttons) that a press redraws in place, in either mode."""
	UPLOAD_URL = 'https://files.slack.com/upload/v1/abc'

	def setUp(self):
		"""The real send path, its posts recorded and answered as Slack would; no waiting."""
		super().setUp()
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.env(slackBotToken='xoxb-test', slackOutgoingWebhook='https://example.com/slack')
		self.posts, self.refusals, self.waits = [], {}, []
		self.patch(slack_common.time, 'sleep', self.waits.append)
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
		self.patch(net, 'post', post)

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

	def uploading(self):
		"""Answer each upload with a new file id, F1 first, as Slack does."""
		uploads = iter(f'F{n}' for n in range(1, 10))
		record = net.post
		def post(url, **kwargs):
			"""Answer as Slack does, with a new file id for each upload."""
			answer = record(url, **kwargs)
			if url.endswith('/files.getUploadURLExternal'):
				return Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': next(uploads)})
			return answer
		self.patch(net, 'post', post)

	def test_a_period_shown_again_within_15_minutes_shows_its_upload_again(self):
		"""A press for a period whose chart was uploaded in the last 15 minutes, for this message or another, shows
		that upload again with the report it came with: nothing is built or uploaded. Past that, the period is built and
		uploaded anew, and the uploads no message shows are deleted, never one a message shows."""
		self.uploading()
		built = []
		build = charts.build
		self.patch(charts, 'build', lambda *args, **kwargs: built.append(args) or build(*args, **kwargs))
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U')) # 1D: F1, in message 1.5
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|w|5,0')) # 7D: F2
		del self.posts[:], built[:]
		worker.process_callback(inbound.Press('slack', 't2', 'C1', '2.5', 'c|l|d|5,0')) # 1D in another message: F1
		self.assertEqual((self.calls(), built, self.errors), (['chat.update'], [], []))
		blocks = self.blocks('chat.update')
		self.assertEqual(blocks[1]['slack_file'], {'id': 'F1'})
		self.assertTrue(blocks[0]['text']['text'].startswith('*≥ 5% at close'))
		with state.edit(slack_common.SLACK_CHARTS, {}) as noted: # 16 minutes on
			for upload in noted['uploads'].values():
				upload[0] -= 16 * 60 + 1
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|d|5,0')) # 1D again: F3
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F3'})
		deleted = [kwargs['data']['file'] for url, kwargs in self.posts if url.endswith('/files.delete')]
		self.assertEqual((deleted, len(built), self.errors), (['F2'], 1, [])) # message 2.5 shows F1

	def test_an_upload_slack_will_not_show_again_is_uploaded_anew(self):
		"""When Slack refuses to show an earlier upload again (a file deleted outside finbot, say), the period is
		built and uploaded anew."""
		self.uploading()
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U')) # 1D: F1
		self.refusals['chat.update'] = ['invalid_blocks']
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|d|5,0'))
		self.assertEqual(self.calls()[-5:], ['chat.update', 'files.getUploadURLExternal', 'upload',
			'files.completeUploadExternal', 'chat.update'])
		self.assertEqual((self.blocks('chat.update')[1]['slack_file'], self.errors), ({'id': 'F2'}, []))

	def test_the_charts_noted_before_uploads_were_reused_are_left_alone(self):
		"""The chart messages noted as before ({'channel ts': file}) are forgotten, their files never deleted."""
		state.save(slack_common.SLACK_CHARTS, {'C1 1.5': 'F0'})
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|w|5,0'))
		self.assertNotIn('files.delete', self.calls())
		self.assertEqual(state.load(slack_common.SLACK_CHARTS)['shown'], {'C1 1.5': 'F1'})

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

	def test_in_socket_mode_a_chart_has_its_buttons_too(self):
		"""In Socket Mode (no slackOutgoingWebhook) a press reaches finbot over the socket, so a chart has its buttons
		as in http mode."""
		self.env(slackOutgoingWebhook='', slackAppToken='xapp-1')
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.postMessage'])
		self.assertEqual(self.blocks('chat.postMessage')[-1]['type'], 'actions')

	def test_a_long_report_takes_several_sections(self):
		"""A report longer than a section takes holds is split into sections, and an empty one takes none."""
		caption = '\n'.join('x' * 99 for _ in range(70)) # 6,999 characters
		blocks = slack_common.chart_blocks(caption, [], 'F1')
		self.assertEqual([block['type'] for block in blocks], ['section'] * 3 + ['image'])
		self.assertTrue(all(len(block['text']['text']) <= 3000 for block in blocks[:3]))
		self.assertEqual([block['type'] for block in slack_common.chart_blocks('', [], 'F1')], ['image'])

	def test_a_chart_messages_buttons_keep_their_rows(self):
		"""The buttons of a chart message are a block a row, as a picker lays them out: never one row of them all, past
		the 25 elements a block takes."""
		rows = [[buttons.Button(f'B{i}{j}', f'k{i}{j}') for j in range(4)] for i in range(8)]
		blocks = slack_common.chart_blocks('x', rows, 'F1')
		self.assertEqual([len(block.get('elements', [])) for block in blocks], [0, 0] + [4] * 8)

	def test_a_chart_message_that_times_out_is_not_posted_again(self):
		"""A chart with its buttons whose chat.postMessage times out may have arrived: no plain copy follows."""
		record = net.post
		def post(url, **kwargs):
			"""Time out on chat.postMessage, as a slow Slack does."""
			if url.endswith('/chat.postMessage'):
				self.posts.append((url, kwargs))
				raise requests.exceptions.ReadTimeout('slow')
			return record(url, **kwargs)
		self.patch(net, 'post', post)
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.price', BOT, 'U'))
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.postMessage'])
		self.assertEqual(self.errors, [])



class EveryNetworkAndMode(FinbotCase):
	"""One rule for the six networks and modes, in a channel and in a DM: a chart has its period buttons and a .jobs
	run list its buttons, a command shows the network's notice that finbot is at work, and the reply goes to the chat
	that asked."""
	MODES = {
		('telegram', 'http'): {'telegramOutgoingWebhook': 'https://example.com/telegram'},
		('telegram', 'pull'): {'telegramOutgoingWebhook': ''},
		('slack', 'http'): {'slackBotToken': 'xoxb-1', 'slackOutgoingWebhook': 'https://example.com/slack'},
		('slack', 'pull'): {'slackBotToken': 'xoxb-1', 'slackAppToken': 'xapp-1', 'slackOutgoingWebhook': ''},
		('discord', 'http'): {'discordBotToken': 'x', 'discordOutgoingWebhook': 'https://example.com/discord',
			'discordPublicKey': 'ab' * 32},
		('discord', 'pull'): {'discordBotToken': 'x', 'discordOutgoingWebhook': ''},
	}
	CHATS = {'telegram': ('-1001', '55'), 'slack': ('C1', 'D1'), 'discord': ('77', '88')} # a channel, then a DM

	def setUp(self):
		"""A job in each chat for .jobs run to list, and what each command posts noted with its destination."""
		super().setUp()
		self.patch(discord_common.READER, 'bot_id', '99')
		every = {'jobs': [{'action': 'trades', 'args': [], 'schedule': {'days': 'weekdays', 'every': 20, 'zone': 'UTC'},
			'on': True}]}
		state.save(jobs.JOBS_FILE, {f'{network}:{chat}': every for network, chats in self.CHATS.items()
			for chat in chats})
		scheduler = jobs.Scheduler()
		with contextlib.redirect_stderr(io.StringIO()):
			scheduler.load()
		self.patch(jobs, 'current', scheduler)
		self.posted = []
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, buttons=None:
			self.posted.append((dest, buttons)) or {'ok': True})
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None: self.posted.append((dest, buttons))
			or [])
		self.updates = 0

	def update(self, network, mode, chat, text):
		"""The update the network sends for a message in this mode: Discord's http mode has only the slash command."""
		self.updates += 1
		n, person = self.updates, {'id': '5', 'username': 'rob', 'first_name': 'Rob'}
		if network == 'telegram':
			message = {'message_id': n, 'chat': {'id': int(chat)}, 'from': person, 'text': text}
			return {'update_id': n, 'message': message}
		if network == 'slack':
			return {'type': 'event_callback', 'event_id': f'Ev{n}', 'authorizations': [{'user_id': 'UBOT'}],
				'event': {'type': 'message', 'channel': chat, 'user': 'U1', 'text': text, 'ts': f'{n}.1'}}
		if mode == 'pull':
			return {'id': str(700 + n), 'channel_id': chat, 'author': person, 'content': text}
		name, _, arguments = text.removeprefix('.').partition(' ')
		options = [{'name': 'arguments', 'type': 3, 'value': arguments}] if arguments else []
		who = {'user': person} if chat == '88' else {'member': {'user': person}}
		return {'id': str(900 + n), 'application_id': '42', 'token': f't{n}', 'type': 2, 'channel_id': chat, **who,
			'data': {'name': name, 'options': options}}

	def test_every_network_in_both_modes_in_a_channel_and_a_dm(self):
		"""A chart and a .jobs run list each come with their buttons, in the chat that asked; the command showed the
		notice that finbot is at work: "typing…" (Telegram, a Discord message), ⏳ on the message (Slack), or Discord's
		"thinking…" for a slash command, which its answer replaces."""
		for (network, mode), keys in self.MODES.items():
			for chat in self.CHATS[network]:
				with self.subTest(network=network, mode=mode, chat=chat):
					self.env(**keys)
					self.posted.clear(); self.typing.clear()
					answers = []
					with contextlib.redirect_stderr(io.StringIO()):
						for text in ('.price', '.jobs run'):
							answer = bot.take(READERS[network], self.update(network, mode, chat, text))
							answers.append(answer)
							if answer.then:
								answer.then()
						self.join_workers()
					self.assertEqual(self.errors, [])
					self.assertEqual([(dest.where, bool(buttons)) for dest, buttons in self.posted], [(chat, True)] * 2)
					if network == 'discord' and mode == 'http':
						self.assertEqual([json.loads(answer.body) for answer in answers], [{'type': 5}] * 2)
						self.assertTrue(all(dest.interaction and not dest.shows_typing for dest, _ in self.posted))
					else:
						self.assertEqual(len(self.typing), 2)
						self.assertTrue(all(dest.shows_typing for dest in self.typing))


if __name__ == '__main__':
	unittest.main()
