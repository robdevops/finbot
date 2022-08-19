#!/usr/bin/python3

import requests
from datetime import datetime
import json
import os
from dotenv import load_dotenv

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
        webhooks['slack'] = os.getenv('slack_webhook'),
    if os.getenv('discord_webhook'):
        webhooks['discord'] = os.getenv('discord_webhook'),

    print(webhooks)
    today = datetime.today().strftime('%Y-%m-%d')
    
    class BearerAuth(requests.auth.AuthBase):
        def __init__(self, token):
            self.token = token
        def __call__(self, r):
            r.headers["Authorization"] = "Bearer " + self.token
            return r
    
    def sharesight_get_token(sharesight_auth_data):
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

        return portfolio_dict


    def sharesight_get_trades(portfolio_name, portfolio_id):
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + today + '&end_date=' + today
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        #print(json.dumps(data['trades'], indent=4, sort_keys=True))
        
        for trade in data['trades']:
           trade['portfolio'] = portfolio_name
        return data['trades']


    def prepare_payload(service, alltrades):
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
            holding_id = trade['holding_id']
            holding_link = '<https://portfolio.sharesight.com/holdings/' + str(holding_id) + f'|{symbol}>'
            #print(f"{date} {portfolio} {type} {units} {symbol} on {market} for {price} {currency} per share.")
    
            if service == 'slack':
                flag_prefix=':flag-'
            else:
                flag_prefix=':flag_'

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
            payload += f"{emoji} {portfolio} {trade_link} {currency} {value} worth of {holding_link} {flag}\n"
        return payload
    
    def webhook_write(url, payload):
        try:
            r = requests.post(url, headers={'Content-type': 'application/json'}, json={"text":payload})
        except:
            print(f'Failure talking to webhook: {url}')
            return []
    
        if r.status_code != 200:
            print(f'Error communicating with webhook. HTTP code {r.status_code}, URL: {url}')
            return []
    
    
    token = sharesight_get_token(sharesight_auth_data)
    portfolios = sharesight_get_portfolios()
    alltrades = []

    for portfolio in portfolios:
        alltrades = alltrades + sharesight_get_trades(portfolio, portfolios[portfolio])

    if alltrades:
        print("Found", len(alltrades), "trades in the specified range.\n")
        for service in webhooks:
            print(f"preparing {service} payload...\n")
            payload = prepare_payload(service, alltrades)
            url = webhooks[service]
            webhook_write(url, payload)
    else:
        print("No trades found in the specified date range.")
    
