#!/usr/bin/python3

import json, time
import datetime

from lib.config import *
import lib.sharesight as sharesight
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_future_days, service=False, specific_stock=False, message_id=False, interactive=False):
    def prepare_earnings_payload(service, market_data, days):
        payload = []
        emoji = "📣"
        now = int(time.time())
        soon = now + days * 86400
        for ticker in market_data:
            title = market_data[ticker]['profile_title']
            try:
                earnings_date = int(market_data[ticker]['earnings_date'])
            except (KeyError, ValueError):
                continue
            if earnings_date:
                data_seconds = earnings_date + 3600 * 4 # allow for Yahoo's inaccuracy
                human_date = time.strftime('%b %d', time.localtime(data_seconds)) # Sep 08
            if (data_seconds > now and data_seconds < soon) or specific_stock:
                flag = util.flag_from_ticker(ticker)
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {title} ({yahoo_link}) {human_date}")
        def last_two_columns(e):
            return e.split()[-2:]
        payload.sort(key=last_two_columns)
        if len(payload):
            if not specific_stock:
                message = f'Upcoming earnings next {days} days:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"No earnings date found for {tickers[0]}"]
                else:
                    payload = [f"No earnings dates found for the next {days} days"]
        return payload

    # MAIN #
    if specific_stock:
        tickers = [specific_stock]
    else:
        tickers = sharesight.get_holdings_wrapper()
        tickers.update(util.watchlist_load())
    market_data = yahoo.fetch(tickers)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    if interactive:
        payload = prepare_earnings_payload(service, market_data, days)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service in webhooks:
            print(service, "Preparing earnings date payload")
            payload = prepare_earnings_payload(service, market_data, config_future_days)
            if service == "telegram":
                url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
            else:
                url = webhooks[service]
            webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
