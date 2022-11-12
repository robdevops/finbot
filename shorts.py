#!/usr/bin/python3

import json, os, time, re
import datetime
#from dotenv import load_dotenv
import pytz
import requests
from bs4 import BeautifulSoup

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.finviz as finviz

def lambda_handler(event,context):
    time_now = datetime.datetime.today()
    today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
    start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    
    def prepare_shorts_payload(service, market_data):
        payload = []
        emoji = "🩳"
        for ticker in tickers:
            try:
                percent_short = market_data[ticker]['percent_short']
            except:
                continue
            if '.AX' in ticker:
                url = 'https://www.shortman.com.au/stock?q=' + ticker.replace('.AX','') # FIX python 3.9
            else:
                url = 'https://finviz.com/quote.ashx?t=' + ticker
            if float(percent_short) > config_shorts_percent:
                title = market_data[ticker]['title']
                percent_short = str(round(percent_short))
                if service == 'telegram':
                    ticker_link = '<a href="' + url + '">' + ticker + '</a>'
                elif service in {'slack', 'discord'}:
                    ticker_link = '<' + url + '|' + ticker + '>'
                else:
                    ticker_link = ticker
                payload.append(f"{emoji} {title} ({ticker_link}) {percent_short}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if service == 'telegram':
            payload.insert(0, "<b>Highly shorted stock warning:</b>")
        elif service == 'slack':
            payload.insert(0, "*Highly shorted stock warning:*")
        elif service == 'discord':
            payload.insert(0, "**Highly shorted stock warning:**")
        else:
            payload.insert(0, "Highly shorted stock warning:")
        return payload

    def fetch_shortman(market_data):
        print("Fetching ASX shorts from Shortman")
        content = {}
        url = 'https://www.shortman.com.au/downloadeddata/latest.csv'
        try:
            r = requests.get(url, timeout=config_http_timeout)
        except:
            print("Failure fetching", url)
            return {}
        if r.status_code == 200:
            print(r.status_code, "success shortman")
        else:
            print(r.status_code, "error communicating with", url)
            return {}
        csv = r.content.decode('utf-8')
        csv = csv.split('\r\n')
        csv.pop(0) # remove header
        del csv[-1] # remove junk
        for line in csv:
            cells = line.split(',')
            title = cells[0]
            ticker = cells[1] + '.AX'
            positions = cells[2]
            on_issue = cells[3]
            short_percent = cells[4]
            content[ticker] = float(short_percent)
            if ticker in market_data:
                market_data[ticker]['percent_short'] = float(short_percent) # naughty update global dict
        return

    # MAIN #
    token = sharesight.get_token(sharesight_auth)
    portfolios = sharesight.get_portfolios(token)
    weekday = datetime.datetime.today().strftime('%A').lower()

    # Fetch holdings from Sharesight, and market data from Yahoo/Finviz
    holdings = {}
    tickers = []    
    tickers_us = [] # used by fetch_finviz()
    tickers_au = [] # used by fetch_shortman()
    tickers_world = [] # used by fetch_yahoo()
    finviz_output = {}
    for portfolio_name in portfolios:
        portfolio_id = portfolios[portfolio_name]
        holdings = {**holdings, **sharesight.get_holdings(token, portfolio_name, portfolio_id)} # FIX python 3.9
    tickers = yahoo.transform_tickers(holdings)
    for ticker in tickers:
        if '.AX' in ticker:
            tickers_au.append(ticker)
        if '.' in ticker:
            tickers_world.append(ticker)
        else:
            tickers_us.append(ticker)

    if tickers_world:
        yahoo_output = yahoo.fetch(tickers_world)

    chunks = util.chunker(tickers_us, 20)
    print("Fetching", len(tickers_us), "holdings from Finviz")
    for chunk in chunks:
        finviz_output = {**finviz_output, **finviz.fetch(chunk)} # FIX python 3.9

    market_data = {**yahoo_output, **finviz_output}

    # Fetch ASX shorts
    if tickers_au:
        fetch_shortman(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        url = webhooks[service]
        print(service, "Preparing shorts payload")
        payload = prepare_shorts_payload(service, market_data)
        if len(payload) > 1: # ignore header
            payload_string = '\n'.join(payload)
            print(payload_string)
            chunks = util.chunker(payload, 20)
            webhook.payload_wrapper(service, url, chunks)

    # make google cloud happy
    return True

lambda_handler(1,2)
