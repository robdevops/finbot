#!/usr/bin/python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
    def prepare_ath_payload(service, market_data):
        emoji = '⭐'
        payload = []
        new = {}
        oldhigh = 0
        old = util.json_load('finbot_ath.json', persist=True)
        for ticker in tickers:
            try:
                regularMarketPrice = market_data[ticker]['regularMarketPrice']
                #regularMarketPreviousClose = market_data[ticker]['regularMarketPreviousClose']
                fiftyTwoWeekHigh = market_data[ticker]['fiftyTwoWeekHigh']
                #allTimeHigh = 'TODO'
            except (KeyError, ValueError):
                continue
            title = market_data[ticker]['profile_title']
            ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service, brief=False)
            new[ticker] = fiftyTwoWeekHigh
            try:
                oldhigh = old[ticker]
            except (KeyError, TypeError):
                pass
            if fiftyTwoWeekHigh > oldhigh:
                payload.append(f"{emoji} {title} ({ticker_link}) reached a 52 week high at {fiftyTwoWeekHigh}")
        payload.sort()
        if payload:
            if not specific_stock:
                message = f'New high:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"{emoji}{tickers[0]} is not at an ATH"]
                else:
                    payload = [f"{emoji}ATH not found"]
        return payload, new

    # MAIN #

    market_data = {}
    if specific_stock:
        ticker = util.transform_to_yahoo(specific_stock)
        tickers = [ticker]
    else:
        tickers = util.get_holdings_and_watchlist()
        tickers = list(tickers)
        tickers.sort()
        market_data = yahoo.fetch(tickers)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    if interactive:
        payload, new = prepare_ath_payload(service, market_data)
        url = webhooks[service]
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = url + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service, url in webhooks.items():
            payload, new = prepare_ath_payload(service, market_data)
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    if new:
        util.json_write('finbot_ath.json', new, persist=True)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
