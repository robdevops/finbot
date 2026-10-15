"""Yahoo, Sharesight and Telegram parsing and failure handling, driven by the real API responses saved under doc/.
HTTP is mocked at lib.net, so the production parsing code runs unchanged."""
import contextlib, copy, datetime, io, json, os, subprocess, unittest
import gevent
from unittest import mock
from tests.common import *

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


class ProviderCase(FinbotCase):
	def setUp(self):
		"""The real parsers in place of the fixture's canned data, with a fixed cookie, crumb and token, and no
		waiting."""
		super().setUp()
		# these tests exercise the real parsers, so undo the canned data from the base fixture
		for module, name in ((yahoo, 'fetch'), (yahoo, 'fetch_detail'), (yahoo, 'price_series'), (sharesight, 'get_portfolios'),
							 (sharesight, 'get_trades'), (sharesight, 'get_performance')):
			self.patch(module, name, REAL[(module.__name__, name)])
		self.patch(yahoo, 'getCookie', lambda *a, **k: 'A=B')
		self.patch(yahoo, 'getCrumb', lambda *a, **k: 'crumb')
		self.patch(sharesight, 'get_token', lambda: 'token')
		self.patch(sharesight.time, 'sleep', lambda s: None)

	def http(self, module, *responses):
		"""Have module's net.get replay these responses; returns the replacement, whose calls lists the URLs asked
		for."""
		getter = serve(*responses)
		self.patch(module.net, 'get', getter)
		return getter


class YahooQuotes(ProviderCase):
	def test_parses_real_v7_quote(self):
		"""A real v7 quote parses into finbot's fields."""
		self.http(yahoo, Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		data = yahoo.fetch(['AAPL'])['AAPL']
		self.assertEqual(data['profile_title'], 'Apple')
		self.assertEqual(data['percent_change'], 0.09)
		self.assertEqual(data['percent_change_postmarket'], -0.13)
		self.assertEqual(data['quoteType'], 'EQUITY')
		self.assertEqual(data['marketState'], 'CLOSED')
		self.assertEqual(data['profile_exchange'], 'NasdaqGS')
		self.assertEqual(data['exchangeTimezoneName'], 'America/New_York')
		self.assertGreater(data['market_cap'], 1e12)

	def test_second_call_is_served_from_cache(self):
		"""A second fetch of the same ticker comes from the cache."""
		getter = self.http(yahoo, Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		yahoo.fetch(['AAPL'])
		yahoo.fetch(['AAPL'])
		self.assertEqual(len(getter.calls), 1)

	def test_falls_back_to_second_host(self):
		"""When the first Yahoo host fails, the second is asked."""
		getter = self.http(yahoo, Resp(status=500), Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		self.assertIn('AAPL', yahoo.fetch(['AAPL']))
		self.assertIn('query1', getter.calls[1])

	def test_all_hosts_failing_raises(self):
		"""Every host failing, or Yahoo unreachable, is a RuntimeError."""
		for failure in (Resp(status=500), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				with self.assertRaises(RuntimeError):
					yahoo.fetch(['AAPL'])

	def test_empty_result_is_none(self):
		"""An empty result is no quotes."""
		self.http(yahoo, Resp({'quoteResponse': {'result': None, 'error': {'code': 'x'}}}))
		self.assertEqual(yahoo.fetch(['NOPE']), {})

	def test_no_tickers_is_none(self):
		"""No tickers asked for: no quotes, and no request."""
		self.assertEqual(yahoo.fetch([]), {})

	def test_incomplete_quotes_are_skipped(self):
		"""A quote without a price or a name is left out."""
		body = sample('yahoo', 'sample_yahoo_v7.json')
		good = body['quoteResponse']['result'][0]
		no_price = {k: v for k, v in good.items() if k != 'regularMarketPrice'} | {'symbol': 'NOPRICE'}
		no_name = {k: v for k, v in good.items() if k not in ('longName', 'shortName')} | {'symbol': 'NONAME'}
		body['quoteResponse']['result'] = [good, no_price, no_name]
		self.http(yahoo, Resp(body))
		self.assertEqual(list(yahoo.fetch(['AAPL', 'NOPRICE', 'NONAME'])), ['AAPL'])


class YahooDetail(ProviderCase):
	@staticmethod
	def combined():
		"""quoteSummary as Yahoo returns it for several modules at once, assembled from the per-module samples."""
		merged = {}
		for module in ('price', 'summaryProfile', 'summaryDetail', 'defaultKeyStatistics', 'financialData', 'calendarEvents', 'earnings'):
			merged.update(sample('yahoo', f'sample_yahoo_v10_{module}.json')['quoteSummary']['result'][0])
		return {'quoteSummary': {'result': [merged], 'error': None}}

	def test_parses_real_quote_summary(self):
		"""A real quoteSummary parses, the company's description included."""
		self.http(yahoo, Resp(self.combined()))
		data = yahoo.fetch_detail('NVDA')['NVDA']
		self.assertEqual(data['profile_title'], 'NVIDIA')
		self.assertTrue(data['profile_bio'])

	def test_a_cached_detail_needs_no_cookie(self):
		"""A detail served from the cache takes neither the cookie nor the crumb, nor their lock."""
		self.http(yahoo, Resp(self.combined()))
		yahoo.fetch_detail('NVDA')
		def refuse():
			"""Fail: the credentials must not be needed."""
			raise AssertionError('a cached detail took the Yahoo auth lock')
		self.patch(yahoo, 'credentials', refuse)
		self.assertIn('NVDA', yahoo.fetch_detail('NVDA'))

	def test_http_failure_gives_empty(self):
		"""A detail Yahoo will not give (404, unreachable) is empty, not an error."""
		for failure in (Resp(status=404), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				self.assertEqual(yahoo.fetch_detail('DRNA'), {})

	def test_missing_names_give_empty(self):
		"""A detail without a name, or without a result, is empty."""
		body = self.combined()
		body['quoteSummary']['result'][0]['price'].update(longName=None, shortName=None)
		self.http(yahoo, Resp(body))
		self.assertEqual(yahoo.fetch_detail('DUB'), {})
		self.http(yahoo, Resp({'quoteSummary': {'result': None, 'error': {}}}))
		self.assertEqual(yahoo.fetch_detail('GONE'), {})


class YahooChart(ProviderCase):
	def test_real_chart_to_dataframe_and_basics(self):
		"""A real v8 chart becomes a frame of dates and closes, and its basics are read."""
		chart = sample('yahoo', 'sample_yahoo_v8_chart.json')
		df = yahoo.chart_json_to_df(chart)
		self.assertEqual(len(df), 2)
		self.assertTrue({'Date', 'Close'} <= set(df.columns))
		basics = yahoo.chart_json_to_stock_basics(chart)
		self.assertEqual((basics['symbol'], basics['currency']), ('CRWD', 'USD'))

	def test_fetch_chart_json_failures_raise(self):
		"""A chart Yahoo will not give is a RuntimeError."""
		for failure in (Resp(status=404), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				with self.assertRaises(RuntimeError):
					yahoo.fetch_chart_json('AAPL', full=True)

	@staticmethod
	def chart(closes, failing=()):
		"""A v8 chart response with one daily bar per close, the last one today (14:30 UTC, New York's open)."""
		today = datetime.datetime.now(datetime.timezone.utc).replace(hour=14, minute=30, second=0, microsecond=0)
		stamps = [int((today - datetime.timedelta(days=len(closes) - 1 - i)).timestamp()) for i in range(len(closes))]
		meta = {'currency': 'USD', 'symbol': 'T1', 'exchangeTimezoneName': 'America/New_York', 'regularMarketTime': stamps[-1],
				'regularMarketPrice': closes[-1], 'longName': 'Co T1'}
		quote = {'open': closes, 'high': closes, 'low': closes, 'close': closes, 'volume': [1] * len(closes)}
		return {'chart': {'result': [{'meta': meta, 'timestamp': stamps, 'indicators': {'quote': [quote]}}], 'error': None}}

	def test_1d_is_the_change_since_the_previous_close(self):
		"""1D is the change since the previous close, and 5D the week's."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		self.http(yahoo, Resp(self.chart([90] * 30 + [100, 105, 110, 115, 120, 116.4]))) # up 20% in a week, down 3% today
		table, image = yahoo.price_history('T1', graph=False)
		self.assertEqual(table['1D'], -3)
		self.assertGreater(table['5D'], 10) # the week, not the day

	def test_a_failed_chart_fetch_raises(self):
		"""A chart refused (429) or unreachable is a RuntimeError, which callers turn into leaving the ticker out."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		for failure in (Resp(status=429), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				with self.assertRaises(RuntimeError):
					yahoo.price_history('AAPL', 7, graph=False)

	def test_one_failed_ticker_does_not_take_the_report_down(self):
		"""One ticker without a chart is left out of a price list, a benchmark without one is said to have none, and
		only a report on that one ticker fails, in one line."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts}) # quotes as canned in the base fixture, charts over HTTP
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
		self.patch(sharesight, 'get_portfolios', lambda: {}) # no Sharesight figures: every ticker needs its history
		good = Resp(self.chart([100.0] * 20 + [110.0]))
		def get(url, **kwargs):
			"""A chart for every ticker but T3 and SPY, which get 404."""
			return Resp(status=404) if '/chart/T3?' in url or '/chart/SPY?' in url else good
		self.patch(yahoo.net, 'get', get)
		def slack(text):
			"""Run a command on Slack, where reports come as text, and return the text."""
			self.sent.clear(); self.errors.clear()
			worker.process_request('slack', 'C1', '<@U1>', text, BOT, 'U')
			self.assertEqual(self.errors, [], text)
			return '\n'.join(map(str, self.sent[-1][1]))
		price_list = slack('.price 7d') # T3 is left out, the rest are listed
		self.assertNotIn('Co T3 (', price_list)
		self.assertIn('Co T4 (', price_list)
		self.patch(sharesight, 'get_portfolios', lambda: {'Rob': 1})
		self.patch(sharesight, 'get_performance', lambda pid, d, *a: {'report': {'holdings': [{'portfolio': {'name': 'Rob'}}],
			'currency_gain_percent': '0', 'capital_gain_percent': '2.5', 'total_gain_percent': '0'}})
		report = slack('.performance 7d') # the S&P 500 benchmark has no history
		self.assertIn('⚠️ S&P 500: no price history', report)
		self.assertIn('NASDAQ 100', report)
		self.command('.T3') # the profile goes out without its history lines
		self.sent.clear(); self.errors.clear()
		worker.process_request('telegram', '55', '@u', '.price T3 7d', BOT, 'U')
		self.assertEqual(len(self.errors), 1) # the one ticker asked for: one line saying why
		self.assertTrue(self.errors[0].startswith('⚠️ .price: RuntimeError: 404 error for T3'))

	def test_the_chart_request_carries_the_cookie_of_its_crumb(self):
		"""A chart request sends the cookie its crumb belongs to."""
		headers = []
		self.patch(yahoo.net, 'get', lambda url, **kwargs: headers.append(kwargs.get('headers', {})) or Resp(self.chart([100.0] * 5)))
		yahoo.fetch_chart_json('T1', full=True)
		self.assertEqual(headers[0].get('Cookie'), 'A=B') # the crumb used to go without its cookie

	def test_with_the_cache_off_no_chart_is_written(self):
		"""With the cache preference off, a drawn chart is not written to the cache."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		self.prefs(cache=False)

		self.http(yahoo, Resp(self.chart([100.0] * 30 + [110.0])))
		table, image = yahoo.price_history('T1', 7, graph=True)
		self.assertIsNotNone(image)
		self.assertEqual([name for name in os.listdir(config.env.cache_dir) if name.startswith('finbot_graph_')], [])

	def test_price_series_raises_on_failure_and_on_empty_history(self):
		"""price_series raises when Yahoo fails and when the history has no closes."""
		self.http(yahoo, Resp(status=500))
		with self.assertRaises(RuntimeError):
			yahoo.price_series('AAPL')
		empty = sample('yahoo', 'sample_yahoo_v8_chart.json')
		empty['chart']['result'][0]['indicators']['quote'][0]['close'] = [None, None]
		self.http(yahoo, Resp(empty))
		with self.assertRaises(RuntimeError):
			yahoo.price_series('EMPTY')


class SharesightApi(ProviderCase):
	def test_portfolios_from_real_response(self):
		"""The portfolio list parses from a real answer."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141})

	def test_portfolio_exclusion_and_inclusion(self):
		"""exclude_portfolios and include_portfolios pick the portfolios reported on."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.prefs(exclude_portfolios=['445825'])

		self.assertEqual(sharesight.get_portfolios(), {'RobSMSF': 684141})
		self.prefs(exclude_portfolios=[])

		self.prefs(include_portfolios=['445825'])

		self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825})

	def test_portfolio_failures_raise(self):
		"""An error answer, Sharesight unreachable or no portfolios is a RuntimeError."""
		for failure in (Resp({'error': 'nope', 'error_code': 'x'}, 401), ConnectionError('down'), Resp({'portfolios': []})):
			with self.subTest(failure=failure):
				self.http(sharesight, failure)
				with self.assertRaises(RuntimeError):
					sharesight.get_portfolios()

	def test_trades_from_real_response(self):
		"""Trades parse from a real answer, tagged with their portfolio."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_trades_684141_1.json')))
		trades = sharesight.get_trades('RobSMSF', 684141, 1)
		self.assertEqual(len(trades), 2)
		self.assertEqual(trades[0]['portfolio'], 'RobSMSF')
		self.assertEqual(trades[0]['symbol'], 'FANG')

	def test_trade_failures_raise(self):
		"""Sharesight unreachable, or an error answer, is a RuntimeError."""
		self.http(sharesight, ConnectionError('down'))
		with self.assertRaises(RuntimeError):
			sharesight.get_trades('RobSMSF', 684141, 1)
		self.http(sharesight, Resp({'trades': [], 'error': 'bad', 'error_code': 'x'}, 400))
		with self.assertRaises(RuntimeError):
			sharesight.get_trades('RobSMSF', 684141, 2)

	def test_performance_and_holdings_from_real_response(self):
		"""A real holdings report parses, and its tickers come out sorted, US ones without a suffix."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
		self.assertEqual(len(sharesight.get_performance(684141, 0)['report']['holdings']), 18)
		tickers = sharesight.Portfolio('RobSMSF', 684141).tickers()
		self.assertIn('ARM', tickers) # US venues carry no Yahoo suffix
		self.assertEqual(tickers, sorted(tickers))

	def test_performance_retries_when_sharesight_is_busy(self):
		"""While Sharesight says too many requests are in flight, the request is tried again."""
		busy = Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429)
		getter = self.http(sharesight, busy, busy, Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
		self.assertIn('report', sharesight.get_performance(684141, 0))
		self.assertEqual(len(getter.calls), 3)

	def test_performance_gives_up_after_repeated_busy_or_hard_errors(self):
		"""Busy every time, a hard error, or unreachable: a RuntimeError in the end."""
		for failure in (Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429),
						Resp({'error': 'forbidden', 'error_code': 'x'}, 403), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(sharesight, failure)
				with self.assertRaises(RuntimeError):
					sharesight.get_performance(684141, 7)

	def test_an_answer_without_a_report_says_so(self):
		"""A performance answer without a report is an error naming the portfolio, and is not cached."""
		self.http(sharesight, Resp({}))
		with self.assertRaisesRegex(RuntimeError, 'no performance report for portfolio 684141'):
			sharesight.get_performance(684141, 7)
		self.assertIsNone(cache.read(sharesight.performance_cache_file(684141, 7))) # and is not cached


class SharesightKeepWarm(ProviderCase):
	"""The background refresher keeps the portfolio list and the holdings report (days=0) cached ahead of their TTLs."""

	def serve_sharesight(self):
		"""Answer with the real portfolio list and holdings report; returns the URLs asked for."""
		portfolios = sample('sharesight', 'finbot_sharesight_portfolios.json')
		performance = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
		calls = []
		def get(url, **kwargs):
			"""The holdings report or the portfolio list, as asked."""
			calls.append(url)
			return Resp(performance if '/performance' in url else portfolios)
		self.patch(sharesight.net, 'get', get)
		return calls

	def age(self, cache_file, seconds):
		"""Make a cache file `seconds` older."""
		path = os.path.join(config.env.cache_dir, cache_file)
		old = os.path.getmtime(path) - seconds
		os.utime(path, (old, old))

	def test_cold_cache_is_filled_then_left_alone(self):
		"""A cold cache is filled (the list and each portfolio's holdings, as of today), then left alone while fresh."""
		calls = self.serve_sharesight()
		self.assertEqual(sharesight.warm()[0], 3) # portfolio list + one holdings report per portfolio (2)
		self.assertEqual(sum('/performance' in c for c in calls), 2)
		self.assertTrue(all('start_date=' + datetime.date.today().isoformat() in c for c in calls if '/performance' in c)) # days=0
		self.assertEqual(sharesight.warm()[0], 0)
		self.assertEqual(len(calls), 3) # nothing refetched while fresh

	def test_refreshes_before_the_ttl_runs_out(self):
		"""A cache file at 95% of its lifetime is fetched again, and only that one."""
		calls = self.serve_sharesight()
		sharesight.warm()[0]
		calls.clear()
		self.age(sharesight.performance_cache_file(684141, 0), 0.95 * config.prefs.performance_cache_seconds) # 95% of its lifetime
		self.assertEqual(sharesight.warm()[0], 1)
		self.assertEqual(len(calls), 1)
		self.assertIn('684141/performance', calls[0])
		calls.clear()
		self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * config.prefs.cache_seconds)
		self.assertEqual(sharesight.warm()[0], 1)
		self.assertTrue(calls[0].endswith('/portfolios'))

	def test_a_request_never_waits_on_a_cache_the_job_has_warmed(self):
		"""Once warmed, the list and the holdings report need no request."""
		calls = self.serve_sharesight()
		sharesight.warm()[0]
		calls.clear()
		self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141})
		self.assertEqual(len(sharesight.get_performance(684141, 0)['report']['holdings']), 18)
		self.assertEqual(calls, [])

	def test_every_holding_is_served_from_the_warmed_cache(self):
		"""Every portfolio's tickers come from the warmed cache, with no request."""
		calls = self.serve_sharesight()
		sharesight.warm()[0]
		calls.clear()
		tickers = sharesight.tickers() # the portfolio list and each portfolio's holdings report, no cache of its own
		self.assertIn('ARM', tickers)
		self.assertEqual(calls, [])

	def test_failed_refresh_keeps_the_old_cache(self):
		"""A refresh that fails keeps the cache it would have replaced."""
		self.serve_sharesight()
		sharesight.warm()[0]
		self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * config.prefs.cache_seconds)
		self.http(sharesight, ConnectionError('down'))
		with self.assertRaises(RuntimeError):
			sharesight.warm()[0]
		self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141}) # still served from the cache

	def test_loop_survives_failures_and_backs_off(self):
		"""keep_warm survives a failure, retries slowly, then sleeps until the next cache is due."""
		class Stop:
			"""keep_warm's stop event: notes each wait, and is set after two."""
			def __init__(self):
				"""No waits yet."""
				self.waits = []
			def is_set(self):
				"""Set after two waits."""
				return len(self.waits) >= 2
			def wait(self, seconds):
				"""Note the wait instead of sleeping."""
				self.waits.append(seconds)
		outcomes = [RuntimeError('boom'), 0]
		def warm():
			"""Fail once, then succeed."""
			outcome = outcomes.pop(0)
			if isinstance(outcome, Exception):
				raise outcome
			return outcome, {}
		self.patch(sharesight, 'warm', warm)
		self.patch(sharesight, 'next_due', lambda portfolios=None: 3000)
		stop = Stop()
		sharesight.keep_warm(retry=300, stop=stop)
		self.assertEqual(stop.waits, [300, 3000]) # slow retry after the failure, then sleep until the next cache is due

	def test_with_cache_off_nothing_is_fetched_until_a_reload_turns_it_on(self):
		"""With the cache preference off, keep_warm idles without asking Sharesight, and starts when a reload turns it
		on."""
		class Stop:
			"""keep_warm's stop event: notes each wait, switches the cache on at the second, and is set after four."""
			def __init__(self):
				"""No waits yet."""
				self.waits = []
			def is_set(self):
				"""Set after four waits."""
				return len(self.waits) >= 4
			def wait(self, seconds):
				"""Note the wait; at the second, switch the cache on as a reload would."""
				self.waits.append(seconds)
				if len(self.waits) == 2:
					config.prefs = dataclasses.replace(config.prefs, cache=True) # what a reload that switches it on does
		passes = []
		self.patch(sharesight, 'warm', lambda: (passes.append(1), (0, {}))[1])
		self.patch(sharesight, 'next_due', lambda portfolios=None: 3000)
		self.prefs(cache=False)

		stop = Stop()
		sharesight.keep_warm(idle=60, stop=stop)
		self.assertEqual((stop.waits, len(passes)), ([60, 60, 3000, 3000], 2)) # idle while off: no Sharesight request every 5 seconds

	def test_a_flush_wakes_the_loop_to_refill_at_once(self):
		"""A flush wakes keep_warm, which refills the caches at once instead of when they are next due."""
		passes = []
		self.patch(sharesight, 'warm', lambda: (passes.append(1), (0, {}))[1])
		self.patch(sharesight, 'next_due', lambda portfolios=None: 3000)
		loop = gevent.spawn(sharesight.keep_warm)
		self.addCleanup(loop.kill)
		gevent.sleep(0.05)
		self.assertEqual(len(passes), 1) # then it sleeps until the next cache is due, 50 minutes away
		sharesight.wake()
		gevent.sleep(0.05)
		self.assertEqual(len(passes), 2)

	def test_a_warming_pass_reads_the_cached_portfolio_list_once(self):
		"""One pass of keep_warm reads the cached portfolio list once, and hands it on."""
		self.serve_sharesight()
		sharesight.warm()[0] # fill the caches
		reads = []
		real = cache.read
		self.patch(cache, 'read', lambda name, *a, **k: (reads.append(name), real(name, *a, **k))[1])
		fetched, portfolios = sharesight.warm() # what one pass of keep_warm does
		due = sharesight.next_due(portfolios=portfolios)
		self.assertEqual((fetched, reads), (0, [sharesight.PORTFOLIOS_CACHE]))
		self.assertAlmostEqual(due, sharesight.next_due(), delta=1) # the same answer as reading the list again
		self.assertEqual(portfolios, {'Rob': 445825, 'RobSMSF': 684141})

	def test_next_due_is_90_percent_of_the_ttl(self):
		"""The next refresh is due at 90% of the shortest cache lifetime; at once for a cold cache."""
		self.serve_sharesight()
		self.assertEqual(sharesight.next_due(), 0) # cold cache
		sharesight.warm()[0]
		due = sharesight.next_due()
		self.assertAlmostEqual(due, 0.9 * min(config.prefs.cache_seconds, config.prefs.performance_cache_seconds), delta=5)

	def test_refresh_flag_bypasses_a_fresh_cache(self):
		"""refresh=True asks Sharesight even while the cache is fresh."""
		calls = self.serve_sharesight()
		sharesight.get_portfolios()
		sharesight.get_portfolios()
		self.assertEqual(len(calls), 1)
		sharesight.get_portfolios(refresh=True)
		self.assertEqual(len(calls), 2)


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

	def test_success_returns_json(self):
		"""A sent message returns Telegram's answer."""
		self.assertEqual(self.post(Resp({'ok': True})), {'ok': True})

	def test_http_error_and_exception_return_none(self):
		"""A refused or failed send returns None."""
		self.assertIsNone(self.post(Resp(status=429)))
		self.assertIsNone(self.post(ConnectionError('down')))

	def test_non_json_success_returns_empty_dict(self):
		"""A 200 that is not JSON returns {}."""
		self.assertEqual(self.post(Resp(None)), {})

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
		for kind in (transports.TelegramBot, transports.SlackWebhook, transports.DiscordWebhook):
			self.patch(kind, 'post_text', lambda dest, text, buttons=None: sent.append((dest.name, text)))
		self.env(webhooks={'telegram': 'https://api.telegram.org/botX/', 'slack': 'https://hooks.slack.com/x', 'discord': 'https://discord.com/x/slack'})
		self.env(telegramChatID='5')

		error = RuntimeError("404 for ZZ at https://x/?a=1&crumb=abc; '<' not supported between <urllib3.connection>")
		with contextlib.redirect_stderr(io.StringIO()):
			REAL_REPORT_ERROR(error, context='.compare <b>')
			REAL_REPORT_ERROR(error, service='telegram', chat_id='55', context='.compare')
		texts = dict(sent[:3])
		self.assertIn('crumb=&lt;redacted&gt;', texts['telegram']) # Telegram's HTML parser rejects a bare <redacted>
		self.assertNotIn('<', texts['telegram'] + sent[3][1])
		self.assertIn('.compare &lt;b&gt;: RuntimeError', texts['telegram'])
		self.assertEqual(texts['slack'], texts['telegram'])
		self.assertIn('crumb=<redacted>', texts['discord'])

	def test_report_error_never_raises(self):
		"""report_error survives a failed send."""
		self.patch(transports.TelegramBot, 'post_text', mock.Mock(side_effect=RuntimeError('send failed')))
		delivery.report_error(ValueError('boom'), service='telegram', chat_id='5')
		delivery.report_error(ValueError('boom'))

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
	"""Charts go to Telegram, and to Slack in replies (uploaded into the channel). A report whose chart cannot be sent goes out as
	text instead of vanishing."""
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
		return [Resp({'ok': True, 'upload_url': self.UPLOAD_URL, 'file_id': 'F1'}), Resp(None, text='OK - 3'), Resp({'ok': True, 'files': [{'id': 'F1'}]})]

	def test_where_charts_can_go(self):
		"""Charts go to Telegram and Discord always, to Slack in replies with the bot token, never in Slack's scheduled
		reports."""
		self.env(slackBotToken='xoxb-test')

		cases = (('telegram',), ('telegram', False), ('slack',), ('slack', False), ('discord', False))
		charted = [delivery.takes_charts(*case) for case in cases]
		self.assertEqual(charted, [True, True, True, False, True]) # Slack: replies, not scheduled reports
		self.env(slackBotToken=False)

		self.assertFalse(delivery.takes_charts('slack'))

	def test_slack_replies_upload_their_charts(self):
		"""A Slack reply uploads its chart in three steps with the bot token, the report as its message, not sent again
		as text."""
		self.env(slackBotToken='xoxb-test')

		for cmd, heading in (('.beta', '*Beta over 1.5'), ('.price', '*5% at close'), ('.compare T1 T2', '*')):
			with self.subTest(cmd=cmd):
				calls = self.slack_answers(*self.upload_steps())
				self.sent.clear(); self.errors.clear()
				worker.process_request('slack', 'C1', '<@U1>', cmd, BOT, 'U')
				self.assertEqual(self.errors, [])
				self.assertEqual([url for url, _ in calls], ['https://slack.com/api/files.getUploadURLExternal', self.UPLOAD_URL,
															 'https://slack.com/api/files.completeUploadExternal'])
				(_, ticket), (_, upload), (_, share) = calls
				self.assertEqual(ticket['headers'], {'Authorization': 'Bearer xoxb-test'})
				self.assertTrue(upload['data'].startswith(b'\x89PNG')) # the chart's bytes, as the body
				self.assertEqual((ticket['data']['filename'], ticket['data']['length']), ('chart.png', len(upload['data'])))
				self.assertEqual((share['data']['channel_id'], json.loads(share['data']['files'])), ('C1', [{'id': 'F1'}]))
				self.assertTrue(share['data']['initial_comment'].startswith(heading), share['data']['initial_comment'][:80]) # the report
				self.assertNotIn(share['data']['initial_comment'].split('\n'), [payload for _, payload in self.sent]) # not sent again as text

	def test_a_slack_upload_that_fails_goes_out_as_text(self):
		"""A Slack upload that fails at any step goes out as text, but not after a timeout on the last step, when it may
		have arrived."""
		self.env(slackBotToken='xoxb-test')

		good = self.upload_steps()
		slow = transports.requests.exceptions.ReadTimeout('slow')
		text = [('text', ['*Heading*', 'line 2'])]
		for outcomes, expect in (([Resp({'ok': False, 'error': 'missing_scope'})], text), ([ConnectionError('down')], text),
								 ([good[0], Resp(None, status=500, text='nope')], text),
								 ([good[0], good[1], Resp({'ok': False, 'error': 'not_in_channel'})], text),
								 ([good[0], good[1], slow], []), # it may have been shared after all
								 (good, [])):
			with self.subTest(outcomes=outcomes):
				self.slack_answers(*outcomes)
				self.sent.clear()
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					report = delivery.Report(['*Heading*', 'line 2'], io.BytesIO(b'png'))
					delivery.deliver(transports.SlackBot('C1'), report)
				self.assertEqual(self.sent, expect)

	def test_scheduled_reports_to_slack_stay_text(self):
		"""Scheduled reports reach Slack's incoming webhook as text and Telegram with their charts."""
		self.env(slackBotToken='xoxb-test')

		self.env(webhooks={**config.env.webhooks, 'slack': 'https://hooks.slack.com/services/x'}) # an incoming webhook cannot upload
		sent = []
		self.patch(transports.Transport, 'chart', lambda dest, image, caption, buttons=None:
			sent.append((dest.name, 'chart')) or {'ok': True})
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None:
			sent.append((dest.name, 'text')) or [])
		for report in (price.lambda_handler, lambda: performance.lambda_handler(past_days=7), shorts.lambda_handler):
			with self.subTest(report=report):
				sent.clear()
				report()
				self.assertEqual(sorted(set(sent)), [('slack', 'text'), ('telegram', 'chart')])

	def test_slack_without_a_bot_token_gets_text_and_no_chart_is_drawn(self):
		"""Without the bot token, Slack replies are text and no chart is drawn for them."""
		self.env(slackBotToken=False)

		def refuse(*a, **k):
			"""Fail: no chart should be drawn."""
			raise AssertionError('a chart was drawn for Slack')
		for name in ('rows_chart', 'pie_chart', 'bar_graph', 'shorts_chart'):
			self.patch(render, name, refuse)
		self.env(webhooks={**config.env.webhooks, 'slack': 'https://hooks.slack.com/services/x'})
		for cmd in ('.beta', '.pie Rob', '.buy', '.sell', '.peg', '.price', '.price top', '.price T1 7d', '.performance 7d', '.shorts', '.history T1', '.compare T1 T2'):
			with self.subTest(cmd=cmd):
				self.sent.clear(); self.errors.clear()
				worker.process_request('slack', 'C1', '<@U1>', cmd, BOT, 'U')
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
			for cmd in ('.price', '.price top', '.performance 7d', '.shorts', '.buy', '.peg', '.beta', '.compare T1 T2', '.pie Rob'):
				with self.subTest(service=service, cmd=cmd):
					self.sent.clear(); self.errors.clear()
					worker.process_request(service, chat, '@u', cmd, BOT, 'U')
					self.assertEqual(self.errors, [])
					self.assertEqual({kind for kind, *_ in self.sent}, {'text'})
		self.assertEqual([url for url in posts if 'sendPhoto' in url or 'files.' in url], [])

	def test_a_chart_telegram_refuses_goes_out_as_text(self):
		"""A chart Telegram refuses or that fails goes out as text, but not after a timeout, when it may have
		arrived."""
		def post(outcome):
			"""A net.post that answers with outcome, or raises it."""
			def fake(url, **kwargs):
				"""The outcome, or raise it."""
				if isinstance(outcome, Exception):
					raise outcome
				return outcome
			return fake
		text = [('text', ['Heading', 'line 2'])]
		for outcome, expect in ((Resp({'ok': False, 'error_code': 400, 'description': "Bad Request: can't parse entities"}, status=400), text),
								(Resp(None, status=502), text), (ConnectionError('down'), text),
								(transports.requests.exceptions.ReadTimeout('slow'), []), # it may be there
								(Resp({'ok': True, 'result': {'message_id': 1}}), [])):
			with self.subTest(outcome=outcome):
				self.sent.clear()
				self.patch(transports.net, 'post', post(outcome))
				with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
					report = delivery.Report(['Heading', 'line 2'], io.BytesIO(b'png'), [[]])
					delivery.deliver(transports.TelegramBot('5'), report)
				self.assertEqual(self.sent, expect)


class DiscordWebhook(FinbotCase):
	"""Discord's own webhook endpoint (the Slack-compatible one takes no flags): no link previews, no pings, charts attached."""
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
		"""A scheduled report goes to Discord with its chart attached and the report, within 2,000 characters, as the
		message."""
		price.lambda_handler()
		(url, kwargs), = self.posts
		self.assertEqual(url, self.URL + '?wait=true')
		payload = json.loads(kwargs['data']['payload_json'])
		self.assertEqual((payload['flags'], payload['allowed_mentions'], payload['attachments'][0]['filename']), (4, {'parse': []}, 'chart.png'))
		self.assertTrue(payload['content'].startswith('**5% at close'), payload['content'][:60])
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
		self.assertEqual(len(self.posts), 2)
		for url, kwargs in self.posts:
			with self.subTest(url=url): # they used to go in the headers, where Slack does not look
				self.assertEqual((kwargs['json']['unfurl_links'], kwargs['json']['unfurl_media']), (False, False))
				self.assertNotIn('unfurl_links', kwargs['headers'])

	def test_a_reply_without_a_bot_token_is_logged_not_sent(self):
		"""A Slack reply without the bot token is logged, once each, and not sent."""
		self.env(slackBotToken=False)

		err = io.StringIO()
		with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
			for cmd in ('.help', '.price', '.compare T1 T2'):
				worker.process_request('slack', 'C1', '<@U1>', cmd, BOT, 'U')
		self.assertEqual((self.posts, self.errors), ([], []))
		self.assertEqual(err.getvalue().count('ERROR slack: a reply to channel C1 needs slackBotToken in finbot.env; not sent'), 3)

	def test_the_slack_api_says_what_is_missing(self):
		"""slack_api without the bot token says so (it used to be a TypeError)."""
		self.env(slackBotToken=False)

		with self.assertRaisesRegex(RuntimeError, 'Slack files.getUploadURLExternal: needs slackBotToken in finbot.env'):
			transports.slack_api('files.getUploadURLExternal', filename='chart.png', length=1) # it was a TypeError
		self.assertEqual(self.posts, [])


class TelegramWebhook(FinbotCase):
	"""bot.py registers the webhook once as it starts. Importing lib.telegram, as every job process does, touches nothing."""

	def setUp(self):
		"""A Telegram bot with an outgoing webhook configured."""
		super().setUp()
		self.env(webhooks={'telegram': 'https://api.telegram.org/botX/'})
		self.env(telegramOutgoingWebhook='https://example.com/telegram')


	def test_register_unregisters_registers_and_names_the_bot(self):
		"""register() removes the webhook, sets it again and returns the bot's @name."""
		calls = []
		def post(url, **kwargs):
			"""Record the method and URL, and answer like Telegram."""
			calls.append((url.rsplit('/', 1)[1], kwargs.get('params', {}).get('url')))
			return Resp({'ok': True, 'result': {'username': 'finbot'} if url.endswith('getMe') else True})
		self.patch(telegram.net, 'post', post)
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(telegram.register(), '@finbot')
		self.assertEqual(calls, [('setWebhook', ''), ('setWebhook', 'https://example.com/telegram'), ('getMe', None)])

	def test_a_refused_call_raises(self):
		"""A call Telegram refuses raises with its description."""
		self.patch(telegram.net, 'post', lambda url, **k: Resp({'ok': False, 'description': 'Bad Request: bad webhook: HTTPS url must be provided'}))
		with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as caught:
			telegram.register()
		self.assertIn('HTTPS url must be provided', str(caught.exception))

	def test_edits_toasts_and_typing_go_through_call(self):
		"""A chart edit that Telegram refuses is an error (unless nothing changed); a toast, a text edit or a typing notice that
		fails, or an edit lost on the way, is only logged."""
		def answer(outcome):
			"""A net.post that answers with outcome, or raises it."""
			def post(url, **kwargs):
				"""The outcome, or raise it."""
				if isinstance(outcome, Exception):
					raise outcome
				return outcome
			return post
		refused = Resp({'ok': False, 'description': 'Bad Request: message to edit not found'})
		unchanged = Resp({'ok': False, 'description': 'Bad Request: message is not modified: specified new message content is the same'})
		chat = transports.TelegramBot('5')
		for outcome, raises in ((refused, True), (unchanged, False), (ConnectionError('down'), False), (Resp({'ok': True, 'result': True}), False)):
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
				'from lib import telegram, yahoo, worker, jobrun\n'
				'print("quiet")')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data, 'telegramBotToken': '123:abc', 'telegramOutgoingWebhook': 'https://example.com/telegram'})
		self.assertEqual(out.stdout.split()[-1:], ['quiet'], out.stderr)

	def test_the_bot_will_not_start_unregistered_and_never_logs_the_token(self):
		"""bot.py exits when the webhook cannot be registered, and never logs the token."""
		skip_if_old_env(self)
		with tempfile.TemporaryDirectory() as data:
			env = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k not in config.STARTUP_KEYS and 'proxy' not in k.lower()}
			env.update(DATA_DIR=data, port='0', scheduler='False', telegramBotToken='123456:SECRET-token', telegramOutgoingToken='tok',
					   telegramOutgoingWebhook='https://example.com/telegram',
					   HTTPS_PROXY='http://127.0.0.1:9', https_proxy='http://127.0.0.1:9') # unreachable, so the registration fails at once and offline
			out = subprocess.run([sys.executable, 'bot.py'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
		self.assertEqual(out.returncode, 1, out.stderr)
		self.assertIn('ERROR ⚠️ telegram webhook:', out.stderr)
		self.assertNotIn('SECRET-token', out.stderr + out.stdout)


if __name__ == '__main__':
	unittest.main()
