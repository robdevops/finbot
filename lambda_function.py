#!/usr/bin/python3

import os, time, urllib.parse, json
import datetime
from dotenv import load_dotenv
import requests

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
    if os.getenv('telegram_url'):
        webhooks['telegram'] = os.getenv('telegram_url')

    if os.getenv('trade_updates'):
        config_trade_updates = os.getenv("trade_updates", 'False').lower() in ('true', '1', 't')

    if os.getenv('price_updates'):
        config_price_updates = os.getenv("price_updates", 'False').lower() in ('true', '1', 't')

    if os.getenv('earnings_reminder'):
        config_earnings_reminder = os.getenv("earnings_reminder", 'False').lower() in ('true', '1', 't')

    config_earnings_reminder_days = 3 # default
    if os.getenv('earnings_reminder_days'):
        config_earnings_reminder_days = os.getenv('earnings_reminder_days') 
        config_earnings_reminder_days = int(config_earnings_reminder_days)

    config_price_updates_percentage = 10 # default
    if os.getenv('price_updates_percentage'):
        config_price_updates_percentage = os.getenv('price_updates_percentage') 
        config_price_updates_percentage = float(config_price_updates_percentage)

    #time_now = datetime.datetime.today() # 2022-08-23 01:35:20.310961
    time_now = datetime.datetime.utcnow() # 2022-08-22 15:35:20.311000
    date = str(time_now).split(' ')[0] # 2022-08-22
    
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
            print("Failed to get Sharesight access token")
            exit(1)
            return []
        if r.status_code != 200:
            print(f"Could not fetch token from endpoint. Code {r.status_code}. Check config in .env file")
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
            print("Failure talking to Sharesight")
            return []
        if r.status_code != 200:
            print(f"Error communicating with Sharesight API. Code: {r.status_code}")
            return []
        data = r.json()
        for portfolio in data['portfolios']:
            portfolio_dict[portfolio['name']] = portfolio['id']
        print(portfolio_dict)
        return portfolio_dict

    def sharesight_get_trades(portfolio_name, portfolio_id):
        print(f"Fetching Sharesight trades for {portfolio_name} on {date}", end=": ")
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + date + '&end_date=' + date
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        print(len(data['trades']))
        for trade in data['trades']:
           trade['portfolio'] = portfolio_name
        return data['trades']

    def sharesight_get_holdings(portfolio_name, portfolio_id):
        print(f"Fetching Sharesight holdings for {portfolio_name}", end=": ")
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/valuation.json?grouping=ungrouped&balance_date=' + date
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        print(len(data['holdings']))
        return data['holdings']

    def transform_tickers(holdings):
        tickers = []
        for holding in holdings:
            symbol = holding['symbol']
            market = holding['market']
            if market == 'ASX':
                tickers.append(symbol + '.AX')
            elif market == 'NASDAQ' or market == 'NYSE' or market == 'BATS':
                if symbol == 'DRNA':
                    continue
                tickers.append(symbol)
            else:
                continue
        return tickers
        
    def prepare_trade_payload(service, trades):
        print(f"Preparing payload: {service}")
        trade_payload = []
        if service == 'telegram':
            trade_payload.append(f"<b>Today's trades:</b>")
        elif service == 'slack':
            trade_payload.append(f"*Today's trades:*")
        else:
            trade_payload.append(f"**Today's trades:**")
        for trade in trades:
            trade_id = trade['id']
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
    
            if service == 'telegram':
                holding_link = '<a href=https://portfolio.sharesight.com/holdings/>' + str(holding_id) + f'>{symbol}</a>'
                trade_link = '<a href=https://portfolio.sharesight.com/holdings/' + str(holding_id) + '/trades/' + str(trade_id) + f'/edit>{action}</a>'
            else:
                holding_link = '<https://portfolio.sharesight.com/holdings/' + str(holding_id) + f'|{symbol}>'
                trade_link = '<https://portfolio.sharesight.com/holdings/' + str(holding_id) + '/trades/' + str(trade_id) + '/edit' + f'|{action}>'
            trade_payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value} of {holding_link} {flag}")
        return trade_payload
    
    def webhook_write(url, payload):
        # slack todo: "unfurl_links": false, "unfurl_media": false
        try:
            r = requests.post(url, headers={'Content-type': 'application/json'}, json={"text":payload})
        except:
            print(f"Failure talking to webhook: {url}")
            return []
        if r.status_code != 200:
            print(f"Error communicating with webhook. HTTP code: {r.status_code}, URL: {url}")
            return []
    
    def telegram_write(url, payload):
        payload = urllib.parse.quote_plus(payload)
        url = url + '&parse_mode=HTML' + '&disable_web_page_preview=true' + '&text=' + payload
        try:
            r = requests.get(url)
        except:
            print(f"Failure talking to webhook: {url}")
            return []
        if r.status_code != 200:
            print(f"Error communicating with webhook. HTTP code: {r.status_code}, URL: {url}")
            return []

    def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))

    def prepare_price_payload(service, yahoo_output, config_price_updates_percentage):
        price_payload = []
        if service == 'telegram':
            price_payload.append(f"<b>Price alerts:</b>")
        elif service == 'slack':
            price_payload.append(f"*Price alerts:*")
        else:
            price_payload.append(f"**Price alerts:**")
        for ticker in yahoo_output:
            percentage = yahoo_output[ticker]['percent_change']
            title = yahoo_output[ticker]['title']
            if abs(percentage) > config_price_updates_percentage:
                yahoo_url = 'https://finance.yahoo.com/quote/' + ticker
                if percentage < 0:
                    if service == 'telegram':
                        price_payload.append(f"🔻 {title} (<a href='{yahoo_url}'>{ticker}</a>) day change: {str(percentage)}%")
                    else:
                        price_payload.append(f"🔻 {title} (<{yahoo_url}|{ticker}>) day change: {str(percentage)}%")
                else:
                    if service == 'telegram':
                        price_payload.append(f"⬆️  {title} (<a href='{yahoo_url}'>{ticker}</a>) day change: {str(percentage)}%")
                    else:
                        price_payload.append(f"⬆️  {title} (<{yahoo_url}|{ticker}>) day change: {str(percentage)}%")
        print(len(price_payload)-1, f"holdings moved more than {config_price_updates_percentage}%")
        return price_payload

    def payload_wrapper(service, url, chunks):
        count=0
        for payload_chunk in chunks: # workaround potential max length
            count=count+1
            payload_chunk = '\n'.join(payload_chunk)
            if service == 'telegram':
                telegram_write(url, payload_chunk)
            else:
                webhook_write(url, payload_chunk)
            if count < len(list(chunks)):
                time.sleep(1) # workaround potential API throttling

    def to_localtime(utc_datetime):
        now_timestamp = time.time()
        offset = datetime.datetime.fromtimestamp(now_timestamp) - datetime.datetime.utcfromtimestamp(now_timestamp)
        return utc_datetime + offset

    def prepare_earnings_reminder_payload(service, yahoo_output):
        earnings_reminder_payload = []
        if service == 'telegram':
            earnings_reminder_payload.append(f"<b>Upcoming earnings:</b>")
        elif service == 'slack':
            earnings_reminder_payload.append(f"*Upcoming earnings:*")
        else:
            earnings_reminder_payload.append(f"**Upcoming earnings:**")
        for ticker in yahoo_output:
            title = yahoo_output[ticker]['title']
            yahoo_url = 'https://finance.yahoo.com/quote/' + ticker
            try:
                earnings_date = yahoo_output[ticker]['earnings_date']
            except KeyError:
                continue
            #earnings_date = earnings_reminders[ticker]
            #ticker_description = tickers[ticker]
            if earnings_date:
                if service == 'telegram':
                    earnings_reminder_payload.append(f"📣 {title} (<a href='{yahoo_url}'>{ticker}</a>) reports on {earnings_date}")
                else:
                    earnings_reminder_payload.append(f"📣 {title} (<{yahoo_url}|{ticker}>) reports on {earnings_date}")
        return earnings_reminder_payload

    def yahoo_fetch(tickers):
        print(f"fetching {len(tickers)} holdings from Yahoo")
        yahoo_output = {}
        now = int(time.time())
        soon = now + config_earnings_reminder_days * 86400
        url = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers)
        url2 = 'https://query2.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers)
        try:
            r = requests.get(url, headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
        except:
            print(f"Failed to query Yahoo. Trying alternate URL.")
            try:
                r = requests.get(url2, headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            except:
                print(f"Failed to query alternate URL. Giving up.")
                return []
            if r.status_code != 200:
                print(f"alternate URL returned {r.status_code}. Giving up.")
                return []
        if r.status_code != 200:
            print(f"Yahoo returned {r.status_code}. Trying alternate URL.")
            try:
                r = requests.get(url2, headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            except:
                print(f"Failed to query alternate URL. Giving up.")
                return []
            if r.status_code != 200:
                print(f"alternate URL returned {r.status_code}. Giving up.")
                return []
        data = r.json()
        data = data['quoteResponse']
        data = data['result']
        for item in data:
            #print(json.dumps(ticker, indent=4, sort_keys=True))
            ticker = item['symbol']
            title = item['longName']
            percent_change = item['regularMarketChangePercent']
            percent_change = round(percent_change, 2)

            # shorten long names to reduce line wrap on mobile
            title = title.replace("First Trust NASDAQ Clean Edge Green Energy Index Fund", "NASDAQ Clean Energy ETF")
            title = title.replace("Global X ", "")
            title = title.replace("The ", "")
            title = title.replace(" Australian", " Aus")
            title = title.replace(" Australia", " Aus")
            title = title.replace(" Infrastructure", " Infra")
            title = title.replace(" Manufacturing Company", " ")
            title = title.replace(" Limited", " ")
            title = title.replace(" Ltd", " ")
            title = title.replace(" Holdings", " ")
            title = title.replace(" Corporation", " ")
            title = title.replace(" Incorporated", " ")
            title = title.replace(" incorporated", " ")
            title = title.replace(" Technologies", " ")
            title = title.replace(" Technology", " ")
            title = title.replace(" Enterprises", " ")
            title = title.replace(" Ventures", " ")
            title = title.replace(" Co.", " ")
            title = title.replace(" Tech ", " ")
            title = title.replace(" Company", " ")
            title = title.replace(" Tech ", " ")
            title = title.replace(" Group", " ")
            title = title.replace(", Inc", " ")
            title = title.replace(" Inc", " ")
            title = title.replace(" Plc", " ")
            title = title.replace(" plc", " ")
            title = title.replace(" Index", " ")
            title = title.replace(" .", " ")
            title = title.replace(" ,", " ")
            title = title.replace("  ", " ")
            try:
                earningsTimestamp = item['earningsTimestamp']
                earningsTimestampStart = item['earningsTimestampStart']
                earningsTimestampEnd = item['earningsTimestampEnd']
            except (KeyError, IndexError):
                pass
            if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd: # if not estimate
                if earningsTimestamp > now and earningsTimestamp < soon:
                    human_timestamp = datetime.datetime.fromtimestamp(earningsTimestamp)
                    yahoo_output[ticker] = { "title": title, "percent_change": percent_change, "earnings_date": str(human_timestamp) }
            else:
                yahoo_output[ticker] = { "title": title, "percent_change": percent_change}
        return yahoo_output

# MAIN #
    token = sharesight_get_token(sharesight_auth_data)
    portfolios = sharesight_get_portfolios()

    # get trades from sharesight
    if config_trade_updates:
        trades = []
        for portfolio_name in portfolios:
            portfolio_id = portfolios[portfolio_name]
            trades = trades + sharesight_get_trades(portfolio_name, portfolio_id)
        if trades:
            print(len(trades), f"trades found for {date}")
        else:
            print(f"No trades found for {date}")

    # get holdings from sharesight
    if config_price_updates or config_earnings_reminder:
        holdings = []
        tickers = []
        for portfolio_name in portfolios:
            portfolio_id = portfolios[portfolio_name]
            holdings = holdings + sharesight_get_holdings(portfolio_name, portfolio_id)
            tickers = transform_tickers(holdings)

    # get yahoo data
    if config_price_updates or config_earnings_reminder:
        yahoo_output = yahoo_fetch(tickers)

    # prep and send payloads
    for service in webhooks:
        url = webhooks[service]
        if config_trade_updates:
            if trades:
                print(f"Preparing trade payload for {service}")
                trade_payload = prepare_trade_payload(service, trades)
                print(f"Sending to {service}")
                chunks = chunker(price_payload, 20)
                payload_wrapper(service, url, chunks)
        if config_price_updates:
            if tickers:
                print(f"preparing price change payload for {service}")
                price_payload = prepare_price_payload(service, yahoo_output, config_price_updates_percentage)
                if price_payload:
                    price_payload_string = '\n'.join(price_payload)
                    print(f"{price_payload_string}")
                    chunks = chunker(price_payload, 20)
                    payload_wrapper(service, url, chunks)
                else:
                    print(f"{service}: no holdings changed by {config_price_updates_percentage}% in the last session.")
        if config_earnings_reminder:
            print(f"preparing earnings reminder payload for {service}")
            earnings_reminder_payload = prepare_earnings_reminder_payload(service, yahoo_output)
            earnings_reminder_payload_string = '\n'.join(earnings_reminder_payload)
            print(f"Sending earnings reminders to {service}")
            print(earnings_reminder_payload_string)
            chunks = chunker(earnings_reminder_payload, 20)
            payload_wrapper(service, url, chunks)

