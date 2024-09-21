import datetime
from dateutil.relativedelta import relativedelta
import hashlib
import io
import json
import requests
import pandas as pd
import pytz
from pandas.tseries.offsets import BDay as businessday
import sys
import lib.telegram as telegram
from lib.config import *
from lib import util
from http.cookies import SimpleCookie

def getCookie():
	# cache read
	cacheFile = "finbot_yahoo_cookie.json"
	cache = util.json_load(cacheFile)
	if config_cache and cache:
		cacheFileAge = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(config_cache_dir + '/' + cacheFile))
		if cacheFileAge < datetime.timedelta(seconds=cache[0][2]):
			cookie = cache[0][0] + '=' + cache[0][1]
			return cookie

	# request
	cookie = None
	user_agent_key = "User-Agent"
	user_agent_value = "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.137 Safari/605.1.15"
	headers = {user_agent_key: user_agent_value}
	url = 'https://fc.yahoo.com/' # 404, but that is ok because cookie is in response header
	try:
		r = requests.get(url, headers=headers)
	except Exception as e:
		print(e, file=sys.stderr)
	if r.status_code not in {200, 404}:
		print(r.status_code, r.text, "returned by", url, file=sys.stderr)

	# parse
	if 'set-cookie' in r.headers:
		cookie = SimpleCookie()
		cookie.load(r.headers['Set-Cookie'])
		cookielist = []
		for name, morsel in cookie.items():
			value = morsel.value
			max_age = int(morsel.get('max-age'))
			cookielist.append([name, value, max_age])
		cookie = cookielist[0][0] + '=' + str(cookielist[0][1])
		if config_cache:
			util.json_write(cacheFile, cookielist)
		return cookie
	else:
		print("Failed to obtain Yahoo auth cookie. Returning fallback cookie", file=sys.stderr)
		fallback='A3=d=AQABBBtR5mYCENFZu2wCWkA5iGGkSRGvRgkFEgEBAQGi52bwZtxM0iMA_eMAAA&S=AQAAAtG8VhxZN7aXopfvLNObtpE;'
		return fallback

def getCrumb(seconds=2592000): # 1 month
	cookie = getCookie()
	cache_file = "finbot_yahoo_crumb.json"
	cache = util.read_cache(cache_file, seconds)
	if config_cache and cache:
		return cache
	headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.137 Safari/605.1.15', 'Cookie': cookie}
	yahoo_urls = ['https://query2.finance.yahoo.com/v1/test/getcrumb']
	yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
	for url in yahoo_urls:
		try:
			r = requests.get(url, headers=headers, timeout=config_http_timeout)
		except Exception as e:
			print(e, file=sys.stderr)
		else:
			if r.status_code != 200:
				print(r.status_code, r.text, "returned by", url, file=sys.stderr)
				continue
			break
	else:
		print("Exhausted Yahoo API attempts. Returning fallback crumb", file=sys.stderr)
		return 'jkQEU8yLqxs'
	if config_cache:
		util.json_write(cache_file, r.text)
	return r.text

def fetch(tickers):
	# DO NOT CACHE MORE THAN 5 mins
	tickers = sorted(set(tickers)) # de-dupe
	tickers_sha256 = hashlib.sha256(str.encode("_".join(tickers))).hexdigest()
	cache_file = "finbot_yahoo_" + tickers_sha256 + '.json'
	cacheData = util.read_cache(cache_file, 300)
	if config_cache and cacheData:
		return cacheData
	now = datetime.datetime.now().timestamp()
	yahoo_output = {}
	cookie = getCookie()
	crumb = getCrumb()
	yahoo_urls = ['https://query2.finance.yahoo.com/v7/finance/quote?crumb=' + crumb + '&symbols=' + ','.join(tickers)]
	yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
	headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0', 'Cookie': cookie}
	for url in yahoo_urls:
		try:
			r = requests.get(url, headers=headers, timeout=config_http_timeout)
		except Exception as e:
			print(e, "at", url, file=sys.stderr)
		else:
			if r.status_code != 200:
				print(r.status_code, "at", url, file=sys.stderr)
				continue
			break
	else:
		print("Exhausted Yahoo API attempts. Giving up", file=sys.stderr)
		sys.exit(1)
	data = r.json()
	data = data['quoteResponse']
	if data['result'] is None or data['error'] is not None:
		print(f"{tickers}†", sep=' ', end='', flush=True, file=sys.stderr)
		return None
	for item in data['result']:
		ticker = item['symbol']
		try:
			profile_title = item['longName']
		except (KeyError, IndexError):
			try:
				profile_title = item['shortName']
			except (KeyError, IndexError):
				continue
		try:
			percent_change = 0
			percent_change = round(float(item['regularMarketChangePercent']), 2)
		except (KeyError, IndexError):
			pass
		try:
			currency = item['currency']
		except (KeyError, IndexError):
			pass
		try:
			regularMarketPrice = item['regularMarketPrice']
		except (KeyError, IndexError):
			continue
		try:
			dividend = round(float(item['trailingAnnualDividendRate']), 1)
		except (KeyError, IndexError):
			dividend = float(0)
		profile_title = util.transform_title(profile_title)
		yahoo_output[ticker] = { 'profile_title': profile_title, 'ticker': ticker, 'percent_change': percent_change, 'dividend': dividend, 'currency': currency, 'regularMarketPrice': regularMarketPrice }
		# optional fields
		try:
			percent_change_premarket = item['preMarketChangePercent']
		except (KeyError, IndexError):
			pass
		else:
			yahoo_output[ticker]["percent_change_premarket"] = round(percent_change_premarket, 2)
		try:
			quoteType = item['quoteType']
		except (KeyError, IndexError):
			pass
		else:
			yahoo_output[ticker]["quoteType"] = quoteType
		try:
			percent_change_postmarket = item['postMarketChangePercent']
		except (KeyError, IndexError):
			pass
		else:
			yahoo_output[ticker]["percent_change_postmarket"] = round(percent_change_postmarket, 2)
		try:
			yahoo_output[ticker]["market_cap"] = round(float(item['marketCap']))
		except (KeyError, IndexError):
			pass
		try:
			yahoo_output[ticker]["price_to_earnings_forward"] = round(item['forwardPE'])
		except:
			pass
		try:
			yahoo_output[ticker]["price_to_earnings_trailing"] = round(item['trailingPE'])
		except:
			pass
		try:
			yahoo_output[ticker]["marketState"] = item['marketState']
		except:
			pass
		try:
			yahoo_output[ticker]["profile_exchange"] = item['fullExchangeName']
		except:
			pass
		try:
			yahoo_output[ticker]["exchangeTimezoneName"] = item['exchangeTimezoneName']
		except:
			pass
		try:
			yahoo_output[ticker]["regularMarketTime"] = item['regularMarketTime']
		except:
			pass
		try:
			yahoo_output[ticker]["financialCurrency"] = item['financialCurrency']
		except:
			pass
		try:
			earningsTimestamp = item['earningsTimestamp']
			earningsTimestampStart = item['earningsTimestampStart']
			earningsTimestampEnd = item['earningsTimestampEnd']
			if earningsTimestamp > now:
				yahoo_output[ticker]["earnings_date"] = earningsTimestamp
			elif earningsTimestampStart > now:
				yahoo_output[ticker]["earnings_date"] = earningsTimestampStart
			elif earningsTimestampEnd > now:
				yahoo_output[ticker]["earnings_date"] = earningsTimestampEnd
			else:
				yahoo_output[ticker]["earnings_date"] = earningsTimestamp
		except (KeyError, IndexError):
			pass
		try:
			yahoo_output[ticker]["regularMarketPreviousClose"] = item['regularMarketPreviousClose']
		except (KeyError, IndexError):
			pass
		try:
			yahoo_output[ticker]["fiftyTwoWeekHigh"] = item['fiftyTwoWeekHigh']
		except (KeyError, IndexError):
			pass
		try:
			fiftyTwoWeekLowTemp = item['fiftyTwoWeekLow']
			if not fiftyTwoWeekLowTemp <= 0:
				yahoo_output[ticker]["fiftyTwoWeekLow"] = fiftyTwoWeekLowTemp
		except (KeyError, IndexError):
			pass
	if config_cache:
		util.json_write(cache_file, yahoo_output)
	return yahoo_output

def fetch_detail(ticker, seconds=config_cache_seconds):
	now = datetime.datetime.now()
	local_market_data = {}
	cookie = getCookie()
	crumb = getCrumb()
	base_url = 'https://query2.finance.yahoo.com/v10/finance/quoteSummary/'
	#headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
	headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7', 'Cookie': cookie}
	local_market_data[ticker] = dict()
	cache_file = "finbot_yahoo_detail_" + ticker + '.json'
	cacheData = util.read_cache(cache_file, seconds)
	if config_cache and cacheData:
		print('.', sep=' ', end='', flush=True)
		data = cacheData
	else:
		print('↓', sep=' ', end='', flush=True)
		yahoo_urls = [base_url + ticker + '?modules=calendarEvents,defaultKeyStatistics,balanceSheetHistoryQuarterly,financialData,summaryProfile,summaryDetail,price,earnings,earningsTrend,insiderTransactions' + '&crumb=' + crumb]
		yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
		for url in yahoo_urls:
			if debug:
				print(url)
			try:
				r = requests.get(url, headers=headers, timeout=config_http_timeout)
			except Exception as e:
				print(e, file=sys.stderr)
			else:
				if r.status_code != 200:
					print('x', sep=' ', end='', flush=True, file=sys.stderr)
					if debug:
						print(r.text)
					continue
				break
		else:
			print(ticker + '†', sep=' ', end='', flush=True)
			return {} # catches some delisted stocks like "DRNA"
		data = r.json()
		if config_cache:
			util.json_write(cache_file, data)
		# might be interesting:
			# majorHoldersBreakdown
			# netSharePurchaseActivity
			# upgradeDowngradeHistory
	try:
		profile_title = data['quoteSummary']['result'][0]['price']['longName']
	except (KeyError, IndexError, ValueError):
		print(ticker + 'x', sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	if profile_title is None:
		try:
			profile_title = data['quoteSummary']['result'][0]['price']['shortName']
		except (KeyError, IndexError, ValueError):
			print(ticker + '†', sep=' ', end='', flush=True, file=sys.stderr)
			return {}
	if profile_title is None: # catches some delisted stocks like "DUB"
		print(f"{ticker}†", sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	profile_title = util.transform_title(profile_title)
	local_market_data[ticker]['profile_title'] = profile_title
	try:
		profile_bio = data['quoteSummary']['result'][0]['summaryProfile']['longBusinessSummary']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_bio'] = profile_bio
	try:
		profile_city = data['quoteSummary']['result'][0]['summaryProfile']['city']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_city'] = profile_city
	try:
		profile_country = data['quoteSummary']['result'][0]['summaryProfile']['country']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_country'] = profile_country
	try:
		profile_state = data['quoteSummary']['result'][0]['summaryProfile']['state']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_state'] = profile_state
	try:
		profile_industry = data['quoteSummary']['result'][0]['summaryProfile']['industry']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_industry'] = profile_industry
	try:
		profile_sector = data['quoteSummary']['result'][0]['summaryProfile']['sector']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_sector'] = profile_sector
	try:
		profile_employees = data['quoteSummary']['result'][0]['summaryProfile']['fullTimeEmployees']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_employees'] = profile_employees
	try:
		profile_website = data['quoteSummary']['result'][0]['summaryProfile']['website']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_website'] = profile_website
	try:
		beta = data['quoteSummary']['result'][0]['summaryDetail']['beta']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['beta'] = beta
	try:
		currency = data['quoteSummary']['result'][0]['summaryDetail']['currency']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['currency'] = currency
	try:
		market_cap = int(data['quoteSummary']['result'][0]['summaryDetail']['marketCap']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['market_cap'] = market_cap
	try:
		dividend = data['quoteSummary']['result'][0]['summaryDetail']['dividendYield']['raw']
	except (KeyError, IndexError):
		pass
	else:
		dividend = dividend * 100
		local_market_data[ticker]['dividend'] = round(dividend, 1)
	try:
		price_to_earnings_trailing = int(data['quoteSummary']['result'][0]['summaryDetail']['trailingPE']['raw'])
	except (KeyError, IndexError, ValueError):
		pass
	else:
		local_market_data[ticker]['price_to_earnings_trailing'] = price_to_earnings_trailing
	try:
		price_to_earnings_forward = data['quoteSummary']['result'][0]['summaryDetail']['forwardPE']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['price_to_earnings_forward'] = price_to_earnings_forward
	try:
		ex_dividend_date = data['quoteSummary']['result'][0]['calendarEvents']['exDividendDate']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['ex_dividend_date'] = ex_dividend_date
	try:
		dividend_date = data['quoteSummary']['result'][0]['calendarEvents']['DividendDate']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['dividend_date'] = dividend_date
	try:
		earnings_date = data['quoteSummary']['result'][0]['calendarEvents']['earnings']['earningsDate'][0]['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['earnings_date'] = earnings_date
	try:
		percent_change = data['quoteSummary']['result'][0]['price']['regularMarketChangePercent']['raw']
	except (KeyError, IndexError):
		pass
	else:
		percent_change = percent_change * 100
		local_market_data[ticker]['percent_change'] = round(percent_change, 1)
	try:
		percent_change_year = float(data['quoteSummary']['result'][0]['summaryDetail']['52WeekChange']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		percent_change_year = percent_change_year * 100
		local_market_data[ticker]['percent_change_year'] = round(percent_change_year, 1)
	try:
		percent_change_premarket = float(data['quoteSummary']['result'][0]['price']['preMarketChangePercent']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		percent_change_premarket = percent_change_premarket * 100
		local_market_data[ticker]['percent_change_premarket'] = round(percent_change_premarket, 1)
	try:
		percent_change_postmarket = float(data['quoteSummary']['result'][0]['price']['postMarketChangePercent']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		percent_change_postmarket = percent_change_postmarket * 100
		local_market_data[ticker]['percent_change_postmarket'] = round(percent_change_postmarket, 1)
	try:
		profile_exchange = data['quoteSummary']['result'][0]['price']['exchangeName']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profile_exchange'] = profile_exchange
	try:
		marketState = data['quoteSummary']['result'][0]['price']['marketState']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['marketState'] = marketState
	try:
		quoteType = data['quoteSummary']['result'][0]['price']['quoteType']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['quoteType'] = quoteType
	try:
		regularMarketPrice = data['quoteSummary']['result'][0]['price']['regularMarketPrice']['raw']
	except (KeyError, IndexError):
		return {} # catches junk
	else:
		local_market_data[ticker]['regularMarketPrice'] = regularMarketPrice
	try:
		regularMarketPreviousClose = data['quoteSummary']['result'][0]['price']['regularMarketPreviousClose']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['regularMarketPreviousClose'] = regularMarketPreviousClose
	try:
		fiftyTwoWeekHigh = data['quoteSummary']['result'][0]['price']['fiftyTwoWeekHigh']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['fiftyTwoWeekHigh'] = fiftyTwoWeekHigh
	try:
		fiftyTwoWeekLowTemp = data['quoteSummary']['result'][0]['price']['fiftyTwoWeekLow']['raw']
		if not fiftyTwoWeekLowTemp <= 0:
			fiftyTwoWeekLow = fiftyTwoWeekLowTemp
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['fiftyTwoWeekLow'] = fiftyTwoWeekLow
	try:
		preMarketPrice = float(data['quoteSummary']['result'][0]['price']['preMarketPrice']['raw'])
	except (KeyError, IndexError, ValueError):
		pass
	else:
		local_market_data[ticker]['prePostMarketPrice'] = preMarketPrice
	try:
		postMarketPrice = float(data['quoteSummary']['result'][0]['price']['postMarketPrice']['raw'])
	except (KeyError, IndexError, ValueError):
		pass
	else:
		local_market_data[ticker]['prePostMarketPrice'] = postMarketPrice
	try:
		netIncomeToCommon = data['quoteSummary']['result'][0]['defaultKeyStatistics']['netIncomeToCommon']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['netIncomeToCommon'] = netIncomeToCommon
	try:
		sharesOutstanding = float(data['quoteSummary']['result'][0]['defaultKeyStatistics']['sharesOutstanding']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['sharesOutstanding'] = sharesOutstanding
	try:
		short_percent = float(data['quoteSummary']['result'][0]['defaultKeyStatistics']['shortPercentOfFloat']['raw'])
	except (KeyError, IndexError):
		pass
	else:
		short_percent = short_percent * 100
		local_market_data[ticker]['short_percent'] = round(short_percent, 1)
	try:
		price_to_book = data['quoteSummary']['result'][0]['defaultKeyStatistics']['priceToBook']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['price_to_book'] = price_to_book
	try:
		earnings_growth_q = data['quoteSummary']['result'][0]['defaultKeyStatistics']['earningsQuarterlyGrowth']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['earnings_growth_q'] = earnings_growth_q
	try:
		price_to_earnings_peg = data['quoteSummary']['result'][0]['defaultKeyStatistics']['pegRatio']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['price_to_earnings_peg'] = price_to_earnings_peg
	try:
		profit_margin = data['quoteSummary']['result'][0]['defaultKeyStatistics']['profitMargins']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['profit_margin'] = profit_margin
	try:
		if data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['fmt'] is not None:
			net_income = data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['raw']
		elif data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-2]['earnings']['fmt'] is not None:
			net_income = data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-2]['earnings']['raw']
		else:
			raise TypeError('quarterly earnings is null')
	except (KeyError, IndexError, TypeError):
		pass
	else:
		local_market_data[ticker]['net_income'] = net_income
	try:
		shareholder_equity = data['quoteSummary']['result'][0]['balanceSheetHistoryQuarterly']['balanceSheetStatements'][0]['totalStockholderEquity']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['shareholder_equity'] = shareholder_equity
	try:
		total_debt = data['quoteSummary']['result'][0]['financialData']['totalDebt']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['total_debt'] = total_debt
	try:
		total_cash = data['quoteSummary']['result'][0]['financialData']['totalCash']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['total_cash'] = total_cash
	try:
		free_cashflow = data['quoteSummary']['result'][0]['financialData']['freeCashflow']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['free_cashflow'] = free_cashflow
	try:
		operating_cashflow = data['quoteSummary']['result'][0]['financialData']['operatingCashflow']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['operating_cashflow'] = operating_cashflow
	try:
		financialCurrency = data['quoteSummary']['result'][0]['financialData']['financialCurrency']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['financialCurrency'] = financialCurrency
	try:
		recommend = data['quoteSummary']['result'][0]['financialData']['recommendationKey']
		recommend_index = data['quoteSummary']['result'][0]['financialData']['recommendationMean']['raw']
		recommend_analysts = data['quoteSummary']['result'][0]['financialData']['numberOfAnalystOpinions']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['recommend'] = recommend
		local_market_data[ticker]['recommend_index'] = recommend_index
		local_market_data[ticker]['recommend_analysts'] = recommend_analysts
	try:
		price_to_sales = data['quoteSummary']['result'][0]['summaryDetail']['priceToSalesTrailing12Months']['raw']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['price_to_sales'] = price_to_sales
	try:
		currency = data['quoteSummary']['result'][0]['summaryDetail']['currency']
	except (KeyError, IndexError):
		pass
	else:
		local_market_data[ticker]['currency'] = currency
	try:
		data['quoteSummary']['result'][0]['earningsTrend']['trend'][0]['growth']['raw']
	except (KeyError, IndexError):
		pass
	else:
		for item in data['quoteSummary']['result'][0]['earningsTrend']['trend']:
			if item['period'] == '+1y':
				try:
					revenueEstimateY = item['revenueEstimate']['growth']['raw']
					earningsEstimateY = item['earningsEstimate']['growth']['raw']
					revenueAnalysts = item['revenueEstimate']['numberOfAnalysts']['raw']
					earningsAnalysts = item['earningsEstimate']['numberOfAnalysts']['raw']
				except KeyError:
					break
		try:
			earningsEstimateY = earningsEstimateY * 100
			revenueEstimateY = revenueEstimateY * 100
			local_market_data[ticker]['revenueEstimateY'] = round(revenueEstimateY, 2)
			local_market_data[ticker]['earningsEstimateY'] = round(earningsEstimateY, 2)
			local_market_data[ticker]['revenueAnalysts'] = revenueAnalysts
			local_market_data[ticker]['earningsAnalysts'] = earningsAnalysts
		except UnboundLocalError:
			print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
	try:
		data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][0]['revenue']['raw']
	except (KeyError, IndexError):
		print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
	else:
		earningsQ = []
		revenueQ = []
		earningsY = []
		revenueY = []
		for item in data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly']:
			if item['earnings']['fmt'] is None: # bad data
				#if len(earningsQ): # may fix weirdness in dodelta()
				earningsQ.append(None)
				#if len(revenueQ):
				revenueQ.append(None)
			else:
				earningsQ.append(item['earnings']['raw'])
				revenueQ.append(item['revenue']['raw'])
		for item in data['quoteSummary']['result'][0]['earnings']['financialsChart']['yearly']:
			earningsY.append(item['earnings']['raw'])
			revenueY.append(item['revenue']['raw'])
		local_market_data[ticker]['earningsQ'] = earningsQ
		local_market_data[ticker]['revenueQ'] = revenueQ
		local_market_data[ticker]['earningsY'] = earningsY
		local_market_data[ticker]['revenueY'] = revenueY
	try:
		data['quoteSummary']['result'][0]['insiderTransactions']['transactions'][0]['startDate']['raw']
	except (KeyError, IndexError):
		pass
	else:
		buyTotal = 0
		buyValue = 0
		sellTotal = 0
		sellValue = 0
		for item in data['quoteSummary']['result'][0]['insiderTransactions']['transactions']:
			dt_startDate = datetime.datetime.fromtimestamp(item['startDate']['raw'])
			if dt_startDate > now - datetime.timedelta(days=90):
				if 'Buy' in item['transactionText']:
					buyTotal = buyTotal + item['shares']['raw']
					buyValue = buyValue + item['value']['raw']
				if 'Sale' in item['transactionText']:
					sellTotal = sellTotal + item['shares']['raw']
					sellValue = sellValue + item['value']['raw']
		local_market_data[ticker]['insiderBuy'] = buyTotal
		local_market_data[ticker]['insiderSell'] = sellTotal
		local_market_data[ticker]['insiderBuyValue'] = buyValue
		local_market_data[ticker]['insiderSellValue'] = sellValue

	local_market_data[ticker] = dict(sorted(local_market_data[ticker].items()))
	return local_market_data

def price_history(ticker, days=None, seconds=config_cache_seconds, graph=config_graph, graphCache=True):
	percent_dict = {}
	price = []
	image_data = None
	max_days = 3655 # 10 years + buffer
	now = datetime.datetime.now()
	interval = ('10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '5D', '1D')

	data = fetch_history(ticker, days=max_days)
	df = json_to_df(data)

	# inject latest
	market_data = fetch([ticker])
	tz = pytz.timezone(market_data[ticker]['exchangeTimezoneName'])
	regularMarketTime = datetime.datetime.fromtimestamp(market_data[ticker]['regularMarketTime']).astimezone(tz).date()
	regularMarketPrice = market_data[ticker]['regularMarketPrice']
	if df['Date'].iloc[-1] == regularMarketTime:
		if df['Close'].iloc[-1] != regularMarketPrice:
			print("Updating", df['Close'].iloc[-1], "to", regularMarketPrice)
			df['Close'].loc[-1] = regularMarketPrice
	else:
		print (ticker, "inserting", regularMarketTime, "after", df['Date'].iloc[-1], file=sys.stderr)
		previous_close = df['Close'].iloc[-1]
		df.loc[len(df)] = {'Date': regularMarketTime, 'Open': previous_close, 'High': None, 'Low': None, 'Close': regularMarketPrice, 'Adj Close': regularMarketPrice, 'Volume': None}
	df = df[df.Close.notnull()]
	#df.sort_values(by='Date', inplace = True)
	df.reset_index(drop=True, inplace=True)

	if days:
		seek_date = now - datetime.timedelta(days = days)
		seek_dt = seek_date.date()
		mask = df['Date'] >= seek_dt
		df = df.loc[mask]
		past_price = df[df.loc[mask]['Date'] >= seek_dt]['Close'].iloc[0]
		df.reset_index(drop=True, inplace=True)
		percent = (regularMarketPrice - past_price) / past_price * 100
		percent_dict[days] = round(percent, 2)
	else:
		default_price = df['Close'].iloc[0]
		default_percent = round((regularMarketPrice - default_price) / default_price * 100)
		for period in interval:
			# try to align with google finance
			if period == 'YTD':
				seek_dt = now.replace(day=1, month=1).date()
				try:
					past_price = df[df['Date'] >= seek_dt]['Close'].iloc[0]
				except IndexError:
					percent_dict['Max'] = default_percent
					continue
			elif period == '1D':
					percent_dict['1D'] = market_data[ticker]['percent_change']
			elif period == '5D':
				#seek_date = now - datetime.timedelta(days = 5)
				seek_date = now - businessday(5)
				seek_dt = seek_date.date()
				try:
					past_price = df[df['Date'] <= seek_dt]['Open'].iloc[-1]
				except IndexError:
					percent_dict['Max'] = default_percent
					continue
			elif period.endswith('M'):
				months = int(period.removesuffix('M'))
				seek_date = now - relativedelta(months=months)
				seek_dt = seek_date.date()
				try:
					past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
				except IndexError:
					percent_dict['Max'] = default_percent
					continue
			elif period.endswith('Y'):
				years = int(period.removesuffix('Y'))
				seek_date = now - relativedelta(years=years)
				seek_dt = seek_date.date()
				try:
					past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
				except IndexError:
					percent_dict['Max'] = default_percent
					continue
			else:
				seek_date = now - datetime.timedelta(days = int(period.removesuffix('D')))
				seek_dt = seek_date.date()
				#print(df[df['Date'] <= seek_dt].tail(1))
				try:
					past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
				except IndexError:
					percent_dict['Max'] = default_percent
					continue
			percent = (regularMarketPrice - past_price) / past_price * 100
			percent_dict[period] = round(percent)
	if graph:
		if days and days < 2:
			return percent_dict, None
		caption = []
		profile_title = market_data[ticker]['profile_title']
		if days:
			title_days = days
			if days > max_days:
				title_days = max_days
			title = profile_title + " (" + ticker + ") " + str(title_days) + " days " + str(percent_dict[days]) + '%'
			caption.append(title)
		else:
			for k,v in percent_dict.items():
				caption.append(str(k) + ": " + str(v) + '%')
			if 'Max' in percent_dict:
				title = profile_title + " (" + ticker + ") Max " + str(percent_dict['Max']) + '%'
			else:
				title = profile_title + " (" + ticker + ") 10Y " + str(percent_dict['10Y']) + '%'
		caption = '\n'.join(caption)
		image_cache_file = "finbot_graph_" + ticker + "_" + str(days) + ".png"
		image_cache = util.read_binary_cache(image_cache_file, seconds)
		if config_cache and image_cache and graphCache:
			image_data = image_cache
		else:
			buf = util.graph(df, title, market_data[ticker])
			#bytesio_to_file(buf, 'temp.png')
			buf.seek(0)
			image_data = buf
			util.write_binary_cache(image_cache_file, image_data)
			buf.seek(0)
	if config_cache:
		util.json_write(cache_file, csv)
	return percent_dict, image_data

def fetch_history(ticker, days=3665):
	now = datetime.datetime.now()
	cache_file = "finbot_yahoo_history_" + ticker + ".json"
	cache = util.read_cache(cache_file, seconds)
	if config_cache and cache:
		return cache
	else:
		cookie = getCookie()
		crumb = getCrumb()
		start =  str(int((now - datetime.timedelta(days=days)).timestamp()))
		end = str(int(now.timestamp()))
		interval = '1d'
		url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
		url = url + ticker + '?period1=' + start + '&period2=' + end + '&interval=' + interval
		url = url + '&crumb=' + crumb
		headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
		try:
			r = requests.get(url, headers=headers, timeout=config_http_timeout)
		except:
			errorstring = f"General failure for {ticker} at {url}"
			print(errorstring, file=sys.stderr)
			return errorstring, None
		if r.status_code == 200:
			print('↓', sep=' ', end='', flush=True)
		else:
			errorstring=f"{r.status_code} error for {ticker} at {url}"
			print(errorstring, file=sys.stderr)
			return errorstring, None
		return r.json()

def json_to_df(json):
	data = [json['chart']['result'][0]['timestamp']] + list(json['chart']['result'][0]['indicators']['quote'][0].values())
	df = pd.DataFrame(
		{'Timestamp': data[0], 'Close': data[1], 'Open': data[2], 'High': data[3], 'Low': data[4], 'Volume': data[5]})
	df['Time'] = pd.to_datetime(df['Timestamp'], unit='s')
	df['Date'] = df['Time'].apply(lambda x: x.strftime('%Y-%m-%d'))
	df['Date'] = pd.to_datetime(df['Date']).dt.date
	return df

def historic_high(ticker, market_data, days=3653, seconds=config_cache_seconds):
	#pd.set_option("display.precision", 8)
	interval = '1d'
	image_data = None
	percent_dict = {}
	tz = pytz.timezone(market_data[ticker]['exchangeTimezoneName'])
	regularMarketTime = datetime.datetime.fromtimestamp(market_data[ticker]['regularMarketTime']).astimezone(tz).date()
	regularMarketPrice = market_data[ticker]['regularMarketPrice']
	now = datetime.datetime.now()
	cache_file = "finbot_yahoo_ath_" + ticker + "_" + interval + ".json"
	cache = util.read_cache(cache_file, seconds)
	if config_cache and cache:
		csv = cache
	else:
		cookie = getCookie()
		crumb = getCrumb()
		start =  str(int((now - datetime.timedelta(days=days)).timestamp()))
		end = str(int(now.timestamp()))
		url = 'https://query1.finance.yahoo.com/v7/finance/download/' + ticker
		url = url + '?period1=' + start + '&period2=' + end + '&interval=' + interval + '&events=history&includeAdjustedClose=true'
		url = url + '&crumb=' + crumb
		if debug:
			print(url)
		headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
		try:
			r = requests.get(url, headers=headers, timeout=config_http_timeout)
		except:
			print("Failure fetching", url, file=sys.stderr)
			return None
		if r.status_code == 200:
			print('↓', sep=' ', end='', flush=True)
		else:
			print(ticker, r.status_code, "error communicating with", url, file=sys.stderr)
			return None
		csv = r.content.decode('utf-8')
	#df = pd.read_csv(io.StringIO(csv), float_precision=None)
	df = pd.read_csv(io.StringIO(csv))
	df['Date'] = pd.to_datetime(df['Date']).dt.date
	df = df[df.High.notnull()]
	df.drop(df.index[:1], inplace=True)
	df.reset_index(drop=True, inplace=True)
	if config_cache:
		util.json_write(cache_file, csv)
	highrow = df.iloc[df['High'].argmax()]
	lowrow = df.iloc[df['Low'].argmin()]
	if debug:
		print(ticker, "High", highrow['Date'], round(highrow['High'], 2))
		print(ticker, "Low", lowrow['Date'], round(lowrow['Low'], 2))
	return round(highrow['High'], 2), round(lowrow['Low'], 2)

