#!/usr/bin/python3

import json, os, random, sys, re
import datetime

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util

def lambda_handler(chat_id=config_telegramChatID, past_days=config_past_days, service=False, user='', portfolio_select=False, message_id=False, interactive=False):
    time_now = datetime.datetime.today()
    start_date = time_now - datetime.timedelta(days=past_days)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    state_file = config_cache_dir + "/finbot_sharesight_trades.json"

    def prepare_trade_payload(service, trades):
        payload_staging = []
        dates = set()
        sharesight_url = "https://portfolio.sharesight.com/holdings/"
        for trade in trades:
            trade_id = int(trade['id'])
            portfolio_name = trade['portfolio'] # custom field
            date = trade['transaction_date']
            transactionType = trade['transaction_type']
            units = float(trade['quantity'])
            price = float(trade['price'])
            currency = trade['brokerage_currency_code']
            symbol = trade['symbol']
            market = trade['market']
            #value = round(trade['value']) # don't use - sharesight converts to local currency
            value = round(price * units)
            holding_id = str(trade['holding_id'])
            ticker = util.transform_to_yahoo(symbol, market)
            dates.add(date)

            action=''
            emoji=''
            if transactionType == 'BUY':
                action = 'bought'
                emoji = '💸'
            elif transactionType == 'SELL':
                action = 'sold'
                emoji = '🤑'
            else:
                print("Skipping corporate action:", portfolio_name, date, transactionType, symbol)
                continue

            if portfolio_select and portfolio_name.lower() != portfolio_select.lower():
                continue

            if trade_id in known_trades:
                print("Skipping known trade_id:", trade_id, date, portfolio_name, transactionType, symbol)
                continue
            newtrades.add(trade_id) # sneaky update global set

            flag = util.flag_from_market(market)
            if service == 'telegram' and len(portfolio_name) > 6: # avoid annoying linewrap
                flag = ''
            # lookup currency or fall back to less reliable sharesight currency
            currency_temp = util.currency_from_market(market)
            if currency_temp:
                currency = currency_temp
            trade_url = sharesight_url + holding_id + '/trades/' + str(trade_id) + '/edit'
            trade_link = util.link(trade_url, action, service)
            if config_hyperlinkProvider == 'google':
                holding_link = util.gfinance_link(symbol, market, service, brief=True)
            else:
                holding_link = util.yahoo_link(ticker, service, brief=True)
            payload_staging.append([date, trade_id, emoji, portfolio_name, trade_link, currency, f'{value:,}', 'of', holding_link, flag])

        payload = []
        payload_staging.sort()
        for idx, date in enumerate(sorted(dates)):
            if past_days > 1:
                payload.append(webhook.bold(date, service) + ':')
            for i, trade in enumerate(payload_staging):
                if date == trade[0]:
                    payload.append(' '.join(trade[2:]))
            if past_days > 1 and idx + 1 < len(dates):
                payload.append("")

        #payload.sort()
        #for i, e in enumerate(payload):
        #    payload[i] = ' '.join(e[2:])

        if interactive and not payload: # easter egg 4
            payload = [f"{user} No trades in the past { f'{past_days} days' if past_days != 1 else 'day' }. {random.choice(noTradesVerb)}"]
        return payload

    def trade_state_read(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            known_trades = json.loads(f.read())
            return known_trades

    def trade_state_write(state_file, newtrades):
        def opener(path, flags):
            return os.open(path, flags, 0o640)
        with open(state_file, "w", opener=opener, encoding="utf-8") as f:
            f.write(json.dumps(newtrades))

    # MAIN #
    portfolios = sharesight.get_portfolios()

    # Get trades from Sharesight
    trades = []
    known_trades = []
    newtrades = set()
    if os.path.isfile(state_file) and not interactive:
        known_trades = trade_state_read(state_file)

    if portfolio_select:
        portfoliosLower = {k.lower():v for k,v in portfolios.items()}
        portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
        if portfolio_select.lower() in portfoliosLower:
            portfolio_id = portfoliosLower[portfolio_select.lower()] # any-case input
            portfolio_select = portfoliosReverseLookup[portfolio_id] # correct-case output
        trades = trades + sharesight.get_trades(portfolio_select, portfolio_id, past_days)
    else:
        for portfolio in portfolios:
            portfolio_id = portfolios[portfolio]
            trades = trades + sharesight.get_trades(portfolio, portfolio_id, past_days)
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
                chat_id=False
            webhook.payload_wrapper(service, url, payload, chat_id)

    # write state file
    if newtrades and not interactive:
        known_trades = set(known_trades) | newtrades
        trade_state_write(state_file, list(known_trades))

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
