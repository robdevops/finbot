#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, threshold=config_price_percent, service=False, user='', interactive=False):
    def prepare_price_payload(service, market_data, threshold):
        payload = []
        for ticker in market_data:
            percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['profile_title']
            if abs(float(percent)) >= threshold:
                if percent < 0:
                    emoji = "🔻"
                else:
                    emoji = "⬆️ "
                percent = str(round(percent))
                flag = util.flag_from_ticker(ticker)
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {title} ({yahoo_link}) {percent}%")
        print(len(payload), f"holdings moved by at least {threshold}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if len(payload):
            message = f'Price alerts (intraday) over {threshold}%:'
            message = webhook.bold(message, service)
            payload.insert(0, message)
        else:
            if interactive:
                payload = [f"{user}, no price movements meet threshold {threshold}% 🛑"]
        return payload


    # MAIN #
    tickers = sharesight.get_holdings_wrapper()
    tickers.update(util.watchlist_load())
    market_data = yahoo.fetch(tickers)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    if interactive:
        payload = prepare_price_payload(service, market_data, threshold)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service in webhooks:
            payload = prepare_price_payload(service, market_data, threshold)
            url = webhooks[service]
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
