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
import shutil
import lib.telegram as telegram
from lib.config import *
from lib import util
from http.cookies import SimpleCookie
from pathlib import Path

def getCookie(maxAge=1209600): # 14 days
	# we must always cache this, as crumb must match cookie
	cacheFile = "finbot_yahoo_cookie.json"
	cache = util.json_load(cacheFile)
	if cache:
		cacheFileAge = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(config_cache_dir + '/' + cacheFile))
		#ttl = datetime.timedelta(seconds=cache[0][2]) - cacheFileAge
		ttl = datetime.timedelta(seconds=maxAge) - cacheFileAge
		if ttl > datetime.timedelta(seconds=30):
			cookie = cache[0][0] + '=' + cache[0][1]
			print("cache hit:", cacheFile, "TTL:", util.td_to_human(ttl), file=sys.stderr) if debug else None
			return cookie
		else:
			print("cache miss:", cacheFile, file=sys.stderr) if debug else None

	# request
	cookie = None
	headers = {'User-Agent': 'Mozilla/5.0'}
	url = 'https://fc.yahoo.com/' # 404, but that is ok because cookie is in response header
	try:
		r = requests.get(url, headers=headers)
	except Exception as e:
		print(e, file=sys.stderr)
	if r.status_code not in {200, 404}:
		print(r.status_code, r.text.rstrip(), "returned by", url, file=sys.stderr)

	# parse
	if not 'set-cookie' in r.headers:
		print("Failed to obtain Yahoo auth cookie. Returning fallback cookie", file=sys.stderr)
		fallback='A3=d=AQABBBtR5mYCENFZu2wCWkA5iGGkSRGvRgkFEgEBAQGi52bwZtxM0iMA_eMAAA&S=AQAAAtG8VhxZN7aXopfvLNObtpE;'
		return fallback
	else:
		cookie = SimpleCookie()
		cookie.load(r.headers['Set-Cookie'])
		cookielist = []
		for name, morsel in cookie.items():
			value = morsel.value
			max_age = int(morsel.get('max-age'))
			cookielist.append([name, value, max_age])
		cookie = cookielist[0][0] + '=' + str(cookielist[0][1])
		#if config_cache:
		util.json_write(cacheFile, cookielist)
		print("Got new cookie:", cookie, file=sys.stderr)
		rmCrumb() # we must invalidate the non-matching crumb
		return cookie

def getCrumb(seconds=1209600): # 14 days
	cookie = getCookie()
	if config_cache:
		cacheFile = "finbot_yahoo_crumb.json"
		cache = util.read_cache(cacheFile, seconds)
		if cache:
			return cache
	headers = {'User-Agent': 'Mozilla/5.0', 'Cookie': cookie}
	yahoo_urls = ['https://query2.finance.yahoo.com/v1/test/getcrumb']
	yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
	for url in yahoo_urls:
		try:
			r = requests.get(url, headers=headers, timeout=config_http_timeout)
		except Exception as e:
			print(e, file=sys.stderr)
		else:
			if r.status_code != 200:
				print(r.status_code, r.text.rstrip(), "returned by", url, file=sys.stderr)
				continue
			break
	else:
		print("Exhausted Yahoo API attempts. Returning fallback crumb", file=sys.stderr)
		return 'jkQEU8yLqxs'
	if config_cache:
		util.json_write(cacheFile, r.text)
	print("Got new crumb:", r.text.rstrip(), file=sys.stderr)
	return r.text

def rmCrumb():
	cacheFile = "finbot_yahoo_crumb.json"
	cacheFile = config_cache_dir + "/" + cacheFile
	dst = Path(cacheFile + '.old')
	src = Path(cacheFile)
	if src.is_file():
		dst.unlink(missing_ok=True)
		shutil.move(src, dst)

def fetch(tickers):
	# DO NOT CACHE MORE THAN 5 mins
	if not len(tickers):
		print("no tickers provided to yahoo.fetch()", file=sys.stderr)
		return None
	tickers = sorted(set(tickers)) # de-dupe
	tickers_sha256 = hashlib.sha256(str.encode("_".join(tickers))).hexdigest()
	if config_cache:
		cacheFile = "finbot_yahoo_" + tickers_sha256 + '.json'
		cache = util.read_cache(cacheFile, 300)
		if cache:
			return cache
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
		util.json_write(cacheFile, yahoo_output)
	return yahoo_output

def fetch_detail(ticker, seconds=config_cache_seconds):
	now = datetime.datetime.now()
	local_market_data = {}
	cookie = getCookie()
	crumb = getCrumb()
	base_url = 'https://query2.finance.yahoo.com/v10/finance/quoteSummary/'
	#headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
	headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie}
	local_market_data[ticker] = dict()
	cache = None
	if config_cache:
		cacheFile = "finbot_yahoo_detail_" + ticker + '.json'
		cache = util.read_cache(cacheFile, seconds)
	if cache:
		print('.', sep=' ', end='', flush=True)
		data = cache
	if not config_cache or not cache:
		print('↓', sep=' ', end='', flush=True)
		yahoo_urls = [base_url + ticker + '?modules=calendarEvents,defaultKeyStatistics,balanceSheetHistoryQuarterly,financialData,summaryProfile,summaryDetail,price,earnings,earningsTrend,insiderTransactions' + '&crumb=' + crumb]
		yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
		for url in yahoo_urls:
			print(url, file=sys.stderr) if debug else None
			try:
				r = requests.get(url, headers=headers, timeout=config_http_timeout)
			except Exception as e:
				print(e, file=sys.stderr)
			else:
				if r.status_code != 200:
					print('x', sep=' ', end='', flush=True, file=sys.stderr)
					print(r.text.rstrip(), file=sys.stderr) if debug else None
					continue
				break
		else:
			print(ticker + '†', sep=' ', end='', flush=True)
			return {} # catches some delisted stocks like "DRNA"
		data = r.json()
		if config_cache:
			util.json_write(cacheFile, data)
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

	data = fetch_chart_json(ticker)
	df = chart_json_to_df(data)
	stock = chart_json_to_stock_basics(data)
	tz = pytz.timezone(stock.get('exchangeTimezoneName'))
	regularMarketTime = datetime.datetime.fromtimestamp(stock.get('regularMarketTime')).astimezone(tz).date()

	# temporarily disabled while testing new method
	# inject latest
	#if df['Date'].iloc[-1] == regularMarketTime:
	#	if df['Close'].iloc[-1] != regularMarketPrice:
	#		print("Updating", df['Close'].iloc[-1], "to", regularMarketPrice)
	#		df['Close'].loc[-1] = regularMarketPrice
	#else:
	#	print (ticker, "inserting", regularMarketTime, "after", df['Date'].iloc[-1], file=sys.stderr)
	#	previous_close = df['Close'].iloc[-1]
	#	df.loc[len(df)] = {'Timestamp' now, 'Close': regularMarketPrice, 'Open': previous_close, 'High': None, 'Low': None, 'Volume': None, 'Time': None, 'Date': regularMarketTime}
	#df = df[df.Close.notnull()]
	##df.sort_values(by='Date', inplace = True)
	#df.reset_index(drop=True, inplace=True)

	if days:
		seek_date = now - datetime.timedelta(days = days)
		seek_dt = seek_date.date()
		mask = df['Date'] >= seek_dt
		df = df.loc[mask]
		past_price = df[df.loc[mask]['Date'] >= seek_dt]['Close'].iloc[0]
		df.reset_index(drop=True, inplace=True)
		percent = (stock.get('regularMarketPrice') - past_price) / past_price * 100
		percent_dict[days] = round(percent, 2)
	else:
		default_price = df['Close'].iloc[0]
		default_percent = round((stock.get('regularMarketPrice') - default_price) / default_price * 100)
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
					#percent_dict['1D'] = market_data[ticker]['percent_change']
					percent_dict['1D'] = default_percent
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
			percent = (stock.get('regularMarketPrice') - past_price) / past_price * 100
			percent_dict[period] = round(percent)
	if not graph or (days and days < 2):
		return percent_dict, None
	company_name = util.transform_title(stock.get('longName', ''))
	price = stock.get('regularMarketPrice', '')
	caption = []
	if days:
		title_days = min(days, max_days)
		percent = percent_dict.get(days, '')
		title = f"{company_name} ({ticker}) {title_days} days {percent:,}% Last: {price}"
		caption.append(title)
	else:
		caption.extend(f"{k}: {v:,}%" for k, v in percent_dict.items())
		label = "Max" if "Max" in percent_dict else "10Y"
		percent = percent_dict.get(label, '')
		title = f"{company_name} ({ticker}) {label} {percent:,}% Last: {price}"
	caption = '\n'.join(caption)
	image_cache_file = "finbot_graph_" + ticker + "_" + str(days) + ".png"
	image_cache = util.read_binary_cache(image_cache_file, seconds)
	if config_cache and image_cache and graphCache:
		image_data = image_cache
	else:
		buf = util.graph(df, title, stock.get('currency'))
		#bytesio_to_file(buf, 'temp.png')
		buf.seek(0)
		image_data = buf
		util.write_binary_cache(image_cache_file, image_data)
		buf.seek(0)
	return percent_dict, image_data

def fetch_chart_json(ticker, days=3665, seconds=config_cache_seconds):
	now = datetime.datetime.now()
	if config_cache:
		cacheFile = "finbot_yahoo_history_" + ticker + ".json"
		cache = util.read_cache(cacheFile, seconds)
		if cache:
			return cache
	cookie = getCookie()
	crumb = getCrumb()
	start =  str(int((now - datetime.timedelta(days=days)).timestamp()))
	end = str(int(now.timestamp()))
	interval = '1d'
	url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
	url = url + ticker + '?period1=' + start + '&period2=' + end + '&interval=' + interval
	url = url + '&crumb=' + crumb
	headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
	print("Fetching", url, file=sys.stderr) if debug else None
	try:
		r = requests.get(url, headers=headers, timeout=config_http_timeout)
	except Exception as e:
		errorstring = f"General failure for {ticker} at {url}: {e}"
		print(errorstring, file=sys.stderr)
		return errorstring, None
	if r.status_code == 200:
		print('↓', sep=' ', end='', flush=True)
	else:
		errorstring=f"{r.status_code} error for {ticker} at {url}"
		print(errorstring, file=sys.stderr)
		return errorstring, None
	if config_cache:
		util.json_write(cacheFile, r.json())
	return r.json()

def chart_json_to_df(chart_json):
	result = chart_json['chart']['result'][0]
	timestamp = result['timestamp']
	quote_data = result['indicators']['quote'][0]

	# Create a dictionary with 'Timestamp' and all available quote data
	data = {'Timestamp': timestamp}
	data.update(quote_data)

	# Create DataFrame
	df = pd.DataFrame(data)

	#timestamp = [datetime.datetime.fromtimestamp(ts) for ts in timestamp]
	df['Date'] = pd.to_datetime(df['Timestamp'], unit='s').dt.date


	# Rename columns to capitalize first letter
	df.columns = [col.capitalize() for col in df.columns]

	print(df, file=sys.stderr) if debug else None
	return df

def chart_json_to_stock_basics(chart_json):
	"""
	extracts stock basics from chart json to save calling fetch()
	{
		"currency": "USD",
		"symbol": "AAPL",
		"exchangeName": "NMS",
		"fullExchangeName": "NasdaqGS",
		"instrumentType": "EQUITY",
		"firstTradeDate": 345479400,
		"regularMarketTime": 1726862403,
		"hasPrePostMarketData": true,
		"gmtoffset": -14400,
		"timezone": "EDT",
		"exchangeTimezoneName": "America/New_York",
		"regularMarketPrice": 228.2,
		"fiftyTwoWeekHigh": 233.09,
		"fiftyTwoWeekLow": 227.62,
		"regularMarketDayHigh": 233.09,
		"regularMarketDayLow": 227.62,
		"regularMarketVolume": 287134033,
		"longName": "Apple Inc.",
		"shortName": "Apple Inc.",
		"chartPreviousClose": 224.53,
		"priceHint": 2,
	}
	"""
	for a in chart_json.values():
		for b in a.values():
			if isinstance(b, list):
				for c in b:
					if 'currency' in c['meta']:
						return c['meta']

def historic_high(ticker):
	data = fetch_chart_json(ticker)
	df = chart_json_to_df(data)
	df = df[df.High.notnull()]
	df.drop(df.index[:1], inplace=True)
	df.reset_index(drop=True, inplace=True)
	highrow = df.iloc[df['High'].argmax()]
	lowrow = df.iloc[df['Low'].argmin()]
	if debug:
		print(ticker, "High", highrow['Date'], round(highrow['High'], 2), file=sys.stderr)
		print(ticker, "Low", lowrow['Date'], round(lowrow['Low'], 2), file=sys.stderr)
	return round(highrow['High'], 2), round(lowrow['Low'], 2)

