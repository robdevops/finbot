#!/usr/bin/python3

import json, os
import datetime

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(telegramChatID=config_telegramChatID, interactive=False, user='', past_days=config_past_days):
    time_now = datetime.datetime.today()
    today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
    start_date = time_now - datetime.timedelta(days=past_days)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    cache_file = config_cache_dir + "/sharesight_trade_cache.json"
    
    def prepare_trade_payload(service, trades):
        if os.path.isfile(cache_file) and not interactive:
            known_trades = trade_cache_read(cache_file)
        else:
            known_trades = []
        payload = []
        sharesight_url = "https://portfolio.sharesight.com/holdings/"
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
            ticker = util.transform_ticker(symbol, market)

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
            brief=True
            if service == 'telegram':
                trade_link = '<a href="' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit">' + verb + '</a>'
                holding_link = util.yahoo_link(ticker, service, brief)
            elif service in {'discord', 'slack'}:
                trade_link = '<' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit' + '|' + verb + '>'
                holding_link = util.yahoo_link(ticker, service, brief)
            else:
                trade_link = verb
                holding_link = symbol
            payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value:,} of {holding_link} {flag}")
        if interactive:
            payload.insert(0, f"@{user}")
            if len(payload) == 1:
                payload.append(f"No trades found in the past {past_days} days 🛑")
        else:
            message = 'New trades:'
            message = webhook.bold(message, service)
            payload.insert(0, message)
        return payload
    
    def trade_cache_read(cache_file):
        with open(cache_file, "r") as f:
            lines = f.read().splitlines()
            return lines
    
    def trade_cache_write(cache_file, trades):
        with open(cache_file, "a") as f:
            for trade in trades:
                f.write(f"{trade}\n")

    # MAIN #
    portfolios = sharesight.get_portfolios()

    # Get trades from Sharesight
    trades = []
    newtrades = set()
    for portfolio_name in portfolios:
        portfolio_id = portfolios[portfolio_name]
        trades = trades + sharesight.get_trades(portfolio_name, portfolio_id, past_days)
    if trades:
        print(len(trades), "trades found since", start_date)
    else:
        print("No trades found since", start_date)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        print(service, "Preparing trade payload")
        payload = prepare_trade_payload(service, trades)
        url = webhooks[service]
        if service == "telegram":
            url = url + "sendMessage?chat_id=" + str(telegramChatID)
        webhook.payload_wrapper(service, url, payload)

    # write state file
    if newtrades and not interactive:
        trade_cache_write(cache_file, newtrades)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
