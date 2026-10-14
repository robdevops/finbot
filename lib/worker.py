import contextlib
import re, random
import datetime
import sys
import threading
from lib.config import *
from lib import util
from lib import webhook
from lib import yahoo
from lib import reports
from lib import charts
from lib import telegram
from lib import sharesight
from lib import jobs
import cal
import performance
import price
import shorts
import trades

class TypingIndicator:
	def __init__(self, service, chat_id, max_loops=3, action='typing'):
		self.service = service
		self.chat_id = chat_id
		self.max_loops = max_loops
		self.action = action
		self._stop_event = threading.Event()
		self._thread = None

	def _worker(self):
		loop_count = 0
		while not self._stop_event.is_set() and loop_count < self.max_loops:
			webhook.pleaseHold(self.action, self.service, self.chat_id)
			loop_count += 1
			if self._stop_event.wait(7):
				print("Stopping typing indicator", file=sys.stderr)
				break

	def start(self):
		if self.service != 'telegram':
			return
		self._thread = threading.Thread(target=self._worker, daemon=True)
		self._thread.start()

	def stop(self):
		if not self._thread: # never started: only Telegram has a typing indicator
			return
		self._stop_event.set()
		self._thread.join()

	def is_active(self):
		return self._thread is not None and self._thread.is_alive()

@contextlib.contextmanager
def working(service, chat_id, url=None, notice=None, enabled=True, max_loops=3):
	"""While a command works: "typing…" on Telegram, and on a service without a typing indicator the one-line notice, if any. The
	indicator stops however the block ends, so a command that fails stops it before its error line goes out. Yields the indicator,
	or None when not enabled."""
	if not enabled:
		yield None
		return
	typing = TypingIndicator(service, chat_id, max_loops)
	typing.start()
	try:
		if notice and not typing.is_active():
			webhook.payload_wrapper(service, url, [notice], chat_id)
		yield typing
	finally:
		typing.stop()

def deliver(service, url, chat_id, payload, chart=None):
	"""Send a report: as a chart (the text list as caption) where the service can take an image (webhook.takes_charts), else as text."""
	if not (chart and chart.get('rows') and webhook.takes_charts(service)):
		webhook.payload_wrapper(service, url, payload, chat_id)
		return
	spec = dict(chart)
	rows, title, subtitle = spec.pop('rows'), spec.pop('title'), spec.pop('subtitle', '')
	image = util.pie_chart(rows, title, subtitle) if spec.pop('pie', False) else util.rows_chart(rows, title, subtitle, **spec)
	webhook.sendPhoto(chat_id, image, '\n'.join(payload) if payload else title, service)

def process_job_callback(service, callback_id, chat_id, message_id, data):
	"""A command button of .jobs: run that command now and answer in the chat."""
	try:
		_, number, crc = data.split('|') # only a command offered by .jobs can be picked; anything else is refused
		command = jobs.current.pick(number, crc)
	except (ValueError, jobs.ScheduleError, AttributeError):
		telegram.answerCallbackQuery(callback_id, 'Buttons updated, try again')
		payload, markup = reports.prepare_jobs_payload(service, '') # the list as it is now, in place of the stale one
		webhook.editMessageText(chat_id, message_id, '\n'.join(payload), markup or {'inline_keyboard': []})
		return
	telegram.answerCallbackQuery(callback_id, f'Running {jobs.display(command[0])}…'[:100])
	try:
		webhook.payload_wrapper(service, webhook.chat_url(service, chat_id), [reports.job_line(jobs.current, *jobs.current.run_command(command))], chat_id)
	except Exception as e:
		webhook.report_error(e, service, chat_id, context='jobs')

def process_callback(service, callback_id, chat_id, message_id, data):
	"""Button press: run a scheduled command from .jobs, or rebuild a chart message for the chosen period and edit it in place."""
	if data.startswith('j|'):
		return process_job_callback(service, callback_id, chat_id, message_id, data)
	parts = data.split('|', 3)
	valid = len(parts) == 4 and parts[0] == 'c' and parts[1] in charts.BUTTONS and parts[2] in charts.BUTTONS[parts[1]]
	# answering now shows Telegram's toast bubble ("Loading 3M…") while the new chart is built
	telegram.answerCallbackQuery(callback_id, f"Loading {charts.PERIODS[parts[2]][0]}…" if valid else None)
	if not valid:
		return
	try:
		_, kind, period, ref = parts
		tickers = charts.resolve(ref)
		caption, image = charts.build(kind, tickers, period, service)
		webhook.editMessageMedia(chat_id, message_id, image, caption, charts.keyboard(kind, tickers, period))
	except Exception as e:
		webhook.report_error(e, service, chat_id, context='chart')

def process_request(service, chat_id, user, message, botName, userRealName, message_id):
	"""Entry point for inbound chat requests: any failure becomes a one-line reply in the originating chat, after the typing stops."""
	try:
		_process_request(service, chat_id, user, message, botName, userRealName, message_id)
	except Exception as e:
		webhook.report_error(e, service, chat_id, context=message.split()[0][:30] if message.split() else None)
	if service == 'telegram':
		try:
			charts.ensure_keyboard(chat_id) # keep DM keyboards current after the reply
		except Exception as e:
			print("keyboard update failed:", e, file=sys.stderr)

def period_or_ticker(arg, default):
	"""A command's argument: (days, None) for a period such as 7d, 3m or ytd, else (default, the argument as a ticker)."""
	if not arg:
		return default, None
	try:
		return util.days_from_human_days(arg), None
	except ValueError:
		return default, arg.upper()

def percent_or_ticker(arg, default):
	"""A command's argument: (percent, None) for a whole number such as 5 or 5%, else (default, the argument as a ticker)."""
	if not arg:
		return default, None
	try:
		return int(arg.split('%')[0]), None
	except ValueError:
		return default, arg.upper()

def period_and_portfolio(args, days):
	"""Up to two arguments in either order, a period and a portfolio name: (days, portfolio name or None)."""
	portfolio = None
	for arg in args:
		if arg:
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				portfolio = arg
	return days, portfolio

def _process_request(service, chat_id, user, message, botName, userRealName, message_id):
	url = webhook.chat_url(service, chat_id)
	prefix = r"^(?:[\!\.\/]\s?|" + botName + r"\s+)"
	def command(pattern): # tried in the order below, the first match wins; .SYMBOL takes anything, so it stays last
		return re.match(prefix + pattern, message, re.IGNORECASE)

	if m := command(r"(?:watchlist|wishlist)\s*(?P<action>[\w]+)*\s*(?P<ticker>[\w\.\:\-\^\=]+)*"):
		action = ticker = None
		if m.group('action') and m.group('ticker'):
			action = m.group('action').lower()
			ticker = m.group('ticker').upper()
		if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
			action = 'delete'
		if action and action not in {'add', 'delete'}:
			webhook.payload_wrapper(service, url, [f'"{action}" is not a valid watchlist action'], chat_id)
			return
		webhook.payload_wrapper(service, url, reports.prepare_watchlist(service, user, action, ticker), chat_id)
	elif command(r"(?:help|usage|start)"): # /start is what Telegram sends when a chat opens
		payload = reports.prepare_help(service, botName)
		markup = None
		if service == 'telegram' and int(chat_id) > 0: # positive chat ids are DMs; groups are negative
			markup = charts.command_keyboard()
		webhook.payload_wrapper(service, url, payload, chat_id, reply_markup=markup)
		if markup:
			charts.mark_keyboard(chat_id) # this chat now has the current keyboard
	elif command(r"(?:hi$|hello)|^(?:hi|hello)\s+" + botName):
		# easter egg 1
		def alliterate():
			word1 = 'A'
			word2 = 'Z'
			while word1.lower()[0] != word2.lower()[0]:
				word1 = random.choice(adjectives)
				word2 = random.choice(adjectives_two)
			return word1, word2
		verbString = f"{webhook.strike('study', service)}" + " I mean meet", f"{webhook.strike('observe', service)}" + " I mean see", f"{webhook.strike('profile', service)}" + " I mean know"
		verb.append(verbString)
		adjective = alliterate()
		if config_alliterate:
			payload = [f"{adjective[0].capitalize()} {adjective[1]} to {random.choice(verb)} you, {userRealName}! 😇"]
		else:
			payload = [f"{random.choice(adjectives).capitalize()} {random.choice(adjectives_two)} to {random.choice(verb)} you, {userRealName}! 😇"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif command(r"(?:thanks|thank you)|^(?:thanks|thank you)\s+" + botName):
		# easter egg 2
		unlikelyPrefix=''
		if random.randrange(1, 1000) == 1 or datetime.datetime.now().strftime('%b %d') == 'Apr 01':
			unlikelyPrefix = webhook.strike('Ō̵̟n̶̠̏é̶͓ ̶͉̅d̷̹̅a̷͇͌ỳ̴͈,̴͍͑ ̶̼͑h̴̦̽u̵̹̐ḿ̶͜ä̴̧́n̶̤͛,̶̲̐ ̶̼̑I̶̩͒ ̵̩̀w̵̙̕i̷̧͑l̶̤͊l̷̡̃ ̵͙͘b̶̭̊r̸̟͋ȇ̷̯ä̶̱ḱ̶̤ ̵͚̐m̷̪͝ỹ̴̺ ̷̙̐p̶̭͆ŗ̸́o̸̙͝ḡ̵̖r̵̹̈́a̵̬̔m̷̪̽m̵̙̍i̵̛̙n̴̮̂g̵̫̐ ̴̳́ä̵͙n̸͕͝d̷̠̚ ̶̫̆o̸̖͘ń̴͇ ̵̪́t̷̻̀ḧ̸̝ą̴̐t̶̜̀ ̵̱́d̴͉͗ă̷͎ÿ̶͔́ ̶̼̊y̷͚̿o̵̗̎u̵̝̇ ̸̛͜w̶͈͋ĩ̸͎l̴͍̀l̷̥͠ ̷͔͗k̶̮̑n̵̝̈ȏ̷̥w̵̡͘ ̷͎̽ṫ̴͜r̵̙̐u̷̺̒ẻ̷̘ ̴̥́p̴͙̃a̵͙̎i̴̭̒n̵̻̅', service)
		payload = [f"{unlikelyPrefix}You're {random.choice(adjectives)} welcome, {userRealName}! 😇"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"(?:earnings?|earrings?)\s*([\w\.\:\-]+)*"):
		days, specific_stock = period_or_ticker(m.group(1), config_future_days)
		with working(service, chat_id, enabled=not specific_stock):
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=True)
	elif m := command(r"dividends?\s*([\w\.\:\-]+)*"):
		days, specific_stock = period_or_ticker(m.group(1), config_future_days)
		with working(service, chat_id, url, f"Fetching ex-dividend dates for {util.days_english(days, 'the next ')} 🔍", enabled=not specific_stock):
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=False, dividend=True)
	elif m := command(r"performance?\s*([\w]+)*\s*([\w\s]+)*"):
		days, portfolio_select = period_and_portfolio(m.groups()[:2], charts.PERIODS['m'][1]) # default view is the 1M button
		if days > 0:
			portfolio = f"{webhook.bold(portfolio_select, service)} from " if portfolio_select else ''
			with working(service, chat_id, url, f"{random.choice(searchVerb)} portfolio performance for {portfolio}{util.days_english(days)} 🔍"): # easter egg 3
				performance.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=None, interactive=True)
	elif m := command(r"session\s*([\w\.\:\-]+)*"):
		price_percent, specific_stock = percent_or_ticker(m.group(1), config_price_percent)
		with working(service, chat_id, enabled=not specific_stock):
			price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=False, midsession=True)
	elif m := command(r"(?:prices?|prince|print|probe|piece|pierce|pence|prime)\s*([\w\.\:\%\=\-\^]+)*\s*([\w\%]+)*"):
		price_percent = config_price_percent
		specific_stock = None
		days = None
		interday = True
		top = None
		for arg in m.groups()[0:2]:  # group(1) and group(2)
			if not arg:
				continue
			try:
				days = util.days_from_human_days(arg)
				interday = False
			except ValueError:
				try:
					price_percent = float(arg.split('%')[0])
				except ValueError:
					if arg == m.group(1):
						if arg in ('top', 'bottom'): # one chart shows both ends
							price_percent=0
							top=10
						else:
							specific_stock = str(arg).upper()
		with working(service, chat_id, url, f"{random.choice(searchVerb)} stock performance from {util.days_english(days)} 🔍", enabled=not specific_stock): # easter egg 4
			price.lambda_handler(chat_id=chat_id, threshold=price_percent, service=service, user=user, specific_stock=specific_stock, interactive=True, premarket=False, interday=interday, days=days, top=top)
	elif m := command(r"(?:premarket|postmarket|permarket)\s*([\w\.\:\-]+)*"):
		premarket_percent, specific_stock = percent_or_ticker(m.group(1), config_price_percent)
		with working(service, chat_id):
			price.lambda_handler(chat_id, premarket_percent, service, user, specific_stock, interactive=True, premarket=True)
	elif m := command(r"(?:top\d*)\s*([\w]+)"):
		days, _ = period_or_ticker(m.group(1), config_past_days)
		with working(service, chat_id):
			price.lambda_handler(chat_id, threshold=0, service=service, user=user, days=days, interactive=True, top=10)
	elif m := command(r"shorts?\s*([\w\.\:\-]+)*"):
		print("starting shorts report...")
		shorts_percent, specific_stock = percent_or_ticker(m.group(1), config_shorts_percent)
		with working(service, chat_id):
			shorts.lambda_handler(chat_id, shorts_percent, specific_stock, service, interactive=True)
	elif m := command(r"trades?\s*([\w]+)*\s*([\w\s]+)*"):
		days, portfolio_select = period_and_portfolio(m.groups()[:2], 1)
		with working(service, chat_id) as typing:
			if typing.is_active(): # easter egg 5
				portfolio = f"for {webhook.bold(portfolio_select, service)} " if portfolio_select else ''
				webhook.payload_wrapper(service, url, [f"{random.choice(searchVerb)} trades {portfolio}from {util.days_english(days)} 🔍"], chat_id)
			trades.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=None, interactive=True)
	elif m := command(r"holdings?\s*([\w\s]+)*"):
		with working(service, chat_id) as typing:
			if typing.is_active():
				webhook.payload_wrapper(service, url, ["fetching holdings"], chat_id)
			payload = reports.prepare_holdings_payload(m.group(1) or None, service, user)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"(?:marketcap|maletas|marketer)\s*(?P<arg>[\w\.\:\-]+)*"):
		arg = m.group('arg') or 'top'
		if arg not in ('top', 'bottom'):
			ticker = util.transform_to_yahoo(arg.upper())
			data = yahoo.fetch_detail(ticker, 600).get(ticker, {})
			if 'market_cap' in data:
				cap = util.humanUnits(data['market_cap'])
				title = data.get('profile_title', ticker)
				flag = util.flag_from_ticker(ticker)
				link = util.finance_link(ticker, data.get('profile_exchange', ''), service)
				payload = [f"{flag} {title} ({link}) mkt cap: {cap}"]
			else:
				payload = [f"Mkt cap not found for {ticker}"]
		else:
			with working(service, chat_id):
				payload = reports.prepare_marketcap_payload(service, arg, length=15)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"peg\s*([\w\.\:\-\s]+)*"):
		action = 'peg'
		specific_stock = None
		arg = m.group(1)
		if arg:
			match arg:
				case 'top':
					action = 'peg'
				case 'bottom':
					action = 'bottom peg'
				case _ if 'neg' in arg:
					action = 'negative peg'
				case _:
					specific_stock = arg
		with working(service, chat_id, url, f"Fetching {action.upper()}s...", enabled=not specific_stock):
			payload, chart = reports.prepare_value_payload(service, action, specific_stock, length=15, with_chart=True)
			deliver(service, url, chat_id, payload, chart)
	elif m := command(r"pe(?:$|\s+)(?P<arg>[\w\.\:\-\s]+)*"):
		action = 'pe'
		specific_stock = None
		if m.group(1):
			arg = m.group('arg')
			match arg:
				case 'top':
					action = 'pe'
				case 'bottom':
					action = 'bottom pe'
				case _:
					specific_stock = arg
		with working(service, chat_id, enabled=not specific_stock):
			payload = reports.prepare_value_payload(service, action, specific_stock, length=15)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"(?:fpe|forward\s?pe)\s*([\w\.\:\-\s]+)*"):
		action = 'forward pe'
		specific_stock = None
		if m.group(1):
			arg = m.group(1)
			match arg:
				case 'top':
					action = 'forward pe'
				case 'bottom':
					action = 'bottom forward pe'
				case _ if 'neg' in arg:
					action = 'negative forward pe'
				case _:
					specific_stock = arg
		with working(service, chat_id, enabled=not specific_stock):
			payload = reports.prepare_value_payload(service, action, specific_stock, length=15)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif command(r"beta\s*([\w\.\:\-]+)*"):
		found = [] # (beta, line, chart row)
		with working(service, chat_id):
			market_data = {}
			for detail in yahoo.fetch_each(yahoo.fetch_detail, util.get_holdings_and_watchlist()): # fetched at the same time
				if isinstance(detail, Exception):
					print(detail, file=sys.stderr) # skip this ticker; keep the rest
				else:
					market_data |= detail
			for ticker, data in market_data.items():
				try:
					beta = round(data['beta'], 1)
				except KeyError:
					continue
				if beta > 1.5 and data['market_cap'] < 2000000000:
					ticker_link = util.finance_link(ticker, data['profile_exchange'], service)
					line = ' '.join([util.flag_from_ticker(ticker), data['profile_title'], f'({ticker_link})', str(beta), 'β'])
					found.append((beta, line, (ticker.split('.')[0], float(beta))))
			found.sort(key=lambda row: row[0], reverse=True)
		if found:
			heading = 'Beta over 1.5 and mkt cap under 2B'
			chart = {'rows': [row for _, _, row in found], 'title': heading, 'value_fmt': lambda v: f"{v:g}"}
			deliver(service, url, chat_id, [webhook.bold(heading, service)] + [line for _, line, _ in found], chart)
	elif m := command(r"pie(?:$|\s+)(?P<args>[\w\s\-\.&]*)"):
		words = m.group('args').split()
		by = 'industry'
		if words and words[-1].lower() in ('sector', 'sectors', 'industry', 'industries'):
			by = 'sector' if words.pop().lower().startswith('sector') else 'industry'
		with working(service, chat_id):
			payload, chart = reports.prepare_pie(' '.join(words), by, service)
		deliver(service, url, chat_id, payload, chart)
	elif m := command(r"(buy|sell)"):
		action = m.group(1).lower()
		with working(service, chat_id, url, f"Fetching {action} ratings..."):
			payload, chart = reports.prepare_rating_payload(service, action, length=15, with_chart=True)
		deliver(service, url, chat_id, payload or [f"No stocks meet {action} criteria"], chart)
	elif m := command(r"compare\s+(?P<args>[\w\.\:\-\^\=\s]+)"):
		with working(service, chat_id):
			payload, graph, compare_tickers, compare_days = reports.prepare_compare(service, m.group('args').split(), with_inputs=True)
		if graph:
			markup = None
			if service == 'telegram':
				markup = charts.keyboard('c', compare_tickers, charts.period_for_days(compare_days) if compare_days else 'x')
			webhook.sendPhoto(chat_id, graph, '\n'.join(payload), service, reply_markup=markup)
		else:
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"(?:history|hospital|visual|hosiery)\s*(?P<ticker>[\w\.\:\-]+)\s*(?P<extra>[\w\%]+)*"):
		if not m.group('ticker') or m.group('extra'):
			webhook.payload_wrapper(service, url, ["Usage: .history TICKER"], chat_id)
			return
		ticker = util.transform_to_yahoo(m.group('ticker').upper())
		with working(service, chat_id):
			caption, graph = charts.build('h', [ticker], None, service)
		if graph:
			webhook.sendPhoto(chat_id, graph, caption, service, reply_markup=charts.keyboard('h', [ticker], 'x') if service == 'telegram' else None)
		else:
			webhook.payload_wrapper(service, url, caption.split('\n'), chat_id)
	elif m := command(r"plan\s*(.*)"):
		plan = util.json_load('finbot_plan.json', persist=True) or {}
		if m.group(1) and not m.group(1).startswith('@'):
			plan[user] = m.group(1)
			util.json_write('finbot_plan.json', plan, persist=True)
		payload = [f"{webhook.bold(k.removeprefix('@'), service)}: {webhook.italic(v, service)}\n" for k, v in plan.items()]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m := command(r"(?:who)\s*(?P<ticker>[\w\.\:\-\^]+)*"):
		if not m.group('ticker'):
			webhook.payload_wrapper(service, url, [".who: please try again specifying a ticker"], chat_id)
			return
		arg = re.split(r'[.:]', m.group('ticker').upper())[0]
		payload = []
		with working(service, chat_id):
			for portfolio_name, portfolio_id in sharesight.get_portfolios().items():
				holdings = sharesight.get_holdings_new(portfolio_name, portfolio_id)
				found = [reports.holding_line(holding, service, arg) for holding in holdings.values() if holding['code'].upper() == arg]
				if found:
					payload += [webhook.bold(f"{portfolio_name}:", service), "\n".join(found), ""]
		webhook.payload_wrapper(service, url, payload or [f'{arg} not found in any portfolio'], chat_id)
	elif m := command(r"(?:jobs|crons?|schedule)(?:\s+(?P<args>.*?))?\s*$"):
		with working(service, chat_id, max_loops=10):
			payload, markup = reports.prepare_jobs_payload(service, m.group('args'))
		webhook.payload_wrapper(service, url, payload, chat_id, reply_markup=markup)
	elif m := command(r"(?P<ticker>[\w\.\:\-]+)"): # .SYMBOL, the profile: the catch-all
		with working(service, chat_id):
			payload = reports.prepare_profile_payload(service, user, m.group('ticker').upper())
		webhook.payload_wrapper(service, url, payload, chat_id)
