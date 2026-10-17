"""Shared fixture: points finbot at a temp cache dir and replaces every external service
(Telegram, Yahoo, Sharesight, Short Man) with canned data. Nothing here touches the network. ProviderCase runs the real
parsers instead, on the API answers saved under doc/ (sample) as a stand-in network returns them (Resp, serve)."""
import collections, dataclasses, datetime, io, json, os, shutil, sys, tempfile, time, unittest, zoneinfo
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.update(telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok')

import bot
from lib import answer, buttons, cache, charts, config, delivery, dialects, formats, inbound, links, markets, net
from lib import render, sharesight, shortman, state, transports, watchlist, worker, yahoo
from lib import discord_common, slack_common, telegram_common # each network's reader and bot
from lib.reports import about, earnings, history, holdings, milestone, movers, performance, profile, rankings, rating
from lib.reports import shorts, trades

REAL = {(m.__name__, n): getattr(m, n) for m, n in ((yahoo, 'fetch'), (yahoo, 'fetch_detail'), (yahoo, 'price_series'),
	(yahoo, 'price_history'), (yahoo, 'historic_high'),
	(sharesight, '_portfolios'), (sharesight, '_trades'), (sharesight, '_performance'))}
REAL_GET_HOLDINGS = watchlist.with_holdings
REAL_DISPATCH = bot.dispatch # FinbotCase notes the worker thread of each update, so that a test can wait for it
REAL_DOUBLED = bot.doubled # FinbotCase takes every message, a repeat sent on purpose too; DoubledMessages puts it back
REAL_REPEATED = worker.repeated # and every press, as RepeatedPresses does not


def no_jobs(data):
	"""No chat known in a data dir, so that a bot started there runs no scheduled report."""
	Path(data, 'finbot_chat_jobs.json').write_text('{}')


def scheduled(key='telegram:1'):
	"""A chat as a scheduled run posts to it, the job's (Telegram's chat 1 unless another key is given)."""
	return delivery.chat(key, scheduled=True)


def bare_environment():
	"""os.environ without finbot's settings (the startup keys and the settings): for a process that must start from
	the defaults."""
	settings = {*config.STARTUP_KEYS, *config.SETTING_KEYS}
	return {k: v for k, v in os.environ.items() if k not in settings}


def temp_dir(case):
	"""A new temporary directory, removed when the test `case` ends."""
	path = tempfile.mkdtemp()
	case.addCleanup(shutil.rmtree, path, True)
	return path

REAL_TEXT = transports.Transport.text # FinbotCase replaces it with a recorder; tests of the real thing put it back
REAL_CHART = transports.Transport.chart # likewise
REAL_REPORT_ERROR = delivery.report_error # likewise
REAL_START_TYPING = transports.Transport.start_typing # FinbotCase notes each chat it is started in
# what FinbotCase replaces with recorders; util/record_outputs.py puts them back to record the real requests
REAL_SENDING = ((transports.Transport, 'text', REAL_TEXT), (transports.Transport, 'chart', REAL_CHART),
	(delivery, 'report_error', REAL_REPORT_ERROR))
TICKERS = [f'T{i}' for i in range(25)]
TELEGRAM, SLACK, DISCORD = dialects.TELEGRAM, dialects.SLACK, dialects.DISCORD
READERS = {'telegram': telegram_common.READER, 'slack': slack_common.READER, 'discord': discord_common.READER}
BOT = '@bot'


def wsgi_environ(path, body, **headers):
	"""A WSGI environ posting `body` (bytes) to `path`, with these headers (as HTTP_* keys)."""
	return {'REQUEST_METHOD': 'POST', 'PATH_INFO': path, 'wsgi.input': io.BytesIO(body),
		'CONTENT_LENGTH': str(len(body)), **headers}


STATES = ('REGULAR', 'PRE', 'POST', 'CLOSED')


NOW = time.time() # one moment for every fixture quote: fetched together in threads, they still tie on their dates


def market_entry(ticker):
	"""A Yahoo quote for a fixture ticker; T0 to T24 vary in market state, move, rating and so on, so that every
	threshold, sort and branch has rows."""
	i = int(ticker[1:]) if ticker[1:].isdigit() else 0 # varied data so threshold/sort/sell branches all have rows
	return {'marketState': STATES[i % 4], 'regularMarketTime': NOW, 'quoteType': 'EQUITY',
			'profile_title': 'Co ' + ticker, 'profile_exchange': 'NasdaqGS', 'percent_change': (i - 12) * 1.5,
			'percent_change_premarket': (i - 12) * 1.5, 'percent_change_postmarket': (i - 12) * 1.5,
			'market_cap': 1e9, 'price_to_earnings_trailing': 9, 'price_to_earnings_forward': 9,
			'beta': 2.0, 'short_percent': 20, 'fiftyTwoWeekHigh': 120.0, 'fiftyTwoWeekLow': 80.0,
			'regularMarketPrice': 100.0, 'earnings_date': NOW + 86400 * 3,
			'ex_dividend_date': NOW + 86400 * 3, 'recommend': 'buy' if i % 2 else 'sell',
			'recommend_index': 1.2 if i % 2 else 4.2, 'recommend_analysts': 8, 'price_to_earnings_peg': 1.2,
			'currency': 'USD'}


class FinbotCase(unittest.TestCase):
	"""Base class: self.sent collects ('photo'|'text', ...) tuples for everything the bot tried to send."""

	def patch(self, target, attr, value):
		"""Replace target.attr with value for the rest of the test."""
		p = mock.patch.object(target, attr, value)
		p.start()
		self.addCleanup(p.stop)

	def join_workers(self):
		"""Wait for the worker thread of every update taken so far (bot.dispatch starts one each)."""
		for thread in self.workers:
			thread.join(10)

	def press_button(self, data, chat_id=55, message_id=9):
		"""Press a button under one of the bot's Telegram messages, as the update arrives: bot.take acknowledges it
		(answerCallbackQuery) and hands it to the worker, whose thread this waits for."""
		bot.take(telegram_common.READER, {'callback_query': {'id': 'cb', 'from': {'username': 'u'}, 'data': data,
			'message': {'message_id': message_id, 'chat': {'id': chat_id}}}})
		self.join_workers()

	def env(self, **changes):
		"""Startup settings for this test: config.env with these fields changed."""
		self.patch(config, 'env', dataclasses.replace(config.env, **changes))

	def settings(self, **changes):
		"""Settings for this test: config.settings with these fields changed (what a reload would do)."""
		self.patch(config, 'settings', dataclasses.replace(config.settings, **changes))

	def setUp(self):
		"""A fresh data dir and the offline fixtures: no request leaves the machine, and whatever the bot sends is
		collected in self.sent (and the buttons of each chart in self.markups, error lines in self.errors)."""
		fake = mock.Mock(status_code=200, text='{}')
		fake.json.return_value = {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 5}}}
		self.patch(__import__('requests').Session, 'request', mock.Mock(return_value=fake)) # no real network traffic
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.env(data_dir=tmp.name, cache_dir=tmp.name, telegramBotToken='X',
			telegram_api='https://api.telegram.org/botX/', sharesight_auth={**config.env.sharesight_auth,
			'client_id': 'test'}) # Sharesight set up: its answers are the fixtures below
		self.patch(bot, '_updates_seen', collections.OrderedDict()) # each test starts with no update taken
		self.patch(bot, '_said', {}) # nor any message
		self.patch(bot, 'doubled', lambda message: False) # a test may send the same message twice on purpose
		self.patch(worker, 'repeated', lambda press: False) # or press the same button twice
		self.settings(admin_only=()) # and use any command: AdminOnly closes the gate again
		self.patch(worker, '_presses', collections.OrderedDict()) # each test starts with no press taken
		self.workers = []
		self.patch(bot, 'dispatch', lambda event: self.workers.append(REAL_DISPATCH(event)))
		self.sent = []
		self.markups = [] # reply_markup of each photo sent
		self.errors = []
		self.patch(delivery, 'report_error',
			lambda e, *a, **k: self.errors.append(delivery.error_line(e, k.get('context'))))
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, markup=None:
			self.record_chart(dest, image, caption, markup))
		self.patch(transports.Transport, 'text', lambda dest, lines, markup=None: self.record_text(dest, lines))
		self.patch(watchlist, 'with_holdings', lambda chat: TICKERS)
		self.patch(worker, 'prime_in_background', lambda *args: None) # no thread draws charts behind a test
		self.patch(charts, 'prime_in_background', lambda *args: None)
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
		moved = {t: float(i * 4 - 40) for i, t in enumerate(TICKERS)} # each stock's move over any period
		self.patch(yahoo, 'price_history', lambda t, days=None, quote=None: # a history with no line to draw
			({days: moved.get(t, 1.5)} if days else {'Max': 5, '1Y': 3}, yahoo.Line('Co ' + t, 'NasdaqGS', 'USD', 100.0,
			())))
		self.patch(yahoo, 'prefetch_history', lambda ts: None)
		self.patch(yahoo, 'historic_high', lambda t: (100.0, 50.0))
		today = datetime.date.today() # 400 days of closes, to today: 100, 101, ... 499
		closes = tuple((today - datetime.timedelta(days=399 - i), float(100 + i)) for i in range(400))
		self.patch(yahoo, 'price_series', lambda t: ('Co ' + t, 'NASDAQ', closes))
		self.patch(shortman, 'fetch', lambda md: md)
		held = [{'id': i, 'instrument': {'code': t, 'market_code': 'NASDAQ', 'name': f'Co {t}'},
					 'portfolio': {'name': 'Rob'}, 'capital_gain_percent': str(i * 4 - 40), 'value': '1000'}
					 for i, t in enumerate(TICKERS)]
		self.patch(sharesight, '_portfolios', lambda seconds=None: [{'name': 'Rob', 'id': 1}])
		self.patch(sharesight, '_performance', lambda pid, days=None, seconds=None: {
			'holdings': held, 'currency_gain_percent': '0', 'capital_gain_percent': '2.5', 'total_gain_percent': '0'})
		self.patch(sharesight, '_trades', lambda pid, days=None: [{
			'id': 1, 'transaction_type': 'BUY', 'symbol': 'T1', 'market': 'NASDAQ',
			'transaction_date': time.strftime('%Y-%m-%d'), 'quantity': '10', 'price': '5.0', 'value': '50',
			'brokerage_currency_code': 'USD', 'holding_id': 7}])
		self.typing = [] # every chat a test starts a typing notice in; none may still be sending it when the test ends
		noted = lambda chat: self.typing.append(chat) or REAL_START_TYPING(chat)
		self.patch(transports.Transport, 'start_typing', noted)
		self.addCleanup(self.no_typing_left)

	def record_text(self, dest, lines):
		"""Transport.text in tests: the typing notice stopped, as the real one does, and ('text', lines) noted, unless
		there are none: the real one posts nothing then."""
		dest.stop_typing()
		lines = list(lines)
		if lines:
			self.sent.append(('text', lines))
		return []

	def record_chart(self, dest, image, caption, markup=None):
		"""Transport.chart in tests: the typing notice stopped, as the real one does, and ('photo', size, first caption
		line) noted with its buttons as Telegram gets them."""
		dest.stop_typing()
		image.seek(0)
		self.sent.append(('photo', len(image.read()), caption.split('\n')[0]))
		self.markups.append(telegram_common.TelegramBot.markup(markup) if markup else None)
		return {'ok': True}

	def no_typing_left(self):
		"""Fail the test if a typing notice it started is still being sent, after stopping it."""
		left = [dest for dest in self.typing if dest.is_typing()]
		for dest in left:
			dest.stop_typing()
		self.assertEqual(left, [], 'a typing notice was left running')

	def command(self, text, chat='55'):
		"""Run a chat message through the real command parser and handlers."""
		self.sent.clear()
		self.markups.clear()
		self.errors.clear()
		worker.process_request(inbound.Message('telegram', chat, '@u', text, BOT, 'U'))
		self.assertEqual(self.errors, [], f'{text} crashed') # the worker reports crashes instead of raising
		return list(self.sent)


DOC = os.path.join(ROOT, 'doc')


def sample(*path):
	"""A saved API response from doc/."""
	with open(os.path.join(DOC, *path), encoding='utf-8') as f:
		return json.load(f)


class Resp:
	def __init__(self, payload=None, status=200, text=''):
		"""A response with this JSON payload (None: not JSON), status and text."""
		self.payload, self.status_code, self.text = payload, status, text or json.dumps(payload)
	def json(self):
		"""The payload, or ValueError when it is not JSON."""
		if self.payload is None:
			raise ValueError('no json')
		return self.payload


def serve(*responses):
	"""net.get replacement: replays the responses in order (exceptions are raised); the last one repeats."""
	queue = list(responses)
	calls = []
	def get(url, **kwargs):
		"""The next response, or raise it when it is an exception."""
		calls.append(url)
		item = queue.pop(0) if len(queue) > 1 else queue[0]
		if isinstance(item, Exception):
			raise item
		return item
	get.calls = calls
	return get


REAL_CREDENTIALS = yahoo.credentials


CHART = render.Chart('bars', 'Heading', rows=(('A', 1.0),)) # a chart for the sending tests, which draw it as b'png'


REAL_TOKEN = sharesight._token


class ProviderCase(FinbotCase):
	def setUp(self):
		"""Real parsers instead of the fixture's canned data, with a fixed cookie, crumb and token, and no waiting."""
		super().setUp()
		# these tests exercise the real parsers, so undo the canned data from the base fixture
		for module, name in ((yahoo, 'fetch'), (yahoo, 'fetch_detail'), (yahoo, 'price_series'),
				(sharesight, '_portfolios'), (sharesight, '_trades'), (sharesight, '_performance')):
			self.patch(module, name, REAL[(module.__name__, name)])
		self.patch(yahoo, 'credentials', lambda renew=False: ('A=B', 'crumb'))
		self.patch(sharesight, '_token', lambda: 'token')
		self.patch(sharesight.time, 'sleep', lambda s: None)

	def http(self, module, *responses):
		"""Have module's net.get replay these responses; returns the stand-in, whose calls lists the URLs asked for."""
		getter = serve(*responses)
		self.patch(module.net, 'get', getter)
		return getter


UTC = zoneinfo.ZoneInfo('UTC')

