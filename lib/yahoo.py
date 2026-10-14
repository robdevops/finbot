import concurrent.futures
import datetime
from dateutil.relativedelta import relativedelta
import hashlib
import requests
import threading
import zoneinfo
import sys
from lib.config import *
from lib import util
from http.cookies import SimpleCookie
from pathlib import Path

_auth = threading.RLock() # Yahoo's cookie and crumb are renewed by one thread at a time: two at once could cache a crumb for the cookie the other replaced

def getCookie(maxAge=1209600): # 14 days
	# we must always cache this, as crumb must match cookie
	with _auth:
		cacheFile = "finbot_yahoo_cookie.json"
		cache = util.json_load(cacheFile)
		if cache:
			#ttl = datetime.timedelta(seconds=cache[0][2] - util.cache_age(cacheFile))
			ttl = datetime.timedelta(seconds=maxAge - util.cache_age(cacheFile))
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
			r = requests.Response() # empty: falls through to the fallback cookie below
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
	with _auth:
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
	"""Set the cached crumb aside (as .old): it belongs to the cookie being replaced."""
	crumb = Path(util.cache_path("finbot_yahoo_crumb.json"))
	if crumb.is_file():
		crumb.replace(crumb.with_name(crumb.name + '.old'))

QUOTE_FIELDS = ( # the optional fields of a v7 quote: (key, Yahoo's name, conversion)
	('percent_change_premarket', 'preMarketChangePercent', lambda v: round(v, 2)),
	('quoteType', 'quoteType', None),
	('percent_change_postmarket', 'postMarketChangePercent', lambda v: round(v, 2)),
	('market_cap', 'marketCap', lambda v: round(float(v))),
	('marketState', 'marketState', None),
	('profile_exchange', 'fullExchangeName', None),
	('exchangeTimezoneName', 'exchangeTimezoneName', None),
	('regularMarketTime', 'regularMarketTime', None),
	('financialCurrency', 'financialCurrency', None),
	('regularMarketPreviousClose', 'regularMarketPreviousClose', None),
	('fiftyTwoWeekHigh', 'fiftyTwoWeekHigh', None),
)

def fetch(tickers):
	# DO NOT CACHE MORE THAN 5 mins
	if not len(tickers):
		print("no tickers provided to yahoo.fetch()", file=sys.stderr)
		return {}
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
		raise RuntimeError("Yahoo API unavailable")
	data = r.json()
	data = data['quoteResponse']
	if data['result'] is None or data['error'] is not None:
		print(f"{tickers}†", sep=' ', end='', flush=True, file=sys.stderr)
		return {} # callers iterate the result
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
		quote = yahoo_output[ticker]
		for key, field, convert in QUOTE_FIELDS:
			if field in item:
				quote[key] = convert(item[field]) if convert else item[field]
		for key, field in (('price_to_earnings_forward', 'forwardPE'), ('price_to_earnings_trailing', 'trailingPE')):
			try:
				quote[key] = round(item[field])
			except:
				pass
		try:
			earningsTimestamp = item['earningsTimestamp']
			earningsTimestampStart = item['earningsTimestampStart']
			earningsTimestampEnd = item['earningsTimestampEnd']
			if earningsTimestamp > now:
				quote["earnings_date"] = earningsTimestamp
			elif earningsTimestampStart > now:
				quote["earnings_date"] = earningsTimestampStart
			elif earningsTimestampEnd > now:
				quote["earnings_date"] = earningsTimestampEnd
			else:
				quote["earnings_date"] = earningsTimestamp
		except (KeyError, IndexError):
			pass
		try:
			fiftyTwoWeekLowTemp = item['fiftyTwoWeekLow']
			if not fiftyTwoWeekLowTemp <= 0:
				quote["fiftyTwoWeekLow"] = fiftyTwoWeekLowTemp
		except (KeyError, IndexError):
			pass
	if config_cache:
		util.json_write(cacheFile, yahoo_output)
	return yahoo_output

def _percent(fraction):
	"""Yahoo's fraction as a percentage, to one decimal: 0.01234 -> 1.2."""
	return round(fraction * 100, 1)

def _float_percent(fraction):
	return _percent(float(fraction))

DETAIL_FIELDS = ( # (key, path in the quoteSummary result[, conversion[, another error that means "not there"]]), applied in this order
	('profile_bio', ('summaryProfile', 'longBusinessSummary')),
	('profile_city', ('summaryProfile', 'city')),
	('profile_country', ('summaryProfile', 'country')),
	('profile_state', ('summaryProfile', 'state')),
	('profile_industry', ('summaryProfile', 'industry')),
	('profile_sector', ('summaryProfile', 'sector')),
	('profile_employees', ('summaryProfile', 'fullTimeEmployees')),
	('profile_website', ('summaryProfile', 'website')),
	('beta', ('summaryDetail', 'beta', 'raw')),
	('currency', ('summaryDetail', 'currency')),
	('market_cap', ('summaryDetail', 'marketCap', 'raw'), int),
	('dividend', ('summaryDetail', 'dividendYield', 'raw'), _percent),
	('price_to_earnings_trailing', ('summaryDetail', 'trailingPE', 'raw'), int, ValueError),
	('price_to_earnings_forward', ('summaryDetail', 'forwardPE', 'raw')),
	('ex_dividend_date', ('calendarEvents', 'exDividendDate', 'raw')),
	('dividend_date', ('calendarEvents', 'DividendDate', 'raw')),
	('earnings_date', ('calendarEvents', 'earnings', 'earningsDate', 0, 'raw')),
	('percent_change', ('price', 'regularMarketChangePercent', 'raw'), _percent),
	('percent_change_year', ('summaryDetail', '52WeekChange', 'raw'), _float_percent),
	('percent_change_premarket', ('price', 'preMarketChangePercent', 'raw'), _float_percent),
	('percent_change_postmarket', ('price', 'postMarketChangePercent', 'raw'), _float_percent),
	('profile_exchange', ('price', 'exchangeName')),
	('marketState', ('price', 'marketState')),
	('quoteType', ('price', 'quoteType')),
	('regularMarketPrice', ('price', 'regularMarketPrice', 'raw')), # required: an answer without it is junk
	('regularMarketPreviousClose', ('price', 'regularMarketPreviousClose', 'raw')),
	('fiftyTwoWeekHigh', ('price', 'fiftyTwoWeekHigh', 'raw')),
	('prePostMarketPrice', ('price', 'preMarketPrice', 'raw'), float, ValueError),
	('prePostMarketPrice', ('price', 'postMarketPrice', 'raw'), float, ValueError), # the after-hours price, when there is one, wins
	('netIncomeToCommon', ('defaultKeyStatistics', 'netIncomeToCommon', 'raw')),
	('sharesOutstanding', ('defaultKeyStatistics', 'sharesOutstanding', 'raw'), float),
	('short_percent', ('defaultKeyStatistics', 'shortPercentOfFloat', 'raw'), _float_percent),
	('price_to_book', ('defaultKeyStatistics', 'priceToBook', 'raw')),
	('earnings_growth_q', ('defaultKeyStatistics', 'earningsQuarterlyGrowth', 'raw')),
	('price_to_earnings_peg', ('defaultKeyStatistics', 'pegRatio', 'raw')),
	('profit_margin', ('defaultKeyStatistics', 'profitMargins', 'raw')),
	('shareholder_equity', ('balanceSheetHistoryQuarterly', 'balanceSheetStatements', 0, 'totalStockholderEquity', 'raw')),
	('total_debt', ('financialData', 'totalDebt', 'raw')),
	('total_cash', ('financialData', 'totalCash', 'raw')),
	('free_cashflow', ('financialData', 'freeCashflow', 'raw')),
	('operating_cashflow', ('financialData', 'operatingCashflow', 'raw')),
	('financialCurrency', ('financialData', 'financialCurrency')),
	('price_to_sales', ('summaryDetail', 'priceToSalesTrailing12Months', 'raw')),
)

def fetch_detail(ticker, seconds=UNSET):
	if seconds is UNSET:
		seconds = config_cache_seconds
	now = datetime.datetime.now()
	cookie = getCookie()
	crumb = getCrumb()
	base_url = 'https://query2.finance.yahoo.com/v10/finance/quoteSummary/'
	#headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
	headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie}
	cacheFile = "finbot_yahoo_detail_" + ticker + '.json'
	data = util.read_cache(cacheFile, seconds) if config_cache else None
	if data:
		print('.', sep=' ', end='', flush=True)
	else:
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
		result = data['quoteSummary']['result'][0]
		profile_title = result['price']['longName']
	except (KeyError, IndexError, ValueError, TypeError): # TypeError: Yahoo answers result=null for unknown symbols
		print(ticker + 'x', sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	if profile_title is None:
		try:
			profile_title = result['price']['shortName']
		except (KeyError, IndexError, ValueError):
			print(ticker + '†', sep=' ', end='', flush=True, file=sys.stderr)
			return {}
	if profile_title is None: # catches some delisted stocks like "DUB"
		print(f"{ticker}†", sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	detail = {'profile_title': util.transform_title(profile_title)}
	for key, path, *how in DETAIL_FIELDS:
		try:
			value = result
			for step in path:
				value = value[step]
			detail[key] = how[0](value) if how else value
		except (KeyError, IndexError, *how[1:]):
			if key == 'regularMarketPrice':
				return {} # catches junk
	try:
		fiftyTwoWeekLowTemp = result['price']['fiftyTwoWeekLow']['raw']
		if not fiftyTwoWeekLowTemp <= 0:
			fiftyTwoWeekLow = fiftyTwoWeekLowTemp
	except (KeyError, IndexError):
		pass
	else:
		detail['fiftyTwoWeekLow'] = fiftyTwoWeekLow
	try:
		quarterly = result['earnings']['financialsChart']['quarterly']
		if quarterly[-1]['earnings']['fmt'] is not None:
			net_income = quarterly[-1]['earnings']['raw']
		elif quarterly[-2]['earnings']['fmt'] is not None:
			net_income = quarterly[-2]['earnings']['raw']
		else:
			raise TypeError('quarterly earnings is null')
	except (KeyError, IndexError, TypeError):
		pass
	else:
		detail['net_income'] = net_income
	try:
		recommend = result['financialData']['recommendationKey']
		recommend_index = result['financialData']['recommendationMean']['raw']
		recommend_analysts = result['financialData']['numberOfAnalystOpinions']['raw']
	except (KeyError, IndexError):
		pass
	else:
		detail.update(recommend=recommend, recommend_index=recommend_index, recommend_analysts=recommend_analysts)
	try:
		result['earningsTrend']['trend'][0]['growth']['raw']
	except (KeyError, IndexError):
		pass
	else:
		for item in result['earningsTrend']['trend']:
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
			detail['revenueEstimateY'] = round(revenueEstimateY, 2)
			detail['earningsEstimateY'] = round(earningsEstimateY, 2)
			detail['revenueAnalysts'] = revenueAnalysts
			detail['earningsAnalysts'] = earningsAnalysts
		except UnboundLocalError:
			print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
	try:
		result['earnings']['financialsChart']['quarterly'][0]['revenue']['raw']
	except (KeyError, IndexError):
		print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
	else:
		earningsQ = []
		revenueQ = []
		earningsY = []
		revenueY = []
		for item in result['earnings']['financialsChart']['quarterly']:
			if item['earnings']['fmt'] is None: # bad data
				#if len(earningsQ): # may fix weirdness in dodelta()
				earningsQ.append(None)
				#if len(revenueQ):
				revenueQ.append(None)
			else:
				earningsQ.append(item['earnings']['raw'])
				revenueQ.append(item['revenue']['raw'])
		for item in result['earnings']['financialsChart']['yearly']:
			earningsY.append(item['earnings']['raw'])
			revenueY.append(item['revenue']['raw'])
		detail['earningsQ'] = earningsQ
		detail['revenueQ'] = revenueQ
		detail['earningsY'] = earningsY
		detail['revenueY'] = revenueY
	try:
		result['insiderTransactions']['transactions'][0]['startDate']['raw']
	except (KeyError, IndexError):
		pass
	else:
		buyTotal = 0
		buyValue = 0
		sellTotal = 0
		sellValue = 0
		for item in result['insiderTransactions']['transactions']:
			dt_startDate = datetime.datetime.fromtimestamp(item['startDate']['raw'])
			if dt_startDate > now - datetime.timedelta(days=90):
				if 'Buy' in item['transactionText']:
					buyTotal = buyTotal + item['shares']['raw']
					buyValue = buyValue + item['value']['raw']
				if 'Sale' in item['transactionText']:
					sellTotal = sellTotal + item['shares']['raw']
					sellValue = sellValue + item['value']['raw']
		detail['insiderBuy'] = buyTotal
		detail['insiderSell'] = sellTotal
		detail['insiderBuyValue'] = buyValue
		detail['insiderSellValue'] = sellValue

	return {ticker: dict(sorted(detail.items()))}

def price_history(ticker, days=None, seconds=UNSET, graph=UNSET, graphCache=True):
	"""({period: percent change}, chart image or None). If the chart cannot be fetched: (error string, None), which the callers
	check for so that one failed ticker does not take a whole report down."""
	if graph is UNSET:
		graph = config_graph
	if seconds is UNSET:
		seconds = config_cache_seconds
	import pandas as pd
	from pandas.tseries.offsets import BDay as businessday
	percent_dict = {}
	max_days = 3655 # 10 years + buffer
	now = datetime.datetime.now()
	interval = ('10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '5D', '1D')

	data = fetch_chart_json(ticker)
	if isinstance(data, tuple): # (error string, None)
		return data
	df = chart_json_to_df(data)
	stock = chart_json_to_stock_basics(data)
	tz = zoneinfo.ZoneInfo(stock.get('exchangeTimezoneName'))
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
		df = df[df['Date'] >= (now - datetime.timedelta(days=days)).date()].reset_index(drop=True)
		past_price = df['Close'].iloc[0]
		percent = (stock.get('regularMarketPrice') - past_price) / past_price * 100
		percent_dict[days] = round(percent, 2)
	else:
		default_price = df['Close'].iloc[0]
		default_percent = round((stock.get('regularMarketPrice') - default_price) / default_price * 100)
		for period in interval:
			if period == '1D':
				# against the previous session's close: the last close dated before the latest bar, in the exchange's time zone
				sessions = pd.to_datetime(df['Timestamp'], unit='s', utc=True).dt.tz_convert(tz).dt.date
				earlier = df[(sessions < sessions.iloc[-1]) & df['Close'].notnull()]
				if earlier.empty:
					continue
				past_price = earlier['Close'].iloc[-1]
			else: # try to align with google finance
				try:
					if period == 'YTD':
						past_price = df[df['Date'] >= now.replace(day=1, month=1).date()]['Close'].iloc[0]
					elif period == '5D':
						past_price = df[df['Date'] <= (now - businessday(5)).date()]['Open'].iloc[-1]
					else: # 10Y to 1M, 7D: the last close on or before the day that long ago
						n, unit = int(period[:-1]), period[-1]
						ago = relativedelta(years=n) if unit == 'Y' else relativedelta(months=n) if unit == 'M' else datetime.timedelta(days=n)
						past_price = df[df['Date'] <= (now - ago).date()]['Close'].iloc[-1]
				except IndexError: # the history does not go back that far
					percent_dict['Max'] = default_percent
					continue
			percent = (stock.get('regularMarketPrice') - past_price) / past_price * 100
			percent_dict[period] = round(percent)
	if not graph or (days and days < 2):
		return percent_dict, None
	company_name = util.transform_title(stock.get('longName', ''))
	price = stock.get('regularMarketPrice', '')
	if days:
		title = f"{company_name} ({ticker}) {min(days, max_days)} days {util.signed_percent(percent_dict.get(days, ''))} Last: {price}"
	else:
		label = "Max" if "Max" in percent_dict else "10Y"
		title = f"{company_name} ({ticker}) {label} {util.signed_percent(percent_dict.get(label, ''))} Last: {price}"
	image_cache_file = "finbot_graph_" + ticker + "_" + str(days) + ".png"
	image_cache = util.read_binary_cache(image_cache_file, seconds)
	if config_cache and image_cache and graphCache:
		return percent_dict, image_cache
	image = util.graph(df, title, stock.get('currency'))
	util.write_binary_cache(image_cache_file, image)
	return percent_dict, image

def price_series(ticker):
	"""Daily closes for a ticker via the same fetch/parse path as price_history(): (name, exchange, pandas Series indexed by datetime)."""
	import pandas as pd
	data = fetch_chart_json(ticker, full=True)
	if isinstance(data, tuple): # fetch_chart_json returns (errorstring, None) on failure
		raise RuntimeError(data[0])
	df = chart_json_to_df(data)
	stock = chart_json_to_stock_basics(data) or {}
	df = df[df['Close'].notnull()]
	if df.empty:
		raise RuntimeError(f"no price history for {ticker}")
	series = pd.Series(df['Close'].astype(float).values, index=pd.to_datetime(df['Date'].astype(str)), name=ticker)
	name = util.transform_title(stock.get('longName') or stock.get('shortName') or ticker)
	return name, stock.get('fullExchangeName') or stock.get('exchangeName') or '', series

def fetch_each(get, tickers, workers=8):
	"""get(ticker) for every ticker, `workers` at a time so their waits overlap: [its result, or the exception it raised], in order."""
	def one(ticker):
		try:
			return get(ticker)
		except Exception as e:
			return e
	with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
		return list(executor.map(one, tickers))

def prefetch_history(tickers, workers=8):
	"""Warm the price-history cache for many tickers at once, so the per-ticker lookups that follow are cache hits."""
	tickers = list(tickers)
	for ticker, result in zip(tickers, fetch_each(fetch_chart_json, tickers, workers)):
		if isinstance(result, Exception):
			print("prefetch failed for", ticker, result, file=sys.stderr)

def fetch_chart_json(ticker, days=3665, seconds=UNSET, full=False):
	"""full=True requests Yahoo's entire history (cached separately) instead of the last `days`."""
	if seconds is UNSET:
		seconds = config_cache_seconds
	now = datetime.datetime.now()
	if config_cache:
		cacheFile = "finbot_yahoo_history_" + ticker + ("_max" if full else "") + ".json"
		cache = util.read_cache(cacheFile, seconds)
		if cache:
			return cache
	crumb = getCrumb() # renews the cookie too, when due
	start = '0' if full else str(int((now - datetime.timedelta(days=days)).timestamp()))
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
	data = r.json()
	if config_cache:
		util.json_write(cacheFile, data)
	return data

def chart_json_to_df(chart_json):
	import pandas as pd
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
	if df.empty: # e.g. total-return indices such as ^SPTTGD carry no High/Low data
		return None
	highrow = df.iloc[df['High'].argmax()]
	lowrow = df.iloc[df['Low'].argmin()]
	if debug:
		print(ticker, "High", highrow['Date'], round(highrow['High'], 2), file=sys.stderr)
		print(ticker, "Low", lowrow['Date'], round(lowrow['Low'], 2), file=sys.stderr)
	return round(highrow['High'], 2), round(lowrow['Low'], 2)

