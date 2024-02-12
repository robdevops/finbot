#!/usr/bin/python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

# BUGS:
# - need to handle stock splits: flush cache if we see a split in yahoo
# https://finance.yahoo.com/quote/TSLA/history?period1=0&period2=1707609600&filter=split

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
    def prepare_ath_payload(service, market_data):
        emoji = '⭐'
        payload = []
        new = {}
        oldhigh = float()
        old = util.json_load('finbot_ath.json', persist=True)
        for ticker in tickers:
            try:
                oldhigh = old[ticker]
            except (KeyError, TypeError):
                try:
                    oldhigh = yahoo.historic_high(ticker)
                except (KeyError, TypeError):
                    continue
            try:
                newhigh = market_data[ticker]['fiftyTwoWeekHigh']
            except (KeyError, ValueError):
                continue
            title = market_data[ticker]['profile_title']
            ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
            currency = market_data[ticker]['currency']
            currency_symbol = util.get_currency_symbol(currency)
            emoji = util.flag_from_ticker(ticker)
            if newhigh > oldhigh:
                new[ticker] = newhigh
                payload.append(f"{emoji} {title} ({ticker_link}) {currency} {newhigh}")
            else:
                new[ticker] = oldhigh
        payload.sort()
        if payload:
            if not specific_stock:
                message = f'Record high:'
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
        #tickers = ['TSLA'] # DEBUG
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
