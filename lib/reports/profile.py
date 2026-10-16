"""The .SYMBOL report: what Yahoo and Simply Wall St know about one company."""
from itertools import pairwise
import datetime
from lib import log
from lib import config
from lib import formats
from lib import links
from lib import yahoo
from lib import simplywallst

TRENDS = {(True, False): '🔼', (False, False): '🔽', (True, True): '🔺', (False, True): '🔻'} # (rose, below zero)

def trend_marks(figures):
	"""Trend marks between consecutive figures (four quarters give three): 🔼 up and 🔽 down while the figure is positive,
	🔺 up and 🔻 down while it is negative, ▪️ unchanged, ❌ missing; padded with ❌ in front to three. A missing figure
	takes the one before it (the first, the first there is) to measure the next against."""
	filled = []
	for figure in figures:
		first = next((f for f in figures if f is not None), 0)
		filled.append(figure if figure is not None else filled[-1] if filled else first)
	marks = ''
	for i, (before, after) in enumerate(pairwise(filled)):
		if figures[i + 1] is None or (i == 0 and figures[0] is None):
			marks += '❌'
		else:
			marks += '▪️' if after == before else TRENDS[(after > before, figures[i + 1] < 0)]
	return '❌' * (3 - len(marks)) + marks

MARKET_STATE_EMOJI = {'REGULAR': '🟢', 'PRE': '🟠', 'POST': '🟠'} # any other state is closed: 🔴
EXCHANGE_PAGES = { # Yahoo's name for an exchange: (the name shown, or None for Yahoo's; the stock's page there)
	'ASX': ('ASX', 'https://www2.asx.com.au/markets/company/{code}'),
	'HKSE': ('HKSE', 'https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote'
		'?sym={code}&sc_lang=en'),
	'Nasdaq': (None, 'https://www.nasdaq.com/market-activity/stocks/{lower}'), # every Nasdaq tier
	'NYSE': ('NYSE', 'https://www.nyse.com/quote/XNYS:{ticker}'),
	'Taiwan': ('TWSE', 'https://mis.twse.com.tw/stock/fibest.jsp?stock={code}&lang=en_us'),
	'Tokyo': ('JPX', 'https://quote.jpx.co.jp/jpx/template/quote.cgi?F=tmp/e_stock_detail&MKTN=T&QCODE={code}'),
}

def prepare_profile_payload(service, user, ticker):
	"""The .SYMBOL report: what Yahoo knows about one company (ticker: Yahoo's symbol), in sections a blank line apart.
	A field Yahoo did not send leaves its line out, and a section with none its blank line."""
	market_data = yahoo.fetch_detail(ticker, 600)
	if ticker not in market_data:
		return [f"{user} 🛑 Beep Boop. I could not find {ticker}"]
	data = market_data[ticker]
	state = data.get('marketState', '').rstrip()
	exchange = data.get('profile_exchange', '').replace('NasdaqCM', 'Nasdaq').replace('NasdaqGS', 'Nasdaq')
	exchange = exchange.replace('NYSEArca', 'NYSE')
	payload = formats.sections(about(data), company(service, data, ticker, exchange), figures(service, data),
		trends(data), outlook(service, data), valuation(service, data, state), changes(service, data, ticker, state),
		footer(service, data, ticker, exchange))
	ticker_link = links.finance_link(ticker, exchange, service, brief=False)
	light = MARKET_STATE_EMOJI.get(state, '🔴') if state else ''
	heading = f"{service.bold(data.get('profile_title', ''))} ({ticker_link}) {light}"
	payload.insert(0, heading)
	if len(payload) < 2:
		payload.append("no data found")
	return payload

def exchange_page(exchange, ticker):
	"""(the exchange's name to show, the stock's page there): a search for the page on one EXCHANGE_PAGES lacks."""
	code = ticker.split('.')[0]
	key = 'Nasdaq' if 'Nasdaq' in exchange else exchange
	if key not in EXCHANGE_PAGES:
		return exchange, 'https://www.google.com/search?q=stock+exchange+' + exchange + '+' + code + '&btnI'
	name, page = EXCHANGE_PAGES[key]
	return name or exchange, page.format(code=code, ticker=ticker, lower=ticker.lower())

def about(data):
	"""What the company does, in paragraphs."""
	return [formats.make_paragraphs(data['profile_bio'])] if 'profile_bio' in data else []

def company(service, data, ticker, exchange):
	"""Where it is, what it is, its size, and its pages: its website, its exchange's page and a few more."""
	lines = []
	location = [data[key] for key in ('profile_city', 'profile_state', 'profile_country') if key in data]
	if location:
		lines.append(service.bold("Location:") + " " + ', '.join(location))
	if 'profile_industry' in data and 'profile_sector' in data:
		lines.append(service.bold("Classification: ") + f"{data['profile_industry']}, {data['profile_sector']}")
	if 'profile_employees' in data:
		lines.append(service.bold("Employees: ") + f"{data['profile_employees']:,}")
	if 'profile_website' in data:
		code = ticker.split('.')[0]
		name, page = exchange_page(exchange, ticker)
		website = data['profile_website']
		sites = [service.link(website, formats.strip_url(website)), service.link(page, name)]
		if 'NYSE' in exchange or 'Nasdaq' in exchange:
			title = data.get('profile_title', '')
			macrotrends = f'https://www.google.com/search?q=site:macrotrends.net+{title}+PE Ratio+{code}&btnI'
			sites += [service.link('https://finviz.com/quote.ashx?t=' + ticker, 'finviz'),
				service.link(macrotrends, 'macrotrends'),
				service.link('https://seekingalpha.com/symbol/' + ticker, 'seekingalpha')]
		elif exchange == 'ASX':
			sites.append(service.link('https://www.shortman.com.au/stock?q=' + code.lower(), 'shortman'))
		lines.append(service.bold("Links: ") + ' | '.join(sites))
	return lines

def figures(service, data):
	"""Its size, dates, dividend, cashflow and whether it makes a profit (always said, if only as unknown)."""
	now = datetime.datetime.now()
	lines = []
	if 'currency' in data and 'market_cap' in data:
		cap = f"{yahoo.market_cap_currency(data)} {formats.human_units(data['market_cap'])}" # GBP, not pence
		lines.append(service.bold("Mkt cap:") + f" {cap}")
	if 'earnings_date' in data:
		earnings_date = datetime.datetime.fromtimestamp(data['earnings_date'])
		if earnings_date > now:
			lines.append(service.bold("Earnings date:") + f" {earnings_date:%b %d}")
	if data.get('dividend', 0) > 0:
		lines.append(service.bold("Dividend:") + f" {data['dividend']}%")
		if 'ex_dividend_date' in data:
			ex_dividend_date = datetime.datetime.fromtimestamp(data['ex_dividend_date'])
			if ex_dividend_date > now:
				lines.append(service.bold("Ex-dividend date:") + f" {ex_dividend_date:%b %d}")
	cashflow = data.get('free_cashflow', data.get('operating_cashflow'))
	if cashflow:
		lines.append(service.bold("Cashflow positive:") + (" no ⚠️ " if cashflow < 0 else " yes"))
	if 'net_income' in data:
		lines.append(service.bold("Profitable:") + (" no ⚠️ " if data['net_income'] <= 0 else " yes"))
	else:
		lines.append(service.bold("Profitable:") + " unknown ⚠️")
	return lines

def trends(data):
	"""Trend marks of the last quarters' and years' revenue and earnings."""
	if 'earningsQ' not in data:
		return []
	figures = (('revenueQ', 'quarterly revenue'), ('earningsQ', 'quarterly earnings'),
		('revenueY', 'annual revenue'), ('earningsY', 'annual earnings'))
	return [f"{trend_marks(data[key])}\t{label} delta" for key, label in figures] # always at least three marks

def outlook(service, data):
	"""The analysts' forecasts and score, insiders' buying or selling, and the short interest."""
	lines = []
	for key, label in (('revenueEstimateY', 'Revenue forecast (1Y):'),
			('earningsEstimateY', 'Earnings forecast (1Y):')):
		if key in data:
			growth = int(round(data[key]))
			lines.append(service.bold(label) + f" {formats.signed_percent(growth)} " + ('' if growth > 0 else '⚠️ '))
	currency = data.get('currency', '')
	if 'insiderBuy' in data:
		if data['insiderBuy'] > data['insiderSell']:
			value = formats.human_units(data['insiderBuyValue'])
			lines.append(service.bold("Net insider action (3M):") + f" Buy {currency} {value} ")
		elif data['insiderBuy'] < data['insiderSell']:
			value = formats.human_units(data['insiderSellValue'])
			lines.append(service.bold("Net insider action (3M):") + f" Sell {currency} {value}⚠️ ")
	if 'short_percent' in data:
		shorted = data['short_percent']
		lines.append(service.bold("Shorted stock:") + f" {shorted}%" + ('⚠️ ' if shorted > 10 else ''))
	if 'recommend' in data:
		rating = data['recommend']
		score = f"{data['recommend_index']} {rating} ({data['recommend_analysts']} analysts)"
		lines.append(service.bold("Score:") + f" {score}")
	return lines

def valuation(service, data, state):
	"""The price (after hours too, out of session) and the price ratios, with a warning where one is high."""
	lines = []
	currency = data.get('currency', '')
	if 'regularMarketPrice' in data:
		price_line = service.bold("Price:") + f" {currency} {data['regularMarketPrice']:,.2f}"
		if state != 'REGULAR' and 'prePostMarketPrice' in data:
			price_line += f" ({data['prePostMarketPrice']:,.2f} after hrs)"
		lines.append(price_line)
	trailing_pe = 'N/A ⚠️ '
	if 'price_to_earnings_trailing' in data:
		trailing_pe = str(int(round(data['price_to_earnings_trailing'])))
	if data.get('net_income', 0) > 0:
		lines.append(service.bold("Trailing P/E:") + f" {trailing_pe}")
	if data.get('netIncomeToCommon', 0) > 0 and data.get('sharesOutstanding') and 'regularMarketPrice' in data:
		current_pe = round(data['regularMarketPrice'] / (data['netIncomeToCommon'] / data['sharesOutstanding']))
		lines.append(service.bold("Current P/E:") + f" {current_pe}")
	if 'price_to_earnings_forward' in data:
		forward_pe = int(round(data['price_to_earnings_forward']))
		warn = forward_pe < 0
		# software is dear: it warns above 100, the rest above 30 or above their trailing P/E
		if 'profile_industry' in data:
			warn = warn or forward_pe > (100 if 'Software' in data['profile_industry'] else 30)
			warn = warn or ('price_to_earnings_trailing' in data and forward_pe > int(trailing_pe))
		lines.append(service.bold("Forward P/E:") + f" {forward_pe} " + ('⚠️ ' if warn else ''))
	if 'price_to_earnings_peg' in data:
		lines.append(service.bold("PEG ratio:") + f" {round(data['price_to_earnings_peg'], 1)}")
	if 'price_to_sales' in data:
		price_to_sales = round(data['price_to_sales'], 1)
		lines.append(service.bold("PS ratio:") + f" {price_to_sales} " + ('⚠️ ' if price_to_sales > 15 else ''))
	return lines

def changes(service, data, ticker, state):
	"""The price's change over 5 years, a year, a month and a day, and out of session the pre- or post-market move."""
	lines = []
	try:
		history, _ = yahoo.price_history(ticker, quote=data) # the percentages only: the profile has no chart
	except RuntimeError as e: # no chart data: the profile goes out without these lines
		log.warn(ticker, e)
		history = {}
	for interval in ('5Y', '1Y', '1M', '1D'):
		if interval in history:
			percent = history[interval]
			label = service.bold(interval + ':')
			lines.append(f"{formats.get_emoji(percent)} {label} {formats.signed_percent(percent)}")
	if state != 'REGULAR':
		for key, label in (('percent_change_premarket', 'Pre-market:'), ('percent_change_postmarket', 'Post-market:')):
			if key in data:
				change = data[key]
				lines.append(f"{formats.get_emoji(change)} {service.bold(label)} {formats.signed_percent(change)}")
				break
	return lines

def footer(service, data, ticker, exchange):
	"""Links to the company on Google Finance, Yahoo and Simply Wall St, with hyperlinkFooter (and hyperlinks) on."""
	if 'profile_website' not in data or not (config.settings.hyperlinkFooter and config.settings.hyperlink):
		return []
	google = links.gfinance_link(ticker, exchange, service, brief=True, text='google')
	sws = service.link(simplywallst.get_url(ticker, data.get('profile_title', ''), exchange), 'simplywall.st')
	return [f"{google} | {links.yahoo_link(ticker, service, brief=True, text='yahoo')} | {sws}"]
