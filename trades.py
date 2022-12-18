#!/usr/bin/python3

import json, os, random
import datetime

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo

def lambda_handler(chat_id=config_telegramChatID, past_days=config_past_days, service=False, user='', interactive=False):
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
            if service == 'telegram':
                trade_link = '<a href="' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit">' + verb + '</a>'
                holding_link = util.yahoo_link(ticker, service, brief=True)
            elif service in {'discord', 'slack'}:
                trade_link = '<' + sharesight_url + holding_id + '/trades/' + trade_id + '/edit' + '|' + verb + '>'
                holding_link = util.yahoo_link(ticker, service, brief=True)
            else:
                trade_link = verb
                holding_link = symbol
            payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value:,} of {holding_link} {flag}")
        if len(payload):
            message = 'New trades:'
            message = webhook.bold(message, service)
            payload.insert(0, message)
        else:
            if interactive:
                # easter egg 3
                noTradesVerb = [
                        "The money is probably resting in another account",
                        "Oh well. The market would have just gone down anyway",
                        "Heating bills don't pay themselves you know",
                        "You were fearful when others were also fearful",
                        "I bet you're regretting that extra 1¢ on your limit order now",
                        "This is why you can't have nice things",
                        "But I'm sure that's just a rounding error",
                        "Nothing + nothing = more nothing. Well played",
                        "Or maybe there was. They don't pay me for this you know",
                        "I guess that's right. Maybe... I'm kinda busy with ChatGPT in another window",
                        "I like this contrarian play you're having on 'being in it to win it'",
                        "With your stock picking skills, this is probably for the best"
                        ]
                payload = [f"{user} No trades in the past { f'{past_days} days' if past_days != 1 else 'day' }. {random.choice(noTradesVerb)}"]
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
    if interactive:
        payload = prepare_trade_payload(service, trades)
        if service == "slack":
            url = 'https://slack.com/api/chat.postMessage'
        elif service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    else:
        for service in webhooks:
            payload = prepare_trade_payload(service, trades)
            url = webhooks[service]
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    # write state file
    if newtrades and not interactive:
        trade_cache_write(cache_file, newtrades)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
