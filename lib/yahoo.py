import concurrent.futures
import datetime
from dateutil.relativedelta import relativedelta
import hashlib
import requests
import threading
import zoneinfo
import sys
from lib import config
from lib import cache
from lib import net
from lib import formats
from lib import render
from http.cookies import SimpleCookie
from pathlib import Path

_auth = threading.RLock() # Yahoo's cookie and crumb are renewed by one thread at a time: two at once could cache a crumb for the cookie the other replaced
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def getCookie(maxAge=1209600): # 14 days
	# we must always cache this, as crumb must match cookie
	with _auth:
		cacheFile = "finbot_yahoo_cookie.json"
		cached = cache.read(cacheFile, maxAge - 30) # renewed 30 seconds before it expires
		if cached:
			return cached[0][0] + '=' + cached[0][1]
		url = 'https://fc.yahoo.com/' # 404, but that is ok because cookie is in response header
		try:
			r = net.get(url, headers=HEADERS, timeout=config.prefs.http_timeout)
		except Exception as e:
			print(net.redact(e), file=sys.stderr)
			r = requests.Response() # empty: falls through to the fallback cookie below
		if r.status_code not in {200, 404}:
			print(r.status_code, "returned by", url, file=sys.stderr)
		if 'set-cookie' not in r.headers:
			print("Failed to obtain Yahoo auth cookie. Returning fallback cookie", file=sys.stderr)
			return 'A3=d=AQABBBtR5mYCENFZu2wCWkA5iGGkSRGvRgkFEgEBAQGi52bwZtxM0iMA_eMAAA&S=AQAAAtG8VhxZN7aXopfvLNObtpE;'
		cookie = SimpleCookie()
		cookie.load(r.headers['Set-Cookie'])
		cookielist = [[name, morsel.value, int(morsel.get('max-age') or 0)] for name, morsel in cookie.items()]
		cache.write(cacheFile, cookielist)
		print("Got a new Yahoo cookie", file=sys.stderr)
		rmCrumb() # we must invalidate the non-matching crumb
		return cookielist[0][0] + '=' + cookielist[0][1]

def getCrumb(seconds=1209600): # 14 days
	with _auth:
		cookie = getCookie()
		cacheFile = "finbot_yahoo_crumb.json"
		if config.prefs.cache and (cached := cache.read(cacheFile, seconds)):
			return cached
		r = _get_first(_hosts('/v1/test/getcrumb'), {**HEADERS, 'Cookie': cookie})
		if r is None:
			print("Exhausted Yahoo API attempts. Returning fallback crumb", file=sys.stderr)
			return 'jkQEU8yLqxs'
		if config.prefs.cache:
			cache.write(cacheFile, r.text)
		print("Got a new Yahoo crumb", file=sys.stderr)
		return r.text

def credentials():
	"""(cookie, crumb), taken together under the lock: a crumb is only good with the cookie it was issued for, and a renewal
	between two separate calls could pair a new cookie with an old crumb."""
	with _auth:
		crumb = getCrumb() # renews the cookie too, when due
		return getCookie(), crumb

def rmCrumb():
	"""Set the cached crumb aside (as .old): it belongs to the cookie being replaced."""
	crumb = Path(cache.path("finbot_yahoo_crumb.json"))
	if crumb.is_file():
		crumb.replace(crumb.with_name(crumb.name + '.old'))

def _hosts(path):
	"""One Yahoo API path on its two hosts: query2, then query1 to fall back on."""
	return ['https://query2.finance.yahoo.com' + path, 'https://query1.finance.yahoo.com' + path]

def _get_first(urls, headers):
	"""The answer of the first URL that answers 200, or None when none does. Each failure is logged."""
	for url in urls:
		try:
			r = net.get(url, headers=headers, timeout=config.prefs.http_timeout)
		except Exception as e:
			print(net.redact(e), file=sys.stderr)
			continue
		if r.status_code == 200:
			return r
		print(r.status_code, r.text.strip()[:200], "returned by", net.redact(url), file=sys.stderr)
	return None

def dig(node, *path):
	"""node[path[0]][path[1]]..., or None where Yahoo left a part out or sent null."""
	for step in path:
		try:
			node = node[step]
		except (KeyError, IndexError, TypeError):
			return None
	return node

def _list(value):
	"""value if Yahoo sent a list there, else an empty one."""
	return value if isinstance(value, list) else []

def _percent(fraction):
	"""Yahoo's fraction as a percentage, to one decimal: 0.01234 -> 1.2."""
	return round(float(fraction) * 100, 1)

def _round2(value):
	return round(float(value), 2)

def _positive(value):
	"""A price that must be above zero: Yahoo sends 0 for a 52-week low it does not have."""
	if value <= 0:
		raise ValueError(f'{value} is not a price')
	return value

def _convert(convert, value):
	"""convert(value), or None for garbage where a number belongs (left out, like a missing field)."""
	try:
		return convert(value) if convert else value
	except (TypeError, ValueError, OverflowError):
		return None

QUOTE_FIELDS = ( # (key, Yahoo's name, conversion) for the fields of a v7 quote; one Yahoo leaves out, sends as null or garbles is left out
	('percent_change', 'regularMarketChangePercent', _round2),
	('dividend', 'trailingAnnualDividendRate', lambda v: round(float(v), 1)),
	('percent_change_premarket', 'preMarketChangePercent', _round2),
	('percent_change_postmarket', 'postMarketChangePercent', _round2),
	('market_cap', 'marketCap', lambda v: round(float(v))),
	('price_to_earnings_forward', 'forwardPE', round),
	('price_to_earnings_trailing', 'trailingPE', round),
	('quoteType', 'quoteType', None),
	('marketState', 'marketState', None),
	('profile_exchange', 'fullExchangeName', None),
	('exchangeTimezoneName', 'exchangeTimezoneName', None),
	('regularMarketTime', 'regularMarketTime', None),
	('financialCurrency', 'financialCurrency', None),
	('regularMarketPreviousClose', 'regularMarketPreviousClose', None),
	('fiftyTwoWeekHigh', 'fiftyTwoWeekHigh', None),
	('fiftyTwoWeekLow', 'fiftyTwoWeekLow', _positive),
)

def fetch(tickers):
	"""v7 quotes for many tickers in one request: {ticker: {...}}. Cached for 5 minutes (DO NOT CACHE LONGER). A ticker Yahoo gives
	no name or price for is left out. Raises RuntimeError when Yahoo cannot be reached."""
	if not tickers:
		print("no tickers provided to yahoo.fetch()", file=sys.stderr)
		return {}
	tickers = sorted(set(tickers)) # de-dupe
	cacheFile = "finbot_yahoo_" + hashlib.sha256("_".join(tickers).encode()).hexdigest() + '.json'
	if config.prefs.cache and (cached := cache.read(cacheFile, 300)):
		return cached
	cookie, crumb = credentials()
	r = _get_first(_hosts('/v7/finance/quote?crumb=' + crumb + '&symbols=' + ','.join(tickers)), {**HEADERS, 'Content-type': 'application/json', 'Cookie': cookie})
	if r is None:
		print("Exhausted Yahoo API attempts. Giving up", file=sys.stderr)
		raise RuntimeError("Yahoo API unavailable")
	data = r.json()['quoteResponse']
	if data['result'] is None or data['error'] is not None:
		print(f"{tickers}†", sep=' ', end='', flush=True, file=sys.stderr)
		return {} # callers iterate the result
	now = datetime.datetime.now().timestamp()
	yahoo_output = {}
	for item in data['result']:
		title = next((name for name in (item.get('longName'), item.get('shortName')) if isinstance(name, str) and name), None)
		if not title or item.get('regularMarketPrice') is None:
			continue
		quote = {'profile_title': formats.transform_title(title), 'ticker': item['symbol'], 'regularMarketPrice': item['regularMarketPrice'],
			'currency': item.get('currency'), 'percent_change': 0.0, 'dividend': 0.0}
		for key, field, convert in QUOTE_FIELDS:
			if (value := _convert(convert, item.get(field))) is not None:
				quote[key] = value
		stamps = [item[name] for name in ('earningsTimestamp', 'earningsTimestampStart', 'earningsTimestampEnd') if isinstance(item.get(name), (int, float))]
		if stamps: # the first still to come, else the announced date
			quote['earnings_date'] = next((stamp for stamp in stamps if stamp > now), stamps[0])
		yahoo_output[item['symbol']] = quote
	if config.prefs.cache:
		cache.write(cacheFile, yahoo_output)
	return yahoo_output

DETAIL_FIELDS = ( # (key, path in the quoteSummary result[, conversion]); a field Yahoo leaves out, sends as null or garbles is left out
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
	('price_to_earnings_trailing', ('summaryDetail', 'trailingPE', 'raw'), round),
	('price_to_earnings_forward', ('summaryDetail', 'forwardPE', 'raw')),
	('percent_change_year', ('summaryDetail', '52WeekChange', 'raw'), _percent),
	('price_to_sales', ('summaryDetail', 'priceToSalesTrailing12Months', 'raw')),
	('ex_dividend_date', ('calendarEvents', 'exDividendDate', 'raw')),
	('dividend_date', ('calendarEvents', 'DividendDate', 'raw')),
	('earnings_date', ('calendarEvents', 'earnings', 'earningsDate', 0, 'raw')),
	('percent_change', ('price', 'regularMarketChangePercent', 'raw'), _percent),
	('percent_change_premarket', ('price', 'preMarketChangePercent', 'raw'), _percent),
	('percent_change_postmarket', ('price', 'postMarketChangePercent', 'raw'), _percent),
	('profile_exchange', ('price', 'exchangeName')),
	('marketState', ('price', 'marketState')),
	('quoteType', ('price', 'quoteType')),
	('regularMarketPrice', ('price', 'regularMarketPrice', 'raw')),
	('regularMarketPreviousClose', ('price', 'regularMarketPreviousClose', 'raw')),
	('fiftyTwoWeekHigh', ('price', 'fiftyTwoWeekHigh', 'raw')),
	('fiftyTwoWeekLow', ('price', 'fiftyTwoWeekLow', 'raw'), _positive),
	('prePostMarketPrice', ('price', 'preMarketPrice', 'raw'), float),
	('prePostMarketPrice', ('price', 'postMarketPrice', 'raw'), float), # the after-hours price, when there is one, wins
	('netIncomeToCommon', ('defaultKeyStatistics', 'netIncomeToCommon', 'raw')),
	('sharesOutstanding', ('defaultKeyStatistics', 'sharesOutstanding', 'raw'), float),
	('short_percent', ('defaultKeyStatistics', 'shortPercentOfFloat', 'raw'), _percent),
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
	('recommend', ('financialData', 'recommendationKey')),
	('recommend_index', ('financialData', 'recommendationMean', 'raw')),
	('recommend_analysts', ('financialData', 'numberOfAnalystOpinions', 'raw')),
)
RECOMMENDATION = ('recommend', 'recommend_index', 'recommend_analysts') # all three, or none

def fetch_detail(ticker, seconds=None):
	"""quoteSummary for one ticker: {ticker: {...}}, or {} when Yahoo has nothing usable (no name or no price)."""
	if seconds is None:
		seconds = config.prefs.cache_seconds
	now = datetime.datetime.now()
	cacheFile = "finbot_yahoo_detail_" + ticker + '.json'
	data = cache.read(cacheFile, seconds) if config.prefs.cache else None
	if not data:
		cookie, crumb = credentials() # only on a miss: a cached detail needs neither, nor the lock
		modules = 'calendarEvents,defaultKeyStatistics,balanceSheetHistoryQuarterly,financialData,summaryProfile,summaryDetail,price,earnings,earningsTrend,insiderTransactions'
		r = _get_first(_hosts('/v10/finance/quoteSummary/' + ticker + '?modules=' + modules + '&crumb=' + crumb), {**HEADERS, 'Cookie': cookie})
		if r is None:
			return {} # catches some delisted stocks like "DRNA"
		data = r.json()
		if config.prefs.cache:
			cache.write(cacheFile, data)
	result = dig(data, 'quoteSummary', 'result', 0)
	if result is None: # Yahoo answers result=null for unknown symbols
		print(ticker + 'x', sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	title = next((name for name in (dig(result, 'price', 'longName'), dig(result, 'price', 'shortName')) if isinstance(name, str) and name), None)
	if not title: # catches some delisted stocks like "DUB"
		print(f"{ticker}†", sep=' ', end='', flush=True, file=sys.stderr)
		return {}
	detail = {'profile_title': formats.transform_title(title)}
	for key, path, *convert in DETAIL_FIELDS:
		if (value := _convert(convert[0] if convert else None, dig(result, *path))) is not None:
			detail[key] = value
	if 'regularMarketPrice' not in detail:
		return {} # catches junk
	if not all(key in detail for key in RECOMMENDATION):
		for key in RECOMMENDATION:
			detail.pop(key, None)
	quarterly = _list(dig(result, 'earnings', 'financialsChart', 'quarterly'))
	for item in quarterly[-1:-3:-1]: # net income: the latest quarter of the last two with an earnings figure
		if dig(item, 'earnings', 'fmt') is not None and dig(item, 'earnings', 'raw') is not None:
			detail['net_income'] = dig(item, 'earnings', 'raw')
			break
	trend = _list(dig(result, 'earningsTrend', 'trend'))
	if trend:
		year = next((item for item in trend if dig(item, 'period') == '+1y'), None)
		estimates = [dig(year, kind, field, 'raw') for kind, field in (('revenueEstimate', 'growth'), ('earningsEstimate', 'growth'),
			('revenueEstimate', 'numberOfAnalysts'), ('earningsEstimate', 'numberOfAnalysts'))]
		if None in estimates:
			print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
		else:
			detail['revenueEstimateY'], detail['earningsEstimateY'] = _percent(estimates[0]), _percent(estimates[1])
			detail['revenueAnalysts'], detail['earningsAnalysts'] = estimates[2], estimates[3]
	if dig(quarterly, 0, 'revenue', 'raw') is None:
		print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
	else: # a quarter without an earnings figure is bad data: None for both, which doDelta marks
		detail['earningsQ'] = [None if dig(item, 'earnings', 'fmt') is None else dig(item, 'earnings', 'raw') for item in quarterly]
		detail['revenueQ'] = [None if dig(item, 'earnings', 'fmt') is None else dig(item, 'revenue', 'raw') for item in quarterly]
		yearly = _list(dig(result, 'earnings', 'financialsChart', 'yearly'))
		detail['earningsY'] = [dig(item, 'earnings', 'raw') for item in yearly]
		detail['revenueY'] = [dig(item, 'revenue', 'raw') for item in yearly]
	transactions = _list(dig(result, 'insiderTransactions', 'transactions'))
	if transactions: # insider buying and selling over the last 3 months: shares and value
		since = now - datetime.timedelta(days=90)
		totals = {'Buy': [0, 0], 'Sale': [0, 0]}
		for item in transactions:
			start = dig(item, 'startDate', 'raw')
			if not isinstance(start, (int, float)) or datetime.datetime.fromtimestamp(start) <= since:
				continue
			for kind, total in totals.items():
				if kind in (dig(item, 'transactionText') or ''):
					total[0] += dig(item, 'shares', 'raw') or 0
					total[1] += dig(item, 'value', 'raw') or 0
		detail['insiderBuy'], detail['insiderBuyValue'] = totals['Buy']
		detail['insiderSell'], detail['insiderSellValue'] = totals['Sale']
	return {ticker: dict(sorted(detail.items()))}

def price_history(ticker, days=None, seconds=None, graph=None, graphCache=True):
	"""({period: percent change}, chart image or None): the change over `days`, else over each standard period. Raises
	RuntimeError when the history cannot be fetched or has no prices."""
	if graph is None:
		graph = config.prefs.graph
	if seconds is None:
		seconds = config.prefs.cache_seconds
	import pandas as pd
	from pandas.tseries.offsets import BDay as businessday
	percent_dict = {}
	max_days = 3655 # 10 years + buffer
	now = datetime.datetime.now()
	interval = ('10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '5D', '1D')
	data = fetch_chart_json(ticker)
	df = chart_json_to_df(data)
	stock = chart_json_to_stock_basics(data)
	closes = df['Close'].dropna()
	if closes.empty:
		raise RuntimeError(f"no price history for {ticker}")
	price = stock.get('regularMarketPrice') or closes.iloc[-1] # the chart's last close when Yahoo gives no current price
	tz = zoneinfo.ZoneInfo(stock.get('exchangeTimezoneName') or 'UTC')
	if days:
		df = df[df['Date'] >= (now - datetime.timedelta(days=days)).date()].reset_index(drop=True)
		if df.empty:
			raise RuntimeError(f"no price history for {ticker} in the past {days} days")
		past_price = df['Close'].iloc[0]
		percent_dict[days] = round((price - past_price) / past_price * 100, 2)
	else:
		default_price = df['Close'].iloc[0]
		default_percent = round((price - default_price) / default_price * 100)
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
			percent_dict[period] = round((price - past_price) / past_price * 100)
	if not graph or (days and days < 2):
		return percent_dict, None
	company_name = formats.transform_title(stock.get('longName', ''))
	if days:
		title = f"{company_name} ({ticker}) {min(days, max_days)} days {formats.signed_percent(percent_dict[days])} Last: {price}"
	else:
		label = "Max" if "Max" in percent_dict else "10Y"
		title = f"{company_name} ({ticker}) {label} {formats.signed_percent(percent_dict[label])} Last: {price}"
	image_cache_file = "finbot_graph_" + ticker + "_" + str(days) + ".png"
	if config.prefs.cache and graphCache and (image := cache.read_bytes(image_cache_file, seconds)):
		return percent_dict, image
	image = render.graph(df, title, stock.get('currency'))
	if config.prefs.cache:
		cache.write_bytes(image_cache_file, image)
	return percent_dict, image

def price_series(ticker):
	"""Daily closes for a ticker via the same fetch/parse path as price_history(): (name, exchange, pandas Series indexed by datetime).
	Raises RuntimeError when there is no history."""
	import pandas as pd
	data = fetch_chart_json(ticker, full=True)
	df = chart_json_to_df(data)
	stock = chart_json_to_stock_basics(data)
	df = df[df['Close'].notnull()]
	if df.empty:
		raise RuntimeError(f"no price history for {ticker}")
	series = pd.Series(df['Close'].astype(float).values, index=pd.to_datetime(df['Date'].astype(str)), name=ticker)
	name = formats.transform_title(stock.get('longName') or stock.get('shortName') or ticker)
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

SUBUNITS = {'GBp': 'GBP', 'GBX': 'GBP', 'ILA': 'ILS', 'ZAc': 'ZAR'} # Yahoo prices these markets in a subunit but gives market caps in the unit

def market_cap_currency(data):
	"""The currency of a ticker's market cap: its quote currency, but the unit where Yahoo quotes in pence or the like."""
	return SUBUNITS.get(data.get('currency'), data.get('currency'))

def add_usd_market_caps(market_data):
	"""Put 'market_cap_usd' beside each 'market_cap', which Yahoo gives in the ticker's own currency, converted at Yahoo's
	exchange rates, so that market caps in won, yen and dollars compare. A ticker whose currency Yahoo has no rate for gets
	none. Returns market_data."""
	wanted = {market_cap_currency(data) for data in market_data.values() if 'market_cap' in data and market_cap_currency(data)} - {'USD'}
	rates = {'USD': 1.0}
	for symbol, quote in (fetch([f'{currency}=X' for currency in wanted]) if wanted else {}).items(): # KRW=X: won per US dollar
		if quote.get('regularMarketPrice'):
			rates[symbol.removesuffix('=X')] = 1 / quote['regularMarketPrice']
	for data in market_data.values():
		if 'market_cap' in data and market_cap_currency(data) in rates:
			data['market_cap_usd'] = data['market_cap'] * rates[market_cap_currency(data)]
	return market_data

def fetch_details(tickers, strict=False):
	"""fetch_detail of every ticker, fetched at the same time, in one {ticker: detail}. A ticker whose fetch failed is left out
	(and logged), so that a list goes out without it; strict=True raises its error instead, for a report on the ticker asked for."""
	tickers = list(tickers)
	details = {}
	for ticker, detail in zip(tickers, fetch_each(fetch_detail, tickers)):
		if isinstance(detail, Exception):
			if strict:
				raise detail
			print(ticker, detail, file=sys.stderr)
		else:
			details |= detail
	return details

def resolve(ticker, lookup):
	"""(ticker, lookup(ticker)) for a ticker Yahoo knows: a bare symbol it does not know is tried on the ASX (BHP: BHP.AX).
	lookup is fetch-shaped ({ticker: data}, without the tickers Yahoo does not know); its {} means Yahoo knows neither."""
	found = lookup(ticker)
	if ticker not in found and '.' not in ticker:
		ticker += '.AX'
		found = lookup(ticker)
	return ticker, found

def prefetch_history(tickers, workers=8):
	"""Warm the price-history cache for many tickers at once, so the per-ticker lookups that follow are cache hits."""
	tickers = list(tickers)
	for ticker, result in zip(tickers, fetch_each(fetch_chart_json, tickers, workers)):
		if isinstance(result, Exception):
			print("prefetch failed for", ticker, result, file=sys.stderr)

def fetch_chart_json(ticker, days=3665, seconds=None, full=False):
	"""Yahoo's daily chart for the last `days`, or with full=True its entire history (cached separately). Raises RuntimeError when
	Yahoo cannot be reached or refuses."""
	if seconds is None:
		seconds = config.prefs.cache_seconds
	now = datetime.datetime.now()
	cacheFile = "finbot_yahoo_history_" + ticker + ("_max" if full else "") + ".json"
	if config.prefs.cache and (cached := cache.read(cacheFile, seconds)):
		return cached
	cookie, crumb = credentials()
	start = '0' if full else str(int((now - datetime.timedelta(days=days)).timestamp()))
	url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start}&period2={int(now.timestamp())}&interval=1d&crumb={crumb}'
	print("Fetching", net.redact(url), file=sys.stderr) if config.prefs.debug else None
	try:
		r = net.get(url, headers={**HEADERS, 'Content-type': 'application/json', 'Cookie': cookie}, timeout=config.prefs.http_timeout)
	except Exception as e:
		raise RuntimeError(f"Yahoo unreachable for {ticker}: {net.redact(e)}") from e
	if r.status_code != 200:
		raise RuntimeError(f"{r.status_code} error for {ticker} from Yahoo's chart API")
	data = r.json()
	if config.prefs.cache:
		cache.write(cacheFile, data)
	return data

def chart_json_to_df(chart_json):
	"""The chart's daily bars as a DataFrame: Timestamp, Open, High, Low, Close, Volume and the Date."""
	import pandas as pd
	result = chart_json['chart']['result'][0]
	df = pd.DataFrame({'Timestamp': result['timestamp'], **result['indicators']['quote'][0]})
	df['Date'] = pd.to_datetime(df['Timestamp'], unit='s').dt.date
	df.columns = [col.capitalize() for col in df.columns]
	return df

def chart_json_to_stock_basics(chart_json):
	"""The chart's meta, which saves a call to fetch(): currency, symbol, exchangeName and fullExchangeName, exchangeTimezoneName,
	regularMarketPrice and regularMarketTime, longName and shortName, fiftyTwoWeekHigh and Low, and more. {} when there is none."""
	return dig(chart_json, 'chart', 'result', 0, 'meta') or {}

def historic_high(ticker):
	"""(highest high, lowest low) of the ticker's history. Raises RuntimeError when it has none (e.g. total-return indices such
	as ^SPTTGD carry no High/Low data)."""
	df = chart_json_to_df(fetch_chart_json(ticker))
	df = df[df.High.notnull()].iloc[1:].reset_index(drop=True)
	if df.empty:
		raise RuntimeError(f"no high/low history for {ticker}")
	highrow = df.iloc[df['High'].argmax()]
	lowrow = df.iloc[df['Low'].argmin()]
	if config.prefs.debug:
		print(ticker, "High", highrow['Date'], round(highrow['High'], 2), file=sys.stderr)
		print(ticker, "Low", lowrow['Date'], round(lowrow['Low'], 2), file=sys.stderr)
	return round(highrow['High'], 2), round(lowrow['Low'], 2)
