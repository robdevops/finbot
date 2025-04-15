from itertools import pairwise
import json, re
import datetime
import sys
from lib.config import *
from lib import sharesight
from lib import util
from lib import webhook
from lib import yahoo
from lib import simplywallst
from itertools import groupby

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
	if ticker:
		ticker = ticker_orig = util.transform_to_yahoo(ticker)
		ticker_link = util.finance_link(ticker, ticker, service)
	duplicate = False
	transformed = False
	watchlist = util.json_load('finbot_watchlist.json', persist=True)
	if action == 'add':
		if ticker in watchlist:
			duplicate = True
		else:
			watchlist.append(ticker)
	if len(watchlist):
		market_data = yahoo.fetch(watchlist)
	else:
		market_data = None
	print("")
	if action == 'delete':
		if ticker in watchlist:
			watchlist.remove(ticker)
		else:
			print(ticker, "not in watchlist")
	if action == 'add':
		if '.' not in ticker and ticker not in market_data:
			watchlist.remove(ticker)
			ticker = ticker + '.AX'
			transformed = True
			ticker_link = util.finance_link(ticker, ticker, service)
			print(ticker_orig, "not found. Trying", ticker)
			if ticker in watchlist:
				print(ticker, "already in watchlist")
				duplicate = True
			else:
				watchlist.append(ticker)
				market_data = yahoo.fetch(watchlist)
				print("")
				if ticker in market_data:
					print("found", ticker)
				else:
					watchlist.remove(ticker)
					print(ticker, "not found")
		elif ticker not in market_data:
			watchlist.remove(ticker)
	payload = []
	if market_data:
		for item in market_data:
			flag = util.flag_from_ticker(item)
			item_link = util.finance_link(item, market_data[item]['profile_exchange'], service)
			profile_title = market_data[item]['profile_title']
			if item == ticker and action == 'delete':
				pass
			elif item == ticker and action == 'add': # highlight requested item
				text = webhook.bold(webhook.italic(f"{flag} {profile_title} ({item_link})", service), service)
				payload.append(text)
			else:
				payload.append(f"{flag} {profile_title} ({item_link})")
	def profile_title_sort(e): # disregards markup in sort command
		return re.findall('[A-Z].*', e)
	payload.sort(key=profile_title_sort)
	if action == 'delete':
		if ticker not in market_data:
			payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker, service) + " to remove it")
		else:
			payload.insert(0, f"Ok {user}, I deleted " + webhook.bold(ticker_link, service))
	elif action == 'add':
		if ticker not in market_data:
			payload = ["Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " to add it"]
		elif transformed and duplicate:
			payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " and I'm already tracking " + webhook.bold(ticker_link, service))
		elif transformed:
			payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " so I added " + webhook.bold(ticker_link, service))
		elif duplicate:
			payload.insert(0, f"{user}, I'm already tracking " + webhook.bold(ticker_link, service))
		else:
			payload.insert(0, f"Ok {user}, I added " + webhook.bold(ticker_link, service))
	elif not action and payload:
		payload.insert(0, f"Hi {user}, I'm currently tracking:")
	else:
		payload.append('Watchlist is empty. Try ".watchlist add SYMBOL" to create it')
	util.json_write('finbot_watchlist.json', watchlist, persist=True)
	return payload

def prepare_help(service, botName):
	payload = []
	payload.append(webhook.bold("Tracked securities:", service))
	payload.append(".holdings")
	payload.append(".watchlist [add|del SYMBOL]")

	payload.append(webhook.bold("\nCompany info:", service))
	payload.append('.SYMBOL')
	payload.append(".profile SYMBOL")
	payload.append(".dividend [period|SYMBOL]")
	payload.append(".earnings [period|SYMBOL]")
	payload.append(".marketcap [SYMBOL|bottom|top]")

	payload.append(webhook.bold("\nPrice:", service))
	payload.append(".beta")
	payload.append(".history SYMBOL")
	payload.append(".performance [period] [portfolio]")
	payload.append(".price [percent|SYMBOL] [period]")
	payload.append(".session [percent|SYMBOL]")
	payload.append(".premarket [percent|SYMBOL]")

	payload.append(webhook.bold("\nRisk & Value:", service))
	payload.append(".buy")
	payload.append(".sell")
	payload.append(".pe [SYMBOL|top|bottom]")
	payload.append(".peg [SYMBOL|top|bottom|negative]")
	payload.append(".forwardpe [SYMBOL|top|bottom|negative]")
	payload.append(".shorts [percent|SYMBOL]")

	payload.append(webhook.bold("\nTrades:", service))
	payload.append(".trades [period] [portfolio]")

	payload.append(webhook.bold("\nAlternative syntax:", service))
	if service == 'slack':
		payload.append('<' + botName + '> trades')
	else:
		payload.append(botName + ' price')
	payload.append("")
	payload.append(f"Full help on {util.link('https://github.com/robdevops/finbot', 'GitHub', service)}")
	return payload

def prepare_holdings_payload(portfolioName, service, user):
	payload = []
	portfolios = sharesight.get_portfolios()
	portfoliosLower = {k.lower():v for k,v in portfolios.items()}
	if portfolioName:
		if portfolioName.lower() in portfoliosLower:
			portfolioId = portfoliosLower[portfolioName.lower()]
			tickers = sharesight.get_holdings(portfolioName, portfolioId)
			market_data = yahoo.fetch(tickers)
			print("")
			for item in market_data:
				ticker = market_data[item]['ticker']
				title = market_data[item]['profile_title']
				exchange = market_data[ticker]['profile_exchange']
				ticker_link = util.finance_link(ticker, exchange, service)
				flag = util.flag_from_ticker(ticker)
				payload.append(f"{flag} {title} ({ticker_link})")
			portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
			payload.sort()
			if payload:
				payload.insert(0, webhook.bold("Holdings for " + portfoliosReverseLookup[portfolioId], service))
		else:
			payload = [ f"{user} {portfolioName} portfolio not found. I only know about:" ]
			for item in portfolios:
				payload.append( item )
	else:
		payload = [ f".holdings: Please try again specifying a portfolio:" ]
		for item in portfolios:
			payload.append( item )
	return payload

def prepare_bio_payload(service, user, ticker):
	ticker = ticker_orig = util.transform_to_yahoo(ticker)
	payload = []
	market_data = yahoo.fetch_detail(ticker, 600)

	print("")

	if ticker not in market_data and '.' not in ticker:
		ticker = ticker + '.AX'
		print("trying again with", ticker)
		market_data = yahoo.fetch_detail(ticker, 600)
		print("")
	if ticker not in market_data:
		payload = [ f"{user} 🛑 Beep Boop. I could not find {ticker_orig}" ]
		return payload
	profile_title = market_data[ticker]['profile_title']
	exchange = market_data[ticker]['profile_exchange']
	exchange = exchange.replace('NasdaqCM', 'Nasdaq').replace('NasdaqGS', 'Nasdaq').replace('NYSEArca', 'NYSE')
	ticker_link = util.finance_link(ticker, exchange, service, brief=False)
	profile_title = market_data[ticker]['profile_title']
	swsURL = simplywallst.get_url(ticker, profile_title, exchange)
	swsLink = util.link(swsURL, 'simplywall.st', service)
	macrotrendsURL = 'https://www.google.com/search?q=site:macrotrends.net+' + profile_title + '+PE Ratio+' + ticker.split('.')[0] + '&btnI'
	macrotrendsLink = util.link(macrotrendsURL, 'macrotrends', service)
	gfinanceLink = util.gfinance_link(ticker, exchange, service, brief=True, text='googlefinance')
	yahoo_url = 'https://au.finance.yahoo.com/quote/' + ticker
	yahoo_link = util.link(yahoo_url, 'yahoo', service)

	if 'profile_website' in market_data[ticker]:
		website = website_text = market_data[ticker]['profile_website']
		website_text = util.strip_url(website)
		website = util.link(website, website_text, service)
	if exchange == 'ASX':
		market_url = 'https://www2.asx.com.au/markets/company/' + ticker.split('.')[0]
		shortman_url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0].lower()
		shortman_link = util.link(shortman_url, 'shortman', service)
	elif exchange == 'HKSE':
		market_url = 'https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=' + ticker.split('.')[0] + '&sc_lang=en'
	elif 'Nasdaq' in exchange:
		market_url = 'https://www.nasdaq.com/market-activity/stocks/' + ticker.lower()
	elif exchange == 'NYSE':
		market_url = 'https://www.nyse.com/quote/XNYS:' + ticker
	elif exchange == 'Taiwan':
		exchange = 'TWSE'
		market_url = 'https://mis.twse.com.tw/stock/fibest.jsp?stock=' + ticker.split('.')[0] + '&lang=en_us'
	elif exchange == 'Tokyo':
		exchange = 'JPX'
		market_url = 'https://quote.jpx.co.jp/jpx/template/quote.cgi?F=tmp/e_stock_detail&MKTN=T&QCODE=' + ticker.split('.')[0]
	else:
		market_url = 'https://www.google.com/search?q=stock+exchange+' + exchange + '+' + ticker.split('.')[0] + '&btnI'
	market_link = util.link(market_url, exchange, service)
	location = []
	if 'profile_city' in market_data[ticker]:
		location.append(market_data[ticker]['profile_city'])
	if 'profile_state' in market_data[ticker]:
		location.append(market_data[ticker]['profile_state'])
	if 'profile_country' in market_data[ticker]:
		profile_country = market_data[ticker]['profile_country']
		location.append(profile_country)
	if 'profile_bio' in market_data[ticker]:
		payload.append(util.make_paragraphs(market_data[ticker]['profile_bio']))

	if payload:
		payload.append("")

	if location:
		payload.append(webhook.bold("Location:", service) + " " + ', '.join(location))
	if 'profile_industry' in market_data[ticker] and 'profile_sector' in market_data[ticker]:
		payload.append(webhook.bold("Classification:", service) + f" {market_data[ticker]['profile_industry']}, {market_data[ticker]['profile_sector']}")
	if 'profile_employees' in market_data[ticker]:
		payload.append(webhook.bold("Employees:", service) + f" {market_data[ticker]['profile_employees']:,}")
	if 'profile_website' in market_data[ticker]:
		payload.append(webhook.bold("Website:", service) + f" {website}")
	if 'profile_website' in market_data[ticker] and config_hyperlink:
		if 'NYSE' in exchange or 'Nasdaq' in exchange:
			finvizURL='https://finviz.com/quote.ashx?t=' + ticker
			seekingalphaURL='https://seekingalpha.com/symbol/' + ticker
			finvizLink = util.link(finvizURL, 'finviz', service)
			seekingalphaLink = util.link(seekingalphaURL, 'seekingalpha', service)
			payload.append(webhook.bold("Links:", service) + f" {market_link} | {finvizLink} | {gfinanceLink} | {macrotrendsLink} | {seekingalphaLink} | {swsLink} | {yahoo_link}")
		elif exchange == 'ASX':
			payload.append(webhook.bold("Links:", service) + f" {market_link} | {gfinanceLink} | {shortman_link} | {swsLink} | {yahoo_link}")
		else:
			payload.append(webhook.bold("Links:", service) + f" {market_link} | {gfinanceLink} | {swsLink} | {yahoo_link}")
	if ticker_orig == ticker:
		payload.insert(0, webhook.bold(f"{profile_title} ({ticker_link})", service))
	else:
		payload.insert(0, "Beep Boop. I could not find " + ticker_orig + ", but I found " + ticker_link)
		payload.insert(1, "")
		payload.insert(2, webhook.bold(f"{profile_title} ({ticker_link})", service))
	if len(payload) < 2:
		payload.append("no data found")
	payload = [i[0] for i in groupby(payload)] # de-dupe white space
	return payload

def prepare_stockfinancial_payload(service, user, ticker):
	cashflow = None
	ticker = ticker_orig = util.transform_to_yahoo(ticker)
	now = datetime.datetime.now()
	payload = []
	market_data = yahoo.fetch_detail(ticker, 600)
	print("")
	if ticker not in market_data and '.' not in ticker:
		ticker = ticker + '.AX'
		print("trying again with", ticker)
		market_data = yahoo.fetch_detail(ticker, 600)
		print("")
	if not market_data:
		payload = [ f"{user} 🛑 Beep Boop. I could not find {ticker_orig}" ]
		return payload
	exchange = market_data[ticker]['profile_exchange']
	ticker_link = util.finance_link(ticker, exchange, service, brief=False)
	profile_title = market_data[ticker]['profile_title']
	if 'marketState' in market_data[ticker]:
		marketState = market_data[ticker]['marketState'].rstrip()
		if marketState == 'REGULAR':
			marketStateEmoji = '🟢'
		elif marketState in {'PRE', 'POST'}:
			marketStateEmoji = '🟠'
		else:
			marketStateEmoji = '🔴'
	if 'profile_exchange' in market_data[ticker]:
		profile_exchange = market_data[ticker]['profile_exchange']
		swsURL = simplywallst.get_url(ticker, profile_title, profile_exchange)
		swsLink = util.link(swsURL, 'simplywall.st', service)
		if 'profile_website' in market_data[ticker]:
			website = website_text = market_data[ticker]['profile_website']
			website_text = util.strip_url(website)
			website = util.link(website, website_text, service)
	if 'currency' in market_data[ticker] and 'market_cap' in market_data[ticker]:
		currency = market_data[ticker]['currency']
		market_cap = market_data[ticker]['market_cap']
		market_cap = util.humanUnits(market_cap)
		payload.append(webhook.bold("Mkt cap:", service) + f" {currency} {market_cap}")
	if 'free_cashflow' in market_data[ticker]:
		cashflow = market_data[ticker]['free_cashflow']
	elif 'operating_cashflow' in market_data[ticker]:
		cashflow = market_data[ticker]['operating_cashflow']
	if 'shareholder_equity' in market_data[ticker] and 'total_debt' in market_data[ticker]:
		total_debt = market_data[ticker]['total_debt']
		shareholder_equity = market_data[ticker]['shareholder_equity']
		#debt_equity_ratio = round(total_debt / shareholder_equity * 100)
		if 'profile_industry' in market_data[ticker] and 'total_cash' in market_data[ticker]:
			if 'Bank' not in market_data[ticker]['profile_industry']:
				emoji = ''
				profile_industry = market_data[ticker]['profile_industry']
				total_cash = market_data[ticker]['total_cash']
				net_debt_equity_ratio = round(((total_debt - total_cash) / shareholder_equity * 100))
				if net_debt_equity_ratio > 40:
					emoji = '⚠️ '
				if net_debt_equity_ratio > 0:
					payload.append(webhook.bold("Net debt/equity ratio:", service) + f" {net_debt_equity_ratio}%{emoji}")
	if 'earnings_date' in market_data[ticker]:
		earnings_date = datetime.datetime.fromtimestamp(market_data[ticker]['earnings_date'])
		human_earnings_date = earnings_date.strftime('%b %d')

		if earnings_date > now:
			payload.append(webhook.bold("Earnings date:", service) + f" {human_earnings_date}")
		else:
			print("Skipping past earnings:", ticker, human_earnings_date)
	if 'dividend' in market_data[ticker]:
		dividend = market_data[ticker]['dividend']
		if market_data[ticker]['dividend'] > 0:
			dividend = str(market_data[ticker]['dividend']) + '%'
			payload.append(webhook.bold("Dividend:", service) + f" {dividend}")
			if 'ex_dividend_date' in market_data[ticker]:
				ex_dividend_date = datetime.datetime.fromtimestamp(market_data[ticker]['ex_dividend_date'])
				human_exdate = ex_dividend_date.strftime('%b %d')
				if ex_dividend_date > now:
					payload.append(webhook.bold("Ex-dividend date:", service) + f" {human_exdate}")
				else:
					print("Skipping past ex-dividend:", ticker, human_exdate)
	if cashflow:
		if cashflow < 0:
			payload.append(webhook.bold("Cashflow positive:", service) + " no ⚠️ ")
		else:
			payload.append(webhook.bold("Cashflow positive:", service) + " yes")
	if 'net_income' in market_data[ticker]:
		if market_data[ticker]['net_income'] <= 0:
			payload.append(webhook.bold("Profitable:", service) + " no ⚠️ ")
		else:
			payload.append(webhook.bold("Profitable:", service) + " yes")
	else:
		payload.append(webhook.bold("Profitable:", service) + " unknown ⚠️")

	if payload:
		payload.append("")

	if 'earningsQ' in market_data[ticker]:
		revenueQs = doDelta(market_data[ticker]['revenueQ'])
		earningsQs = doDelta(market_data[ticker]['earningsQ'])
		revenueYs = doDelta(market_data[ticker]['revenueY'])
		earningsYs = doDelta(market_data[ticker]['earningsY'])
		if revenueQs:
			payload.append(f"{revenueQs}  quarterly revenue delta")
		if earningsQs:
			payload.append(f"{earningsQs}  quarterly earnings delta")
		if revenueYs:
			payload.append(f"{revenueYs}  annual revenue delta")
		if earningsYs:
			payload.append(f"{earningsYs}  annual earnings delta")

	if payload:
		payload.append("")

	if 'revenueEstimateY' in market_data[ticker]:
		emoji = ''
		revenueEstimateY = int(round(market_data[ticker]['revenueEstimateY']))
		#revenueAnalysts = market_data[ticker]['revenueAnalysts']
		if revenueEstimateY <= 0:
			emoji = '⚠️ '
			prefix = ''
		else:
			prefix='+'
		payload.append(webhook.bold("Revenue forecast (1Y):", service) + f" {prefix}{revenueEstimateY}% {emoji}")
	if 'earningsEstimateY' in market_data[ticker]:
		emoji = ''
		prefix = ''
		earningsEstimateY = int(round(market_data[ticker]['earningsEstimateY']))
		#earningsAnalysts = market_data[ticker]['earningsAnalysts']
		if earningsEstimateY <= 0:
			emoji = '⚠️ '
		else:
			prefix='+'
		payload.append(webhook.bold("Earnings forecast (1Y):", service) + f" {prefix}{earningsEstimateY}% {emoji}")
	if 'insiderBuy' in market_data[ticker]:
		emoji=''
		insiderBuy = market_data[ticker]['insiderBuy']
		insiderSell = market_data[ticker]['insiderSell']
		insiderBuyValue = market_data[ticker]['insiderBuyValue']
		insiderSellValue = market_data[ticker]['insiderSellValue']
		if insiderBuy > insiderSell:
			action = 'Buy'
			humanValue = util.humanUnits(insiderBuyValue)
			payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue} {emoji}")
		elif insiderBuy < insiderSell:
			emoji = '⚠️ '
			action = 'Sell'
			humanValue = util.humanUnits(insiderSellValue)
			payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue}{emoji}")
	if 'short_percent' in market_data[ticker]:
		emoji=''
		short_percent = market_data[ticker]['short_percent']
		if short_percent > 10:
			emoji = '⚠️ '
		payload.append(webhook.bold("Shorted stock:", service) + f" {short_percent}%{emoji}")
	if 'recommend' in market_data[ticker]:
		recommend = market_data[ticker]['recommend'].replace('_', ' ')
		recommend_index = market_data[ticker]['recommend_index']
		recommend_analysts = market_data[ticker]['recommend_analysts']
		payload.append(webhook.bold("Score:", service) + f" {recommend_index} {recommend} ({recommend_analysts} analysts)")

	if payload:
		payload.append("")

	if 'regularMarketPrice' in market_data[ticker]:
		regularMarketPrice = market_data[ticker]['regularMarketPrice']
		currency = market_data[ticker]['currency']
		prePostMarketPrice = None
		marketState = market_data[ticker]['marketState']
		if marketState != 'REGULAR' and 'prePostMarketPrice' in market_data[ticker]:
			prePostMarketPrice = market_data[ticker]['prePostMarketPrice']
			payload.append(webhook.bold("Price:", service) + f" {currency} {regularMarketPrice:,.2f} ({prePostMarketPrice:,.2f} after hrs)")
		else:
			payload.append(webhook.bold("Price:", service) + f" {currency} {regularMarketPrice:,.2f}" )
	if 'price_to_earnings_trailing' in market_data[ticker]:
		trailingPe = str(int(round(market_data[ticker]['price_to_earnings_trailing'])))
	else:
		trailingPe = 'N/A ⚠️ '
	if 'net_income' in market_data[ticker] and market_data[ticker]['net_income'] > 0:
		payload.append(webhook.bold("Trailing P/E:", service) + f" {trailingPe}")
	if 'netIncomeToCommon' in market_data[ticker] and market_data[ticker]['netIncomeToCommon'] > 0:
		currentPe = round(market_data[ticker]['regularMarketPrice'] / (market_data[ticker]['netIncomeToCommon'] / market_data[ticker]['sharesOutstanding']))
		payload.append(webhook.bold("Current P/E:", service) + f" {currentPe}")
	if 'price_to_earnings_forward' in market_data[ticker]:
		forwardPe = int(round(market_data[ticker]['price_to_earnings_forward']))
		emoji=''
		if 'profile_industry' in market_data[ticker]:
			profile_industry = market_data[ticker]['profile_industry']
			if 'Software' in profile_industry and forwardPe > 100:
				emoji = '⚠️ '
			elif 'Software' not in profile_industry and forwardPe > 30:
				emoji = '⚠️ '
			if 'price_to_earnings_trailing' in market_data[ticker] and forwardPe > int(trailingPe):
				emoji = '⚠️ '
		payload.append(webhook.bold("Forward P/E:", service) + f" {str(forwardPe)} {emoji}")
	if 'price_to_earnings_peg' in market_data[ticker]:
		peg = round(market_data[ticker]['price_to_earnings_peg'], 1)
		payload.append(webhook.bold("PEG ratio:", service) + f" {str(peg)}")
	if 'price_to_sales' in market_data[ticker]:
		price_to_sales = round(market_data[ticker]['price_to_sales'], 1)
		payload.append(webhook.bold("PS ratio:", service) + f" {str(price_to_sales)}")

	if payload:
		payload.append("")

	price_history, graph = yahoo.price_history(ticker)
	for interval in ('5Y', '1Y', '1M', '1D'):
	   if interval in price_history:
		   percent = price_history[interval]
		   emoji = util.get_emoji(percent)
		   payload.append(f"{emoji} {webhook.bold(interval + ':', service)} {percent}%")
	percent_change = market_data[ticker]['percent_change']
	marketState = market_data[ticker]['marketState']
	if marketState != 'REGULAR' and 'percent_change_premarket' in market_data[ticker]:
		percent_change_premarket = market_data[ticker]['percent_change_premarket']
		emoji = util.get_emoji(percent_change_premarket)
		payload.append(f"{emoji} {webhook.bold('Pre-market:', service)} {percent_change_premarket:,}%")
	elif marketState != 'REGULAR' and 'percent_change_postmarket' in market_data[ticker]:
		percent_change_postmarket = market_data[ticker]['percent_change_postmarket']
		emoji = util.get_emoji(percent_change_postmarket)
		payload.append(f"{emoji} {webhook.bold('Post-market:', service)} {percent_change_postmarket:,}%")

	if 'profile_website' in market_data[ticker] and config_hyperlinkFooter and config_hyperlink:
		footer = f"{website} | {swsLink}"
		if payload and footer:
			payload.append("")
		payload.append(footer)
	if ticker_orig == ticker:
		payload.insert(0, f"{profile_title} ({ticker_link}) {marketStateEmoji}")
	else:
		payload.insert(0, f"I could not find {ticker_orig} but I found {ticker_link}:")
		payload.insert(1, "")
		payload.insert(2, f"{profile_title} ({ticker_link}) {marketStateEmoji}")
	payload = [i[0] for i in groupby(payload)] # de-dupe white space
	if len(payload) < 2:
		payload.append("no data found")
	return payload

def prepare_marketcap_payload(service, action='top', length=15):
	def last_col(e):
		try:
			return float(e.split()[-1])
		except ValueError:
			pass
	payload_staging = []
	tickers = util.get_holdings_and_watchlist()
	market_data = yahoo.fetch(tickers)
	for ticker in market_data:
		try:
			market_cap = market_data[ticker]['market_cap']
		except:
			print(ticker, "no market cap", file=sys.stderr)
			continue
		market_cap_readable = util.humanUnits(market_cap)
		title = market_data[ticker]['profile_title']
		link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
		flag = util.flag_from_ticker(ticker)
		payload_staging.append(f"{flag} {title} ({link}) mkt cap: {market_cap_readable} {market_cap}")
	if payload_staging:
		payload_staging.sort(key=last_col)
		if action == 'top':
			payload_staging.reverse()
		payload_staging = payload_staging[:length]
		payload = []
		for line in payload_staging: # drop no longer needed sort key
			words = line.split()
			payload.append(' '.join(words[:-1]))
		payload.insert(0, f"{webhook.bold(f'{action.title()} {length} tracked stocks by market cap', service)}")
	return payload

def prepare_rating_payload(service, action, length=15):
		def score_col(e):
			return (float(e.split()[-3]), int(e.split()[-2].removeprefix('(')))
		payload = []
		tickers = util.get_holdings_and_watchlist()
		market_data = {}
		for ticker in tickers:
			try:
				market_data = market_data | yahoo.fetch_detail(ticker)
			except TypeError:
				pass
		for ticker in market_data:
			if 'recommend' in market_data[ticker]:
				recommend = market_data[ticker]['recommend'].replace('_', ' ')
				recommend_index = market_data[ticker]['recommend_index']
				recommend_analysts = market_data[ticker]['recommend_analysts']
				if recommend_analysts > 1:
					profile_title = market_data[ticker]['profile_title']
					ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
					flag = util.flag_from_ticker(ticker)
					if action == 'buy' and 'buy' in recommend:
							payload.append(f"{flag} {profile_title} ({ticker_link}) {recommend_index} ({recommend_analysts} analysts)")
					elif action == 'sell' and (recommend == 'sell' or recommend == 'underperform'):
							payload.append(f"{flag} {profile_title} ({ticker_link}) {recommend_index} ({recommend_analysts} analysts)")
		payload.sort(key=score_col)
		payload = payload[:length]
		if payload:
			message = f"Top {length} analyst {action} ratings for tracked stocks"
			payload.insert(0, f"{webhook.bold(message, service)}")
		return payload

def prepare_value_payload(service, action='pe', ticker_select=None, length=15):
		def last_col(e):
			return float(e.split()[-1])
		payload = []
		if ticker_select:
			tickers = [ticker_select]
		else:
			tickers = util.get_holdings_and_watchlist()
		market_data = yahoo.fetch(tickers)
		for ticker in market_data:
			try:
				if action == 'pe' or action == 'bottom pe':
					ratio = market_data[ticker]['price_to_earnings_trailing']
				elif action == 'forward pe' or action == 'bottom forward pe':
					if not ticker_select and market_data[ticker]['price_to_earnings_forward'] < 0:
						continue
					ratio = market_data[ticker]['price_to_earnings_forward']
				elif action == 'negative forward pe':
					if not ticker_select and market_data[ticker]['price_to_earnings_forward'] >= 0:
						continue
					ratio = market_data[ticker]['price_to_earnings_forward']
				elif action == 'peg' or action == 'bottom peg':
					market_data = market_data | yahoo.fetch_detail(ticker)
					if not ticker_select and market_data[ticker]['price_to_earnings_peg'] < 0:
						continue
					ratio = market_data[ticker]['price_to_earnings_peg']
				elif action == 'negative peg':
					market_data = market_data | yahoo.fetch_detail(ticker)
					if not ticker_select and market_data[ticker]['price_to_earnings_peg'] >= 0:
						continue
					ratio = market_data[ticker]['price_to_earnings_peg']
			except KeyError:
				print(ticker, action, "value not found", file=sys.stderr)
				continue
			profile_title = market_data[ticker]['profile_title']
			ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
			flag = util.flag_from_ticker(ticker)
			payload.append(f"{flag} {profile_title} ({ticker_link}) {ratio}")
		payload.sort(key=last_col)
		if not ticker_select:
			heading_type = "Bottom" if 'bottom' in action else "Top"
			heading_trail = action.replace('bottom ', '')
			if 'bottom' in action:
				payload.reverse()
			payload = payload[:length]
			if payload:
				payload.insert(0, f"{webhook.bold(f'{heading_type} {length} tracked stocks by {heading_trail} ratio', service)}")
		return payload
