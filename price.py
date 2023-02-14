#!/usr/bin/python3

import json, re, sys

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, threshold=config_price_percent, service=False, user='', specific_stock=False, interactive=False, ignoreclosed=False, premarket=False, intraday=False):
    def prepare_price_payload(service, market_data, threshold):
        payload = []
        for ticker in market_data:
            if ignoreclosed and market_data[ticker]['marketState'] != "REGULAR": # for scheduling mid-session updates
                continue
            elif intraday:
                percent = market_data[ticker]['percent_change']
            elif premarket:
                if 'percent_change_premarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_premarket']
                elif 'percent_change_postmarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_postmarket']
                else:
                    print("no data for", ticker)
                    continue
            title = market_data[ticker]['profile_title']
            if percent < 0:
                emoji = "🔻"
            elif percent > 0:
                emoji = "⬆️ "
            else:
                emoji = "▪️"
            percent = str(round(percent))
            flag = util.flag_from_ticker(ticker)
            yahoo_link = util.yahoo_link(ticker, service)
            if abs(float(percent)) >= threshold or specific_stock:
                payload.append(f"{emoji} {title} ({yahoo_link}) {percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if len(payload):
            if not specific_stock:
                if ignoreclosed:
                    message = f'Mid-session over {threshold}%:'
                elif premarket:
                    message = f'Stocks moving over {threshold}% pre-market:'
                else:
                    message = f'Price alerts (intraday) over {threshold}%:'
                message = webhook.bold(message, service)
                payload.insert(0, message)
        else:
            if interactive:
                if specific_stock:
                    payload = [f"No intraday price found for {tickers[0]}"]
                elif premarket:
                    payload = [f"No pre-market price movements meet threshold {threshold}%"]
                else:
                    payload = [f"{user}, no price movements meet threshold {threshold}%"]
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
        payload = prepare_price_payload(service, market_data, threshold)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service in webhooks:
            payload = prepare_price_payload(service, market_data, threshold)
            url = webhooks[service]
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # change to "match .. case" in python 3.10
        if sys.argv[1] == 'ignoreclosed':
            lambda_handler(ignoreclosed=True)
        elif sys.argv[1] == 'intraday':
            lambda_handler(intraday=True)
        elif sys.argv[1] == 'premarket':
            lambda_handler(premarket=True)
        else:
            print("Usage:", sys.argv[0], "[ignoreclosed|intraday|premarket]")
    else:
        print("Usage:", sys.argv[0], "[ignoreclosed|intraday|premarket]")
