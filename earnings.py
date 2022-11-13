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
    
    def prepare_earnings_payload(service):
        payload = []
        emoji = "📣"
        finviz_date_list = []
        now = int(time.time())
        soon = now + config_earnings_future_days * 86400
        today = datetime.datetime.today()
        this_month = str(today.strftime('%b'))
        this_year = str(today.strftime('%Y'))
        next_year = str(int(this_year) + 1)
        for ticker in market_data:
            title = market_data[ticker]['title']
            url = 'https://finance.yahoo.com/quote/' + ticker
            before_after_close = ''
            try:
                earnings_date = market_data[ticker]['earnings_date']
            except KeyError:
                continue
            if earnings_date == '-':
                continue
            if earnings_date:
                if '/a' in str(earnings_date) or '/b' in str(earnings_date):
                    human_date = earnings_date
                    finviz_date_list = str(earnings_date).split('/')
                    finviz_suffix = finviz_date_list[1]
                    finviz_date_list = finviz_date_list[0].split(' ')
                    finviz_month = finviz_date_list[0]
                    finviz_day = finviz_date_list[1]
                    if this_month in {'Oct','Nov','Dec'} and finviz_month in {'Jan','Feb','Mar'}:
                        finviz_year = next_year # guess Finviz year
                    else:
                        finviz_year = this_year
                    finviz_date = finviz_year + finviz_month + finviz_day
                    data_seconds = time.mktime(datetime.datetime.strptime(finviz_date,"%Y%b%d").timetuple())
                    if finviz_suffix == 'b':
                        data_seconds = data_seconds + 3600 * 9 # 9 AM
                    if finviz_suffix == 'a':
                        data_seconds = data_seconds + 3600 * 18 # 6 PM
                else: # yahoo
                    data_seconds = int(earnings_date)
                    data_seconds = data_seconds + 3600 * 4 # allow for Yahoo's inaccuracy
                    human_date = time.strftime('%b %d', time.localtime(data_seconds)) # Sep 08
                if data_seconds > now and data_seconds < soon:
                    if service == 'telegram':
                        ticker_link = '<a href="' + url + '">' + ticker + '</a>'
                    elif service in {'slack', 'discord'}:
                        ticker_link = '<' + url + '|' + ticker + '>'
                    else:
                        ticker_link = ticker
                    payload.append(f"{emoji} {title} ({ticker_link}) {human_date}")
        def last_two_columns(e):
            return e.split()[-2:]
        payload.sort(key=last_two_columns)
        if service == 'telegram':
            payload.insert(0, "<b>Upcoming earnings:</b>")
        elif service == 'slack':
            payload.insert(0, "*Upcoming earnings:*")
        elif service == 'discord':
            payload.insert(0, "**Upcoming earnings:**")
        else:
            payload.insert(0, "Upcoming earnings:")
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
        print(service, "Preparing earnings date payload")
        payload = prepare_earnings_payload(service)
        if len(payload) > 1: # ignore header
            payload_string = '\n'.join(payload)
            print(payload_string)
            chunks = util.chunker(payload, 20)
            webhook.payload_wrapper(service, url, chunks)

    # make google cloud happy
    return True

lambda_handler(1,2)
