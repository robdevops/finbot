import dataclasses
import datetime
import sys
import threading
import time
import requests
from lib import config
from lib import cache
from lib import net
from lib import formats
from lib import markets

MAX_CONCURRENT = 1 # Sharesight rejects parallel requests beyond a few per account: allow one at a time across all chats and threads
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT)

def _get(url, **kwargs):
	"""net.get, waiting its turn: one Sharesight request at a time (MAX_CONCURRENT)."""
	with _request_slots:
		return net.get(url, **kwargs)

def _post(url, **kwargs):
	"""net.post, waiting its turn like _get."""
	with _request_slots:
		return net.post(url, **kwargs)

def _request(send, url, what, **kwargs):
	"""Send a request to Sharesight and return the JSON answer. A request that fails raises RuntimeError naming `what`."""
	try:
		r = send(url, timeout=config.prefs.http_timeout, **kwargs)
	except Exception as e:
		print("Error", net.redact(e), url, file=sys.stderr)
		raise RuntimeError(f"Sharesight {what} request failed: {e}")
	if r.status_code != 200:
		print(r.status_code, "error", url, file=sys.stderr)
	return r.json()

def _check(data, what):
	"""Raise RuntimeError with Sharesight's error, when it answered with one."""
	if 'error' in data:
		print("Sharesight error:", data['error_code'], data['error'], file=sys.stderr)
		raise RuntimeError(f"Sharesight {what} error: {data['error']}")

class BearerAuth(requests.auth.AuthBase):
	def __init__(self, token):
		"""token: the access token."""
		self.token = token
	def __call__(self, r):
		"""Add the token to a request's Authorization header."""
		r.headers["Authorization"] = "Bearer " + self.token
		return r

def get_token():
	"""An access token for the Sharesight API: the cached one while it has more than 20 seconds left, else a new one
	(cached while the cache preference is on)."""
	if config.prefs.cache:
		cacheFile = "finbot_sharesight_token.json"
		cached = cache.load(cacheFile)
		if cached:
			cache_expiry = datetime.datetime.fromtimestamp(cached['created_at'] + cached['expires_in'])
			ttl = cache_expiry - datetime.datetime.now()
			if ttl > datetime.timedelta(seconds=20):
				print("cache hit:", cacheFile, "TTL:", formats.td_to_human(ttl), file=sys.stderr) if config.prefs.debug else None
				return cached['access_token']
			else:
				print("cache miss:", cacheFile, file=sys.stderr) if config.prefs.debug else None

	data = _request(_post, "https://api.sharesight.com/oauth2/token", 'auth', data=config.env.sharesight_auth)
	_check(data, 'auth')
	if config.prefs.cache and 'access_token' in data:
		cache.write(cacheFile, data)
	print("Got a Sharesight token", file=sys.stderr) if config.prefs.debug else None
	return data['access_token']

PORTFOLIOS_CACHE = "finbot_sharesight_portfolios.json" # ttl: the cache_seconds preference

def performance_cache_file(portfolio_id, days):
	"""The cache file of a portfolio's performance report over `days`."""
	return "finbot_sharesight_performance_" + str(portfolio_id) + "_" + str(days) + '.json'

def get_portfolios(refresh=False):
	"""refresh=True skips the cache read and fetches again (the cache is rewritten)."""
	data = cache.read(PORTFOLIOS_CACHE, config.prefs.cache_seconds) if config.prefs.cache and not refresh else None
	if not data:
		token = get_token()
		data = _request(_get, "https://api.sharesight.com/api/v3/portfolios", 'portfolios', headers={'Content-type': 'application/json'}, auth=BearerAuth(token))
		_check(data, 'portfolios')
		if config.prefs.cache and 'portfolios' in data:
			cache.write(PORTFOLIOS_CACHE, data)
	include, exclude = config.prefs.include_portfolios, config.prefs.exclude_portfolios
	portfolio_dict = {portfolio['name']: portfolio['id'] for portfolio in data['portfolios']
		if str(portfolio['id']) not in exclude and (not include or str(portfolio['id']) in include)}
	if not portfolio_dict:
		print("No portfolios found. Exiting.", file=sys.stderr)
		raise RuntimeError("No Sharesight portfolios found")
	return portfolio_dict

class PortfolioNotFound(LookupError):
	"""No portfolio is called what was asked for. `lines` is the answer to give: the name, and the portfolios there are."""
	def __init__(self, name, names):
		"""name: what was asked for; names: the portfolios there are."""
		self.lines = [f"{name} portfolio not found. I only know about:"] + list(names)
		super().__init__(' '.join(self.lines))

@dataclasses.dataclass(frozen=True)
class Portfolio:
	"""A Sharesight portfolio. Its methods ask Sharesight through the module functions (cached, one request at once)."""
	name: str # as Sharesight spells it
	id: int

	def performance(self, days=None):
		"""Sharesight's performance report over the past `days` (past_days when None); days=0 gives today's holdings."""
		return get_performance(self.id, config.prefs.past_days if days is None else days)

	def holdings(self):
		"""{'CODE:MARKET': Sharesight's instrument, with the holding's id and value added} of what it holds."""
		holdings = {}
		for item in self.performance(0)['report']['holdings']:
			instrument = item['instrument']
			key = instrument['code'] + ':' + instrument['market_code']
			holdings[key] = instrument | {'holding_id': item['id'], 'value': item.get('value')}
		return holdings

	def tickers(self):
		"""What it holds, as Yahoo tickers, sorted."""
		return sorted({markets.transform_to_yahoo(each['code'], each['market_code']) for each in self.holdings().values()})

	def trades(self, days=None):
		"""Its trades of the past `days` (the past_days preference when None)."""
		return get_trades(self.name, self.id, days)

def portfolios(select=None):
	"""The portfolios to report on (after include_portfolios and exclude_portfolios), or the one called `select`, in any
	case. Raises PortfolioNotFound for a name that is none of them."""
	found = [Portfolio(name, portfolio_id) for name, portfolio_id in get_portfolios().items()]
	if not select:
		return found
	chosen = [portfolio for portfolio in found if portfolio.name.lower() == select.lower()]
	if not chosen:
		raise PortfolioNotFound(select, [portfolio.name for portfolio in found])
	return chosen

def tickers():
	"""Every portfolio's holdings as Yahoo tickers, sorted."""
	return sorted({ticker for portfolio in portfolios() for ticker in portfolio.tickers()})

def get_trades(portfolio_name, portfolio_id, days=None):
	"""The portfolio's trades of the past `days` (the past_days preference when None), each tagged with its portfolio's
	name; cached for 5 minutes. Raises RuntimeError when Sharesight cannot be reached or answers with an error."""
	if days is None:
		days = config.prefs.past_days
	if config.prefs.cache:
		cache_file = "finbot_sharesight_trades_" + str(portfolio_id) + "_" + str(days) + ".json"
		cached = cache.read(cache_file, 299) # max freq 5 min
		if cached:
			return cached['trades']
	start_date = datetime.datetime.now() - datetime.timedelta(days=days)
	start_date = start_date.strftime('%Y-%m-%d') # 2022-08-20
	token = get_token()
	url = 'https://api.sharesight.com/api/v2/portfolios/'
	url = url + str(portfolio_id) + '/trades.json' + '?start_date=' + start_date
	data = _request(_get, url, 'trades', auth=BearerAuth(token))
	_check(data, 'trades')
	for trade in data['trades']:
		trade['portfolio'] = portfolio_name # inject custom field
	if config.prefs.cache and 'trades' in data:
		cache.write(cache_file, data)
	return data['trades']

def get_performance(portfolio_id, days, seconds=None, refresh=False):
	"""Sharesight's performance report of a portfolio since `days` ago (0: today's holdings), cached for `seconds` (the
	performance_cache_seconds preference when None); refresh=True asks again. While Sharesight says too many requests
	are in flight it retries, up to five tries. Raises RuntimeError on an error answer, or one without a report."""
	if seconds is None:
		seconds = config.prefs.performance_cache_seconds
	start_date = datetime.datetime.now() - datetime.timedelta(days=days)
	start_date = start_date.strftime('%Y-%m-%d') # 2023-04-25
	cache_file = performance_cache_file(portfolio_id, days)
	if config.prefs.cache and not refresh:
		cached = cache.read(cache_file, seconds)
		if cached:
			return cached
	token = get_token()
	endpoint = 'https://api.sharesight.com/api/v3/portfolios/'
	url = endpoint + str(portfolio_id) + '/performance?grouping=ungrouped&start_date=' + start_date
	for attempt in range(5): # Sharesight allows only a few requests in flight at once; back off and retry when it says so
		data = _request(_get, url, 'performance', auth=BearerAuth(token))
		if 'error' in data and 'parallel' in str(data['error']).lower() and attempt < 4:
			print("Sharesight busy:", data['error'], "- retrying", file=sys.stderr)
			time.sleep(1 + attempt)
			continue
		break
	_check(data, 'performance')
	if 'report' not in data:
		raise RuntimeError(f"Sharesight sent no performance report for portfolio {portfolio_id}")
	if config.prefs.cache:
		cache.write(cache_file, data)
	return data

def warm(margin=0.9):
	"""Refresh the portfolio list and each portfolio's holdings report (days=0) once they reach `margin` of their cache lifetime,
	so a request never has to wait on Sharesight. Returns (the number of fetches made, the portfolios): the caller can hand
	the portfolios on instead of reading the cached list again."""
	fetched = 0
	age = cache.age(PORTFOLIOS_CACHE)
	if age is None or age >= config.prefs.cache_seconds * margin:
		portfolios = get_portfolios(refresh=True)
		fetched += 1
	else:
		portfolios = get_portfolios()
	for portfolio_name, portfolio_id in portfolios.items():
		age = cache.age(performance_cache_file(portfolio_id, 0))
		if age is None or age >= margin * config.prefs.performance_cache_seconds:
			get_performance(portfolio_id, 0, refresh=True)
			fetched += 1
	return fetched, portfolios

def next_due(margin=0.9, portfolios=None):
	"""Seconds until the soonest warmed cache needs refreshing (0 if one already does). `portfolios` is the list warm() just
	used; without it the cached list is read."""
	waits = []
	age = cache.age(PORTFOLIOS_CACHE)
	waits.append(0 if age is None else margin * config.prefs.cache_seconds - age)
	for portfolio_name, portfolio_id in (get_portfolios() if portfolios is None else portfolios).items():
		age = cache.age(performance_cache_file(portfolio_id, 0))
		waits.append(0 if age is None else margin * config.prefs.performance_cache_seconds - age)
	return max(0, min(waits))

_wake = threading.Event() # set by wake(): the caches were flushed, refill them now

def wake():
	"""Have keep_warm refill the caches now instead of when they would next be due."""
	_wake.set()

def keep_warm(min_wait=5, retry=300, idle=60, stop=None):
	"""Background loop: keep the portfolio list and holdings report cached, sleeping until the next one is due (90% of its TTL).
	While the cache preference is off (a reload can switch it either way) it fetches nothing, since nothing would be written and
	everything would always be due, and looks again every `idle` seconds. Never raises; after a failure it waits `retry` seconds."""
	while not (stop and stop.is_set()):
		if not config.prefs.cache:
			wait = idle
		else:
			try:
				_, portfolios = warm()
				wait = max(min_wait, next_due(portfolios=portfolios))
			except Exception as e:
				print("Sharesight cache refresh failed:", e, file=sys.stderr)
				wait = retry
		if stop:
			stop.wait(wait)
		else:
			_wake.wait(wait)
			_wake.clear()
