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
    
    def prepare_ex_dividend_payload(service, market_data):
        payload = []
        emoji = "🤑"
        now = int(time.time())
        soon = now + config_ex_dividend_future_days * 86400
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
                payload.append(f"{emoji} {human_date} {title} ({ticker_link})")
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

    # Fetch holdings from Sharesight, and market data from Yahoo/Finviz
    finviz_output = {}
    yahoo_output = {}
    holdings = sharesight.get_holdings_wrapper(token, portfolios)
    tickers = yahoo.transform_tickers(holdings)
    tickers.update(config_watchlist)
    tickers_au, tickers_world, tickers_us = util.categorise_tickers(tickers)
    yahoo_output = yahoo.fetch(tickers_world)
    finviz_output = finviz.wrapper(tickers_us)
    market_data = {**yahoo_output, **finviz_output}
    market_data = yahoo.fetch_ex_dividends(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing ex-dividend date payload")
        payload = prepare_ex_dividend_payload(service, market_data)
        url = webhooks[service]
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

lambda_handler(1,2)
