#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.finviz as finviz
import lib.shortman as shortman

def lambda_handler(event,context):
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
    market_data = shortman.fetch(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing shorts payload")
        payload = prepare_shorts_payload(service, market_data)
        url = webhooks[service]
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

lambda_handler(1,2)
