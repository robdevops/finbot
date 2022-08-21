#!/usr/bin/python3

import requests
from datetime import datetime
import json
import os
from dotenv import load_dotenv
import urllib.parse
import time
import yfinance as yf
import re

def lambda_handler(event,context):
    load_dotenv()
    sharesight_auth_data = {
            "grant_type": os.getenv('sharesight_grant_type'),
            "code": os.getenv('sharesight_code'),
            "client_id": os.getenv('sharesight_client_id'),
            "client_secret": os.getenv('sharesight_client_secret'),
            "redirect_uri": os.getenv('sharesight_redirect_uri')
    }
    webhooks = {}
    if os.getenv('slack_webhook'):
        webhooks['slack'] = os.getenv('slack_webhook')
    if os.getenv('discord_webhook'):
        webhooks['discord'] = os.getenv('discord_webhook')

    telegram_url = os.getenv('telegram_url')
    if os.getenv('alert_threshold'):
        alert_threshold = os.getenv('alert_threshold') 
        alert_threshold = float(alert_threshold)
    date = datetime.today().strftime('%Y-%m-%d')
    #date = '2022-08-13'
    
    class BearerAuth(requests.auth.AuthBase):
        def __init__(self, token):
            self.token = token
        def __call__(self, r):
            r.headers["Authorization"] = "Bearer " + self.token
            return r
    
    def sharesight_get_token(sharesight_auth_data):
        print("Fetching Sharesight auth token")
        try:
            r = requests.post("https://api.sharesight.com/oauth2/token", data=sharesight_auth_data)
        except:
            print(f'Failed to get Sharesight access token')
            exit(1)
            return []
    
        if r.status_code != 200:
            print(f'Could not fetch token from endpoint. Code {r.status_code}. Check config in .env file')
            exit(1)
            return []
    
        data = r.json()
        return data['access_token']


    def sharesight_get_portfolios():
        print("Fetching Sharesight portfolios")
        portfolio_dict = {}
        try:
            r = requests.get("https://api.sharesight.com/api/v2/portfolios.json", headers={'Content-type': 'application/json'}, auth=BearerAuth(token))
        except:
            print(f'Failure talking to Sharesight')
            return []
    
        if r.status_code != 200:
            print(f'Error communicating with Sharesight API. Code {r.status_code}')
            return []
    
        data = r.json()
        for portfolio in data['portfolios']:
            portfolio_dict[portfolio['name']] = portfolio['id']

        print(portfolio_dict)
        return portfolio_dict


    def sharesight_get_trades(portfolio_name, portfolio_id):
        print(f"Fetching Sharesight trades for {portfolio_name} on {date}", end=': ')
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + date + '&end_date=' + date
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        print(len(data['trades']))
        for trade in data['trades']:
           trade['portfolio'] = portfolio_name
        return data['trades']


    def sharesight_get_holdings(portfolio_id, portfolio_name):
        print(f"Fetching Sharesight holdings for {portfolio_name}", end=': ')
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/valuation.json?grouping=ungrouped&balance_date=' + date
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        print(len(data['holdings']))
        return data

    def holdings_to_yahoo_tickers(holdings):
        tickers = {}
        for holding in holdings['holdings']:
            symbol = holding['symbol']
            name = holding['name']
            market = holding['market']

            # shorten long names to reduce line wrap on mobile
            name = name.replace("- Ordinary Shares - Class A", "")
            name = name.replace("Global X Funds - Global X ", "")
            name = name.replace("- New York Shares", "")
            name = name.replace("Co (The)", " ")
            name = name.replace("- ADR", "")
            name = name.replace(" Index", " ")
            name = name.replace(" Enterprises", " ")
            name = name.replace(" Enterprise", " ")
            name = name.replace(" Enterpr", " ")
            name = name.replace(" Group", " ")
            name = name.replace(" Co.", " ")
            name = name.replace(" Holdings", " ")
            name = name.replace(" Infrastructure", " Infra")
            name = name.replace(" Technologies", " ")
            name = name.replace(" Technology", " ")
            name = name.replace(" Plc", " ")
            name = name.replace(" Limited", " ")
            name = name.replace(" Ltd", " ")
            name = name.replace(" Incorporated", " ")
            name = name.replace(" Inc", " ")
            name = name.replace(" Corporation", " ")
            name = name.replace(" Corp", " ")
            name = name.replace(" Australian", " Aus")
            name = name.replace(" Australia", " Aus")
            name = name.replace("Etf", "ETF")
            name = name.replace("Tpg", "TPG")
            name = name.replace("Rea", "REA")
            name = name.replace(" .", " ")
            name = name.replace("  ", " ")
            name = name.rstrip()
            if symbol == 'QCLN':
                name = 'NASDAQ Clean Energy ETF'
            if symbol == 'LIS' and market == 'ASX':
                name = 'LI-S Energy'
            if symbol == 'TSM':
                name = 'Taiwan Semiconductor'
            if symbol == 'MAP' and market == 'ASX':
                name = 'Microba Life Sciences'
            if symbol == 'DRNA' and market == 'NASDAQ':
                continue

            if market == 'ASX':
                tickers[symbol + '.AX'] = name
            elif market == 'NASDAQ' or market == 'NYSE' or market == 'BATS':
                tickers[symbol] = name
            else:
                continue
        return tickers
        
    def prepare_payload(service, alltrades):
        print("Preparing payload")
        payload = ''
        for trade in alltrades:
            id = trade['id']
            portfolio = trade['portfolio']
            date = trade['transaction_date']
            type = trade['transaction_type']
            units = round(trade['quantity'])
            price = trade['price']
            currency = trade['brokerage_currency_code']
            symbol = trade['symbol']
            market = trade['market']
            value = round(trade['value'])
            value = abs(value)
            holding_id = trade['holding_id']
            holding_link = '<https://portfolio.sharesight.com/holdings/' + str(holding_id) + f'|{symbol}>'
            #print(f"{date} {portfolio} {type} {units} {symbol} on {market} for {price} {currency} per share.")
    
            if service == 'slack':
                flag_prefix=':flag-'
            else:
                flag_prefix=':flag_'

            flag=''
            if market == 'ASX':
                flag = flag_prefix + 'au:'
            elif market == 'NASDAQ' or market == 'NYSE' or market == 'BATS':
                flag = flag_prefix + 'us:'
            elif market == 'KRX' or market == 'KOSDAQ':
                flag = flag_prefix + 'kr:'
            elif market == 'TAI':
                flag = flag_prefix + 'tw:'
            elif market == 'HKG':
                flag = flag_prefix + 'hk:'
            elif market == 'LSE':
                flag = flag_prefix + 'gb:'
    
            action=''
            emoji=''
            if type == 'BUY':
                action = 'bought'
                emoji = ':money_with_wings:'
            elif type == 'SELL':
                action = 'sold'
                emoji = ':moneybag:'
    
            trade_link = '<https://portfolio.sharesight.com/holdings/' + str(holding_id) + '/trades/' + str(id) + '/edit' + f'|{action}>'
            payload += f"{emoji} {portfolio} {trade_link} {currency} {value} of {holding_link} {flag}\n"
        return payload
    
    def prepare_payload_telegram(alltrades):
        print("Preparing payload - telegram")
        payload = []
        for trade in alltrades:
            id = trade['id']
            portfolio = trade['portfolio']
            date = trade['transaction_date']
            type = trade['transaction_type']
            units = round(trade['quantity'])
            price = trade['price']
            currency = trade['brokerage_currency_code']
            symbol = trade['symbol']
            market = trade['market']
            value = round(trade['value'])
            value = abs(value)
            holding_id = trade['holding_id']
            holding_link = '<a href=https://portfolio.sharesight.com/holdings/>' + str(holding_id) + f'>{symbol}</a>'
            #print(f"{date} {portfolio} {type} {units} {symbol} on {market} for {price} {currency} per share.")

            flag=''
            if market == 'ASX':
                flag = '🇦🇺'
            elif market == 'NASDAQ' or market == 'NYSE' or market == 'BATS':
                flag = '🇺🇸'
            elif market == 'KRX' or market == 'KOSDAQ':
                flag = '🇰🇷'
            elif market == 'TAI':
                flag = '🇹🇼'
            elif market == 'HKG':
                flag = '🇭🇰'
            elif market == 'LSE':
                flag = '🇬🇧'

            action=''
            emoji=''
            if type == 'BUY':
                action = 'bought'
                emoji = '💸'
            elif type == 'SELL':
                action = 'sold'
                emoji = '💰'

            trade_link = '<a href=https://portfolio.sharesight.com/holdings/' + str(holding_id) + '/trades/' + str(id) + f'/edit>{action}</a>'
            #trade_link = f'[{action}](https://portfolio.sharesight.com/holdings/' + str(holding_id) + '/trades/' + str(id) + '/edit)'
            #payload += f"{emoji} {portfolio} {trade_link} {currency} {value} of {holding_link} {flag}\n"
            #payload.append(f"{portfolio} {action} {currency} {value} of {symbol}")
            payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value} of {holding_link} {flag}")
        return payload

    def webhook_write(url, payload):
        # slack: "unfurl_links": false, "unfurl_media": false
        try:
            r = requests.post(url, headers={'Content-type': 'application/json'}, json={"text":payload})
        except:
            print(f'Failure talking to webhook: {url}')
            return []
    
        if r.status_code != 200:
            print(f'Error communicating with webhook. HTTP code {r.status_code}, URL: {url}')
            return []
    
    def telegram_write(url, payload):
        print("Sending to telgram")
        payload = urllib.parse.quote_plus(payload)
        url = url + '&parse_mode=HTML' + '&disable_web_page_preview=true' + '&text=' + payload
        #url = url + '&parse_mode=MarkdownV2' + '&disable_web_page_preview=true' + '&text=' + payload
        # post method
        #data = { "text": payload }
        #url = url + '&parse_mode=MarkdownV2' + '&disable_web_page_preview=true'
        try:
            r = requests.get(url)
            #r = requests.post(url, data=data)
        except:
            print(f'Failure talking to webhook: {url}')
            return []

        if r.status_code != 200:
            print(f'Error communicating with webhook. HTTP code {r.status_code}, URL: {url}')
            return []

    def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))


    def percentage_change(previous, current):
        if current == previous:
            return 0
        try:
            return (abs(current - previous) / previous) * 100.0
        except ZeroDivisionError:
            return float('inf')
    
    def yahoo_get_history(stockcode):
        stock = yf.Ticker(stockcode)
        history = stock.history(period="2d")

        #                     Open    High        Low       Close    Volume  Dividends  Stock Splits
        #Date
        #2022-08-18  97.739998  101.07  96.730003  100.440002  76059500          0             0
        #2022-08-19  98.669998   99.25  94.589996   95.949997  67167500          0             0
    
        price = {}
        count=0
        for line in str(history).splitlines():
            if match := re.search(r'([0-9]{4}-[0-9]{2}-[0-9]{2}) +(\d+\.\d+) +(\d+\.\d+) +(\d+\.\d+) +(\d+\.\d+) +(\d+)', line):
                count=count+1
                date = match.group(1)
                openprice = float(match.group(2))
                high = float(match.group(3))
                low = float(match.group(4))
                close = float(match.group(5))
                volume = int(match.group(6))
                price[count] = close
        return price

    def compare_prices(tickers, alert_threshold):
        alert = []
        alert_telegram = []
        all_tickers_string = ' '.join(tickers)
        print("Fetching Yahoo price histories")
        print(all_tickers_string)
        data = yf.download(all_tickers_string, period="2d", group_by='ticker')

        for ticker in tickers:
            previous=data[ticker].to_numpy()[0][4]
            current=data[ticker].to_numpy()[1][4]
            #print(ticker, previous, current)
            percentage = percentage_change(previous, current)
            percentage = round(percentage, 2)
            if percentage > alert_threshold:
                yahoo_url = 'https://finance.yahoo.com/quote/' + ticker
                if previous > current:
                    alert.append(f'🔻{tickers[ticker]} (<{yahoo_url}|{ticker}>) day change: -{str(percentage)}%')
                    alert_telegram.append('🔻' + tickers[ticker] + ' (<a href="' + yahoo_url + '">' + ticker + '</a>) ' + "day change: -" + str(percentage) + '%')
                else:
                    alert.append(f'⬆️ {tickers[ticker]} (<{yahoo_url}|{ticker}>) day change: {str(percentage)}%')
                    alert.telegram.append('⬆️ ' + tickers[ticker] + ' (<a href="' + yahoo_url + '">' + ticker + '</a>) ' + "day change: " + str(percentage) + '%')
        return alert, alert_telegram

    token = sharesight_get_token(sharesight_auth_data)
    portfolios = sharesight_get_portfolios()
    alltrades = []
    tickers = {}

    for portfolio in portfolios:
        alltrades = alltrades + sharesight_get_trades(portfolio, portfolios[portfolio])
        holdings = sharesight_get_holdings(portfolios[portfolio], portfolio)
        tickers = {**tickers, **holdings_to_yahoo_tickers(holdings)}

    if alltrades:
        print("Found", len(alltrades), "trades in the specified range")
        for service in webhooks:
            print(f"preparing {service} payload")
            payload = prepare_payload(service, alltrades)
            url = webhooks[service]
            print(f"sending to {service}")
            webhook_write(url, payload)
        if telegram_url:
            print('preparing telegram payload')
            payload = prepare_payload_telegram(alltrades)
            for payload_chunk in chunker(payload, 20): # split to workaround potential max length
                payload_chunk = '\n'.join(payload_chunk)
                telegram_write(telegram_url, payload_chunk)
                time.sleep(1)
    else:
        print(f"No trades found for {date}")
    
    if tickers and alert_threshold:
        #print(json.dumps(tickers, indent=4, sort_keys=True))
        alert, alert_telegram = compare_prices(tickers, alert_threshold)
        if alert:
            alert = '\n'.join(alert)
            for service in webhooks:
                print(alert)
                url = webhooks[service]
                webhook_write(url, alert)
        else:
            print(f"No stocks changed {alert_threshold}% or more in the last session.")

        if alert_telegram and telegram_url:
            alert_telegram = '\n'.join(alert_telegram)
            print(alert_telegram)
            telegram_write(telegram_url, alert_telegram)

