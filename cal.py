#!/usr/bin/python3

import json, time, sys

from lib.config import *
from lib import sharesight
from lib import util
from lib import webhook
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_future_days, service=False, specific_stock=False, message_id=False, interactive=False, earnings=False, dividend=False):
    def prepare_payload(service, market_data, days):
        payload_staging = []
        emoji = "📣"
        now = int(time.time())
        soon = now + days * 86400
        dates = set()
        for ticker in market_data:
            try:
                if earnings:
                    timestamp = int(market_data[ticker]['earnings_date'] + 3600 * 4) # allow for Yahoo inaccuracy
                elif dividend:
                    timestamp = int(market_data[ticker]['ex_dividend_date'])
            except (KeyError, ValueError):
                continue
            if (timestamp > now and timestamp < soon) or specific_stock:
                title = market_data[ticker]['profile_title']
                ticker_link = util.yahoo_link(ticker, service)
                human_date = time.strftime('%b %d', time.localtime(timestamp)) # Dec 30
                dates.add(human_date)
                payload_staging.append([emoji, timestamp, title, f'({ticker_link})', human_date])

        def second_element(e):
            return e[0]
        payload_staging.sort(key=second_element)

        payload = []
        for date in sorted(dates):
            if not specific_stock:
                payload.append("")
                payload.append(webhook.bold(date, service))
            for i, e in enumerate(payload_staging):
                if str(date) == e[4]:
                    if specific_stock:
                        e[1] = e[4]
                        payload.append(' '.join(e[:-1]))
                    else:
                        payload.append(' '.join([e[0]] + e[2:-1]))

        #for i, e in enumerate(payload):
        #    e[1] = time.strftime('%b %d', time.localtime(e[1])) # Dec 30
        #    payload[i] = ' '.join(e)

        if payload:
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
        ticker = util.transform_to_yahoo(specific_stock)
        tickers = [ticker]
    else:
        tickers = sharesight.get_holdings_wrapper()
        tickers.update(util.watchlist_load())
    if earnings:
        market_data = yahoo.fetch(tickers)
    elif dividend:
        market_data = {}
        for ticker in tickers:
            try:
                market_data = market_data | yahoo.fetch_detail(ticker)
            except TypeError:
                pass
        print("")

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    if interactive:
        payload = prepare_payload(service, market_data, days)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service, url in webhooks.items():
            payload = prepare_payload(service, market_data, config_future_days)
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + config_telegramChatID
            webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:

        # python 3.9
        if sys.argv[1] == 'earnings':
            lambda_handler(earnings=True)
        elif sys.argv[1] == 'dividend':
            lambda_handler(dividend=True)
        else:
            print("Usage:", sys.argv[0], "[earnings|ex-dividend]", file=sys.stderr)

        # python 3.10
        #match sys.argv[1]:
        #    case 'earnings':
        #        lambda_handler(earnings=True)
        #    case 'ex-dividend':
        #        lambda_handler(dividend=True)
        #    case other:
        #        print("Usage:", sys.argv[0], "[earnings|ex-dividend]", file=sys.stderr)

    else:
        print("Usage:", sys.argv[0], "[earnings|ex-dividend]", file=sys.stderr)
