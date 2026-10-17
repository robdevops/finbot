"""Every chat command and scheduled report produces output on mocked data."""
import contextlib
import unittest
import datetime
import re
from tests.common import *
from lib.reports import pick


class Commands(FinbotCase):
	def test_text_commands(self):
		"""Every text command answers."""
		for cmd in ('.help', '/start', '.who', '.holdings', '.marketcap',
					'.pe', '.fpe', '.peg', '.beta', '.buy', '.sell', '.buysell', '.earnings', '.dividend',
					'.earningsdividend',
					'.earnings T1', '.dividend T1', '.trades', '.trades 30d', '.price T1', '.session T1',
					'.premarket T1', '.shorts T1', '.watchlist', '.T1'):
			with self.subTest(cmd=cmd):
				self.assertTrue(self.command(cmd), f'{cmd} sent nothing')

	def test_session_and_premarket_are_movers_by_other_names(self):
		""".movers session and .movers premarket are what .session and .premarket were, which still answer typed: the
		same report, a SYMBOL too; neither is in .help, the keyboard or the slash commands."""
		self.settings(graph=False)
		for typed, same in (('.session', '.movers session'), ('.premarket 2', '.movers premarket 2'),
				('.premarket T1', '.movers premarket T1'), ('.postmarket', '.movers postmarket')):
			with self.subTest(typed=typed):
				self.assertEqual(self.command(typed), self.command(same))
		self.assertEqual(self.command('.movers session 7d')[0][1][0][:6], 'Usage:')
		shown = [line for _, lines in worker.help_sections() for line in lines]
		self.assertIn('/movers [percent|top|bottom|session|premarket] [period]', shown)
		self.assertFalse([line for line in shown if line.startswith(('/session', '/premarket'))])

	def test_exdividend_is_the_ex_dividend_report(self):
		""".exdividend and .ex-dividend are .dividend: the ex-dividend dates, not a stock named EXDIVIDEND."""
		self.settings(graph=False)
		for text in ('.dividend', '.exdividend', '.ex-dividend'):
			with self.subTest(text=text):
				self.assertIn('Upcoming ex-dividends', str(self.command(text)))

	def test_earningsdividend_is_the_earnings_then_the_ex_dividend_report(self):
		""".earningsdividend posts the upcoming earnings, then the ex-dividends; .earnings and .dividend, typed, each
		the one."""
		self.settings(graph=False)
		both = str(self.command('.earningsdividend'))
		self.assertEqual(both.count('Upcoming'), 2)
		self.assertLess(both.index('Upcoming earnings'), both.index('Upcoming ex-dividends'))
		self.assertEqual(both, str(self.command('.earnings') + self.command('.dividend')))
		self.assertEqual(both, str(self.command('.earnings & dividend'))) # the keyboard's button
		self.assertEqual(str(self.command('.earnings & dividend T1')), str(self.command('.earningsdividend T1')))

	def test_a_period_list_and_one_stocks_view_give_the_same_figure(self):
		"""Over a period, the list and one stock's view take a holding's figure from its Yahoo history, which its chart
		draws, not Sharesight's gain over the time it was held (+33% here), which the list used to take."""
		holding = {'id': 1, 'instrument': {'code': 'T1', 'market_code': 'NASDAQ'}, 'capital_gain_percent': '33'}
		self.patch(sharesight, '_performance', lambda pid, days=None, seconds=None:
			{'capital_gain_percent': '0', 'holdings': [holding]})
		def t1(text):
			"""T1's figure in what the command sends as text."""
			return re.search(r'Co T1 \(.*?\) ([+-]\d+%)', str(self.command(text))).group(1)
		self.settings(graph=False) # the list as text: a chart's caption is recorded by its heading
		self.assertEqual((t1('.movers 7d'), t1('.price T1 7d')), ('-36%', '-36%'))

	def test_chart_commands(self):
		"""Every chart command answers with a chart."""
		for cmd in ('.movers', '.movers 7d', '.movers top', '.movers bottom', '.session', '.premarket', '.postmarket',
					'.performance', '.performance 7d', '.performance 1y', '.shorts', '.peg', '.buy', '.sell', '.beta',
					'.movers top 7d',
					'.forward pe', '.fpe bottom'):
			with self.subTest(cmd=cmd):
				out = self.command(cmd)
				self.assertTrue(out, f'{cmd} sent nothing')
				self.assertTrue(any(kind == 'photo' for kind, *_ in out), f'{cmd} sent no chart: {out}')

	def test_one_button_asks_for_both_ratings_reports(self):
		""".buy & sell (and its spellings) sends both ratings reports, in the order asked, each once."""
		for text in ('.buysell', '.buy & sell', '.buy sell', '.buy/sell', '.buy and sell'):
			with self.subTest(text=text):
				captions = [caption for kind, _, caption in self.command(text) if kind == 'photo']
				self.assertEqual(len(captions), 2, captions)
				self.assertIn('analyst buy ratings', captions[0])
				self.assertIn('analyst sell ratings', captions[1])
		self.assertIn('analyst sell ratings', str(self.command('.sell & buy')[0])) # in the order asked
		self.assertEqual(len(self.command('.buy & buy')), 1) # each report once

	def test_the_keyboard_is_alphabetical_and_every_button_is_its_command(self):
		"""The command keyboard is alphabetical, .schedule (the jobs) in place of .beta, and each button runs the
		command it belongs to in the table, not taken for a ticker by .SYMBOL."""
		buttons = [button['text'] for row in worker.command_keyboard()['keyboard'] for button in row]
		self.assertEqual(buttons, sorted(buttons))
		self.assertEqual(buttons, ['.buy & sell', '.earnings & dividend', '.movers', '.pe', '.peg',
			'.performance', '.price', '.schedule', '.shorts', '.trades', '.treemap', '.watchlist'])
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
					self.assertIn(worker.slashed(line), text)
					called = worker.read(line.replace('SYMBOL', 'T1'), BOT)[0]
					self.assertIs(called, command)

	def test_a_portfolio_with_no_holdings_is_reported_by_name(self):
		"""Its name used to be read from its first holding: an empty portfolio crashed .performance."""
		self.patch(sharesight, '_performance', lambda pid, days=None, seconds=None:
			{'holdings': [], 'capital_gain_percent': '0.0'})
		payload, _ = performance.report(TELEGRAM, 7)
		self.assertTrue(any('>Rob</a>' in line for line in payload), payload)

	def test_a_holding_is_grouped_by_sector_industry_country_currency_or_market(self):
		"""group_of: a holding's sector, industry, its market's country (flag and letters), currency or market; a
		holding without one is Unclassified; .treemap takes each as a word, in the plural too."""
		holding = {'market_code': 'ASX', 'currency_code': 'AUD', 'sector_classification_name': 'Energy',
			'industry_classification_name': 'Oil'}
		self.assertEqual([holdings.group_of(holding, by) for by in holdings.GROUPS.values()],
			['Energy', 'Oil', '🇦🇺 AU', 'AUD', 'ASX'])
		self.assertEqual({holdings.group_of({}, by) for by in holdings.GROUPS.values()}, {'Unclassified'})
		self.assertEqual([self.command(f'.treemap Rob {word}')[0][2].split(' by ')[1] for word in
			('countries', 'currency', 'markets')], ['country</b>', 'currency</b>', 'market</b>'])

	def test_a_portfolio_command_without_a_portfolio_answers_for_the_first(self):
		""".holdings and .treemap without a portfolio answer for the first one, typed or run by a job (as .jobs
		Add adds them), with buttons for the portfolios there are; where there are no buttons, they name them."""
		job, unbuttoned = delivery.chat('telegram:55', scheduled=True), delivery.chat('telegram:55', scheduled=True)
		unbuttoned.takes_buttons = False
		for text in ('.holdings', '.treemap'):
			with self.subTest(text=text):
				self.sent.clear()
				typed = self.command(text)
				self.assertEqual(typed[0][0], 'text' if text == '.holdings' else 'photo')
				self.sent.clear()
				worker.job_commands()[text[1:]].run(job, words=[])
				self.assertEqual(self.sent, typed)
				self.sent.clear()
				worker.job_commands()[text[1:]].run(unbuttoned, words=[])
				by = '' if text == '.holdings' else ' [sector|industry|country|currency|market]'
				usage = f"Usage: {worker.slashed(text)} [PORTFOLIO]" + by
				self.assertEqual(self.sent, [('text', [usage, 'Portfolios: Rob'])])

	def test_prepare_marketcap(self):
		"""The market cap list is built."""
		self.assertTrue(rankings.marketcap_list(TELEGRAM, 'telegram:55', length=5))

	def test_prepare_rating(self):
		"""The buy and sell lists are built."""
		for action in ('buy', 'sell'):
			self.assertTrue(rankings.prepare_rating_payload(TELEGRAM, 'telegram:55', action, length=5)[0])

	def test_ratings_list_the_strongest_first(self):
		"""1 is a strong buy and 5 a strong sell: .sell used to list the mildest sells first. On equal ratings, more
		analysts first; fewer than 7 analysts and the stock is left out (T7, T8: the ASX small caps that are always a
		perfect 1.0)."""
		ratings = {'T1': ('buy', 1.5, 7), 'T2': ('strong_buy', 1.2, 12), 'T3': ('buy', 1.5, 9),
			'T7': ('strong_buy', 1.0, 6),
				   'T4': ('sell', 4.2, 7), 'T5': ('underperform', 4.6, 10), 'T6': ('sell', 4.2, 8),
				   'T8': ('strong_buy', 1.0, 2)}
		self.patch(watchlist, 'with_holdings', lambda chat: list(ratings))
		self.patch(yahoo, 'fetch_detail',
			lambda t, *a, **k: {t: market_entry(t) | dict(zip(('recommend', 'recommend_index', 'recommend_analysts'),
			ratings[t]))})
		def order(action):
			"""(the tickers listed, the tickers charted) of a ratings report, in order."""
			payload, chart = rankings.prepare_rating_payload(TELEGRAM, 'telegram:55', action)
			return [line.split('Co ')[1].split(' ')[0] for line in payload[1:]], [label for label, _ in chart.rows]
		self.assertEqual(order('buy'), (['T2', 'T3', 'T1'], ['T2', 'T3', 'T1']))
		self.assertEqual(order('sell'), (['T5', 'T6', 'T4'], ['T5', 'T6', 'T4']))
		self.assertIn('(7+ analysts)', rankings.prepare_rating_payload(TELEGRAM, 'telegram:55', 'buy')[0][0])
		self.patch(watchlist, 'with_holdings', lambda chat: ['T7', 'T8'])
		with self.assertRaises(answer.Nothing) as none:
			rankings.prepare_rating_payload(TELEGRAM, 'telegram:55', 'buy')
		self.assertEqual(none.exception.lines, ['No tracked stocks rated buy by 7+ analysts'])

	def test_a_small_cap_quoted_in_won_needs_the_bigger_move_too(self):
		"""demote_volatile compares market caps in US dollars: unconverted, a small cap in won was never small."""
		self.patch(yahoo, 'fetch',
			lambda ts: {t: market_entry(t) | ({'regularMarketPrice': 1380.0} if t == 'KRW=X' else {'currency': 'KRW',
			'market_cap': 1e11}) for t in ts})
		self.settings(demote_volatile=True)

		quote = movers.gather(TICKERS)['T1']
		self.assertAlmostEqual(quote['market_cap_usd'], 1e11 / 1380.0) # US$72M
		self.assertEqual(movers.trigger_bar('T1', quote, 5, {}), 5 * config.settings.volatility_multiplier)

	def test_a_short_top_list_repeats_none_of_its_best_as_the_worst(self):
		"""With fewer than twice `top` stocks, the Bottom list leaves out those in the Top list (it repeated them), and
		with none left there is no Bottom list and no gap in the chart; the subtitle says "over the past 3 months"."""
		for count, bottom, bars in ((12, 2, 13), (8, 0, 8)):
			with self.subTest(count=count):
				found = movers.moves(TICKERS[:count], 'period', 0, 90, interactive=True)
				payload, chart = movers.report(TELEGRAM, found, 'period', 0, 90, top=10, asked=True)
				shown = payload[payload.index('<b>Bottom 10</b>') + 1:] if bottom else []
				self.assertEqual((len(shown), len(chart.rows)), (bottom, bars))
				self.assertEqual(len(payload), 1 + min(count, 10) + (bottom and 2 + bottom))
				self.assertEqual(chart.subtitle, '% change over the past 3 months') # it said "in 3 months"

	def test_the_small_caps_betas_are_fetched_together(self):
		"""A scheduled price report asks for the betas of the small caps that moved (US$150M to US$1B) together."""
		calls = []
		self.patch(yahoo, 'fetch_details',
			lambda tickers, strict=False: calls.append(sorted(tickers)) or {t: market_entry(t) for t in tickers})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: self.fail('a beta fetched on its own'))
		self.settings(demote_volatile=True)

		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'market_cap': 5e8} for t in ts})
		movers.run(scheduled())
		self.assertEqual(len(calls), 1)
		self.assertTrue(calls[0])

	def test_forward_pe_lists_need_as_many_analysts_as_buy(self):
		"""A forward P/E is analysts' estimate: from few, it says little, as a perfect 1.0 buy from two brokers does."""
		analysts = {'T1': 7, 'T2': 6, 'T3': 12, 'T4': 2}
		self.patch(watchlist, 'with_holdings', lambda chat: list(analysts))
		self.patch(yahoo, 'fetch',
			lambda ts: {t: market_entry(t) | {'price_to_earnings_forward': -5 if t == 'T3' else 20} for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'recommend_analysts': analysts[t]}})
		def listed(mode='top'):
			"""(heading, the tickers listed, the chart) of a forward P/E list."""
			payload, chart = rankings.ratio_list(TELEGRAM, 'telegram:55', 'forward pe', mode)
			return payload[0], [line.split('Co ')[1].split(' ')[0] for line in payload[1:]], chart
		heading, names, chart = listed()
		# T2 and T4: too few analysts; T3: negative
		self.assertEqual((names, [label for label, _ in chart.rows]), (['T1'], ['T1']))
		self.assertIn('forward pe ratio (7+ analysts)', heading)
		self.assertEqual(listed('negative')[1], ['T3'])
		self.assertIn('Co T2', rankings.ratio_line(TELEGRAM, 'T2', 'forward pe')) # one ticker asked for: shown
		self.settings(min_analysts=13) # the one setting moves .buy and .forward pe together
		for none, said in ((listed, 'No tracked stocks with 13+ analysts have a forward pe ratio'),
				(lambda: rankings.prepare_rating_payload(TELEGRAM, 'telegram:55', 'buy'),
				'No tracked stocks rated buy by 13+ analysts')):
			with self.assertRaises(answer.Nothing) as nothing:
				none()
			self.assertEqual(nothing.exception.lines, [said])

	def test_market_caps_compare_in_us_dollars(self):
		"""Yahoo gives a market cap in the stock's own currency: unconverted, a won market cap topped every list."""
		stocks = {'K1.KS': ('KRW', 1.01e15), 'K2.KS': ('KRW', 5e11), 'U1': ('USD', 5.39e12), 'L1.L': ('GBp', 6.25e10),
			'Z1': ('XYZ', 1e12)}
		fx = {'KRW=X': 1380.0, 'GBP=X': 0.79} # units per US dollar; nothing for XYZ
		def fetch(tickers):
			"""Quotes in each stock's own currency, and the exchange rates."""
			own = lambda t: {'currency': stocks[t][0], 'market_cap': stocks[t][1], 'beta': 2.0}
			return {t: market_entry(t) | ({'regularMarketPrice': fx[t]} if t in fx else own(t))
				for t in tickers if t in fx or t in stocks}
		self.patch(yahoo, 'fetch', fetch)
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: fetch([t]))
		self.patch(watchlist, 'with_holdings', lambda chat: list(stocks))
		payload = rankings.marketcap_list(TELEGRAM, 'telegram:55')
		self.assertIn('by market cap (USD)', payload[0])
		# Z1: no rate, left out
		self.assertEqual([line.split('Co ')[1].split(' ')[0] for line in payload[1:]], ['U1', 'K1.KS', 'L1.L', 'K2.KS'])
		self.assertIn('mkt cap: 731.88 B', payload[2]) # 1.01 Q won
		self.assertIn('mkt cap: KRW 1.01 Q (USD 731.88 B)', rankings.marketcap_line(TELEGRAM, 'K1.KS'))
		self.assertIn('mkt cap: GBP 62.50 B (USD 79.11 B)', rankings.marketcap_line(TELEGRAM, 'L1.L')) # pence: pounds
		beta = rankings.prepare_beta_payload(TELEGRAM, 'telegram:55')[0]
		self.assertIn('Co K2.KS', str(beta)) # 500 billion won is US$362M: a small cap, which it never was unconverted
		self.assertNotIn('Co K1.KS', str(beta))

	def test_prepare_value(self):
		"""Each ratio report has its heading: top, bottom, and negative, where none found is nothing to show."""
		for kind, mode, heading in (('forward pe', 'bottom', 'Bottom 5 tracked stocks by forward pe ratio'),
				('peg', 'top', 'Top 5 tracked stocks by peg ratio')):
			with self.subTest(kind=kind, mode=mode):
				payload, chart = rankings.ratio_list(TELEGRAM, 'telegram:55', kind, mode, length=5)
				self.assertIn(heading, payload[0])
		with self.assertRaises(answer.Nothing) as none:
			rankings.ratio_list(TELEGRAM, 'telegram:55', 'peg', 'negative', length=5)
		self.assertEqual(none.exception.lines, ['negative peg: no data found'])

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
		""".pe and .fpe build a chart, and send it."""
		for typed in ('.pe', '.fpe'):
			self.assertEqual([kind for kind, *_ in self.command(typed)], ['photo'])

	def test_prepare_beta(self):
		"""The beta report charts a bar per stock listed, and says so when none qualify."""
		payload, chart = rankings.prepare_beta_payload(TELEGRAM, 'telegram:55')
		self.assertIn('Beta over 1.5', payload[0])
		self.assertEqual(len(chart.rows), len(payload) - 1) # a bar per stock listed
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'beta': 1.0}})
		with self.assertRaises(answer.Nothing) as none:
			rankings.prepare_beta_payload(TELEGRAM, 'telegram:55')
		self.assertEqual(none.exception.lines, ['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'])

	def test_prepare_profile(self):
		"""A company profile is built."""
		self.assertTrue(profile.prepare_profile_payload(TELEGRAM, '@u', 'T1'))

	def test_a_profile_leaves_out_what_yahoo_did_not_send(self):
		"""Each of these fields missing (or a zero equity) used to crash the whole profile."""
		full = market_entry('T1') | {'insiderBuy': 1, 'insiderSell': 0, 'insiderBuyValue': 5e6, 'insiderSellValue': 0,
			'netIncomeToCommon': 1e6,
									 'sharesOutstanding': 1e6, 'shareholder_equity': 1e9, 'total_debt': 9e8,
									 'total_cash': 1e8, 'profile_industry': 'Tools'}
		for missing in ('marketState', 'profile_exchange', 'market_cap', 'currency', 'regularMarketPrice',
				'sharesOutstanding', 'percent_change'):
			with self.subTest(missing=missing):
				self.patch(yahoo, 'fetch_detail',
					lambda t, *a, **k: {t: {k: v for k, v in full.items() if k != missing}})
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
		# forward P/E 99 warns (above 30): its warning used to show on the PS line too
		for ps, warned in ((12.3, False), (15.1, True)):
			with self.subTest(ps=ps):
				self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | {'price_to_sales': ps,
					'price_to_earnings_forward': 99, 'profile_industry': 'Tools'}})
				line = next(line for line in profile.prepare_profile_payload(TELEGRAM, '@u',
					'T1') if 'PS ratio' in line)
				self.assertEqual('⚠️' in line, warned, line)

	def test_prepare_watchlist(self):
		"""The watchlist is listed."""
		self.assertTrue(holdings.prepare_watchlist(TELEGRAM, 'telegram:55', '@u'))

	def test_each_chat_follows_its_own_watchlist_besides_the_holdings(self):
		"""Each chat has a watchlist of its own: .watchlist lists it, and a report, asked for or scheduled, covers that
		chat's watchlist and the holdings, which every chat shares, and no other chat's watchlist."""
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		self.patch(sharesight, 'tickers', lambda: ['T1'])
		fetched = []
		self.patch(yahoo, 'fetch', lambda ts: fetched.append(sorted(ts)) or {t: market_entry(t) for t in ts})
		self.command('.watchlist add T2')
		self.command('.watchlist add T3', chat='56')
		listed = [str(self.command('.watchlist', chat=chat)) for chat in ('55', '56')]
		self.assertEqual([('Co T2' in text, 'Co T3' in text) for text in listed], [(True, False), (False, True)])
		for chat, followed in (('55', ['T1', 'T2']), ('56', ['T1', 'T3'])):
			with self.subTest(chat=chat):
				fetched.clear()
				self.command('.movers', chat=chat)
				self.assertEqual(fetched[0], followed)
				fetched.clear()
				self.command('.marketcap', chat=chat)
				self.assertEqual(fetched[0], followed)
		fetched.clear()
		shorts.run(delivery.chat('telegram:56', scheduled=True))
		self.assertEqual(fetched[0], ['T1', 'T3'])

	def test_price_usage(self):
		""".price with more than eight tickers gets its usage, from the command table, typed as .compare too."""
		usage = ['Usage: /price [SYMBOL ... up to 8] [period]']
		for name in ('.price', '.compare'):
			with self.subTest(name=name):
				self.assertEqual(self.command(name + ' T1 T2 T3 T4 T5 T6 T7 T8 T9'), [('text', usage)])

	def test_compare_history_and_chart_are_price_by_hidden_names(self):
		""".compare, .history and .chart are .price by names .help and the slash commands leave out: one stock's line,
		two or more rebased, and bare the first ticker's, with the buttons to pick others."""
		shown = [line for _, lines in worker.help_sections() for line in lines]
		self.assertIn('/price [SYMBOL ... up to 8] [period]', shown)
		self.assertFalse([line for line in shown if line.startswith(('/compare', '/history', '/chart'))])
		self.assertFalse({'compare', 'history', 'chart'} & {slash.name for slash in worker.slash_commands()})
		for typed in ('T1 7d', 'T1 T2', ''):
			price = self.command(f'.price {typed}')
			for name in ('.compare', '.history', '.chart'):
				with self.subTest(typed=typed, name=name):
					self.assertEqual(self.command(f'{name} {typed}'), price)

	def test_one_stock_is_drawn_as_the_price_history_was(self):
		""".compare of one stock is its price line, as .history's chart was: titled with its name, symbol and span,
		its price and change beneath, red or green with the change; of two or more, the rebased lines, 'T1 vs T2'."""
		closes = tuple((datetime.date(2026, 1, day), 100.0 - day) for day in range(1, 31))
		self.patch(yahoo, 'price_history', lambda t, days=None, quote=None: ({days: -12.5},
			yahoo.Line('Co ' + t, 'NasdaqGS', 'USD', 70.0, closes)))
		_, one = charts.build('c', ['T1'], TELEGRAM, 'telegram:55', period='m')
		_, two = charts.build('c', ['T1', 'T2'], TELEGRAM, 'telegram:55', period='m')
		self.assertEqual((one.kind, one.title, one.subtitle, one.change), ('line', 'Co T1 (T1) 30 days',
			'70.00 USD   ▼ 12.5%', -12.5))
		self.assertEqual((two.kind, two.title), ('compare', 'T1 vs T2'))


class ScheduledReports(FinbotCase):
	"""The scheduled entry points (not interactive: they post to the job's chat)."""

	def test_movers(self):
		"""The scheduled movers report posts."""
		movers.run(scheduled())
		self.assertTrue(self.sent)

	def test_performance(self):
		"""The scheduled performance report posts."""
		performance.run(scheduled(), past_days=7)
		self.assertTrue(self.sent)

	def test_shorts(self):
		"""The scheduled shorts report posts."""
		shorts.run(scheduled())
		self.assertTrue(self.sent)

	def test_earnings_and_dividends(self):
		"""The scheduled earnings and ex-dividend reports post."""
		for kwargs in ({'event': 'earnings'}, {'event': 'ex-dividend'}):
			with self.subTest(kwargs=kwargs):
				self.sent.clear()
				cal.run(scheduled(), **kwargs)
				self.assertTrue(self.sent)

	def test_only_the_scheduled_earnings_report_is_pinned(self):
		"""The scheduled earnings report is pinned on Telegram; a reply to .earnings is not, or the chat would collect
		pinned copies, and neither is the ex-dividend report."""
		pins = []
		self.patch(telegram_common.TelegramBot, 'pin', lambda chat, answers: pins.append(chat.where))
		self.command('.earnings')
		self.assertEqual(pins, [])
		cal.run(scheduled(), event='ex-dividend')
		cal.run(scheduled(), event='earnings')
		self.assertEqual(pins, ['1'])

	def test_a_chats_job_runs_its_report_as_scheduled_not_as_a_command(self):
		"""A report a chat's job runs is a scheduled run: it says nothing when nothing passes,
		where a command's reply says so, and the earnings report is pinned. price, shorts and cal took any chat they
		were given for a command."""
		pins = []
		self.patch(telegram_common.TelegramBot, 'pin', lambda chat, answers: pins.append(chat.where))
		job_chat = delivery.chat('telegram:5', scheduled=True)
		for module, kwargs in ((movers, {'mode': 'premarket', 'threshold': 1000}), (shorts, {'threshold': 1000})):
			with self.subTest(report=module.__name__):
				self.sent.clear()
				module.run(job_chat, **kwargs)
				self.assertEqual(self.sent, [])
				module.run(telegram_common.TelegramBot('5'), **kwargs) # a command's reply says that nothing passed
				self.assertTrue(self.sent)
		cal.run(job_chat, event='earnings')
		self.assertEqual(pins, ['5'])

	def test_a_report_run_now_says_when_it_has_nothing_to_show(self):
		"""Run now asks for its run (delivery.asked): a report with nothing to show says so, where the same run on
		schedule posts nothing."""
		from lib.reports import podcasts
		self.patch(trades, 'gather', lambda days, portfolio, known: [])
		self.patch(rating, 'changed', lambda market_data, seen, old: [])
		self.patch(milestone, 'compare', lambda tickers, market_data, records: ([], [], {}))
		self.patch(cal, 'gather', lambda tickers, days, specific_stock, event: [])
		self.patch(podcasts, 'fetch_new_episodes', lambda feed_url, seen: [])
		past = formats.days_english(config.settings.past_days, 'in the past ')
		ahead = formats.days_english(config.settings.future_days, 'for the next ')
		runs = ((trades, {}, f'No new trades {past}.'), (rating, {}, 'No rating changes found'),
			(milestone, {}, 'No new record highs or lows'), (cal, {'event': 'ex-dividend'}, f'No events found {ahead}'),
			(podcasts, {'feed_url': 'https://example.com/feed'}, '📣 No new episodes'),
			(shorts, {'threshold': 1000}, '🩳 No stocks shorted over 1000%. Try specifying a number.'),
			(movers, {'mode': 'premarket', 'threshold': 1000}, 'No pre-market price movements meet threshold 1000%'),
			(movers, {'mode': 'interday', 'threshold': 1000}, 'No price movements meet threshold 1000%'))
		for module, kwargs, said in runs:
			for asked, posted in ((False, []), (True, [('text', [said])])):
				with self.subTest(report=module.__name__, asked=asked):
					self.sent.clear()
					module.run(delivery.chat('telegram:5', scheduled=True, asked=asked), **kwargs)
					self.assertEqual(self.sent, posted)

	def test_earnings_skip_an_adr_whose_primary_listing_yahoo_does_not_know(self):
		"""T1 has no earnings date, even in its details, so its primary listing is looked up: Yahoo not knowing it
		crashed the report."""
		self.patch(cal, 'primary_listings', lambda: {'T1': 'T1.XX'})
		undated = lambda t: {k: v for k, v in market_entry(t).items() if not (t == 'T1' and k == 'earnings_date')}
		self.patch(yahoo, 'fetch', lambda ts: {t: undated(t) for t in ts})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1.XX' else {t: undated(t)})
		cal.run(scheduled(), event='earnings')
		self.assertIn('Co T2 ', str(self.sent))
		self.assertNotIn('Co T1 ', str(self.sent))

	def test_a_us_listing_takes_its_home_markets_date_only_without_one_of_its_own(self):
		"""A foreign company's US listing (ARM, CLBT: held on a US market) whose quote lacks the date takes it from its
		own details; only when they have none, from its home market's listing (T1.L, a British company's), a guess:
		one that Yahoo does not know (ARM.L, CLBT.TA: there are none) leaves the stock out."""
		undated = lambda t: {k: v for k, v in market_entry(t).items() if not (t == 'T1' and k == 'earnings_date')}
		self.patch(yahoo, 'fetch', lambda ts: {t: undated(t) for t in ts})
		for own_date, home, listed, guessed in ((True, True, True, []), (False, True, True, [('T1.L', True)]),
				(False, False, False, [('T1.L', True)])):
			with self.subTest(own_date=own_date, home=home):
				asked = []
				def details(t, *a, guess=False, **k):
					"""T1's details, of a British company, with its date or without; T1.L's, if Yahoo knows it."""
					asked.append((t, guess))
					if t == 'T1.L':
						return {t: market_entry('T1')} if home else {}
					return {t: {**(market_entry(t) if own_date else undated(t)), 'profile_country': 'United Kingdom'}}
				self.patch(yahoo, 'fetch_detail', details)
				self.sent.clear()
				cal.run(scheduled(), event='earnings')
				self.assertEqual('Co T1 ' in str(self.sent), listed)
				self.assertEqual([(t, guess) for t, guess in asked if '.' in t], guessed)

	def test_trades(self):
		""".trades run from a chat posts."""
		trades.run(telegram_common.TelegramBot('5'))
		self.assertTrue(self.sent)

	def test_a_trade_is_in_its_market_currency_not_the_brokerage_one(self):
		"""A NASDAQ trade is in US dollars, though Yahoo names the exchange NasdaqGS and the broker charges in
		Australian dollars (it used to say AUD)."""
		self.patch(sharesight, '_trades', lambda pid, days=None: [{'id': 1, 'transaction_type': 'BUY',
			'symbol': 'T1', 'market': 'NASDAQ', 'transaction_date': time.strftime('%Y-%m-%d'),
			'quantity': '10', 'price': '5.0', 'value': '50', 'brokerage_currency_code': 'AUD', 'holding_id': 7}])
		self.assertIn(' USD 50 ', self.command('.trades')[0][1][-1])

	def test_trades_asks_yahoo_only_for_new_trades(self):
		"""A scheduled trades run asks Yahoo only about trades it has not reported, and nothing once all are known."""
		fetched = []
		self.patch(yahoo, 'fetch',
			lambda tickers: fetched.append(set(tickers)) or {t: market_entry(t) for t in tickers})
		trades.run(scheduled())
		self.assertEqual(fetched, [{'T1'}])
		fetched.clear()
		trades.run(scheduled()) # the trade is known now: nothing to report and nothing to fetch
		self.assertEqual(fetched, [])

	def test_a_scheduled_run_keeps_the_trades_another_run_recorded_meanwhile(self):
		"""The seen trades are read again as the run ends, so a trade another run recorded meanwhile is kept."""
		meanwhile = lambda tickers: state.save(trades.STATE_FILE,
			{'chats': {'telegram:1': [999]}}) or {t: market_entry(t) for t in tickers}
		self.patch(yahoo, 'fetch', meanwhile) # called after the seen trades were read, before the new ones are recorded
		trades.run(scheduled())
		known = state.load_for('telegram:1', trades.STATE_FILE, [])
		self.assertEqual((known[0], len(known)), (999, 2))

	def test_a_trade_or_a_rating_change_reaches_each_chat_that_schedules_the_report(self):
		"""Each chat keeps its own record of what a report told it, so a trade or a rating change reaches every chat
		whose job runs the report, each once: the first chat's run used to mark it told for all."""
		told = []
		self.patch(transports.Transport, 'text', lambda dest, lines, markup=None:
			told.append((dest.key, ' '.join(lines))) or [])
		chats = [delivery.chat(key, scheduled=True) for key in ('telegram:5', 'slack:C9')]
		self.env(slackBotToken='xoxb-test')
		for chat in chats * 2:
			trades.run(chat)
		self.assertEqual([key for key, text in told if 'T1' in text], ['telegram:5', 'slack:C9'])
		for chat in chats:
			rating.run(chat) # the first sighting, recorded
		told.clear()
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | ({'recommend': 'sell',
			'recommend_index': 4.5} if t == 'T1' else {})})
		for chat in chats * 2:
			rating.run(chat)
		self.assertEqual([key for key, text in told if 'Co T1' in text], ['telegram:5', 'slack:C9'])

	def test_milestone(self):
		"""The milestone report posts."""
		milestone.run(scheduled())
		self.assertTrue(self.sent)

	def test_milestone_records_a_ticker_only_with_its_new_values(self):
		"""A first sighting without 52-week values was recorded as 0/0: the next run reported a record high for it."""
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0)) # beyond the 52-week range (120/80): nothing new
		self.patch(yahoo, 'fetch',
			lambda ts: {t: {k: v for k, v in market_entry(t).items() if not k.startswith('fiftyTwoWeek')} for t in ts})
		milestone.run(scheduled())
		self.assertFalse(state.load_for('telegram:1', milestone.STATE_FILE, {}))
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts})
		self.sent.clear()
		milestone.run(scheduled())
		self.assertNotIn('Record high', str(self.sent))
		self.assertEqual(state.load_for('telegram:1', milestone.STATE_FILE, {})['T1'],
			{'all_time_high': 150.0, 'all_time_low': 50.0})

	def test_a_record_kept_from_ten_years_is_seeded_again_from_the_whole_history(self):
		"""Records kept before they came from the whole history (record_high, from 10 years) are seeded again: a stock
		above its 10-year high but below its all-time one posted a false record."""
		state.save(milestone.STATE_FILE, {'chats': {'telegram:1': {'T1': {'record_high': 110.0, 'record_low': 90.0}}}})
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
		milestone.run(scheduled()) # the 52-week range (120/80) was past the old record, but not the whole history's
		self.assertNotIn('Co T1 ', str(self.sent))
		self.assertEqual(state.load_for('telegram:1', milestone.STATE_FILE, {})['T1'],
			{'all_time_high': 150.0, 'all_time_low': 50.0})

	def test_milestone_records_are_all_time(self):
		"""A new 52-week high below the all-time high is no record. The record used to become the 52-week high after the
		first run, so a stock far below its peak posted a record high each time it set a new 52-week one."""
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
		milestone.run(scheduled()) # first sighting: the 52-week range (120/80) is inside the history (150/50)
		for high, expected in ((130.0, False), (160.0, True), (155.0, False)):
			with self.subTest(high=high):
				self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) | {'fiftyTwoWeekHigh': high} for t in ts})
				self.sent.clear()
				milestone.run(scheduled())
				self.assertEqual('Record high' in str(self.sent), expected)

	def test_a_52_week_record_kept_before_is_replaced_by_the_history(self):
		"""A record kept in the old 52-week format is replaced by the history: no false record high."""
		state.save(milestone.STATE_FILE, {'chats': {'telegram:1': {f'T{i}': {'high': 110.0, 'low': 90.0}
			for i in range(25)}}})
		self.patch(yahoo, 'historic_high', lambda t: (150.0, 50.0))
		milestone.run(scheduled()) # 120 beats the old 52-week record of 110, but not the history's 150
		self.assertNotIn('Record high', str(self.sent))

	def test_rating(self):
		""".rating run from a chat posts."""
		rating.run(telegram_common.TelegramBot('5'))
		self.assertTrue(self.sent)

	def test_rating_keeps_the_last_rating_of_a_ticker_missing_from_a_run(self):
		"""A ticker missing from one run keeps its last rating, so its change is reported when it comes back; it used to
		be dropped from the record."""
		rating.run(scheduled()) # records every ticker's rating
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {} if t == 'T1' else {t: market_entry(t)})
		rating.run(scheduled()) # no T1 this time: its rating used to be dropped from the record
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {t: market_entry(t) | ({'recommend': 'sell',
			'recommend_index': 4.5} if t == 'T1' else {})})
		self.sent.clear()
		rating.run(scheduled())
		self.assertIn('Co T1 ', str(self.sent)) # so its change from buy to sell went unreported

	def test_an_interactive_rating_records_nothing(self):
		"""A rating report asked for in a chat leaves the record for the scheduled runs alone."""
		rating.run(telegram_common.TelegramBot('5'))
		self.assertIsNone(state.load(rating.STATE_FILE))

	def test_scheduled_reports_reach_each_jobs_chat_with_its_own_token(self):
		"""Scheduled reports reach a Telegram and a Slack job's chat, each with its own bot's credentials: Slack's
		request carries the Slack token and channel, and Telegram's chat id goes only to Telegram."""
		self.env(slackBotToken='xoxb-test')
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		self.patch(render, 'draw', lambda chart: io.BytesIO(b'png'))
		posts = []
		def post(url, **kwargs):
			"""Record (host, the Slack token sent, the channel or chat) and answer ok."""
			data = kwargs.get('data') or kwargs.get('json') or {}
			posts.append((url.split('/')[2], kwargs.get('headers', {}).get('Authorization'),
				data.get('channel') or data.get('channel_id') or data.get('chat_id')))
			return mock.Mock(status_code=200, text='OK', json=lambda: {'ok': True, 'upload_url': 'https://files.x/u',
				'file_id': 'F1', 'ts': '1.5', 'result': {'message_id': 1, 'chat': {'id': 1}}})
		self.patch(net, 'post', post)
		for report in (movers.run, shorts.run, milestone.run):
			with self.subTest(report=report):
				posts.clear()
				with contextlib.redirect_stderr(io.StringIO()):
					report(scheduled())
					report(scheduled('slack:C9'))
				self.assertIn(('slack.com', 'Bearer xoxb-test', 'C9'), posts)
				self.assertTrue(any(host == 'api.telegram.org' and chat == '1' for host, _, chat in posts))
				self.assertFalse(any(host == 'slack.com' and chat == '1' for host, _, chat in posts))

	def test_nowhere_to_post_is_an_error(self):
		"""A report run for no chat (there are no home chats) is an error that says so."""
		with self.assertRaisesRegex(RuntimeError, 'nowhere to post'):
			movers.run()


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

	def test_movers_list_has_a_1d_button_marked_by_default(self):
		"""The movers list offers 1D, marked by default, and a period moves the marker."""
		self.assertEqual(self.buttons('.movers'), ['● 1D', '7D', '1M', '1Y', 'Max'])
		self.assertEqual(self.buttons('.movers top'), ['● 1D', '7D', '1M', '1Y', 'Max'])
		self.assertEqual(self.buttons('.movers 1m'), ['1D', '7D', '● 1M', '1Y', 'Max'])

	def test_trades_has_period_buttons_and_a_press_shows_the_trades_of_that_span_in_place(self):
		""".trades offers 1D, 7D and 1M, 1D marked by default and a period moving the marker; a press edits the text in
		place, for the one portfolio named too; a trades report posted on schedule has none."""
		shown = []
		self.patch(transports.Transport, 'text', lambda dest, lines, markup=None: shown.append(
			telegram_common.TelegramBot.markup(markup) if markup else None) or self.record_text(dest, lines))
		def labels(typed):
			"""The period buttons the command's text came with: (labels, the first one's data)."""
			shown.clear()
			self.command(typed)
			row = shown[0]['inline_keyboard'][0]
			return [b['text'] for b in row], row[0]['callback_data']
		self.assertEqual(labels('.trades'), (['● 1D', '7D', '1M'], 'c|r|d|'))
		self.assertEqual(labels('.trades 7d')[0], ['1D', '● 7D', '1M'])
		self.assertEqual(labels('.trades 7d Rob'), (['1D', '● 7D', '1M'], 'c|r|d|Rob'))
		edits = []
		self.patch(telegram_common.TelegramBot, 'edit_text', lambda dest, msg, text, buttons=None: edits.append(
			(text, [b['text'] for b in telegram_common.TelegramBot.markup(buttons)['inline_keyboard'][0]])))
		self.press_button('c|r|m|Rob')
		self.assertEqual((len(edits), edits[0][1], self.errors), (1, ['1D', '7D', '● 1M'], []))
		shown.clear()
		trades.run(delivery.chat('telegram:55', scheduled=True))
		self.assertEqual(shown, [None])

	def test_a_chart_has_five_buttons_at_most(self):
		"""No chart offers more than five buttons, Discord's limit for a row, and a period no button has (3m) marks
		none of them."""
		self.assertTrue(all(len(keys) <= 5 for keys in buttons.BUTTONS.values()))
		self.assertEqual(self.buttons('.performance 3m'), ['7D', '1M', '1Y', 'Max'])

	def test_other_charts_do_not_offer_1d(self):
		"""Only the movers list offers 1D."""
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
		with self.assertRaises(answer.Answer):
			buttons.resolve(refs[0])
		self.press_button(f'c|c|w|{refs[0]}') # said in the chat, as an answer: no error report
		self.assertEqual((self.sent, self.errors), ([('text', ['These buttons have expired: send the command again'])],
			[]))

	def test_telegram_charts_have_buttons_in_both_modes(self):
		"""A Telegram chart, a scheduled one included, has its period buttons whether Telegram posts their presses to
		telegramOutgoingWebhook (http mode) or finbot fetches them (pull mode)."""
		label, kwargs = movers.job(['7']) # as scheduled: price.py 7
		for hook in ('https://example.com/telegram', ''):
			with self.subTest(telegramOutgoingWebhook=hook):
				self.env(telegramOutgoingWebhook=hook)
				self.markups.clear()
				movers.run(scheduled(), **kwargs)
				self.assertTrue(self.markups and self.markups[0])

	def press(self, data):
		"""Press a period button: (the edits made, the toasts shown)."""
		edits, toasts = [], []
		self.patch(telegram_common.TelegramBot, 'edit_chart', lambda dest, msg, img, caption, buttons=None:
			edits.append((caption.split('\n')[0], telegram_common.TelegramBot.markup(buttons))))
		self.patch(telegram_common, 'answerCallbackQuery', lambda cid, text=None, alert=False: toasts.append(text))
		self.press_button(data)
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
		edits, toasts = self.press('c|c|w|T1') # the fixture's histories have no closes to draw
		self.assertEqual((edits, toasts, self.errors), ([], ['Loading 7D…'], []))
		self.assertEqual(self.sent, [('text', ['Too few prices to draw 7D'])])
		self.sent.clear()
		self.patch(charts, 'build', lambda *args, **kwargs: ('caption', render.Chart('bars'))) # a chart of no rows
		edits, toasts = self.press('c|f|w|')
		self.assertEqual((edits, self.sent, self.errors), ([], [('text', ['Too few prices to draw 7D'])], []))

	def test_a_button_a_chart_does_not_offer_is_ignored(self):
		"""A button a chart does not offer, or an unknown period, changes nothing."""
		edits, toasts = self.press('c|f|d|') # performance has no 1D
		self.assertEqual((edits, toasts), ([], [None]))
		edits, toasts = self.press('c|l|zz|3,0')
		self.assertEqual((edits, toasts), ([], [None]))


class Podcasts(FinbotCase):
	def test_format_helpers(self):
		"""Durations in any feed format, how long ago, and zoneless dates taken as UTC; nonsense gives nothing."""
		from lib.reports import podcasts
		self.assertEqual(podcasts.format_duration('3725'), '01:02')
		self.assertEqual(podcasts.format_duration('1:02:03'), '01:02')
		self.assertEqual(podcasts.format_duration('62:05'), '01:02')
		self.assertEqual(podcasts.format_duration('nonsense'), '')
		self.assertTrue(podcasts.how_long_ago(podcasts.published('Mon, 01 Jan 2024 00:00:00 +0000')).endswith('d ago'))
		# no zone given: UTC
		self.assertEqual(podcasts.published('Mon, 01 Jan 2024 00:00:00 -0000').tzinfo, datetime.timezone.utc)
		self.assertIsNone(podcasts.published('yesterday'))

	def test_new_episodes_are_posted_once_newest_first(self):
		"""A feed whose items mix dated and undated ones used to crash the sort (aware and naive times)."""
		from lib.reports import podcasts
		def item(n, date):
			"""A feed item, its date optional."""
			return (f'<item><guid>g{n}</guid><title>Show: ep {n}</title><enclosure url="https://x/{n}.mp3"/>{date}'
				'<itunes:duration>600</itunes:duration></item>')
		feed = ('<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Show</title>'
				+ item(1, '<pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>') + item(2, '') + item(3,
					'<pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate>')
				+ '</channel></rss>').encode()
		self.patch(podcasts.net, 'get', lambda url, **k: mock.Mock(content=feed, raise_for_status=lambda: None))
		podcasts.run(scheduled(), feed_url='https://example.com/feed')
		self.assertEqual([line.split(' (')[0] for line in self.sent[0][1]],
			['📣 Show: <a href="https://x/3.mp3">ep 3</a> 00:10',
						 '📣 Show: <a href="https://x/1.mp3">ep 1</a> 00:10',
						 '📣 Show: <a href="https://x/2.mp3">ep 2</a> 00:10'])
		self.sent.clear()
		podcasts.run(scheduled(), feed_url='https://example.com/feed')
		self.assertEqual(self.sent, []) # all seen now


class TreemapCommand(FinbotCase):
	def setUp(self):
		"""A portfolio of five holdings across three industries, one unclassified and one worth nothing."""
		super().setUp()
		data = [('A', 'Semiconductors', 'Electronic Technology', 500),
			('B', 'Semiconductors', 'Electronic Technology', 300), ('C', 'Biotechnology', 'Health Technology', 200),
			('D', None, None, 100), ('E', 'Gold', 'Minerals', 0)]
		held = {c + ':NASDAQ': {'code': c, 'market_code': 'NASDAQ', 'industry_classification_name': i,
			'sector_classification_name': s, 'value': v} for c, i, s, v in data}
		self.patch(sharesight.Portfolio, 'holdings', lambda portfolio: held)

	def test_by_industry_default(self):
		""".treemap PORTFOLIO charts by industry."""
		sent = self.command('.treemap Rob')
		self.assertEqual(sent[0][0], 'photo')
		self.assertIn('Rob treemap by industry', sent[0][2])

	def test_groups_and_holdings(self):
		"""By sector: the groups largest first with their holdings, worthless ones left out, and the chart draws."""
		payload, chart = holdings.prepare_treemap('rob', 'sector', TELEGRAM)
		self.assertEqual([r[0] for r in chart.rows], ['Electronic Technology', 'Health Technology', 'Unclassified'])
		self.assertEqual(chart.rows[0][1], (('A', 500.0), ('B', 300.0)))
		self.assertIn('Electronic Technology: 72.7%', payload)
		self.assertEqual(chart.subtitle, '3 sectors, 4 holdings')
		self.assertTrue(render.draw_treemap(chart).read().startswith(b'\x89PNG'))
		self.assertEqual(self.command('.treemap Rob sector')[0][0], 'photo')

	def test_folds_into_other(self):
		"""Over eight groups, the smallest are one Other, which keeps their holdings."""
		held = {f'T{i}:X': {'code': f'T{i}', 'industry_classification_name': f'Ind {i}',
			'value': 100 - i} for i in range(12)}
		self.patch(sharesight.Portfolio, 'holdings', lambda portfolio: held)
		payload, chart = holdings.prepare_treemap('Rob', 'industry', TELEGRAM)
		self.assertEqual(len(chart.rows), 8)
		self.assertEqual(chart.rows[-1][0], 'Other')
		self.assertEqual(len(chart.rows[-1][1]), 5)
		self.assertTrue(render.draw_treemap(chart).read().startswith(b'\x89PNG'))

	def test_nothing_with_a_value(self):
		"""A portfolio of worthless holdings answers in a line, with no chart."""
		self.patch(sharesight.Portfolio, 'holdings', lambda portfolio: {'E:X': {'code': 'E', 'value': 0}})
		self.assertEqual(holdings.prepare_treemap('Rob', 'industry', TELEGRAM),
			(['Rob has no holdings with a value'], None))

	def test_unknown_or_missing_portfolio_lists_known(self):
		""".treemap with no portfolio, or an unknown one, lists the portfolios there are."""
		self.assertEqual(self.command('.treemap')[0][0], 'photo') # the buttons of the portfolios
		self.assertEqual(self.command('.treemap Nope'),
			[('text', ['Nope portfolio not found. I only know about:', 'Rob'])])


class CommandJobs(FinbotCase):
	"""A job that runs a command of .help posts in its chat what the command posts when typed there."""

	def test_a_command_job_with_nothing_to_show_says_so_only_when_asked(self):
		"""A command with nothing to show (answer.Nothing) says so typed, and in a job run now (asked), but posts
		nothing on schedule; .buy & sell posts the list there is, saying the other has none only where asked."""
		def rated(service, chat, action, length=15):
			"""Sell ratings, and no stock rated buy."""
			if action == 'buy':
				raise answer.Nothing('No tracked stocks rated buy')
			return ['Sells'], None
		self.patch(rankings, 'prepare_rating_payload', rated)
		none, sells = ('text', ['No tracked stocks rated buy']), ('text', ['Sells'])
		self.assertEqual(self.command('.buy & sell'), [none, sells])
		for name, asked, posted in (('buy&sell', False, [sells]), ('buy&sell', True, [none, sells]), ('buy', False, []),
				('buy', True, [none])):
			with self.subTest(name=name, asked=asked):
				self.sent.clear()
				worker.job_commands()[name].run(delivery.chat('telegram:55', scheduled=True, asked=asked), words=[])
				self.assertEqual(self.sent, posted)

	def test_a_command_job_posts_what_the_typed_command_posts(self):
		"""peg, beta, buy & sell, price, compare and history, run as a job's, post what each posts when typed in the
		chat, bare too (the first ticker); one that cannot take its words posts its usage."""
		chat = delivery.chat('telegram:55', scheduled=True)
		for name, words, typed in (('peg', [], '.peg'), ('beta', [], '.beta'), ('buy&sell', [], '.buy & sell'),
				('compare', ['T1', 'T2'], '.compare T1 T2'), ('compare', [], '.compare'), ('price', [], '.price'),
				('history', [], '.history')):
			with self.subTest(name=name, words=words):
				posted = self.command(typed)
				self.sent.clear()
				worker.job_commands()[name].run(chat, words=words)
				self.assertEqual(self.sent, posted)
		self.sent.clear()
		worker.job_commands()['price'].run(chat, words=[f'T{i}' for i in range(9)])
		self.assertEqual(self.sent, [('text', ['Usage: /price [SYMBOL ... up to 8] [period]'])])


class WithoutSharesight(FinbotCase):
	"""Without Sharesight's keys, a chat's reports cover its watchlist alone, and what needs Sharesight says it is not
	set up."""

	def setUp(self):
		"""No Sharesight keys in finbot.env."""
		super().setUp()
		self.env(sharesight_auth={**config.env.sharesight_auth, 'client_id': None})
		self.patch(sharesight, '_portfolios', lambda seconds=None: self.fail('Sharesight was asked'))

	def test_the_watchlist_alone_and_never_a_request(self):
		"""The stocks a chat's reports cover are its watchlist alone, and Sharesight is never asked."""
		self.assertEqual((watchlist._followed(['T9', 'T1']), sharesight.tickers()), (['T1', 'T9'], []))

	def test_what_needs_sharesight_says_it_is_not_set_up(self):
		""".holdings, .trades, .performance, .who and .treemap say Sharesight is not set up, and where its keys go."""
		for typed in ('.holdings Rob', '.holdings', '.trades', '.performance', '.who T1', '.treemap Rob'):
			with self.subTest(typed=typed):
				self.assertEqual(self.command(typed), [('text', ['Sharesight is not set up: its keys go in finbot.env'
					' (doc/configuration.md)'])])


class Pickers(FinbotCase):
	"""A command typed with nothing to say what it is about answers with buttons: one message, edited as they are
	pressed."""

	def setUp(self):
		"""Telegram's edits and toasts of a press are noted: self.edits (kind, lines, buttons by row; an edit of the
		buttons alone keeps the lines the message showed), self.toasts."""
		super().setUp()
		self.edits, self.toasts, self.shown, self.showing = [], [], [], []
		bot_class = telegram_common.TelegramBot
		def edited(kind, lines, buttons):
			"""Note an edit, which is the screen shown now."""
			self.edits.append((kind, lines, self.rows(buttons)))
			self.shown, self.showing = self.edits[-1][2], lines
		def posted(dest, lines, buttons=None):
			"""Transport.text in these tests: noted as the others are, and its buttons are the screen shown now."""
			self.shown, self.showing = self.rows(buttons), list(lines)
			return self.record_text(dest, lines)
		def charted(dest, image, caption, markup=None):
			"""Transport.chart in these tests: noted as the others are, and its buttons are the screen shown now."""
			self.shown, self.showing = self.rows(markup), caption.split('\n')
			return self.record_chart(dest, image, caption, markup)
		self.patch(bot_class, 'edit_chart', lambda dest, msg, image, caption, buttons=None:
			edited('photo', caption.split('\n'), buttons))
		self.patch(bot_class, 'edit_text', lambda dest, msg, text, buttons=None:
			edited('text', text.split('\n'), buttons))
		self.patch(bot_class, 'edit_buttons', lambda dest, msg, buttons:
			edited('buttons', self.showing, buttons) or True)
		self.patch(transports.Transport, 'text', posted)
		self.patch(transports.Transport, 'chart', charted)
		self.patch(telegram_common, 'answerCallbackQuery', lambda cid, text=None, alert=False:
			self.toasts.append((text, alert)))

	@staticmethod
	def rows(buttons):
		"""Rows of (label, data) of the buttons a message was left with."""
		return [[(b.label if not b.active else '● ' + b.label, b.data) for b in row] for row in buttons or []]

	def sent_rows(self):
		"""The buttons of the picker as shown now (posted or edited), by row: (label, data)."""
		return self.shown

	def tap(self, label, rows=None):
		"""Press the button with this label (as marked, '✅ T1' or '● Max') in the last screen shown."""
		rows = rows or self.shown
		data = next(data for row in rows for text, data in row if text == label)
		self.press_button(data)
		self.assertEqual(self.errors, [])
		return self.edits[-1]

	def labels(self, rows=None):
		"""The labels of a screen's buttons, by row (the screen shown now unless given)."""
		return [[text for text, _ in row] for row in (self.shown if rows is None else rows)]

	def portfolios(self, *names):
		"""Sharesight has these portfolios."""
		self.patch(sharesight, '_portfolios', lambda seconds=None: [{'name': n, 'id': i} for i, n in enumerate(names)])

	def test_a_portfolio_command_answers_with_the_first_portfolio(self):
		""".treemap and .holdings answer with the first portfolio alphabetically at once, its button marked, the
		Group by button after the portfolios."""
		self.patch(holdings, 'prepare_holdings_payload', lambda name, service: [f'<b>Holdings for {name} (25)</b>'])
		self.portfolios('Zed', 'Amy')
		self.command('.treemap')
		self.assertEqual((self.sent[-1][0], self.sent[-1][2]), ('photo', '<b>Amy treemap by industry</b>'))
		self.assertEqual(self.labels(), [['● Amy', 'Zed'], ['Group by: Industry ▾']])
		self.command('.treemap sector')
		self.assertEqual((self.sent[-1][2], self.labels()), ('<b>Amy treemap by sector</b>',
			[['● Amy', 'Zed'], ['Group by: Sector ▾']]))
		self.command('.holdings')
		self.assertEqual((self.sent[-1], self.labels()), (('text', ['<b>Holdings for Amy (25)</b>']),
			[['● Amy', 'Zed']]))

	def test_portfolios_come_four_to_a_row(self):
		"""Portfolios are in rows of four before the Group by row."""
		names = [f'P{i}' for i in range(6)]
		self.portfolios(*names)
		self.command('.treemap')
		self.assertEqual(self.labels(), [['● P0', 'P1', 'P2', 'P3'], names[4:], ['Group by: Industry ▾']])

	def test_the_group_menu_and_another_portfolio_redraw_the_answer(self):
		"""The Group by button opens a menu of the five groupings, the one shown marked, and a choice (or Back) redoes
		the chart in place with the portfolio buttons; another portfolio's button does too."""
		self.portfolios('Amy', 'Zed')
		self.command('.treemap')
		kind, lines, rows = self.tap('Group by: Industry ▾')
		self.assertEqual((kind, self.labels(rows)), ('buttons',
			[['Sector', '● Industry', 'Country', 'Currency'], ['Market'], ['◀ Back']]))
		kind, lines, rows = self.tap('Sector')
		self.assertEqual((kind, lines[0], self.labels(rows)), ('photo', '<b>Amy treemap by sector</b>',
			[['● Amy', 'Zed'], ['Group by: Sector ▾']]))
		self.assertEqual(self.toasts[-1], ('Updating…', False))
		kind, lines, rows = self.tap('Zed')
		self.assertEqual((kind, lines[0], self.labels(rows)), ('photo', '<b>Zed treemap by sector</b>',
			[['Amy', '● Zed'], ['Group by: Sector ▾']]))
		self.tap('Group by: Sector ▾')
		kind, lines, rows = self.tap('Currency')
		self.assertEqual((lines[0], self.labels(rows)[1]), ('<b>Zed treemap by currency</b>', ['Group by: Currency ▾']))
		self.tap('Group by: Currency ▾')
		kind, lines, rows = self.tap('◀ Back')
		self.assertEqual((lines[0], self.labels(rows)[1]), ('<b>Zed treemap by currency</b>', ['Group by: Currency ▾']))

	def test_a_holdings_answer_keeps_its_buttons(self):
		""".holdings: another portfolio's list as text in place of the first's, the portfolio buttons still under it."""
		self.patch(holdings, 'prepare_holdings_payload', lambda name, service:
			[f'<b>Holdings for {name} (25)</b>', 'x'])
		self.portfolios('Amy', 'Rob')
		self.command('.holdings')
		kind, lines, rows = self.tap('Rob')
		self.assertEqual((kind, lines, self.labels(rows)), ('text', ['<b>Holdings for Rob (25)</b>', 'x'],
			[['Amy', '● Rob']]))

	def test_compare_starts_on_the_first_ticker_alone(self):
		""".compare (and .history) answers with the first ticker alone at once, on 7D, the periods and + in one row; +
		opens the tickers' screen with the ticks as they are (the first ticker's); OK draws those ticked."""
		self.command('.compare')
		self.assertEqual(self.labels(), [['● 7D', '1M', '1Y', 'Max', '+']])
		self.assertTrue(any('Co T0' in line for line in self.showing))
		kind, lines, rows = self.tap('+')
		ticks = [t for row in self.labels(rows) for t in row if t.startswith('✅')]
		self.assertEqual((kind, ticks), ('buttons', ['✅ T0'])) # the first ticker, as shown, stays ticked
		self.tap('✅ T0') # unticked
		self.tap('T3')
		kind, lines, rows = self.tap('OK')
		self.assertTrue(any('Co T3' in line for line in lines) and not any('Co T0' in line for line in lines))
		self.assertEqual(self.labels(rows), [['● 7D', '1M', '1Y', 'Max', '+']])
		kind, lines, rows = self.tap('+') # T3 stays ticked
		self.assertEqual([t for row in self.labels(rows) for t in row if t.startswith('✅')], ['✅ T3'])
		self.assertEqual(self.command('.history'), self.command('.compare'))

	def test_compare_ticks_change_the_buttons_until_show_is_pressed(self):
		""".compare answers at the period typed; ticking changes the buttons, not the chart, until OK is pressed,
		which shows those ticked and goes back to the period row."""
		self.command('.compare 1y')
		first = self.sent[-1][2]
		self.assertEqual(self.labels(), [['7D', '1M', '● 1Y', 'Max', '+']])
		self.tap('+')
		kind, lines, rows = self.tap('T10')
		self.assertEqual((lines[0], self.labels(rows)[0][:3]), (first, ['✅ T0', 'T1', '✅ T10']))
		self.assertFalse(any('Co T10' in line for line in lines)) # the chart is still of the first
		self.assertEqual(self.labels(rows)[-1], ['◀ Back', 'OK'])
		kind, lines, rows = self.tap('OK')
		self.assertTrue(any('Co T10' in line for line in lines) and any('Co T0' in line for line in lines))
		self.assertEqual((self.toasts[-1], self.labels(rows)), (('Loading…', False),
			[['7D', '1M', '● 1Y', 'Max', '+']]))
		self.command('.compare max') # as typed: not the 7D a bare .compare starts on
		self.assertEqual(self.labels()[0], ['7D', '1M', '1Y', '● Max', '+'])

	def test_an_answer_with_nothing_to_draw_is_a_photo_all_the_same(self):
		"""A first answer with no chart (a portfolio with nothing to draw) goes as a blank photo, its buttons under it,
		so that a press can turn it into a chart: a text message cannot become one."""
		self.portfolios('Amy', 'Zed')
		self.patch(holdings, 'prepare_treemap', lambda name, by, service: ([f'<b>{name} by {by}</b>'], None))
		self.command('.treemap')
		self.assertEqual((self.sent[-1][:2], self.labels()), (('photo', len(render.blank().read())),
			[['● Amy', 'Zed'], ['Group by: Industry ▾']]))

	def test_compare_ticks_up_to_eight_and_refuses_a_ninth(self):
		""".compare: ticks toggle, a ninth is refused with an alert and a note."""
		self.command('.compare')
		self.tap('+')
		for ticker in ('T1', 'T10', 'T11', 'T12', 'T13', 'T14', 'T15'): # with T0, the first, ticked already
			kind, lines, rows = self.tap(ticker)
		self.assertEqual([t for row in self.labels(rows) for t in row if t.startswith('✅')],
			['✅ T0', '✅ T1', '✅ T10', '✅ T11', '✅ T12', '✅ T13', '✅ T14', '✅ T15'])
		self.assertEqual(self.toasts[-1], ('Updating…', False))
		kind, lines, rows = self.tap('T16')
		self.assertEqual((self.toasts[-1], lines[0]), ((buttons.TOO_MANY, True), buttons.TOO_MANY))
		self.assertNotIn('✅ T16', [t for row in self.labels(rows) for t in row])
		kind, lines, rows = self.tap('✅ T13') # unticking makes room
		self.assertNotIn(buttons.TOO_MANY, lines)
		self.assertEqual(len([t for row in self.labels(rows) for t in row if t.startswith('✅')]), 7)

	def test_a_tick_or_a_page_changes_the_buttons_alone(self):
		"""+, a tick and a page of tickers change only the buttons, the chart left as it is (nothing drawn or uploaded);
		under a note (a ninth tick refused), the next press draws the message whole, which takes the note away; where
		the network cannot change buttons alone, the message is drawn whole."""
		self.many()
		self.command('.compare')
		first = self.showing
		for label in ('+', 'S05', '>'):
			kind, lines, rows = self.tap(label)
			self.assertEqual((kind, lines), ('buttons', first), label)
		for ticker in ('S40', 'S41', 'S42', 'S43', 'S44', 'S45'): # eight ticked, with S00 and S05
			self.assertEqual(self.tap(ticker)[0], 'buttons')
		kind, lines, rows = self.tap('S46') # refused, as the ninth: said in a note
		self.assertEqual((kind, lines[0]), ('photo', buttons.TOO_MANY))
		kind, lines, rows = self.tap('✅ S45')
		self.assertEqual((kind, lines), ('photo', first))
		self.assertEqual(self.tap('S46')[0], 'buttons') # room again, and no note to take away
		self.assertEqual(self.tap('<')[0], 'buttons')
		self.patch(telegram_common.TelegramBot, 'edit_buttons', transports.Transport.edit_buttons) # none on Slack
		self.assertEqual(self.tap('>')[0], 'photo')

	def test_buttons_of_another_list_start_again(self):
		"""A button drawn for other tickers than there are now starts the picker again, at its first answer, saying
		so."""
		self.command('.compare')
		stale = self.shown[0][-1][1] # +
		self.patch(sharesight, 'tickers', lambda: ['A1', 'B1', 'C1'])
		self.press_button(stale)
		kind, lines, rows = self.edits[-1]
		self.assertEqual(lines[0], 'The list has changed: here it is now')
		self.assertEqual(self.labels(rows), [['● 7D', '1M', '1Y', 'Max', '+']])
		self.assertTrue(any('Co A1' in line for line in lines))

	def test_watchlist_edit_crosses_tickers_off_and_ok_deletes_them(self):
		""".watchlist lists the watchlist with an Edit button, which offers a button for each ticker: pressing one
		strikes it through in the list (and again undoes it); Delete deletes the struck ones; Cancel goes back."""
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		for ticker in ('T3', 'T1', 'T2'):
			watchlist.add('telegram:55', ticker)
		self.command('.watchlist')
		self.assertEqual(self.labels(), [['Edit']])
		kind, lines, rows = self.tap('Edit')
		self.assertEqual(self.labels(rows), [['T1', 'T2', 'T3'], ['Delete', 'Cancel']])
		self.assertFalse(any(line.startswith('<s>') for line in lines))
		kind, lines, rows = self.tap('T2')
		self.assertEqual(self.labels(rows), [['T1', about.struck('T2'), 'T3'], ['Delete', 'Cancel']])
		struck = [line for line in lines if line.startswith('<s>')]
		self.assertEqual([('Co T2' in line, line.endswith('</s>')) for line in struck], [(True, True)])
		kind, lines, rows = self.tap(about.struck('T2'))
		self.assertFalse(any(line.startswith('<s>') for line in lines))
		self.tap('T1')
		kind, lines, rows = self.tap('Cancel')
		self.assertEqual((self.labels(rows), watchlist.tickers('telegram:55')), ([['Edit']], ['T3', 'T1', 'T2']))
		self.tap('Edit')
		self.tap('T1')
		self.tap('T3')
		kind, lines, rows = self.tap('Delete')
		self.assertEqual((self.labels(rows), lines[0], watchlist.tickers('telegram:55')),
			([['Edit']], 'Deleted: T1, T3', ['T2']))

	def test_watchlist_shows_its_edit_button_however_it_is_opened_and_none_when_empty(self):
		"""The Edit button is under the watchlist after an add or a delete too, and an empty watchlist, however it
		comes to be, has no buttons."""
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		empty = ['Watchlist is empty. Try ".watchlist add SYMBOL" to create it']
		self.assertEqual(self.command('.watchlist'), [('text', empty)])
		self.assertEqual(self.shown, [])
		self.command('.watchlist add T1')
		self.assertEqual(self.labels(), [['Edit']])
		self.assertIn('Co T1', str(self.showing))
		self.command('.watchlist add T2')
		self.command('.watchlist del T2')
		self.assertEqual(self.labels(), [['Edit']])
		self.tap('Edit')
		self.tap('T1')
		kind, lines, rows = self.tap('Delete')
		self.assertEqual((rows, watchlist.tickers('telegram:55')), ([], []))
		self.command('.watchlist del T1')
		self.assertEqual(self.shown, [])

	def test_watchlist_buttons_of_another_list_start_again(self):
		"""Buttons drawn for a watchlist that has changed since delete nothing: the list is drawn again, with a note."""
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		for ticker in ('T1', 'T2'):
			watchlist.add('telegram:55', ticker)
		self.command('.watchlist')
		self.tap('Edit')
		old = self.tap('T1')[2]
		watchlist.add('telegram:55', 'T3')
		kind, lines, rows = self.tap('Delete', old)
		self.assertEqual((lines[0], self.labels(rows), watchlist.tickers('telegram:55')),
			('The list has changed: here it is now', [['Edit']], ['T1', 'T2', 'T3']))

	def test_without_holdings_the_watchlist_is_offered(self):
		"""Tickers to pick are the holdings', else the chat's watchlist; none at all says how to add one, and one is
		enough."""
		self.patch(sharesight, 'tickers', lambda: [])
		self.patch(watchlist, 'tickers', lambda chat: ['MSFT', 'AAPL'])
		self.command('.compare')
		self.tap('+')
		self.assertEqual([t for row in self.labels(self.edits[-1][2]) for t in row], ['✅ AAPL', 'MSFT', '◀ Back'])
		self.patch(watchlist, 'tickers', lambda chat: [])
		self.assertEqual(self.command('.compare'),
			[('text', ['No tickers to pick from: .watchlist add SYMBOL adds one'])])
		self.patch(watchlist, 'tickers', lambda chat: ['MSFT'])
		self.assertEqual(self.command('.compare')[0][0], 'photo')

	def test_with_the_graph_off_the_picker_is_text_and_edits_as_text(self):
		"""Where charts are not drawn, the answer and its buttons are a text message, edited as text."""
		self.settings(graph=False)
		self.portfolios('Amy', 'Zed')
		self.command('.treemap')
		self.assertEqual(self.sent[-1][0], 'text')
		self.assertEqual(self.labels(), [['● Amy', 'Zed'], ['Group by: Industry ▾']])
		kind, lines, rows = self.tap('Zed')
		self.assertEqual((kind, lines[0], self.labels(rows)), ('text', '<b>Zed treemap by industry</b>',
			[['Amy', '● Zed'], ['Group by: Industry ▾']]))

	def many(self, count=70):
		"""Held tickers S00, S01..., enough to need pages."""
		self.patch(sharesight, 'tickers', lambda: [f'S{i:02d}' for i in range(count)])

	def test_tickers_are_paged_32_to_a_page_under_the_tickers_menu(self):
		"""The top level has no < or >; the tickers menu has 32 tickers to a page, in rows of four, with < and > where
		there is another page, Back always, and ticks lasting across pages."""
		self.many()
		self.command('.compare')
		self.assertEqual(self.labels(), [['● 7D', '1M', '1Y', 'Max', '+']]) # compare starts on 7D
		kind, lines, rows = self.tap('+')
		self.assertEqual((len(rows) - 1, [t for row in self.labels(rows)[:-1] for t in row][-1], self.labels(rows)[-1]),
			(8, 'S31', ['◀ Back', '>']))
		kind, lines, rows = self.tap('>')
		self.assertEqual((self.labels(rows)[0], self.labels(rows)[-1]), (['S32', 'S33', 'S34', 'S35'],
			['◀ Back', '<', '>']))
		kind, lines, rows = self.tap('S40')
		kind, lines, rows = self.tap('>')
		self.assertEqual((self.labels(rows)[-1], [t for row in self.labels(rows)[:-1] for t in row][-1]),
			(['◀ Back', '<', 'OK'], 'S69'))
		kind, lines, rows = self.tap('<')
		self.assertIn('✅ S40', [t for row in self.labels(rows) for t in row])
		kind, lines, rows = self.tap('◀ Back')
		self.assertEqual(self.labels(rows), [['● 7D', '1M', '1Y', 'Max', '+'], ['OK']])

	def test_a_ninth_tick_is_refused_on_a_later_page(self):
		"""The limit of eight counts every page's ticks, and the refusal stays on the page."""
		self.many()
		self.command('.compare')
		self.tap('+')
		for ticker in ('S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07'): # with S00, the first, ticked already
			self.tap(ticker)
		self.tap('>')
		kind, lines, rows = self.tap('S33')
		self.assertEqual((self.toasts[-1], lines[0], self.labels(rows)[0][:2]), ((buttons.TOO_MANY, True),
			buttons.TOO_MANY, ['S32', 'S33']))

	def test_an_item_on_a_later_page_is_the_one_picked(self):
		"""A ticker ticked on page two is the one OK draws, back at the top."""
		self.many()
		self.command('.compare')
		self.tap('+')
		self.tap('>')
		self.tap('S40')
		kind, lines, rows = self.tap('OK')
		self.assertTrue(any('Co S40' in line for line in lines))
		self.assertEqual(self.labels(rows), [['● 7D', '1M', '1Y', 'Max', '+']])

	def test_portfolios_page_too(self):
		"""Thirty-two portfolios to a page, in rows of four, then Group by, then the page buttons."""
		names = [f'P{i:02d}' for i in range(40)]
		self.portfolios(*names)
		self.command('.treemap')
		rows = self.labels()
		self.assertEqual((len(rows), rows[7], rows[8], rows[9]), (10, ['P28', 'P29', 'P30', 'P31'],
			['Group by: Industry ▾'], ['>']))
		kind, lines, rows = self.tap('>')
		self.assertEqual((self.labels(rows)[0], self.labels(rows)[-1]), (['P32', 'P33', 'P34', 'P35'], ['<']))

	def test_discord_pages_hold_five_rows(self):
		"""Discord's five rows of five buttons hold 12 portfolios with Group by and the page buttons, or 20 tickers
		with Back, the page buttons and OK."""
		for cmd, items in (('t', 12), ('c', 20)):
			with self.subTest(cmd=cmd):
				names = [f'N{i:02d}' for i in range(60)]
				rows = pick.screen(DISCORD, cmd, names, '0', '0', 0, 0b11 if cmd == 'c' else 0,
					'm' if cmd == 'c' else 'p', 1)[1]
				self.assertLessEqual(len(rows), 5)
				self.assertTrue(all(len(row) <= 5 for row in rows))
				counted = sum(button.label.endswith(tuple('0123456789')) for row in rows for button in row)
				self.assertEqual(counted, items)

	def test_pick_data_carries_the_page_and_what_is_shown(self):
		"""A button's data says its page and what the message shows (compare's eight tickers packed), within a button's
		64 bytes with 100 items."""
		press = buttons.PickPress('c', 's', 'x', pick.pack([0, 1, 2, 3, 4, 5, 98, 99]), (1 << 100) - 1, 'm2', 'a1b2')
		button = buttons.pick_button('x', press)
		self.assertEqual((buttons.parse(button.data), len(button.data) <= 64), (press, True))
		self.assertEqual(pick.unpack(press.shown), [0, 1, 2, 3, 4, 5, 98, 99])
		for data in ('k|c|0|x|0|0|z1|a1b2', 'k|c|0|x|0|0|p|a1b2', 'k|c|0|x|0|0|r-1|a1b2', 'k|c|0|x|0|0|s1|a1b2'):
			self.assertIsNone(buttons.parse(data))

	def test_a_pie_or_treemap_primes_the_other_charts_in_the_background(self):
		"""Once the first chart is out, a pie or treemap starts drawing the others in a thread (the first portfolio's
		other grouping first); compare (.history) and holdings start none, nor does a job's run, nor a chat without
		charts."""
		started = []
		self.patch(worker, 'prime_in_background', lambda *args: started.append(args))
		self.portfolios('Amy', 'Zed')
		for text in ('.treemap sector', '.history', '.compare', '.holdings'):
			self.command(text)
		self.assertEqual([args[1:] for args in started], [('t', 's', ['Amy', 'Zed'], 0)])
		worker.job_commands()['treemap'].run(delivery.chat('telegram:55', scheduled=True), words=[])
		self.settings(graph=False)
		self.command('.treemap')
		self.assertEqual(len(started), 1)

	def test_priming_draws_the_other_grouping_then_the_other_portfolios(self):
		"""pick.prime draws a treemap's shown portfolio's other groupings, then each other portfolio in every one. An
		empty chart is skipped, and a failure is logged and the rest still drawn."""
		drawn = []
		self.patch(render, 'draw', lambda chart: drawn.append(chart.title))
		self.portfolios('Amy', 'Bob', 'Cat', 'Zed')
		pick.prime(TELEGRAM, 't', '0', ['Amy', 'Bob', 'Zed'], 0)
		each = lambda name, *groups: [f'{name} treemap by {group}' for group in groups]
		every = ('sector', 'industry', 'country', 'currency', 'market')
		self.assertEqual(drawn, each('Amy', 'sector', 'country', 'currency', 'market') + each('Bob', *every) +
			each('Zed', *every))
		drawn.clear()
		real = holdings.prepare_treemap
		def prepare(name, by, service):
			"""Fail for Bob, answer nothing for Zed, as usual for the rest."""
			if name == 'Bob':
				raise RuntimeError('boom')
			return real(name, by, service) if name != 'Zed' else (['x'], None)
		self.patch(holdings, 'prepare_treemap', prepare)
		with contextlib.redirect_stderr(io.StringIO()) as err:
			pick.prime(TELEGRAM, 't', 's', ['Amy', 'Bob', 'Cat', 'Zed'], 0)
		self.assertEqual(drawn, each('Amy', 'industry', 'country', 'currency', 'market') + each('Cat', *every))
		self.assertIn('priming t Bob sector failed: boom', err.getvalue())

	def test_compare_typed_with_tickers_has_the_tickers_button_too(self):
		""".compare T1 T2 [period] answers with the period row and the tickers' + under its chart, those typed ticked
		and shown; tickers the chat does not offer, or a period no button has, leave the chart its period buttons."""
		self.command('.compare T3 T1 1y')
		self.assertEqual(self.labels(), [['7D', '1M', '● 1Y', 'Max', '+']])
		kind, lines, rows = self.tap('+')
		self.assertEqual([t for row in self.labels(rows) for t in row if t.startswith('✅')], ['✅ T1', '✅ T3'])
		self.command('.compare T1 NOPE')
		self.assertEqual(self.labels(), [['7D', '1M', '1Y', '● Max']])
		self.command('.compare T1 T2 3m')
		self.assertEqual(self.labels(), [['7D', '1M', '1Y', 'Max']])

	def test_every_chart_with_a_period_row_primes_its_other_periods(self):
		"""Once a chart with period buttons is out, its other periods are drawn in the background: .compare,
		.performance, the movers list and a picker's answer, but not where no chart goes."""
		started = []
		self.patch(charts, 'prime_in_background', lambda *args: started.append(args[:1] + args[1:2] + args[4:]))
		self.command('.compare T1 T2')
		self.command('.performance')
		self.command('.movers')
		self.command('.movers top')
		self.assertEqual(started, [('c', ['T1', 'T2'], 'x'), ('f', [''], 'm'), ('l', ['5', '0'], 'd'),
			('l', ['0', '10'], 'd')])
		started.clear()
		self.command('.price T1') # one stock's line, which has no chart here
		self.settings(graph=False)
		self.command('.compare T1 T2')
		self.assertEqual(started, [])

	def test_priming_draws_each_other_period_and_survives_a_failure(self):
		"""charts.prime draws the chart of each period button but the one shown, skipping one with nothing to draw,
		and logs a failure."""
		drawn = []
		self.patch(render, 'draw', lambda chart: drawn.append(chart.kind))
		built = []
		def build(kind, args, service, chat, period=None, days=None):
			"""Fail for 1M, answer nothing for 1Y, a chart for the rest."""
			built.append(period)
			if period == 'm':
				raise RuntimeError('boom')
			return 'caption', None if period == 'y' else render.Chart('bars', rows=(('a', 1.0),))
		self.patch(charts, 'build', build)
		with contextlib.redirect_stderr(io.StringIO()) as err:
			charts.prime('c', ['T1'], TELEGRAM, 'telegram:55', 'x')
		self.assertEqual((built, drawn), (['w', 'm', 'y'], ['bars']))
		self.assertIn("priming c ['T1'] m failed: boom", err.getvalue())


if __name__ == '__main__':
	unittest.main()
