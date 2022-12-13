import json
import datetime
import requests
from lib.config import *
import lib.util as util
import time

time_now = datetime.datetime.today()
now = int(time.time())
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20

class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token):
        self.token = token
    def __call__(self, r):
        r.headers["Authorization"] = "Bearer " + self.token
        return r

def get_token():
    cache_file = config_cache_dir + "/sharesight_token_cache.json"
    cache = util.read_cache(cache_file, 1740)
    if config_cache and cache:
        cache_expiry = cache['created_at'] + cache['expires_in']
        if cache_expiry < now + 60:
            print("token cache has expired")
        else:
            return cache['access_token']
    print("Fetching Sharesight auth token")
    try:
        r = requests.post("https://api.sharesight.com/oauth2/token", data=sharesight_auth, timeout=config_http_timeout)
    except:
        print("Failed to get Sharesight access token")
        exit(1)
    if r.status_code == 200:
        print(r.status_code, "success sharesight")
    else:
        print(r.status_code, "Could not fetch Sharesight token. Check config in .env file")
        exit(1)
    data = r.json()
    util.write_cache(cache_file, data)
    print(data)
    return data['access_token']

def get_portfolios():
    cache_file = config_cache_dir + "/sharesight_portfolio_cache.json"
    cache = util.read_cache(cache_file, config_cache_seconds)
    if config_cache and cache:
        print(cache)
        return cache
    print("Fetching Sharesight portfolios")
    token = get_token()
    portfolio_dict = {}
    url = "https://api.sharesight.com/api/v3/portfolios"
    try:
        r = requests.get(url, headers={'Content-type': 'application/json'}, auth=BearerAuth(token), timeout=config_http_timeout)
    except:
        print("Failure talking to Sharesight")
        exit(1)
    if r.status_code == 200:
        print(r.status_code, "success sharesight")
    else:
        print(r.status_code, "error sharesight")
        exit(1)
    data = r.json()
    for portfolio in data['portfolios']:
        if str(portfolio['id']) in config_exclude_portfolios:
            print(portfolio['id'], "(" + portfolio['name'] + ") in exclusion list. Skipping.")
        elif str(portfolio['id']) not in config_include_portfolios and config_include_portfolios:
            print("Exclusion list is defined and does not contain", portfolio['id'], "(" + portfolio['name'] + "). Skipping.")
        else:
            portfolio_dict[portfolio['name']] = portfolio['id']
    if len(portfolio_dict) == 0:
        print("No portfolios found. Exiting.")
        exit(1)
    print(portfolio_dict)
    util.write_cache(cache_file, portfolio_dict)
    return portfolio_dict

def get_trades(portfolio_name, portfolio_id, days=config_past_days):
    # DO NOT CACHE #
    start_date = time_now - datetime.timedelta(days=days)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    print("Fetching Sharesight trades for", portfolio_name, end=": ")
    token = get_token()
    endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
    url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + start_date
    r = requests.get(url, auth=BearerAuth(token), timeout=config_http_timeout)
    data = r.json()
    print(len(data['trades']))
    for trade in data['trades']:
       trade['portfolio'] = portfolio_name
    return data['trades']

def get_holdings(portfolio_name, portfolio_id):
    cache_file = config_cache_dir + "/sharesight_holdings_cache_" + str(portfolio_id) + '.json'
    cache = util.read_cache(cache_file, config_cache_seconds)
    if config_cache and cache:
        print(portfolio_name, end=": ")
        print(len(cache))
        return cache
    print("Fetching Sharesight holdings", portfolio_name, end=": ")
    token = get_token()
    holdings = {}
    endpoint = 'https://api.sharesight.com/api/v3/portfolios/'
    url = endpoint + str(portfolio_id) + '/performance?grouping=ungrouped&start_date=' + today
    r = requests.get(url, auth=BearerAuth(token), timeout=config_http_timeout)
    if r.status_code != 200:
        print(r.status_code, "error")
    data = r.json()
    print(len(data['report']['holdings']))
    for item in data['report']['holdings']:
        code = item['instrument']['code']
        holdings[code] = item['instrument']
    tickers = set()
    for holding in holdings:
        symbol = holdings[holding]['code']
        market = holdings[holding]['market_code']
        ticker = util.transform_ticker(symbol, market)
        tickers.add(ticker)
    tickers = list(tickers)
    tickers.sort()
    util.write_cache(cache_file, tickers)
    return tickers

def get_holdings_wrapper():
    tickers = set()
    portfolios = get_portfolios()
    for portfolio_name in portfolios:
        portfolio_id = int(portfolios[portfolio_name])
        tickers.update(get_holdings(portfolio_name, portfolio_id))
    return tickers

