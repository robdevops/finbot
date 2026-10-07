"""Every chat command and scheduled report produces output on mocked data."""
import unittest
from tests.common import *


class Commands(FinbotCase):
    def test_text_commands(self):
        for cmd in ('.help', '/start', '.hello', '.thanks', '.who', '.plan', '.holdings', '.marketcap',
                    '.pe', '.fpe', '.peg', '.beta', '.buy', '.sell', '.earnings', '.dividend',
                    '.earnings T1', '.dividend T1', '.trades', '.trades 30d', '.price T1', '.session T1',
                    '.premarket T1', '.shorts T1', '.watchlist', '.T1'):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.command(cmd), f'{cmd} sent nothing')

    def test_chart_commands(self):
        for cmd in ('.price', '.price 7d', '.price top', '.price bottom', '.session', '.premarket', '.postmarket',
                    '.performance', '.performance 7d', '.performance 1y', '.shorts', '.peg', '.buy', '.sell', '.beta', '.top10 week'):
            with self.subTest(cmd=cmd):
                out = self.command(cmd)
                self.assertTrue(out, f'{cmd} sent nothing')
                self.assertTrue(any(kind == 'photo' for kind, *_ in out) or cmd.startswith('.top10'), f'{cmd} sent no chart: {out}')

    def test_history_and_compare(self):
        for cmd in ('.history T1', '.compare T1 T2', '.compare T1 T2 3m'):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.command(cmd), f'{cmd} sent nothing')

    def test_trades_and_rating_report_when_nothing_is_stored(self):
        # first run: no state files exist yet, which used to crash these
        for cmd in ('.trades', '.watchlist'):
            self.assertTrue(self.command(cmd), cmd)

    def test_unknown_stickers_and_noise_are_ignored(self):
        self.assertEqual(self.command('lorem ipsum dolor sit amet'), [])


class ReportFunctions(FinbotCase):
    def test_prepare_help(self):
        self.assertTrue(reports.prepare_help('telegram', BOT))

    def test_prepare_holdings(self):
        self.assertTrue(reports.prepare_holdings_payload(None, 'telegram', '@u'))

    def test_prepare_marketcap(self):
        self.assertTrue(reports.prepare_marketcap_payload('telegram', 'top', length=5))

    def test_prepare_rating(self):
        for action in ('buy', 'sell'):
            self.assertTrue(reports.prepare_rating_payload('telegram', action, length=5))

    def test_prepare_value(self):
        for action in ('pe', 'fpe', 'peg', 'beta'):
            with self.subTest(action=action):
                self.assertTrue(reports.prepare_value_payload('telegram', action, length=5))

    def test_prepare_profile(self):
        self.assertTrue(reports.prepare_profile_payload('telegram', '@u', 'T1'))

    def test_prepare_watchlist(self):
        self.assertTrue(reports.prepare_watchlist('telegram', '@u'))

    def test_prepare_compare_usage(self):
        caption = reports.prepare_compare('telegram', ['T1'])[0]
        self.assertIn('Usage', ' '.join(caption))


class ScheduledReports(FinbotCase):
    """The cron entry points (non-interactive: they post to the default channel)."""

    def test_price(self):
        price.lambda_handler()
        self.assertTrue(self.sent)

    def test_performance(self):
        performance.lambda_handler(past_days=7)
        self.assertTrue(self.sent)

    def test_shorts(self):
        shorts.lambda_handler()
        self.assertTrue(self.sent)

    def test_earnings_and_dividends(self):
        for kwargs in ({'earnings': True}, {'dividend': True}):
            with self.subTest(kwargs=kwargs):
                self.sent.clear()
                cal.lambda_handler(**kwargs)
                self.assertTrue(self.sent)

    def test_trades(self):
        trades.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertTrue(self.sent)

    def test_milestone(self):
        milestone.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertTrue(self.sent)

    def test_rating(self):
        rating.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertTrue(self.sent)


class Podcasts(unittest.TestCase):
    def test_format_helpers(self):
        import podcasts
        self.assertEqual(podcasts.format_duration('3725'), '01:02')
        self.assertEqual(podcasts.format_duration('1:02:03'), '01:02')
        self.assertEqual(podcasts.format_duration('nonsense'), '')
        self.assertTrue(podcasts.how_long_ago('Mon, 01 Jan 2024 00:00:00 +0000').endswith('d ago'))


if __name__ == '__main__':
    unittest.main()
