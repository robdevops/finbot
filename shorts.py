#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.shortman as shortman

def lambda_handler(telegramChatID = config_telegramChatID, interactive = False, user='', threshold=config_shorts_percent):
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
            if float(short_percent) > threshold:
                title = market_data[ticker]['profile_title']
                short_percent = str(round(short_percent))
                flag = util.flag_from_ticker(ticker)
                if service == 'telegram':
                    short_interest_link = '<a href="' + url + '">' + ticker + '</a>'
                elif service in {'slack', 'discord'}:
                    short_interest_link = '<' + url + '|' + ticker + '>'
                else:
                    short_interest_link = ticker
                payload.append(f"{emoji} {title} ({short_interest_link}) {short_percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if interactive:
            payload.insert(0, f"<b>@{user} stocks with at least {threshold}% short interest</b>")
            if len(payload) == 1:
                payload.append(f"No shorts meet threshold {emoji}. Try specifying a number.")
        else:
            message = 'Highly shorted stock warning:'
            message = webhook.bold(message, service)
            payload.insert(0, message)
        return payload

    # MAIN #

    tickers = sharesight.get_holdings_wrapper()
    tickers.update(config_watchlist)
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
    for service in webhooks:
        print(service, "Preparing shorts payload")
        payload = prepare_shorts_payload(service, market_data)
        url = webhooks[service]
        if service == "telegram":
            url = url + "sendMessage?chat_id=" + str(telegramChatID)
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()

