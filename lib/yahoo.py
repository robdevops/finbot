#!/usr/bin/python3

import json
import requests
import datetime
import time

from lib.config import *
import lib.util as util

time_now = datetime.datetime.today()
now = time_now.timestamp()

def transform_ticker_wrapper(holdings):
    tickers = set()
    for holding in holdings:
        symbol = holdings[holding]['code']
        market = holdings[holding]['market_code']
        ticker = transform_ticker(symbol, market)
        tickers.add(ticker)
    return tickers
    
def transform_ticker(ticker, market):
    if market == 'ASX':
        ticker = ticker + '.AX'
    if market == 'HKG':
        ticker = ticker + '.HK'
    if market == 'KRX':
        ticker = ticker + '.KS'
    if market == 'KOSDAQ':
        ticker = ticker + '.KQ'
    if market == 'LSE':
        ticker = ticker + '.L'
    if market == 'TAI':
        ticker = ticker + '.TW'
    return ticker

def fetch(tickers):
    print("Fetching Yahoo data for " + str(len(tickers)) + " global holdings")
    yahoo_output = {}
    yahoo_urls = ['https://query1.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers)]
    yahoo_urls.append('https://query2.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers))
    headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    for url in yahoo_urls:
        print("Fetching", url)
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
        except Exception as e:
            print(e)
        else:
            if r.status_code == 200:
                print(r.status_code, "success yahoo")
            else:
                print(r.status_code, "returned by", url)
                continue
            break
    else:
        print("Exhausted Yahoo API attempts. Giving up")
        return False
    data = r.json()
    data = data['quoteResponse']
    data = data['result']
    for item in data:
        ticker = item['symbol']
        title = item['longName']
        percent_change = round(float(item['regularMarketChangePercent']), 2)
        currency = item['currency']
        try:
            dividend = float(item['trailingAnnualDividendRate'])
        except (KeyError, IndexError):
            dividend = float(0)
        title = util.transform_title(title)
        yahoo_output[ticker] = { 'title': title, 'ticker': ticker, 'percent_change': percent_change, 'dividend': dividend, 'currency': currency }
        # optional fields
        try:
            percent_change_premarket = item['preMarketChangePercent']
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["percent_change_premarket"] = round(percent_change_premarket, 2)
        try:
            percent_change_postmarket = item['postMarketChangePercent']
        except (KeyError, IndexError):
            pass
        else:
            print(percent_change_postmarket)
            yahoo_output[ticker]["percent_change_postmarket"] = round(percent_change_postmarket, 2)
        try:
            market_cap = round(float(item['marketCap']))
        except (KeyError, IndexError):
            pass
        else:
            market_cap = f"{market_cap:,}"
            yahoo_output[ticker]["market_cap"] = market_cap
        try:
            pe = round(item['forwardPE'])
        except:
            pass
        else:
            yahoo_output[ticker]["pe"] = pe
        try:
            earningsTimestamp = item['earningsTimestamp']
            earningsTimestampStart = item['earningsTimestampStart']
            earningsTimestampEnd = item['earningsTimestampEnd']
        except (KeyError, IndexError):
            continue
        if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd:
            yahoo_output[ticker]["earnings_date"] = earningsTimestamp
    return yahoo_output

def fetch_ex_dividends(market_data):
    cache_file = config_cache_dir + "/sharesight_ex_dividends_cache"
    cache = util.read_cache(cache_file)
    if cache:
        print("Fetching ex-dividend dates from cache:", cache_file)
        return cache
    local_market_data = market_data.copy()
    print("Fetching ex-dividend dates from Yahoo")
    base_url = 'https://query1.finance.yahoo.com/v10/finance/quoteSummary/'
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    for ticker in market_data:
        yahoo_urls = [base_url + ticker + '?modules=summaryDetail']
        yahoo_urls.append(base_url + ticker + '?modules=summaryDetail')
        print('.', sep=' ', end='', flush=True)
        if market_data[ticker]['dividend'] > 0:
            time.sleep(0.1)
            for url in yahoo_urls:
                try:
                    r = requests.get(url, headers=headers, timeout=config_http_timeout)
                except Exception as e:
                    print(e)
                else:
                    if r.status_code != 200:
                        print(r.status_code, "error", ticker, url)
                        continue
                    break
            else:
                print("Exhausted Yahoo API attempts. Giving up")
                return False
            data = r.json()
            data = data['quoteSummary']
            data = data['result']
            for item in data:
                try:
                    timestamp = item['summaryDetail']['exDividendDate']['raw']
                except (KeyError, TypeError):
                    pass
                else:
                    local_market_data[ticker]['ex_dividend_date'] = timestamp
    print("")
    util.write_cache(cache_file, local_market_data)
    return local_market_data

