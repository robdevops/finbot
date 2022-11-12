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
    
    def prepare_ex_dividend_payload(service, market_data):
        payload = []
        emoji = "🤑"
        now = int(time.time())
        soon = now + config_ex_dividend_days * 86400
        for ticker in market_data:
            try:
                timestamp = market_data[ticker]['ex_dividend_date']
            except KeyError:
                continue
            url = 'https://finance.yahoo.com/quote/' + ticker
            title = market_data[ticker]['title']
            if timestamp > now and timestamp < soon:
                human_date = time.strftime('%b %d', time.localtime(timestamp)) # Sep 08
                if service == 'telegram':
                    ticker_link = '<a href="' + url + '">' + ticker + '</a>'
                elif service in {'slack', 'discord'}:
                    ticker_link = '<' + url + '|' + ticker + '>'
                else:
                    ticker_link = ticker
                payload.append(f"{emoji} {title} ({ticker_link}) {human_date}")
        payload.sort()
        if service == 'telegram':
            payload.insert(0, "<b>Ex-dividend dates. Avoid buy on:</b>")
        elif service == 'slack':
            payload.insert(0, "*Ex-dividend dates. Avoid buy on:*")
        elif service == 'discord':
            payload.insert(0, "**Ex-dividend dates. Avoid buy on:**")
        else:
            payload.insert(0, "Ex-dividend dates. Avoid buy on:")
        return payload

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
    yahoo_output = yahoo.fetch(tickers_world)
    chunks = util.chunker(tickers_us, 20)
    print("Fetching", len(tickers_us), "holdings from Finviz")
    for chunk in chunks:
        finviz_output = {**finviz_output, **finviz.fetch(chunk)} # FIX python 3.9
    market_data = {**yahoo_output, **finviz_output}

    # Fetch ex_dividend_dates from Yahoo
    yahoo.fetch_ex_dividends(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        url = webhooks[service]
        print(service, "Preparing ex-dividend date payload")
        payload = prepare_ex_dividend_payload(service, market_data)
        if len(payload) > 1: # ignore header
            payload_string = '\n'.join(payload)
            print(payload_string)
            chunks = util.chunker(payload, 20)
            webhook.payload_wrapper(service, url, chunks)

    # make google cloud happy
    return True

lambda_handler(1,2)
