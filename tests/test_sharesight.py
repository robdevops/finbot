"""Sharesight's portfolios, holdings, gains and trades on the answers saved under doc/, its failures,
and the cache warmer."""
import contextlib, datetime, unittest
from tests.common import *


def portfolios():
	"""{name: id} of the portfolios to report on."""
	return {portfolio.name: portfolio.id for portfolio in sharesight.portfolios()}


class SharesightApi(ProviderCase):
	def setUp(self):
		"""Yahoo's exchange rates fixed, which a holdings report asks for to note its values in US dollars."""
		super().setUp()
		self.patch(yahoo, 'usd_rates', lambda currencies: {'USD': 1.0, 'AUD': 0.5})

	def test_portfolios_from_real_response(self):
		"""The portfolio list parses from a real answer."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.assertEqual(portfolios(), {'Rob': 445825, 'RobSMSF': 684141})

	def test_portfolio_exclusion_and_inclusion(self):
		"""exclude_portfolios and include_portfolios pick the portfolios reported on."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.settings(exclude_portfolios=['445825'])

		self.assertEqual(portfolios(), {'RobSMSF': 684141})
		self.settings(exclude_portfolios=[], include_portfolios=['445825'])
		self.assertEqual(portfolios(), {'Rob': 445825})

	def test_portfolio_failures_raise(self):
		"""An error answer, Sharesight unreachable or no portfolios is a RuntimeError."""
		for failure in (Resp({'error': 'nope', 'error_code': 'x'}, 401), ConnectionError('down'),
				Resp({'portfolios': []})):
			with self.subTest(failure=failure):
				self.http(sharesight, failure)
				with self.assertRaises(RuntimeError):
					sharesight.portfolios()

	def test_an_answer_that_is_not_json_says_so(self):
		"""An HTML error page from Sharesight is a RuntimeError naming the request and the status, not a JSON parse
		error."""
		self.http(sharesight, Resp(None, 502, '<html>Bad gateway</html>'))
		with self.assertRaisesRegex(RuntimeError, 'Sharesight trades: a 502 answer that is not JSON'):
			sharesight.Portfolio('RobSMSF', 684141).trades(1)

	def test_trades_from_real_response(self):
		"""Trades parse from a real answer, tagged with their portfolio, which the cache leaves out: it holds the answer
		as sent."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_trades_684141_1.json')))
		trades = sharesight.Portfolio('RobSMSF', 684141).trades(1)
		self.assertEqual(len(trades), 2)
		self.assertEqual(trades[0]['portfolio'], 'RobSMSF')
		self.assertEqual(trades[0]['symbol'], 'FANG')
		self.assertEqual(cache.read('finbot_sharesight_trades_684141_1.json'), sample('sharesight',
			'finbot_sharesight_trades_684141_1.json'))

	def test_trade_failures_raise(self):
		"""Sharesight unreachable, or an error answer, is a RuntimeError."""
		self.http(sharesight, ConnectionError('down'))
		with self.assertRaises(RuntimeError):
			sharesight.Portfolio('RobSMSF', 684141).trades(1)
		self.http(sharesight, Resp({'trades': [], 'error': 'bad', 'error_code': 'x'}, 400))
		with self.assertRaisesRegex(RuntimeError, 'Sharesight trades: bad'):
			sharesight.Portfolio('RobSMSF', 684141).trades(2)

	def test_an_oauth_error_is_reported_with_its_description(self):
		"""Sharesight's refusal of the credentials says why, in OAuth's words (it used to be a KeyError on its missing
		error_code)."""
		self.patch(sharesight, '_token', REAL_TOKEN)
		refusal = {'error': 'invalid_client', 'error_description': 'Client authentication failed'}
		self.patch(sharesight.net, 'post', lambda url, **kwargs: Resp(refusal, 401))
		with self.assertRaisesRegex(RuntimeError, 'Sharesight auth: invalid_client: Client authentication failed'):
			sharesight.portfolios()

	def test_an_answer_without_what_was_asked_for_is_an_error(self):
		"""A refusal without an error, or a 200 without the list asked for, is an error saying so, not a KeyError
		later."""
		for answer in (Resp({'message': 'nope'}, 403), Resp({'links': {}})):
			with self.subTest(status=answer.status_code):
				self.http(sharesight, answer)
				why = f'Sharesight portfolios: a {answer.status_code} answer without portfolios'
				with self.assertRaisesRegex(RuntimeError, why):
					sharesight.portfolios()

	def test_performance_and_holdings_from_real_response(self):
		"""A real holdings report parses: its tickers come out sorted, US ones without a suffix, and its gain is the
		portfolio's."""
		sent = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
		self.http(sharesight, Resp(sent))
		self.assertEqual(len(sharesight._performance(684141, 0)['holdings']), 18)
		portfolio = sharesight.Portfolio('RobSMSF', 684141)
		tickers = portfolio.tickers()
		self.assertIn('ARM', tickers) # US venues carry no Yahoo suffix
		self.assertEqual(tickers, sorted(tickers))
		self.assertEqual(portfolio.gain(0), float(sent['report']['capital_gain_percent']))

	def test_performance_retries_when_sharesight_is_busy(self):
		"""While Sharesight says too many requests are in flight, the request is tried again."""
		busy = Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429)
		getter = self.http(sharesight, busy, busy,
			Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
		self.assertIn('holdings', sharesight._performance(684141, 0))
		self.assertEqual(len(getter.calls), 3)

	def test_performance_gives_up_after_repeated_busy_or_hard_errors(self):
		"""Busy every time, a hard error, or unreachable: a RuntimeError in the end."""
		for failure in (Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429),
						Resp({'error': 'forbidden', 'error_code': 'x'}, 403), ConnectionError('down')):
			with self.subTest(failure=failure):
				self.http(sharesight, failure)
				with self.assertRaises(RuntimeError):
					sharesight._performance(684141, 7)

	def test_an_answer_without_a_report_says_so(self):
		"""A performance answer without a report is an error naming the portfolio, and is not cached."""
		self.http(sharesight, Resp({}))
		with self.assertRaisesRegex(RuntimeError, 'performance of portfolio 684141: a 200 answer without report'):
			sharesight._performance(684141, 7)
		self.assertIsNone(cache.read(sharesight.performance_cache_file(684141, 7))) # and is not cached


class SharesightLargest(ProviderCase):
	"""largest(): the ticker held in the biggest amount over the portfolios, noted in US dollars as holdings reports
	arrive."""

	def setUp(self):
		"""Yahoo's exchange rates fixed: an Australian dollar is half a US dollar."""
		super().setUp()
		self.patch(yahoo, 'usd_rates', lambda currencies: {'USD': 1.0, 'AUD': 0.5})

	def report(self, currency, **values):
		"""A holdings report in `currency` whose holdings (US-listed tickers) have these values."""
		return {'currency': {'code': currency}, 'holdings': [
			{'value': value, 'instrument': {'code': code, 'market_code': 'NASDAQ'}} for code, value in values.items()]}

	def test_a_start_notes_the_holdings_reports_the_cache_holds(self):
		"""note_cached notes the holdings reports already in the cache, whatever their age, with no request but a
		rate: a restart need not wait for the warm job."""
		performance = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
		cache.write(sharesight.PORTFOLIOS_CACHE, sample('sharesight', 'finbot_sharesight_portfolios.json'))
		cache.write(sharesight.performance_cache_file(684141, 0), performance) # the other portfolio has no report
		self.patch(sharesight.net, 'get', lambda *args, **kwargs: self.fail('Sharesight was asked'))
		sharesight.note_cached()
		top = max(performance['report']['holdings'], key=lambda each: each['value'])
		self.assertEqual(sharesight.largest(), markets.transform_to_yahoo(top['instrument']['code'],
			top['instrument']['market_code']))
		self.assertEqual(set(cache.load(sharesight.LARGEST)['portfolios']), {'684141'})

	def test_a_start_leaves_what_an_earlier_run_noted(self):
		"""The file survives a restart: with it there, note_cached changes nothing (the warm job keeps it current)."""
		sharesight._note_values(1, self.report('USD', KEPT=5.0))
		cache.write(sharesight.PORTFOLIOS_CACHE, sample('sharesight', 'finbot_sharesight_portfolios.json'))
		cache.write(sharesight.performance_cache_file(684141, 0), sample('sharesight',
			'finbot_sharesight_performance_684141_0.json'))
		before = cache.load(sharesight.LARGEST)
		sharesight.note_cached()
		self.assertEqual(cache.load(sharesight.LARGEST), before)
		self.assertEqual(sharesight.largest(), 'KEPT')

	def test_a_start_notes_nothing_without_sharesight_or_a_cache(self):
		"""note_cached does nothing with the cache setting off, Sharesight not set up, or nothing cached."""
		sharesight.note_cached() # nothing cached
		self.assertIsNone(sharesight.largest())
		cache.write(sharesight.PORTFOLIOS_CACHE, sample('sharesight', 'finbot_sharesight_portfolios.json'))
		cache.write(sharesight.performance_cache_file(684141, 0), sample('sharesight',
			'finbot_sharesight_performance_684141_0.json'))
		self.settings(cache=False)
		sharesight.note_cached()
		self.settings(cache=True)
		self.patch(sharesight, 'configured', lambda: False)
		sharesight.note_cached()
		self.assertIsNone(sharesight.largest())

	def test_nothing_is_largest_before_any_report(self):
		"""No holdings report yet: no biggest holding."""
		self.assertIsNone(sharesight.largest())

	def test_a_fetched_holdings_report_notes_its_biggest_holding_in_us_dollars(self):
		"""Asking Sharesight for a portfolio's holdings (days 0) keeps what each holding is worth in US dollars (the
		report's values are in its currency, here AUD), and largest() is the biggest."""
		performance = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
		self.http(sharesight, Resp(performance))
		self.assertEqual(len(sharesight._performance(684141, 0)['holdings']), 18)
		top = max(performance['report']['holdings'], key=lambda each: each['value'])
		ticker = markets.transform_to_yahoo(top['instrument']['code'], top['instrument']['market_code'])
		self.assertEqual(sharesight.largest(), ticker)
		kept = cache.load(sharesight.LARGEST)['portfolios']['684141']
		self.assertAlmostEqual(kept[ticker], top['value'] * 0.5)
		self.assertEqual(len(kept), 18)

	def test_a_ticker_in_several_portfolios_counts_them_all_in_one_currency(self):
		"""A ticker held in an AUD and a USD portfolio is worth both in US dollars, which can put it past a ticker whose
		single position is bigger than either of its."""
		sharesight._note_values(1, self.report('AUD', A=100.0, B=120.0)) # A 50, B 60
		self.assertEqual(sharesight.largest(), 'B')
		sharesight._note_values(2, self.report('USD', A=40.0)) # A 50 + 40
		self.assertEqual(sharesight.largest(), 'A')
		sharesight._note_values(2, self.report('USD', A=5.0)) # a newer report replaces the portfolio's
		self.assertEqual(sharesight.largest(), 'B')

	def test_only_the_portfolios_reported_on_count(self):
		"""A portfolio that exclude_portfolios (or include_portfolios) leaves out does not count."""
		sharesight._note_values(1, self.report('USD', A=10.0))
		sharesight._note_values(2, self.report('USD', B=20.0))
		self.assertEqual(sharesight.largest(), 'B')
		self.settings(exclude_portfolios=['2'])
		self.assertEqual(sharesight.largest(), 'A')
		self.settings(exclude_portfolios=[], include_portfolios=['2'])
		self.assertEqual(sharesight.largest(), 'B')

	def test_a_holding_without_a_value_is_left_out(self):
		"""A holding with no value, or none above zero, is no candidate."""
		sharesight._note_values(1, self.report('USD', A=None, B=0.0, C=3.0))
		self.assertEqual(sharesight.largest(), 'C')
		self.assertEqual(set(cache.load(sharesight.LARGEST)['portfolios']['1']), {'C'})

	def test_a_rate_that_cannot_be_had_loses_the_note_and_never_the_report(self):
		"""No US dollar rate for the report's currency, or the cache setting off: the holdings report comes back all the
		same, and nothing is kept."""
		performance = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
		self.patch(yahoo, 'usd_rates', lambda currencies: {'USD': 1.0})
		self.http(sharesight, Resp(performance))
		with contextlib.redirect_stderr(io.StringIO()) as err:
			self.assertEqual(len(sharesight._performance(684141, 0)['holdings']), 18)
		self.assertIsNone(sharesight.largest())
		self.assertIn('could not note the holdings of portfolio 684141', err.getvalue())
		self.settings(cache=False)
		sharesight._note_values(1, self.report('USD', A=1.0))
		self.assertIsNone(sharesight.largest())

	def test_other_reports_note_nothing(self):
		"""A performance report over past days (the gain of a period) says nothing about the holdings now."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
		sharesight._performance(684141, 28)
		self.assertIsNone(sharesight.largest())

	def test_a_damaged_file_is_no_largest_holding(self):
		"""largest() never raises: a file that is not what _note_values writes is no answer."""
		cache.write(sharesight.LARGEST, {'portfolios': {'1': 'nonsense'}})
		self.assertIsNone(sharesight.largest())


class SharesightWarm(ProviderCase):
	"""warm() fetches the portfolio list and the holdings reports (days=0) afresh, for sharesight_warm.py to run on its
	schedule."""

	def setUp(self):
		"""Yahoo's exchange rates fixed, which a holdings report asks for to note its values in US dollars."""
		super().setUp()
		self.patch(yahoo, 'usd_rates', lambda currencies: {'USD': 1.0, 'AUD': 0.5})

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

	def test_the_list_and_each_holdings_report_are_fetched_afresh(self):
		"""warm fetches the list and each portfolio's holdings as of today, afresh even while their caches are fresh."""
		calls = self.serve_sharesight()
		self.assertEqual([portfolio.name for portfolio in sharesight.warm()], ['Rob', 'RobSMSF'])
		self.assertEqual(len(calls), 3) # portfolio list + one holdings report per portfolio (2)
		self.assertEqual(sum('/performance' in c for c in calls), 2)
		today = 'start_date=' + formats.today().isoformat()
		self.assertTrue(all(today in c for c in calls if '/performance' in c)) # days=0
		sharesight.warm()
		self.assertEqual(len(calls), 6)

	def test_a_portfolio_that_is_gone_no_longer_counts_towards_the_biggest_holding(self):
		"""warm keeps the biggest holding of the portfolios in Sharesight's list alone."""
		self.serve_sharesight()
		sharesight._note_values(999, {'currency': {'code': 'USD'}, 'holdings': [
			{'value': 1e12, 'instrument': {'code': 'GONE', 'market_code': 'NASDAQ'}}]})
		self.assertEqual(sharesight.largest(), 'GONE')
		sharesight.warm()
		self.assertNotEqual(sharesight.largest(), 'GONE')
		self.assertEqual(set(cache.load(sharesight.LARGEST)['portfolios']), {'445825', '684141'})

	def test_a_request_never_waits_on_a_cache_the_job_has_warmed(self):
		"""Once warmed, the list and the holdings report need no request."""
		calls = self.serve_sharesight()
		sharesight.warm()
		calls.clear()
		self.assertEqual(portfolios(), {'Rob': 445825, 'RobSMSF': 684141})
		self.assertEqual(len(sharesight._performance(684141, 0)['holdings']), 18)
		self.assertEqual(calls, [])

	def test_every_holding_is_served_from_the_warmed_cache(self):
		"""Every portfolio's tickers come from the warmed cache, with no request."""
		calls = self.serve_sharesight()
		sharesight.warm()
		calls.clear()
		tickers = sharesight.tickers() # the portfolio list and each portfolio's holdings report, no cache of its own
		self.assertIn('ARM', tickers)
		self.assertEqual(calls, [])

	def test_failed_refresh_keeps_the_old_cache(self):
		"""A refresh that fails raises, and keeps the cache it would have replaced."""
		self.serve_sharesight()
		sharesight.warm()
		self.http(sharesight, ConnectionError('down'))
		with self.assertRaises(RuntimeError):
			sharesight.warm()
		self.assertEqual(portfolios(), {'Rob': 445825, 'RobSMSF': 684141}) # still served from the cache


if __name__ == '__main__':
	unittest.main()
