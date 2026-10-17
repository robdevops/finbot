"""Failure and no-data scenarios: empty or broken upstream data, bad arguments, unknown portfolios, secrets
kept out of logs, and the bot's signals."""
import contextlib, io, os, re, signal, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from tests.common import *
from lib import log


COMMANDS = ('.price', '.price 7d', '.price top', '.session', '.premarket', '.performance 7d', '.shorts', '.peg', '.buy',
			'.sell', '.beta', '.pe', '.marketcap', '.earnings', '.dividend', '.trades', '.holdings', '.watchlist',
			'.T1', '.history T1', '.compare T1 T2')


class UpstreamEmpty(FinbotCase):
	"""Yahoo answers, but with nothing usable. Every command must reply sanely and never crash."""

	def run_all(self):
		"""Run every command in COMMANDS: each answers (one without data says so, as a reply), and none crashes."""
		for cmd in COMMANDS:
			with self.subTest(cmd=cmd):
				self.assertTrue(self.command(cmd), cmd)

	def test_yahoo_returns_empty_dict(self):
		"""Yahoo answers with no data at all: every command still replies sanely."""
		self.patch(yahoo, 'fetch', lambda ts: {})
		self.patch(yahoo, 'fetch_detail', lambda t, *a, **k: {})
		self.run_all()

	def test_yahoo_raises(self):
		"""Yahoo is down: each command reports one error line, not a traceback."""
		def down(*a, **k):
			"""Fail like Yahoo when it is unreachable."""
			raise RuntimeError('Yahoo API unavailable')
		for name in ('fetch', 'fetch_detail', 'price_series'):
			self.patch(yahoo, name, down)
		for cmd in ('.price', '.peg', '.T1', '.compare T1 T2'):
			with self.subTest(cmd=cmd):
				self.sent.clear(); self.errors.clear()
				worker.process_request(inbound.Message('telegram', '55', '@u', cmd, BOT, 'U'))
				self.assertEqual(len(self.errors), 1, cmd) # exactly one one-line report, not a traceback to the user
				self.assertTrue(self.errors[0].startswith('⚠️'))

	def test_sharesight_down_is_reported_once(self):
		"""Sharesight is down: .performance reports one error line."""
		def down(*a, **k):
			"""Fail like Sharesight when it errors."""
			raise RuntimeError('Sharesight performance error: boom')
		self.patch(sharesight, '_performance', down)
		self.patch(sharesight, '_portfolios', down)
		self.sent.clear(); self.errors.clear()
		worker.process_request(inbound.Message('telegram', '55', '@u', '.performance 7d', BOT, 'U'))
		self.assertEqual(len(self.errors), 1)

	def test_the_typing_notice_stops_before_any_message_goes_out(self):
		"""The typing notice stops before the first message of an answer goes out, for a command that replies, one that
		posts its report itself (.price, .trades), and one that fails: a later notice would show "typing…" again."""
		def down(*a, **k):
			"""Fail like Sharesight when it errors."""
			raise RuntimeError('Sharesight performance error: boom')
		self.patch(sharesight, '_performance', down)
		self.patch(delivery, 'report_error', REAL_REPORT_ERROR)
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)
		typing = []
		self.patch(telegram_common.TelegramBot, 'post_text', lambda dest, *a, **k: typing.append(dest.is_typing()))
		self.patch(telegram_common.TelegramBot, 'post_chart', lambda dest, *a, **k: typing.append(dest.is_typing()) or
			{'ok': True})
		for cmd in ('.help', '.price', '.trades 7d', '.performance 7d'):
			with self.subTest(cmd=cmd), contextlib.redirect_stderr(io.StringIO()):
				typing.clear()
				worker.process_request(inbound.Message('telegram', '55', '@u', cmd, BOT, 'U'))
				self.assertEqual(typing, [False])

	def test_no_holdings_and_empty_watchlist(self):
		"""With nothing held and nothing watched, the watchlist, price and earnings commands still answer."""
		self.patch(watchlist, 'with_holdings', lambda chat: [])
		for cmd in ('.watchlist', '.price', '.earnings'):
			with self.subTest(cmd=cmd):
				self.command(cmd)


class WatchlistActions(FinbotCase):
	def test_add_duplicate_delete_and_unknown_action(self):
		"""Add, add again (said differently), remove, and an unknown action is refused by name."""
		add = self.command('.watchlist add MSFT')
		self.assertTrue(add)
		self.assertEqual(state.load('finbot_watchlist.json'), {'chats': {'telegram:55': ['MSFT']}})
		again = self.command('.watchlist add MSFT')
		self.assertNotEqual(add, again) # a duplicate is reported differently from a first add
		self.assertEqual(watchlist.tickers('telegram:55'), ['MSFT'])
		self.command('.watchlist rm MSFT')
		self.assertEqual(watchlist.tickers('telegram:55'), [])
		self.assertEqual(self.command('.watchlist frobnicate MSFT'), [('text', ['Usage: .watchlist [add|del SYMBOL]'])])

	def test_a_bare_symbol_yahoo_does_not_know_is_tried_on_the_asx(self):
		"""A symbol Yahoo does not know is added as its ASX listing, once, and removed by the same name; a ticker with a
		market is not retried."""
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts if t.endswith('.AX')})
		self.assertIn('I added', str(self.command('.watchlist add BHP')))
		self.assertIn('already tracking', str(self.command('.watchlist add BHP')))
		# a ticker with a market is not retried
		self.assertIn('could not find', str(self.command('.watchlist add BHP.L')))
		self.assertEqual(watchlist.tickers('telegram:55'), ['BHP.AX'])
		self.assertIn('I deleted', str(self.command('.watchlist del bhp')))
		self.assertEqual(watchlist.tickers('telegram:55'), [])

	def test_two_chats_adding_at_once_both_count(self):
		"""Two chats adding at once both count: Yahoo is asked before the file is opened, where both adds used to read
		the list, wait on Yahoo, and the later write won."""
		def slow_fetch(tickers):
			"""A Yahoo that takes its time, so the two adds overlap."""
			time.sleep(0.01)
			return {t: market_entry(t) for t in tickers}
		self.patch(yahoo, 'fetch', slow_fetch)
		threads = [threading.Thread(target=holdings.prepare_watchlist, args=(TELEGRAM, chat, '@u', 'add', ticker))
			for chat, ticker in (('telegram:55', 'T1'), ('telegram:55', 'T2'), ('slack:C1', 'T3'))]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(sorted(watchlist.tickers('telegram:55')), ['T1', 'T2'])
		self.assertEqual(watchlist.tickers('slack:C1'), ['T3'])

	def test_removing_a_ticker_yahoo_no_longer_knows(self):
		"""A ticker Yahoo no longer knows is still removed, and said to be; removing it again says it is not there."""
		state.save('finbot_watchlist.json', {'chats': {'telegram:55': ['GONE', 'T1']}})
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts if t != 'GONE'})
		self.assertIn('I deleted', str(self.command('.watchlist rm GONE')))
		self.assertIn('could not find', str(self.command('.watchlist rm GONE')))
		self.assertEqual(watchlist.tickers('telegram:55'), ['T1'])


class BadArguments(FinbotCase):
	def test_compare_argument_errors_give_usage(self):
		""".compare with too few or too many tickers, or one twice, gets its usage."""
		for cmd in ('.compare T1', '.compare T1 T2 T3 T4 T5 T6 T7 T8 T9', '.compare T1 T1'):
			with self.subTest(cmd=cmd):
				self.assertIn('Usage', str(self.command(cmd)))

	def test_no_data_is_an_answer_not_an_error(self):
		""".compare or .history of a ticker without prices, and a period button with nothing to draw, say so in a plain
		reply: no error line."""
		def no_history(t, *a, **k):
			"""Fail like Yahoo for a ticker with no price history."""
			raise yahoo.NoData(f'no price history for {t}')
		self.patch(yahoo, 'price_series', no_history)
		self.patch(yahoo, 'price_history', no_history)
		self.assertEqual(self.command('.compare T1 T2'), [('text', ['no price history for T1'])])
		self.assertEqual(self.command('.history T1'), [('text', ['no price history for T1'])])
		self.sent.clear()
		worker.process_callback(inbound.Press('telegram', 'cb', '55', '9', 'c|h|m|T1'))
		self.assertEqual((self.sent, self.errors), ([('text', ['no price history for T1'])], []))

	def test_history_without_a_ticker_or_with_extra_argument_gives_usage(self):
		""".history with an extra argument gets its usage, not the profile of a ticker called HISTORY; with no
		ticker, the buttons for one."""
		self.assertEqual(self.command('.history')[0][0], 'photo') # the first ticker's answer: blank, nothing to draw
		self.assertEqual(self.command('.history T1 1y'), [('text', ['Usage: .history SYMBOL'])])


class PortfolioNames(FinbotCase):
	def test_an_unknown_portfolio_gets_the_same_answer_everywhere(self):
		"""An unknown portfolio gets one answer from .trades, .performance, .holdings and .pie: the ones there are."""
		for cmd in ('.trades 7d Nope', '.performance Nope', '.holdings Nope', '.pie Nope'):
			# it used to be a ValueError, "no Sharesight data found", or two wordings of this
			with self.subTest(cmd=cmd):
				self.assertEqual(self.command(cmd), [('text', ['Nope portfolio not found. I only know about:', 'Rob'])])

	def test_a_portfolio_name_in_any_case(self):
		"""A portfolio's name is matched in any case."""
		holding = {'code': 'T1', 'market_code': 'NASDAQ', 'name': 'Co T1', 'holding_id': 1}
		self.patch(sharesight.Portfolio, 'holdings', lambda portfolio: {'T1:NASDAQ': holding})
		self.assertIn('Holdings for Rob (1)', str(self.command('.holdings rob')))

	def test_commands_with_nothing_to_show_say_so(self):
		"""A command with nothing to show says so, where it used to send nothing at all: .plan before anyone has saved
		one, .performance over no days, a ratio of a ticker Yahoo does not know."""
		self.patch(yahoo, 'fetch', lambda ts: {t: market_entry(t) for t in ts if not t.startswith('XYZ')})
		for text, reply in (('.plan', 'No plans yet: .plan TEXT records yours'),
				('.performance 0d', 'The period must cover a day or more, such as 7d, 3m or ytd'),
				('.pe XYZ', 'XYZ: no data found'), ('.peg XYZ', 'XYZ: no data found')):
			with self.subTest(text=text):
				self.assertEqual(self.command(text), [('text', [reply])])

	def test_trades_with_no_buy_or_sell_still_get_an_answer(self):
		""".trades with only dividends says there were no trades (it used to say nothing)."""
		self.patch(sharesight, '_trades', lambda pid, days=None: [{'id': 2, 'transaction_type': 'DIVIDEND'}])
		self.assertIn('No trades', str(self.command('.trades 7d'))) # it used to say nothing at all


class CommandArguments(FinbotCase):
	def args(self, message):
		"""The (command's first name, its Args) that a message calls."""
		command, args = worker.read(message, BOT)
		return command and command.names[:1], args

	def test_period_and_portfolio_in_either_order(self):
		"""A period and a portfolio name, of several words too, come in either order, and either may be left out."""
		for text, expected in (('', (None, '')), ('7d', (7, '')), ('Rob', (None, 'Rob')), ('7d Rob', (7, 'Rob')),
				('Rob 7d', (7, 'Rob')), ('My Portfolio', (None, 'My Portfolio')),
				('My Portfolio 3m', (90, 'My Portfolio')),
				('Rob ', (None, 'Rob'))):
			with self.subTest(text=text):
				_, args = self.args('.performance ' + text)
				self.assertEqual((args.days, args.rest), expected)

	def test_a_percentage_is_a_number_and_nan_a_ticker(self):
		"""A number, with or without %, is a threshold; nan and inf are tickers."""
		for arg, expected in (('', (None, [])), ('2.5', (2.5, [])), ('3%', (3.0, [])), ('T1', (None, ['T1'])),
				('nan', (None, ['nan'])), ('inf', (None, ['inf']))):
			with self.subTest(arg=arg):
				_, args = self.args('.session ' + arg)
				self.assertEqual((args.percent, args.words), expected)
		self.assertIn('2.5%', str(self.command('.session 2.5'))) # a threshold, not a ticker called 2.5

	def test_a_command_is_its_whole_name_in_any_case(self):
		"""A command is called by its whole name, in any case and from any of its prefixes; a word that only starts with
		one is a ticker (.planet used to save the plan "et"), and the bot's name among the arguments is left out."""
		for message, name in (('.PRICE 7d', 'price'), ('! price', 'price'), ('/price@bot 7d', 'price'),
				('@bot price', 'price'), ('.forward PE top', 'forward pe'), ('.buy/sell', 'buy'),
				('.price @bot', 'price')):
			with self.subTest(message=message):
				self.assertEqual(self.args(message)[0], (name,))
		for message in ('.planet', '.shortman', '.pricey', '.stock T1', '/profile T1'):
			with self.subTest(message=message):
				self.assertEqual(self.args(message)[0], ('stock',), message) # .SYMBOL
		self.assertEqual(self.args('.price @bot')[1].words, [])
		for message in ('price 7d', '/price@otherbot', '...', '. ?'):
			with self.subTest(message=message):
				self.assertEqual(worker.read(message, BOT), (None, None))

	def test_keywords_in_any_case(self):
		"""A keyword is read in any case, from either end: .price TOP is the top list, not the ticker TOP."""
		for message, keyword in (('.price TOP', 'top'), ('.price 7d Bottom', 'bottom'), ('.pie Rob Sectors', 'sector'),
				('.fpe NEG', 'negative'), ('.watchlist ADD x', 'add'), ('.watchlist Remove x', 'delete')):
			with self.subTest(message=message):
				self.assertEqual(self.args(message)[1].keyword, keyword)
		self.assertIn('Top 10 performers', str(self.command('.price TOP 7d')))

	def test_a_bare_number_on_price_is_a_percent(self):
		"""As on .session, .premarket and .shorts, and as doc/commands.md has it; a period carries its unit."""
		self.assertIn('3% at close', str(self.command('.price 3'))) # it used to be a 3-day report
		self.assertIn('Price movement ≥ 3%', str(self.command('.price 3 7d'))) # the 3 used to be dropped
		self.assertIn('Price movement ≥ 5%', str(self.command('.price 7d')))

	def test_top_is_gone(self):
		""".top is a ticker now, like any word: the command is .price top."""
		# .price top 7d is the command; .top is a ticker now, like any word
		self.assertIn('Co TOP', str(self.command('.top 7d')))

	def test_a_ratio_command_reads_its_ticker_as_the_other_commands_do(self):
		""".pe t1 reads its ticker in any case, and a trailing space after top is fine."""
		self.assertIn('Co T1 ', str(self.command('.pe t1')))
		self.assertIn('Top 15 tracked stocks by pe ratio', str(self.command('.pe top '))) # trailing space and all

	def test_the_greetings_are_gone(self):
		"""hi @bot gets no answer, and .hello and .thanks are tickers like any word."""
		self.assertEqual(self.command('hi @bot'), [])
		self.assertIn('Co HELLO', str(self.command('.hello')))

	def test_a_ticker_yahoo_does_not_know_is_tried_on_the_local_exchange(self):
		"""A bare ticker Yahoo does not know is tried with exchange_suffix, for every command that takes one; one with a
		market is not, nor any with exchange_suffix empty."""
		asked = []
		self.patch(yahoo, 'fetch', lambda ts: asked.append(sorted(ts)) or {t: market_entry(t) for t in ts if '.' in t})
		self.assertEqual(yahoo.symbols(['BHP', 'BHP.L', 'cba', 'CBA:ASX']), ['BHP.AX', 'BHP.L', 'CBA.AX', 'CBA.AX'])
		self.assertEqual(asked, [['BHP', 'CBA'], ['BHP.AX', 'CBA.AX']]) # two requests, however many tickers
		self.settings(exchange_suffix='NZ')
		self.assertEqual(yahoo.symbol('BHP'), 'BHP.NZ')
		self.settings(exchange_suffix='')
		asked.clear()
		self.assertEqual(yahoo.symbol('BHP'), 'BHP')
		self.assertEqual(asked, []) # nothing to try, so Yahoo is not asked
		self.settings(exchange_suffix='AX')
		for message, shown in (('.price BHP', 'BHP.AX'), ('.history BHP', 'BHP.AX'), ('.earnings BHP', 'BHP.AX'),
				('.shorts BHP', 'BHP'), ('.pe BHP', 'BHP'), ('.marketcap BHP', 'BHP.AX'), ('.BHP', 'BHP.AX')):
			with self.subTest(message=message):
				self.assertIn('Co BHP.AX', str(self.command(message)))


class SecretsStayOutOfLogs(FinbotCase):
	"""A failed request's error carries its URL: the Telegram token, a Slack or Discord webhook path, a Yahoo crumb."""
	SECRET_URL = 'https://api.telegram.org/bot123456:SECRET-tok_en/sendMessage?chat_id=1'

	def stderr_of(self, call):
		"""What call() writes to stderr."""
		err = io.StringIO()
		with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
			call()
		return err.getvalue()

	def test_a_failed_send_logs_no_token(self):
		"""A failed send logs no Telegram, Slack or Discord token, nor the token of a Discord interaction."""
		def refuse(url, **kwargs):
			"""Fail like requests does, the URL and headers in the message."""
			raise ConnectionError(f"Max retries exceeded with url: {url} (headers {kwargs.get('headers')})")
		self.patch(net, 'post', refuse)
		self.patch(net, 'request', lambda method, url, **kwargs: refuse(url, **kwargs))
		token = 'MTAwMDAwMDAwMDAwMDAwMDAwMDA.SECRET.' + 'a' * 38 # a Discord bot token's shape
		self.env(slackBotToken='xoxb-SECRET', telegram_api=self.SECRET_URL.split('sendMessage')[0],
			discordBotToken=token)
		log = self.stderr_of(lambda: telegram_common.TelegramBot('1').post_text('hi'))
		log += self.stderr_of(lambda: slack_common.SlackBot('C1').post_text('hi'))
		slash = discord_common.DiscordBot('77', interaction='42/SECRET-interaction')
		log += self.stderr_of(lambda: slash.post_text('hi'))
		self.assertIn('failed', log)
		for secret in ('SECRET-tok_en', 'xoxb-SECRET', 'SECRET-interaction', token):
			self.assertNotIn(secret, log)

	def test_the_traceback_of_a_reported_error_is_redacted(self):
		"""The traceback logged with a reported error is redacted."""
		self.patch(delivery, 'report_error', REAL_REPORT_ERROR)
		self.patch(telegram_common.TelegramBot, 'post_text', lambda *a, **k: None)
		try:
			raise ConnectionError('failed: ' + self.SECRET_URL)
		except ConnectionError as e:
			log = self.stderr_of(lambda: delivery.report_error(e, telegram_common.TelegramBot('55'), context='x'))
		self.assertIn('Traceback', log)
		self.assertIn('bot<redacted>', log)
		self.assertNotIn('SECRET-tok_en', log)


class Unbuffered(io.StringIO):
	"""A stream like stderr under PYTHONUNBUFFERED (finbot.service, the image): each write is a write to the journal,
	whose system call lets another thread run."""

	def write(self, text):
		"""Let another thread run, then write."""
		time.sleep(0)
		return super().write(text)


class WholeLogLines(unittest.TestCase):
	"""bot.WholeLines, the bot's stderr: a line goes out whole, whichever threads log at once."""

	def test_lines_that_threads_print_at_once_stay_whole(self):
		"""Lines that threads print at the same time come out whole, never mixed ("TTL:cache hit:  34254 s/var/..."):
		print() writes its pieces one by one, and a thread's pieces wait for the end of its line."""
		out = Unbuffered()
		stream = bot.WholeLines(out)
		def log(n):
			"""Print lines of several pieces each."""
			for i in range(200):
				print('cache hit:', f'/var/lib/finbot/cache/{n}.json', 'TTL:', f'{i}s', file=stream)
		threads = [threading.Thread(target=log, args=(n,)) for n in range(8)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		lines = out.getvalue().splitlines()
		self.assertEqual(len(lines), 8 * 200)
		self.assertEqual([line for line in lines if not re.fullmatch(r'cache hit: \S+/\d\.json TTL: \d+s', line)], [])

	def test_a_flush_writes_a_line_that_has_not_ended(self):
		"""A flush writes what the thread holds, though its line has not ended; the rest passes through."""
		out = io.StringIO()
		stream = bot.WholeLines(out)
		print('partial', end='', file=stream)
		self.assertEqual(out.getvalue(), '')
		stream.flush()
		self.assertEqual(out.getvalue(), 'partial')
		self.assertEqual(stream.getvalue(), 'partial') # the stream's own


class LogLevels(FinbotCase):
	"""log_level: each of syslog's levels lets in its own lines and those of the levels above it."""

	def logged(self, level, run):
		"""What run() logs with log_level at this level."""
		self.settings(log_level=level)
		with contextlib.redirect_stderr(io.StringIO()) as err:
			run()
		return err.getvalue().splitlines()

	def test_each_level_lets_in_its_own_lines_and_those_above_it(self):
		"""An error always reaches the log; WARN adds the warnings, INFO what finbot does, DEBUG its detail."""
		def each():
			"""A line at each level."""
			log.error('e')
			log.warn('w')
			log.info('i')
			log.debug('d')
		for level, shown in (('ERROR', 'e'), ('WARN', 'ew'), ('INFO', 'ewi'), ('DEBUG', 'ewid')):
			with self.subTest(log_level=level):
				self.assertEqual(self.logged(level, each), list(shown))

	def test_a_cache_miss_hit_or_write_is_debug(self):
		"""A cache miss (of a file not there, or too old), a hit, and the write after a miss are logged at DEBUG only:
		at INFO, the request a miss sends is the line."""
		def twice():
			"""A miss and its write, then a hit, then a miss of a file too old."""
			cache.cached('finbot_test.json', 60, lambda: {'a': 1})
			cache.cached('finbot_test.json', 60, lambda: {'a': 1})
			cache.cached('finbot_test.json', -1, lambda: {})
		where = cache.path('finbot_test.json')
		self.assertEqual(self.logged('INFO', twice), [])
		os.remove(where)
		lines = self.logged('DEBUG', twice)
		kinds = [line.split(':')[0] for line in lines]
		self.assertEqual(kinds, ['cache miss', 'cache write', 'cache hit', 'cache miss'])
		self.assertRegex(lines[2], r'^cache hit: \S+finbot_test\.json TTL: \d+s$')


	def test_a_stock_without_a_market_cap_is_debug(self):
		"""A stock that .marketcap cannot rank, without a market cap (an ETF), is logged at DEBUG only: nothing went
		wrong."""
		self.patch(yahoo, 'fetch', lambda tickers: {'ETF1': {'profile_title': 'A Fund', 'profile_exchange': 'NYSE'}})
		self.patch(yahoo, 'add_usd_market_caps', lambda quotes: quotes)
		rank = lambda: rankings.marketcap_list(TELEGRAM, '55')
		self.assertEqual((self.logged('INFO', rank), self.logged('DEBUG', rank)), ([], ['ETF1 no market cap']))


class RequestLog(FinbotCase):
	"""Each request that goes out (a cache miss, or a call that has no cache) is a line at INFO."""

	def test_each_request_is_a_short_line_without_secrets(self):
		"""A request logs its method and URL at INFO, without the scheme or a secret, cut to log_width characters (71,
		the last an ellipsis); Telegram's long polling (logged=False) does not, and nothing does below INFO."""
		with contextlib.redirect_stderr(io.StringIO()) as err:
			net.get('https://query1.finance.yahoo.com/v7/finance/quote?crumb=s3cret')
			net.post('https://api.telegram.org/bot123:ABC-def/sendMessage', json={})
			net.request('PATCH', 'https://discord.com/api/v10/channels/7/messages/9', json={})
			net.post('https://api.telegram.org/bot123:ABC-def/getUpdates', json={}, logged=False)
			net.get('https://query2.finance.yahoo.com/v10/finance/quoteSummary/ARM.L?modules=calendarEvents,'
				'defaultKeyStatistics,earnings,financialData,price&crumb=s3cret')
		lines = err.getvalue().splitlines()
		self.assertEqual(lines, ['GET query1.finance.yahoo.com/v7/finance/quote?crumb=<redacted>',
			'POST api.telegram.org/bot<redacted>/sendMessage', 'PATCH discord.com/api/v10/channels/7/messages/9',
			'GET query2.finance.yahoo.com/v10/finance/quoteSummary/ARM.L?modules=ca…'])
		self.assertEqual(len(lines[3]), 71)
		self.settings(log_level='WARN')
		with contextlib.redirect_stderr(io.StringIO()) as err:
			net.get('https://example.com/')
		self.assertEqual(err.getvalue(), '')

	def test_log_width_sets_where_a_long_line_is_cut(self):
		"""The log_width setting is where a long line is cut, its last character an ellipsis; at 0 none is."""
		whole = 'GET query2.finance.yahoo.com/v10/finance/quoteSummary/ARM.L?modules=calendarEvents' # 82 characters
		for width, line in ((20, 'GET query2.finance.…'), (81, whole[:80] + '…'), (82, whole), (0, whole), (1, '…')):
			with self.subTest(width=width):
				self.settings(log_width=width)
				with contextlib.redirect_stderr(io.StringIO()) as err:
					net.get('https://' + whole[4:])
				self.assertEqual(err.getvalue().splitlines(), [line])

	def test_a_chat_message_is_one_line_cut_to_log_width(self):
		"""A chat message is logged on one line, its line breaks spaces, cut to log_width characters like a request's;
		at 0 it is whole, still on one line. So is one not run again, sent twice within a second."""
		self.patch(worker, 'process_request', lambda message: None)
		self.patch(bot, 'doubled', REAL_DOUBLED)
		text = '/jobs add message daily at 9am "Morning!\nThe ASX opens at 10am,\n\nso coffee first"'
		def logged(update_id, chat=55):
			"""What taking a Telegram message of that text in that chat logs."""
			update = {'update_id': update_id, 'message': {'message_id': update_id, 'chat': {'id': chat},
				'from': {'first_name': 'Rob', 'username': 'rob'}, 'text': text}}
			with contextlib.redirect_stderr(io.StringIO()) as err:
				bot.take(telegram_common.READER, update)
				self.join_workers()
			return err.getvalue().splitlines()
		whole = 'Telegram @rob /jobs add message daily at 9am "Morning! The ASX opens at 10am, so coffee first"'
		self.assertEqual(logged(1), [whole[:70] + '…'])
		self.assertEqual(logged(2), ['Telegram @rob sent it again within 1 s, not run again: /jobs add messa…'])
		self.settings(log_width=0)
		self.assertEqual(logged(3, chat=66), [whole]) # another chat's: taken


class SharedSession(unittest.TestCase):
	def test_the_session_keeps_no_cookies(self):
		"""Yahoo's cookie goes in a header: a stored one would go to fc.yahoo.com, which then sets no new one."""
		import email.message, urllib.request
		from lib import net
		headers = email.message.Message()
		headers['Set-Cookie'] = 'A3=d=AQAB; Max-Age=31557600; Domain=.yahoo.com; Path=/; Secure'
		response = type('Response', (), {'info': lambda self: headers})()
		net.session.cookies.extract_cookies(response, urllib.request.Request('https://fc.yahoo.com/'))
		self.assertEqual(len(net.session.cookies), 0)


class SignalHandOff(unittest.TestCase):
	def test_a_signal_handler_hands_its_work_to_a_thread_one_at_a_time(self):
		"""A signal handler returns at once, and its work runs in a thread of its own, one signal's after another's."""
		events = []
		def work():
			"""Record the start and the end, a while apart."""
			events.append('start')
			time.sleep(0.1)
			events.append('end')
		handler = bot.in_thread(work)
		started = time.monotonic()
		handler(signal.SIGHUP, None)
		handler(signal.SIGHUP, None)
		self.assertLess(time.monotonic() - started, 0.05) # neither waited for the work
		deadline = time.monotonic() + 5
		while len(events) < 4 and time.monotonic() < deadline:
			time.sleep(0.01)
		self.assertEqual(events, ['start', 'end', 'start', 'end']) # never two at once


class CacheFlush(FinbotCase):
	def test_a_flush_fills_the_cache_again_at_once(self):
		"""Once the cache is deleted, a flush starts the warm jobs, through the scheduler, in a thread of their own."""
		started = []
		self.patch(bot.jobs, 'start_thread', lambda target, *args: started.append((target, args)))
		self.patch(bot.jobs, 'current', 'the scheduler')
		with contextlib.redirect_stderr(io.StringIO()) as log:
			bot.flush_cache()
		self.assertIn('cache: flushed', log.getvalue())
		self.assertEqual(started, [(bot.jobs.warm_now, ('the scheduler',))])


OPTIONAL = ('waitress', 'websocket', 'discord', 'nacl') # each imported only by the mode that needs it


class OptionalLibraries(unittest.TestCase):
	"""An install without the optional libraries (requirements-optional.txt) runs every mode that does not need them."""

	def blocked(self, data):
		"""The environment of a process for which no optional library can be imported, and that has no webhook set."""
		stubs = Path(data, 'stubs')
		stubs.mkdir()
		for name in OPTIONAL:
			(stubs / f'{name}.py').write_text('raise ImportError("blocked by the test")\n')
		env = bare_environment()
		env.update(DATA_DIR=data, port='0', PYTHONPATH=str(stubs))
		no_jobs(data)
		return env

	def test_every_module_imports_without_them(self):
		"""bot and every module of lib and lib.reports import with the optional libraries blocked, and none of them is
		imported."""
		code = ('import importlib, pkgutil, sys, bot, lib, lib.reports\n'
			'for package in (lib, lib.reports):\n'
			'    for module in pkgutil.iter_modules(package.__path__, package.__name__ + "."):\n'
			'        importlib.import_module(module.name)\n'
			f'print(sorted(name for name in {OPTIONAL!r} if sys.modules.get(name)))')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=self.blocked(data), capture_output=True,
				text=True, timeout=60)
		self.assertEqual(out.stdout.strip().splitlines()[-1:], ['[]'], out.stderr)

	def test_finbot_starts_without_them(self):
		"""With no webhook set, bot.py starts with the optional libraries blocked: no HTTP server, so no waitress."""
		with tempfile.TemporaryDirectory() as data:
			proc = subprocess.Popen([sys.executable, '-u', 'bot.py'], cwd=ROOT, env=self.blocked(data),
				stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
			self.addCleanup(proc.wait)
			self.addCleanup(proc.kill)
			lines = []
			for line in proc.stderr:
				lines.append(line)
				if line.startswith('finbot is running'):
					break
			self.assertIsNone(proc.poll(), ''.join(lines))
			self.assertIn('No webhook is set: finbot takes no HTTP requests', ''.join(lines))


class StartupSignals(unittest.TestCase):
	"""A reload (SIGHUP) that arrives while the bot is still starting must not kill it."""

	def test_sighup_during_startup_is_ignored_and_works_afterwards(self):
		"""A SIGHUP while bot.py starts is ignored, where its default action would kill it; once serving, it reloads."""
		with tempfile.TemporaryDirectory() as data:
			no_jobs(data)
			env = bare_environment()
			env.update(DATA_DIR=data, port='0')
			proc = subprocess.Popen([sys.executable, '-u', 'bot.py'], cwd=ROOT, env=env, stderr=subprocess.PIPE,
				stdout=subprocess.DEVNULL, text=True)
			self.addCleanup(proc.wait)
			self.addCleanup(proc.kill)
			deadline = time.monotonic() + 30
			# until SIGHUP is ignored
			while not int(Path(f'/proc/{proc.pid}/status').read_text().split('SigIgn:')[1].split()[0], 16) & 1:
				self.assertLess(time.monotonic(), deadline)
				time.sleep(0.001)
			proc.send_signal(signal.SIGHUP) # still importing: the default action would kill it
			lines = []
			for line in proc.stderr:
				lines.append(line)
				if line.startswith('finbot is running'): # the handlers are in
					break
			self.assertIsNone(proc.poll(), ''.join(lines))
			proc.send_signal(signal.SIGHUP)
			for line in proc.stderr: # a reload now runs (there is no settings.conf here, so it says so)
				lines.append(line)
				if 'reload requested' in line:
					break
			self.assertIsNone(proc.poll(), ''.join(lines))
			self.assertIn('reload requested but', ''.join(lines))

	def test_usr1_flushes_the_cache_and_keeps_the_state(self):
		"""SIGUSR1 is ignored in startup, then clears the cache but not writes in flight, anything else there or the
		state."""
		with tempfile.TemporaryDirectory() as data:
			cache = Path(data, 'cache')
			(cache / 'other').mkdir(parents=True)
			cached = ('finbot_yahoo_cookie.json', 'finbot_chart_0123456789abcdef0123.png', 'finbot_x.json.abc.tmp')
			for name in cached: # the last: a write in flight
				(cache / name).write_text('{}')
			Path(data, 'finbot_watchlist.json').write_text('["T1"]') # state, not cache
			Path(data, 'settings.conf').write_text('cache=False\n') # the warm jobs a flush starts fetch nothing
			no_jobs(data)
			env = bare_environment()
			env.update(DATA_DIR=data, port='0')
			proc = subprocess.Popen([sys.executable, '-u', 'bot.py'], cwd=ROOT, env=env, stderr=subprocess.PIPE,
				stdout=subprocess.DEVNULL, text=True)
			self.addCleanup(proc.wait)
			self.addCleanup(proc.kill)
			deadline = time.monotonic() + 30
			while not int(Path(f'/proc/{proc.pid}/status').read_text().split('SigIgn:')[1].split()[0],
					16) & (1 << (signal.SIGUSR1 - 1)):
				self.assertLess(time.monotonic(), deadline)
				time.sleep(0.001)
			proc.send_signal(signal.SIGUSR1) # still starting: ignored, where its default action would kill the bot
			lines = []
			for line in proc.stderr:
				lines.append(line)
				if line.startswith('finbot is running'): # the handlers are in
					break
			self.assertIsNone(proc.poll(), ''.join(lines))
			self.assertEqual(len(os.listdir(cache)), 4) # nothing flushed yet
			proc.send_signal(signal.SIGUSR1)
			for line in proc.stderr:
				lines.append(line)
				if 'cache: warm jobs done' in line: # each in a child process, as the scheduler is off
					break
			self.assertIn('cache: flushed 2 files', ''.join(lines))
			self.assertIn('cache: filling it again: sharesight_warm, yahoo_warm', ''.join(lines))
			self.assertEqual(sorted(os.listdir(cache)), ['finbot_x.json.abc.tmp', 'other'])
			self.assertTrue(Path(data, 'finbot_watchlist.json').exists())


if __name__ == '__main__':
	unittest.main()
