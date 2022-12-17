#!/usr/bin/python3

import json, time
import datetime

from lib.config import *
import lib.sharesight as sharesight
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo

def lambda_handler(event,context):
    def prepare_earnings_payload(service):
        payload = []
        emoji = "📣"
        now = int(time.time())
        soon = now + config_future_days * 86400
        for ticker in market_data:
            title = market_data[ticker]['profile_title']
            try:
                earnings_date = int(market_data[ticker]['earnings_date'])
            except (KeyError, ValueError):
                continue
            if earnings_date:
                data_seconds = earnings_date + 3600 * 4 # allow for Yahoo's inaccuracy
                human_date = time.strftime('%b %d', time.localtime(data_seconds)) # Sep 08
            if data_seconds > now and data_seconds < soon:
                flag = util.flag_from_ticker(ticker)
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {title} ({yahoo_link}) {human_date}")
        def last_two_columns(e):
            return e.split()[-2:]
        payload.sort(key=last_two_columns)
        if len(payload):
            message = 'Upcoming earnings:'
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
        print(service, "Preparing earnings date payload")
        payload = prepare_earnings_payload(service)
        if service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
        elif service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

lambda_handler(1,2)
