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
from lib import formats
from lib import markets
from lib import net
from lib import yahoo

API = 'https://api.sharesight.com/'
MAX_CONCURRENT = 1 # Sharesight refuses parallel requests beyond a few per account: one at a time, whoever asks
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
TOKEN = 'finbot_sharesight_token.json' # good until the expiry it carries, whatever the cache setting
TOKEN_MARGIN = 20 # seconds a kept token must have left to be used: one about to expire is renewed first
_auth = threading.Lock() # one token request at a time, or two threads would each ask for one
PORTFOLIOS_CACHE = 'finbot_sharesight_portfolios.json' # good for the cache_seconds setting
TRADES_SECONDS = 299 # trades are asked for afresh after 5 minutes, so that a trades job every 5 sees each new one
LARGEST = 'finbot_sharesight_largest.json' # what each portfolio's holdings are worth in US dollars: see largest()
_largest_lock = threading.Lock() # one change of LARGEST at a time: two portfolios' reports can arrive together


class Refused(RuntimeError):
	"""Sharesight refused a request's credentials (a 401): an access token revoked, say."""


def _request(path, what, expect, **kwargs):
	"""Sharesight's answer to a request (a POST with data=, else a GET), checked to hold `expect`: one request at a
	time (MAX_CONCURRENT), tried again while Sharesight says too many are in flight (five tries in all). Raises
	RuntimeError naming `what` when Sharesight cannot be reached, or answers with an error (Refused for a 401), or
	without `expect`."""
	for attempt in range(5):
		with _request_slots:
			r = net.answer('Sharesight', what, API + path, **kwargs)
		data = net.json_answer(r, 'Sharesight', what) # an HTML error page raises
		error = data.get('error') if isinstance(data, dict) else None
		if not (error and 'parallel' in str(error).lower() and attempt < 4):
			break
		log.warn("Sharesight busy:", error, "- retrying")
		time.sleep(1 + attempt)
	if error: # an OAuth error describes itself too
		why = ': '.join(str(data[key]) for key in ('error', 'error_description') if data.get(key))
	elif r.status_code != 200 or not isinstance(data, dict) or expect not in data:
		why = f"a {r.status_code} answer without {expect}"
	else:
		return data
	raise (Refused if r.status_code == 401 else RuntimeError)(f"Sharesight {what}: {why}")


def _token(refused=None):
	"""An access token for Sharesight's API: the one kept (TOKEN) while it has more than TOKEN_MARGIN seconds left,
	unless it is the one Sharesight `refused`; else a new one, for the client's keys. One thread at a time: one that
	waited while another renewed the token takes the new one."""
	with _auth:
		kept = cache.load(TOKEN)
		if (kept and kept['access_token'] != refused and
				kept['created_at'] + kept['expires_in'] - time.time() > TOKEN_MARGIN):
			return kept['access_token']
		data = _request('oauth2/token', 'auth', 'access_token', data={'grant_type': 'client_credentials',
			'client_id': config.env.sharesight_client_id, 'client_secret': config.env.sharesight_client_secret,
			'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob'})
		cache.write(TOKEN, data)
		return data['access_token']


def _api(path, what, expect):
	"""Sharesight's answer to an API query (path: under api/, with its query string) with the access token, and with a
	new one once when Sharesight refuses it; see _request."""
	token = _token()
	try:
		return _request('api/' + path, what, expect, headers={'Authorization': 'Bearer ' + token})
	except Refused:
		return _request('api/' + path, what, expect, headers={'Authorization': 'Bearer ' + _token(refused=token)})


def _portfolios(seconds=None):
	"""Sharesight's list of every portfolio, from the cache while under `seconds` old (cache_seconds when None)."""
	fetch = lambda: _api('v3/portfolios', 'portfolios', 'portfolios')
	return cache.cached(PORTFOLIOS_CACHE, seconds, fetch)['portfolios']


def performance_cache_file(portfolio_id, days):
	"""The cache file of a portfolio's performance report over `days`."""
	return f"finbot_sharesight_performance_{portfolio_id}_{days}.json"


def _since(days):
	"""The date `days` ago, as Sharesight takes it: 2023-04-25."""
	return (formats.today() - datetime.timedelta(days=days)).isoformat()


def _performance(portfolio_id, days=None, seconds=None):
	"""Sharesight's performance report of a portfolio since `days` ago (0: today's holdings; past_days when None), from
	the cache while under `seconds` old (the performance_cache_seconds setting when None)."""
	if days is None:
		days = config.settings.past_days
	query = f'v3/portfolios/{portfolio_id}/performance?grouping=ungrouped&start_date={_since(days)}'
	def fetch():
		"""Ask Sharesight for the report; a holdings report (days 0) also notes what its holdings are worth."""
		data = _api(query, f'performance of portfolio {portfolio_id}', 'report')
		if days == 0:
			_note_values(portfolio_id, data['report'])
		return data
	if seconds is None:
		seconds = config.settings.performance_cache_seconds
	return cache.cached(performance_cache_file(portfolio_id, days), seconds, fetch)['report']


def _note_values(portfolio_id, report):
	"""Keep what the holdings of a portfolio's holdings report are worth in US dollars (their values are in the report's
	currency), for largest(); with the cache setting on. A failure (Yahoo's rate, the write) is only logged."""
	if not config.settings.cache:
		return
	try:
		code = (report.get('currency') or {}).get('code')
		rate = yahoo.usd_rates([code]).get(code)
		if not rate:
			raise RuntimeError(f"no US dollar rate for {code}")
		worth = {}
		for each in report.get('holdings') or []:
			if each.get('value') is not None and float(each['value']) > 0:
				ticker = _ticker(each['instrument'])
				worth[ticker] = worth.get(ticker, 0.0) + float(each['value']) * rate
		with _largest_lock:
			kept = cache.load(LARGEST) or {}
			kept.setdefault('portfolios', {})[str(portfolio_id)] = worth
			cache.write(LARGEST, kept)
	except Exception as e:
		log.warn(f"Sharesight: could not note the holdings of portfolio {portfolio_id} in US dollars:", e)


def largest():
	"""The Yahoo ticker held in the biggest amount, in US dollars, over the portfolios to report on, as their last
	holdings reports left it (a ticker in several portfolios counts them all); None where there is none. Reads what
	was kept (_note_values) and never asks anyone, and never raises."""
	try:
		totals = {}
		for portfolio_id, worth in ((cache.load(LARGEST) or {}).get('portfolios') or {}).items():
			if _wanted(portfolio_id):
				for ticker, value in worth.items():
					totals[ticker] = totals.get(ticker, 0.0) + value
		return max(totals, key=lambda ticker: (totals[ticker], ticker)) if totals else None
	except Exception as e:
		log.warn("Sharesight: cannot read the biggest holding:", e)


def note_cached():
	"""Note, for largest(), the holdings reports the cache already holds (whatever their age), as a start does when
	nothing is noted yet (the file survives a restart, so a start with it changes nothing): a warm job fetches a report
	afresh only on its schedule. Asks no one but Yahoo, for a rate (cached); nothing without Sharesight or the cache
	setting."""
	if not (configured() and config.settings.cache) or cache.load(LARGEST):
		return
	for portfolio, report in _cached_reports():
		if report:
			_note_values(portfolio.id, report)


def _trades(portfolio_id, days=None):
	"""Sharesight's trades in a portfolio over the past `days` (past_days when None), from the cache while under 5
	minutes old."""
	if days is None:
		days = config.settings.past_days
	query = f'v2/portfolios/{portfolio_id}/trades.json?start_date={_since(days)}'
	fetch = lambda: _api(query, 'trades', 'trades')
	return cache.cached(f"finbot_sharesight_trades_{portfolio_id}_{days}.json", TRADES_SECONDS, fetch)['trades']


class NotSetUp(answer.Answer, RuntimeError):
	"""Sharesight is not set up (configured): what needs it says so, as an answer."""
	def __init__(self):
		"""The answer: what is missing, and where it goes."""
		super().__init__('Sharesight is not set up: its keys go in finbot.env (doc/configuration.md)')


def configured():
	"""Whether Sharesight is set up, its keys in finbot.env: without, a chat's reports cover its watchlist alone."""
	return bool(config.env.sharesight_client_id)


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
		"""Its capital gain over the past `days` (the past_days setting when None), in percent."""
		return float(_performance(self.id, days)['capital_gain_percent'])

	def holdings(self):
		"""{'CODE:MARKET': Sharesight's instrument, with the holding's id and value added} of what it holds."""
		return {each['instrument']['code'] + ':' + each['instrument']['market_code']:
			each['instrument'] | {'holding_id': each['id'], 'value': each.get('value')}
			for each in _performance(self.id, 0)['holdings']}

	def tickers(self):
		"""What it holds, as Yahoo tickers, sorted."""
		return sorted({_ticker(each) for each in self.holdings().values()})

	def trades(self, days=None):
		"""Its trades of the past `days` (the past_days setting when None), each with the portfolio's name added."""
		return [trade | {'portfolio': self.name} for trade in _trades(self.id, days)]


def _ticker(instrument):
	"""The Yahoo ticker of a Sharesight instrument (its code and market)."""
	return markets.transform_to_yahoo(instrument['code'], instrument['market_code'])


def _wanted(portfolio_id):
	"""Whether a portfolio (by its id) is one to report on, after include_portfolios and exclude_portfolios."""
	include, exclude = config.settings.include_portfolios, config.settings.exclude_portfolios
	return str(portfolio_id) not in exclude and (not include or str(portfolio_id) in include)


def _chosen(listed):
	"""The portfolios of Sharesight's list to report on, after include_portfolios and exclude_portfolios."""
	return [Portfolio(each['name'], each['id']) for each in listed if _wanted(each['id'])]


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
	found = _cached_reports()
	held = {_ticker(each['instrument']) for _, report in found for each in (report or {}).get('holdings') or []}
	return [portfolio.name for portfolio, _ in found], sorted(held)


def _cached_reports():
	"""[(portfolio, its holdings report or None)] of the portfolios to report on, from what the cache holds, whatever
	its age: never a request."""
	return [(portfolio, (cache.load(performance_cache_file(portfolio.id, 0)) or {}).get('report'))
		for portfolio in _chosen((cache.load(PORTFOLIOS_CACHE) or {}).get('portfolios') or [])]


def warm():
	"""Fetch afresh the portfolio list and each portfolio's holdings report (days=0), so that a request never waits on
	Sharesight (scheduled: sharesight_warm.py). Returns the portfolios. Raises as the requests do, and then the caches
	it would have replaced stay."""
	found = portfolios(seconds=0)
	for portfolio in found:
		_performance(portfolio.id, 0, seconds=0)
	with _largest_lock: # a portfolio that is gone no longer counts towards largest()
		kept = cache.load(LARGEST) or {}
		listed = {str(portfolio.id) for portfolio in found}
		if kept.get('portfolios') and not set(kept['portfolios']) <= listed:
			kept['portfolios'] = {each: worth for each, worth in kept['portfolios'].items() if each in listed}
			cache.write(LARGEST, kept)
	return found

