"""Posting to the networks against their answers and failures: Telegram, Slack (text, charts, Block Kit
buttons) and Discord."""
import contextlib, html.parser, io, json, threading, types, unittest
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
		"""Telegram refuses an edit that changes nothing ("message is not modified": a press whose answer looks as the
		message does), which each edit takes as done, logged at debug in a few words, never as a failure."""
		refusal = Resp({'ok': False, 'description': 'Bad Request: message is not modified: specified new message'
			' content and reply markup are exactly the same as a current content and reply markup of the message'}, 400)
		self.patch(net, 'post', lambda url, **kwargs: refusal)
		chat = telegram_common.TelegramBot('5')
		for name, edit in (('text', lambda: chat.edit_text('8', 'text')),
				('buttons', lambda: chat.edit_buttons('8', [])),
				('chart', lambda: chat.edit_chart('8', io.BytesIO(b'png'), 'caption'))):
			for level, logged in (('INFO', ''), ('DEBUG', 'Telegram message not edited: it shows that already\n')):
				self.settings(log_level=level)
				with self.subTest(edit=name, level=level), contextlib.redirect_stderr(io.StringIO()) as log:
					edit()
					lines = log.getvalue().splitlines(keepends=True) # a chart's file id is looked up in the cache first
					self.assertEqual(''.join(line for line in lines if not line.startswith('cache ')), logged)

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

	def photos(self, refused=()):
		"""net.post as Telegram, each upload answered with a new file id (P1, P2...), and each file id in `refused`
		refused as Telegram refuses another bot's: the requests, as (method, data, whether bytes went)."""
		sent, uploads = [], iter(f'P{n}' for n in range(1, 10))
		def post(url, data=None, files=None, **kwargs):
			"""Answer as Telegram does, the message with its photo's sizes, the largest last."""
			sent.append((url.rsplit('/', 1)[1], data, files is not None))
			given = data.get('photo') or json.loads(data.get('media', '{}')).get('media')
			if given in refused:
				return Resp({'ok': False, 'description': 'Bad Request: wrong file identifier/HTTP URL specified'}, 400)
			photo = next(uploads) if files else 'unchanged'
			return Resp({'ok': True, 'result': {'message_id': 8, 'photo': [{'file_id': photo + 's', 'width': 320},
				{'file_id': photo, 'width': 1280}]}})
		self.patch(net, 'post', post)
		return sent

	def test_a_chart_uploaded_once_is_shown_again_by_its_file_id(self):
		"""A chart Telegram has (the same bytes, by this bot) goes by the file id of its largest size, in a new message
		or a message edited for a period or portfolio pressed again: no bytes are sent. Another chart is uploaded."""
		sent = self.photos()
		chat = telegram_common.TelegramBot('5')
		chat.post_chart(io.BytesIO(b'png one'), 'caption')
		chat.post_chart(io.BytesIO(b'png one'), 'caption')
		chat.edit_chart('8', io.BytesIO(b'png two'), 'another period')
		chat.edit_chart('8', io.BytesIO(b'png one'), 'back to the first')
		self.assertEqual([(method, uploaded) for method, _, uploaded in sent], [('sendPhoto', True),
			('sendPhoto', False), ('editMessageMedia', True), ('editMessageMedia', False)])
		self.assertEqual(sent[1][1]['photo'], 'P1')
		self.assertEqual(json.loads(sent[2][1]['media'])['media'], 'attach://photo')
		self.assertEqual(json.loads(sent[3][1]['media']), {'type': 'photo', 'caption': 'back to the first',
			'parse_mode': 'HTML', 'media': 'P1'})

	def test_a_file_id_telegram_refuses_gives_way_to_an_upload(self):
		"""A file id Telegram will not take (another bot's, say) is followed by the upload, whose file id is kept."""
		sent = self.photos(refused=('P1',))
		chat = telegram_common.TelegramBot('5')
		chat.post_chart(io.BytesIO(b'png'), 'caption')
		with contextlib.redirect_stderr(io.StringIO()) as log:
			chat.post_chart(io.BytesIO(b'png'), 'caption')
		self.assertIn('refused an earlier upload of the chart', log.getvalue())
		chat.post_chart(io.BytesIO(b'png'), 'caption')
		self.assertEqual([(uploaded, data.get('photo')) for _, data, uploaded in sent], [(True, None), (False, 'P1'),
			(True, None), (False, 'P2')])

	def test_a_press_that_uploads_its_chart_logs_its_post_at_info(self):
		"""A press's edit logs its POST line at INFO when it uploads the chart's image, and at DEBUG only when it sends
		the file id of an earlier upload: the log tells which presses uploaded a chart."""
		chat = telegram_common.TelegramBot('5')
		cache.write(telegram_common.photo_file(b'known png'), 'P1')
		for level, image, shown in (('INFO', b'new png', True), ('INFO', b'known png', False),
				('DEBUG', b'known png', True)):
			self.settings(log_level=level)
			with self.subTest(level=level, image=image), contextlib.redirect_stderr(io.StringIO()) as log:
				chat.edit_chart('8', io.BytesIO(image), 'caption')
				self.assertEqual('POST api.telegram.org/botX/editMessageMedia\n' in log.getvalue(), shown)

	def preloading(self):
		"""A clock of this test's own for the preloads' gap (its last preload long gone), each wait noted: the waits."""
		self.now, waits = [1000.0], []
		self.patch(transports, 'time', types.SimpleNamespace(monotonic=lambda: self.now[0], sleep=waits.append))
		self.patch(telegram_common.TelegramBot, 'preloaded_at', 0.0)
		self.patch(slack_common.SlackBot, 'preloaded_at', 0.0)
		return waits

	def test_a_chart_preloaded_goes_to_the_preload_chat_and_keeps_its_file_id(self):
		"""Preloading uploads a chart Telegram has not to the preload chat, silently and with no caption, and keeps its
		file id: a press's edit of that chart in another chat then sends the id. A chart Telegram has is not sent again,
		the next preload waits out the gap, and with the cache setting off nothing is sent."""
		sent, waits = self.photos(), self.preloading()
		self.settings(preload_gap=3.0)
		chat = telegram_common.TelegramBot('-100777')
		self.assertTrue(chat.preload(b'one'))
		self.assertTrue(chat.preload(b'one')) # Telegram has it now
		self.now[0] += 1
		self.assertTrue(chat.preload(b'two'))
		telegram_common.TelegramBot('5').edit_chart('8', io.BytesIO(b'one'), 'pressed')
		self.assertEqual([(method, data['chat_id'], uploaded) for method, data, uploaded in sent], [('sendPhoto',
			'-100777', True), ('sendPhoto', '-100777', True), ('editMessageMedia', '5', False)])
		self.assertEqual(sent[0][1], {'chat_id': '-100777', 'disable_notification': True})
		self.assertEqual(waits, [0.0, 3.0 - 1])
		self.settings(cache=False)
		self.assertTrue(chat.preload(b'three'))
		self.assertEqual(len(sent), 3)

	def test_the_gap_between_preloads_is_a_setting(self):
		"""preload_gap says how long a preload waits after the last one, for either network."""
		waits = self.preloading()
		self.settings(preload_gap=1.0)
		chat = telegram_common.TelegramBot('5')
		self.patch(telegram_common.TelegramBot, 'send_ahead', lambda dest, photo: None)
		self.assertTrue(chat.preload(b'one'))
		self.now[0] += 0.25
		self.assertTrue(chat.preload(b'two'))
		self.settings(preload_gap=0.0)
		self.assertTrue(chat.preload(b'three'))
		self.assertEqual(waits, [0.0, 0.75, 0.0])

	def test_the_gap_runs_from_the_start_of_the_last_send_not_its_end(self):
		"""A preload that takes two seconds to upload leaves only the rest of the gap to wait: sends begin the gap
		apart, not the gap plus an upload."""
		waits = self.preloading()
		self.settings(preload_gap=3.0)
		def upload(dest, photo):
			"""An upload that takes two seconds."""
			self.now[0] += 2
		self.patch(telegram_common.TelegramBot, 'send_ahead', upload)
		chat = telegram_common.TelegramBot('-100777')
		self.assertTrue(chat.preload(b'one'))
		self.assertTrue(chat.preload(b'two'))
		self.assertEqual(waits, [0.0, 1.0]) # the 3 second gap less the 2 seconds the first took

	def test_a_rate_limit_is_waited_out_once_and_the_preload_tried_again(self):
		"""Telegram's "retry after 5" (Slack's "ratelimited": ten seconds) is slept through, at most RATE_LIMIT_WAIT,
		and the chart sent again; a second refusal, or any other failure, ends it as before."""
		waits = self.preloading()
		limited = 'Telegram sendPhoto: Too Many Requests: retry after '
		telegram, slack = telegram_common.TelegramBot, slack_common.SlackBot
		def refusing(error, times):
			"""A send_ahead that raises `error` its first `times` calls, and counts its calls in tries."""
			tries = []
			def send(dest, photo):
				"""Raise, or send."""
				tries.append(photo)
				if len(tries) <= times:
					raise RuntimeError(error)
			return send, tries
		cases = ((telegram, limited + '5', 5), (telegram, limited + '900', transports.RATE_LIMIT_WAIT),
			(slack, 'Slack files.completeUploadExternal: ratelimited', 10))
		for kind, error, wait in cases:
			with self.subTest(error=error):
				send, tries = refusing(error, 1)
				self.patch(kind, 'send_ahead', send)
				del waits[:]
				with contextlib.redirect_stderr(io.StringIO()) as log:
					self.assertTrue(kind('-100777').preload(b'png'))
				self.assertEqual((len(tries), waits[1:]), (2, [wait]))
				self.assertIn('is rate limited', log.getvalue())
		for error, tried in ((limited + '1', 2), ('Telegram sendPhoto: Bad Request: chat not found', 1)):
			with self.subTest(error=error), contextlib.redirect_stderr(io.StringIO()):
				send, tries = refusing(error, 9)
				self.patch(telegram, 'send_ahead', send)
				self.assertFalse(telegram('-100777').preload(b'png')) # refused again, or not a rate limit: it stops
				self.assertEqual(len(tries), tried)

	def test_charts_drawn_are_preloaded_to_their_networks_preload_chat_where_a_setting_names_one(self):
		"""A delivery.Preloader hands each chart added to the preload chat its network's setting names, as that
		network's bot; with no chat named, on Discord, or with no image, it does nothing."""
		taken = []
		for kind in (telegram_common.TelegramBot, slack_common.SlackBot):
			self.patch(kind, 'preload', lambda chat, photo: taken.append((chat.key, photo)) or True)
		def preload(service, *images):
			"""Add the images to a preloader and wait for it."""
			preloader = delivery.Preloader(service)
			for image in images:
				preloader.add(image)
			preloader.finish()
		preload(TELEGRAM, io.BytesIO(b'png'))
		self.settings(telegram_preload_chat='-100777', slack_preload_chat='C9')
		for service in (TELEGRAM, SLACK, DISCORD):
			preload(service, io.BytesIO(b'png'), None, io.BytesIO(b'two'))
		self.assertEqual(sorted(taken), [('slack:C9', b'png'), ('slack:C9', b'two'), ('telegram:-100777', b'png'),
			('telegram:-100777', b'two')])

	def test_charts_are_preloaded_two_at_a_time_by_the_same_code_on_both_networks(self):
		"""A Preloader sends the charts it is handed PRELOAD_PARALLEL at a time, on Telegram as on Slack: all are sent,
		never more than two in flight (each waits at the barrier for the other, so none could go after another)."""
		self.settings(preload_gap=0.0, telegram_preload_chat='-100777', slack_preload_chat='C9')
		for kind, service in ((telegram_common.TelegramBot, TELEGRAM), (slack_common.SlackBot, SLACK)):
			with self.subTest(network=kind.name):
				busy, peak, sent, lock = [0], [0], [], threading.Lock()
				meet = threading.Barrier(transports.PRELOAD_PARALLEL, timeout=5)
				def upload(chat, photo):
					"""An upload that waits for the one beside it, counting those in flight."""
					with lock:
						busy[0] += 1
						peak[0] = max(peak[0], busy[0])
					meet.wait()
					with lock:
						busy[0] -= 1
						sent.append(photo)
				self.patch(kind, 'preloaded_at', 0.0)
				self.patch(kind, 'send_ahead', upload)
				preloader = delivery.Preloader(service)
				for photo in (b'a', b'b', b'c', b'd'):
					preloader.add(io.BytesIO(photo))
				preloader.finish()
				self.assertEqual((sorted(sent), peak[0], preloader.failed), ([b'a', b'b', b'c', b'd'], 2, False))
		self.assertEqual(transports.PRELOAD_PARALLEL, 2)

	def test_a_preload_that_fails_stops_the_rest(self):
		"""A chart that cannot be preloaded is a warning, and the charts handed over after it are not sent."""
		self.settings(preload_gap=0.0, telegram_preload_chat='-100777')
		self.patch(telegram_common.TelegramBot, 'preloaded_at', 0.0)
		sent = []
		def upload(chat, photo):
			"""Refuse the first chart."""
			sent.append(photo)
			raise RuntimeError('Telegram sendPhoto: Bad Request: chat not found')
		self.patch(telegram_common.TelegramBot, 'send_ahead', upload)
		with contextlib.redirect_stderr(io.StringIO()) as log:
			preloader = delivery.Preloader(TELEGRAM)
			preloader.add(io.BytesIO(b'one'))
			preloader.finish()
			preloader.pool = None # finished: what is handed over now is not even queued
			preloader.add(io.BytesIO(b'two'))
		self.assertEqual((sent, preloader.failed), ([b'one'], True))
		self.assertIn('Telegram preload to -100777 failed', log.getvalue())

	def test_a_preload_telegram_refuses_is_logged_and_stops(self):
		"""A preload that fails (the bot not in the chat, say) is a warning, and False: priming stops preloading."""
		self.preloading()
		refusal = Resp({'ok': False, 'description': 'Bad Request: chat not found'}, 400)
		self.patch(net, 'post', lambda url, **kwargs: refusal)
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertFalse(telegram_common.TelegramBot('-100777').preload(b'png'))
		self.assertIn('Telegram preload to -100777 failed: Telegram sendPhoto: Bad Request: chat not found',
			log.getvalue())

	def test_a_file_id_is_another_bots_after_the_token_changes_or_none_with_the_cache_off(self):
		"""A file id is reused by the bot that uploaded it alone (a new token is another bot), and not at all with the
		cache setting off."""
		sent = self.photos()
		telegram_common.TelegramBot('5').post_chart(io.BytesIO(b'png'), 'caption')
		self.env(telegramBotToken='Y')
		telegram_common.TelegramBot('5').post_chart(io.BytesIO(b'png'), 'caption')
		self.settings(cache=False)
		telegram_common.TelegramBot('5').post_chart(io.BytesIO(b'png'), 'caption')
		self.assertEqual([uploaded for _, _, uploaded in sent], [True, True, True])

	def test_each_network_draws_a_buttons_look_in_its_own_style(self):
		"""A button's look (buttons.look) becomes each network's style: a toggle that is on green and one that is off
		red, the button shown now blue on Telegram (primary, its label unmarked) and Discord (blurple), green on Slack
		(primary); a plain button gets none, grey on Discord."""
		row = [buttons.Button('a', 'da', tone=buttons.ON), buttons.Button('b', 'db', tone=buttons.OFF),
			buttons.Button('c', 'dc', active=True), buttons.Button('d', 'dd')]
		keyboard = telegram_common.TelegramBot.markup([row])['inline_keyboard'][0]
		self.assertEqual([(button['text'], button.get('style')) for button in keyboard],
			[('a', 'success'), ('b', 'danger'), ('c', 'primary'), ('d', None)])
		elements = slack_common.actions_block(row)['elements']
		self.assertEqual([element.get('style') for element in elements], ['primary', 'danger', 'primary', None])
		components = discord_common.components([row])[0]['components']
		self.assertEqual([component['style'] for component in components], [3, 4, 1, 2])

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

	def test_every_bot_takes_charts(self):
		"""Every network's bot takes charts, whichever way its updates arrive, and no setting holds them back."""
		self.env(slackBotToken='', slackAppToken='', slackOutgoingWebhook='', telegramOutgoingWebhook='')
		for kind in (telegram_common.TelegramBot, slack_common.SlackBot, discord_common.DiscordBot):
			with self.subTest(kind=kind.__name__):
				self.assertTrue(kind('1').takes_charts)

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

		for cmd, heading in (('.beta', '*Beta over 1.5'), ('.peg', '*')):
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
		for report in (movers.run, lambda dest: performance.run(dest, past_days=7), shorts.run):
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
			for cmd in ('.movers', '.movers top', '.performance 7d', '.shorts', '.buy', '.peg', '.beta',
					'.compare T1 T2', '.pie Rob'):
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
			movers.run(scheduled('discord:77'))
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
			for cmd in ('.help', '.movers', '.compare T1 T2'):
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


class TelegramCharts(FinbotCase):
	"""A Telegram chart and its period buttons through the real send path: what each press sends, and what it builds."""

	def setUp(self):
		"""The real sending, Telegram answering each photo with its file id (P1, P2... for each upload, else the file id
		sent), and each chart built counted."""
		super().setUp()
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.requests, self.refused, uploads = [], set(), iter(f'P{n}' for n in range(1, 10))
		def post(url, data=None, files=None, **kwargs):
			"""Answer as Telegram does: the message, with its photo's sizes, the largest last; a file id in refused
			is refused, as another bot's is."""
			data = data or {}
			media = json.loads(data.get('media', '{}'))
			given = data.get('photo') or media.get('media')
			self.requests.append((url.rsplit('/', 1)[1], given, files is not None, data.get('caption') or
				media.get('caption')))
			if given in self.refused:
				return Resp({'ok': False, 'description': 'Bad Request: wrong file identifier/HTTP URL specified'}, 400)
			photo = next(uploads) if files else given
			return Resp({'ok': True, 'result': {'message_id': 9, 'chat': {'id': 55},
				'photo': [{'file_id': f'{photo}-small'}, {'file_id': photo}]}})
		self.patch(net, 'post', post)
		self.built = []
		build = charts.build
		self.patch(charts, 'build', lambda *args, **kwargs: self.built.append(args[1]) or build(*args, **kwargs))

	def press(self, data, chat='55', message='9'):
		"""Press a chart's button, as its update arrives."""
		worker.process_callback(inbound.Press('telegram', 'cb', chat, message, data))
		self.assertEqual(self.errors, [])

	def age_views(self, seconds):
		"""Make what each chat's chart messages showed for each period `seconds` older."""
		for name in os.listdir(config.env.cache_dir):
			if name.startswith('finbot_telegram_view_'):
				path = os.path.join(config.env.cache_dir, name)
				os.utime(path, (os.path.getmtime(path) - seconds,) * 2)

	def test_a_period_pressed_again_within_30_minutes_shows_its_upload_again(self):
		"""A press for a period shown in this chat in the last 30 minutes (in this message or another) shows that
		upload again by its file id, with the report it came with: nothing is built, drawn or uploaded. Another chat
		builds its own; past 30 minutes the period is built again, its chart (the same) sent by its file id."""
		worker.process_request(inbound.Message('telegram', '55', '@u', '.movers', BOT, 'U')) # 1D: P1
		caption = next(caption for method, _, _, caption in self.requests if method == 'sendPhoto')
		self.press('c|l|w|5,0') # 7D: built, uploaded as P2
		self.assertEqual(self.built, [['5', '0']])
		self.assertEqual(self.requests[-1][:3], ('editMessageMedia', 'attach://photo', True))
		self.press('c|l|d|5,0', message='10') # 1D in another message: P1 shown again, with its report
		self.assertEqual((len(self.built), self.requests[-1]), (1, ('editMessageMedia', 'P1', False, caption)))
		self.press('c|l|d|5,0', chat='56') # another chat: built for it
		self.assertEqual(len(self.built), 2)
		self.age_views(30 * 60)
		self.press('c|l|w|5,0') # 7D again, 30 minutes on: built, the same chart sent by its file id
		self.assertEqual((len(self.built), self.requests[-1][:3]), (3, ('editMessageMedia', 'P2', False)))

	def test_an_earlier_upload_telegram_refuses_is_drawn_anew(self):
		"""A period's earlier upload that Telegram will not show again is built, drawn and uploaded anew."""
		worker.process_request(inbound.Message('telegram', '55', '@u', '.movers', BOT, 'U')) # 1D: P1
		self.refused.add('P1')
		with contextlib.redirect_stderr(io.StringIO()):
			self.press('c|l|d|5,0')
		self.assertEqual((len(self.built), self.requests[-1][:3]), (1, ('editMessageMedia', 'attach://photo', True)))

	def test_with_the_cache_off_each_press_builds_its_period(self):
		"""With the cache setting off, nothing is noted to show again: each press builds and uploads its period."""
		self.settings(cache=False)
		worker.process_request(inbound.Message('telegram', '55', '@u', '.movers', BOT, 'U'))
		self.press('c|l|w|5,0')
		self.press('c|l|d|5,0')
		uploads = [uploaded for _, _, uploaded, _ in self.requests if uploaded]
		self.assertEqual((len(self.built), uploads), (2, [True] * 3))


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
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U'))
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

	def test_a_period_shown_again_within_30_minutes_shows_its_upload_again(self):
		"""A press for a period whose chart was uploaded in the last 30 minutes, for this message or another, shows
		that upload again with the report it came with: nothing is built or uploaded. Past that, the period is built and
		uploaded anew, and the uploads no message shows are deleted a minute later, never one a message shows."""
		self.uploading()
		built = []
		build = charts.build
		self.patch(charts, 'build', lambda *args, **kwargs: built.append(args) or build(*args, **kwargs))
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U')) # 1D: F1, in message 1.5
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|w|5,0')) # 7D: F2
		del self.posts[:], built[:]
		worker.process_callback(inbound.Press('slack', 't2', 'C1', '2.5', 'c|l|d|5,0')) # 1D in another message: F1
		self.assertEqual((self.calls(), built, self.errors), (['chat.update'], [], []))
		blocks = self.blocks('chat.update')
		self.assertEqual(blocks[1]['slack_file'], {'id': 'F1'})
		self.assertTrue(blocks[0]['text']['text'].startswith('*≥ 5% at close'))
		self.assertEqual(slack_common.SLACK_REUSE_SECONDS, 30 * 60)
		with state.edit(slack_common.SLACK_CHARTS, {}) as noted: # 31 minutes on
			for upload in noted['uploads'].values():
				upload[0] -= 31 * 60 + 1
		worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'c|l|d|5,0')) # 1D again: F3
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F3'})
		deleted = [kwargs['data']['file'] for url, kwargs in self.posts if url.endswith('/files.delete')]
		self.assertEqual((deleted, len(built), self.errors), (['F2'], 1, [])) # message 2.5 shows F1

	def test_the_same_chart_is_shown_with_its_earlier_upload(self):
		"""A chart uploaded in the last 30 minutes (the same PNG), such as a portfolio picked again, is shown with that
		upload, which counts as new again: nothing is uploaded, and Slack shows it at once. Past 30 minutes, it is
		uploaded anew."""
		self.uploading()
		chat = slack_common.SlackBot('C1')
		for image in (b'one', b'two', b'one'):
			chat.edit_chart('1.5', io.BytesIO(image), image.decode())
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.update'] * 2 + ['chat.update'])
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F1'})
		self.assertEqual(self.blocks('chat.update')[0]['text']['text'], 'one')
		with state.edit(slack_common.SLACK_CHARTS, {}) as noted: # 29 minutes on: still shown again
			for upload in noted['uploads'].values():
				upload[0] -= 29 * 60
		chat.edit_chart('1.5', io.BytesIO(b'two'), 'two')
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F2'})
		with state.edit(slack_common.SLACK_CHARTS, {}) as noted: # 30 minutes after it was shown again
			for upload in noted['uploads'].values():
				upload[0] -= 30 * 60
		chat.edit_chart('1.5', io.BytesIO(b'two'), 'two')
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F3'})
		self.assertEqual(self.waits, []) # never a chart Slack could not show yet

	def test_a_period_pressed_in_another_channel_is_its_own_chart(self):
		"""A period's upload is shown again in the channel it was drawn for: another channel's movers list is of the
		stocks that channel follows, so a press there builds its own."""
		self.uploading()
		self.patch(watchlist, 'with_holdings', lambda chat: TICKERS[:3] if chat == 'slack:C2' else TICKERS)
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U')) # 1D: F1
		worker.process_callback(inbound.Press('slack', 't2', 'C2', '2.5', 'c|l|d|5,0')) # 1D in C2: its own, F2
		self.assertEqual(self.errors, [])
		self.assertEqual(self.calls()[-4:], ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal',
			'chat.update'])
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F2'})

	def test_a_chart_preloaded_into_the_preload_channel_is_shown_without_an_upload(self):
		"""Preloading uploads a chart into the preload channel; a press's edit of that chart in another channel within
		30 minutes shows that upload, uploading nothing. A preloaded file no message shows is deleted 31 minutes on,
		as every such upload is."""
		self.uploading()
		self.patch(transports, 'time', types.SimpleNamespace(monotonic=lambda: 1000.0, sleep=lambda seconds: None))
		self.patch(slack_common.SlackBot, 'preloaded_at', 0.0)
		preload = slack_common.SlackBot('C9')
		self.assertTrue(preload.preload(b'one'))
		self.assertEqual(self.calls(), ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal'])
		self.assertEqual(self.posts[-1][1]['data']['channel_id'], 'C9')
		self.assertTrue(preload.preload(b'one')) # uploaded already: nothing more
		slack_common.SlackBot('C1').edit_chart('1.5', io.BytesIO(b'one'), 'one')
		self.assertEqual(self.calls()[3:], ['chat.update'])
		self.assertEqual(self.blocks('chat.update')[1]['slack_file'], {'id': 'F1'})
		self.assertTrue(preload.preload(b'two')) # F2, which no message shows
		with state.edit(slack_common.SLACK_CHARTS, {}) as noted: # 31 minutes on
			for upload in noted['uploads'].values():
				upload[0] -= 31 * 60 + 1
		slack_common.SlackBot('C1').edit_chart('1.5', io.BytesIO(b'three'), 'three')
		deleted = [kwargs['data']['file'] for url, kwargs in self.posts if url.endswith('/files.delete')]
		self.assertIn('F2', deleted)

	def test_an_upload_slack_will_not_show_again_is_uploaded_anew(self):
		"""When Slack refuses to show an earlier upload again (a file deleted outside finbot, say), the period is
		built and uploaded anew."""
		self.uploading()
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U')) # 1D: F1
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
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U'))
		self.assertEqual((self.calls()[-2:], self.waits), (['chat.postMessage', 'chat.postMessage'], [1]))
		self.assertEqual((self.sent, self.errors), ([], []))

	def test_buttons_slack_will_not_show_leave_a_plain_chart(self):
		"""When Slack will not show the chart with its buttons, the chart is uploaded into the channel without them."""
		self.refusals['chat.postMessage'] = ['invalid_blocks'] * 4
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U'))
		self.assertEqual(self.calls()[-3:], ['files.getUploadURLExternal', 'upload', 'files.completeUploadExternal'])
		self.assertEqual(self.posts[-1][1]['data']['channel_id'], 'C1')
		self.assertEqual((self.waits, self.sent, self.errors), ([1, 2, 4], [], []))

	def test_in_socket_mode_a_chart_has_its_buttons_too(self):
		"""In Socket Mode (no slackOutgoingWebhook) a press reaches finbot over the socket, so a chart has its buttons
		as in http mode."""
		self.env(slackOutgoingWebhook='', slackAppToken='xapp-1')
		worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U'))
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
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.movers', BOT, 'U'))
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
						for text in ('.movers', '.jobs run'):
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
