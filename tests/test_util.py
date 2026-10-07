"""Pure helpers in lib/util.py: table-driven pass and fail cases."""
import datetime, unittest
from tests.common import *


class Parsing(unittest.TestCase):
    def test_days_from_human_days(self):
        for arg, days in (('7', 7), ('7d', 7), ('7D', 7), ('2w', 14), ('3m', 90), ('1y', 365), ('0', 0)):
            with self.subTest(arg=arg):
                self.assertEqual(util.days_from_human_days(arg), days)
        today = datetime.date.today()
        self.assertEqual(util.days_from_human_days('ytd'), (today - today.replace(month=1, day=1)).days)

    def test_days_from_human_days_rejects_non_periods(self):
        for arg in ('AAPL', '', 'x5d', '1.5y', 'week'):
            with self.subTest(arg=arg), self.assertRaises(ValueError):
                util.days_from_human_days(arg)

    def test_transform_to_yahoo(self):
        for args, expected in ((('AAPL',), 'AAPL'), (('FANG', 'ASX'), 'FANG.AX'), (('ARM', 'NASDAQ'), 'ARM'),
                               (('ARM:NASDAQ',), 'ARM'), (('BHP.AX',), 'BHP.AX'), (('0700', 'HKG'), '0700.HK'),
                               (('BRK', 'B'), 'BRK-B'), (('2330', 'TAI'), '2330.TW'), (('VOD', 'LSE'), 'VOD.L')):
            with self.subTest(args=args):
                self.assertEqual(util.transform_to_yahoo(*args), expected)

    def test_transform_title(self):
        self.assertEqual(util.transform_title('APPLE INC'), 'Apple')
        self.assertEqual(util.transform_title('Acme FPO'), 'Acme')
        self.assertEqual(util.transform_title('Mixed Case Name'), 'Mixed Case Name')


class Formatting(unittest.TestCase):
    def test_signed_percent(self):
        for value, decimals, expected in ((12, None, '+12%'), (-3.5, None, '-3.5%'), (0, None, '0%'), (1234, None, '+1,234%'),
                                          (2.345, 1, '+2.3%'), (-0.04, 1, '-0.0%')):
            with self.subTest(value=value):
                self.assertEqual(util.signed_percent(value, decimals), expected)

    def test_days_english(self):
        for days, expected in ((None, 'today'), (0, 'today'), (1, 'the past day'), (7, 'the past week')):
            with self.subTest(days=days):
                self.assertEqual(util.days_english(days), expected)

    def test_date_range_english(self):
        end = datetime.date(2026, 10, 5)
        self.assertEqual(util.date_range_english(7, end), '28 Sep - 5 Oct 2026')
        self.assertEqual(util.date_range_english(30, end), '5 Sep - 5 Oct 2026')
        self.assertEqual(util.date_range_english(10, datetime.date(2026, 1, 5)), '26 Dec 2025 - 5 Jan 2026') # crosses a year
        with self.assertRaises(TypeError):
            util.date_range_english(None, end) # callers must pass a period

    def test_ordinal(self):
        for number, suffix in ((1, 'st'), (2, 'nd'), (3, 'rd'), (4, 'th'), (11, 'th'), (12, 'th'), (13, 'th'), (21, 'st'), (112, 'th')):
            with self.subTest(number=number):
                self.assertEqual(util.ordinal(number), suffix)

    def test_get_emoji(self):
        self.assertEqual([util.get_emoji(n) for n in (1, -1, 0)], ['🔼', '🔻', '▪️'])

    def test_links_per_service(self):
        telegram_link = util.link('https://example.com/x', 'text', 'telegram')
        slack_link = util.link('https://example.com/x', 'text', 'slack')
        self.assertIn('<a href=', telegram_link)
        self.assertIn('|text', slack_link)

    def test_flags_for_known_and_unknown_markets(self):
        self.assertTrue(util.flag_from_ticker('BHP.AX'))
        self.assertTrue(util.flag_from_ticker('AAPL'))
        self.assertIsInstance(util.flag_from_ticker('XYZ.ZZ'), str) # unknown suffix must not crash


class StateFiles(FinbotCase):
    def test_json_roundtrip_and_missing_file(self):
        self.assertIsNone(util.json_load('absent.json', persist=True))
        util.json_write('state.json', {'a': [1, 2]}, persist=True)
        self.assertEqual(util.json_load('state.json', persist=True), {'a': [1, 2]})

    def test_read_cache_missing_or_expired_is_falsy(self):
        self.assertFalse(util.read_cache('absent.json', 60))
        util.json_write('old.json', {'a': 1})
        self.assertFalse(util.read_cache('old.json', -1)) # already expired

    def test_binary_cache_roundtrip(self):
        self.assertFalse(util.read_binary_cache('absent.png'))
        util.write_binary_cache('img.png', io.BytesIO(b'png-bytes'))
        self.assertEqual(util.read_binary_cache('img.png').read(), b'png-bytes')

    def test_holdings_and_watchlist_without_a_watchlist_file(self):
        # first run: no watchlist exists yet
        self.patch(util.sharesight, 'get_holdings_wrapper', lambda: ['AAPL', 'GOOG', 'GOOGL'])
        self.patch(util, 'get_holdings_and_watchlist', REAL_GET_HOLDINGS)
        self.assertEqual(util.get_holdings_and_watchlist(), ['AAPL', 'GOOG']) # GOOGL dropped when GOOG is present
        util.json_write('finbot_watchlist.json', ['MSFT'], persist=True)
        self.assertEqual(util.get_holdings_and_watchlist(), ['AAPL', 'GOOG', 'MSFT'])


if __name__ == '__main__':
    unittest.main()
