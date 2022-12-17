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
                if percent < 0:
                    emoji = "🔻"
                else:
                    emoji = "⬆️ "
                percent = str(round(percent))
                flag = util.flag_from_ticker(ticker)
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {title} ({yahoo_link}) {percent}%")
        print(len(payload), f"holdings moved by at least {config_price_percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        message = f'Price alerts (intraday) over {config_price_percent}%:'
        message = webhook.bold(message, service)
        payload.insert(0, message)
        return payload


    # MAIN #

    tickers = sharesight.get_holdings_wrapper()
    tickers.update(util.watchlist_load())
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
