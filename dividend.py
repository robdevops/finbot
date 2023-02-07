#!/usr/bin/python3

import json, time

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_future_days, service=False, message_id=False, interactive=False):
    def prepare_ex_dividend_payload(service, market_data, days):
        payload = []
        emoji = "⚠️"
        now = int(time.time())
        soon = now + days * 86400
        for ticker in market_data:
            try:
                timestamp = market_data[ticker]['ex_dividend_date']
            except KeyError:
                continue
            title = market_data[ticker]['profile_title']
            flag = util.flag_from_ticker(ticker)
            ticker_short = ticker.split('.')[0]
            if timestamp > now and timestamp < soon:
                human_date = time.strftime('%b %d', time.localtime(timestamp)) # Sep 08
                yahoo_link = util.yahoo_link(ticker, service)
                payload.append(f"{emoji} {human_date} {title} ({yahoo_link})")
        payload.sort()
        if len(payload):
            message = f'Ex-dividends next {days} days. Avoid buy before:'
            message = webhook.bold(message, service)
            payload.insert(0, message)
        return payload

    # MAIN #

    tickers = sharesight.get_holdings_wrapper()
    tickers.update(util.watchlist_load())
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
        payload = prepare_ex_dividend_payload(service, market_data, days)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service in webhooks:
            print(service, "Preparing ex-dividend date payload")
            payload = prepare_ex_dividend_payload(service, market_data, config_future_days)
            url = webhooks[service]
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + config_telegramChatID
            webhook.payload_wrapper(service, url, payload)
    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
