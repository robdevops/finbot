"""Failure and no-data scenarios: empty or broken upstream data, bad requests, rejected callers."""
import contextlib, io, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
import gevent
from tests.common import *

COMMANDS = ('.price', '.price 7d', '.price top', '.session', '.premarket', '.performance 7d', '.shorts', '.peg', '.buy',
            '.sell', '.beta', '.pe', '.marketcap', '.earnings', '.dividend', '.trades', '.holdings', '.watchlist',
            '.T1', '.history T1', '.compare T1 T2')


class UpstreamEmpty(FinbotCase):
    """Yahoo answers, but with nothing usable. Every command must reply sanely and never crash."""

    ONE_LINE_ERROR = ('.history T1', '.compare T1 T2') # these say so with a single error line when the ticker has no data

    def run_all(self):
        for cmd in COMMANDS:
            with self.subTest(cmd=cmd):
                if cmd in self.ONE_LINE_ERROR:
                    self.sent.clear(); self.errors.clear()
                    worker.process_request('telegram', '55', '@u', cmd, BOT, 'U')
                    self.assertLessEqual(len(self.errors), 1, cmd)
                else:
                    self.command(cmd)

    def test_yahoo_returns_empty_dict(self):
        self.patch(yahoo, 'fetch', lambda ts: {})
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {})
        self.run_all()

    def test_yahoo_raises(self):
        def down(*a, **k):
            raise RuntimeError('Yahoo API unavailable')
        for name in ('fetch', 'fetch_detail', 'price_series'):
            self.patch(yahoo, name, down)
        for cmd in ('.price', '.peg', '.T1', '.compare T1 T2'):
            with self.subTest(cmd=cmd):
                self.sent.clear(); self.errors.clear()
                worker.process_request('telegram', '55', '@u', cmd, BOT, 'U')
                self.assertEqual(len(self.errors), 1, cmd) # exactly one one-line report, not a traceback to the user
                self.assertTrue(self.errors[0].startswith('⚠️'))

    def test_sharesight_down_is_reported_once(self):
        def down(*a, **k):
            raise RuntimeError('Sharesight performance error: boom')
        self.patch(sharesight, 'get_performance_wrapper', down)
        self.patch(sharesight, 'get_performance', down)
        self.patch(sharesight, 'get_portfolios', down)
        self.sent.clear(); self.errors.clear()
        worker.process_request('telegram', '55', '@u', '.performance 7d', BOT, 'U')
        self.assertEqual(len(self.errors), 1)

    def test_a_failed_command_stops_typing_before_saying_why(self):
        def down(*a, **k):
            raise RuntimeError('Sharesight performance error: boom')
        self.patch(sharesight, 'get_portfolios', down)
        typing_when_reported = []
        self.patch(webhook, 'report_error', lambda e, *a, **k: typing_when_reported.append([t.is_active() for t in self.typing]))
        worker.process_request('telegram', '55', '@u', '.performance 7d', BOT, 'U')
        self.assertEqual(typing_when_reported, [[False]]) # its one indicator had stopped when the error line went out

    def test_no_holdings_and_empty_watchlist(self):
        self.patch(util, 'get_holdings_and_watchlist', lambda: [])
        for cmd in ('.watchlist', '.price', '.earnings'):
            with self.subTest(cmd=cmd):
                self.command(cmd)


class WatchlistActions(FinbotCase):
    def test_add_duplicate_delete_and_unknown_action(self):
        add = self.command('.watchlist add MSFT')
        self.assertTrue(add)
        self.assertEqual(util.json_load('finbot_watchlist.json', persist=True), ['MSFT'])
        again = self.command('.watchlist add MSFT')
        self.assertNotEqual(add, again) # a duplicate is reported differently from a first add
        self.assertEqual(util.json_load('finbot_watchlist.json', persist=True), ['MSFT'])
        self.command('.watchlist rm MSFT')
        self.assertEqual(util.json_load('finbot_watchlist.json', persist=True), [])
        self.assertIn('not a valid watchlist action', str(self.command('.watchlist frobnicate MSFT')))


class BadArguments(FinbotCase):
    def test_compare_argument_errors_give_usage(self):
        for cmd in ('.compare', '.compare T1', '.compare T1 T2 T3 T4 T5 T6 T7', '.compare T1 T1'):
            with self.subTest(cmd=cmd):
                self.assertIn('Usage', str(self.command(cmd)))

    def test_compare_with_a_ticker_that_has_no_history(self):
        def no_history(t):
            raise RuntimeError(f'no price history for {t}')
        self.patch(yahoo, 'price_series', no_history)
        self.sent.clear(); self.errors.clear()
        worker.process_request('telegram', '55', '@u', '.compare T1 T2', BOT, 'U')
        self.assertEqual(len(self.errors), 1)

    def test_history_without_a_ticker_or_with_extra_argument_gives_usage(self):
        self.assertEqual(self.command('.history'), [('text', ['Usage: .history SYMBOL'])]) # not the profile of a ticker called HISTORY
        self.assertEqual(self.command('.history T1 1y'), [('text', ['Usage: .history SYMBOL'])])


class PortfolioNames(FinbotCase):
    def test_an_unknown_portfolio_gets_the_same_answer_everywhere(self):
        for cmd in ('.trades 7d Nope', '.performance Nope', '.holdings Nope', '.pie Nope'):
            with self.subTest(cmd=cmd): # it used to be a ValueError, "no Sharesight data found", or two wordings of this
                self.assertEqual(self.command(cmd), [('text', ['Nope portfolio not found. I only know about:', 'Rob'])])

    def test_a_portfolio_name_in_any_case(self):
        self.patch(sharesight, 'get_holdings_new', lambda name, pid: {'T1:NASDAQ': {'code': 'T1', 'market_code': 'NASDAQ', 'name': 'Co T1', 'holding_id': 1}})
        self.assertIn('Holdings for Rob (1)', str(self.command('.holdings rob')))

    def test_trades_with_no_buy_or_sell_still_get_an_answer(self):
        self.patch(sharesight, 'get_trades', lambda name, pid, days=7: [{'id': 2, 'transaction_type': 'DIVIDEND', 'portfolio': name}])
        self.assertIn('No trades', str(self.command('.trades 7d'))) # it used to say nothing at all


class CommandArguments(FinbotCase):
    def test_period_and_portfolio_in_either_order(self):
        for text, expected in (('', (30, None)), ('7d', (7, None)), ('Rob', (30, 'Rob')), ('7d Rob', (7, 'Rob')), ('Rob 7d', (7, 'Rob')),
                               ('My Portfolio', (30, 'My Portfolio')), ('My Portfolio 3m', (90, 'My Portfolio')), ('Rob ', (30, 'Rob'))):
            with self.subTest(text=text):
                self.assertEqual(worker.period_and_portfolio(text, 30), expected)

    def test_a_percentage_is_a_number_and_nan_a_ticker(self):
        for arg, expected in (('', (5, None)), ('2.5', (2.5, None)), ('3%', (3.0, None)), ('T1', (5, 'T1')), ('nan', (5, 'NAN')), ('inf', (5, 'INF'))):
            with self.subTest(arg=arg):
                self.assertEqual(worker.percent_or_ticker(arg, 5), expected)
        self.assertIn('2.5%', str(self.command('.session 2.5'))) # a threshold, not a ticker called 2.5

    def test_a_bare_number_on_price_is_a_percent(self):
        """As on .session, .premarket and .shorts, and as the README has it; a period carries its unit."""
        self.assertIn('3% at close', str(self.command('.price 3'))) # it used to be a 3-day report
        self.assertIn('Price movement 3%', str(self.command('.price 3 7d'))) # the 3 used to be dropped
        self.assertIn('Price movement 5%', str(self.command('.price 7d')))

    def test_top_is_gone(self):
        self.assertIn('Co TOP', str(self.command('.top 7d'))) # .price top 7d is the command; .top is a ticker now, like any word

    def test_a_ratio_command_reads_its_ticker_as_the_other_commands_do(self):
        self.assertIn('Co T1 ', str(self.command('.pe t1')))
        self.assertIn('Top 15 tracked stocks by pe ratio', str(self.command('.pe top '))) # trailing space and all

    def test_hello_leaves_the_word_list_as_it_was(self):
        before = list(worker.verb)
        for _ in range(30):
            line = self.command('.hello')[0][1][0]
            self.assertNotIn("('", line) # a verb, not a tuple of them
            self.assertTrue(line.endswith(' you, U! 😇'), line)
        self.assertEqual(worker.verb, before)
        self.assertEqual(self.command('hi there'), []) # hello by name only: "hi @bot"


class WsgiRejections(FinbotCase):
    SECRET = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}

    def request(self, path='/telegram', body=None, headers=None):
        body = body if isinstance(body, bytes) else json.dumps(body if body is not None else {}).encode()
        env = {'PATH_INFO': path, 'wsgi.input': io.BytesIO(body), **(headers or {})}
        status = []
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            out = bot.main(env, lambda s, *a, **k: status.append(s))
        return b''.join(out), status[-1]

    def test_telegram_requires_the_secret_header(self):
        message = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'text': '.help'}}
        self.assertIn(b'Unauthorized', self.request(body=message)[0])
        self.assertIn(b'Unauthorized', self.request(body=message, headers={'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'wrong'})[0])
        self.assertEqual(self.sent, []) # nothing was processed

    def test_unknown_path_is_404(self):
        self.assertEqual(self.request(path='/nope')[1], '404 Not Found')

    def test_malformed_body_is_refused_not_a_crash(self):
        self.assertEqual(self.request(body=b'not json')[1], '403 Forbidden') # no secret: turned away before the body is read
        for body in (b'not json', b'', b'[1, 2]', b'7'):
            self.assertEqual(self.request(body=body, headers=self.SECRET)[1], '400 Bad Request', body)
        self.assertEqual(self.errors, [])

    def test_strangers_cannot_post_into_the_chats(self):
        self.patch(bot, 'config_slackOutgoingWebhook', 'https://example.com/slack')
        self.patch(bot, 'config_slackOutgoingToken', 'stok')
        for path, body, headers, status in (('/', b'', {}, '404 Not Found'), ('/wp-login.php', b'log=x&pwd=y', {}, '404 Not Found'),
                ('/telegram', b'log=x', {}, '403 Forbidden'), ('/telegram', {'message': {}}, {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'wrong'}, '403 Forbidden'),
                ('/slack', b'', {}, '400 Bad Request'), ('/slack', b'token=stok', {}, '400 Bad Request'), ('/slack', {'type': 'event_callback'}, {}, '403 Forbidden'),
                ('/slack', {'token': 'wrong', 'type': 'event_callback'}, {}, '403 Forbidden'), ('/slack', {'token': 'stok'}, {}, '200 OK')):
            with self.subTest(path=path, body=body):
                self.assertEqual(self.request(path, body, headers)[1], status)
        self.assertEqual(self.errors, []) # nothing reached the chats
        self.assertEqual(self.sent, [])

    def test_a_failure_before_authentication_is_only_logged(self):
        def broken(*a, **k):
            raise RuntimeError('boom')
        self.patch(bot, 'urlparse', broken) # fails while routing, before the secret is even looked at
        env = {'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(b'{}'), **self.SECRET}
        status = []
        with contextlib.redirect_stderr(io.StringIO()) as err:
            bot.main(env, lambda s, *a, **k: status.append(s))
        self.assertEqual((status[-1][:3], self.errors), ('500', []))
        self.assertIn('boom', err.getvalue())

    def test_a_failure_after_authentication_is_reported_once_and_not_retried(self):
        broken = {'message': {'message_id': 1, 'from': {'first_name': 'A'}, 'text': '.help'}} # no chat
        self.assertEqual(self.request(body=broken, headers=self.SECRET)[1], '200 OK') # a retry would only fail and report again
        self.assertEqual(len(self.errors), 1)
        self.assertIn("KeyError: 'chat'", self.errors[0])

    def test_telegram_edge_updates(self):
        secret = self.SECRET
        self.assertEqual(self.request(body={'edited_message': {}}, headers=secret)[0], b'Unsupported')
        self.assertEqual(self.request(body={'callback_query': {'id': '1'}}, headers=secret)[0], b'Unsupported')
        odd = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'new_chat_members': []}}
        self.assertIn(b'Unhandled', self.request(body=odd, headers=secret)[0])

    def test_button_presses_are_logged(self):
        calls = []
        self.patch(worker, 'process_callback', lambda *a: calls.append(a))
        secret = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
        for sender, who in (({'username': 'rob', 'first_name': 'Rob'}, '@rob'), ({'first_name': 'Ann'}, 'Ann'), ({}, 'unknown')):
            body = json.dumps({'callback_query': {'id': '1', 'from': sender, 'data': 'j|7|abcd', 'message': {'message_id': 9, 'chat': {'id': 55}}}}).encode()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                bot.main({'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(body), **secret}, lambda *a, **k: None)
            self.assertIn(f'[Telegram button]: {who} chat 55 j|7|abcd', err.getvalue())


class SlackEvents(FinbotCase):
    """Slack sends every message in a subscribed channel, the bot's own posts included."""

    def setUp(self):
        super().setUp()
        self.patch(bot, 'config_slackOutgoingWebhook', 'https://example.com/slack')
        self.patch(bot, 'config_slackOutgoingToken', 'stok')
        self.requests = []
        self.patch(worker, 'process_request', lambda *a: self.requests.append(a))

    def event(self, **event):
        body = json.dumps({'token': 'stok', 'type': 'event_callback', 'authorizations': [{'user_id': 'UBOT'}],
            'event': dict({'type': 'message', 'channel': 'C1', 'ts': '1.2'}, **event)}).encode()
        status = []
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            bot.main({'PATH_INFO': '/slack', 'wsgi.input': io.BytesIO(body)}, lambda s, *a, **k: status.append(s))
        gevent.sleep(0.05) # the worker runs in a (gevent) thread
        return status[-1]

    def test_only_people_are_answered(self):
        for event in ({'subtype': 'bot_message', 'bot_id': 'B1', 'text': "⚠️ /slack: KeyError: 'user'"}, # a webhook report
                      {'user': 'UBOT', 'bot_id': 'B2', 'text': '.holdings: Please try again'}, # this bot's own reply
                      {'user': 'UBOT', 'text': '.holdings'},
                      {'subtype': 'channel_join', 'user': 'U1', 'text': '<@U1> has joined the channel'},
                      {'subtype': 'message_changed', 'message': {'text': '.price'}},
                      {'text': '.price'}): # no user at all
            with self.subTest(event=event):
                self.assertEqual(self.event(**event), '200 OK')
        self.assertEqual((self.requests, self.errors), ([], []))
        self.assertEqual(self.event(user='U1', text='.price <@UBOT>'), '200 OK')
        self.assertEqual(self.event(user='U2', subtype='thread_broadcast', text='.trades'), '200 OK')
        self.assertEqual([(r[0], r[1], r[2], r[3], r[4]) for r in self.requests],
                         [('slack', 'C1', '<@U1>', '.price @UBOT', '@UBOT'), ('slack', 'C1', '<@U2>', '.trades', '@UBOT')])

    def test_slack_does_not_change_the_telegram_bot_name(self):
        self.patch(bot, 'botName', '@finbot_tg')
        self.event(user='U1', text='.price')
        self.assertEqual(bot.botName, '@finbot_tg')


class UserTextIsEscaped(FinbotCase):
    """Replies go out as Telegram HTML: text a user wrote is shown, never read as markup. One stray < in a .plan entry made Telegram
    refuse that reply and every .plan reply after it."""

    def test_a_plan_is_shown_as_text(self):
        reply = self.command('.plan buy <cheap> & hold')[0][1]
        self.assertIn('<i>buy &lt;cheap&gt; &amp; hold</i>', reply[0])
        self.assertEqual(self.command('.plan')[0][1], reply) # and the same way again
        self.sent.clear()
        worker.process_request('slack', 'C1', '<@U1>', '.plan sell &lt;dear&gt;', BOT, 'U') # Slack escapes what it sends
        text = '\n'.join(self.sent[0][1])
        self.assertIn('*<@U1>*', text) # a Slack mention stays markup
        self.assertIn('_sell &lt;dear&gt;_', text) # escaped once, not twice
        self.assertIn('_buy &lt;cheap&gt; &amp; hold_', text)

    def test_a_telegram_name_is_escaped_where_it_arrives(self):
        requests = []
        self.patch(worker, 'process_request', lambda *a: requests.append(a))
        body = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A<b>&'}, 'text': '.hello'}}
        env = {'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(json.dumps(body).encode()), 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
        with contextlib.redirect_stderr(io.StringIO()):
            bot.main(env, lambda *a, **k: None)
        gevent.sleep(0.05) # the worker runs in a (gevent) thread
        self.assertEqual((requests[0][2], requests[0][5]), ('@A&lt;b&gt;&amp;', '@A&lt;b&gt;&amp;')) # the handle and the name


class SecretsStayOutOfLogs(FinbotCase):
    """A failed request's error message carries its URL: the Telegram token, a Slack or Discord webhook path, a Yahoo crumb."""
    SECRET_URL = 'https://api.telegram.org/bot123456:SECRET-tok_en/sendMessage?chat_id=1'

    def stderr_of(self, call):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            call()
        return err.getvalue()

    def test_a_failed_send_logs_no_token(self):
        def refuse(url, **kwargs):
            raise ConnectionError(f"Max retries exceeded with url: {url} (headers {kwargs.get('headers')})")
        self.patch(webhook.net, 'post', refuse)
        self.patch(webhook, 'config_slackBotToken', 'xoxb-SECRET')
        log = self.stderr_of(lambda: webhook.write('telegram', self.SECRET_URL, 'hi', '1'))
        log += self.stderr_of(lambda: webhook.write('slack', 'https://hooks.slack.com/services/T0/B0/SECRETpath', 'hi', 'C1'))
        self.assertIn('Failure sending', log)
        for secret in ('SECRET-tok_en', 'SECRETpath', 'xoxb-SECRET'):
            self.assertNotIn(secret, log)

    def test_the_traceback_of_a_reported_error_is_redacted(self):
        self.patch(webhook, 'report_error', REAL_REPORT_ERROR)
        self.patch(webhook, 'write', lambda *a, **k: None)
        try:
            raise ConnectionError('failed: ' + self.SECRET_URL)
        except ConnectionError as e:
            log = self.stderr_of(lambda: webhook.report_error(e, 'telegram', '55', context='x'))
        self.assertIn('Traceback', log)
        self.assertIn('bot<redacted>', log)
        self.assertNotIn('SECRET-tok_en', log)


class SharedSession(unittest.TestCase):
    def test_the_session_keeps_no_cookies(self):
        """Yahoo's cookie goes in an explicit header: a stored one would be sent to fc.yahoo.com, which then sets no new one."""
        import email.message, urllib.request
        from lib import net
        headers = email.message.Message()
        headers['Set-Cookie'] = 'A3=d=AQAB; Max-Age=31557600; Domain=.yahoo.com; Path=/; Secure'
        response = type('Response', (), {'info': lambda self: headers})()
        net.session.cookies.extract_cookies(response, urllib.request.Request('https://fc.yahoo.com/'))
        self.assertEqual(len(net.session.cookies), 0)


class StartupSignals(unittest.TestCase):
    """A reload (SIGHUP) that arrives while the bot is still starting must not kill it."""

    def test_sighup_during_startup_is_ignored_and_works_afterwards(self):
        skip_if_old_env(self)
        with tempfile.TemporaryDirectory() as data:
            env = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k not in config.STARTUP_KEYS}
            env.update(DATA_DIR=data, port='0', scheduler='False')
            proc = subprocess.Popen([sys.executable, '-u', 'bot.py'], cwd=ROOT, env=env, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            deadline = time.monotonic() + 30
            while not int(Path(f'/proc/{proc.pid}/status').read_text().split('SigIgn:')[1].split()[0], 16) & 1: # until SIGHUP is ignored
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.001)
            proc.send_signal(signal.SIGHUP) # still importing: the default action would kill it
            lines = []
            for line in proc.stderr:
                lines.append(line)
                if line.startswith('Opening socket'):
                    break
            self.assertIsNone(proc.poll(), ''.join(lines))
            time.sleep(1) # the handler goes in just before serving
            proc.send_signal(signal.SIGHUP)
            for line in proc.stderr: # a reload now runs (there is no preferences.conf here, so it says so)
                lines.append(line)
                if 'reload requested' in line:
                    break
            self.assertIsNone(proc.poll(), ''.join(lines))
            self.assertIn('reload requested but', ''.join(lines))

    def test_usr1_flushes_the_cache_and_keeps_the_state(self):
        skip_if_old_env(self)
        with tempfile.TemporaryDirectory() as data:
            cache = Path(data, 'cache')
            (cache / 'matplotlib').mkdir(parents=True)
            for name in ('finbot_yahoo_cookie.json', 'finbot_graph_T1_None.png', 'finbot_x.json.abc.tmp'): # the last: a write in flight
                (cache / name).write_text('{}')
            Path(data, 'finbot_watchlist.json').write_text('["T1"]') # state, not cache
            env = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k not in config.STARTUP_KEYS}
            env.update(DATA_DIR=data, port='0', scheduler='False')
            proc = subprocess.Popen([sys.executable, '-u', 'bot.py'], cwd=ROOT, env=env, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            deadline = time.monotonic() + 30
            while not int(Path(f'/proc/{proc.pid}/status').read_text().split('SigIgn:')[1].split()[0], 16) & (1 << (signal.SIGUSR1 - 1)):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.001)
            proc.send_signal(signal.SIGUSR1) # still starting: ignored, where its default action would kill the bot
            lines = []
            for line in proc.stderr:
                lines.append(line)
                if line.startswith('Opening socket'):
                    break
            self.assertIsNone(proc.poll(), ''.join(lines))
            self.assertEqual(len(os.listdir(cache)), 4) # nothing flushed yet
            time.sleep(1) # the handler goes in just before serving
            proc.send_signal(signal.SIGUSR1)
            for line in proc.stderr:
                lines.append(line)
                if 'cache: flushed' in line:
                    break
            self.assertIn('cache: flushed 2 files', ''.join(lines))
            self.assertEqual(sorted(os.listdir(cache)), ['finbot_x.json.abc.tmp', 'matplotlib'])
            self.assertTrue(Path(data, 'finbot_watchlist.json').exists())


if __name__ == '__main__':
    unittest.main()
