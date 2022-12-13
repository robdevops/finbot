#!/usr/bin/python3

import json, time

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.finviz as finviz

def lambda_handler(event,context):
    def prepare_ex_dividend_payload(service, market_data):
        payload = []
        emoji = "⚠️"
        now = int(time.time())
        soon = now + config_future_days * 86400
        for ticker in market_data:
            try:
                timestamp = market_data[ticker]['ex_dividend_date']
            except KeyError:
                continue
            url = 'https://finance.yahoo.com/quote/' + ticker
            title = market_data[ticker]['profile_title']
            flag = util.flag_from_ticker(ticker)
            ticker_short = ticker.split('.')[0]
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
            payload.insert(0, "<b>Ex-dividend dates. Avoid buy before:</b>")
        elif service == 'slack':
            payload.insert(0, "*Ex-dividend dates. Avoid buy before:*")
        elif service == 'discord':
            payload.insert(0, "**Ex-dividend dates. Avoid buy before:**")
        else:
            payload.insert(0, "Ex-dividend dates. Avoid buy before:")
        return payload

    # MAIN #

    # Fetch holdings from Sharesight, and market data from Yahoo/Finviz
    finviz_output = {}
    yahoo_output = {}
    tickers = sharesight.get_holdings_wrapper()
    tickers.update(config_watchlist)
    tickers_au, tickers_world, tickers_us = util.categorise_tickers(tickers)
    for ticker in tickers:
        try:
            yahoo_output = { **yahoo_output, **yahoo.fetch_detail(ticker) }
        except (TypeError):
            pass
    finviz_output = finviz.wrapper(tickers_us)
    market_data = {**yahoo_output, **finviz_output}
    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing ex-dividend date payload")
        payload = prepare_ex_dividend_payload(service, market_data)
        url = webhooks[service]
        if service == "telegram":
            url = url + "sendMessage?chat_id=" + config_telegram_chat_id
        webhook.payload_wrapper(service, url, payload)
    # make google cloud happy
    return True

lambda_handler(1,2)
