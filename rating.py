#!/usr/bin/python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
    def prepare_rating_payload(service, market_data):
        def get_emoji(old, new):
            if old > new:
                return '📈'
            if old < new:
                return '📉'
            else:
                return '▪️'
        payload = []
        new = {}
        old = util.json_load('finbot_rating.json')
        for ticker in tickers:
            old_action=None
            old_index = float()
            try:
                action = market_data[ticker]['recommend'].replace('_', ' ')
                index = float(market_data[ticker]['recommend_index'])
                analysts = market_data[ticker]['recommend_analysts']
            except (KeyError, ValueError):
                continue
            title = market_data[ticker]['profile_title']
            ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service, brief=False)
            new[ticker] = [action, index]
            try:
                old_action = old[ticker][0]
                old_index = old[ticker][1]
            except (KeyError, TypeError):
                pass
            if old_action and action != old_action:
                emoji = get_emoji(old_index, index)
                message = f"{webhook.bold(f'{old_index} {old_action}', service)} to {webhook.bold(f'{index} {action}', service)} ({analysts})"
                payload.append(f"{emoji} {title} ({ticker_link}) changed from {message} analysts")
        util.json_write('finbot_rating.json', new)
        payload.sort()
        if payload:
            if not specific_stock:
                message = f'Consensus rating changes:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"{emoji}No rating changes found for {tickers[0]}"]
                else:
                    payload = [f"{emoji}No rating changes found"]
        return payload

    # MAIN #

    market_data = {}
    if specific_stock:
        ticker = util.transform_to_yahoo(specific_stock)
        tickers = [ticker]
    else:
        tickers = util.get_holdings_and_watchlist()
        tickers = list(tickers)
        tickers.sort()

    for ticker in tickers:
        market_data = market_data | yahoo.fetch_detail(ticker)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    if interactive:
        payload = prepare_rating_payload(service, market_data)
        url = webhooks[service]
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = url + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service, url in webhooks.items():
            payload = prepare_rating_payload(service, market_data)
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
