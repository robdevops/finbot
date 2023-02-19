#!/usr/bin/python3

import json, time, sys

from lib.config import *
import lib.sharesight as sharesight
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_future_days, service=False, specific_stock=False, message_id=False, interactive=False, earnings=False, dividend=False):
    def prepare_payload(service, market_data, days):
        payload = []
        emoji = "📣"
        now = int(time.time())
        soon = now + days * 86400
        for ticker in market_data:
            try:
                if earnings:
                    timestamp = int(market_data[ticker]['earnings_date'] + 3600 * 4) # allow for Yahoo inaccuracy
                elif dividend:
                    timestamp = market_data[ticker]['ex_dividend_date']
            except (KeyError, ValueError):
                continue
            if (timestamp > now and timestamp < soon) or specific_stock:
                title = market_data[ticker]['profile_title']
                human_date = time.strftime('%b %d', time.localtime(timestamp)) # Sep 08
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {human_date} {title} ({yahoo_link})")
        payload.sort()
        if len(payload):
            if not specific_stock:
                if earnings:
                    message = f'Upcoming earnings next {days} days:'
                elif dividend:
                    message = f'Upcoming ex-dividend next {days} days:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"No events found for {tickers[0]}"]
                else:
                    payload = [f"No events found for the next {days} days"]
        return payload

    # MAIN #
    if specific_stock:
        tickers = [specific_stock]
    else:
        tickers = sharesight.get_holdings_wrapper()
        tickers.update(util.watchlist_load())
    if earnings:
        market_data = yahoo.fetch(tickers)
    elif dividend:
        market_data = {}
        for ticker in tickers:
            try:
                market_data = { **market_data, **yahoo.fetch_detail(ticker) }
            except (TypeError):
                pass
        print("")

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    if interactive:
        payload = prepare_payload(service, market_data, days)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service in webhooks:
            payload = prepare_payload(service, market_data, config_future_days)
            if service == "telegram":
                url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
            else:
                url = webhooks[service]
            webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # change to "match .. case" in python 3.10
        if sys.argv[1] == 'earnings':
            lambda_handler(earnings=True)
        elif sys.argv[1] == 'ex-dividend':
            lambda_handler(dividend=True)
        else:
            print("Usage:", sys.argv[0], "[earnings|ex-dividend]")
    else:
        print("Usage:", sys.argv[0], "[earnings|ex-dividend]")
