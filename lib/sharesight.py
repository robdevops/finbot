import json
import sys
import time
import datetime
import concurrent.futures
import requests
from lib.config import *
import lib.util as util

class BearerAuth(requests.auth.AuthBase):
	def __init__(self, token):
		self.token = token
	def __call__(self, r):
		r.headers["Authorization"] = "Bearer " + self.token
		return r

def get_token():
	if config_cache:
		cacheFile = "finbot_sharesight_token.json"
		cache = util.json_load(cacheFile)
		if cache:
			cache_expiry = datetime.datetime.fromtimestamp(cache['created_at'] + cache['expires_in'])
			ttl = cache_expiry - datetime.datetime.now()
			if ttl > datetime.timedelta(seconds=20):
				print("cache hit:", cacheFile, "TTL:", util.td_to_human(ttl), file=sys.stderr) if debug else None
				return cache['access_token']
			else:
				print("cache miss:", cacheFile, file=sys.stderr) if debug else None

	print("Fetching Sharesight auth token")
	url = "https://api.sharesight.com/oauth2/token"
	try:
		r = requests.post(url, data=config_sharesight_auth, timeout=config_http_timeout)
	except Exception as e:
		print("Error", str(e), url, file=sys.stderr)
		raise RuntimeError(f"Sharesight auth request failed: {e}")
	if r.status_code != 200:
		print(r.status_code, "error", url, file=sys.stderr)
	data = r.json()
	if 'error' in data:
		print("Sharesight error:", data['error_code'], data['error'], file=sys.stderr)
		raise RuntimeError(f"Sharesight auth error: {data['error']}")
	if config_cache and 'access_token' in data:
		util.json_write(cacheFile, data)
	print("Got Sharesight token:", data['access_token'], file=sys.stderr) if debug else None
	return data['access_token']

def get_portfolios():
	portfolio_dict = {}
	cache = None
	if config_cache:
		cache_file = "finbot_sharesight_portfolios.json"
		cache = util.read_cache(cache_file, config_cache_seconds)
		if cache:
			data = cache
	if not cache or not config_cache:
		token = get_token()
		print("Fetching Sharesight portfolios")
		url = "https://api.sharesight.com/api/v3/portfolios"
		try:
			r = requests.get(url, headers={'Content-type': 'application/json'}, auth=BearerAuth(token), timeout=config_http_timeout)
		except Exception as e:
			print("Error", str(e), url, file=sys.stderr)
			raise RuntimeError(f"Sharesight portfolios request failed: {e}")
		if r.status_code != 200:
			print(r.status_code, "error", url, file=sys.stderr)
		data = r.json()
		if 'error' in data:
			print("Sharesight error:", data['error_code'], data['error'], file=sys.stderr)
			raise RuntimeError(f"Sharesight portfolios error: {data['error']}")
		if config_cache and 'portfolios' in data:
			util.json_write(cache_file, data)
	for portfolio in data['portfolios']:
		print("Found portfolio:", portfolio['name'], file=sys.stderr)
		if str(portfolio['id']) in config_exclude_portfolios:
			print(portfolio['id'], "(" + portfolio['name'] + ") in exclusion list. Skipping.")
		elif str(portfolio['id']) not in config_include_portfolios and config_include_portfolios:
			print("Exclusion list is defined and does not contain", portfolio['id'], "(" + portfolio['name'] + "). Skipping.")
		else:
			portfolio_dict[portfolio['name']] = portfolio['id']
	if not len(portfolio_dict):
		print("No portfolios found. Exiting.", file=sys.stderr)
		raise RuntimeError(f"No Sharesight portfolios found")
	print(portfolio_dict)
	return portfolio_dict

def get_trades(portfolio_name, portfolio_id, days=config_past_days):
	if config_cache:
		cache_file = "finbot_sharesight_trades_" + str(portfolio_id) + "_" + str(days) + ".json"
		cache = util.read_cache(cache_file, 299) # max freq 5 min
		if cache:
			return cache['trades']
	start_date = datetime.datetime.now() - datetime.timedelta(days=days)
	start_date = start_date.strftime('%Y-%m-%d') # 2022-08-20
	token = get_token()
	print("Fetching Sharesight trades for", portfolio_name, end=": ")
	url = 'https://api.sharesight.com/api/v2/portfolios/'
	url = url + str(portfolio_id) + '/trades.json' + '?start_date=' + start_date
	try:
		r = requests.get(url, auth=BearerAuth(token), timeout=config_http_timeout)
	except Exception as e:
		print("Error", str(e), url, file=sys.stderr)
		raise RuntimeError(f"Sharesight trades request failed: {e}")
	if r.status_code != 200:
		print(r.status_code, "error", url, file=sys.stderr)
	data = r.json()
	print(len(data['trades']))
	if 'error' in data:
		print("Sharesight error:", data['error_code'], data['error'], file=sys.stderr)
		raise RuntimeError(f"Sharesight trades error: {data['error']}")
	for trade in data['trades']:
		trade['portfolio'] = portfolio_name # inject custom field
	if config_cache and 'trades' in data:
		util.json_write(cache_file, data)
	return data['trades']

def get_holdings(portfolio_name, portfolio_id):
	tickers = set()
	holdings = get_holdings_new(portfolio_name, portfolio_id)
	for holding in holdings:
		symbol = holdings[holding]['code']
		market = holdings[holding]['market_code']
		ticker = util.transform_to_yahoo(symbol, market)
		tickers.add(ticker)
	return sorted(tickers)

def get_holdings_new(portfolio_name, portfolio_id):
	print("Fetching Sharesight holdings", portfolio_name, end=": ")
	data = get_performance(portfolio_id, 0)
	print(len(data['report']['holdings']))
	holdings = {}
	for item in data['report']['holdings']:
		code = item['instrument']['code']
		market_code = item['instrument']['market_code']
		symbol = code + ":" + market_code
		holdings[symbol] = item['instrument']
		holdings[symbol]['holding_id'] = item['id']
	return holdings

def get_holdings_wrapper():
	tickers = set()
	portfolios = get_portfolios()
	if not portfolios:
		return None
	for portfolio_name, portfolio_id in portfolios.items():
		tickers.update(get_holdings(portfolio_name, portfolio_id))
	tickers = sorted(set(tickers))
	return tickers

def get_performance(portfolio_id, days, config_cache_seconds=299):
	start_date = datetime.datetime.now() - datetime.timedelta(days=days)
	start_date = start_date.strftime('%Y-%m-%d') # 2023-04-25
	if config_cache:
		cache_file = "finbot_sharesight_performance_" + str(portfolio_id) + "_" + str(days) + '.json'
		cache = util.read_cache(cache_file, config_cache_seconds)
		if cache:
			return cache
	token = get_token()
	endpoint = 'https://api.sharesight.com/api/v3/portfolios/'
	url = endpoint + str(portfolio_id) + '/performance?grouping=ungrouped&start_date=' + start_date
	for attempt in range(5): # Sharesight allows only a few requests in flight at once; back off and retry when it says so
		try:
			r = requests.get(url, auth=BearerAuth(token), timeout=config_http_timeout)
		except Exception as e:
			print("Error", str(e), url, file=sys.stderr)
			raise RuntimeError(f"Sharesight performance request failed: {e}")
		if r.status_code != 200:
			print(r.status_code, "error", url, file=sys.stderr)
		data = r.json()
		if 'error' in data and 'parallel' in str(data['error']).lower() and attempt < 4:
			print("Sharesight busy:", data['error'], "- retrying", file=sys.stderr)
			time.sleep(1 + attempt)
			continue
		break
	if 'error' in data:
		print("Sharesight error:", data['error_code'], data['error'], file=sys.stderr)
		raise RuntimeError(f"Sharesight performance error: {data['error']}")
	if config_cache and 'report' in data:
		util.json_write(cache_file, data)
	return data

MAX_PARALLEL = 2 # Sharesight rejects more than ~3 concurrent requests per account, and other chats may be querying too

def get_performance_wrapper(days=config_past_days):
	performance = {}
	portfolios = get_portfolios()
	get_token() # make sure there is a fresh token before the requests below fan out and would each fetch their own
	with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(portfolios), MAX_PARALLEL)) as executor: # a couple of requests at a time
		futures = {portfolio_id: executor.submit(get_performance, portfolio_id, days) for portfolio_id in portfolios.values()}
		for portfolio_id, future in futures.items():
			performance[portfolio_id] = future.result()
			if not performance[portfolio_id]:
				print("Could not get performance for portfolio:", portfolio_id, file=sys.stderr)
				raise RuntimeError(f"Sharesight returned no performance for portfolio {portfolio_id}")
	return performance
