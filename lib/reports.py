from itertools import pairwise
import hashlib, re
import datetime
import sys
from lib import config
from lib import cache
from lib import watchlist
from lib import sharesight
from lib import util
from lib import webhook
from lib import yahoo
from lib import simplywallst
from itertools import groupby

def last_col(line):
	"""Sort key: the number a report line ends with; a line without one sorts first."""
	try:
		return float(line.split()[-1])
	except ValueError:
		return float('-inf')

def holding_line(holding, service, text=None):
	"""'🇦🇺 Title (CODE)' for a Sharesight holding, CODE (or `text`) linking to the holding on Sharesight."""
	link = util.link(f"https://portfolio.sharesight.com/holdings/{holding['holding_id']}/dashboard", holding['code'] if text is None else text, service)
	return f"{util.flag_from_market(holding['market_code'])} {util.transform_title(holding['name'])} ({link})"

def doDelta(inputList):
	deltaString = ''
	inputListFixed = inputList.copy()
	# replace any NoneType to allow delta calculation
	for idx, absolute in enumerate(inputList):
		if absolute is None:
			if idx == 0:
				# get the next value that's not None
				inputListFixed[idx] = next((x for x in inputList if x is not None), 0)
			else:
				# get the previous value
				inputListFixed[idx] = inputListFixed[idx-1]
	deltaList = [y-x for (x,y) in pairwise(inputListFixed)]
	for idx, delta in enumerate(deltaList):
		absolute = inputList[idx+1]
		if absolute is None or (idx == 0 and inputList[0] is None):
			deltaString = deltaString + '❌'
		elif delta < 0 and absolute < 0:
			deltaString = deltaString + '🔻'
		elif delta < 0 and absolute >= 0:
			deltaString = deltaString + '🔽'
		elif delta > 0 and absolute < 0:
			deltaString = deltaString + '🔺'
		elif delta > 0 and absolute >= 0:
			deltaString = deltaString + '🔼'
		else:
			deltaString = deltaString + '▪️'
	# fallback if input has missing elements
	missingfromstart = 3 - len(deltaString) # desired length hard coded
	deltaString = ("❌" * missingfromstart) + deltaString
	return deltaString

def prepare_watchlist(service, user, action=None, ticker=None):
	"""The .watchlist reply: the companies watched, or one line on adding ('add') or removing ('delete') a ticker."""
	if action:
		return [watchlist_change(service, user, action, util.transform_to_yahoo(ticker))]
	watched = watchlist.tickers()
	market_data = yahoo.fetch(watched) if watched else {}
	lines = sorted((f"{util.flag_from_ticker(t)} {quote['profile_title']} ({util.finance_link(t, quote.get('profile_exchange'), service)})"
		for t, quote in market_data.items()), key=lambda line: re.findall('[A-Z].*', line)) # by name, the flag aside
	if not lines:
		return ['Watchlist is empty. Try ".watchlist add SYMBOL" to create it']
	return [f"Hi {user}, I'm currently tracking:"] + lines

def watchlist_change(service, user, action, asked):
	"""The reply to adding or removing `asked` (a Yahoo ticker)."""
	def described(ticker, quote): # "Full Name (TICKER)", bold
		quote = quote or {}
		link = util.finance_link(ticker, quote.get('profile_exchange') or ticker, service)
		return webhook.bold(f"{quote['profile_title']} ({link})" if quote.get('profile_title') else link, service)
	if action == 'delete':
		if asked not in watchlist.tickers():
			return f"Beep Boop. I could not find {webhook.bold(asked, service)} to remove it"
		quote = yahoo.fetch([asked]).get(asked)
		watchlist.remove(asked)
		return f"Ok {user}, I deleted {described(asked, quote)}"
	found, quote = watchlist.find(asked)
	if not quote:
		return f"Beep Boop. I could not find {webhook.bold(asked, service)} to add it"
	added = watchlist.add(found)
	if found != asked:
		done = "so I added" if added else "and I'm already tracking"
		return f"Beep Boop. I could not find {webhook.bold(asked, service)} {done} {described(found, quote)}"
	return f"Ok {user}, I added {described(found, quote)}" if added else f"{user}, I'm already tracking {described(found, quote)}"

def prepare_compare(service, args):
	"""Compare 2-6 tickers as rebased % change. A trailing time period (3m/1y/90d/ytd) is optional;
	without one, the span is the earliest date covered by every ticker. Returns (caption lines, image, tickers, period days)."""
	import pandas as pd
	usage = ['Usage: .compare SYMBOL SYMBOL [SYMBOL...up to 6] [period|max]  (default: 10 years)']
	period_days = None
	full_history = False
	args = list(args)
	if args:
		if args[-1].lower() in ('max', 'all'):
			full_history = True
			args.pop()
		else:
			try:
				period_days = util.days_from_human_days(args[-1])
				args.pop()
			except ValueError:
				pass
	tickers = list(dict.fromkeys(util.transform_to_yahoo(a.upper()) for a in args)) # de-duplicated, order kept
	if not 2 <= len(tickers) <= 6:
		return usage, None, tickers, period_days
	spec = period_days or ('max' if full_history else 'default')
	cache_key = hashlib.sha1(f"{service}|{','.join(tickers)}|{spec}".encode()).hexdigest()[:16]
	image_cache_file, caption_cache_file = f"finbot_compare_{cache_key}.png", f"finbot_compare_{cache_key}.json"
	if config.prefs.cache:
		cached_image = cache.read_bytes(image_cache_file)
		cached_caption = cache.read(caption_cache_file)
		if cached_image and cached_caption:
			return cached_caption, cached_image, tickers, period_days
	names, exchanges, closes = {}, {}, {}
	for ticker, history in zip(tickers, yahoo.fetch_each(yahoo.price_series, tickers)): # downloaded at the same time
		if isinstance(history, Exception):
			raise history
		names[ticker], exchanges[ticker], closes[ticker] = history
	limiting = max(closes, key=lambda t: closes[t].index[0]) # ticker with the shortest history
	common_start = closes[limiting].index[0]
	start = common_start
	note = ''
	if not period_days and not full_history: # default window; ask for a longer period (or max) to go further
		default_start = pd.Timestamp(datetime.datetime.now().date() - datetime.timedelta(days=3655))
		start = max(common_start, default_start)
	if period_days:
		requested = pd.Timestamp(datetime.datetime.now().date() - datetime.timedelta(days=period_days))
		if requested >= common_start:
			start = requested
		else:
			note = f" (limited by {limiting} history)"
	cropped = []
	for ticker in tickers:
		series = closes[ticker]
		base = series[series.index <= start]
		base_value = base.iloc[-1] if len(base) else series.iloc[0] # last close on/before the start date
		series = pd.concat([pd.Series([base_value], index=[start]), series[series.index > start]])
		cropped.append((ticker, series))
	if any(len(series) < 2 for _, series in cropped):
		raise RuntimeError("not enough price history in that period to compare")
	span_days = (datetime.datetime.now().date() - start.date()).days
	period_label = util.days_english(period_days) if period_days and not note else f"{span_days} days"
	by_performance = sorted(cropped, key=lambda item: item[1].iloc[-1] / item[1].iloc[0], reverse=True)
	title = ' vs '.join(t.split('.')[0] for t, _ in by_performance) # best first; line colours stay tied to input order
	subtitle = f"% change over {period_label}, since {start:%d %b %Y}" + note
	image = util.compare_graph([(t.split('.')[0], series) for t, series in cropped], title, subtitle)
	image.seek(0)
	caption = [webhook.bold(f"{period_label}, since {start:%d %b %Y}", service) + note]
	results = sorted(((series.iloc[-1] / series.iloc[0] - 1) * 100, t) for t, series in cropped)
	for pct, t in reversed(results):
		link = util.finance_link(t, exchanges[t], service, days=span_days, brief=False)
		caption.append(f"{util.get_emoji(pct)} {names[t]} ({link}): {pct:+,.1f}%")
	if config.prefs.cache:
		cache.write_bytes(image_cache_file, image)
		cache.write(caption_cache_file, caption)
		image.seek(0)
	return caption, image, tickers, period_days

def prepare_jobs_payload(service, args):
	"""`.jobs` lists the scheduled commands, each once; `.jobs run <number|command>` runs one now, as cron would.
	Returns (payload, reply_markup): Telegram gets a button per command."""
	from lib import jobs # here: jobs imports every script, and some scripts import this module
	scheduler = jobs.current
	if scheduler is None:
		return ['Scheduled jobs are off (scheduler=False)'], None
	args = (args or '').strip()
	if not args:
		commands = scheduler.commands()
		if not commands:
			return ['No scheduled jobs'], None
		payload = [webhook.bold('Scheduled commands:', service)]
		for number, (label, _, _) in enumerate(commands, 1):
			payload.append(f"{number}. {jobs.display(label)}" + (' (running)' if label in scheduler.busy else ''))
		payload.append("\nRun one with .jobs run NUMBER" + (' or tap it' if service == 'telegram' else ''))
		markup = None
		if service == 'telegram':
			buttons = [{'text': f"{number}. {jobs.display(label)}"[:30], 'callback_data': f"j|{number}|{jobs.checksum(label)}"} for number, (label, _, _) in enumerate(commands, 1)]
			markup = {'inline_keyboard': [buttons[i:i + 2] for i in range(0, len(buttons), 2)]}
		return payload, markup
	m = re.fullmatch(r'run(?:\s+(.+))?', args, re.IGNORECASE)
	if not m or not m.group(1):
		return ['Usage: .jobs [run NUMBER|COMMAND]'], None
	return [run_job_line(scheduler, m.group(1))], None

def run_job_line(scheduler, text):
	"""Run a scheduled command now and say how it went in one line."""
	from lib import jobs # here: jobs imports every script, and some scripts import this module
	try:
		return job_line(scheduler, *scheduler.run_now(text))
	except jobs.ScheduleError as e:
		return str(e)

def job_line(scheduler, label, outcome):
	from lib import jobs # here: jobs imports every script, and some scripts import this module
	number = [command[0] for command in scheduler.commands()].index(label) + 1
	return f"{number}. {jobs.display(label)}: {outcome}"

def prepare_help(service, botName):
	payload = []
	payload.append(webhook.bold("Tracked securities:", service))
	payload.append(".holdings")
	payload.append(".pie PORTFOLIO [sector]")
	payload.append(".watchlist [add|del SYMBOL]")
	payload.append(".who SYMBOL")

	payload.append(webhook.bold("\nCompany info:", service))
	payload.append('.SYMBOL')
	payload.append(".dividend [period|SYMBOL]")
	payload.append(".earnings [period|SYMBOL]")
	payload.append(".marketcap [SYMBOL|bottom|top]")

	payload.append(webhook.bold("\nPrice:", service))
	payload.append(".beta")
	payload.append(".compare SYMBOL SYMBOL [...] [period|max]")
	payload.append(".history SYMBOL")
	payload.append(".performance [period] [portfolio]")
	payload.append(".price [percent|SYMBOL] [period]")
	payload.append(".session [percent|SYMBOL]")
	payload.append(".premarket [percent|SYMBOL]")

	payload.append(webhook.bold("\nRisk & Value:", service))
	payload.append(".buy")
	payload.append(".sell")
	payload.append(".pe [SYMBOL|top|bottom]")
	payload.append(".forwardpe [SYMBOL|top|bottom|negative]")
	payload.append(".peg [SYMBOL|top|bottom|negative]")
	payload.append(".shorts [percent|SYMBOL]")

	payload.append(webhook.bold("\nTrades:", service))
	payload.append(".trades [period] [portfolio]")

	payload.append(webhook.bold("\nScheduled jobs:", service))
	payload.append(".jobs [run NUMBER|COMMAND]")

	payload.append(webhook.bold("\nAlternative syntax:", service))
	if service == 'slack':
		payload.append('<' + botName + '> trades')
	else:
		payload.append(botName + ' price')
	payload.append("")
	payload.append(f"Full help on {util.link('https://github.com/robdevops/finbot', 'GitHub', service)}")
	return payload

def prepare_holdings_payload(portfolio_name, service):
	"""The holdings of the portfolio called `portfolio_name`. Raises sharesight.PortfolioNotFound."""
	if not portfolio_name:
		names = [portfolio.name for portfolio in sharesight.portfolios()]
		return [".holdings: please try again specifying a portfolio:"] + names
	portfolio, = sharesight.portfolios(portfolio_name)
	holdings = portfolio.holdings()
	payload = sorted(holding_line(holding, service) for holding in holdings.values())
	if payload:
		payload.insert(0, webhook.bold(f"Holdings for {portfolio.name} ({len(holdings)})", service))
	return payload

def prepare_who(service, code):
	"""Which portfolios hold `code` (a ticker without its exchange), each holding linked to Sharesight."""
	payload = []
	for portfolio in sharesight.portfolios():
		found = [holding_line(holding, service, code)
			for holding in portfolio.holdings().values() if holding['code'].upper() == code]
		if found:
			payload += [webhook.bold(f"{portfolio.name}:", service), "\n".join(found), ""]
	return payload or [f'{code} not found in any portfolio']

def prepare_pie(portfolio_name, by, service, max_slices=8):
	"""Portfolio value by industry (or by='sector'). Returns (payload, chart); chart is None unless there is something to draw.
	Raises sharesight.PortfolioNotFound."""
	if not portfolio_name:
		names = [portfolio.name for portfolio in sharesight.portfolios()]
		return [".pie: please try again specifying a portfolio:"] + names, None
	portfolio, = sharesight.portfolios(portfolio_name)
	name = portfolio.name
	key = 'sector_classification_name' if by == 'sector' else 'industry_classification_name'
	totals = {}
	for holding in portfolio.holdings().values():
		try:
			value = float(holding.get('value'))
		except (TypeError, ValueError):
			continue
		if value > 0:
			label = holding.get(key) or 'Unclassified'
			totals[label] = totals.get(label, 0.0) + value
	if not totals:
		return [f"{name} has no holdings with a value"], None
	rows = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
	if len(rows) > max_slices:
		rest = sum(v for _, v in rows[max_slices - 1:])
		rows = rows[:max_slices - 1]
		rows.append(('Other', rest))
	total = sum(v for _, v in rows)
	title = f"{name} by {by}"
	payload = [webhook.bold(title, service)]
	payload += [f"{label}: {value / total * 100:.1f}%" for label, value in rows]
	noun = {'sector': ('sector', 'sectors'), 'industry': ('industry', 'industries')}[by]
	subtitle = f"{len(totals)} {noun[0] if len(totals) == 1 else noun[1]}"
	return payload, {'pie': True, 'rows': rows, 'title': title, 'subtitle': subtitle}

def prepare_marketcap_payload(service, action='top', length=15):
	"""The `length` tracked stocks of largest (action 'top') or smallest ('bottom') market cap, compared in US dollars at Yahoo's
	exchange rates: a market cap in won or yen is a far bigger number. Any other action is one ticker's, in its own currency too."""
	if action not in ('top', 'bottom'):
		ticker = util.transform_to_yahoo(action.upper())
		data = yahoo.add_usd_market_caps(yahoo.fetch_detail(ticker, 600)).get(ticker, {})
		if 'market_cap' not in data:
			return [f"Mkt cap not found for {ticker}"]
		currency = yahoo.market_cap_currency(data) or ''
		cap = f"{currency} {util.humanUnits(data['market_cap'])}".strip()
		if currency != 'USD' and 'market_cap_usd' in data:
			cap += f" (USD {util.humanUnits(data['market_cap_usd'])})"
		link = util.finance_link(ticker, data.get('profile_exchange', ''), service)
		return [util.security_line(util.flag_from_ticker(ticker), data.get('profile_title', ticker), link) + f" mkt cap: {cap}"]
	caps = [] # (market cap in US dollars, line)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch(util.get_holdings_and_watchlist())).items():
		if 'market_cap_usd' not in data:
			print(ticker, "no market cap" if 'market_cap' not in data else f"no exchange rate for {data.get('currency')}", file=sys.stderr)
			continue
		link = util.finance_link(ticker, data['profile_exchange'], service)
		caps.append((data['market_cap_usd'], util.security_line(util.flag_from_ticker(ticker), data['profile_title'], link) + f" mkt cap: {util.humanUnits(data['market_cap_usd'])}"))
	if not caps:
		return ['No market cap data found']
	caps.sort(key=lambda cap: cap[0], reverse=action == 'top')
	return [webhook.bold(f'{action.title()} {length} tracked stocks by market cap (USD)', service)] + [line for _, line in caps[:length]]

def prepare_rating_payload(service, action, length=15):
	"""(payload, chart) of the `length` tracked stocks rated `action` ('buy' or 'sell') by min_analysts or more analysts (fewer,
	and the consensus says little: ASX small caps covered by two to six brokers are nearly all a perfect 1.0 buy), the strongest
	rating first (1 is a strong buy, 5 a strong sell); on equal ratings, the one more analysts give first."""
	found = [] # (rating, analysts, line, ticker)
	for ticker, data in yahoo.fetch_details(util.get_holdings_and_watchlist()).items():
		if 'recommend' not in data or data['recommend_analysts'] < config.prefs.min_analysts:
			continue
		recommend = data['recommend'].replace('_', ' ')
		if (action == 'buy' and 'buy' in recommend) or (action == 'sell' and recommend in ('sell', 'underperform')):
			rating, analysts = round(data['recommend_index'], 2), data['recommend_analysts']
			link = util.finance_link(ticker, data['profile_exchange'], service)
			found.append((rating, analysts, f"{util.flag_from_ticker(ticker)} {data['profile_title']} ({link}) {rating} ({analysts} analysts)", ticker))
	found = sorted(found, key=lambda row: (row[0] if action == 'buy' else -row[0], -row[1]))[:length]
	payload = [line for _, _, line, _ in found]
	if not payload:
		return [f"No tracked stocks rated {action} by {config.prefs.min_analysts}+ analysts"], None
	message = f"Top {length} analyst {action} ratings for tracked stocks ({config.prefs.min_analysts}+ analysts)"
	shown = [(ticker.split('.')[0], rating) for rating, _, _, ticker in found]
	low, high = min(r for _, r in shown), max(r for _, r in shown)
	spread = (high - low) or 0.2
	# zoom the axis onto the ratings so the bars fill the panel (ratings only run 1-5)
	chart = {'rows': shown, 'title': message, 'subtitle': 'Mean analyst rating: 1 = strong buy, 5 = strong sell (axis zoomed)',
		'value_fmt': lambda v: f"{v:g}", 'xlim': (max(0.9, low - spread * 0.9), min(5.1, high + spread * 0.25))}
	return [webhook.bold(message, service)] + payload, chart

def prepare_value_payload(service, action='pe', ticker_select=None, length=15):
	"""(payload, chart): the tracked stocks by a ratio (`action`), or one ticker's. A forward P/E is analysts' estimate, so its lists
	take only stocks that min_analysts or more analysts cover, as .buy does."""
	payload = []
	chart_rows = [] # (ticker, ratio)
	tickers = [ticker_select] if ticker_select else util.get_holdings_and_watchlist()
	market_data = yahoo.fetch(tickers)
	if action in ('peg', 'bottom peg', 'negative peg'): # the PEG is in Yahoo's details
		market_data |= yahoo.fetch_details(market_data, strict=bool(ticker_select))
	covered = None # for a forward P/E list: the tickers enough analysts cover
	if 'forward' in action and not ticker_select:
		covered = {ticker for ticker, detail in yahoo.fetch_details(market_data).items() if detail.get('recommend_analysts', 0) >= config.prefs.min_analysts}
	for ticker in market_data:
		if covered is not None and ticker not in covered:
			continue
		trailing_ratio = None
		forward_ratio = None
		peg_ratio = None
		ratio = None
		if action in ('pe', 'bottom pe', 'forward pe', 'bottom forward pe'):
			trailing_ratio = market_data.get(ticker).get('price_to_earnings_trailing')
			forward_ratio = market_data.get(ticker).get('price_to_earnings_forward')
			if action in ('forward pe', 'bottom forward pe'):
				if not ticker_select and forward_ratio is not None and forward_ratio < 0:
					continue
				ratio = forward_ratio
			else:
				if not ticker_select and trailing_ratio is not None and trailing_ratio < 0:
					continue
				ratio = trailing_ratio
		elif action == 'negative forward pe':
			forward_ratio = market_data.get(ticker).get('price_to_earnings_forward')
			if not ticker_select and (forward_ratio is None or forward_ratio >= 0):
				continue
			ratio = forward_ratio
		elif action in ('peg', 'bottom peg'):
			peg_ratio = market_data.get(ticker).get('price_to_earnings_peg')
			if not ticker_select and peg_ratio is not None and peg_ratio < 0:
				continue
			ratio = peg_ratio
		elif action == 'negative peg':
			peg_ratio = market_data.get(ticker).get('price_to_earnings_peg')
			if not ticker_select and (peg_ratio is None or peg_ratio >= 0):
				continue
			ratio = peg_ratio
		if ratio is None:
			continue
		profile_title = market_data.get(ticker).get('profile_title')
		ticker_link = util.finance_link(ticker, market_data.get(ticker).get('profile_exchange'), service)
		flag = util.flag_from_ticker(ticker)
		if ticker_select and action in {'pe', 'forward pe'}:
			parts = []
			if trailing_ratio is not None:
				parts.append(f"trailing {trailing_ratio}")
			if forward_ratio is not None:
				parts.append(f"forward {forward_ratio}")
			payload.append(f"{flag} {profile_title} ({ticker_link}) PE: {', '.join(parts)}")
		else:
			payload.append(f"{flag} {profile_title} ({ticker_link}) {ratio}")
			chart_rows.append((ticker.split('.')[0], float(ratio)))
	payload.sort(key=last_col)
	chart_rows.sort(key=lambda row: row[1])
	chart = None
	if not ticker_select:
		heading_type = "Bottom" if 'bottom' in action else "Top"
		heading_trail = action.replace('bottom ', '')
		if 'bottom' in action:
			payload.reverse()
			chart_rows.reverse()
		payload = payload[:length]
		coverage = f" ({config.prefs.min_analysts}+ analysts)" if covered is not None else ''
		if not payload:
			payload = [f"No tracked stocks with {config.prefs.min_analysts}+ analysts have a {heading_trail} ratio" if covered is not None else f"{action}: no data found"]
		else:
			heading = f'{heading_type} {length} tracked stocks by {heading_trail} ratio{coverage}'
			payload.insert(0, f"{webhook.bold(heading, service)}")
			chart = {'rows': chart_rows[:length], 'title': heading, 'value_fmt': lambda v: f"{v:g}"}
	return payload, chart

def prepare_beta_payload(service):
	"""(payload, chart) of the tracked stocks with a beta over 1.5 and a market cap under US$2B, the highest beta first."""
	found = [] # (beta, line, chart row)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch_details(util.get_holdings_and_watchlist())).items():
		if 'beta' not in data:
			continue
		beta = round(data['beta'], 1)
		if beta > 1.5 and data.get('market_cap_usd', float('inf')) < 2e9:
			link = util.finance_link(ticker, data['profile_exchange'], service)
			found.append((beta, util.security_line(util.flag_from_ticker(ticker), data['profile_title'], link) + f" {beta} β", (ticker.split('.')[0], float(beta))))
	if not found:
		return ['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'], None
	found.sort(key=lambda row: row[0], reverse=True)
	heading = 'Beta over 1.5 and mkt cap under US$2B'
	chart = {'rows': [row for _, _, row in found], 'title': heading, 'value_fmt': lambda v: f"{v:g}"}
	return [webhook.bold(heading, service)] + [line for _, line, _ in found], chart

MARKET_STATE_EMOJI = {'REGULAR': '🟢', 'PRE': '🟠', 'POST': '🟠'} # any other state is closed: 🔴

def prepare_profile_payload(service, user, ticker):
	"""The .SYMBOL report: what Yahoo knows about one company. A field Yahoo did not send leaves its line out."""
	ticker_orig = util.transform_to_yahoo(ticker)
	now = datetime.datetime.now()
	payload = []
	ticker, market_data = yahoo.resolve(ticker_orig, lambda symbol: yahoo.fetch_detail(symbol, 600))
	if ticker not in market_data:
		return [f"{user} 🛑 Beep Boop. I could not find {ticker_orig}"]
	data = market_data[ticker]
	code = ticker.split('.')[0]
	title = data.get('profile_title', '')
	state = data.get('marketState', '').rstrip()
	currency = data.get('currency', '')
	exchange = data.get('profile_exchange', '').replace('NasdaqCM', 'Nasdaq').replace('NasdaqGS', 'Nasdaq').replace('NYSEArca', 'NYSE')
	ticker_link = util.finance_link(ticker, exchange, service, brief=False)
	gfinance_link = util.gfinance_link(ticker, exchange, service, brief=True, text='google') # all three before exchange is renamed below
	sws_link = util.link(simplywallst.get_url(ticker, title, exchange), 'simplywall.st', service)
	macrotrends_link = util.link('https://www.google.com/search?q=site:macrotrends.net+' + title + '+PE Ratio+' + code + '&btnI', 'macrotrends', service)
	if 'profile_bio' in data:
		payload.append(util.make_paragraphs(data['profile_bio']))

	if exchange == 'ASX':
		exchange_url = 'https://www2.asx.com.au/markets/company/' + code
	elif exchange == 'HKSE':
		exchange_url = 'https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=' + code + '&sc_lang=en'
	elif 'Nasdaq' in exchange:
		exchange_url = 'https://www.nasdaq.com/market-activity/stocks/' + ticker.lower()
	elif exchange == 'NYSE':
		exchange_url = 'https://www.nyse.com/quote/XNYS:' + ticker
	elif exchange == 'Taiwan':
		exchange = 'TWSE'
		exchange_url = 'https://mis.twse.com.tw/stock/fibest.jsp?stock=' + code + '&lang=en_us'
	elif exchange == 'Tokyo':
		exchange = 'JPX'
		exchange_url = 'https://quote.jpx.co.jp/jpx/template/quote.cgi?F=tmp/e_stock_detail&MKTN=T&QCODE=' + code
	else:
		exchange_url = 'https://www.google.com/search?q=stock+exchange+' + exchange + '+' + code + '&btnI'
	exchange_link = util.link(exchange_url, exchange, service)
	location = [data[key] for key in ('profile_city', 'profile_state', 'profile_country') if key in data]
	if payload:
		payload.append("")

	if location:
		payload.append(webhook.bold("Location:", service) + " " + ', '.join(location))
	if 'profile_industry' in data and 'profile_sector' in data:
		payload.append(webhook.bold("Classification: ", service) + f"{data['profile_industry']}, {data['profile_sector']}")
	if 'profile_employees' in data:
		payload.append(webhook.bold("Employees: ", service) + f"{data['profile_employees']:,}")
	if 'profile_website' in data:
		links = [util.link(data['profile_website'], util.strip_url(data['profile_website']), service), exchange_link]
		if 'NYSE' in exchange or 'Nasdaq' in exchange:
			links += [util.link('https://finviz.com/quote.ashx?t=' + ticker, 'finviz', service), macrotrends_link,
				util.link('https://seekingalpha.com/symbol/' + ticker, 'seekingalpha', service)]
		elif exchange == 'ASX':
			links.append(util.link('https://www.shortman.com.au/stock?q=' + code.lower(), 'shortman', service))
		payload.append(webhook.bold("Links: ", service) + ' | '.join(links))

	if payload:
		payload.append("")

	if 'currency' in data and 'market_cap' in data:
		payload.append(webhook.bold("Mkt cap:", service) + f" {yahoo.market_cap_currency(data)} {util.humanUnits(data['market_cap'])}") # GBP, not pence
	if all(key in data for key in ('shareholder_equity', 'total_debt', 'total_cash', 'profile_industry')) and data['shareholder_equity'] and 'Bank' not in data['profile_industry']:
		net_debt_equity_ratio = round((data['total_debt'] - data['total_cash']) / data['shareholder_equity'] * 100)
		if net_debt_equity_ratio > 0:
			payload.append(webhook.bold("Net debt/equity ratio:", service) + f" {net_debt_equity_ratio}%" + ('⚠️ ' if net_debt_equity_ratio > 40 else ''))
	if 'earnings_date' in data:
		earnings_date = datetime.datetime.fromtimestamp(data['earnings_date'])
		if earnings_date > now:
			payload.append(webhook.bold("Earnings date:", service) + f" {earnings_date:%b %d}")
	if data.get('dividend', 0) > 0:
		payload.append(webhook.bold("Dividend:", service) + f" {data['dividend']}%")
		if 'ex_dividend_date' in data:
			ex_dividend_date = datetime.datetime.fromtimestamp(data['ex_dividend_date'])
			if ex_dividend_date > now:
				payload.append(webhook.bold("Ex-dividend date:", service) + f" {ex_dividend_date:%b %d}")
	cashflow = data.get('free_cashflow', data.get('operating_cashflow'))
	if cashflow:
		payload.append(webhook.bold("Cashflow positive:", service) + (" no ⚠️ " if cashflow < 0 else " yes"))
	if 'net_income' in data:
		payload.append(webhook.bold("Profitable:", service) + (" no ⚠️ " if data['net_income'] <= 0 else " yes"))
	else:
		payload.append(webhook.bold("Profitable:", service) + " unknown ⚠️")

	if payload:
		payload.append("")

	if 'earningsQ' in data:
		deltas = [(doDelta(data[key]), label) for key, label in (('revenueQ', 'quarterly revenue'), ('earningsQ', 'quarterly earnings'),
			('revenueY', 'annual revenue'), ('earningsY', 'annual earnings'))]
		payload += [f"{delta}\t{label} delta" for delta, label in deltas] # doDelta always gives at least three symbols

	if payload:
		payload.append("")

	for key, label in (('revenueEstimateY', 'Revenue forecast (1Y):'), ('earningsEstimateY', 'Earnings forecast (1Y):')):
		if key in data:
			growth = int(round(data[key]))
			payload.append(webhook.bold(label, service) + (f" +{growth}% " if growth > 0 else f" {growth}% ⚠️ "))
	if 'insiderBuy' in data:
		if data['insiderBuy'] > data['insiderSell']:
			payload.append(webhook.bold("Net insider action (3M):", service) + f" Buy {currency} {util.humanUnits(data['insiderBuyValue'])} ")
		elif data['insiderBuy'] < data['insiderSell']:
			payload.append(webhook.bold("Net insider action (3M):", service) + f" Sell {currency} {util.humanUnits(data['insiderSellValue'])}⚠️ ")
	if 'short_percent' in data:
		payload.append(webhook.bold("Shorted stock:", service) + f" {data['short_percent']}%" + ('⚠️ ' if data['short_percent'] > 10 else ''))
	if 'recommend' in data:
		payload.append(webhook.bold("Score:", service) + f" {data['recommend_index']} {data['recommend'].replace('_', ' ')} ({data['recommend_analysts']} analysts)")

	if payload:
		payload.append("")

	if 'regularMarketPrice' in data:
		price_line = webhook.bold("Price:", service) + f" {currency} {data['regularMarketPrice']:,.2f}"
		if state != 'REGULAR' and 'prePostMarketPrice' in data:
			price_line += f" ({data['prePostMarketPrice']:,.2f} after hrs)"
		payload.append(price_line)
	trailing_pe = str(int(round(data['price_to_earnings_trailing']))) if 'price_to_earnings_trailing' in data else 'N/A ⚠️ '
	if data.get('net_income', 0) > 0:
		payload.append(webhook.bold("Trailing P/E:", service) + f" {trailing_pe}")
	if data.get('netIncomeToCommon', 0) > 0 and data.get('sharesOutstanding') and 'regularMarketPrice' in data:
		current_pe = round(data['regularMarketPrice'] / (data['netIncomeToCommon'] / data['sharesOutstanding']))
		payload.append(webhook.bold("Current P/E:", service) + f" {current_pe}")
	if 'price_to_earnings_forward' in data:
		forward_pe = int(round(data['price_to_earnings_forward']))
		warn = forward_pe < 0
		if 'profile_industry' in data: # software is dear: it warns above 100, the rest above 30 or above their trailing P/E
			warn = warn or forward_pe > (100 if 'Software' in data['profile_industry'] else 30)
			warn = warn or ('price_to_earnings_trailing' in data and forward_pe > int(trailing_pe))
		payload.append(webhook.bold("Forward P/E:", service) + f" {forward_pe} " + ('⚠️ ' if warn else ''))
	if 'price_to_earnings_peg' in data:
		payload.append(webhook.bold("PEG ratio:", service) + f" {round(data['price_to_earnings_peg'], 1)}")
	if 'price_to_sales' in data:
		price_to_sales = round(data['price_to_sales'], 1)
		payload.append(webhook.bold("PS ratio:", service) + f" {price_to_sales} " + ('⚠️ ' if price_to_sales > 15 else ''))

	if payload:
		payload.append("")

	try:
		price_history, _ = yahoo.price_history(ticker, graph=False) # the percentages only: the profile has no chart
	except RuntimeError as e: # no chart data: the profile goes out without these lines
		print(ticker, e, file=sys.stderr)
		price_history = {}
	for interval in ('5Y', '1Y', '1M', '1D'):
		if interval in price_history:
			percent = price_history[interval]
			payload.append(f"{util.get_emoji(percent)} {webhook.bold(interval + ':', service)} {percent}%")
	if state != 'REGULAR':
		for key, label in (('percent_change_premarket', 'Pre-market:'), ('percent_change_postmarket', 'Post-market:')):
			if key in data:
				payload.append(f"{util.get_emoji(data[key])} {webhook.bold(label, service)} {data[key]:,}%")
				break

	if 'profile_website' in data and config.prefs.hyperlinkFooter and config.prefs.hyperlink:
		if payload:
			payload.append("")
		payload.append(f"{gfinance_link} | {util.yahoo_link(ticker, service, brief=True, text='yahoo')} | {sws_link}")
	heading = f"{webhook.bold(title, service)} ({ticker_link}) {MARKET_STATE_EMOJI.get(state, '🔴') if state else ''}"
	if ticker_orig == ticker:
		payload.insert(0, heading)
	else:
		payload[:0] = [f"I could not find {ticker_orig} but I found {ticker_link}:", "", heading]
	payload = [i[0] for i in groupby(payload)] # de-dupe white space
	if len(payload) < 2:
		payload.append("no data found")
	return payload
