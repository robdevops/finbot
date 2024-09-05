#!/usr/bin/env python3

import json, os, random, sys, re
import datetime

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_past_days, service=None, user='', portfolio_select=None, message_id=None, interactive=False):
    start_date = datetime.datetime.now() - datetime.timedelta(days=days)
    start_date = start_date.strftime('%Y-%m-%d') # 2022-08-20
    state_file = "finbot_sharesight_trades.json"

    def prepare_trade_payload(service, trades):
        payload_staging = []
        dates = set()
        sharesight_url = "https://portfolio.sharesight.com/holdings/"
        if config_trades_use_yahoo:
            tickers = []
            for trade in trades:
                if trade['transaction_type'] not in {'BUY', 'SELL'}:
                    continue
                symbol = trade['symbol']
                market = trade['market']
                ticker = util.transform_to_yahoo(symbol, market)
                tickers.append(ticker)
            set(tickers)
            market_data = yahoo.fetch(tickers)

        for trade in trades:
            action=''
            emoji=''
            portfolio_name = trade['portfolio'] # custom field
            date = trade['transaction_date'] # 2023-12-30
            transactionType = trade['transaction_type']
            symbol = trade['symbol']
            market = trade['market']
            if transactionType == 'BUY':
                action = 'bought'
                emoji = '💸'
            elif transactionType == 'SELL':
                action = 'sold'
                emoji = '🤑'
            else:
                print("Skipping corporate action:", portfolio_name, date, transactionType, symbol)
                continue

            trade_id = int(trade['id'])
            units = float(trade['quantity'])
            price = float(trade['price'])
            currency = trade['brokerage_currency_code']
            if config_trades_use_yahoo:
                ticker = util.transform_to_yahoo(symbol, market)
                market = market_data[ticker]['profile_exchange']
            #value = round(trade['value']) # don't use - sharesight converts to local currency
            value = round(price * units)
            holding_id = str(trade['holding_id'])
            ticker = util.transform_to_yahoo(symbol, market)
            dt_date = datetime.datetime.strptime(date, '%Y-%m-%d').date() # (2023, 12, 30)

            if portfolio_select and portfolio_name.lower() != portfolio_select.lower():
                continue

            if not interactive and trade_id in known_trades:
                print("Skipping known trade_id:", trade_id, date, portfolio_name, transactionType, symbol)
                continue
            newtrades.add(trade_id) # sneaky update global set
            dates.add(dt_date)

            flag = util.flag_from_market(market)
            # lookup currency or fall back to less reliable sharesight currency
            currency_temp = util.currency_from_market(market)
            if currency_temp:
                currency = currency_temp
            trade_url = sharesight_url + holding_id + '/trades/' + str(trade_id) + '/edit'
            trade_link = util.link(trade_url, action, service)
            holding_link = util.finance_link(symbol, market, service)
            payload_staging.append([dt_date, trade_id, emoji, portfolio_name, trade_link, currency, f'{value}', holding_link, flag])

        payload = []
        payload_staging.sort()
        for date in sorted(dates):
            if len(dates) > 1 or (interactive and days > 1):
                human_date = date.strftime('%b %d') # Dec 30
                payload.append("")
                payload.append(webhook.bold(human_date, service))
            for trade in payload_staging:
                if date == trade[0]:
                    payload.append(' '.join(trade[2:]))

        if interactive and not payload: # easter egg 4
            payload = [f"{user} No trades {util.days_english(days, 'in the past ')}. {random.choice(noTradesVerb)}"]
        return payload

    # MAIN #
    portfolios = sharesight.get_portfolios()

    # Get trades from Sharesight
    trades = []
    known_trades = []
    newtrades = set()
    known_trades = util.json_load(state_file, persist=True)

    if portfolio_select:
        portfoliosLower = {k.lower():v for k,v in portfolios.items()}
        portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
        if portfolio_select.lower() in portfoliosLower:
            portfolio_id = portfoliosLower[portfolio_select.lower()] # any-case input
            portfolio_select = portfoliosReverseLookup[portfolio_id] # correct-case output
        else:
            print("Portfolio not found:", portfolio_select, file=sys.stderr)
            sys.exit(1)
        trades = trades + sharesight.get_trades(portfolio_select, portfolio_id, days)
    else:
        for portfolio in portfolios:
            portfolio_id = portfolios[portfolio]
            trades = trades + sharesight.get_trades(portfolio, portfolio_id, days)
        if trades:
            print(len(trades), "trades found since", start_date)
        else:
            print("No trades found since", start_date)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    if interactive:
        payload = prepare_trade_payload(service, trades)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id, message_id)
    else:
        for service, url in webhooks.items():
            payload = prepare_trade_payload(service, trades)
            if service == "telegram":
                chat_id=config_telegramChatID
                url = url + "sendMessage?chat_id=" + str(chat_id)
            else:
                chat_id = None
            webhook.payload_wrapper(service, url, payload, chat_id)

    # write state file
    if newtrades and not interactive:
        known_trades = set(known_trades) | newtrades
        util.json_write(state_file, list(known_trades), persist=True)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
