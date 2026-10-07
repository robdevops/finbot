"""Failure and no-data scenarios: empty or broken upstream data, bad requests, rejected callers."""
import contextlib, io, json, unittest
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
                    worker.process_request('telegram', '55', '@u', cmd, BOT, 'U', '1')
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
                worker.process_request('telegram', '55', '@u', cmd, BOT, 'U', '1')
                self.assertEqual(len(self.errors), 1, cmd) # exactly one one-line report, not a traceback to the user
                self.assertTrue(self.errors[0].startswith('⚠️'))

    def test_sharesight_down_is_reported_once(self):
        def down(*a, **k):
            raise RuntimeError('Sharesight performance error: boom')
        self.patch(sharesight, 'get_performance_wrapper', down)
        self.patch(sharesight, 'get_performance', down)
        self.patch(sharesight, 'get_portfolios', down)
        self.sent.clear(); self.errors.clear()
        worker.process_request('telegram', '55', '@u', '.performance 7d', BOT, 'U', '1')
        self.assertEqual(len(self.errors), 1)

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
        for cmd in ('.compare T1', '.compare T1 T2 T3 T4 T5 T6 T7', '.compare T1 T1'):
            with self.subTest(cmd=cmd):
                self.assertIn('Usage', str(self.command(cmd)))

    def test_compare_with_a_ticker_that_has_no_history(self):
        def no_history(t):
            raise RuntimeError(f'no price history for {t}')
        self.patch(yahoo, 'price_series', no_history)
        self.sent.clear(); self.errors.clear()
        worker.process_request('telegram', '55', '@u', '.compare T1 T2', BOT, 'U', '1')
        self.assertEqual(len(self.errors), 1)

    def test_history_with_extra_argument_is_rejected_cleanly(self):
        self.assertTrue(self.command('.history'))
        self.assertTrue(self.command('.history T1 1y'))


class WsgiRejections(FinbotCase):
    def request(self, path='/telegram', body=None, headers=None):
        body = json.dumps(body if body is not None else {}).encode()
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

    def test_malformed_body_is_a_500_not_a_crash(self):
        env = {'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(b'not json')}
        status = []
        with contextlib.redirect_stderr(io.StringIO()):
            bot.main(env, lambda s, *a, **k: status.append(s))
        self.assertTrue(status[-1].startswith('500'))

    def test_telegram_edge_updates(self):
        secret = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
        self.assertEqual(self.request(body={'edited_message': {}}, headers=secret)[0], b'Unsupported')
        self.assertEqual(self.request(body={'callback_query': {'id': '1'}}, headers=secret)[0], b'Unsupported')
        odd = {'message': {'message_id': 1, 'chat': {'id': 5}, 'from': {'first_name': 'A'}, 'new_chat_members': []}}
        self.assertIn(b'Unhandled', self.request(body=odd, headers=secret)[0])


if __name__ == '__main__':
    unittest.main()
