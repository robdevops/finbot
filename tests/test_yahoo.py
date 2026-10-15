"""Yahoo's quotes, details and charts: the real parsers on the answers saved under doc/, and failures.
HTTP is mocked at lib.net, so the production parsing code runs unchanged."""
import datetime, os, unittest
from tests.common import *


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

	def test_an_error_answer_is_not_cached(self):
		"""Yahoo's error answer is no quotes, and is not cached: the next fetch asks again."""
		error = Resp({'quoteResponse': {'result': None, 'error': {'code': 'x'}}})
		self.http(yahoo, error, Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		self.assertEqual(yahoo.fetch(['AAPL']), {})
		self.assertIn('AAPL', yahoo.fetch(['AAPL']))

	def test_the_cache_holds_yahoos_answer_so_a_parser_fix_needs_no_flush(self):
		"""Quotes are cached as Yahoo sent them, not parsed: a change to the parsing applies to a cached answer."""
		body = sample('yahoo', 'sample_yahoo_v7.json')
		self.http(yahoo, Resp(body))
		yahoo.fetch(['AAPL'])
		self.http(yahoo, ConnectionError('down')) # from here on, only the cache answers
		self.patch(yahoo, 'QUOTE_FIELDS', yahoo.QUOTE_FIELDS + (('short_name', 'shortName', None),))
		self.assertEqual(yahoo.fetch(['AAPL'])['AAPL']['short_name'], 'Apple Inc.')

	def test_with_the_cache_off_every_fetch_asks_yahoo(self):
		"""With the cache preference off, every fetch asks Yahoo, and nothing is written to the cache."""
		self.prefs(cache=False)
		getter = self.http(yahoo, Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		yahoo.fetch(['AAPL'])
		yahoo.fetch(['AAPL'])
		self.assertEqual(len(getter.calls), 2)
		self.assertEqual([name for name in os.listdir(config.env.cache_dir) if name.startswith('finbot_yahoo_')], [])

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
		for module in ('price', 'summaryProfile', 'summaryDetail', 'defaultKeyStatistics', 'financialData',
				'calendarEvents', 'earnings'):
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

	def test_the_cache_holds_yahoos_answer_so_a_parser_fix_needs_no_flush(self):
		"""A detail is cached as Yahoo sent it, not parsed: a change to the parsing applies to a cached answer."""
		self.http(yahoo, Resp(self.combined()))
		yahoo.fetch_detail('NVDA')
		self.http(yahoo, ConnectionError('down')) # from here on, only the cache answers
		self.patch(yahoo, 'DETAIL_FIELDS', yahoo.DETAIL_FIELDS + (('short_name', ('price', 'shortName')),))
		self.assertEqual(yahoo.fetch_detail('NVDA')['NVDA']['short_name'], 'NVIDIA Corporation')

	def test_a_symbol_yahoo_does_not_know_is_empty_and_an_outage_an_error(self):
		"""A detail of a symbol Yahoo does not know (404 Not Found) is empty, an answer; Yahoo unreachable or refusing
		is an error, where it used to read as an unknown symbol ("I could not find TSLA")."""
		unknown = {'quoteSummary': {'result': None, 'error': {'code': 'Not Found', 'description': 'Quote not found'}}}
		self.http(yahoo, Resp(unknown, status=404))
		self.assertEqual(yahoo.fetch_detail('DRNA'), {})
		for failure in (Resp(status=404), Resp(status=500), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				with self.assertRaises(RuntimeError):
					yahoo.fetch_detail('TSLA')

	def test_missing_names_give_empty(self):
		"""A detail without a name, or without a result, is empty."""
		body = self.combined()
		body['quoteSummary']['result'][0]['price'].update(longName=None, shortName=None)
		self.http(yahoo, Resp(body))
		self.assertEqual(yahoo.fetch_detail('DUB'), {})
		self.http(yahoo, Resp({'quoteSummary': {'result': None, 'error': {}}}))
		self.assertEqual(yahoo.fetch_detail('GONE'), {})


class YahooChart(ProviderCase):
	def test_real_chart_to_bars(self):
		"""A real v8 chart becomes its daily bars: the day, the open and the close."""
		rows = yahoo.bars(sample('yahoo', 'sample_yahoo_v8_chart.json'))
		self.assertEqual(len(rows), 2)
		self.assertTrue(all(isinstance(day, datetime.date) and close for day, _, close in rows))

	def test_a_bar_is_dated_in_its_exchanges_time_zone(self):
		"""An ASX bar, stamped at Sydney's open (23:00 UTC the day before), is dated the day it traded: it used to be
		dated the day before, so N-day changes and chart dates slipped a session."""
		open_sydney = datetime.datetime(2026, 1, 5, 23, 0, tzinfo=datetime.timezone.utc) # 10:00 on 6 Jan in Sydney
		chart = {'chart': {'result': [{'meta': {'exchangeTimezoneName': 'Australia/Sydney'},
			'timestamp': [int(open_sydney.timestamp())], 'indicators': {'quote': [{'open': [1.0], 'close': [2.0]}]}}]}}
		self.assertEqual(yahoo.bars(chart), [(datetime.date(2026, 1, 6), 1.0, 2.0)])

	def test_a_refused_crumb_is_renewed_once(self):
		"""Yahoo refusing the crumb (401) gets a new cookie and crumb, and the request is asked again, once."""
		renewed = []
		fresh = lambda renew=False: renewed.append(renew) or ('A=B', 'new' if renew else 'old')
		self.patch(yahoo, 'credentials', fresh)
		getter = self.http(yahoo, Resp(status=401), Resp(status=401), Resp(sample('yahoo', 'sample_yahoo_v7.json')))
		self.assertIn('AAPL', yahoo.fetch(['AAPL']))
		crumbs = [url.rsplit('crumb=', 1)[1] for url in getter.calls]
		self.assertEqual((renewed, crumbs), ([False, True], ['old', 'old', 'new']))
		self.http(yahoo, Resp(status=401))
		with self.assertRaises(RuntimeError): # a new crumb refused too: an error, not a loop
			yahoo.fetch(['MSFT'])

	def test_the_credentials_are_one_file_renewed_together(self):
		"""The cookie and the crumb Yahoo issued for it are cached together and renewed together; no cookie, or no
		crumb, is an error, where a stale fallback pair turned it into a refusal later."""
		self.patch(yahoo, 'credentials', REAL_CREDENTIALS)
		cookie = Resp(None, status=404)
		cookie.headers = {'Set-Cookie': 'A3=d=AQAB; Max-Age=31557600; Domain=.yahoo.com; Path=/; Secure'}
		getter = self.http(yahoo, cookie, Resp(None, text='crumb1'))
		self.assertEqual(yahoo.credentials(), ('A3=d=AQAB', 'crumb1'))
		self.assertEqual(yahoo.credentials(), ('A3=d=AQAB', 'crumb1')) # from the cache now
		self.assertEqual(len(getter.calls), 2)
		nothing = Resp(None, status=404)
		nothing.headers = {}
		self.http(yahoo, nothing)
		with self.assertRaisesRegex(RuntimeError, 'no cookie'):
			yahoo.credentials(renew=True)

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
		meta = {'currency': 'USD', 'symbol': 'T1', 'exchangeTimezoneName': 'America/New_York',
			'regularMarketTime': stamps[-1],
				'regularMarketPrice': closes[-1], 'longName': 'Co T1'}
		quote = {'open': closes, 'high': closes, 'low': closes, 'close': closes, 'volume': [1] * len(closes)}
		return {'chart': {'result': [{'meta': meta, 'timestamp': stamps, 'indicators': {'quote': [quote]}}],
			'error': None}}

	def test_1d_is_the_change_since_the_previous_close(self):
		"""1D is the change since the previous close, and 5D the week's; with a quote, its price and today's change
		count, the chart's being up to cache_seconds old."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		# up 20% in a week, down 3% today
		self.http(yahoo, Resp(self.chart([90] * 30 + [100, 105, 110, 115, 120, 116.4])))
		table, line = yahoo.price_history('T1')
		self.assertEqual(table['1D'], -3)
		self.assertGreater(table['5D'], 10) # the week, not the day
		table, line = yahoo.price_history('T1', quote={'regularMarketPrice': 125.0, 'percent_change': 7.4})
		self.assertEqual((table['1D'], line.price), (7, 125.0))

	def test_a_record_is_from_the_whole_history(self):
		"""historic_high reads the whole history (the chart from period1=0), its first day aside: records seeded
		from 10 years were no all-time records."""
		urls = []
		chart = self.chart([5.0, 50.0, 10.0, 20.0])
		self.patch(yahoo, 'historic_high', REAL[('lib.yahoo', 'historic_high')])
		self.patch(yahoo.net, 'get', lambda url, **kwargs: urls.append(url) or Resp(chart))
		self.assertEqual(yahoo.historic_high('T1'), (50.0, 10.0)) # 5.0, the first day, aside
		self.assertIn('period1=0&', urls[0])

	def test_a_symbol_yahoo_does_not_know_is_no_data(self):
		"""Yahoo's 404 for a symbol it does not know is NoData, an answer; any other 404 is an error, not an answer."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		unknown = {'chart': {'result': None, 'error': {'code': 'Not Found', 'description': 'No data found'}}}
		self.http(yahoo, Resp(unknown, status=404))
		with self.assertRaises(yahoo.NoData) as caught:
			yahoo.price_history('XYZ', 7)
		self.assertEqual(caught.exception.lines, ['no price history for XYZ'])
		self.http(yahoo, Resp(status=404)) # an endpoint that moved, say
		with self.assertRaises(RuntimeError) as caught:
			yahoo.price_history('XYZ', 7)
		self.assertNotIsInstance(caught.exception, answer.Answer)

	def test_a_failed_chart_fetch_raises(self):
		"""A chart refused (429) or unreachable is a RuntimeError, which callers turn into leaving the ticker out."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		for failure in (Resp(status=429), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(yahoo, failure)
				with self.assertRaises(RuntimeError):
					yahoo.price_history('AAPL', 7)

	def test_one_failed_ticker_does_not_take_the_report_down(self):
		"""One ticker without a chart is left out of a price list, a benchmark without one is said to have none, and
		only a report on that one ticker fails, in one line."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		quotes = lambda ts: {t: market_entry(t) | {'regularMarketPrice': 110.0} for t in ts} # charts over HTTP
		self.patch(yahoo, 'fetch', quotes)
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
		self.patch(sharesight, '_portfolios', lambda seconds=None: [{'name': 'Rob', 'id': 1}])
		self.patch(sharesight, '_performance', lambda pid, days=None, seconds=None: # every ticker needs its history
			{'holdings': [], 'capital_gain_percent': '2.5'})
		good = Resp(self.chart([100.0] * 20 + [110.0]))
		def get(url, **kwargs):
			"""A chart for every ticker but T3 and SPY, which get 404."""
			return Resp(status=404) if '/chart/T3?' in url or '/chart/SPY?' in url else good
		self.patch(yahoo.net, 'get', get)
		def slack(text):
			"""Run a command on Slack, its report as text (no charts), and return the text."""
			self.prefs(graph=False)
			self.sent.clear(); self.errors.clear()
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', text, BOT, 'U'))
			self.assertEqual(self.errors, [], text)
			return '\n'.join(map(str, self.sent[-1][1]))
		price_list = slack('.price 7d') # T3 is left out, the rest are listed
		self.assertNotIn('Co T3 (', price_list)
		self.assertIn('Co T4 (', price_list)
		report = slack('.performance 7d') # the S&P 500 benchmark has no history
		self.assertIn('⚠️ S&P 500: no price history', report)
		self.assertIn('NASDAQ 100', report)
		self.command('.T3') # the profile goes out without its history lines
		self.sent.clear(); self.errors.clear()
		worker.process_request(inbound.Message('telegram', '55', '@u', '.price T3 7d', BOT, 'U'))
		self.assertEqual(len(self.errors), 1) # the one ticker asked for: one line saying why
		self.assertTrue(self.errors[0].startswith('⚠️ .price: RuntimeError: 404 error for T3'))

	def test_the_chart_request_carries_the_cookie_of_its_crumb(self):
		"""A chart request sends the cookie its crumb belongs to."""
		headers = []
		self.patch(yahoo.net, 'get',
			lambda url, **kwargs: headers.append(kwargs.get('headers', {})) or Resp(self.chart([100.0] * 5)))
		yahoo.fetch_chart_json('T1', full=True)
		self.assertEqual(headers[0].get('Cookie'), 'A=B') # the crumb used to go without its cookie

	def test_with_the_cache_off_no_chart_is_written(self):
		"""With the cache preference off, a chart is drawn but not written to the cache."""
		self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
		self.prefs(cache=False)
		self.http(yahoo, Resp(self.chart([100.0] * 30 + [110.0])))
		changes, line = yahoo.price_history('T1', 7)
		self.assertTrue(render.draw(history.line_chart('T1', changes, line, 7)).read().startswith(b'\x89PNG'))
		self.assertEqual([name for name in os.listdir(config.env.cache_dir) if name.startswith('finbot_chart_')], [])

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


if __name__ == '__main__':
	unittest.main()
