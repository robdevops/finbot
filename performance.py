#!/usr/bin/python3

import sys
import json

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util

def lambda_handler(chat_id=config_telegramChatID, past_days=config_past_days, service=False, user='', portfolio_select=False, message_id=False, interactive=False):
    def prepare_performance_payload(service, performance, portfolios):
        portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
        payload = []
        for portfolio_id in performance:
            portfolio_url = "https://portfolio.sharesight.com/portfolios/" + str(portfolio_id)
            portfolio_name = portfoliosReverseLookup[portfolio_id]
            portfolio_link = util.link(portfolio_url, portfolio_name, service)
            percent = float(performance[portfolio_id]['report']['currency_gain_percent'])
            payload.append(f"{portfolio_link} {percent}%")
        if len(payload):
            days_english = f'{past_days} days' if past_days != 1 else 'day'
            message = "Performance over past " + days_english
            message = webhook.bold(message, service)
            payload.insert(0, message)
        return payload

    # MAIN #
    portfolios = sharesight.get_portfolios()
    performance = {}

    if portfolio_select:
        portfoliosLower = {k.lower():v for k,v in portfolios.items()}
        if portfolio_select.lower() in portfoliosLower:
            portfolio_id = portfoliosLower[portfolio_select.lower()] # any-case input
            performance[portfolio_id] = sharesight.get_performance(portfolio_id, past_days)
    else:
        for portfolio, portfolio_id in portfolios.items():
            performance[portfolio_id] = sharesight.get_performance(portfolio_id, past_days)

    # Prep and send payloads
    if not len(performance):
        print("Error: no Sharesight data found")
        sys.exit(1)
    if not webhooks:
        print("Error: no services enabled in .env")
        sys.exit(1)
    if interactive:
        payload = prepare_performance_payload(service, performance, portfolios)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service, url in webhooks.items():
            payload = prepare_performance_payload(service, performance, portfolios)
            if service == "telegram":
                chat_id = config_telegramChatID
                url = url + "sendMessage?chat_id=" + str(chat_id)
            else:
                chat_id=False
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print("Usage:", sys.argv[0], "[integer]")
            sys.exit(1)
        lambda_handler(past_days=days)
    else:
        lambda_handler()

