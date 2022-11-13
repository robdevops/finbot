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
    
    def prepare_price_payload(service, market_data):
        payload = []
        for ticker in market_data:
            percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['title']
            if abs(float(percent)) >= config_price_updates_percent:
                url = 'https://finance.yahoo.com/quote/' + ticker
                if percent < 0:
                    emoji = "🔻"
                else:
                    emoji = "⬆️ "
                percent = str(round(percent))
                if service == 'telegram':
                    ticker_link = '<a href="' + url + '">' + ticker + '</a>'
                elif service in {'slack', 'discord'}:
                    ticker_link = '<' + url + '|' + ticker + '>'
                else:
                    ticker_link = ticker
                payload.append(f"{emoji} {title} ({ticker_link}) {percent}%")
        print(len(payload), f"holdings moved by at least {config_price_updates_percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if service == 'telegram':
            payload.insert(0, "<b>Price alerts (intraday):</b>")
        elif service == 'slack':
            payload.insert(0, "*Price alerts (intraday):*")
        elif service == 'discord':
            payload.insert(0, "**Price alerts (intraday):**")
        else:
            payload.insert(0, "Price alerts (intraday):")
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
    tickers.update(config_watchlist)
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

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        url = webhooks[service]
        if tickers:
            print(service, "Preparing price change payload")
            payload = prepare_price_payload(service, market_data)
            if len(payload) > 1: # ignore header
                payload_string = '\n'.join(payload)
                print(payload_string)
                chunks = util.chunker(payload, 20)
                webhook.payload_wrapper(service, url, chunks)
            else:
                print("No holdings changed by", config_price_updates_percent, "% or more in the last session.")

    # make google cloud happy
    return True

lambda_handler(1,2)
