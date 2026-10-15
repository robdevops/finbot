"""The .SYMBOL report: what Yahoo and Simply Wall St know about one company."""
from itertools import pairwise
import datetime
import sys
from lib import config
from lib import formats
from lib import links
from lib import markets
from lib import yahoo
from lib import simplywallst
from itertools import groupby

def doDelta(inputList):
	"""Trend marks between consecutive figures (four quarters give three): 🔼 up and 🔽 down while the figure is positive,
	🔺 up and 🔻 down while it is negative, ▪️ unchanged, ❌ missing; padded with ❌ to three."""
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

MARKET_STATE_EMOJI = {'REGULAR': '🟢', 'PRE': '🟠', 'POST': '🟠'} # any other state is closed: 🔴

def prepare_profile_payload(service, user, ticker):
	"""The .SYMBOL report: what Yahoo knows about one company. A field Yahoo did not send leaves its line out."""
	ticker_orig = markets.transform_to_yahoo(ticker)
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
	ticker_link = links.finance_link(ticker, exchange, service, brief=False)
	gfinance_link = links.gfinance_link(ticker, exchange, service, brief=True, text='google') # all three before exchange is renamed below
	sws_link = service.link(simplywallst.get_url(ticker, title, exchange), 'simplywall.st')
	macrotrends_link = service.link('https://www.google.com/search?q=site:macrotrends.net+' + title + '+PE Ratio+' + code + '&btnI', 'macrotrends')
	if 'profile_bio' in data:
		payload.append(formats.make_paragraphs(data['profile_bio']))

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
	exchange_link = service.link(exchange_url, exchange)
	location = [data[key] for key in ('profile_city', 'profile_state', 'profile_country') if key in data]
	if payload:
		payload.append("")

	if location:
		payload.append(service.bold("Location:") + " " + ', '.join(location))
	if 'profile_industry' in data and 'profile_sector' in data:
		payload.append(service.bold("Classification: ") + f"{data['profile_industry']}, {data['profile_sector']}")
	if 'profile_employees' in data:
		payload.append(service.bold("Employees: ") + f"{data['profile_employees']:,}")
	if 'profile_website' in data:
		sites = [service.link(data['profile_website'], formats.strip_url(data['profile_website'])), exchange_link]
		if 'NYSE' in exchange or 'Nasdaq' in exchange:
			sites += [service.link('https://finviz.com/quote.ashx?t=' + ticker, 'finviz'), macrotrends_link,
				service.link('https://seekingalpha.com/symbol/' + ticker, 'seekingalpha')]
		elif exchange == 'ASX':
			sites.append(service.link('https://www.shortman.com.au/stock?q=' + code.lower(), 'shortman'))
		payload.append(service.bold("Links: ") + ' | '.join(sites))

	if payload:
		payload.append("")

	if 'currency' in data and 'market_cap' in data:
		payload.append(service.bold("Mkt cap:") + f" {yahoo.market_cap_currency(data)} {formats.humanUnits(data['market_cap'])}") # GBP, not pence
	if all(key in data for key in ('shareholder_equity', 'total_debt', 'total_cash', 'profile_industry')) and data['shareholder_equity'] and 'Bank' not in data['profile_industry']:
		net_debt_equity_ratio = round((data['total_debt'] - data['total_cash']) / data['shareholder_equity'] * 100)
		if net_debt_equity_ratio > 0:
			payload.append(service.bold("Net debt/equity ratio:") + f" {net_debt_equity_ratio}%" + ('⚠️ ' if net_debt_equity_ratio > 40 else ''))
	if 'earnings_date' in data:
		earnings_date = datetime.datetime.fromtimestamp(data['earnings_date'])
		if earnings_date > now:
			payload.append(service.bold("Earnings date:") + f" {earnings_date:%b %d}")
	if data.get('dividend', 0) > 0:
		payload.append(service.bold("Dividend:") + f" {data['dividend']}%")
		if 'ex_dividend_date' in data:
			ex_dividend_date = datetime.datetime.fromtimestamp(data['ex_dividend_date'])
			if ex_dividend_date > now:
				payload.append(service.bold("Ex-dividend date:") + f" {ex_dividend_date:%b %d}")
	cashflow = data.get('free_cashflow', data.get('operating_cashflow'))
	if cashflow:
		payload.append(service.bold("Cashflow positive:") + (" no ⚠️ " if cashflow < 0 else " yes"))
	if 'net_income' in data:
		payload.append(service.bold("Profitable:") + (" no ⚠️ " if data['net_income'] <= 0 else " yes"))
	else:
		payload.append(service.bold("Profitable:") + " unknown ⚠️")

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
			payload.append(service.bold(label) + f" {formats.signed_percent(growth)} " + ('' if growth > 0 else '⚠️ '))
	if 'insiderBuy' in data:
		if data['insiderBuy'] > data['insiderSell']:
			payload.append(service.bold("Net insider action (3M):") + f" Buy {currency} {formats.humanUnits(data['insiderBuyValue'])} ")
		elif data['insiderBuy'] < data['insiderSell']:
			payload.append(service.bold("Net insider action (3M):") + f" Sell {currency} {formats.humanUnits(data['insiderSellValue'])}⚠️ ")
	if 'short_percent' in data:
		payload.append(service.bold("Shorted stock:") + f" {data['short_percent']}%" + ('⚠️ ' if data['short_percent'] > 10 else ''))
	if 'recommend' in data:
		payload.append(service.bold("Score:") + f" {data['recommend_index']} {data['recommend'].replace('_', ' ')} ({data['recommend_analysts']} analysts)")

	if payload:
		payload.append("")

	if 'regularMarketPrice' in data:
		price_line = service.bold("Price:") + f" {currency} {data['regularMarketPrice']:,.2f}"
		if state != 'REGULAR' and 'prePostMarketPrice' in data:
			price_line += f" ({data['prePostMarketPrice']:,.2f} after hrs)"
		payload.append(price_line)
	trailing_pe = str(int(round(data['price_to_earnings_trailing']))) if 'price_to_earnings_trailing' in data else 'N/A ⚠️ '
	if data.get('net_income', 0) > 0:
		payload.append(service.bold("Trailing P/E:") + f" {trailing_pe}")
	if data.get('netIncomeToCommon', 0) > 0 and data.get('sharesOutstanding') and 'regularMarketPrice' in data:
		current_pe = round(data['regularMarketPrice'] / (data['netIncomeToCommon'] / data['sharesOutstanding']))
		payload.append(service.bold("Current P/E:") + f" {current_pe}")
	if 'price_to_earnings_forward' in data:
		forward_pe = int(round(data['price_to_earnings_forward']))
		warn = forward_pe < 0
		if 'profile_industry' in data: # software is dear: it warns above 100, the rest above 30 or above their trailing P/E
			warn = warn or forward_pe > (100 if 'Software' in data['profile_industry'] else 30)
			warn = warn or ('price_to_earnings_trailing' in data and forward_pe > int(trailing_pe))
		payload.append(service.bold("Forward P/E:") + f" {forward_pe} " + ('⚠️ ' if warn else ''))
	if 'price_to_earnings_peg' in data:
		payload.append(service.bold("PEG ratio:") + f" {round(data['price_to_earnings_peg'], 1)}")
	if 'price_to_sales' in data:
		price_to_sales = round(data['price_to_sales'], 1)
		payload.append(service.bold("PS ratio:") + f" {price_to_sales} " + ('⚠️ ' if price_to_sales > 15 else ''))

	if payload:
		payload.append("")

	try:
		price_history, _ = yahoo.price_history(ticker) # the percentages only: the profile has no chart
	except RuntimeError as e: # no chart data: the profile goes out without these lines
		print(ticker, e, file=sys.stderr)
		price_history = {}
	for interval in ('5Y', '1Y', '1M', '1D'):
		if interval in price_history:
			percent = price_history[interval]
			label = service.bold(interval + ':')
			payload.append(f"{formats.get_emoji(percent)} {label} {formats.signed_percent(percent)}")
	if state != 'REGULAR':
		for key, label in (('percent_change_premarket', 'Pre-market:'), ('percent_change_postmarket', 'Post-market:')):
			if key in data:
				change = data[key]
				payload.append(f"{formats.get_emoji(change)} {service.bold(label)} {formats.signed_percent(change)}")
				break

	if 'profile_website' in data and config.prefs.hyperlinkFooter and config.prefs.hyperlink:
		if payload:
			payload.append("")
		payload.append(f"{gfinance_link} | {links.yahoo_link(ticker, service, brief=True, text='yahoo')} | {sws_link}")
	heading = f"{service.bold(title)} ({ticker_link}) {MARKET_STATE_EMOJI.get(state, '🔴') if state else ''}"
	if ticker_orig == ticker:
		payload.insert(0, heading)
	else:
		payload[:0] = [f"I could not find {ticker_orig} but I found {ticker_link}:", "", heading]
	payload = [i[0] for i in groupby(payload)] # de-dupe white space
	if len(payload) < 2:
		payload.append("no data found")
	return payload
