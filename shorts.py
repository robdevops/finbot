#!/usr/bin/python3

import json, re
from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.shortman as shortman

def lambda_handler(chat_id=config_telegramChatID, threshold=config_shorts_percent, specific_stock=False, service=False, user='', interactive=False):
    def prepare_shorts_payload(service, market_data):
        payload = []
        emoji = "🩳"
        for ticker in tickers:
            try:
                short_percent = market_data[ticker]['short_percent']
            except:
                continue
            if '.AX' in ticker:
                url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0]
            else:
                url = 'https://finance.yahoo.com/quote/' + ticker + '/key-statistics?p=' + ticker
            title = market_data[ticker]['profile_title']
            short_percent = str(round(short_percent))

            flag = util.flag_from_ticker(ticker)
            if service == 'telegram':
                short_interest_link = '<a href="' + url + '">' + ticker + '</a>'
            elif service in {'slack', 'discord'}:
                short_interest_link = '<' + url + '|' + ticker + '>'
            else:
                short_interest_link = ticker

            if float(short_percent) > threshold or specific_stock:
                payload.append(f"{emoji} {title} ({short_interest_link}) {short_percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if len(payload):
            if not specific_stock:
                message = f'Stocks shorted over {threshold}%:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"{emoji}No short interest found for {tickers[0]}"]
                else:
                    payload = [f"{emoji}No stocks shorted over {threshold}%. Try specifying a number."]
        return payload

    # MAIN #

    if specific_stock:
        tickers = [specific_stock]
    else:
        tickers = sharesight.get_holdings_wrapper()
        tickers.update(util.watchlist_load())
    market_data = yahoo.fetch(tickers)
    for ticker in tickers:
        if '.' not in ticker:
            try:
                market_data = { **market_data, **yahoo.fetch_detail(ticker) }
            except (TypeError):
                pass
    print("")
    market_data = shortman.fetch(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    if interactive:
        payload = prepare_shorts_payload(service, market_data)
        url = webhooks[service]
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = url + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service in webhooks:
            payload = prepare_shorts_payload(service, market_data)
            url = webhooks[service]
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()

