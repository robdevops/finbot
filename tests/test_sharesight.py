"""Sharesight's portfolios, holdings, gains and trades on the answers saved under doc/, its failures,
and the cache warmer."""
import datetime, os, unittest
import gevent
from tests.common import *


def portfolios():
	"""{name: id} of the portfolios to report on."""
	return {portfolio.name: portfolio.id for portfolio in sharesight.portfolios()}


class SharesightApi(ProviderCase):
	def test_portfolios_from_real_response(self):
		"""The portfolio list parses from a real answer."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.assertEqual(portfolios(), {'Rob': 445825, 'RobSMSF': 684141})

	def test_portfolio_exclusion_and_inclusion(self):
		"""exclude_portfolios and include_portfolios pick the portfolios reported on."""
		self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
		self.prefs(exclude_portfolios=['445825'])

		self.assertEqual(portfolios(), {'RobSMSF': 684141})
		self.prefs(exclude_portfolios=[], include_portfolios=['445825'])
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
		sharesight.warm()
		self.assertEqual(len(calls), 3) # portfolio list + one holdings report per portfolio (2)
		self.assertEqual(sum('/performance' in c for c in calls), 2)
		today = 'start_date=' + datetime.date.today().isoformat()
		self.assertTrue(all(today in c for c in calls if '/performance' in c)) # days=0
		sharesight.warm()
		self.assertEqual(len(calls), 3) # nothing refetched while fresh

	def test_refreshes_before_the_ttl_runs_out(self):
		"""A cache file at 95% of its lifetime is fetched again, and only that one."""
		calls = self.serve_sharesight()
		sharesight.warm()
		calls.clear()
		# 95% of its lifetime
		self.age(sharesight.performance_cache_file(684141, 0), 0.95 * config.prefs.performance_cache_seconds)
		sharesight.warm()
		self.assertEqual(len(calls), 1)
		self.assertIn('684141/performance', calls[0])
		calls.clear()
		self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * config.prefs.cache_seconds)
		sharesight.warm()
		self.assertEqual(len(calls), 1)
		self.assertTrue(calls[0].endswith('/portfolios'))

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
		"""A refresh that fails keeps the cache it would have replaced."""
		self.serve_sharesight()
		sharesight.warm()
		self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * config.prefs.cache_seconds)
		self.http(sharesight, ConnectionError('down'))
		with self.assertRaises(RuntimeError):
			sharesight.warm()
		self.assertEqual(portfolios(), {'Rob': 445825, 'RobSMSF': 684141}) # still served from the cache

	def test_a_pass_says_when_the_next_is_due(self):
		"""A pass reads each cache file once and gives the seconds until the next refresh: 90% of the shortest cache
		lifetime once everything is fresh."""
		self.serve_sharesight()
		due = sharesight.warm() # a cold cache, filled
		shortest = min(config.prefs.cache_seconds, config.prefs.performance_cache_seconds)
		self.assertAlmostEqual(due, 0.9 * shortest, delta=5)
		reads = []
		real = cache.read
		self.patch(cache, 'read', lambda name, *a, **k: (reads.append(name), real(name, *a, **k))[1])
		self.age(sharesight.performance_cache_file(684141, 0), 600)
		due = sharesight.warm()
		self.assertAlmostEqual(due, 0.9 * config.prefs.performance_cache_seconds - 600, delta=5)
		files = [sharesight.PORTFOLIOS_CACHE] + [sharesight.performance_cache_file(id, 0) for id in (445825, 684141)]
		self.assertEqual(sorted(reads), sorted(files))

	class Stopped(Exception):
		"""Raised by the stand-in for keep_warm's wake event, to end the loop."""

	def waits(self, count, on_wait=lambda n: None, **kwargs):
		"""Run keep_warm until it has waited `count` times, noting each wait instead of sleeping (on_wait(n) at the
		nth); returns the waits."""
		waits, stopped = [], self.Stopped
		class Wake:
			"""keep_warm's wake event, which nobody sets."""
			def wait(self, seconds):
				"""Note the wait instead of sleeping, and end the loop after the last."""
				waits.append(seconds)
				on_wait(len(waits))
				if len(waits) == count:
					raise stopped
			def clear(self):
				"""Nothing to clear."""
		self.patch(sharesight, '_wake', Wake())
		with self.assertRaises(self.Stopped):
			sharesight.keep_warm(**kwargs)
		return waits

	def test_loop_survives_failures_and_backs_off(self):
		"""keep_warm survives a failure, retries slowly, then sleeps until the next cache is due."""
		outcomes = [RuntimeError('boom'), 3000]
		def warm():
			"""Fail once, then succeed."""
			outcome = outcomes.pop(0)
			if isinstance(outcome, Exception):
				raise outcome
			return outcome
		self.patch(sharesight, 'warm', warm)
		self.assertEqual(self.waits(2, retry=300), [300, 3000]) # a slow retry after the failure, then until one is due

	def test_with_cache_off_nothing_is_fetched_until_a_reload_turns_it_on(self):
		"""With cache off, keep_warm idles without asking Sharesight, and starts when a reload turns it on."""
		passes = []
		self.patch(sharesight, 'warm', lambda: passes.append(1) or 3000)
		self.prefs(cache=False)
		def reload(n):
			"""At the second wait, switch the cache on, as a reload would."""
			if n == 2:
				config.prefs = dataclasses.replace(config.prefs, cache=True)
		self.assertEqual(self.waits(4, reload, idle=60), [60, 60, 3000, 3000]) # no request every 5 seconds while off
		self.assertEqual(len(passes), 2)

	def test_a_flush_wakes_the_loop_to_refill_at_once(self):
		"""A flush wakes keep_warm, which refills the caches at once instead of when they are next due."""
		passes = []
		self.patch(sharesight, 'warm', lambda: passes.append(1) or 3000)
		loop = gevent.spawn(sharesight.keep_warm)
		self.addCleanup(loop.kill)
		gevent.sleep(0.05)
		self.assertEqual(len(passes), 1) # then it sleeps until the next cache is due, 50 minutes away
		sharesight.wake()
		gevent.sleep(0.05)
		self.assertEqual(len(passes), 2)


if __name__ == '__main__':
	unittest.main()
