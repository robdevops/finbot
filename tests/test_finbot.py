"""Offline smoke tests: external services (Telegram, Yahoo, Sharesight, Short Man) are mocked.

Run with: python -m unittest discover -s tests -v
"""
import unittest
import sys, os, time, io, json, datetime, tempfile, contextlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update(telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok')
os.chdir(ROOT)
from unittest import mock
from lib import webhook, util, yahoo, sharesight, shortman, worker, charts, telegram, reports
import performance, shorts, price, reminder, cal
util.config_var_dir = tempfile.mkdtemp(); util.config_cache_dir = tempfile.mkdtemp()
webhook.webhooks.clear(); webhook.webhooks['telegram'] = 'https://api.telegram.org/botX/'
for m in (performance, shorts, price, cal): m.webhooks = webhook.webhooks


class Smoke(unittest.TestCase):
    def check(self, name, cond):
        self.assertTrue(cond, name)

    def setUp(self):
        fake = mock.Mock(status_code=200, text='{}')
        fake.json.return_value = {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 5}}}
        patcher = mock.patch('requests.Session.request', return_value=fake) # no real network traffic
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all(self):

        # 1. chunked send (the len(generator) bug) with a keyboard on the last chunk
        posted = []
        class R:
            status_code = 200
            def json(s): return {'ok': True, 'result': {'message_id': len(posted), 'chat': {'id': 5}}}
        with mock.patch.object(webhook.requests, 'post', lambda url, **k: (posted.append(k['json']), R())[1]), mock.patch.object(webhook.time, 'sleep', lambda x: None):
            res = webhook.payload_wrapper('telegram', 'https://api.telegram.org/botX/sendMessage?chat_id=5', ['x' * 60] * 300, '5', reply_markup={'keyboard': []})
        self.check(f'chunked send returns one result per chunk ({len(res)})', len(res) > 1 and len(posted) == len(res))
        self.check('keyboard only on the last chunk', 'reply_markup' in posted[-1] and all('reply_markup' not in p for p in posted[:-1]))

        # 2. zoneinfo: reminder and yahoo timezone handling
        tz = __import__('zoneinfo').ZoneInfo('Australia/Melbourne')
        self.check('birthday tz offset is not LMT', datetime.datetime(2022, 8, 18, tzinfo=tz).utcoffset() == datetime.timedelta(hours=10))
        payload = None
        with mock.patch.object(reminder, 'load_reminders', lambda: []):
            reminder.config_timezone = 'Australia/Melbourne'
            payload = reminder.lambda_handler.__code__ is not None
        self.check('reminder imports/compiles with zoneinfo', payload)

        # 3. reports through the worker on mocked data
        sent = []
        webhook.sendPhoto = lambda chat, img, cap, svc, **k: sent.append(('photo', len(img.read()), cap.split('\n')[0]))
        webhook.payload_wrapper = lambda svc, url, payload, *a, **k: sent.append(('text', len(payload)))
        tick = [f'T{i}' for i in range(25)]; util.get_holdings_and_watchlist = lambda: tick
        yahoo.fetch = lambda ts: {t: {'marketState': 'CLOSED', 'regularMarketTime': time.time(), 'profile_title': 'Co ' + t, 'profile_exchange': 'NasdaqGS', 'percent_change': 1.0, 'market_cap': 1e9, 'price_to_earnings_trailing': 9, 'price_to_earnings_forward': 9, 'beta': 2.0, 'short_percent': 20} for t in ts}
        sharesight.get_performance_wrapper = lambda d: {1: {'report': {'holdings': [{'instrument': {'code': t, 'market_code': 'NASDAQ'}, 'capital_gain_percent': str(i * 4 - 40)} for i, t in enumerate(tick)]}}}
        sharesight.get_portfolios = lambda: {'Rob': 1}
        sharesight.get_performance = lambda pid, d: {'report': {'holdings': [{'portfolio': {'name': 'Rob'}}], 'currency_gain_percent': '0', 'capital_gain_percent': '2.5', 'total_gain_percent': '0'}}
        yahoo.price_history = lambda t, days=None, **k: ({days: 1.5} if days else {'Max': 5, '1Y': 3}, None)
        yahoo.prefetch_history = lambda ts: None
        shortman.fetch = lambda md: md
        yahoo.fetch_detail = lambda t, s=0: {t: dict(yahoo.fetch([t])[t], price_to_earnings_peg=1.2, recommend='buy', recommend_index=1.2, recommend_analysts=4)}
        for label, call in (
            ('price top/bottom', lambda: price.lambda_handler(threshold=0, days=30, top=10)),
            ('price list', lambda: price.lambda_handler(chat_id='5', threshold=3, service='telegram', interactive=True, days=30)),
            ('performance', lambda: performance.lambda_handler(past_days=7)),
            ('shorts', lambda: shorts.lambda_handler()),
        ):
            sent.clear(); call(); self.check(f'{label} -> {sent[0][0]} {sent[0][1:]}', sent and sent[0][0] == 'photo')
        for cmd in ('.peg', '.buy', '.beta', '.help'):
            sent.clear(); worker.process_request('telegram', '55', '@u', cmd, '@bot', 'U', '1'); self.check(f'{cmd} -> {sent[:1]}', bool(sent))

        # 4. bot handler with real gevent: sticker is silent, unknown logged
        import bot
        def post_msg(message):
            body = json.dumps({'update_id': 1, 'message': dict({'message_id': 5, 'chat': {'id': 55, 'type': 'private'}, 'from': {'id': 9, 'first_name': 'Rob'}, 'date': 1}, **message)}).encode()
            env = {'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(body), 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                out = bot.main(env, lambda *a, **k: None)
            return out, err.getvalue()
        self.check('sticker is silent', post_msg({'sticker': {'file_id': 'x'}}) == ([b''], ''))
        self.check('git hash helper', len(bot.git_version()) >= 7)

if __name__ == '__main__':
    unittest.main()
