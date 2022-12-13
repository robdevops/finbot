#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.finviz as finviz

def lambda_handler(telegram_chat_id=config_telegram_chat_id, interactive=False, user='', threshold=config_price_percent):
    def prepare_price_payload(service, market_data):
        postmarket = False
        payload = []
        for ticker in market_data:
            if 'percent_change_premarket' in market_data[ticker]:
                percent = market_data[ticker]['percent_change_premarket']
            elif 'percent_change_postmarket' in market_data[ticker]:
                postmarket = True
                percent = market_data[ticker]['percent_change_postmarket']
            else:
                print("no data for", ticker)
                continue
            title = market_data[ticker]['profile_title']
            if abs(float(percent)) >= threshold:
                url = 'https://finance.yahoo.com/quote/' + ticker
                if percent < 0:
                    emoji = "🔻"
                else:
                    emoji = "⬆️ "
                percent = str(round(percent))
                flag = util.flag_from_ticker(ticker)
                ticker_short = ticker.split('.')[0]
                if service == 'telegram':
                    ticker_link = '<a href="' + url + '">' + ticker + '</a>'
                elif service in {'slack', 'discord'}:
                    ticker_link = '<' + url + '|' + ticker + '>'
                else:
                    ticker_link = ticker
                payload.append(f"{emoji} {title} ({ticker_link}) {percent}%")
        print(len(payload), f"holdings moved by at least {threshold}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if interactive:
            payload.insert(0, f"<b>@{user} stocks moving at least {threshold}% pre-market</b>")
            if len(payload) == 1:
                payload.append(f"No price movements meet threshold 🛑")
        elif service == 'telegram':
            payload.insert(0, "<b>Price alerts (pre-market):</b>")
        elif service == 'slack':
            payload.insert(0, "*Price alerts (pre-market):*")
        elif service == 'discord':
            payload.insert(0, "**Price alerts (pre-market):**")
        else:
            payload.insert(0, "Price alerts (pre-market):")
        return payload


    # MAIN #
    token = sharesight.get_token(sharesight_auth)
    portfolios = sharesight.get_portfolios(token)

    # Fetch holdings from Sharesight, and market data from Yahoo/Finviz
    finviz_output = {}
    yahoo_output = {}
    holdings = sharesight.get_holdings_wrapper(token, portfolios)
    tickers = yahoo.transform_ticker_wrapper(holdings)
    tickers.update(config_watchlist)
    tickers_au, tickers_world, tickers_us = util.categorise_tickers(tickers)
    market_data = yahoo.fetch(tickers_us)
    #finviz_output = finviz.wrapper(tickers_us)
    #market_data = {**yahoo_output, **finviz_output}

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing intraday price payload")
        payload = prepare_price_payload(service, market_data)
        url = webhooks[service]
        if service == "telegram":
            url = url + "sendMessage?chat_id=" + str(telegram_chat_id)
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()

