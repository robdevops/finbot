#!/usr/bin/python3

import json, os
import datetime

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(event,context):
    time_now = datetime.datetime.today()
    today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
    start_date = time_now - datetime.timedelta(days=config_past_days)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    
    def prepare_trade_payload(service, trades):
        if os.path.isfile(config_state_file):
            known_trades = state_file_read()
        else:
            known_trades = []
        payload = []
        sharesight_url = "https://portfolio.sharesight.com/holdings/"
        yahoo_url = "https://au.finance.yahoo.com/quote/"
        if service == 'telegram':
            payload.append("<b>New trades:</b>")
        elif service == 'slack':
            payload.append("*New trades:*")
        elif service == 'discord':
            payload.append("**New trades:**")
        else:
            payload.append("New trades:")
        for trade in trades:
            trade_id = str(trade['id'])
            portfolio = trade['portfolio']
            date = trade['transaction_date']
            type = trade['transaction_type']
            units = float(round(trade['quantity']))
            price = float(trade['price'])
            currency = trade['brokerage_currency_code']
            symbol = trade['symbol']
            market = trade['market']
            #value = abs(round(trade['value'])) # don't use - sharesight converts to local currency
            value = abs(round(price * units))
            holding_id = str(trade['holding_id'])
            ticker = yahoo.transform_ticker(symbol, market)

            verb=''
            emoji=''
            if type == 'BUY':
                verb = 'bought'
                emoji = '💸'
            elif type == 'SELL':
                verb = 'sold'
                emoji = '🤑'
            else:
                print("Skipping corporate action:", portfolio, date, type, symbol)
                continue

            if trade_id in known_trades:
                print("Skipping known trade_id:", trade_id, date, portfolio, type, symbol)
                continue
            else:
                newtrades.add(trade_id) # sneaky update global set

            flag = util.flag_from_market(market)
            # lookup currency or fall back to less reliable sharesight currency
            currency_temp = util.currency_from_market(market)
            if currency_temp:
                currency = currency_temp

            if service == 'telegram':
                trade_link = '<a href="' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit">' + verb + '</a>'
                holding_link = '<a href="' + yahoo_url + ticker + '">' + symbol + '</a>'
            elif service in {'discord', 'slack'}:
                trade_link = '<' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit' + '|' + verb + '>'
                holding_link = '<' + yahoo_url + ticker + '|' + symbol + '>'
            else:
                trade_link = verb
                holding_link = symbol
            payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value:,} of {holding_link} {flag}")
        return payload
    
    def state_file_read():
        with open(config_state_file, "r") as f:
            lines = f.read().splitlines()
            return lines
    
    def state_file_write(trades):
        with open(config_state_file, "a") as f:
            for trade in trades:
                f.write(f"{trade}\n")

    # MAIN #
    token = sharesight.get_token(sharesight_auth)
    portfolios = sharesight.get_portfolios(token)

    # Get trades from Sharesight
    trades = []
    newtrades = set()
    for portfolio_name in portfolios:
        portfolio_id = portfolios[portfolio_name]
        trades = trades + sharesight.get_trades(token, portfolio_name, portfolio_id)
    if trades:
        print(len(trades), "trades found since", start_date)
    else:
        print("No trades found since", start_date)
        exit()

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing trade payload")
        payload = prepare_trade_payload(service, trades)
        url = webhooks[service]
        webhook.payload_wrapper(service, url, payload)

    # write state file
    if newtrades:
        state_file_write(newtrades)

    # make google cloud happy
    return True

lambda_handler(1, 2)
