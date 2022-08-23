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

    config_price_updates_percentage = 10 # default
    if os.getenv('price_updates_percentage'):
        config_price_updates_percentage = os.getenv('price_updates_percentage') 
        config_price_updates_percentage = float(config_price_updates_percentage)

    if os.getenv('earnings'):
        config_earnings = os.getenv("earnings", 'False').lower() in ('true', '1', 't')

    config_earnings_days = 3 # default
    if os.getenv('earnings_days'):
        config_earnings_days = os.getenv('earnings_days') 
        config_earnings_days = int(config_earnings_days)

    config_earnings_weekday = 'any' # default
    if os.getenv('earnings_weekday'):
        config_earnings_weekday = os.getenv('earnings_weekday')

    if os.getenv('ex_dividend'):
        config_ex_dividend = os.getenv("ex_dividend", 'False').lower() in ('true', '1', 't')

    config_ex_dividend_days = 7 # default
    if os.getenv('ex_dividend_days'):
        config_ex_dividend_days = os.getenv('ex_dividend_days') 
        config_ex_dividend_days = int(config_ex_dividend_days)

    config_ex_dividend_weekday = 'any' # default
    if os.getenv('ex_dividend_weekday'):
        config_ex_dividend_weekday = os.getenv('ex_dividend_weekday') 

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
            elif market in ('NASDAQ', 'NYSE', 'BATS'):
                if symbol == 'DRNA':
                    continue
                tickers.append(symbol)
            else:
                continue
        tickers = list(set(tickers)) # de-dupe
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
            elif market in ('NASDAQ', 'NYSE', 'BATS'):
                flag = '🇺🇸'
            elif market in ('KRX', 'KOSDAQ'):
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

    def prepare_earnings_payload(service, yahoo_output):
        earnings_payload = []
        if service == 'telegram':
            earnings_payload.append(f"<b>Upcoming earnings:</b>")
        elif service == 'slack':
            earnings_payload.append(f"*Upcoming earnings:*")
        else:
            earnings_payload.append(f"**Upcoming earnings:**")
        for ticker in yahoo_output:
            title = yahoo_output[ticker]['title']
            yahoo_url = 'https://finance.yahoo.com/quote/' + ticker
            try:
                earnings_date = yahoo_output[ticker]['earnings_date']
            except KeyError:
                continue
            if earnings_date:
                if service == 'telegram':
                    earnings_payload.append(f"📣 {title} (<a href='{yahoo_url}'>{ticker}</a>) reports on {earnings_date}")
                else:
                    earnings_payload.append(f"📣 {title} (<{yahoo_url}|{ticker}>) reports on {earnings_date}")
        return earnings_payload

    def prepare_ex_dividend_payload(service, ex_dividend_dates, yahoo_output):
        ex_dividend_payload = []
        if service == 'telegram':
            ex_dividend_payload.append(f"<b>Upcoming ex-dividend dates:</b>")
        elif service == 'slack':
            ex_dividend_payload.append(f"*Upcoming ex-dividend dates:*")
        else:
            ex_dividend_payload.append(f"**Upcoming ex-dividend dates:**")
        for ticker in ex_dividend_dates:
            ex_dividend_date = ex_dividend_dates[ticker]
            yahoo_url = 'https://finance.yahoo.com/quote/' + ticker
            title = yahoo_output[ticker]['title']
            if service == 'telegram':
                ex_dividend_payload.append(f"🤑 {title} (<a href='{yahoo_url}'>{ticker}</a>) goes ex-dividend on {ex_dividend_date}")
            else:
                ex_dividend_payload.append(f"🤑 {title} (<{yahoo_url}|{ticker}>) goes ex-dividend on {ex_dividend_date}")
        return ex_dividend_payload

    def yahoo_fetch(tickers):
        print(f"Fetching Yahoo price info for {len(tickers)} holdings")
        yahoo_output = {}
        now = int(time.time())
        soon = now + config_earnings_days * 86400
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
            title = title.rstrip()
            try:
                earningsTimestamp = item['earningsTimestamp']
                earningsTimestampStart = item['earningsTimestampStart']
                earningsTimestampEnd = item['earningsTimestampEnd']
            except (KeyError, IndexError):
                yahoo_output[ticker] = { "title": title, "percent_change": percent_change} # no earnings date
                continue
            if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd:
                if earningsTimestamp > now and earningsTimestamp < soon:
                    human_timestamp = datetime.datetime.fromtimestamp(earningsTimestamp)
                    yahoo_output[ticker] = { "title": title, "percent_change": percent_change, "earnings_date": str(human_timestamp) }
                else:
                    yahoo_output[ticker] = { "title": title, "percent_change": percent_change} # earnings date past
            else:
                yahoo_output[ticker] = { "title": title, "percent_change": percent_change} # earnings date not announced
        return yahoo_output

    def yahoo_fetch_ex_dividends(tickers, config_ex_dividend_days):
        print(f"Fetching {len(tickers)} ex-dividend dates from Yahoo")
        now = int(time.time())
        soon = now + config_ex_dividend_days * 86400
        ex_dividend_dates = {}
        for ticker in tickers:
            yahoo_output = {}
            url = 'https://query1.finance.yahoo.com/v10/finance/quoteSummary/' + ticker + '?modules=summaryDetail'
            url2 = 'https://query2.finance.yahoo.com/v10/finance/quoteSummary/' + ticker + '?modules=summaryDetail'
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
            data = data['quoteSummary']
            data = data['result']
            for item in data:
                try:
                    raw = item['summaryDetail']['exDividendDate']['raw']
                    fmt = item['summaryDetail']['exDividendDate']['fmt']
                except (KeyError, TypeError):
                    continue
                if raw > now and raw < soon:
                    ex_dividend_dates[ticker] = fmt
        return ex_dividend_dates

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

    # Fetch holdings from sharesight, and holding detail from Yahoo
    if config_price_updates or config_earnings or config_ex_dividend:
        holdings = []
        tickers = []    
        for portfolio_name in portfolios:
            portfolio_id = portfolios[portfolio_name]
            holdings = holdings + sharesight_get_holdings(portfolio_name, portfolio_id)
            tickers = transform_tickers(holdings)
        yahoo_output = yahoo_fetch(tickers)

    # fetch ex_dividend_dates from Yahoo
    if config_ex_dividend:
        ex_dividend_dates = yahoo_fetch_ex_dividends(tickers, config_ex_dividend_days)
        #print(json.dumps(ex_dividend_dates, indent=4, sort_keys=True))

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
                    print(price_payload_string)
                    chunks = chunker(price_payload, 20)
                    payload_wrapper(service, url, chunks)
                else:
                    print(f"{service}: no holdings changed by {config_price_updates_percentage}% in the last session.")
        if config_earnings:
            weekday = datetime.datetime.today().strftime('%A')
            if config_earnings_weekday.lower() in {'any', 'all', weekday.lower()}:
                print(f"preparing earnings date payload for {service}")
                earnings_payload = prepare_earnings_payload(service, yahoo_output)
                earnings_payload_string = '\n'.join(earnings_payload)
                print(f"Sending earnings dates to {service}")
                print(earnings_payload_string)
                chunks = chunker(earnings_payload, 20)
                payload_wrapper(service, url, chunks)
            else:
                print(f"Skipping earnings date because today is {weekday} and earnings_weekday is set to {config_earnings_weekday}")
        if config_ex_dividend:
            weekday = datetime.datetime.today().strftime('%A')
            if config_ex_dividend_weekday.lower() in {'any', 'all', weekday.lower()}:
                print(f"preparing ex-dividend date payload for {service}")
                ex_dividend_payload = prepare_ex_dividend_payload(service, ex_dividend_dates, yahoo_output)
                ex_dividend_payload_string = '\n'.join(ex_dividend_payload)
                print(f"Sending ex-dividend dates to {service}")
                print(ex_dividend_payload_string)
                chunks = chunker(ex_dividend_payload, 20)
                payload_wrapper(service, url, chunks)
            else:
                print(f"Skipping ex-dividend date because today is {weekday} and ex_dividend_weekday is set to {config_ex_dividend_weekday}")
