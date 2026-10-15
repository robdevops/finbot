"""Shared fixture: points finbot at a temp cache dir and replaces every external service
(Telegram, Yahoo, Sharesight, Short Man) with canned data. Nothing here touches the network."""
import collections, dataclasses, io, os, shutil, sys, tempfile, time, unittest
import pandas as pd
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.update(telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok',
	telegramChatID='1')

# first, and once: it monkey-patches with gevent, which must happen before requests imports ssl and never mid-test
import bot
from lib import answer, buttons, cache, charts, config, delivery, dialects, formats, inbound, links, markets, render
from lib import sharesight, shortman, state, telegram, transports, watchlist, worker, yahoo
from lib.reports import about, cal, history, holdings, milestone, performance, price, profile, rankings, rating
from lib.reports import reminder, shorts, trades

REAL = {(m.__name__, n): getattr(m, n) for m, n in ((yahoo, 'fetch'), (yahoo, 'fetch_detail'), (yahoo, 'price_series'),
	(yahoo, 'price_history'), (yahoo, 'historic_high'),
	(sharesight, '_portfolios'), (sharesight, '_trades'), (sharesight, '_performance'))}
REAL_GET_HOLDINGS = watchlist.with_holdings


def bare_environment():
	"""os.environ without finbot's settings (the startup keys, the preferences, the flag that hands a job its
	preferences): for a process that must start from the defaults."""
	settings = {*config.STARTUP_KEYS, *config.PREFERENCE_KEYS, config.PASSED}
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
BOT = '@bot'


def wsgi_environ(path, body, **headers):
	"""A WSGI environ posting `body` (bytes) to `path`, with these headers (as HTTP_* keys)."""
	return {'PATH_INFO': path, 'wsgi.input': io.BytesIO(body), 'CONTENT_LENGTH': str(len(body)), **headers}


def skip_if_old_env(case):
	"""Skip a test that starts bot.py while the checkout has a leftover .env (config.check_startup_environment)."""
	if config.OLD_ENV.exists():
		case.skipTest(f'bot.py will not start while {config.OLD_ENV} exists')


STATES = ('REGULAR', 'PRE', 'POST', 'CLOSED')


def market_entry(ticker):
	"""A Yahoo quote for a fixture ticker; T0 to T24 vary in market state, move, rating and so on, so that every
	threshold, sort and branch has rows."""
	i = int(ticker[1:]) if ticker[1:].isdigit() else 0 # varied data so threshold/sort/sell branches all have rows
	return {'marketState': STATES[i % 4], 'regularMarketTime': time.time(), 'quoteType': 'EQUITY',
			'profile_title': 'Co ' + ticker, 'profile_exchange': 'NasdaqGS', 'percent_change': (i - 12) * 1.5,
			'percent_change_premarket': (i - 12) * 1.5, 'percent_change_postmarket': (i - 12) * 1.5,
			'market_cap': 1e9, 'price_to_earnings_trailing': 9, 'price_to_earnings_forward': 9,
			'beta': 2.0, 'short_percent': 20, 'fiftyTwoWeekHigh': 120.0, 'fiftyTwoWeekLow': 80.0,
			'regularMarketPrice': 100.0, 'earnings_date': time.time() + 86400 * 3,
			'ex_dividend_date': time.time() + 86400 * 3, 'recommend': 'buy' if i % 2 else 'sell',
			'recommend_index': 1.2 if i % 2 else 4.2, 'recommend_analysts': 8, 'price_to_earnings_peg': 1.2,
			'currency': 'USD'}


class FinbotCase(unittest.TestCase):
	"""Base class: self.sent collects ('photo'|'text', ...) tuples for everything the bot tried to send."""

	def patch(self, target, attr, value):
		"""Replace target.attr with value for the rest of the test."""
		p = mock.patch.object(target, attr, value)
		p.start()
		self.addCleanup(p.stop)

	def env(self, **changes):
		"""Startup settings for this test: config.env with these fields changed."""
		self.patch(config, 'env', dataclasses.replace(config.env, **changes))

	def prefs(self, **changes):
		"""Preferences for this test: config.prefs with these fields changed (what a reload would do)."""
		self.patch(config, 'prefs', dataclasses.replace(config.prefs, **changes))

	def setUp(self):
		"""A fresh data dir and the offline fixtures: no request leaves the machine, and whatever the bot sends is
		collected in self.sent (and the buttons of each chart in self.markups, error lines in self.errors)."""
		fake = mock.Mock(status_code=200, text='{}')
		fake.json.return_value = {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 5}}}
		self.patch(__import__('requests').Session, 'request', mock.Mock(return_value=fake)) # no real network traffic
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.env(data_dir=tmp.name, cache_dir=tmp.name, webhooks={'telegram': 'https://api.telegram.org/botX/'})
		self.patch(bot, '_updates_seen', collections.OrderedDict()) # each test starts with no update taken
		self.sent = []
		self.markups = [] # reply_markup of each photo sent
		self.errors = []
		self.patch(delivery, 'report_error',
			lambda e, *a, **k: self.errors.append(delivery.error_line(e, k.get('context'))))
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, markup=None:
			self.record_chart(dest, image, caption, markup))
		self.patch(transports.Transport, 'text', lambda dest, lines, markup=None: self.record_text(dest, lines))
		self.patch(watchlist, 'with_holdings', lambda: TICKERS)
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
		self.patch(yahoo, 'price_history', lambda t, days=None, quote=None: # a history with no line to draw
			({days: 1.5} if days else {'Max': 5, '1Y': 3}, yahoo.Line('Co ' + t, 'NasdaqGS', 'USD', 100.0, ())))
		self.patch(yahoo, 'prefetch_history', lambda ts: None)
		self.patch(yahoo, 'historic_high', lambda t: (100.0, 50.0))
		dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=400)
		self.patch(yahoo, 'price_series',
			lambda t: ('Co ' + t, 'NASDAQ', pd.Series(range(100, 500), index=dates, name=t, dtype=float)))
		self.patch(shortman, 'fetch', lambda md: md)
		held = [{'id': i, 'instrument': {'code': t, 'market_code': 'NASDAQ'}, 'portfolio': {'name': 'Rob'},
					 'capital_gain_percent': str(i * 4 - 40), 'value': '1000'} for i, t in enumerate(TICKERS)]
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
		self.markups.append(transports.TelegramBot.markup(markup) if markup else None)
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
