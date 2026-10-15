"""Every chat command and scheduled report produces output on mocked data."""
import unittest
import datetime
from tests.common import *


class Commands(FinbotCase):
	def test_text_commands(self):
		"""Every text command answers."""
		for cmd in ('.help', '/start', '.who', '.plan', '.holdings', '.marketcap',
					'.pe', '.fpe', '.peg', '.beta', '.buy', '.sell', '.earnings', '.dividend',
					'.earnings T1', '.dividend T1', '.trades', '.trades 30d', '.price T1', '.session T1',
					'.premarket T1', '.shorts T1', '.watchlist', '.T1'):
			with self.subTest(cmd=cmd):
				self.assertTrue(self.command(cmd), f'{cmd} sent nothing')

	def test_chart_commands(self):
		"""Every chart command answers with a chart."""
		for cmd in ('.price', '.price 7d', '.price top', '.price bottom', '.session', '.premarket', '.postmarket',
					'.performance', '.performance 7d', '.performance 1y', '.shorts', '.peg', '.buy', '.sell', '.beta', '.price top 7d',
					'.forward pe', '.fpe bottom'):
			with self.subTest(cmd=cmd):
				out = self.command(cmd)
				self.assertTrue(out, f'{cmd} sent nothing')
				self.assertTrue(any(kind == 'photo' for kind, *_ in out), f'{cmd} sent no chart: {out}')

	def test_one_button_asks_for_both_ratings_reports(self):
		""".buy & sell (and its spellings) sends both ratings reports, in the order asked, each once."""
		for text in ('.buy & sell', '.buy sell', '.buy/sell', '.buy and sell'):
			with self.subTest(text=text):
				captions = [caption for kind, _, caption in self.command(text) if kind == 'photo']
				self.assertEqual(len(captions), 2, captions)
				self.assertIn('analyst buy ratings', captions[0])
				self.assertIn('analyst sell ratings', captions[1])
		self.assertIn('analyst sell ratings', str(self.command('.sell & buy')[0])) # in the order asked
		self.assertEqual(len(self.command('.buy & buy')), 1) # each report once

	def test_the_keyboard_is_alphabetical_and_every_button_is_its_command(self):
		"""The command keyboard is alphabetical, and each button runs the command it belongs to in the table, not taken
		for a ticker by .SYMBOL."""
		buttons = [button['text'] for row in worker.command_keyboard()['keyboard'] for button in row]
		self.assertEqual(buttons, sorted(buttons))
		self.assertIn('.buy & sell', buttons)
		self.assertIn('.forward pe', buttons)
		for command in worker.COMMANDS:
			for text in command.buttons:
				with self.subTest(text=text):
					self.assertIs(worker.read(text, BOT)[0], command)

	def test_history_and_compare(self):
		""".history and .compare answer."""
		for cmd in ('.history T1', '.compare T1 T2', '.compare T1 T2 3m'):
			with self.subTest(cmd=cmd):
				self.assertTrue(self.command(cmd), f'{cmd} sent nothing')

	def test_trades_and_watchlist_report_when_nothing_is_stored(self):
		"""On the first run no state files exist yet, which used to crash .trades and .watchlist."""
		for cmd in ('.trades', '.watchlist'):
			self.assertTrue(self.command(cmd), cmd)

	def test_unknown_stickers_and_noise_are_ignored(self):
		"""A message that is no command gets no answer."""
		self.assertEqual(self.command('lorem ipsum dolor sit amet'), [])


class ReportFunctions(FinbotCase):
	def test_help_headings_are_bold_on_slack(self):
		"""On Slack each heading is bold, with the blank line before it outside the markers: *\nPrice:* is not bold."""
		text = about.prepare_help(SLACK, BOT, worker.help_sections())
		self.assertIn('*Price:*', text)
		self.assertEqual([line for line in text if line.startswith('*\n')], [])

	def test_help_comes_from_the_command_table(self):
		""".help lists every command's lines from the table, under its section's heading, the sections in order; and
		each line names a command that runs it."""
		text = about.prepare_help(TELEGRAM, BOT, worker.help_sections())
		headings = [line for line in text if line.startswith('<b>')]
		self.assertEqual(headings[:len(worker.SECTIONS)], [f"<b>{s}:</b>" for s in worker.SECTIONS])
		self.assertTrue(all(text[text.index(heading) - 1] == '' for heading in headings[1:])) # a blank line before
		for command in worker.COMMANDS:
			for line in command.usage:
				with self.subTest(line=line):
					self.assertIn(line, text)
					called = worker.read(line.replace('SYMBOL', 'T1'), BOT)[0]
					self.assertIs(called, command)

	def test_a_portfolio_with_no_holdings_is_reported_by_name(self):
		"""Its name used to be read from its first holding: an empty portfolio crashed .performance."""
		self.patch(sharesight, 'get_performance', lambda pid, d, *a: {'report': {'holdings': [], 'capital_gain_percent': '0.0'}})
		payload, _ = performance.report(TELEGRAM, 7)
		self.assertTrue(any('>Rob</a>' in line for line in payload), payload)

	def test_prepare_holdings(self):
		""".holdings without a portfolio lists the portfolios."""
		self.assertTrue(holdings.prepare_holdings_payload(None, TELEGRAM))

	def test_prepare_marketcap(self):
		"""The market cap list is built."""
		self.assertTrue(rankings.marketcap_list(TELEGRAM, length=5))

	def test_prepare_rating(self):
		"""The buy and sell lists are built."""
		for action in ('buy', 'sell'):
			self.assertTrue(rankings.prepare_rating_payload(TELEGRAM, action, length=5)[0])

	def test_ratings_list_the_strongest_first(self):
		"""1 is a strong buy and 5 a strong sell: .sell used to list the mildest sells first. On equal ratings, more analysts first;
		fewer than 7 analysts and the stock is left out (T7, T8: the ASX small caps that are always a perfect 1.0)."""
		ratings = {'T1': ('buy', 1.5, 7), 'T2': ('strong_buy', 1.2, 12), 'T3': ('buy', 1.5, 9), 'T7': ('strong_buy', 1.0, 6),
				   'T4': ('sell', 4.2, 7), 'T5': ('underperform', 4.6, 10), 'T6': ('sell', 4.2, 8), 'T8': ('strong_buy', 1.0, 2)}
		self.patch(watchlist, 'with_holdings', lambda: list(ratings))
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | dict(zip(('recommend', 'recommend_index', 'recommend_analysts'), ratings[t]))})
		def order(action):
			"""(the tickers listed, the tickers charted) of a ratings report, in order."""
			payload, chart = rankings.prepare_rating_payload(TELEGRAM, action)
			return [line.split('Co ')[1].split(' ')[0] for line in payload[1:]], [label for label, _ in chart.rows]
		self.assertEqual(order('buy'), (['T2', 'T3', 'T1'], ['T2', 'T3', 'T1']))
		self.assertEqual(order('sell'), (['T5', 'T6', 'T4'], ['T5', 'T6', 'T4']))
		self.assertIn('(7+ analysts)', rankings.prepare_rating_payload(TELEGRAM, 'buy')[0][0])
		self.patch(watchlist, 'with_holdings', lambda: ['T7', 'T8'])
		self.assertEqual(rankings.prepare_rating_payload(TELEGRAM, 'buy'), (['No tracked stocks rated buy by 7+ analysts'], None))

	def test_a_small_cap_quoted_in_won_needs_the_bigger_move_too(self):
		"""demote_volatile compares market caps in US dollars: unconverted, a small cap quoted in won was never small."""
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | ({'regularMarketPrice': 1380.0} if t == 'KRW=X' else {'currency': 'KRW', 'market_cap': 1e11}) for t in ts})
		self.prefs(demote_volatile=True)

		quote = price.gather()[1]['T1']
		self.assertAlmostEqual(quote['market_cap_usd'], 1e11 / 1380.0) # US$72M
		self.assertEqual(price.trigger_bar('T1', quote, 5, {}), 5 * config.prefs.volatility_multiplier)

	def test_a_short_top_list_repeats_none_of_its_best_as_the_worst(self):
		"""With fewer than twice `top` stocks, the Bottom list leaves out those in the Top list (it repeated them), and
		with none left there is no Bottom list and no gap in the chart; the subtitle says "over the past 3 months"."""
		for count, bottom, bars in ((12, 2, 13), (8, 0, 8)):
			with self.subTest(count=count):
				self.patch(watchlist, 'with_holdings', lambda: TICKERS[:count])
				found = price.moves('period', 0, 90, interactive=True)
				payload, chart = price.report(TELEGRAM, found, 'period', 0, 90, top=10, interactive=True)
				shown = payload[payload.index('<b>Bottom 10</b>') + 1:] if bottom else []
				self.assertEqual((len(shown), len(chart.rows)), (bottom, bars))
				self.assertEqual(len(payload), 1 + min(count, 10) + (bottom and 2 + bottom))
				self.assertEqual(chart.subtitle, '% change over the past 3 months') # it said "in 3 months"

	def test_the_small_caps_betas_are_fetched_together(self):
		"""A scheduled price report asks for the beta of each small cap that moved (US$150M to US$1B): together, not one by one."""
		calls = []
		self.patch(yahoo, 'fetch_details', lambda tickers, strict=False: calls.append(sorted(tickers)) or {t: market_entry(t) for t in tickers})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: self.fail('a beta fetched on its own'))
		self.prefs(demote_volatile=True)

		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'market_cap': 5e8} for t in ts})
		price.run()
		self.assertEqual(len(calls), 1)
		self.assertTrue(calls[0])

	def test_forward_pe_lists_need_as_many_analysts_as_buy(self):
		"""A forward P/E is analysts' estimate: with few of them it says little, as a perfect 1.0 buy from two brokers does."""
		analysts = {'T1': 7, 'T2': 6, 'T3': 12, 'T4': 2}
		self.patch(watchlist, 'with_holdings', lambda: list(analysts))
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'price_to_earnings_forward': -5 if t == 'T3' else 20} for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'recommend_analysts': analysts[t]}})
		def listed(mode='top'):
			"""(heading, the tickers listed, the chart) of a forward P/E list."""
			payload, chart = rankings.ratio_list(TELEGRAM, 'forward pe', mode)
			return payload[0], [line.split('Co ')[1].split(' ')[0] for line in payload[1:]], chart
		heading, names, chart = listed()
		# T2 and T4: too few analysts; T3: negative
		self.assertEqual((names, [label for label, _ in chart.rows]), (['T1'], ['T1']))
		self.assertIn('forward pe ratio (7+ analysts)', heading)
		self.assertEqual(listed('negative')[1], ['T3'])
		self.assertIn('Co T2', rankings.ratio_line(TELEGRAM, 'T2', 'forward pe')) # one ticker asked for: shown
		self.prefs(min_analysts=13) # the one setting moves .buy and .forward pe together
		self.assertEqual(listed()[0], 'No tracked stocks with 13+ analysts have a forward pe ratio')
		self.assertEqual(rankings.prepare_rating_payload(TELEGRAM, 'buy')[0], ['No tracked stocks rated buy by 13+ analysts'])

	def test_market_caps_compare_in_us_dollars(self):
		"""Yahoo gives a market cap in the stock's own currency: unconverted, a won market cap topped every list."""
		stocks = {'K1.KS': ('KRW', 1.01e15), 'K2.KS': ('KRW', 5e11), 'U1': ('USD', 5.39e12), 'L1.L': ('GBp', 6.25e10), 'Z1': ('XYZ', 1e12)}
		fx = {'KRW=X': 1380.0, 'GBP=X': 0.79} # units per US dollar; nothing for XYZ
		def fetch(tickers):
			"""Quotes in each stock's own currency, and the exchange rates."""
			return {t: market_entry(t) | {'regularMarketPrice': fx[t]} if t in fx else market_entry(t) | {'currency': stocks[t][0], 'market_cap': stocks[t][1], 'beta': 2.0}
					for t in tickers if t in fx or t in stocks}
		self.patch(yahoo, 'fetch', fetch)
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: fetch([t]))
		self.patch(watchlist, 'with_holdings', lambda: list(stocks))
		payload = rankings.marketcap_list(TELEGRAM)
		self.assertIn('by market cap (USD)', payload[0])
		self.assertEqual([line.split('Co ')[1].split(' ')[0] for line in payload[1:]], ['U1', 'K1.KS', 'L1.L', 'K2.KS']) # Z1: no rate, left out
		self.assertIn('mkt cap: 731.88 B', payload[2]) # 1.01 Q won
		self.assertIn('mkt cap: KRW 1.01 Q (USD 731.88 B)', rankings.marketcap_line(TELEGRAM, 'K1.KS'))
		self.assertIn('mkt cap: GBP 62.50 B (USD 79.11 B)', rankings.marketcap_line(TELEGRAM, 'L1.L')) # pence: pounds
		beta = rankings.prepare_beta_payload(TELEGRAM)[0]
		self.assertIn('Co K2.KS', str(beta)) # 500 billion won is US$362M: a small cap, which it never was unconverted
		self.assertNotIn('Co K1.KS', str(beta))

	def test_prepare_value(self):
		"""Each ratio report has its heading: top, bottom, and negative (with none found)."""
		for kind, mode, heading in (('pe', 'top', 'Top 5 tracked stocks by pe ratio'),
				('forward pe', 'bottom', 'Bottom 5 tracked stocks by forward pe ratio'),
				('peg', 'top', 'Top 5 tracked stocks by peg ratio'),
				('peg', 'negative', 'negative peg: no data found')):
			with self.subTest(kind=kind, mode=mode):
				payload, chart = rankings.ratio_list(TELEGRAM, kind, mode, length=5)
				self.assertIn(heading, payload[0])

	def test_one_stocks_ratio_shows_what_yahoo_has(self):
		""".pe of a loss-maker shows its forward P/E (it used to say nothing), .peg labels its figure, and a stock
		without the ratio asked for, or one Yahoo does not know, is said to have none."""
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'price_to_earnings_trailing': None} for t in ts
			if not t.startswith('NONE')})
		self.assertEqual(self.command('.pe T1')[0][1][0].split(') ')[1], 'PE: forward 9')
		self.assertEqual(self.command('.peg T1')[0][1][0].split(') ')[1], 'PEG: 1.2')
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'price_to_earnings_peg': None}})
		self.assertEqual(self.command('.peg T1'), [('text', ['T1: no peg ratio found'])])
		self.assertEqual(self.command('.pe NONE.L'), [('text', ['NONE.L: no data found'])])

	def test_pe_sends_its_chart_as_forward_pe_and_peg_do(self):
		""".pe builds a chart, and now sends it."""
		self.assertEqual([kind for kind, *_ in self.command('.pe')], ['photo'])

	def test_prepare_beta(self):
		"""The beta report charts a bar per stock listed, and says so when none qualify."""
		payload, chart = rankings.prepare_beta_payload(TELEGRAM)
		self.assertIn('Beta over 1.5', payload[0])
		self.assertEqual(len(chart.rows), len(payload) - 1) # a bar per stock listed
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'beta': 1.0}})
		self.assertEqual(rankings.prepare_beta_payload(TELEGRAM), (['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'], None))

	def test_prepare_profile(self):
		"""A company profile is built."""
		self.assertTrue(profile.prepare_profile_payload(TELEGRAM, '@u', 'T1'))

	def test_a_profile_leaves_out_what_yahoo_did_not_send(self):
		"""Each of these fields missing (or a zero equity) used to crash the whole profile."""
		full = market_entry('T1') | {'insiderBuy': 1, 'insiderSell': 0, 'insiderBuyValue': 5e6, 'insiderSellValue': 0, 'netIncomeToCommon': 1e6,
									 'sharesOutstanding': 1e6, 'shareholder_equity': 1e9, 'total_debt': 9e8, 'total_cash': 1e8, 'profile_industry': 'Tools'}
		for missing in ('marketState', 'profile_exchange', 'market_cap', 'currency', 'regularMarketPrice', 'sharesOutstanding', 'percent_change'):
			with self.subTest(missing=missing):
				self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: {k: v for k, v in full.items() if k != missing}})
				self.assertIn('Co T1', profile.prepare_profile_payload(TELEGRAM, '@u', 'T1')[0])
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: full | {'shareholder_equity': 0}})
		self.assertNotIn('Net debt/equity', str(profile.prepare_profile_payload(TELEGRAM, '@u', 'T1')))

	def test_a_profile_signs_its_changes(self):
		"""A profile signs its price changes, as .history does: +3% over a year, +1.5% pre-market."""
		profile = '\n'.join(self.command('.T13')[0][1]) # T13 is pre-market, up 1.5%
		self.assertIn('<b>1Y:</b> +3%', profile)
		self.assertIn('<b>Pre-market:</b> +1.5%', profile)

	def test_a_profile_warns_of_a_ps_ratio_only_above_15(self):
		"""The PS ratio line warns only above 15; the forward P/E's warning used to show on it too."""
		for ps, warned in ((12.3, False), (15.1, True)): # forward P/E 99 warns (above 30): its warning used to show on the PS line too
			with self.subTest(ps=ps):
				self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'price_to_sales': ps, 'price_to_earnings_forward': 99, 'profile_industry': 'Tools'}})
				line = next(line for line in profile.prepare_profile_payload(TELEGRAM, '@u', 'T1') if 'PS ratio' in line)
				self.assertEqual('⚠️' in line, warned, line)

	def test_prepare_watchlist(self):
		"""The watchlist is listed."""
		self.assertTrue(holdings.prepare_watchlist(TELEGRAM, '@u'))

	def test_compare_usage(self):
		""".compare with one ticker gets its usage, from the command table."""
		usage = 'Usage: .compare SYMBOL SYMBOL [... up to 6] [period]'
		self.assertEqual(self.command('.compare T1'), [('text', [usage])])


class ScheduledReports(FinbotCase):
	"""The cron entry points (non-interactive: they post to the default channel)."""

	def test_price(self):
		"""The scheduled price report posts."""
		price.run()
		self.assertTrue(self.sent)

	def test_performance(self):
		"""The scheduled performance report posts."""
		performance.run(past_days=7)
		self.assertTrue(self.sent)

	def test_shorts(self):
		"""The scheduled shorts report posts."""
		shorts.run()
		self.assertTrue(self.sent)

	def test_earnings_and_dividends(self):
		"""The scheduled earnings and ex-dividend reports post."""
		for kwargs in ({'event': 'earnings'}, {'event': 'ex-dividend'}):
			with self.subTest(kwargs=kwargs):
				self.sent.clear()
				cal.run(**kwargs)
				self.assertTrue(self.sent)

	def test_only_the_scheduled_earnings_report_is_pinned(self):
		"""The scheduled earnings report is pinned on Telegram; a reply to .earnings is not, or the chat would collect
		pinned copies, and neither is the ex-dividend report."""
		pins = []
		self.patch(transports.TelegramBot, 'pin', lambda chat, answers: pins.append(chat.where))
		self.command('.earnings')
		self.assertEqual(pins, [])
		self.env(webhooks={'telegram': 'https://api.telegram.org/botX/'}, telegramChatID='1')
		cal.run(event='ex-dividend')
		cal.run(event='earnings')
		self.assertEqual(pins, ['1'])

	def test_earnings_skip_an_adr_whose_primary_listing_yahoo_does_not_know(self):
		"""T1 has no earnings date, so its primary listing is looked up; Yahoo knowing nothing of it used to crash the report."""
		self.patch(cal, 'primary_listings', lambda: {'T1': 'T1.XX'})
		self.patch(yahoo, 'fetch', lambda ts: {t: {k: v for k, v in market_entry(t).items() if not (t == 'T1' and k == 'earnings_date')} for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1.XX' else {t: market_entry(t)})
		cal.run(event='earnings')
		self.assertIn('Co T2 ', str(self.sent))
		self.assertNotIn('Co T1 ', str(self.sent))

	def test_trades(self):
		""".trades run from a chat posts."""
		trades.run(transports.TelegramBot('5'))
		self.assertTrue(self.sent)

	def test_a_trade_is_in_its_market_currency_not_the_brokerage_one(self):
		"""A NASDAQ trade is in US dollars, though Yahoo names the exchange NasdaqGS and the broker charges in
		Australian dollars (it used to say AUD)."""
		self.patch(sharesight, 'get_trades', lambda name, pid, days=7: [{'id': 1, 'transaction_type': 'BUY',
			'symbol': 'T1', 'market': 'NASDAQ', 'portfolio': name, 'transaction_date': time.strftime('%Y-%m-%d'),
			'quantity': '10', 'price': '5.0', 'value': '50', 'brokerage_currency_code': 'AUD', 'holding_id': 7}])
		self.assertIn(' USD 50 ', self.command('.trades')[0][1][-1])

	def test_trades_asks_yahoo_only_for_new_trades(self):
		"""A scheduled trades run asks Yahoo only about trades it has not reported, and nothing once all are known."""
		fetched = []
		self.patch(yahoo, 'fetch', lambda tickers: fetched.append(set(tickers)) or {t: market_entry(t) for t in tickers})
		trades.run()
		self.assertEqual(fetched, [{'T1'}])
		fetched.clear()
		trades.run() # the trade is known now: nothing to report and nothing to fetch
		self.assertEqual(fetched, [])

	def test_a_scheduled_run_keeps_the_trades_another_run_recorded_meanwhile(self):
		"""The seen trades are read again as the run ends, so a trade another run recorded meanwhile is kept."""
		meanwhile = lambda tickers: state.save('finbot_sharesight_trades.json', [999]) or {t: market_entry(t) for t in tickers}
		self.patch(yahoo, 'fetch', meanwhile) # called after the seen trades were read, before the new ones are recorded
		trades.run()
		known = state.load('finbot_sharesight_trades.json')
		self.assertEqual((known[0], len(known)), (999, 2))

	def test_milestone(self):
		"""The milestone report posts."""
		milestone.run()
		self.assertTrue(self.sent)

	def test_milestone_records_a_ticker_only_with_its_new_values(self):
		"""A first sighting without 52-week values used to be recorded as 0/0, so the next run reported a record high for it."""
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0)) # beyond the 52-week range (120/80): nothing new
		self.patch(yahoo, 'fetch', lambda ts: {t: {k: v for k, v in market_entry(t).items() if not k.startswith('fiftyTwoWeek')} for t in ts})
		milestone.run()
		self.assertFalse(state.load('finbot_milestone.json'))
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
		self.sent.clear()
		milestone.run()
		self.assertNotIn('Record high', str(self.sent))
		self.assertEqual(state.load('finbot_milestone.json')['T1'], {'record_high': 150.0, 'record_low': 50.0}) # all-time

	def test_milestone_records_are_all_time(self):
		"""A new 52-week high below the all-time high is no record. The record used to become the 52-week high after the first
		run, so a stock far below its peak posted a record high each time it set a new 52-week one."""
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
		milestone.run() # first sighting: the 52-week range (120/80) is inside the history (150/50)
		for high, expected in ((130.0, False), (160.0, True), (155.0, False)):
			with self.subTest(high=high):
				self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'fiftyTwoWeekHigh': high} for t in ts})
				self.sent.clear()
				milestone.run()
				self.assertEqual('Record high' in str(self.sent), expected)

	def test_a_52_week_record_kept_before_is_replaced_by_the_history(self):
		"""A record kept in the old 52-week format is replaced by the history: no false record high."""
		state.save('finbot_milestone.json', {f'T{i}': {'high': 110.0, 'low': 90.0} for i in range(25)})
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
		milestone.run() # 120 beats the old 52-week record of 110, but not the history's 150
		self.assertNotIn('Record high', str(self.sent))

	def test_rating(self):
		""".rating run from a chat posts."""
		rating.run(transports.TelegramBot('5'))
		self.assertTrue(self.sent)

	def test_rating_keeps_the_last_rating_of_a_ticker_missing_from_a_run(self):
		"""A ticker missing from one run keeps its last rating, so its change is reported when it comes back; it used to
		be dropped from the record."""
		rating.run() # records every ticker's rating
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1' else {t: market_entry(t)})
		rating.run() # no T1 this time: its rating used to be dropped from the record
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | ({'recommend': 'sell', 'recommend_index': 4.5} if t == 'T1' else {})})
		self.sent.clear()
		rating.run()
		self.assertIn('Co T1 ', str(self.sent)) # so its change from buy to sell went unreported

	def test_an_interactive_rating_records_nothing(self):
		"""A rating report asked for in a chat leaves the record for the scheduled runs alone."""
		rating.run(transports.TelegramBot('5'))
		self.assertIsNone(state.load('finbot_rating.json'))

	def test_slack_webhook_without_a_bot_token_gets_scheduled_reports(self):
		"""Scheduled reports reach Slack through its incoming webhook, which takes no channel and no token. They used to send
		Telegram's chat id along, which made write() need slackBotToken and crash without one, before Telegram got its copy."""
		self.env(slackBotToken=False)

		self.env(webhooks={**config.env.webhooks, 'slack': 'https://hooks.slack.com/services/T/B/x'})
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		posts = []
		def post(url, **kwargs):
			"""Record (host, whether a bot token was sent, the channel) and answer ok."""
			posts.append((url.split('/')[2], 'Authorization' in kwargs.get('headers', {}), (kwargs.get('json') or {}).get('channel')))
			return mock.Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 1, 'chat': {'id': 1}}})
		self.patch(transports.net, 'post', post)
		for report in (price.run, shorts.run, milestone.run):
			with self.subTest(report=report):
				posts.clear()
				report()
				self.assertIn(('hooks.slack.com', False, None), posts)
				self.assertTrue(any(host == 'api.telegram.org' for host, _, _ in posts))

	def test_nowhere_to_post_is_an_error(self):
		"""A scheduled report with nowhere to post is an error that says so."""
		self.env(webhooks={})
		with self.assertRaisesRegex(RuntimeError, 'nowhere to post'):
			price.run()


class PeriodButtons(FinbotCase):
	"""Default views line up with the buttons: the highlighted button is the period actually shown."""

	def buttons(self, command):
		"""The labels of the period buttons a command's chart came with."""
		self.command(command)
		self.assertTrue(self.markups and self.markups[0], f'{command} sent no buttons')
		return [b['text'] for b in self.markups[0]['inline_keyboard'][0]]

	def test_performance_defaults_to_one_month(self):
		""".performance shows a month, marked on its button, and says month, not 4 weeks."""
		self.assertEqual(self.buttons('.performance'), ['7D', '● 1M', '1Y', 'Max'])
		self.assertIn('month', self.sent[0][2]) # "Performance over the past month", not 4 weeks

	def test_performance_period_argument_moves_the_marker(self):
		"""A period on .performance moves the marker to its button."""
		self.assertEqual(self.buttons('.performance 7d'), ['● 7D', '1M', '1Y', 'Max'])
		self.assertEqual(self.buttons('.performance 1y'), ['7D', '1M', '● 1Y', 'Max'])

	def test_price_list_has_a_1d_button_marked_by_default(self):
		"""The price list offers 1D, marked by default, and a period moves the marker."""
		self.assertEqual(self.buttons('.price'), ['● 1D', '7D', '1M', '1Y', 'Max'])
		self.assertEqual(self.buttons('.price top'), ['● 1D', '7D', '1M', '1Y', 'Max'])
		self.assertEqual(self.buttons('.price 1m'), ['1D', '7D', '● 1M', '1Y', 'Max'])

	def test_a_chart_has_five_buttons_at_most(self):
		"""No chart offers more than five buttons, Discord's limit for a row, and a period no button has (3m) marks
		none of them."""
		self.assertTrue(all(len(keys) <= 5 for keys in buttons.BUTTONS.values()))
		self.assertEqual(self.buttons('.performance 3m'), ['7D', '1M', '1Y', 'Max'])

	def test_other_charts_do_not_offer_1d(self):
		"""Only the price list offers 1D."""
		for command in ('.performance', '.compare T1 T2'):
			with self.subTest(command=command):
				self.assertNotIn('1D', [b.lstrip('● ') for b in self.buttons(command)])

	def test_a_long_list_is_stored_and_only_the_newest_are_kept(self):
		"""A button whose tickers do not fit the callback data carries a stored list's id; only the newest REF_LIMIT
		lists are kept, and an older button says it has expired."""
		self.patch(buttons, 'REF_LIMIT', 2)
		long = lambda i: [f'TICKER{i}.AX', 'LONGER.AX', 'LONGEST.AX', 'MORE.AX', 'EVEN.AX', 'MOST.AX', 'LAST.AX']
		refs = [buttons._ref(long(i)) for i in range(3)]
		self.assertTrue(all(ref.startswith('#') for ref in refs))
		self.assertEqual(buttons.resolve(refs[2]), long(2))
		with self.assertRaises(KeyError):
			buttons.resolve(refs[0])

	def test_no_buttons_where_their_presses_would_go_nowhere(self):
		"""Without telegramOutgoingWebhook (reports only), Telegram hears nothing from finbot's buttons, so a chart, a
		scheduled one included, comes without them."""
		self.env(webhooks={'telegram': 'https://api.telegram.org/botX/'}, telegramChatID='1')
		label, kwargs = price.job(['7']) # as scheduled: price.py 7
		for hook, buttons in (('https://example.com/telegram', True), ('', False)):
			with self.subTest(telegramOutgoingWebhook=hook):
				self.env(telegramOutgoingWebhook=hook)
				self.markups.clear()
				price.run(**kwargs)
				self.assertEqual(bool(self.markups and self.markups[0]), buttons)

	def press(self, data):
		"""Press a period button: (the edits made, the toasts shown)."""
		edits, toasts = [], []
		self.patch(transports.TelegramBot, 'edit_chart', lambda dest, msg, img, caption, buttons=None:
			edits.append((caption.split('\n')[0], transports.TelegramBot.markup(buttons))))
		self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: toasts.append(text))
		worker.process_callback('telegram', 'cb', '55', '9', data)
		return edits, toasts

	def test_pressing_1d_rebuilds_todays_list_and_moves_the_marker(self):
		"""Pressing 1D shows a toast, rebuilds today's list in place and marks 1D."""
		edits, toasts = self.press('c|l|d|3,0')
		self.assertEqual(toasts, ['Loading 1D…'])
		self.assertEqual(self.errors, [])
		self.assertEqual(len(edits), 1)
		self.assertEqual([b['text'] for b in edits[0][1]['inline_keyboard'][0]][0], '● 1D')

	def test_a_period_with_too_few_prices_is_said_in_the_chat(self):
		"""A period button whose span has too few prices for a line says so in the chat and leaves the chart as it is
		(Telegram was sent an edit without its photo)."""
		edits, toasts = self.press('c|h|w|T1') # the fixture's histories have no closes to draw
		self.assertEqual((edits, toasts, self.errors), ([], ['Loading 7D…'], []))
		self.assertEqual(self.sent, [('text', ['Too few prices to draw 7D'])])

	def test_a_button_a_chart_does_not_offer_is_ignored(self):
		"""A button a chart does not offer, or an unknown period, changes nothing."""
		edits, toasts = self.press('c|f|d|') # performance has no 1D
		self.assertEqual((edits, toasts), ([], [None]))
		edits, toasts = self.press('c|l|zz|3,0')
		self.assertEqual((edits, toasts), ([], [None]))


class Reminders(FinbotCase):
	def test_a_reminder_takes_links_and_italics_in_each_networks_markup(self):
		"""[text](url) is a link and a line in _underscores_ is in italics, an underscore in a url included; the rest
		is text, escaped where the network needs it."""
		line = '_See [R&D notes](https://x.example/a_b) & more_'
		self.assertEqual(reminder.markup(line, TELEGRAM),
			'<i>See <a href="https://x.example/a_b">R&amp;D notes</a> &amp; more</i>')
		self.assertEqual(reminder.markup(line, SLACK), '_See <https://x.example/a_b|R&amp;D notes> &amp; more_')
		self.assertEqual(reminder.markup(line, DISCORD), '_See [R&D notes](<https://x.example/a_b>) & more_')
		self.assertEqual(reminder.markup('a_b_c and _', TELEGRAM), 'a_b_c and _') # italic only when the whole line is

	def test_the_end_of_financial_year_reminder_comes_from_reminder_json(self):
		"""On 23 June an Australian gets the EOFY checklist from reminder.json, links and footnotes included; others do
		not, and a year or a country an entry names must match."""
		entries = config.data_json('reminder.json', [])
		eofy = reminder.report(TELEGRAM, datetime.date(2026, 6, 23), entries)
		self.assertEqual(eofy[0], '<b>Finance event reminders:</b>')
		self.assertIn('💸 Realise capital gains/losses by EOFY June 30🇦🇺', eofy)
		dgr = '<a href="https://abr.business.gov.au/Tools/DgrListing">DGR-registered</a>'
		self.assertIn(f'<i>* Organisation must be {dgr}</i>', eofy)
		self.prefs(country_code='US')
		self.assertEqual(reminder.report(TELEGRAM, datetime.date(2026, 6, 23), entries), [])
		dated = [{'month_day': '06-23', 'year': '2027', 'message': 'next year'},
			{'month_day': '06-23', 'message': ['a', 'b']}]
		self.assertEqual(reminder.report(SLACK, datetime.date(2026, 6, 23), dated),
			['*Finance event reminders:*', 'a', 'b'])

	def test_the_birthday(self):
		"""On 18 August finbot counts its years."""
		self.assertEqual(reminder.report(SLACK, datetime.date(2026, 8, 18), [])[1:], ["It's my 4th birthday! 🥳"])


class Podcasts(FinbotCase):
	def test_format_helpers(self):
		"""Durations in any feed format, how long ago, and zoneless dates taken as UTC; nonsense gives nothing."""
		from lib.reports import podcasts
		self.assertEqual(podcasts.format_duration('3725'), '01:02')
		self.assertEqual(podcasts.format_duration('1:02:03'), '01:02')
		self.assertEqual(podcasts.format_duration('62:05'), '01:02')
		self.assertEqual(podcasts.format_duration('nonsense'), '')
		self.assertTrue(podcasts.how_long_ago(podcasts.published('Mon, 01 Jan 2024 00:00:00 +0000')).endswith('d ago'))
		self.assertEqual(podcasts.published('Mon, 01 Jan 2024 00:00:00 -0000').tzinfo, datetime.timezone.utc) # no zone given: UTC
		self.assertIsNone(podcasts.published('yesterday'))

	def test_new_episodes_are_posted_once_newest_first(self):
		"""A feed whose items mix dated and undated ones used to crash the sort (aware and naive times)."""
		from lib.reports import podcasts
		def item(n, date):
			"""A feed item, its date optional."""
			return f'<item><guid>g{n}</guid><title>Show: ep {n}</title><enclosure url="https://x/{n}.mp3"/>{date}<itunes:duration>600</itunes:duration></item>'
		feed = ('<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Show</title>'
				+ item(1, '<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>') + item(2, '') + item(3, '<pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>')
				+ '</channel></rss>').encode()
		self.patch(podcasts.net, 'get', lambda url, **k: mock.Mock(content=feed, raise_for_status=lambda: None))
		podcasts.run(feed_url='https://example.com/feed')
		self.assertEqual([line.split(' (')[0] for line in self.sent[0][1]], ['📣 Show: <a href="https://x/3.mp3">ep 3</a> 00:10',
						 '📣 Show: <a href="https://x/1.mp3">ep 1</a> 00:10', '📣 Show: <a href="https://x/2.mp3">ep 2</a> 00:10'])
		self.sent.clear()
		podcasts.run(feed_url='https://example.com/feed')
		self.assertEqual(self.sent, []) # all seen now


class PieCommand(FinbotCase):
	def setUp(self):
		"""A portfolio of five holdings across three industries, one unclassified and one worth nothing."""
		super().setUp()
		def holdings(portfolio):
			"""The five holdings, whatever the portfolio."""
			data = [('A', 'Semiconductors', 'Electronic Technology', 500), ('B', 'Semiconductors', 'Electronic Technology', 300),
					('C', 'Biotechnology', 'Health Technology', 200), ('D', None, None, 100), ('E', 'Gold', 'Minerals', 0)]
			return {c + ':NASDAQ': {'code': c, 'market_code': 'NASDAQ', 'industry_classification_name': i,
									'sector_classification_name': s, 'value': v} for c, i, s, v in data}
		self.patch(sharesight.Portfolio, 'holdings', holdings)

	def test_by_industry_default(self):
		""".pie PORTFOLIO charts by industry."""
		sent = self.command('.pie Rob')
		self.assertEqual(sent[0][0], 'photo')
		self.assertIn('Rob by industry', sent[0][2])

	def test_by_sector_and_payload(self):
		""".pie by sector: the slices in order, the unclassified ones together, worthless holdings left out."""
		payload, chart = holdings.prepare_pie('rob', 'sector', TELEGRAM)
		self.assertEqual([r[0] for r in chart.rows], ['Electronic Technology', 'Health Technology', 'Unclassified'])
		self.assertIn('Electronic Technology: 72.7%', payload) # 800 of 1100; zero-value Gold is left out
		self.assertEqual(self.command('.pie Rob sector')[0][0], 'photo')

	def test_folds_into_other_and_renders(self):
		"""Over eight slices, the smallest fold into Other, and the chart draws."""
		held = {f'T{i}:X': {'code': f'T{i}', 'industry_classification_name': f'Ind {i}', 'value': 100 - i} for i in range(12)}
		self.patch(sharesight.Portfolio, 'holdings', lambda portfolio: held)
		payload, chart = holdings.prepare_pie('Rob', 'industry', TELEGRAM)
		self.assertEqual(len(chart.rows), 8)
		self.assertEqual(chart.rows[-1][0], 'Other')
		self.assertTrue(render.pie_chart(chart.rows, chart.title, chart.subtitle).read().startswith(b'\x89PNG'))

	def test_unknown_or_missing_portfolio_lists_known(self):
		""".pie with no portfolio, or an unknown one, lists the portfolios there are."""
		self.assertEqual(self.command('.pie'), [('text', ['Usage: .pie PORTFOLIO [sector]', 'Portfolios: Rob'])])
		self.assertEqual(self.command('.pie Nope'), [('text', ['Nope portfolio not found. I only know about:', 'Rob'])])

	def test_a_service_that_takes_no_images_gets_text(self):
		"""Slack without the bot token takes no images: the report goes as text."""
		self.env(slackBotToken=False)
		worker.Request(SLACK, 'C1', '@u', 'U', BOT).reply(['x'], render.Chart('pie', 't', rows=(('a', 1.0),)))
		self.assertEqual(self.sent[-1][0], 'text')


if __name__ == '__main__':
	unittest.main()
