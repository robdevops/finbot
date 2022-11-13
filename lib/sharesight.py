import json, os, time
import datetime
import requests
from lib.config import *

time_now = datetime.datetime.today()
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20

class BearerAuth(requests.auth.AuthBase):
    def __init__(self, token):
        self.token = token
    def __call__(self, r):
        r.headers["Authorization"] = "Bearer " + self.token
        return r

def get_token(sharesight_auth):
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
    return data['access_token']

def get_portfolios(token):
    print("Fetching Sharesight portfolios")
    #headers={'Content-type': 'application/json', 'Authorization': 'Bearer ' + token}
    portfolio_dict = {}
    url = "https://api.sharesight.com/api/v3/portfolios"
    try:
        #r = requests.get(url, headers=headers, timeout=config_http_timeout)
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
        if str(portfolio['id']) in config_excluded_portfolios:
            print(portfolio['id'], "(" + portfolio['name'] + ") in exclusion list. Skipping.")
        elif str(portfolio['id']) not in config_included_portfolios and config_included_portfolios:
            print("Exclusion list is defined and does not contain", portfolio['id'], "(" + portfolio['name'] + "). Skipping.")
        else:
            portfolio_dict[portfolio['name']] = portfolio['id']
    if len(portfolio_dict) == 0:
        print("No portfolios found. Exiting.")
        exit(1)
    print(portfolio_dict)
    return portfolio_dict

def get_trades(token, portfolio_name, portfolio_id):
    print("Fetching Sharesight trades for", portfolio_name, end=": ")
    endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
    url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + start_date
    r = requests.get(url, auth=BearerAuth(token), timeout=config_http_timeout)
    data = r.json()
    print(len(data['trades']))
    for trade in data['trades']:
       trade['portfolio'] = portfolio_name
    return data['trades']

def get_holdings(token, portfolio_name, portfolio_id):
    holdings = {}
    print("Fetching Sharesight holdings for", portfolio_name, end=": ")
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
    return holdings

