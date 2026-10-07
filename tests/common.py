"""Shared fixture: points finbot at a temp cache dir and replaces every external service
(Telegram, Yahoo, Sharesight, Short Man) with canned data. Nothing here touches the network."""
import os, sys, tempfile, time, unittest
import pandas as pd
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.update(telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok')

from lib import webhook, util, yahoo, sharesight, shortman, worker, charts, telegram, reports
import performance, shorts, price, reminder, cal, trades, milestone, rating

REAL_PAYLOAD_WRAPPER = webhook.payload_wrapper # FinbotCase replaces it; tests of the real thing use this
TICKERS = [f'T{i}' for i in range(25)]
BOT = '@bot'


STATES = ('REGULAR', 'PRE', 'POST', 'CLOSED')


def market_entry(ticker):
    i = int(ticker[1:]) if ticker[1:].isdigit() else 0 # varied data so threshold/sort/sell branches all have rows
    return {'marketState': STATES[i % 4], 'regularMarketTime': time.time(), 'quoteType': 'EQUITY',
            'profile_title': 'Co ' + ticker, 'profile_exchange': 'NasdaqGS', 'percent_change': (i - 12) * 1.5, 'percent_change_premarket': (i - 12) * 1.5, 'percent_change_postmarket': (i - 12) * 1.5,
            'market_cap': 1e9, 'price_to_earnings_trailing': 9, 'price_to_earnings_forward': 9,
            'beta': 2.0, 'short_percent': 20, 'fiftyTwoWeekHigh': 120.0, 'fiftyTwoWeekLow': 80.0,
            'regularMarketPrice': 100.0, 'earnings_date': time.time() + 86400 * 3,
            'ex_dividend_date': time.time() + 86400 * 3, 'recommend': 'buy' if i % 2 else 'sell', 'recommend_index': 1.2 if i % 2 else 4.2,
            'recommend_analysts': 4, 'price_to_earnings_peg': 1.2, 'currency': 'USD'}


class FinbotCase(unittest.TestCase):
    """Base class: self.sent collects ('photo'|'text', ...) tuples for everything the bot tried to send."""

    def patch(self, target, attr, value):
        p = mock.patch.object(target, attr, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        fake = mock.Mock(status_code=200, text='{}')
        fake.json.return_value = {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 5}}}
        self.patch(__import__('requests').Session, 'request', mock.Mock(return_value=fake)) # no real network traffic
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patch(util, 'config_var_dir', tmp.name)
        self.patch(util, 'config_cache_dir', tmp.name)
        self.patch(webhook, 'webhooks', {'telegram': 'https://api.telegram.org/botX/'})
        for m in (performance, shorts, price, cal, trades, milestone, rating, worker, reminder):
            self.patch(m, 'webhooks', webhook.webhooks)
        self.sent = []
        self.patch(webhook, 'sendPhoto', lambda chat, img, cap, svc, **k: self.sent.append(('photo', len(img.read()), cap.split('\n')[0])))
        self.patch(webhook, 'payload_wrapper', lambda svc, url, payload, *a, **k: self.sent.append(('text', payload)) or [])
        self.patch(util, 'get_holdings_and_watchlist', lambda: TICKERS)
        self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t)})
        self.patch(yahoo, 'price_history', lambda t, days=None, **k: ({days: 1.5} if days else {'Max': 5, '1Y': 3}, None))
        self.patch(yahoo, 'prefetch_history', lambda ts: None)
        self.patch(yahoo, 'historic_high', lambda t: (100.0, 50.0))
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=400)
        self.patch(yahoo, 'price_series', lambda t: ('Co ' + t, 'NASDAQ', pd.Series(range(100, 500), index=dates, name=t, dtype=float)))
        self.patch(shortman, 'fetch', lambda md: md)
        holdings = [{'id': i, 'instrument': {'code': t, 'market_code': 'NASDAQ'}, 'portfolio': {'name': 'Rob'},
                     'capital_gain_percent': str(i * 4 - 40), 'value': '1000'} for i, t in enumerate(TICKERS)]
        self.patch(sharesight, 'get_performance_wrapper', lambda d: {1: {'report': {'holdings': holdings}}})
        self.patch(sharesight, 'get_portfolios', lambda: {'Rob': 1})
        self.patch(sharesight, 'get_performance', lambda pid, d, *a: {'report': {
            'holdings': holdings, 'currency_gain_percent': '0', 'capital_gain_percent': '2.5', 'total_gain_percent': '0'}})
        self.patch(sharesight, 'get_trades', lambda name, pid, days=7: [{
            'id': 1, 'transaction_type': 'BUY', 'symbol': 'T1', 'market': 'NASDAQ', 'portfolio': name,
            'transaction_date': time.strftime('%Y-%m-%d'), 'quantity': '10', 'price': '5.0', 'value': '50', 'brokerage_currency_code': 'USD', 'holding_id': 7}])

    def command(self, text, chat='55'):
        """Run a chat message through the real command parser and handlers."""
        self.sent.clear()
        worker.process_request('telegram', chat, '@u', text, BOT, 'U', '1')
        return list(self.sent)
