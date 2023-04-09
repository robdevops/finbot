#!/usr/bin/python3

import json, re, sys
import datetime
import pytz

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, threshold=config_price_percent, service=False, user='', specific_stock=False, interactive=False, midsession=False, premarket=False, intraday=False):
    def prepare_price_payload(service, market_data, threshold):
        payload = []
        marketStates = []
        for ticker in market_data:
            marketState = market_data[ticker]['marketState']
            marketStates.append(marketState)
            regularMarketTime = market_data[ticker]['regularMarketTime']
            tz = pytz.timezone(market_data[ticker]['exchangeTimezoneName'])
            now = datetime.datetime.now(tz).timestamp()
            if midsession and marketState != "REGULAR":
                # skip stocks not in session
                # Possible market states: PREPRE PRE REGULAR POST POSTPOST CLOSED
                continue
            elif intraday and not interactive and now - regularMarketTime > 86400:
                # avoid repeating on public holidays
                whenMarketClosed = round((now - regularMarketTime) / 86400)
                print("Skipping security not traded in", whenMarketClosed, "days:", ticker)
                continue
            elif premarket:
                if 'percent_change_premarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_premarket']
                elif 'percent_change_postmarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_postmarket']
                else:
                    print("no pre/post-market data for", ticker)
                    continue
            else:
                percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['profile_title']
            if percent < 0:
                emoji = "🔻"
            elif percent > 0:
                emoji = '🔼'
            else:
                emoji = "▪️"
            percent = str(round(percent))
            flag = util.flag_from_ticker(ticker)
            exchange = market_data[ticker]['profile_exchange']
            if not (premarket and 'PRE' in marketState) and config_hyperlinkProvider == 'google' and exchange != 'Taipei Exchange':
                # oddly, google provides post-market but not pre-market pricing
                ticker_link = util.gfinance_link(ticker, exchange, service)
            else:
                ticker_link = util.yahoo_link(ticker, service)
            if specific_stock or float(percent) >= threshold:
                payload.append(f"{emoji} {title} ({ticker_link}) {percent}%")
        def last_column_percent(e):
            return int(re.split(' |%', e)[-2])
        payload.sort(key=last_column_percent)
        if len(payload):
            if not specific_stock:
                if midsession:
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
                    if midsession:
                        payload = [f"{tickers[0]} not found or not in session"]
                    elif premarket:
                        payload = [f"No premarket price found for {tickers[0]}"]
                    else:
                        payload = [f"No intraday price found for {tickers[0]}"]
                elif premarket:
                    payload = [f"No pre-market price movements meet threshold {threshold}%"]
                elif midsession:
                    if 'REGULAR' not in marketStates:
                        payload = [f"{user}, none of the stocks I'm tracking are currently in a trading sesion."]
                    else:
                        payload = [f"{user}, no in-session securities meet threshold {threshold}%"]
                else:
                    payload = [f"{user}, no price movements meet threshold {threshold}%"]
        return payload


    # MAIN #
    if specific_stock:
        specific_stock = util.transform_to_yahoo(specific_stock)
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
        if sys.argv[1] == 'midsession':
            lambda_handler(midsession=True)
        elif sys.argv[1] == 'intraday':
            lambda_handler(intraday=True)
        elif sys.argv[1] == 'premarket':
            lambda_handler(premarket=True)
        else:
            print("Usage:", sys.argv[0], "[midsession|intraday|premarket]")
    else:
        print("Usage:", sys.argv[0], "[midsession|intraday|premarket]")
