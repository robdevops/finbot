#!/usr/bin/python3

import json, os, time, re
import datetime
#from dotenv import load_dotenv
import pytz
import requests

from lib.config import *
import lib.util as util

time_now = datetime.datetime.today()
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20

def transform_tickers(holdings):
    tickers = set()
    for holding in holdings:
        symbol = holdings[holding]['code']
        market = holdings[holding]['market_code']
        if market == 'ASX':
            tickers.add(symbol + '.AX')
        if market == 'HKG':
            tickers.add(symbol + '.HK')
        if market == 'KRX':
            tickers.add(symbol + '.KS')
        if market == 'KOSDAQ':
            tickers.add(symbol + '.KQ')
        if market == 'LSE':
            tickers.add(symbol + '.L')
        if market == 'TAI':
            tickers.add(symbol + '.TW')
        if market in {'NASDAQ', 'NYSE', 'BATS'}:
            tickers.add(symbol)
        else:
            continue
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
        try:
            ticker = item['symbol']
            title = item['longName']
            percent_change = item['regularMarketChangePercent']
        except (KeyError, IndexError):
            print("Yahoo: ", ticker, " not found. Skipping")
            continue
        try:
            dividend = float(item['trailingAnnualDividendRate'])
        except (KeyError, IndexError):
            dividend = float(0)
        title = util.transform_title(title)
        try:
            earningsTimestamp = item['earningsTimestamp']
            earningsTimestampStart = item['earningsTimestampStart']
            earningsTimestampEnd = item['earningsTimestampEnd']
        except (KeyError, IndexError):
            yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend} # no date
            continue
        if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd:
            yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend, 'earnings_date': earningsTimestamp}
        else: # approximate date
            yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend}
    return yahoo_output

def fetch_ex_dividends(market_data):
    print("Fetching ex-dividend dates from Yahoo")
    base_url = 'https://query1.finance.yahoo.com/v10/finance/quoteSummary/'
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    for ticker in market_data:
        yahoo_urls = [base_url + ticker + '?modules=summaryDetail']
        yahoo_urls.append(base_url + ticker + '?modules=summaryDetail')
        if market_data[ticker]['dividend'] > 0:
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
                    timestamp == ''
                market_data[ticker]['ex_dividend_date'] = timestamp # naughty update global dict
    return

