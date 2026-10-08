"""Yahoo, Sharesight and Telegram parsing and failure handling, driven by the real API responses saved under doc/.
HTTP is mocked at the requests layer, so the production parsing code runs unchanged."""
import copy, datetime, json, os, unittest
from unittest import mock
from tests.common import *

DOC = os.path.join(ROOT, 'doc')


def sample(*path):
    with open(os.path.join(DOC, *path), encoding='utf-8') as f:
        return json.load(f)


class Resp:
    def __init__(self, payload=None, status=200, text=''):
        self.payload, self.status_code, self.text = payload, status, text or json.dumps(payload)
    def json(self):
        if self.payload is None:
            raise ValueError('no json')
        return self.payload


def serve(*responses):
    """requests.get replacement: replays the responses in order (exceptions are raised); the last one repeats."""
    queue = list(responses)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item
    get.calls = calls
    return get


class ProviderCase(FinbotCase):
    def setUp(self):
        super().setUp()
        # these tests exercise the real parsers, so undo the canned data from the base fixture
        for module, name in ((yahoo, 'fetch'), (yahoo, 'fetch_detail'), (yahoo, 'price_series'), (sharesight, 'get_portfolios'),
                             (sharesight, 'get_trades'), (sharesight, 'get_performance'), (sharesight, 'get_performance_wrapper')):
            self.patch(module, name, REAL[(module.__name__, name)])
        self.patch(yahoo, 'getCookie', lambda *a, **k: 'A=B')
        self.patch(yahoo, 'getCrumb', lambda *a, **k: 'crumb')
        self.patch(sharesight, 'get_token', lambda: 'token')
        self.patch(sharesight.time, 'sleep', lambda s: None)

    def http(self, module, *responses):
        getter = serve(*responses)
        self.patch(module.requests, 'get', getter)
        return getter


class YahooQuotes(ProviderCase):
    def test_parses_real_v7_quote(self):
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
        getter = self.http(yahoo, Resp(sample('yahoo', 'sample_yahoo_v7.json')))
        yahoo.fetch(['AAPL'])
        yahoo.fetch(['AAPL'])
        self.assertEqual(len(getter.calls), 1)

    def test_falls_back_to_second_host(self):
        getter = self.http(yahoo, Resp(status=500), Resp(sample('yahoo', 'sample_yahoo_v7.json')))
        self.assertIn('AAPL', yahoo.fetch(['AAPL']))
        self.assertIn('query1', getter.calls[1])

    def test_all_hosts_failing_raises(self):
        for failure in (Resp(status=500), ConnectionError('down')):
            with self.subTest(failure=failure):
                self.http(yahoo, failure)
                with self.assertRaises(RuntimeError):
                    yahoo.fetch(['AAPL'])

    def test_empty_result_is_none(self):
        self.http(yahoo, Resp({'quoteResponse': {'result': None, 'error': {'code': 'x'}}}))
        self.assertEqual(yahoo.fetch(['NOPE']), {})

    def test_no_tickers_is_none(self):
        self.assertEqual(yahoo.fetch([]), {})

    def test_incomplete_quotes_are_skipped(self):
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
        self.http(yahoo, Resp(self.combined()))
        data = yahoo.fetch_detail('NVDA')['NVDA']
        self.assertEqual(data['profile_title'], 'NVIDIA')
        self.assertTrue(data['profile_bio'])

    def test_http_failure_gives_empty(self):
        for failure in (Resp(status=404), ConnectionError('down')):
            with self.subTest(failure=failure):
                self.http(yahoo, failure)
                self.assertEqual(yahoo.fetch_detail('DRNA'), {})

    def test_missing_names_give_empty(self):
        body = self.combined()
        body['quoteSummary']['result'][0]['price'].update(longName=None, shortName=None)
        self.http(yahoo, Resp(body))
        self.assertEqual(yahoo.fetch_detail('DUB'), {})
        self.http(yahoo, Resp({'quoteSummary': {'result': None, 'error': {}}}))
        self.assertEqual(yahoo.fetch_detail('GONE'), {})


class YahooChart(ProviderCase):
    def test_real_chart_to_dataframe_and_basics(self):
        chart = sample('yahoo', 'sample_yahoo_v8_chart.json')
        df = yahoo.chart_json_to_df(chart)
        self.assertEqual(len(df), 2)
        self.assertTrue({'Date', 'Close'} <= set(df.columns))
        basics = yahoo.chart_json_to_stock_basics(chart)
        self.assertEqual((basics['symbol'], basics['currency']), ('CRWD', 'USD'))

    def test_fetch_chart_json_failures_return_error_strings(self):
        for failure in (Resp(status=404), ConnectionError('down')):
            with self.subTest(failure=failure):
                self.http(yahoo, failure)
                result = yahoo.fetch_chart_json('AAPL', full=True)
                self.assertIsInstance(result, tuple)
                self.assertIsNone(result[1])

    def test_price_series_raises_on_failure_and_on_empty_history(self):
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
        self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
        self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141})

    def test_portfolio_exclusion_and_inclusion(self):
        self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_portfolios.json')))
        self.patch(sharesight, 'config_exclude_portfolios', ['445825'])
        self.assertEqual(sharesight.get_portfolios(), {'RobSMSF': 684141})
        self.patch(sharesight, 'config_exclude_portfolios', [])
        self.patch(sharesight, 'config_include_portfolios', ['445825'])
        self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825})

    def test_portfolio_failures_raise(self):
        for failure in (Resp({'error': 'nope', 'error_code': 'x'}, 401), ConnectionError('down'), Resp({'portfolios': []})):
            with self.subTest(failure=failure):
                self.http(sharesight, failure)
                with self.assertRaises(RuntimeError):
                    sharesight.get_portfolios()

    def test_trades_from_real_response(self):
        self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_trades_684141_1.json')))
        trades = sharesight.get_trades('RobSMSF', 684141, 1)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0]['portfolio'], 'RobSMSF')
        self.assertEqual(trades[0]['symbol'], 'FANG')

    def test_trade_failures_raise(self):
        self.http(sharesight, ConnectionError('down'))
        with self.assertRaises(RuntimeError):
            sharesight.get_trades('RobSMSF', 684141, 1)
        self.http(sharesight, Resp({'trades': [], 'error': 'bad', 'error_code': 'x'}, 400))
        with self.assertRaises(RuntimeError):
            sharesight.get_trades('RobSMSF', 684141, 2)

    def test_performance_and_holdings_from_real_response(self):
        self.http(sharesight, Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
        self.assertEqual(len(sharesight.get_performance(684141, 0)['report']['holdings']), 18)
        tickers = sharesight.get_holdings('RobSMSF', 684141)
        self.assertIn('ARM', tickers) # US venues carry no Yahoo suffix
        self.assertEqual(tickers, sorted(tickers))

    def test_performance_retries_when_sharesight_is_busy(self):
        busy = Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429)
        getter = self.http(sharesight, busy, busy, Resp(sample('sharesight', 'finbot_sharesight_performance_684141_0.json')))
        self.assertIn('report', sharesight.get_performance(684141, 0))
        self.assertEqual(len(getter.calls), 3)

    def test_performance_gives_up_after_repeated_busy_or_hard_errors(self):
        for failure in (Resp({'error': 'Too many parallel requests', 'error_code': 'x'}, 429),
                        Resp({'error': 'forbidden', 'error_code': 'x'}, 403), ConnectionError('down')):
            with self.subTest(failure=failure):
                self.http(sharesight, failure)
                with self.assertRaises(RuntimeError):
                    sharesight.get_performance(684141, 7)


class SharesightKeepWarm(ProviderCase):
    """The background refresher keeps the portfolio list and the holdings report (days=0) cached ahead of their TTLs."""

    def serve_sharesight(self):
        portfolios = sample('sharesight', 'finbot_sharesight_portfolios.json')
        performance = sample('sharesight', 'finbot_sharesight_performance_684141_0.json')
        calls = []
        def get(url, **kwargs):
            calls.append(url)
            return Resp(performance if '/performance' in url else portfolios)
        self.patch(sharesight.requests, 'get', get)
        return calls

    def age(self, cache_file, seconds):
        path = os.path.join(util.config_cache_dir, cache_file)
        old = os.path.getmtime(path) - seconds
        os.utime(path, (old, old))

    def test_cold_cache_is_filled_then_left_alone(self):
        calls = self.serve_sharesight()
        self.assertEqual(sharesight.warm_once(), 3) # portfolio list + one holdings report per portfolio (2)
        self.assertEqual(sum('/performance' in c for c in calls), 2)
        self.assertTrue(all('start_date=' + datetime.date.today().isoformat() in c for c in calls if '/performance' in c)) # days=0
        self.assertEqual(sharesight.warm_once(), 0)
        self.assertEqual(len(calls), 3) # nothing refetched while fresh

    def test_refreshes_before_the_ttl_runs_out(self):
        calls = self.serve_sharesight()
        sharesight.warm_once()
        calls.clear()
        self.age(sharesight.performance_cache_file(684141, 0), 0.95 * sharesight.PERFORMANCE_TTL) # 95% of its lifetime
        self.assertEqual(sharesight.warm_once(), 1)
        self.assertEqual(len(calls), 1)
        self.assertIn('684141/performance', calls[0])
        calls.clear()
        self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * sharesight.config_cache_seconds)
        self.assertEqual(sharesight.warm_once(), 1)
        self.assertTrue(calls[0].endswith('/portfolios'))

    def test_a_request_never_waits_on_a_cache_the_job_has_warmed(self):
        calls = self.serve_sharesight()
        sharesight.warm_once()
        calls.clear()
        self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141})
        self.assertEqual(len(sharesight.get_performance(684141, 0)['report']['holdings']), 18)
        self.assertEqual(calls, [])

    def test_holdings_wrapper_is_served_entirely_from_the_warmed_cache(self):
        calls = self.serve_sharesight()
        sharesight.warm_once()
        calls.clear()
        tickers = sharesight.get_holdings_wrapper() # get_portfolios() + get_holdings() per portfolio, no cache of its own
        self.assertIn('ARM', tickers)
        self.assertEqual(calls, [])

    def test_failed_refresh_keeps_the_old_cache(self):
        self.serve_sharesight()
        sharesight.warm_once()
        self.age(sharesight.PORTFOLIOS_CACHE, 0.95 * sharesight.config_cache_seconds)
        self.http(sharesight, ConnectionError('down'))
        with self.assertRaises(RuntimeError):
            sharesight.warm_once()
        self.assertEqual(sharesight.get_portfolios(), {'Rob': 445825, 'RobSMSF': 684141}) # still served from the cache

    def test_loop_survives_failures_and_backs_off(self):
        class Stop:
            def __init__(self): self.waits = []
            def is_set(self): return len(self.waits) >= 2
            def wait(self, seconds): self.waits.append(seconds)
        outcomes = [RuntimeError('boom'), 0]
        def warm():
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.patch(sharesight, 'warm_once', warm)
        self.patch(sharesight, 'next_due', lambda: 3000)
        stop = Stop()
        sharesight.keep_warm(retry=300, stop=stop)
        self.assertEqual(stop.waits, [300, 3000]) # slow retry after the failure, then sleep until the next cache is due

    def test_next_due_is_90_percent_of_the_ttl(self):
        self.serve_sharesight()
        self.assertEqual(sharesight.next_due(), 0) # cold cache
        sharesight.warm_once()
        due = sharesight.next_due()
        self.assertAlmostEqual(due, 0.9 * min(sharesight.config_cache_seconds, sharesight.PERFORMANCE_TTL), delta=5)

    def test_refresh_flag_bypasses_a_fresh_cache(self):
        calls = self.serve_sharesight()
        sharesight.get_portfolios()
        sharesight.get_portfolios()
        self.assertEqual(len(calls), 1)
        sharesight.get_portfolios(refresh=True)
        self.assertEqual(len(calls), 2)


class TelegramSending(FinbotCase):
    """webhook.write against failing endpoints. The real send path, not the base fixture's recorder."""

    def post(self, outcome):
        def fake(url, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        self.patch(webhook.requests, 'post', fake)
        return webhook.write('telegram', 'https://api.telegram.org/botX/sendMessage?chat_id=5', 'hi', '5')

    def test_success_returns_json(self):
        self.assertEqual(self.post(Resp({'ok': True})), {'ok': True})

    def test_http_error_and_exception_return_none(self):
        self.assertIsNone(self.post(Resp(status=429)))
        self.assertIsNone(self.post(ConnectionError('down')))

    def test_non_json_success_returns_empty_dict(self):
        self.assertEqual(self.post(Resp(None)), {})

    def test_error_line_redacts_secrets_and_truncates(self):
        line = webhook.error_line(RuntimeError('GET /bot123456:ABC-def_1/send?crumb=SECRET&x=1 failed'), 'ctx')
        self.assertNotIn('ABC-def_1', line)
        self.assertNotIn('SECRET', line)
        self.assertTrue(line.startswith('⚠️ ctx: '))
        self.assertLessEqual(len(webhook.error_line('x' * 1000)), 205)

    def test_report_error_never_raises(self):
        self.patch(webhook, 'write', mock.Mock(side_effect=RuntimeError('send failed')))
        webhook.report_error(ValueError('boom'), service='telegram', chat_id='5')
        webhook.report_error(ValueError('boom'))

    def test_guarded_reports_and_exits_nonzero(self):
        reported = []
        self.patch(webhook, 'report_error', lambda e, **k: reported.append(e))
        with self.assertRaises(SystemExit) as raised:
            webhook.guarded('job', lambda: 1 / 0)
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(len(reported), 1)
        self.assertEqual(webhook.guarded('job', lambda: 'fine'), 'fine')


if __name__ == '__main__':
    unittest.main()
