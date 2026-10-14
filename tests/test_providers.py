"""Yahoo, Sharesight and Telegram parsing and failure handling, driven by the real API responses saved under doc/.
HTTP is mocked at the requests layer, so the production parsing code runs unchanged."""
import contextlib, copy, datetime, io, json, os, subprocess, unittest
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
        self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
        self.http(yahoo, Resp(self.chart([90] * 30 + [100, 105, 110, 115, 120, 116.4]))) # up 20% in a week, down 3% today
        table, image = yahoo.price_history('T1', graph=False)
        self.assertEqual(table['1D'], -3)
        self.assertGreater(table['5D'], 10) # the week, not the day

    def test_a_failed_chart_fetch_is_handed_back_not_raised(self):
        self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
        for failure in (Resp(status=429), ConnectionError('down')):
            with self.subTest(failure=failure):
                self.http(yahoo, failure)
                percent, image = yahoo.price_history('AAPL', 7, graph=False)
                self.assertIsInstance(percent, str)
                self.assertIsNone(image)

    def test_one_failed_ticker_does_not_take_the_report_down(self):
        self.patch(yahoo, 'price_history', REAL[('lib.yahoo', 'price_history')])
        self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts}) # quotes as canned in the base fixture, charts over HTTP
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
        self.patch(sharesight, 'get_performance_wrapper', lambda d: {}) # no Sharesight figures: every ticker needs its Yahoo history
        good = Resp(self.chart([100.0] * 20 + [110.0]))
        def get(url, **kwargs):
            return Resp(status=404) if '/chart/T3?' in url or '/chart/SPY?' in url else good
        self.patch(yahoo.requests, 'get', get)
        def slack(text): # Slack: the reports come as text
            self.sent.clear(); self.errors.clear()
            worker.process_request('slack', 'C1', '<@U1>', text, BOT, 'U', '1')
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
        worker.process_request('telegram', '55', '@u', '.price T3 7d', BOT, 'U', '1')
        self.assertEqual(len(self.errors), 1) # the one ticker asked for: one line saying why
        self.assertTrue(self.errors[0].startswith('⚠️ .price: RuntimeError: 404 error for T3'))

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
        self.age(sharesight.performance_cache_file(684141, 0), 0.95 * sharesight.config_performance_cache_seconds) # 95% of its lifetime
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
            return outcome, {}
        self.patch(sharesight, 'warm', warm)
        self.patch(sharesight, 'next_due', lambda portfolios=None: 3000)
        stop = Stop()
        sharesight.keep_warm(retry=300, stop=stop)
        self.assertEqual(stop.waits, [300, 3000]) # slow retry after the failure, then sleep until the next cache is due

    def test_with_cache_off_nothing_is_fetched_until_a_reload_turns_it_on(self):
        class Stop:
            def __init__(self): self.waits = []
            def is_set(self): return len(self.waits) >= 4
            def wait(self, seconds):
                self.waits.append(seconds)
                if len(self.waits) == 2:
                    sharesight.config_cache = True # what a reload that switches it on does
        passes = []
        self.patch(sharesight, 'warm', lambda: (passes.append(1), (0, {}))[1])
        self.patch(sharesight, 'next_due', lambda portfolios=None: 3000)
        self.patch(sharesight, 'config_cache', False)
        stop = Stop()
        sharesight.keep_warm(idle=60, stop=stop)
        self.assertEqual((stop.waits, len(passes)), ([60, 60, 3000, 3000], 2)) # idle while off: no Sharesight request every 5 seconds

    def test_a_warming_pass_reads_the_cached_portfolio_list_once(self):
        self.serve_sharesight()
        sharesight.warm_once() # fill the caches
        reads = []
        real = util.read_cache
        self.patch(util, 'read_cache', lambda name, *a, **k: (reads.append(name), real(name, *a, **k))[1])
        fetched, portfolios = sharesight.warm() # what one pass of keep_warm does
        due = sharesight.next_due(portfolios=portfolios)
        self.assertEqual((fetched, reads), (0, [sharesight.PORTFOLIOS_CACHE]))
        self.assertAlmostEqual(due, sharesight.next_due(), delta=1) # the same answer as reading the list again
        self.assertEqual(portfolios, {'Rob': 445825, 'RobSMSF': 684141})

    def test_next_due_is_90_percent_of_the_ttl(self):
        self.serve_sharesight()
        self.assertEqual(sharesight.next_due(), 0) # cold cache
        sharesight.warm_once()
        due = sharesight.next_due()
        self.assertAlmostEqual(due, 0.9 * min(sharesight.config_cache_seconds, sharesight.config_performance_cache_seconds), delta=5)

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

    def test_error_reports_are_escaped_for_telegram_and_slack(self):
        sent = []
        self.patch(webhook, 'write', lambda service, url, text, *a, **k: sent.append((service, text)))
        self.patch(webhook, 'webhooks', {'telegram': 'https://api.telegram.org/botX/', 'slack': 'https://hooks.slack.com/x', 'discord': 'https://discord.com/x/slack'})
        self.patch(webhook, 'config_telegramChatID', '5')
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


class ChartDelivery(FinbotCase):
    """Charts go to Telegram only. A report whose chart cannot be sent goes out as text instead of vanishing."""

    def setUp(self):
        super().setUp()
        self.patch(webhook, 'sendPhoto', REAL_SEND_PHOTO)

    def test_slack_replies_are_text_and_no_chart_is_drawn_for_them(self):
        def refuse(*a, **k):
            raise AssertionError('a chart was drawn for Slack')
        for name in ('rows_chart', 'pie_chart', 'bar_graph', 'shorts_chart'):
            self.patch(util, name, refuse)
        webhook.webhooks['slack'] = 'https://hooks.slack.com/services/x'
        for cmd in ('.beta', '.pie Rob', '.buy', '.sell', '.peg', '.price', '.price top', '.price T1 7d', '.performance 7d', '.shorts', '.history T1', '.compare T1 T2'):
            with self.subTest(cmd=cmd):
                self.sent.clear(); self.errors.clear()
                worker.process_request('slack', 'C1', '<@U1>', cmd, BOT, 'U', '1')
                self.assertEqual(self.errors, [])
                self.assertTrue(self.sent)
                self.assertEqual({kind for kind, *_ in self.sent}, {'text'})

    def test_a_chart_telegram_refuses_goes_out_as_text(self):
        def post(outcome):
            def fake(url, **kwargs):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            return fake
        text = [('text', ['Heading', 'line 2'])]
        for outcome, expect in ((Resp({'ok': False, 'error_code': 400, 'description': "Bad Request: can't parse entities"}, status=400), text),
                                (Resp(None, status=502), text), (ConnectionError('down'), text),
                                (webhook.requests.exceptions.ReadTimeout('slow'), []), # it may have arrived after all: no duplicate
                                (Resp({'ok': True, 'result': {'message_id': 1}}), [])):
            with self.subTest(outcome=outcome):
                self.sent.clear()
                self.patch(webhook.requests, 'post', post(outcome))
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    webhook.sendPhoto('5', io.BytesIO(b'png'), 'Heading\nline 2', 'telegram', reply_markup={'inline_keyboard': []})
                self.assertEqual(self.sent, expect)


class TelegramWebhook(FinbotCase):
    """bot.py registers the webhook once as it starts. Importing lib.telegram, as every job process does, touches nothing."""

    def setUp(self):
        super().setUp()
        self.patch(telegram, 'webhooks', {'telegram': 'https://api.telegram.org/botX/'})
        self.patch(telegram, 'config_telegramOutgoingWebhook', 'https://example.com/telegram')

    def test_register_unregisters_registers_and_names_the_bot(self):
        calls = []
        def post(url, **kwargs):
            calls.append((url.rsplit('/', 1)[1], kwargs.get('params', {}).get('url')))
            return Resp({'ok': True, 'result': {'username': 'finbot'} if url.endswith('getMe') else True})
        self.patch(telegram.requests, 'post', post)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(telegram.register(), '@finbot')
        self.assertEqual(calls, [('setWebhook', ''), ('setWebhook', 'https://example.com/telegram'), ('getMe', None)])

    def test_a_refused_call_raises(self):
        self.patch(telegram.requests, 'post', lambda url, **k: Resp({'ok': False, 'description': 'Bad Request: bad webhook: HTTPS url must be provided'}))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError) as caught:
            telegram.register()
        self.assertIn('HTTPS url must be provided', str(caught.exception))

    def test_importing_never_calls_telegram(self):
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
