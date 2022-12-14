#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(event,context):
    def prepare_price_payload(service, market_data):
        payload = []
        for ticker in market_data:
            percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['profile_title']
            if abs(float(percent)) >= config_price_percent:
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
        print(len(payload), f"holdings moved by at least {config_price_percent}%")
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

    tickers = sharesight.get_holdings_wrapper()
    tickers.update(config_watchlist)
    market_data = yahoo.fetch(tickers)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing intraday price payload")
        payload = prepare_price_payload(service, market_data)
        url = webhooks[service]
        if service == "telegram":
            url = url + "sendMessage?chat_id=" + config_telegramChatID
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True


lambda_handler(1,2)
