import calendar
import concurrent.futures
import datetime
import hashlib
import threading
import typing
import zoneinfo
from lib import log
from lib import answer
from lib import config
from lib import cache
from lib import net
from lib import formats
from lib import markets
from http.cookies import SimpleCookie

_auth = threading.Lock() # Yahoo's cookie and crumb are renewed by one thread at a time, or two could pair up wrongly
HEADERS = {'User-Agent': 'Mozilla/5.0'}
CREDENTIALS = 'finbot_yahoo_credentials.json' # [cookie, crumb]: Yahoo issues the crumb for the cookie: they go together

def credentials(renew=False):
	"""(cookie, crumb) for Yahoo's API, from one cache file kept 14 days whatever the cache setting, and renewed
	together (renew=True: now, for a pair Yahoo refused). Raises RuntimeError when Yahoo gives no cookie or no crumb."""
	with _auth:
		if not renew and (cached := cache.read(CREDENTIALS, 14 * 86400)):
			return tuple(cached)
		r = net.answer('Yahoo', 'a cookie', 'https://fc.yahoo.com/', headers=HEADERS) # a 404, the cookie in its headers
		jar = SimpleCookie()
		jar.load(r.headers.get('Set-Cookie', ''))
		if not jar:
			raise RuntimeError(f"Yahoo gave no cookie ({r.status_code})")
		cookie = '{}={}'.format(*next((name, morsel.value) for name, morsel in jar.items()))
		for url in _hosts('/v1/test/getcrumb'):
			try:
				r = net.answer('Yahoo', 'a crumb', url, headers={**HEADERS, 'Cookie': cookie})
			except RuntimeError as e:
				log.warn(e)
				continue
			if r.status_code == 200 and r.text.strip():
				cache.write(CREDENTIALS, [cookie, r.text.strip()])
				log.info("Got a new Yahoo cookie and crumb")
				return cookie, r.text.strip()
			log.warn(r.status_code, "from Yahoo for a crumb")
		raise RuntimeError("Yahoo gave no crumb")

def _hosts(path):
	"""One Yahoo API path on its two hosts: query2, then query1 to fall back on."""
	return ['https://query2.finance.yahoo.com' + path, 'https://query1.finance.yahoo.com' + path]

def _answer(query, what):
	"""Yahoo's JSON answer to an API query, from query2 or else query1, with the cookie and its crumb (renewed once when
	Yahoo refuses them): None when Yahoo says it has no such symbol (404 Not Found). Raises RuntimeError when no host
	answers with JSON, or one refuses otherwise; `what` names the request in the error."""
	refusal = ''
	for renew in (False, True):
		cookie, crumb = credentials(renew)
		for url in _hosts(query + ('&' if '?' in query else '?') + 'crumb=' + crumb):
			try:
				r = net.answer('Yahoo', what, url, headers={**HEADERS, 'Cookie': cookie})
				if r.status_code == 200:
					return net.json_answer(r, 'Yahoo', what)
			except RuntimeError as e:
				refusal = str(e)
				log.warn(refusal)
				continue
			if r.status_code == 404 and not_found(r):
				return None
			refusal = f"{r.status_code} error for {what} from Yahoo"
			log.warn(refusal + ':', r.text.strip()[:200])
		if not refusal.startswith('401 '): # only a refused crumb is worth a new one
			break
	raise RuntimeError(refusal)

def not_found(response):
	"""Whether an answer is Yahoo saying it has no such symbol (the chart's or the quoteSummary's error code Not Found),
	rather than some other failure."""
	try:
		body = response.json()
	except ValueError:
		return False
	return isinstance(body, dict) and any(dig(part, 'error', 'code') == 'Not Found' for part in body.values())

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
	"""value as a float rounded to two places."""
	return round(float(value), 2)

def _positive(value):
	"""A price that must be above zero: Yahoo sends 0 for a 52-week low it does not have."""
	if value <= 0:
		raise ValueError(f'{value} is not a price')
	return value

def _convert(convert, value):
	"""convert(value); None for a field Yahoo leaves out or sends as null (an ETF has no analysts' recommendation), and
	for garbage, such as text where a number belongs (left out, like a missing field)."""
	if value is None:
		return None
	try:
		return convert(value) if convert else value
	except (TypeError, ValueError, OverflowError, AttributeError):
		return None

# (key, Yahoo's name, conversion) for the fields of a v7 quote; one Yahoo leaves out, sends as null or garbles is left
# out
QUOTE_FIELDS = (
	('percent_change', 'regularMarketChangePercent', _round2),
	('percent_change_premarket', 'preMarketChangePercent', _round2),
	('percent_change_postmarket', 'postMarketChangePercent', _round2),
	('market_cap', 'marketCap', lambda v: round(float(v))),
	('price_to_earnings_forward', 'forwardPE', round),
	('price_to_earnings_trailing', 'trailingPE', round),
	('quoteType', 'quoteType', None),
	('marketState', 'marketState', None),
	('profile_exchange', 'fullExchangeName', None),
	('regularMarketTime', 'regularMarketTime', None),
	('financialCurrency', 'financialCurrency', None),
	('fiftyTwoWeekHigh', 'fiftyTwoWeekHigh', None),
	('fiftyTwoWeekLow', 'fiftyTwoWeekLow', _positive),
)

def fetch(tickers):
	"""v7 quotes for many tickers in one request: {ticker: {...}}. Cached for 5 minutes (DO NOT CACHE LONGER). A ticker
	Yahoo gives no name or price for is left out. Raises RuntimeError when Yahoo cannot be reached."""
	if not tickers:
		log.info("no tickers provided to yahoo.fetch()")
		return {}
	tickers = sorted(set(tickers)) # de-dupe
	name = "finbot_yahoo_quote_" + hashlib.sha256("_".join(tickers).encode()).hexdigest() + '.json'
	data = cache.cached(name, 300, lambda: _quote_answer(tickers))
	if data is None:
		log.warn("Yahoo has no quotes for", ', '.join(tickers))
		return {} # callers iterate the result
	now = datetime.datetime.now().timestamp()
	yahoo_output = {}
	for item in data['quoteResponse']['result']:
		title = next((name for name in (item.get('longName'), item.get('shortName')) if isinstance(name, str) and name),
			None)
		if not title or item.get('regularMarketPrice') is None:
			continue
		quote = {'profile_title': formats.transform_title(title), 'ticker': item['symbol'],
			'regularMarketPrice': item['regularMarketPrice'],
			'currency': item.get('currency'), 'percent_change': 0.0}
		for key, field, convert in QUOTE_FIELDS:
			if (value := _convert(convert, item.get(field))) is not None:
				quote[key] = value
		stamps = [item[name] for name in ('earningsTimestamp', 'earningsTimestampStart',
			'earningsTimestampEnd') if isinstance(item.get(name), (int, float))]
		if stamps: # the first still to come, else the announced date
			quote['earnings_date'] = next((stamp for stamp in stamps if stamp > now), stamps[0])
		yahoo_output[item['symbol']] = quote
	return yahoo_output

def _quote_answer(tickers):
	"""The v7 answer for the tickers, None for an error answer (not cached). Raises RuntimeError when Yahoo cannot be
	reached or refuses."""
	data = _answer('/v7/finance/quote?symbols=' + ','.join(tickers), 'quotes')
	quotes = dig(data, 'quoteResponse') or {}
	return data if quotes.get('result') is not None and quotes.get('error') is None else None

# (key, path in the quoteSummary result[, conversion]); a field Yahoo leaves out, sends as null or garbles is left out
DETAIL_FIELDS = (
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
	('price_to_sales', ('summaryDetail', 'priceToSalesTrailing12Months', 'raw')),
	('ex_dividend_date', ('calendarEvents', 'exDividendDate', 'raw')),
	('earnings_date', ('calendarEvents', 'earnings', 'earningsDate', 0, 'raw')),
	('percent_change', ('price', 'regularMarketChangePercent', 'raw'), _percent),
	('percent_change_premarket', ('price', 'preMarketChangePercent', 'raw'), _percent),
	('percent_change_postmarket', ('price', 'postMarketChangePercent', 'raw'), _percent),
	('profile_exchange', ('price', 'exchangeName')),
	('marketState', ('price', 'marketState')),
	('quoteType', ('price', 'quoteType')),
	('regularMarketPrice', ('price', 'regularMarketPrice', 'raw')),
	('prePostMarketPrice', ('price', 'preMarketPrice', 'raw'), float),
	('prePostMarketPrice', ('price', 'postMarketPrice', 'raw'), float), # the after-hours price, when there is one, wins
	('netIncomeToCommon', ('defaultKeyStatistics', 'netIncomeToCommon', 'raw')),
	('sharesOutstanding', ('defaultKeyStatistics', 'sharesOutstanding', 'raw'), float),
	('short_percent', ('defaultKeyStatistics', 'shortPercentOfFloat', 'raw'), _percent),
	('price_to_earnings_peg', ('defaultKeyStatistics', 'pegRatio', 'raw')),
	('free_cashflow', ('financialData', 'freeCashflow', 'raw')),
	('operating_cashflow', ('financialData', 'operatingCashflow', 'raw')),
	('financialCurrency', ('financialData', 'financialCurrency')),
	('recommend', ('financialData', 'recommendationKey'), lambda key: key.replace('_', ' ')), # strong_buy: strong buy
	('recommend_index', ('financialData', 'recommendationMean', 'raw')),
	('recommend_analysts', ('financialData', 'numberOfAnalystOpinions', 'raw')),
)
RECOMMENDATION = ('recommend', 'recommend_index', 'recommend_analysts') # all three, or none

def fetch_detail(ticker, seconds=None, guess=False):
	"""One ticker's quoteSummary: {ticker: {...}}, cached `seconds` (or cache_seconds); {} for a symbol Yahoo does not
	know, or without a name or price, which is logged as a warning, or for a listing guessed at (guess: the calendar's
	other listing of a company), whose absence is no fault, at DEBUG. Raises RuntimeError when Yahoo cannot be reached
	or refuses."""
	missing = log.debug if guess else log.warn
	now = datetime.datetime.now()
	data = cache.cached("finbot_yahoo_detail_" + ticker + '.json', seconds, lambda: _detail_answer(ticker))
	result = dig(data, 'quoteSummary', 'result', 0)
	if result is None: # Yahoo answers 404 Not Found, or result=null, for a symbol it does not know
		missing(ticker, "is unknown to Yahoo")
		return {}
	title = next((name for name in (dig(result, 'price', 'longName'),
		dig(result, 'price', 'shortName')) if isinstance(name, str) and name), None)
	if not title: # catches some delisted stocks like "DUB"
		missing(ticker, "has no name at Yahoo")
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
		estimates = [dig(year, kind, 'growth', 'raw') for kind in ('revenueEstimate', 'earningsEstimate')]
		if None not in estimates:
			detail['revenueEstimateY'], detail['earningsEstimateY'] = _percent(estimates[0]), _percent(estimates[1])
	# a quarter without an earnings figure is bad data: None for both, which trend_marks marks
	if dig(quarterly, 0, 'revenue', 'raw') is not None:
		detail['earningsQ'] = [None if dig(item, 'earnings', 'fmt') is None else dig(item, 'earnings',
			'raw') for item in quarterly]
		detail['revenueQ'] = [None if dig(item, 'earnings', 'fmt') is None else dig(item, 'revenue',
			'raw') for item in quarterly]
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

DETAIL_MODULES = ('calendarEvents,defaultKeyStatistics,financialData,summaryProfile,summaryDetail,price,earnings,'
	'earningsTrend,insiderTransactions') # the quoteSummary modules fetch_detail reads

def _detail_answer(ticker):
	"""Yahoo's quoteSummary answer for one ticker, with every module finbot reads; None for a symbol Yahoo does not
	know. Raises RuntimeError when Yahoo cannot be reached or refuses."""
	return _answer(f'/v10/finance/quoteSummary/{ticker}?modules={DETAIL_MODULES}', ticker)

class Line(typing.NamedTuple):
	"""The prices behind a price_history, for its chart: the company's name, Yahoo's full name for its exchange (as
	fetch() gives profile_exchange), the currency, the current price (else the last close) and the closes over the span,
	((date, close), ...)."""
	name: str
	exchange: str
	currency: str
	price: float
	closes: tuple


class NoData(answer.Answer, RuntimeError):
	"""Yahoo has nothing for it (no such symbol, no prices): a reply in a chat, a RuntimeError where a list skips it."""


def bars(chart_json):
	"""A chart answer's daily bars, oldest first: [(the day, in the exchange's time zone; open; close)], a price Yahoo
	left out None. Yahoo stamps a bar with the time its market opened, which in UTC is the day before for Sydney or
	Auckland."""
	result = dig(chart_json, 'chart', 'result', 0) or {}
	zone = zoneinfo.ZoneInfo(dig(result, 'meta', 'exchangeTimezoneName') or 'UTC')
	stamps = _list(result.get('timestamp'))
	quote = dig(result, 'indicators', 'quote', 0) or {}
	opens, closes = _list(quote.get('open')) or [None] * len(stamps), _list(quote.get('close')) or [None] * len(stamps)
	return [(datetime.datetime.fromtimestamp(stamp, zone).date(), first, last)
		for stamp, first, last in zip(stamps, opens, closes)]

INTERVALS = ('10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '5D', '1D') # price_history's standard periods

def months_before(day, months):
	"""The same day of the month `months` months before, or the last day of that month where it is shorter: a month
	before 31 March is 28 or 29 February."""
	year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
	return day.replace(year=year, month=month + 1, day=min(day.day, calendar.monthrange(year, month + 1)[1]))

def _history(ticker):
	"""(Yahoo's meta, the bars (see bars), the closes [(day, close)] where it has one) of a ticker's daily chart. Raises
	NoData when there are no closes, RuntimeError when the chart cannot be fetched."""
	data = fetch_chart_json(ticker)
	daily = bars(data)
	closes = [(day, last) for day, _, last in daily if last is not None]
	if not closes:
		raise NoData(f"no price history for {ticker}")
	return dig(data, 'chart', 'result', 0, 'meta') or {}, daily, closes

def _named(meta, ticker):
	"""(the company's name, its exchange's) as a chart's meta has them: its long name, else its short one, else the
	ticker; the exchange's full name, else its short one."""
	return (formats.transform_title(meta.get('longName') or meta.get('shortName') or ticker),
		meta.get('fullExchangeName') or meta.get('exchangeName') or '')

def price_history(ticker, days=None, quote=None):
	"""({period: percent change}, its Line): the change over `days`, else over each standard period (and 'Max', from the
	first close, when one goes back further than the history), and the closes behind it, for a chart. The change is to
	the price now: the quote's (the ticker's quote or detail, which carries today's change too), else the chart's.
	Days are counted in the exchange's time zone. Raises NoData when there are no prices, RuntimeError when the history
	cannot be fetched."""
	meta, daily, closes = _history(ticker)
	quote = quote or {}
	price = quote.get('regularMarketPrice') or meta.get('regularMarketPrice') or closes[-1][1]
	today = datetime.datetime.now(zoneinfo.ZoneInfo(meta.get('exchangeTimezoneName') or 'UTC')).date()
	change = lambda past: (price - past) / past * 100
	changes = {}
	if days:
		closes = [(day, last) for day, last in closes if day >= today - datetime.timedelta(days=days)]
		if not closes:
			raise NoData(f"no price history for {ticker} in the past {days} days")
		changes[days] = round(change(closes[0][1]), 2)
	else:
		week_ago = today # five trading days back, as Google Finance counts its 5D
		for _ in range(5):
			week_ago -= datetime.timedelta(days=3 if week_ago.weekday() == 0 else 2 if week_ago.weekday() == 6 else 1)
		for period in INTERVALS:
			if period == '1D': # since the previous session's close: the quote's, or the last close before the last bar
				before = [last for day, last in closes if day < daily[-1][0]]
				if quote.get('percent_change') is not None:
					changes['1D'] = round(quote['percent_change'])
				elif before:
					changes['1D'] = round(change(before[-1]))
				continue
			if period == 'YTD':
				past = next((last for day, last in closes if day >= today.replace(month=1, day=1)), None)
			elif period == '5D': # the open of that day, to align with Google Finance
				past = next((first for day, first, _ in reversed(daily) if day <= week_ago and first is not None), None)
			else: # 10Y to 1M, 7D: the last close on or before the day that long ago
				count = int(period[:-1])
				cutoff = today - datetime.timedelta(days=count) if period[-1] == 'D' else \
					months_before(today, count * (12 if period[-1] == 'Y' else 1))
				past = next((last for day, last in reversed(closes) if day <= cutoff), None)
			if past is None: # the history does not go back that far
				changes['Max'] = round(change(closes[0][1]))
			else:
				changes[period] = round(change(past))
	return changes, Line(*_named(meta, ticker), meta.get('currency') or '', price,
		tuple((str(day), float(last)) for day, last in closes))

def price_series(ticker):
	"""A ticker's daily closes over 10 years, from the same chart as price_history(): (name, exchange, ((date,
	close), ...)), oldest first, each date a datetime.date. Raises NoData when there is no history."""
	meta, _, closes = _history(ticker)
	return *_named(meta, ticker), tuple((day, float(last)) for day, last in closes)

def fetch_each(get, tickers, workers=8):
	"""get(ticker) for each ticker, `workers` at a time so the waits overlap: [its result or the exception raised]."""
	def one(ticker):
		"""get(ticker), or the exception it raised."""
		try:
			return get(ticker)
		except Exception as e:
			return e
	with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
		return list(executor.map(one, tickers))

# Yahoo prices these markets in a subunit but gives market caps in the unit
SUBUNITS = {'GBp': 'GBP', 'GBX': 'GBP', 'ILA': 'ILS', 'ZAc': 'ZAR'}

def market_cap_currency(data):
	"""The currency of a ticker's market cap: its quote currency, or the unit where Yahoo quotes in pence and so on."""
	return SUBUNITS.get(data.get('currency'), data.get('currency'))

def usd_rates(currencies):
	"""{currency: US dollars to one unit of it} at Yahoo's exchange rates, for each of `currencies` it has a rate for
	(USD is 1.0, and a currency without a rate is left out)."""
	wanted = set(currencies) - {None, '', 'USD'}
	rates = {'USD': 1.0}
	# KRW=X: won per US dollar
	for symbol, quote in (fetch([f'{currency}=X' for currency in wanted]) if wanted else {}).items():
		if quote.get('regularMarketPrice'):
			rates[symbol.removesuffix('=X')] = 1 / quote['regularMarketPrice']
	return rates

def add_usd_market_caps(market_data):
	"""Put 'market_cap_usd' beside each 'market_cap', which Yahoo gives in the ticker's own currency, converted at
	Yahoo's exchange rates, so that market caps in won, yen and dollars compare. A ticker whose currency Yahoo has no
	rate for gets none. Returns market_data."""
	rates = usd_rates({market_cap_currency(data) for data in market_data.values() if 'market_cap' in data})
	for data in market_data.values():
		if 'market_cap' in data and market_cap_currency(data) in rates:
			data['market_cap_usd'] = data['market_cap'] * rates[market_cap_currency(data)]
	return market_data

def fetch_details(tickers, strict=False):
	"""fetch_detail of every ticker, fetched at the same time, in one {ticker: detail}. A ticker whose fetch failed is
	left out (and logged), so that a list goes out without it; strict=True raises its error instead, for a report on the
	ticker asked for."""
	tickers = list(tickers)
	details = {}
	for ticker, detail in zip(tickers, fetch_each(fetch_detail, tickers)):
		if isinstance(detail, Exception):
			if strict:
				raise detail
			log.warn(ticker, detail)
		else:
			details |= detail
	return details

def symbols(typed):
	"""Yahoo's symbols for tickers as written in a chat: BHP:ASX, BHP.ASX and bhp.ax give BHP.AX (see
	markets.transform_to_yahoo). A bare symbol Yahoo does not know is tried again on the local exchange, with the
	exchange_suffix setting (AX: BHP.AX), unless that is empty; a symbol Yahoo knows neither way stays as written.
	Two requests at most, however many tickers. Raises RuntimeError when Yahoo cannot be reached."""
	tickers = [markets.transform_to_yahoo(ticker.upper()) for ticker in typed]
	suffix = config.settings.exchange_suffix
	bare = [ticker for ticker in tickers if '.' not in ticker]
	if not (suffix and bare):
		return tickers
	known = fetch(bare)
	local = {ticker: f'{ticker}.{suffix}' for ticker in bare if ticker not in known}
	found = fetch(list(local.values())) if local else {}
	return [local[ticker] if local.get(ticker) in found else ticker for ticker in tickers]

def symbol(typed):
	"""Yahoo's symbol for one ticker as written in a chat (see symbols): BHP may be BHP.AX."""
	return symbols([typed])[0]

def prefetch_history(tickers, workers=8, seconds=None):
	"""Warm the price-history cache for many tickers at once, so the per-ticker lookups that follow are cache hits: a
	history is fetched unless its cache file is under `seconds` old (cache_seconds when None; 0 fetches each afresh),
	which its age tells (a fresh one is not read: a 10-year history takes 3 ms to decode). With the cache setting off
	nothing would be kept, so nothing is fetched. Returns the tickers whose history could not be fetched (logged)."""
	if not config.settings.cache:
		return []
	limit = config.settings.cache_seconds if seconds is None else seconds
	tickers = [ticker for ticker in tickers if (age := cache.age(history_file(ticker))) is None or age >= limit]
	failed = []
	for ticker, result in zip(tickers, fetch_each(lambda t: fetch_chart_json(t, seconds=seconds), tickers, workers)):
		if isinstance(result, Exception):
			log.warn("prefetch failed for", ticker, result)
			failed.append(ticker)
	return failed

def history_file(ticker, full=False):
	"""The cache file of a ticker's daily chart, or of its entire history (full)."""
	return "finbot_yahoo_history_" + ticker + ("_max" if full else "") + ".json"

CHART_DAYS = 3665 # days of daily bars in a chart: ten years (Max) and a fortnight before, for a bar to start from

def fetch_chart_json(ticker, seconds=None, full=False):
	"""Yahoo's daily chart for the last CHART_DAYS, or with full=True its entire history (cached separately). Raises
	NoData for a symbol Yahoo does not know, RuntimeError when Yahoo cannot be reached or refuses."""
	return cache.cached(history_file(ticker, full), seconds, lambda: _chart_answer(ticker, full))

def _chart_answer(ticker, full):
	"""The v8 chart answer: the daily bars of CHART_DAYS, or all with full=True. Raises as fetch_chart_json does."""
	now = datetime.datetime.now()
	start = 0 if full else int((now - datetime.timedelta(days=CHART_DAYS)).timestamp())
	data = _answer(f'/v8/finance/chart/{ticker}?period1={start}&period2={int(now.timestamp())}&interval=1d', ticker)
	if data is None:
		raise NoData(f"no price history for {ticker}")
	return data

def historic_high(ticker):
	"""(highest high, lowest low) of the ticker's whole history, its first day aside (Yahoo's first bar can be partial).
	Raises NoData when it has none (total-return indices such as ^SPTTGD carry no highs and lows)."""
	quote = dig(fetch_chart_json(ticker, full=True), 'chart', 'result', 0, 'indicators', 'quote', 0) or {}
	ranges = [(high, low) for high, low in zip(_list(quote.get('high')), _list(quote.get('low')))
		if high is not None and low is not None][1:]
	if not ranges:
		raise NoData(f"no high/low history for {ticker}")
	return round(max(high for high, _ in ranges), 2), round(min(low for _, low in ranges), 2)
