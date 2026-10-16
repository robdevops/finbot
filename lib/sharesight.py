"""Sharesight's API: the portfolios to report on (Portfolio), with their holdings, gains and trades. Answers are cached
as sent, and requests go one at a time."""
import dataclasses
import datetime
import threading
import time

from lib import log
from lib import answer
from lib import cache
from lib import config
from lib import markets
from lib import net

API = 'https://api.sharesight.com/'
MAX_CONCURRENT = 1 # Sharesight refuses parallel requests beyond a few per account: one at a time, whoever asks
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
TOKEN = 'finbot_sharesight_token.json' # good until the expiry it carries
PORTFOLIOS_CACHE = 'finbot_sharesight_portfolios.json' # good for the cache_seconds preference


def _request(path, what, expect, **kwargs):
	"""Sharesight's answer to a request (a POST with data=, else a GET), checked to hold `expect`: one request at a
	time (MAX_CONCURRENT), tried again while Sharesight says too many are in flight (five tries in all). Raises
	RuntimeError naming `what` when Sharesight cannot be reached, or answers with an error, or without `expect`."""
	send = net.post if 'data' in kwargs else net.get
	for attempt in range(5):
		with _request_slots:
			try:
				r = send(API + path, **kwargs)
			except Exception as e:
				raise RuntimeError(f"Sharesight {what}: {net.redact(e)}") from e
		try:
			data = r.json()
		except ValueError: # an HTML error page, say
			data = None
		error = data.get('error') if isinstance(data, dict) else None
		if not (error and 'parallel' in str(error).lower() and attempt < 4):
			break
		log.warn("Sharesight busy:", error, "- retrying")
		time.sleep(1 + attempt)
	if error: # an OAuth error describes itself too
		why = ': '.join(str(data[key]) for key in ('error', 'error_description') if data.get(key))
	elif not isinstance(data, dict):
		why = f"a {r.status_code} answer that is not JSON"
	elif r.status_code != 200 or expect not in data:
		why = f"a {r.status_code} answer without {expect}"
	else:
		return data
	raise RuntimeError(f"Sharesight {what}: {why}")


def _token():
	"""An access token for Sharesight's API: the cached one while it has more than 20 seconds left, else a new one
	(cached while the cache preference is on)."""
	cached = cache.load(TOKEN) if config.prefs.cache else None
	if cached and cached['created_at'] + cached['expires_in'] - time.time() > 20:
		return cached['access_token']
	data = _request('oauth2/token', 'auth', 'access_token', data=config.env.sharesight_auth)
	if config.prefs.cache:
		cache.write(TOKEN, data)
	return data['access_token']


def _api(path, what, expect):
	"""Sharesight's answer to an API query (path: under api/, with its query string) with the access token; see
	_request."""
	return _request('api/' + path, what, expect, headers={'Authorization': 'Bearer ' + _token()})


def _portfolios(seconds=None):
	"""Sharesight's list of every portfolio, from the cache while under `seconds` old (cache_seconds when None)."""
	fetch = lambda: _api('v3/portfolios', 'portfolios', 'portfolios')
	return cache.cached(PORTFOLIOS_CACHE, seconds, fetch)['portfolios']


def performance_cache_file(portfolio_id, days):
	"""The cache file of a portfolio's performance report over `days`."""
	return f"finbot_sharesight_performance_{portfolio_id}_{days}.json"


def _since(days):
	"""The date `days` ago, as Sharesight takes it: 2023-04-25."""
	return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _performance(portfolio_id, days=None, seconds=None):
	"""Sharesight's performance report of a portfolio since `days` ago (0: today's holdings; past_days when None), from
	the cache while under `seconds` old (the performance_cache_seconds preference when None)."""
	if days is None:
		days = config.prefs.past_days
	query = f'v3/portfolios/{portfolio_id}/performance?grouping=ungrouped&start_date={_since(days)}'
	fetch = lambda: _api(query, f'performance of portfolio {portfolio_id}', 'report')
	if seconds is None:
		seconds = config.prefs.performance_cache_seconds
	return cache.cached(performance_cache_file(portfolio_id, days), seconds, fetch)['report']


def _trades(portfolio_id, days=None):
	"""Sharesight's trades in a portfolio over the past `days` (past_days when None), from the cache while under 5
	minutes old."""
	if days is None:
		days = config.prefs.past_days
	query = f'v2/portfolios/{portfolio_id}/trades.json?start_date={_since(days)}'
	fetch = lambda: _api(query, 'trades', 'trades')
	return cache.cached(f"finbot_sharesight_trades_{portfolio_id}_{days}.json", 299, fetch)['trades']


class NotSetUp(answer.Answer, RuntimeError):
	"""Sharesight is not set up (configured): what needs it says so, as an answer."""
	def __init__(self):
		"""The answer: what is missing, and where it goes."""
		super().__init__('Sharesight is not set up: its keys go in finbot.env (doc/configuration.md)')


def configured():
	"""Whether Sharesight is set up, its keys in finbot.env: without, a chat's reports cover its watchlist alone."""
	return bool(config.env.sharesight_auth.get('client_id'))


class PortfolioNotFound(answer.Answer, LookupError):
	"""No portfolio is called what was asked for: the answer names it, and the portfolios there are."""
	def __init__(self, name, names):
		"""name: what was asked for; names: the portfolios there are."""
		super().__init__(f"{name} portfolio not found. I only know about:", *names)


@dataclasses.dataclass(frozen=True)
class Portfolio:
	"""A Sharesight portfolio. Its methods ask Sharesight (cached, one request at a time)."""
	name: str # as Sharesight spells it
	id: int

	def gain(self, days=None):
		"""Its capital gain over the past `days` (the past_days preference when None), in percent."""
		return float(_performance(self.id, days)['capital_gain_percent'])

	def holdings(self):
		"""{'CODE:MARKET': Sharesight's instrument, with the holding's id and value added} of what it holds."""
		return {each['instrument']['code'] + ':' + each['instrument']['market_code']:
			each['instrument'] | {'holding_id': each['id'], 'value': each.get('value')}
			for each in _performance(self.id, 0)['holdings']}

	def tickers(self):
		"""What it holds, as Yahoo tickers, sorted."""
		return sorted({markets.transform_to_yahoo(each['code'],
			each['market_code']) for each in self.holdings().values()})

	def trades(self, days=None):
		"""Its trades of the past `days` (the past_days preference when None), each with the portfolio's name added."""
		return [trade | {'portfolio': self.name} for trade in _trades(self.id, days)]


def _chosen(listed):
	"""The portfolios of Sharesight's list to report on, after include_portfolios and exclude_portfolios."""
	include, exclude = config.prefs.include_portfolios, config.prefs.exclude_portfolios
	return [Portfolio(each['name'], each['id']) for each in listed
		if str(each['id']) not in exclude and (not include or str(each['id']) in include)]


def portfolios(select=None, seconds=None):
	"""The portfolios to report on (after include_portfolios and exclude_portfolios), or the one called `select`, in any
	case; the list is cached for `seconds` (cache_seconds when None). Raises NotSetUp without Sharesight's keys,
	RuntimeError when there are none, and PortfolioNotFound for a name that is none of them."""
	if not configured():
		raise NotSetUp()
	found = _chosen(_portfolios(seconds))
	if not found:
		raise RuntimeError("No Sharesight portfolios found")
	if not select:
		return found
	chosen = [portfolio for portfolio in found if portfolio.name.lower() == select.lower()]
	if not chosen:
		raise PortfolioNotFound(select, [portfolio.name for portfolio in found])
	return chosen


def tickers():
	"""Every portfolio's holdings as Yahoo tickers, sorted; none where Sharesight is not set up."""
	if not configured():
		return []
	return sorted({ticker for portfolio in portfolios() for ticker in portfolio.tickers()})


def cached():
	"""(the portfolios' names, the Yahoo tickers they hold, sorted) from what the cache holds, whatever its age, and
	never a request: for suggestions while a command is typed, which must come at once. Empty where nothing is
	cached."""
	found = _chosen((cache.load(PORTFOLIOS_CACHE) or {}).get('portfolios') or [])
	held = set()
	for portfolio in found:
		report = (cache.load(performance_cache_file(portfolio.id, 0)) or {}).get('report') or {}
		held |= {markets.transform_to_yahoo(each['instrument']['code'], each['instrument']['market_code'])
			for each in report.get('holdings') or []}
	return [portfolio.name for portfolio in found], sorted(held)


def warm():
	"""Fetch afresh the portfolio list and each portfolio's holdings report (days=0), so that a request never waits on
	Sharesight (scheduled: sharesight_warm.py). Returns the portfolios. Raises as the requests do, and then the caches
	it would have replaced stay."""
	found = portfolios(seconds=0)
	for portfolio in found:
		_performance(portfolio.id, 0, seconds=0)
	return found

