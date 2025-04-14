import re, random
import datetime
import sys
import threading
from lib.config import *
from lib import util
from lib import webhook
from lib import yahoo
from lib import reports
import cal
import performance
import price
import shorts
import trades

def typing_worker(stop_event, service, chat_id, max_loops=3, action='typing'):
	loop_count = 0
	while not stop_event.is_set() and loop_count < max_loops:
		webhook.pleaseHold(action, service, chat_id)
		loop_count += 1
		if stop_event.wait(7):
			break

def typing_start(service, chat_id):
	if service == 'telegram':
		stop_event = threading.Event()
		typing_thread = threading.Thread(target=typing_worker, args=(stop_event,service,chat_id))
		typing_thread.start()
		return stop_event

def process_request(service, chat_id, user, message, botName, userRealName, message_id):
	if service == 'slack':
		url = 'https://slack.com/api/chat.postMessage'
	elif service == 'telegram':
		url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)

	dividend_command = r"^([\!\.]\s?|" + botName + r"\s+)dividends?\s*([\w\.\:\-]+)*"
	m_dividend = re.match(dividend_command, message, re.IGNORECASE)

	earnings_command = r"^([\!\.]\s?|" + botName + r"\s+)(earnings?|earrings?)\s*([\w\.\:\-]+)*"
	m_earnings = re.match(earnings_command, message, re.IGNORECASE)

	hello_command = r"^([\!\.]\s?|" + botName + r"\s+)(hi$|hello)|^(hi|hello)\s+" + botName
	m_hello = re.match(hello_command, message, re.IGNORECASE)

	help_command = r"^([\!\.]\s?|" + botName + r"\s+)(help|usage)"
	m_help = re.match(help_command, message, re.IGNORECASE)

	session_command = r"^([\!\.]\s?|^" + botName + r"\s+)session\s*([\w\.\:\-]+)*"
	m_session = re.match(session_command, message, re.IGNORECASE)

	holdings_command = r"^([\!\.]\s?|^" + botName + r"\s+)holdings?\s*([\w\s]+)*"
	m_holdings = re.match(holdings_command, message, re.IGNORECASE)

	marketcap_command = r"^([\!\.]\s?|^" + botName + r"\s+)(marketcap|maletas|marketer)\s*([\w\.\:\-]+)*"
	m_marketcap = re.match(marketcap_command, message, re.IGNORECASE)

	plan_command = r"^([\!\.]\s?|^" + botName + r"\s+)plan\s*(.*)"
	m_plan = re.match(plan_command, message, re.IGNORECASE)

	pe_command = r"^([\!\.]\s?|^" + botName + r"\s+)pe\s*([\w\.\:\-\s]+)*"
	m_pe = re.match(pe_command, message, re.IGNORECASE)

	forwardpe_command = r"^([\!\.]\s?|^" + botName + r"\s+)(fpe|forward\s?pe)\s*([\w\.\:\-\s]+)*"
	m_forwardpe = re.match(forwardpe_command, message, re.IGNORECASE)

	peg_command = r"^([\!\.]\s?|^" + botName + r"\s+)peg\s*([\w\.\:\-\s]+)*"
	m_peg = re.match(peg_command, message, re.IGNORECASE)

	beta_command = r"^([\!\.]\s?|^" + botName + r"\s+)beta\s*([\w\.\:\-]+)*"
	m_beta = re.match(beta_command, message, re.IGNORECASE)

	buy_command = r"^([\!\.]\s?|^" + botName + r"\s+)buy"
	m_buy = re.match(buy_command, message, re.IGNORECASE)

	sell_command = r"^([\!\.]\s?|^" + botName + r"\s+)sell"
	m_sell = re.match(sell_command, message, re.IGNORECASE)

	history_command = r"^([\!\.]\s?|^" + botName + r"\s+)(history|hospital|visual)\s*([\w\.\:\-]+)*"
	m_history = re.match(history_command, message, re.IGNORECASE)

	performance_command = r"^([\!\.]\s?|^" + botName + r"\s+)performance?\s*([\w]+)*\s*([\w\s]+)*"
	m_performance = re.match(performance_command, message, re.IGNORECASE)

	premarket_command = r"^([\!\.]\s?|^" + botName + r"\s+)(premarket|postmarket|permarket)\s*([\w\.\:\-]+)*"
	m_premarket = re.match(premarket_command, message, re.IGNORECASE)

	price_command = r"^([\!\.]\s?|^" + botName + r"\s+)(prices?|prince|print|probe|piece|pierce|pence|prime)\s*([\w\.\:\%\=\-\^]+)*\s*([\w\%]+)*"
	m_price = re.match(price_command, message, re.IGNORECASE)

	shorts_command = r"^([\!\.]\s?|^" + botName + r"\s+)shorts?\s*([\w\.\:\-]+)*"
	m_shorts = re.match(shorts_command, message, re.IGNORECASE)

	stockfinancial_command = r"^([\!\.]\s?|^" + botName + r"\s+)([\w\.\:\-]+)"
	m_stockfinancial = re.match(stockfinancial_command, message, re.IGNORECASE)

	profile_command = r"^([\!\.]\s?|^" + botName + r"\s+)(about|bio|profile|professor|proudly|proteja|properties|possible)\s*([\w\.\:\-]+)*"
	m_profile = re.match(profile_command, message, re.IGNORECASE)

	thanks_command = r"^([\!\.]\s?|^" + botName + r"\s+)(thanks|thank you)|^(thanks|thank you)\s+" + botName
	m_thanks = re.match(thanks_command, message, re.IGNORECASE)

	trades_command = r"^([\!\.]\s?|^" + botName + r"\s+)trades?\s*([\w]+)*\s*([\w\s]+)*"
	m_trades = re.match(trades_command, message, re.IGNORECASE)

	watchlist_command = r"^([\!\.]\s?|^" + botName + r"\s+)(watchlist|wishlist)\s*([\w]+)*\s*([\w\.\:\-\^]+)*"
	m_watchlist = re.match(watchlist_command, message, re.IGNORECASE)

	super_command = r"^([\!\.]\s?|" + botName + r"\s+)(super|smsf|payout)\s*([\w\.\:\-]+)*"
	m_super = re.match(super_command, message, re.IGNORECASE)

	if m_watchlist:
		action = None
		ticker = None
		if m_watchlist.group(3) and m_watchlist.group(4):
			action = m_watchlist.group(3).lower()
			ticker = m_watchlist.group(4).upper()
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
		if m_earnings.group(3):
			arg = m_earnings.group(3)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				specific_stock = str(arg).upper()
				days = config_future_days
			if service == 'telegram' and not specific_stock:
				typing_stop = typing_start(service, chat_id)
		try:
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
	elif m_dividend:
		days = config_future_days
		specific_stock = None
		if m_dividend.group(2):
			arg = m_dividend.group(2)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				specific_stock = str(arg).upper()
		if not specific_stock:
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			else:
				payload = [ f"Fetching ex-dividend dates for {util.days_english(days, 'the next ')} 🔍" ]
				webhook.payload_wrapper(service, url, payload, chat_id)
		try:
			cal.lambda_handler(chat_id, days, service, specific_stock, message_id=None, interactive=True, earnings=False, dividend=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
	elif m_performance:
		portfolio_select = None
		days = config_past_days
		if m_performance.group(2):
			arg = m_performance.group(2)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				portfolio_select = arg
		if m_performance.group(3):
			arg = m_performance.group(3)
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				portfolio_select = arg
		if days > 0:
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			else:
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
			if service == 'telegram':
				typing_stop.set()
	elif m_session:
		price_percent = config_price_percent
		specific_stock = None
		if m_session.group(2):
			arg = m_session.group(2)
			try:
				price_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		if service == 'telegram' and not specific_stock:
			typing_stop = typing_start(service, chat_id)
		try:
			price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=False, midsession=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
	elif m_price:
		price_percent = config_price_percent
		specific_stock = None
		days = None
		interday = True
		if m_price.group(3):
			arg = m_price.group(3)
			try:
				days = util.days_from_human_days(arg)
				interday = False
			except ValueError:
				try:
					price_percent = float(arg.split('%')[0])
				except ValueError:
					specific_stock = str(arg).upper()
		if m_price.group(4):
			arg = m_price.group(4)
			try:
				days = util.days_from_human_days(arg)
				interday = False
			except ValueError:
			   try:
				   price_percent = int(arg.split('%')[0])
			   except ValueError:
				   pass
		if days and days > 0 and not specific_stock:
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			else:
				# easter egg 4
				payload = [ f"{random.choice(searchVerb)} stock performance from {util.days_english(days)} 🔍" ]
				webhook.payload_wrapper(service, url, payload, chat_id)
		try:
			price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=interday, days=days)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram' and days and days > 0 and not specific_stock:
			typing_stop.set()
	elif m_premarket:
		premarket_percent = config_price_percent
		specific_stock = None
		if m_premarket.group(3):
			arg = m_premarket.group(3)
			try:
				premarket_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		try:
			price.lambda_handler(chat_id, premarket_percent, service, user, specific_stock, interactive=True, premarket=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
	elif m_shorts:
		print("starting shorts report...")
		shorts_percent = config_shorts_percent
		specific_stock = None
		if m_shorts.group(2):
			arg = m_shorts.group(2)
			try:
				shorts_percent = int(arg.split('%')[0])
			except ValueError:
				specific_stock = str(arg).upper()
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		try:
			shorts.lambda_handler(chat_id, shorts_percent, specific_stock, service, interactive=True)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
	elif m_trades:
		days = 1
		portfolio_select = None
		for arg in m_trades.groups()[1:3]:  # groups 2 and 3
			if arg:
				try:
					days = util.days_from_human_days(arg)
				except ValueError:
					portfolio_select = arg
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		else:
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
		if service == 'telegram':
			typing_stop.set()
	elif m_holdings:
		portfolioName = None
		if m_holdings.group(2):
			portfolioName = m_holdings.group(2)
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		else:
			webhook.payload_wrapper(service, url, ["fetching holdings"], chat_id)
		try:
			payload = reports.prepare_holdings_payload(portfolioName, service, user)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_marketcap:
		if m_marketcap.group(3) and m_marketcap.group(3) not in ('top', 'bottom'):
			ticker = m_marketcap.group(3).upper()
			ticker = util.transform_to_yahoo(ticker)
			market_data = yahoo.fetch_detail(ticker, 600)
			if ticker in market_data and 'market_cap' in market_data[ticker]:
				market_cap = market_data[ticker]['market_cap']
				market_cap_readable = util.humanUnits(market_cap)
				title = market_data[ticker]['profile_title']
				flag = util.flag_from_ticker(ticker)
				link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
				payload = [f"{flag} {title} ({link}) mkt cap: {market_cap_readable}"]
			else:
				payload = [f"Mkt cap not found for {ticker}"]
		else:
			action = 'top'
			if m_marketcap.group(3):
				action = m_marketcap.group(3)
			if service == 'telegram' and not specific_stock:
				typing_stop = typing_start(service, chat_id)
			try:
				payload = reports.prepare_marketcap_payload(service, action, length=15)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram' and not specific_stock:
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_peg:
		action = 'peg'
		ticker_select = None
		if m_peg.group(2):
			arg = m_peg.group(2)
			if arg == 'top':
				action = 'peg'
			elif arg == 'bottom':
				action = 'bottom peg'
			elif 'neg' in arg:
				action = 'negative peg'
			else:
				ticker_select = arg
		if not ticker_select:
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			else:
				message = [f"Fetching {action.upper()}s..."]
				webhook.payload_wrapper(service, url, message, chat_id)
		try:
			payload = reports.prepare_value_payload(service, action, ticker_select, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		webhook.payload_wrapper(service, url, payload, chat_id)
		if service == 'telegram' and not ticker_select:
			typing_stop.set()
	elif m_pe:
		action = 'pe'
		ticker_select = None
		if m_pe.group(2):
			arg = m_pe.group(2)
			if arg == 'top':
				action = 'pe'
			elif arg == 'bottom':
				action = 'bottom pe'
			else:
				ticker_select = arg
		if service == 'telegram' and not ticker_select:
			typing_stop = typing_start(service, chat_id)
		try:
			payload = reports.prepare_value_payload(service, action, ticker_select, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram' and not ticker_select:
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_forwardpe:
		action = 'forward pe'
		ticker_select = None
		if m_forwardpe.group(3):
			arg = m_forwardpe.group(3)
			if arg == 'top':
				action = 'forward pe'
			elif arg == 'bottom':
				action = 'bottom forward pe'
			elif 'neg' in arg:
				action = 'negative forward pe'
			else:
				ticker_select = arg
		if service == 'telegram' and not ticker_select:
			typing_stop = typing_start(service, chat_id)
		try:
			payload = reports.prepare_value_payload(service, action, ticker_select, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram' and not ticker_select:
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_beta:
		def last_col(e):
			return float(e.split()[-1])
		payload = []
		market_data = {}
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
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
		if service == 'telegram':
			typing_stop.set()
		payload.sort(key=last_col)
		payload.reverse()
		if payload:
			payload.insert(0, f"{webhook.bold('Beta over 1.5 and mkt cap under 1B', service)}")
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_buy:
		action='buy'
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		else:
			message = [f"Fetching {action} ratings..."]
			webhook.payload_wrapper(service, url, message, chat_id)
		try:
			payload = reports.prepare_rating_payload(service, action, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
		if payload:
			webhook.payload_wrapper(service, url, payload, chat_id)
		else:
			payload = [f"No stocks meet {action} criteria"]
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_sell:
		action='sell'
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		else:
			message = [f"Fetching {action} ratings..."]
			webhook.payload_wrapper(service, url, message, chat_id)
		try:
			payload = reports.prepare_rating_payload(service, action, length=15)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
		if payload:
			webhook.payload_wrapper(service, url, payload, chat_id)
		else:
			payload = [f"No stocks meet {action} criteria"]
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_history:
		payload = []
		graph = None
		errorstring = False
		if m_history.group(3):
			ticker = m_history.group(3).upper()
			ticker = util.transform_to_yahoo(ticker)
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			try:
				market_data = yahoo.fetch_detail(ticker, 600)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
			title = market_data[ticker]['profile_title']
			ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service, days=1825, brief=False)
			if ticker in market_data and 'percent_change' in market_data[ticker]:
				try:
					price_history, graph = yahoo.price_history(ticker)
				except Exception as e:
					print(e, file=sys.stderr)
					webhook.payload_wrapper(service, url, [e], chat_id)
				if isinstance(price_history, str):
					errorstring=price_history
					print(errorstring, file=sys.stderr)
					payload = [errorstring]
				else:
					payload.append(webhook.bold(f"{title} ({ticker_link}) performance history", service))
					for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
						if interval in price_history:
							percent = price_history[interval]
							emoji = util.get_emoji(percent)
							payload.append(f"{emoji} {webhook.bold(interval + ':', service)} {percent}%")
			else:
				payload = [f".history: Data not found for {ticker}"]
		else:
			payload = [".history: please try again specifying a ticker"]
		caption = '\n'.join(payload)
		if graph:
			try:
				webhook.sendPhoto(chat_id, graph, caption, service)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
			if service == 'telegram':
				typing_stop.set()
		else:
			webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_plan:
		filename = 'finbot_plan.json'
		plan = util.json_load(filename, persist=True)
		if not plan:
			plan = dict()
		payload = []
		if m_plan.group(2) and not m_plan.group(2).startswith('@'):
			plan[user] = m_plan.group(2)
			util.json_write(filename, plan, persist=True)
		for k,v in plan.items():
			payload.append(f"{webhook.bold(k.removeprefix('@'), service)}: {webhook.italic(v, service)}\n")
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_super:
		heading = webhook.bold('Super payout deadlines:', service)
		payload = [heading, "28 January", "28 April", "28 July", "28 October"]
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_profile:
		if m_profile.group(3):
			ticker = m_profile.group(3).upper()
			ticker = util.transform_to_yahoo(ticker)
			if service == 'telegram':
				typing_stop = typing_start(service, chat_id)
			try:
				market_data = yahoo.fetch_detail(ticker, 600)
			except Exception as e:
				print(e, file=sys.stderr)
				webhook.payload_wrapper(service, url, [e], chat_id)
			if ticker in market_data:
				try:
					payload = reports.prepare_bio_payload(service, user, ticker, market_data)
				except Exception as e:
					print(e, file=sys.stderr)
					webhook.payload_wrapper(service, url, [e], chat_id)
			else:
				payload = [f"{ticker} not found"]
		else:
			payload = [".profile: please try again specifying a ticker"]
		if service == 'telegram':
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
	elif m_stockfinancial:
		if service == 'telegram':
			typing_stop = typing_start(service, chat_id)
		if m_stockfinancial.group(2):
			ticker = m_stockfinancial.group(2).upper()
		try:
			payload = reports.prepare_stockfinancial_payload(service, user, ticker)
		except Exception as e:
			print(e, file=sys.stderr)
			webhook.payload_wrapper(service, url, [e], chat_id)
		if service == 'telegram':
			typing_stop.set()
		webhook.payload_wrapper(service, url, payload, chat_id)
