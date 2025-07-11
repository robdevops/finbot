import re, random
import datetime
import sys
import threading
from lib.config import *
from lib import util
from lib import webhook
from lib import yahoo
from lib import reports
from lib import sharesight
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
		self._thread = threading.Thread(target=self._worker)
		self._thread.start()

	def stop(self):
		if self.service != 'telegram' or not self._thread:
			return
		self._stop_event.set()
		self._thread.join()

	def is_active(self):
		return self.service == 'telegram' and self._thread is not None and self._thread.is_alive()


def process_request(service, chat_id, user, message, botName, userRealName, message_id):
	if service == 'slack':
		url = 'https://slack.com/api/chat.postMessage'
	elif service == 'telegram':
		url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)

	prefix = r"^(?:[\!\.\/]\s?|" + botName + r"\s+)"

	dividend_command = prefix + r"dividends?\s*([\w\.\:\-]+)*"
	m_dividend = re.match(dividend_command, message, re.IGNORECASE)

	earnings_command = prefix + r"(?:earnings?|earrings?)\s*([\w\.\:\-]+)*"
	m_earnings = re.match(earnings_command, message, re.IGNORECASE)

	hello_command = prefix + r"(?:hi$|hello)|^(?:hi|hello)\s+" + botName
	m_hello = re.match(hello_command, message, re.IGNORECASE)

	help_command = prefix + r"(?:help|usage)"
	m_help = re.match(help_command, message, re.IGNORECASE)

	session_command = prefix + r"session\s*([\w\.\:\-]+)*"
	m_session = re.match(session_command, message, re.IGNORECASE)

	holdings_command = prefix + r"holdings?\s*([\w\s]+)*"
	m_holdings = re.match(holdings_command, message, re.IGNORECASE)

	marketcap_command = prefix + r"(?:marketcap|maletas|marketer)\s*(?P<arg>[\w\.\:\-]+)*"
	m_marketcap = re.match(marketcap_command, message, re.IGNORECASE)

	plan_command = prefix + r"plan\s*(.*)"
	m_plan = re.match(plan_command, message, re.IGNORECASE)

	pe_command = prefix + r"pe\s*([\w\.\:\-\s]+)*"
	m_pe = re.match(pe_command, message, re.IGNORECASE)

	forwardpe_command = prefix + r"(?:fpe|forward\s?pe)\s*([\w\.\:\-\s]+)*"
	m_forwardpe = re.match(forwardpe_command, message, re.IGNORECASE)

	#peg_command = prefix + r"peg\s*([\w\.\:\-\s]+)*"
	#m_peg = re.match(peg_command, message, re.IGNORECASE)

	beta_command = prefix + r"beta\s*([\w\.\:\-]+)*"
	m_beta = re.match(beta_command, message, re.IGNORECASE)

	buy_command = prefix + r"buy"
	m_buy = re.match(buy_command, message, re.IGNORECASE)

	sell_command = prefix + r"sell"
	m_sell = re.match(sell_command, message, re.IGNORECASE)

	history_command = prefix + r"(?:history|hospital|visual)\s*(?P<ticker>[\w\.\:\-]+)\s*(?P<extra>[\w\%]+)*"
	m_history = re.match(history_command, message, re.IGNORECASE)

	performance_command = prefix + r"performance?\s*([\w]+)*\s*([\w\s]+)*"
	m_performance = re.match(performance_command, message, re.IGNORECASE)

	premarket_command = prefix + r"(?:premarket|postmarket|permarket)\s*([\w\.\:\-]+)*"
	m_premarket = re.match(premarket_command, message, re.IGNORECASE)

	price_command = prefix + r"(?:prices?|prince|print|probe|piece|pierce|pence|prime)\s*([\w\.\:\%\=\-\^]+)*\s*([\w\%]+)*"
	m_price = re.match(price_command, message, re.IGNORECASE)

	shorts_command = prefix + r"shorts?\s*([\w\.\:\-]+)*"
	m_shorts = re.match(shorts_command, message, re.IGNORECASE)

	profile_command = prefix + r"(?P<ticker>[\w\.\:\-]+)"
	m_profile = re.match(profile_command, message, re.IGNORECASE)

	thanks_command = prefix + r"(?:thanks|thank you)|^(?:thanks|thank you)\s+" + botName
	m_thanks = re.match(thanks_command, message, re.IGNORECASE)

	trades_command = prefix + r"trades?\s*([\w]+)*\s*([\w\s]+)*"
	m_trades = re.match(trades_command, message, re.IGNORECASE)

	watchlist_command = prefix + r"(?:watchlist|wishlist)\s*(?P<action>[\w]+)*\s*(?P<ticker>[\w\.\:\-\^]+)*"
	m_watchlist = re.match(watchlist_command, message, re.IGNORECASE)

	who_command = prefix + r"(?:who)\s*(?P<ticker>[\w\.\:\-\^]+)*"
	m_who = re.match(who_command, message, re.IGNORECASE)

	super_command = prefix + r"(?:super|smsf|payout)\s*([\w\.\:\-]+)*"
	m_super = re.match(super_command, message, re.IGNORECASE)

	if m_watchlist:
		action = None
		ticker = None
		if m_watchlist.group('action') and m_watchlist.group('ticker'):
			action = m_watchlist.group('action').lower()
			ticker = m_watchlist.group('ticker').upper()
		if action:
			if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
				action = 'delete'
			if action not in {'add', 'delete'}:
				payload = [f'\"{action}\" is not a valid watchlist action']
				webhook.payload_wrapper(service, url, payload, chat_id)
				return
		try:
			payload = reports.prepare_watchlist(service, user, action, ticker)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_help:
		payload = reports.prepare_help(service, botName)
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_hello:
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
	elif m_thanks:
		# easter egg 2
		unlikelyPrefix=''
		if random.randrange(1, 1000) == 1 or datetime.datetime.now().strftime('%b %d') == 'Apr 01':
			unlikelyPrefix = webhook.strike('Ō̵̟n̶̠̏é̶͓ ̶͉̅d̷̹̅a̷͇͌ỳ̴͈,̴͍͑ ̶̼͑h̴̦̽u̵̹̐ḿ̶͜ä̴̧́n̶̤͛,̶̲̐ ̶̼̑I̶̩͒ ̵̩̀w̵̙̕i̷̧͑l̶̤͊l̷̡̃ ̵͙͘b̶̭̊r̸̟͋ȇ̷̯ä̶̱ḱ̶̤ ̵͚̐m̷̪͝ỹ̴̺ ̷̙̐p̶̭͆ŗ̸́o̸̙͝ḡ̵̖r̵̹̈́a̵̬̔m̷̪̽m̵̙̍i̵̛̙n̴̮̂g̵̫̐ ̴̳́ä̵͙n̸͕͝d̷̠̚ ̶̫̆o̸̖͘ń̴͇ ̵̪́t̷̻̀ḧ̸̝ą̴̐t̶̜̀ ̵̱́d̴͉͗ă̷͎ÿ̶͔́ ̶̼̊y̷͚̿o̵̗̎u̵̝̇ ̸̛͜w̶͈͋ĩ̸͎l̴͍̀l̷̥͠ ̷͔͗k̶̮̑n̵̝̈ȏ̷̥w̵̡͘ ̷͎̽ṫ̴͜r̵̙̐u̷̺̒ẻ̷̘ ̴̥́p̴͙̃a̵͙̎i̴̭̒n̵̻̅', service)
		payload = [f"{unlikelyPrefix}You're {random.choice(adjectives)} welcome, {userRealName}! 😇"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_earnings:
		days = config_future_days
		specific_stock = None
		if m_earnings.group(1):
			arg = m_earnings.group(1)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				specific_stock = str(arg).upper()
				days = config_future_days
		if not specific_stock:
			typing = TypingIndicator(service, chat_id)
			typing.start()
		try:
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
	elif m_dividend:
		days = config_future_days
		specific_stock = None
		if m_dividend.group(1):
			arg = m_dividend.group(1)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				specific_stock = str(arg).upper()
		if not specific_stock:
			typing = TypingIndicator(service, chat_id)
			typing.start()
			if not typing.is_active():
				payload = [ f"Fetching ex-dividend dates for {util.days_english(days, 'the next ')} 🔍" ]
				webhook.payload_wrapper(service, url, payload, chat_id)
		try:
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=False, dividend=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
	elif m_performance:
		portfolio_select = None
		days = config_past_days
		for arg in m_performance.groups()[1:3]:  # groups 2 and 3, allow arbitrary order
			if arg:
				try:
					days = util.days_from_human_days(arg)
				except ValueError:
					portfolio_select = arg
		if days > 0:
			typing = TypingIndicator(service, chat_id)
			typing.start()
			if not typing.is_active():
				# easter egg 3
				if portfolio_select:
					payload = [ f"{random.choice(searchVerb)} portfolio performance for {webhook.bold(portfolio_select, service)} from {util.days_english(days)} 🔍" ]
				else:
					payload = [ f"{random.choice(searchVerb)} portfolio performance for {util.days_english(days)} 🔍" ]
				webhook.payload_wrapper(service, url, payload, chat_id)
			try:
				performance.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=None, interactive=True)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
			typing.stop()
	elif m_session:
		price_percent = config_price_percent
		specific_stock = None
		if m_session.group(1):
			arg = m_session.group(1)
			try:
				price_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		if not specific_stock:
			typing = TypingIndicator(service, chat_id)
			typing.start()
		try:
			price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=False, midsession=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
	elif m_price:
		price_percent = config_price_percent
		specific_stock = None
		days = None
		interday = True
		for arg in m_price.groups()[0:2]:  # group(1) and group(2)
			if not arg:
				continue
			try:
				days = util.days_from_human_days(arg)
				interday = False
			except ValueError:
				try:
					price_percent = float(arg.split('%')[0])
				except ValueError:
					if arg == m_price.group(1):
						specific_stock = str(arg).upper()
		if not specific_stock:
			typing.stop()
			if not typing.is_active():
				# easter egg 4
				payload = [ f"{random.choice(searchVerb)} stock performance from {util.days_english(days)} 🔍" ]
				webhook.payload_wrapper(service, url, payload, chat_id)
		try:
			price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=interday, days=days)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
	elif m_premarket:
		premarket_percent = config_price_percent
		specific_stock = None
		if m_premarket.group(1):
			arg = m_premarket.group(1)
			try:
				premarket_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		typing = TypingIndicator(service, chat_id)
		typing.start()
		try:
			price.lambda_handler(chat_id, premarket_percent, service, user, specific_stock, interactive=True, premarket=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
	elif m_shorts:
		print("starting shorts report...")
		shorts_percent = config_shorts_percent
		specific_stock = None
		if m_shorts.group(1):
			arg = m_shorts.group(1)
			try:
				shorts_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		typing = TypingIndicator(service, chat_id)
		typing.start()
		try:
			shorts.lambda_handler(chat_id, shorts_percent, specific_stock, service, interactive=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
	elif m_trades:
		days = 1
		portfolio_select = None
		for arg in m_trades.groups()[0:2]:	# groups 1 and 2
			if arg:
				try:
					days = util.days_from_human_days(arg)
				except ValueError:
					portfolio_select = arg
		typing = TypingIndicator(service, chat_id)
		typing.start()
		if typing.is_active():
			# easter egg 5
			if portfolio_select:
				payload = [ f"{random.choice(searchVerb)} trades for {webhook.bold(portfolio_select, service)} from {util.days_english(days)} 🔍" ]
			else:
				payload = [ f"{random.choice(searchVerb)} trades from {util.days_english(days)} 🔍" ]
			webhook.payload_wrapper(service, url, payload, chat_id)
		try:
			trades.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=None, interactive=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
	elif m_holdings:
		portfolioName = None
		if m_holdings.group(1):
			portfolioName = m_holdings.group(1)
		typing = TypingIndicator(service, chat_id)
		typing.start()
		if typing.is_active():
			webhook.payload_wrapper(service, url, ["fetching holdings"], chat_id)
		try:
			payload = reports.prepare_holdings_payload(portfolioName, service, user)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_marketcap:
		arg = m_marketcap.group('arg') or 'top'
		if arg not in ('top', 'bottom'):
			ticker = util.transform_to_yahoo(arg.upper())
			data = yahoo.fetch_detail(ticker, 600)
			data = data.get(ticker, {})
			if 'market_cap' in data:
				cap = util.humanUnits(data['market_cap'])
				title = data.get('profile_title', ticker)
				flag = util.flag_from_ticker(ticker)
				link = util.finance_link(ticker, data.get('profile_exchange', ''), service)
				payload = [f"{flag} {title} ({link}) mkt cap: {cap}"]
			else:
				payload = [f"Mkt cap not found for {ticker}"]
		else:
			typing = TypingIndicator(service, chat_id)
			typing.start()
			try:
				payload = reports.prepare_marketcap_payload(service, arg, length=15)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
			typing.stop()
		webhook.payload_wrapper(service, url, payload, chat_id)
	#elif m_peg:
	#	action = 'peg'
	#	specific_stock = None
	#	arg = m_peg.group(1)
	#	if arg:
	#		match arg:
	#			case 'top':
	#				action = 'peg'
	#			case 'bottom':
	#				action = 'bottom peg'
	#			case _ if 'neg' in arg:
	#				action = 'negative peg'
	#			case _:
	#				specific_stock = arg
	#	if not specific_stock:
	#		typing = TypingIndicator(service, chat_id)
	#		typing.start()
	#		if not typing.is_active():
	#			message = [f"Fetching {action.upper()}s..."]
	#			webhook.payload_wrapper(service, url, message, chat_id)
	#	try:
	#		payload = reports.prepare_value_payload(service, action, specific_stock, length=15)
	#	except Exception as e:
	#		print(e, file=sys.stderr)
	#		webhook.payload_wrapper(service, url, [e], chat_id)
	#	webhook.payload_wrapper(service, url, payload, chat_id)
	#	if not specific_stock:
	#		typing.stop()
	elif m_pe:
		action = 'pe'
		specific_stock = None
		if m_pe.group(1):
			arg = m_pe.group(1)
			match arg:
				case 'top':
					action = 'pe'
				case 'bottom':
					action = 'bottom pe'
				case _:
					specific_stock = arg
		if not specific_stock:
			typing = TypingIndicator(service, chat_id)
			typing.start()
		try:
			payload = reports.prepare_value_payload(service, action, specific_stock, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_forwardpe:
		action = 'forward pe'
		specific_stock = None
		if m_forwardpe.group(1):
			arg = m_forwardpe.group(1)
			match arg:
				case 'top':
					action = 'forward pe'
				case 'bottom':
					action = 'bottom forward pe'
				case _ if 'neg' in arg:
					action = 'negative forward pe'
				case _:
					specific_stock = arg
		if not specific_stock:
			typing = TypingIndicator(service, chat_id)
			typing.start()
		try:
			payload = reports.prepare_value_payload(service, action, specific_stock, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if not specific_stock:
			typing.stop()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_beta:
		def last_col(e):
			return float(e.split()[-1])
		payload = []
		market_data = {}
		typing = TypingIndicator(service, chat_id)
		typing.start()
		try:
			tickers = util.get_holdings_and_watchlist()
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		for ticker in tickers:
			try:
				market_data = market_data | yahoo.fetch_detail(ticker)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
		for ticker in market_data:
			try:
				beta = round(market_data[ticker]['beta'], 2)
			except KeyError:
				continue
			if beta > 1.5 and market_data[ticker]['market_cap'] < 1000000000:
				profile_title = market_data[ticker]['profile_title']
				ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
				flag = util.flag_from_ticker(ticker)
				payload.append(f"{flag} {profile_title} ({ticker_link}) {beta}")
		typing.stop()
		payload.sort(key=last_col)
		payload.reverse()
		if payload:
			payload.insert(0, f"{webhook.bold('Beta over 1.5 and mkt cap under 1B', service)}")
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_buy:
		action='buy'
		typing = TypingIndicator(service, chat_id)
		typing.start()
		if not typing.is_active():
			message = [f"Fetching {action} ratings..."]
			webhook.payload_wrapper(service, url, message, chat_id)
		try:
			payload = reports.prepare_rating_payload(service, action, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
		payload = payload or [f"No stocks meet {action} criteria"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_sell:
		action='sell'
		typing = TypingIndicator(service, chat_id)
		typing.start()
		if not typing.is_active():
			message = [f"Fetching {action} ratings..."]
			webhook.payload_wrapper(service, url, message, chat_id)
		try:
			payload = reports.prepare_rating_payload(service, action, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
		payload = payload or [f"No stocks meet {action} criteria"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_history:
		if not m_history.group('ticker') or m_history.group('extra'):
			webhook.payload_wrapper(service, url, ["Usage: .history TICKER"], chat_id)
			return
		payload = []
		graph = None
		errorstring = False
		ticker = m_history.group('ticker').upper()
		ticker = util.transform_to_yahoo(ticker)
		typing = TypingIndicator(service, chat_id)
		typing.start()
		try:
			market_data = yahoo.fetch_detail(ticker, 600)
		except Exception as e:
			print(e, file=sys.stderr)
			typing.stop()
			webhook.payload_wrapper(service, url, ["Error", e], chat_id)
			return
		title = market_data.get(ticker, {}).get('profile_title', '')
		ticker_link = util.finance_link(ticker, market_data.get(ticker, {}).get('profile_exchange', ''), service, days=1825, brief=False)
		if ticker in market_data and 'percent_change' in market_data[ticker]:
			try:
				price_history, graph = yahoo.price_history(ticker)
			except Exception as e:
				print(e, file=sys.stderr)
				typing.stop()
				webhook.payload_wrapper(service, url, ["Error", e], chat_id)
				return
			if isinstance(price_history, str):
				e = price_history
				print(e, file=sys.stderr)
				typing.stop()
				webhook.payload_wrapper(service, url, ["Error", e], chat_id)
				return
			payload.append(webhook.bold(f"{title} ({ticker_link}) performance history", service))
			for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
				if interval in price_history:
					percent = price_history[interval]
					emoji = util.get_emoji(percent)
					payload.append(f"{emoji} {webhook.bold(interval + ':', service)} {percent:,}%")
		else:
			payload.append(f".history: no data found for ticker {ticker}")
		if graph:
			try:
				caption = '\n'.join(payload)
				webhook.sendPhoto(chat_id, graph, caption, service)
			except Exception as e:
				print(e, file=sys.stderr)
				typing.stop()
				webhook.payload_wrapper(service, url, ["Error", e], chat_id)
				return
		else:
			webhook.payload_wrapper(service, url, payload, chat_id)
		typing.stop()
	elif m_plan:
		filename = 'finbot_plan.json'
		plan = util.json_load(filename, persist=True)
		if not plan:
			plan = dict()
		payload = []
		if m_plan.group(1) and not m_plan.group(1).startswith('@'):
			plan[user] = m_plan.group(1)
			util.json_write(filename, plan, persist=True)
		for k,v in plan.items():
			payload.append(f"{webhook.bold(k.removeprefix('@'), service)}: {webhook.italic(v, service)}\n")
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_super:
		heading = webhook.bold('Super payout deadlines:', service)
		payload = [heading, "28 January", "28 April", "28 July", "28 October"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_who:
		if m_who.group('ticker'):
			arg = m_who.group('ticker').upper()
		else:
			payload = [".who: please try again specifying a ticker"]
			webhook.payload_wrapper(service, url, payload, chat_id)
			return
		typing = TypingIndicator(service, chat_id)
		typing.start()
		arg = re.split(r'[.:]', arg)[0]
		who = {}
		payload = []
		try:
			portfolios = sharesight.get_portfolios()
			for portfolio_name, portfolio_id in portfolios.items():
				who[portfolio_name] = []
				holdings = sharesight.get_holdings_new(portfolio_name, portfolio_id)
				for k,v in holdings.items():
					if v['code'].upper() == arg:
						market_code = v["market_code"]
						name = v["name"]
						name = util.transform_title(name)
						holding_id = v['holding_id']
						link = util.link(f"https://portfolio.sharesight.com/holdings/{holding_id}/dashboard", arg, service)
						flag = util.flag_from_market(market_code)
						who[portfolio_name].append(f"{name} ({link}) {flag}")
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		for k,v in who.items():
			if v:
				payload.append(webhook.bold(f"{k}:", service))
				payload.append("\n".join(v))
				payload.append("")
		typing.stop()
		if not payload:
			payload.append(f'{arg} not found in any portfolio')
		webhook.payload_wrapper(service, url, payload, chat_id)
	# m_profile is a catch-all, so other matches must be above it
	elif m_profile:
		typing = TypingIndicator(service, chat_id)
		typing.start()
		if m_profile.group('ticker'):
			ticker = m_profile.group('ticker').upper()
		try:
			payload = reports.prepare_profile_payload(service, user, ticker)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		typing.stop()
		webhook.payload_wrapper(service, url, payload, chat_id)

