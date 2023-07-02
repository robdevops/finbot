#!/usr/bin/python3

import json, re, sys, os
import datetime

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo
from lib import telegram

def lambda_handler(chat_id=config_telegramChatID, threshold=config_price_percent, service=None, user='', specific_stock=None, interactive=False, midsession=False, premarket=False, interday=False, days=None):
    def prepare_price_payload(service, market_data, threshold):
        payload = []
        graph = False
        marketStates = []
        multiplier = config_volatility_multiplier
        for ticker in market_data:
            marketState = market_data[ticker]['marketState']
            marketStates.append(marketState)
            regularMarketTime = datetime.datetime.fromtimestamp(market_data[ticker]['regularMarketTime'])
            now = datetime.datetime.now()
            if midsession and marketState != "REGULAR":
                # skip stocks not in session
                # Possible market states: PREPRE PRE REGULAR POST POSTPOST CLOSED
                continue
            if interday and not interactive and now - regularMarketTime > datetime.timedelta(days=1):
                # avoid repeating on public holidays
                print(ticker + '⏭', sep='', end=' ', flush=True)
                continue
            if premarket:
                if 'percent_change_premarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_premarket']
                elif 'percent_change_postmarket' in market_data[ticker]:
                    percent = market_data[ticker]['percent_change_postmarket']
                else:
                    continue
            elif days:
                try:
                    percent = market_data[ticker]['percent_change_period'] # sharesight value
                except KeyError:
                    if specific_stock:
                        percent, graph = yahoo.price_history(ticker, days)
                    else:
                        percent, graph = yahoo.price_history(ticker, days, graph=False)
                    percent = percent[days]
            else:
                percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['profile_title']
            percent = float(percent)
            if percent < 0:
                emoji = "🔻"
            elif percent > 0:
                emoji = '🔼'
            else:
                emoji = "▪️"
            #flag = util.flag_from_ticker(ticker)
            exchange = market_data[ticker]['profile_exchange']
            if config_hyperlinkProvider == 'google' and exchange != 'Taipei Exchange':
                ticker_link = util.gfinance_link(ticker, exchange, service, days=days)
            else:
                ticker_link = util.yahoo_link(ticker, service)
            if specific_stock or abs(percent) >= threshold: # abs catches negative percentages
                if config_demote_volatile:
                    market_data = market_data | yahoo.fetch_detail(ticker)
                    if 'beta' in market_data[ticker] and market_data[ticker]['beta'] > 1.5 and market_data[ticker]['market_cap'] < 1000000000:
                        if debug:
                            print(ticker, "meets volatility criteria - promoting threshold to "f"{threshold*multiplier}%", file=sys.stderr)
                        if abs(percent) >= (threshold*multiplier):
                            payload.append([emoji, title, f'({ticker_link})', percent])
                    else:
                        payload.append([emoji, title, f'({ticker_link})', percent])
                else:
                    payload.append([emoji, title, f'({ticker_link})', percent])
        def last_element(e):
            return e[-1]
        payload.sort(key=last_element)
        for i, e in enumerate(payload):
            e[-1] = str(round(e[-1])) + '%'
            payload[i] = ' '.join(e)

        if payload:
            if not specific_stock:
                if midsession:
                    message = f'Tracking ≥ {threshold}% mid-session:'
                elif premarket:
                    message = f'Tracking ≥ {threshold}% pre-market:'
                elif days:
                    message = f'Moved ≥ {threshold}% {util.days_english(days, "in ", "a ")}:'
                else:
                    message = f'Moved ≥ {threshold}% interday:'
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
                        payload = [f"No interday price found for {tickers[0]}"]
                elif premarket:
                    payload = [f"No pre-market price movements meet threshold {threshold}%"]
                elif midsession:
                    if 'REGULAR' not in marketStates:
                        payload = [f"{user}, no tracked stocks are currently in session."]
                    else:
                        payload = [f"{user}, no in-session securities meet threshold {threshold}%"]
                else:
                    payload = [f"{user}, no price movements meet threshold {threshold}%"]
        return payload, graph


    # MAIN #
    if specific_stock:
        specific_stock = util.transform_to_yahoo(specific_stock)
        tickers = [specific_stock]
    else:
        tickers = util.get_holdings_and_watchlist()
    market_data = yahoo.fetch(tickers)

    if not specific_stock and days: # else market_data or yahoo.price_history is faster
        performance = sharesight.get_performance_wrapper(days)
        for portfolio_id, data in performance.items():
            for holding in data['report']['holdings']:
                symbol = holding['instrument']['code']
                market = holding['instrument']['market_code']
                percent = float(holding['capital_gain_percent'])
                ticker = util.transform_to_yahoo(symbol, market)
                if ticker not in tickers:
                    continue
                try:
                    market_data[ticker]['percent_change_period'] = percent # inject sharesight value
                except KeyError:
                    print("Notice:", os.path.basename(__file__), ticker, "has no data", file=sys.stderr)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    if interactive:
        if specific_stock:
            payload, graph = prepare_price_payload(service, market_data, threshold)
        else:
            payload, graph = prepare_price_payload(service, market_data, threshold)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        if graph:
            caption = '\n'.join(payload)
            webhook.sendPhoto(chat_id, graph, caption, service)
        else:
            webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service, url in webhooks.items():
            payload, graph = prepare_price_payload(service, market_data, threshold)
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # make google cloud happy
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:

        # python 3.9
        try:
            arg = int(sys.argv[1])
        except ValueError:
            if sys.argv[1] == 'midsession':
                lambda_handler(midsession=True)
            elif sys.argv[1] == 'interday':
                lambda_handler(interday=True)
            elif sys.argv[1] == 'premarket':
                lambda_handler(premarket=True)
            else:
                print("Usage:", sys.argv[0], "[midsession|interday|premarket|days (int)]", file=sys.stderr)
        else:
            lambda_handler(days=arg)

        # python 3.10
        #match sys.argv[1]:
        #    case 'midsession':
        #        lambda_handler(midsession=True)
        #    case 'interday':
        #        lambda_handler(interday=True)
        #    case 'premarket':
        #        lambda_handler(premarket=True)
        #    case 'week':
        #        lambda_handler(days=7)
        #    case 'month':
        #        lambda_handler(days=28)
        #    case other:
        #        print("Usage:", sys.argv[0], "[midsession|interday|premarket|week|month]", file=sys.stderr)

    else:
        print("Usage:", sys.argv[0], "[midsession|interday|premarket|days (int)]", file=sys.stderr)
