"""Every chat command and scheduled report produces output on mocked data."""
import unittest
import datetime
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
                    '.performance', '.performance 7d', '.performance 1y', '.shorts', '.peg', '.buy', '.sell', '.beta', '.price top 7d'):
            with self.subTest(cmd=cmd):
                out = self.command(cmd)
                self.assertTrue(out, f'{cmd} sent nothing')
                self.assertTrue(any(kind == 'photo' for kind, *_ in out), f'{cmd} sent no chart: {out}')

    def test_one_button_asks_for_both_ratings_reports(self):
        for text in ('.buy & sell', '.buy sell', '.buy/sell', '.buy and sell'):
            with self.subTest(text=text):
                captions = [caption for kind, _, caption in self.command(text) if kind == 'photo']
                self.assertEqual(len(captions), 2, captions)
                self.assertIn('analyst buy ratings', captions[0])
                self.assertIn('analyst sell ratings', captions[1])
        self.assertIn('analyst sell ratings', str(self.command('.sell & buy')[0])) # in the order asked
        self.assertEqual(len(self.command('.buy & buy')), 1) # each report once

    def test_the_keyboard_is_alphabetical_and_every_button_is_a_command(self):
        buttons = [button['text'] for row in charts.command_keyboard()['keyboard'] for button in row]
        self.assertEqual(buttons, sorted(buttons))
        self.assertEqual(len(buttons), 15)
        self.assertIn('.buy & sell', buttons)
        self.assertIn('.forward pe', buttons)
        for text in buttons: # not taken for a ticker by the catch-all .SYMBOL
            with self.subTest(text=text):
                self.assertIsNot(next(handler for pattern, handler in worker.COMMANDS if worker.match(pattern, text, BOT)), worker.on_profile)

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
        self.assertTrue(reports.prepare_holdings_payload(None, 'telegram'))

    def test_prepare_marketcap(self):
        self.assertTrue(reports.prepare_marketcap_payload('telegram', 'top', length=5))

    def test_prepare_rating(self):
        for action in ('buy', 'sell'):
            self.assertTrue(reports.prepare_rating_payload('telegram', action, length=5)[0])

    def test_ratings_list_the_strongest_first(self):
        """1 is a strong buy and 5 a strong sell: .sell used to list the mildest sells first. On equal ratings, more analysts first;
        fewer than 7 analysts and the stock is left out (T7, T8: the ASX small caps that are always a perfect 1.0)."""
        ratings = {'T1': ('buy', 1.5, 7), 'T2': ('strong_buy', 1.2, 12), 'T3': ('buy', 1.5, 9), 'T7': ('strong_buy', 1.0, 6),
                   'T4': ('sell', 4.2, 7), 'T5': ('underperform', 4.6, 10), 'T6': ('sell', 4.2, 8), 'T8': ('strong_buy', 1.0, 2)}
        self.patch(util, 'get_holdings_and_watchlist', lambda: list(ratings))
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | dict(zip(('recommend', 'recommend_index', 'recommend_analysts'), ratings[t]))})
        def order(action):
            payload, chart = reports.prepare_rating_payload('telegram', action)
            return [line.split('Co ')[1].split(' ')[0] for line in payload[1:]], [label for label, _ in chart['rows']]
        self.assertEqual(order('buy'), (['T2', 'T3', 'T1'], ['T2', 'T3', 'T1']))
        self.assertEqual(order('sell'), (['T5', 'T6', 'T4'], ['T5', 'T6', 'T4']))
        self.assertIn('(7+ analysts)', reports.prepare_rating_payload('telegram', 'buy')[0][0])
        self.patch(util, 'get_holdings_and_watchlist', lambda: ['T7', 'T8'])
        self.assertEqual(reports.prepare_rating_payload('telegram', 'buy'), (['No tracked stocks rated buy by 7+ analysts'], None))

    def test_a_small_cap_quoted_in_won_needs_the_bigger_move_too(self):
        """demote_volatile compares market caps in US dollars: unconverted, a small cap quoted in won was never small."""
        self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | ({'regularMarketPrice': 1380.0} if t == 'KRW=X' else {'currency': 'KRW', 'market_cap': 1e11}) for t in ts})
        self.patch(price, 'config_demote_volatile', True)
        quote = price.gather()[1]['T1']
        self.assertAlmostEqual(quote['market_cap_usd'], 1e11 / 1380.0) # US$72M
        self.assertEqual(price.trigger_bar('T1', quote, 5), 5 * price.config_volatility_multiplier)

    def test_market_caps_compare_in_us_dollars(self):
        """Yahoo gives a market cap in the stock's own currency: unconverted, a won market cap topped every list."""
        stocks = {'K1.KS': ('KRW', 1.01e15), 'K2.KS': ('KRW', 5e11), 'U1': ('USD', 5.39e12), 'L1.L': ('GBp', 6.25e10), 'Z1': ('XYZ', 1e12)}
        fx = {'KRW=X': 1380.0, 'GBP=X': 0.79} # units per US dollar; nothing for XYZ
        def fetch(tickers):
            return {t: market_entry(t) | {'regularMarketPrice': fx[t]} if t in fx else market_entry(t) | {'currency': stocks[t][0], 'market_cap': stocks[t][1], 'beta': 2.0}
                    for t in tickers if t in fx or t in stocks}
        self.patch(yahoo, 'fetch', fetch)
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: fetch([t]))
        self.patch(util, 'get_holdings_and_watchlist', lambda: list(stocks))
        payload = reports.prepare_marketcap_payload('telegram')
        self.assertIn('by market cap (USD)', payload[0])
        self.assertEqual([line.split('Co ')[1].split(' ')[0] for line in payload[1:]], ['U1', 'K1.KS', 'L1.L', 'K2.KS']) # Z1: no rate, left out
        self.assertIn('mkt cap: 731.88 B', payload[2]) # 1.01 Q won
        self.assertIn('mkt cap: KRW 1.01 Q (USD 731.88 B)', reports.prepare_marketcap_payload('telegram', 'K1.KS')[0])
        self.assertIn('mkt cap: GBP 62.50 B (USD 79.11 B)', reports.prepare_marketcap_payload('telegram', 'L1.L')[0]) # pence quote, pound cap
        beta = reports.prepare_beta_payload('telegram')[0]
        self.assertIn('Co K2.KS', str(beta)) # 500 billion won is US$362M: a small cap, which it never was unconverted
        self.assertNotIn('Co K1.KS', str(beta))

    def test_prepare_value(self):
        for action, heading in (('pe', 'Top 5 tracked stocks by pe ratio'), ('bottom forward pe', 'Bottom 5 tracked stocks by forward pe ratio'),
                                ('peg', 'Top 5 tracked stocks by peg ratio'), ('negative peg', 'negative peg: no data found')):
            with self.subTest(action=action):
                payload, chart = reports.prepare_value_payload('telegram', action, length=5)
                self.assertIn(heading, payload[0])

    def test_prepare_beta(self):
        payload, chart = reports.prepare_beta_payload('telegram')
        self.assertIn('Beta over 1.5', payload[0])
        self.assertEqual(len(chart['rows']), len(payload) - 1) # a bar per stock listed
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'beta': 1.0}})
        self.assertEqual(reports.prepare_beta_payload('telegram'), (['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'], None))

    def test_prepare_profile(self):
        self.assertTrue(reports.prepare_profile_payload('telegram', '@u', 'T1'))

    def test_a_profile_leaves_out_what_yahoo_did_not_send(self):
        """Each of these fields missing (or a zero equity) used to crash the whole profile."""
        full = market_entry('T1') | {'insiderBuy': 1, 'insiderSell': 0, 'insiderBuyValue': 5e6, 'insiderSellValue': 0, 'netIncomeToCommon': 1e6,
                                     'sharesOutstanding': 1e6, 'shareholder_equity': 1e9, 'total_debt': 9e8, 'total_cash': 1e8, 'profile_industry': 'Tools'}
        for missing in ('marketState', 'profile_exchange', 'market_cap', 'currency', 'regularMarketPrice', 'sharesOutstanding', 'percent_change'):
            with self.subTest(missing=missing):
                self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: {k: v for k, v in full.items() if k != missing}})
                self.assertIn('Co T1', reports.prepare_profile_payload('telegram', '@u', 'T1')[0])
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: full | {'shareholder_equity': 0}})
        self.assertNotIn('Net debt/equity', str(reports.prepare_profile_payload('telegram', '@u', 'T1')))

    def test_a_profile_warns_of_a_ps_ratio_only_above_15(self):
        for ps, warned in ((12.3, False), (15.1, True)): # forward P/E 99 warns (above 30): its warning used to show on the PS line too
            with self.subTest(ps=ps):
                self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'price_to_sales': ps, 'price_to_earnings_forward': 99, 'profile_industry': 'Tools'}})
                line = next(line for line in reports.prepare_profile_payload('telegram', '@u', 'T1') if 'PS ratio' in line)
                self.assertEqual('⚠️' in line, warned, line)

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
        for kwargs in ({'event': 'earnings'}, {'event': 'ex-dividend'}):
            with self.subTest(kwargs=kwargs):
                self.sent.clear()
                cal.lambda_handler(**kwargs)
                self.assertTrue(self.sent)

    def test_earnings_skip_an_adr_whose_primary_listing_yahoo_does_not_know(self):
        """T1 has no earnings date, so its primary listing is looked up; Yahoo knowing nothing of it used to crash the report."""
        self.patch(cal, 'primary_listing', {'T1': 'T1.XX'})
        self.patch(yahoo, 'fetch', lambda ts: {t: {k: v for k, v in market_entry(t).items() if not (t == 'T1' and k == 'earnings_date')} for t in ts})
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1.XX' else {t: market_entry(t)})
        cal.lambda_handler(event='earnings')
        self.assertIn('Co T2 ', str(self.sent))
        self.assertNotIn('Co T1 ', str(self.sent))

    def test_trades(self):
        trades.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertTrue(self.sent)

    def test_trades_asks_yahoo_only_for_new_trades(self):
        fetched = []
        self.patch(yahoo, 'fetch', lambda tickers: fetched.append(set(tickers)) or {t: market_entry(t) for t in tickers})
        trades.lambda_handler()
        self.assertEqual(fetched, [{'T1'}])
        fetched.clear()
        trades.lambda_handler() # the trade is known now: nothing to report and nothing to fetch
        self.assertEqual(fetched, [])

    def test_milestone(self):
        milestone.lambda_handler()
        self.assertTrue(self.sent)

    def test_milestone_records_a_ticker_only_with_its_new_values(self):
        """A first sighting without 52-week values used to be recorded as 0/0, so the next run reported a record high for it."""
        self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0)) # beyond the 52-week range (120/80): nothing new
        self.patch(yahoo, 'fetch', lambda ts: {t: {k: v for k, v in market_entry(t).items() if not k.startswith('fiftyTwoWeek')} for t in ts})
        milestone.lambda_handler()
        self.assertFalse(util.json_load('finbot_milestone.json', persist=True))
        self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
        self.sent.clear()
        milestone.lambda_handler()
        self.assertNotIn('Record high', str(self.sent))
        self.assertEqual(util.json_load('finbot_milestone.json', persist=True)['T1'], {'record_high': 150.0, 'record_low': 50.0}) # all-time

    def test_milestone_records_are_all_time(self):
        """A new 52-week high below the all-time high is no record. The record used to become the 52-week high after the first
        run, so a stock far below its peak posted a record high each time it set a new 52-week one."""
        self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
        milestone.lambda_handler() # first sighting: the 52-week range (120/80) is inside the history (150/50)
        for high, expected in ((130.0, False), (160.0, True), (155.0, False)):
            with self.subTest(high=high):
                self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'fiftyTwoWeekHigh': high} for t in ts})
                self.sent.clear()
                milestone.lambda_handler()
                self.assertEqual('Record high' in str(self.sent), expected)

    def test_a_52_week_record_kept_before_is_replaced_by_the_history(self):
        util.json_write('finbot_milestone.json', {f'T{i}': {'high': 110.0, 'low': 90.0} for i in range(25)}, persist=True)
        self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
        milestone.lambda_handler() # 120 beats the old 52-week record of 110, but not the history's 150
        self.assertNotIn('Record high', str(self.sent))

    def test_rating(self):
        rating.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertTrue(self.sent)

    def test_rating_keeps_the_last_rating_of_a_ticker_missing_from_a_run(self):
        rating.lambda_handler() # records every ticker's rating
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1' else {t: market_entry(t)})
        rating.lambda_handler() # no T1 this time: its rating used to be dropped from the record
        self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | ({'recommend': 'sell', 'recommend_index': 4.5} if t == 'T1' else {})})
        self.sent.clear()
        rating.lambda_handler()
        self.assertIn('Co T1 ', str(self.sent)) # so its change from buy to sell went unreported

    def test_an_interactive_rating_records_nothing(self):
        rating.lambda_handler(interactive=True, service='telegram', chat_id='5')
        self.assertIsNone(util.json_load('finbot_rating.json', persist=True))

    def test_slack_webhook_without_a_bot_token_gets_scheduled_reports(self):
        """Scheduled reports reach Slack through its incoming webhook, which takes no channel and no token. They used to send
        Telegram's chat id along, which made write() need slackBotToken and crash without one, before Telegram got its copy."""
        self.patch(webhook, 'config_slackBotToken', False)
        webhook.webhooks['slack'] = 'https://hooks.slack.com/services/T/B/x'
        self.patch(webhook, 'payload_wrapper', REAL_PAYLOAD_WRAPPER)
        self.patch(webhook, 'sendPhoto', REAL_SEND_PHOTO)
        posts = []
        def post(url, **kwargs):
            posts.append((url.split('/')[2], 'Authorization' in kwargs.get('headers', {}), (kwargs.get('json') or {}).get('channel')))
            return mock.Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 1}}})
        self.patch(webhook.net, 'post', post)
        for report in (price.lambda_handler, shorts.lambda_handler, milestone.lambda_handler):
            with self.subTest(report=report):
                posts.clear()
                report()
                self.assertIn(('hooks.slack.com', False, None), posts)
                self.assertTrue(any(host == 'api.telegram.org' for host, _, _ in posts))

    def test_nowhere_to_post_is_an_error(self):
        self.patch(webhook, 'webhooks', {})
        with self.assertRaisesRegex(RuntimeError, 'nowhere to post'):
            price.lambda_handler()


class PeriodButtons(FinbotCase):
    """Default views line up with the buttons: the highlighted button is the period actually shown."""

    def buttons(self, command):
        self.command(command)
        self.assertTrue(self.markups and self.markups[0], f'{command} sent no buttons')
        return [b['text'] for b in self.markups[0]['inline_keyboard'][0]]

    def test_performance_defaults_to_one_month(self):
        self.assertEqual(self.buttons('.performance'), ['7D', '● 1M', '3M', '1Y', 'Max'])
        self.assertIn('month', self.sent[0][2]) # "Performance over the past month", not 4 weeks

    def test_performance_period_argument_moves_the_marker(self):
        self.assertEqual(self.buttons('.performance 7d'), ['● 7D', '1M', '3M', '1Y', 'Max'])
        self.assertEqual(self.buttons('.performance 1y'), ['7D', '1M', '3M', '● 1Y', 'Max'])

    def test_price_list_has_a_1d_button_marked_by_default(self):
        self.assertEqual(self.buttons('.price'), ['● 1D', '7D', '1M', '3M', '1Y', 'Max'])
        self.assertEqual(self.buttons('.price top'), ['● 1D', '7D', '1M', '3M', '1Y', 'Max'])
        self.assertEqual(self.buttons('.price 1m'), ['1D', '7D', '● 1M', '3M', '1Y', 'Max'])

    def test_other_charts_do_not_offer_1d(self):
        for command in ('.performance', '.compare T1 T2'):
            with self.subTest(command=command):
                self.assertNotIn('1D', [b.lstrip('● ') for b in self.buttons(command)])

    def press(self, data):
        edits, toasts = [], []
        self.patch(webhook, 'editMessageMedia', lambda chat, msg, img, caption, markup=None: edits.append((caption.split('\n')[0], markup)))
        self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: toasts.append(text))
        worker.process_callback('telegram', 'cb', '55', '9', data)
        return edits, toasts

    def test_pressing_1d_rebuilds_todays_list_and_moves_the_marker(self):
        edits, toasts = self.press('c|l|d|3,0')
        self.assertEqual(toasts, ['Loading 1D…'])
        self.assertEqual(self.errors, [])
        self.assertEqual(len(edits), 1)
        self.assertEqual([b['text'] for b in edits[0][1]['inline_keyboard'][0]][0], '● 1D')

    def test_a_button_a_chart_does_not_offer_is_ignored(self):
        edits, toasts = self.press('c|f|d|') # performance has no 1D
        self.assertEqual((edits, toasts), ([], [None]))
        edits, toasts = self.press('c|l|zz|3,0')
        self.assertEqual((edits, toasts), ([], [None]))


class Podcasts(FinbotCase):
    def test_format_helpers(self):
        import podcasts
        self.assertEqual(podcasts.format_duration('3725'), '01:02')
        self.assertEqual(podcasts.format_duration('1:02:03'), '01:02')
        self.assertEqual(podcasts.format_duration('62:05'), '01:02')
        self.assertEqual(podcasts.format_duration('nonsense'), '')
        self.assertTrue(podcasts.how_long_ago(podcasts.published('Mon, 01 Jan 2024 00:00:00 +0000')).endswith('d ago'))
        self.assertEqual(podcasts.published('Mon, 01 Jan 2024 00:00:00 -0000').tzinfo, datetime.timezone.utc) # no zone given: UTC
        self.assertIsNone(podcasts.published('yesterday'))

    def test_new_episodes_are_posted_once_newest_first(self):
        """A feed whose items mix dated and undated ones used to crash the sort (aware and naive times)."""
        import podcasts
        def item(n, date):
            return f'<item><guid>g{n}</guid><title>Show: ep {n}</title><enclosure url="https://x/{n}.mp3"/>{date}<itunes:duration>600</itunes:duration></item>'
        feed = ('<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Show</title>'
                + item(1, '<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>') + item(2, '') + item(3, '<pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>')
                + '</channel></rss>').encode()
        self.patch(podcasts.net, 'get', lambda url, **k: mock.Mock(content=feed, raise_for_status=lambda: None))
        podcasts.lambda_handler('https://example.com/feed')
        self.assertEqual([line.split(' (')[0] for line in self.sent[0][1]], ['📣 Show: <a href="https://x/3.mp3">ep 3</a> 00:10',
                         '📣 Show: <a href="https://x/1.mp3">ep 1</a> 00:10', '📣 Show: <a href="https://x/2.mp3">ep 2</a> 00:10'])
        self.sent.clear()
        podcasts.lambda_handler('https://example.com/feed')
        self.assertEqual(self.sent, []) # all seen now


if __name__ == '__main__':
    unittest.main()


class PieCommand(FinbotCase):
    def setUp(self):
        super().setUp()
        def holdings(name, pid):
            data = [('A', 'Semiconductors', 'Electronic Technology', 500), ('B', 'Semiconductors', 'Electronic Technology', 300),
                    ('C', 'Biotechnology', 'Health Technology', 200), ('D', None, None, 100), ('E', 'Gold', 'Minerals', 0)]
            return {c + ':NASDAQ': {'code': c, 'market_code': 'NASDAQ', 'industry_classification_name': i,
                                    'sector_classification_name': s, 'value': v} for c, i, s, v in data}
        self.patch(sharesight, 'get_holdings_new', holdings)

    def test_by_industry_default(self):
        sent = self.command('.pie Rob')
        self.assertEqual(sent[0][0], 'photo')
        self.assertIn('Rob by industry', sent[0][2])

    def test_by_sector_and_payload(self):
        payload, chart = reports.prepare_pie('rob', 'sector', 'telegram')
        self.assertEqual([r[0] for r in chart['rows']], ['Electronic Technology', 'Health Technology', 'Unclassified'])
        self.assertIn('Electronic Technology: 72.7%', payload) # 800 of 1100; zero-value Gold is left out
        self.assertEqual(self.command('.pie Rob sector')[0][0], 'photo')

    def test_folds_into_other_and_renders(self):
        self.patch(sharesight, 'get_holdings_new', lambda n, p: {f'T{i}:X': {'code': f'T{i}', 'industry_classification_name': f'Ind {i}', 'value': 100 - i} for i in range(12)})
        payload, chart = reports.prepare_pie('Rob', 'industry', 'telegram')
        self.assertEqual(len(chart['rows']), 8)
        self.assertEqual(chart['rows'][-1][0], 'Other')
        self.assertTrue(util.pie_chart(chart['rows'], chart['title'], chart['subtitle']).read().startswith(b'\x89PNG'))

    def test_unknown_or_missing_portfolio_lists_known(self):
        for text, first in (('.pie', '.pie: please try again'), ('.pie Nope', 'Nope portfolio not found')):
            sent = self.command(text)
            self.assertTrue(sent[0][1][0].startswith(first), text)
            self.assertIn('Rob', sent[0][1])

    def test_text_only_service(self):
        worker.Request('discord', '1', '@u', 'U', BOT).deliver(['x'], {'pie': True, 'rows': [('a', 1.0)], 'title': 't'})
        self.assertEqual(self.sent[-1][0], 'text')
