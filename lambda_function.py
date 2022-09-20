#!/usr/bin/python3

import json, os, time, urllib.parse
import datetime
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import os.path


def lambda_handler(event,context):
    load_dotenv()
    sharesight_auth = {
            "grant_type": 'client_credentials',
            "code": os.getenv('sharesight_code'),
            "client_id": os.getenv('sharesight_client_id'),
            "client_secret": os.getenv('sharesight_client_secret'),
            "redirect_uri": 'urn:ietf:wg:oauth:2.0:oob'
    }
    webhooks = {}
    if os.getenv('slack_webhook'):
        webhooks['slack'] = os.getenv('slack_webhook')
    if os.getenv('discord_webhook'):
        webhooks['discord'] = os.getenv('discord_webhook')
    if os.getenv('telegram_url'):
        webhooks['telegram'] = os.getenv('telegram_url')

    config_trade_updates = True # default
    if os.getenv('trade_updates'):
        config_trade_updates=os.getenv("trade_updates",'False').lower() in ('true','1','t')

    config_price_updates = True # default
    if os.getenv('price_updates'):
        config_price_updates=os.getenv("price_updates",'False').lower() in ('true','1','t')

    config_price_updates_percent = 10 # default
    if os.getenv('price_updates_percent'):
        config_price_updates_percent = os.getenv('price_updates_percent') 
        config_price_updates_percent = float(config_price_updates_percent)

    config_earnings = True # default
    if os.getenv('earnings'):
        config_earnings=os.getenv("earnings",'False').lower() in ('true','1','t')

    config_earnings_days = 3 # default
    if os.getenv('earnings_days'):
        config_earnings_days = os.getenv('earnings_days') 
        config_earnings_days = int(config_earnings_days)

    config_earnings_weekday = 'any' # default
    if os.getenv('earnings_weekday'):
        config_earnings_weekday = os.getenv('earnings_weekday')

    config_ex_dividend = True # default
    if os.getenv('ex_dividend'):
        config_ex_dividend=os.getenv("ex_dividend",'False').lower() in ('true','1','t')

    config_ex_dividend_days = 7 # default
    if os.getenv('ex_dividend_days'):
        config_ex_dividend_days = os.getenv('ex_dividend_days') 
        config_ex_dividend_days = int(config_ex_dividend_days)

    config_ex_dividend_weekday = 'any' # default
    if os.getenv('ex_dividend_weekday'):
        config_ex_dividend_weekday = os.getenv('ex_dividend_weekday') 

    config_shorts = False # default
    if os.getenv('shorts'):
        config_shorts=os.getenv("shorts",'False').lower() in ('true','1','t')

    config_shorts_weekday = 'any' # default
    if os.getenv('shorts_weekday'):
        config_shorts_weekday = os.getenv('shorts_weekday') 

    config_shorts_percent = 15 # default
    if os.getenv('shorts_weekday'):
        config_shorts_percent = int(os.getenv('shorts_percent'))

    time_now = datetime.datetime.today()
    today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
    start_date = time_now - datetime.timedelta(days=31)
    start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20
    file = '/tmp/sharesight_trades.txt'
    
    class BearerAuth(requests.auth.AuthBase):
        def __init__(self, token):
            self.token = token
        def __call__(self, r):
            r.headers["Authorization"] = "Bearer " + self.token
            return r
    
    def sharesight_get_token(sharesight_auth):
        print("Fetching Sharesight auth token")
        try:
            r = requests.post("https://api.sharesight.com/oauth2/token", data=sharesight_auth)
        except:
            print("Failed to get Sharesight access token")
            exit(1)
        if r.status_code == 200:
            print(r.status_code, "success sharesight")
        else:
            print(r.status_code, "Could not fetch Sharesight token. Check config in .env file")
            exit(1)
        data = r.json()
        return data['access_token']

    def sharesight_get_portfolios():
        print("Fetching Sharesight portfolios")
        portfolio_dict = {}
        url = "https://api.sharesight.com/api/v3/portfolios"
        try:
            r = requests.get(url, headers={'Content-type': 'application/json'}, auth=BearerAuth(token))
        except:
            print("Failure talking to Sharesight")
            return {}
        if r.status_code == 200:
            print(r.status_code, "success sharesight")
        else:
            print(r.status_code, "error sharesight")
            return {}
        data = r.json()
        for portfolio in data['portfolios']:
            portfolio_dict[portfolio['name']] = portfolio['id']
        print(portfolio_dict)
        return portfolio_dict

    def sharesight_get_trades(portfolio_name, portfolio_id):
        print("Fetching Sharesight trades for", portfolio_name, end=": ")
        endpoint = 'https://api.sharesight.com/api/v2/portfolios/'
        url = endpoint + str(portfolio_id) + '/trades.json' + '?start_date=' + start_date
        r = requests.get(url, auth=BearerAuth(token))
        data = r.json()
        print(len(data['trades']))
        for trade in data['trades']:
           trade['portfolio'] = portfolio_name
        return data['trades']

    def sharesight_get_holdings(portfolio_name, portfolio_id):
        holdings = {}
        print("Fetching Sharesight holdings for", portfolio_name, end=": ")
        endpoint = 'https://api.sharesight.com/api/v3/portfolios/'
        url = endpoint + str(portfolio_id) + '/performance?grouping=ungrouped&start_date=' + today
        r = requests.get(url, auth=BearerAuth(token))
        if r.status_code != 200:
            print(r.status_code, "error")
        data = r.json()
        print(len(data['report']['holdings']))
        for item in data['report']['holdings']:
            code = item['instrument']['code']
            holdings[code] = item['instrument']
        return holdings

    def transform_tickers_for_yahoo(holdings):
        tickers = []
        for holding in holdings:
            symbol = holdings[holding]['code']
            market = holdings[holding]['market_code']
            if market == 'ASX':
                tickers.append(symbol + '.AX')
            if market == 'HKG':
                tickers.append(symbol + '.HK')
            if market == 'KRX':
                tickers.append(symbol + '.KS')
            if market == 'KOSDAQ':
                tickers.append(symbol + '.KQ')
            if market == 'LSE':
                tickers.append(symbol + '.L')
            if market == 'TAI':
                tickers.append(symbol + '.TW')
            if market in ('NASDAQ', 'NYSE', 'BATS'):
                if symbol == 'DRNA':
                    continue
                tickers.append(symbol)
            else:
                continue
        tickers = list(set(tickers)) # de-dupe
        return tickers
        
    def prepare_trade_payload(service, trades):
        if os.path.isfile(file):
            known_trades = open_trades_file(file)
        else:
            known_trades = []
        newtrades = []
        payload = []
        url = "https://portfolio.sharesight.com/holdings/"
        if service == 'telegram':
            payload.append("<b>Today's trades:</b>")
        elif service == 'slack':
            payload.append("*Today's trades:*")
        elif service == 'discord':
            payload.append("**Today's trades:**")
        else:
            payload.append("Today's trades:")
        for trade in trades:
            trade_id = str(trade['id'])
            portfolio = trade['portfolio']
            date = trade['transaction_date']
            type = trade['transaction_type']
            units = str(round(trade['quantity']))
            price = str(trade['price'])
            currency = trade['brokerage_currency_code']
            symbol = trade['symbol']
            market = trade['market']
            value = str(abs(round(trade['value'])))
            holding_id = str(trade['holding_id'])

            if type not in ('BUY', 'SELL'):
                print("Skipping corporate action:", type, symbol)
                continue

            if trade_id in known_trades:
                print("Skipping known trade_id:", trade_id, type, symbol)
                continue
            else:
                newtrades.append(trade_id)

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

            currency_symbol = ''
            if currency in ['AUD', 'CAD', 'HKD', 'NZD', 'SGD', 'TWD', 'USD']:
                currency_symbol = '$'
            elif currency_symbol in ['CNY', 'JPY']:
                currency_symbol = '¥'
            elif currency == 'EUR':
                currency_symbol = '€'
            elif currency == 'GBP':
                currency_symbol = '£'
            elif currency_symbol == 'KRW':
                currency_symbol = '₩'

            verb=''
            emoji=''
            if type == 'BUY':
                verb = 'bought'
                emoji = '💸'
            elif type == 'SELL':
                verb = 'sold'
                emoji = '💰'

            if service == 'telegram':
                holding_link = '<a href="' + url + holding_id + '">' + symbol + '</a>'
                trade_link = '<a href="' + url + holding_id + '/trades/' + trade_id + '/edit">' + verb + '</a>'
            elif service in ['discord', 'slack']:
                holding_link = '<' + url + holding_id + '|' + symbol + '>'
                trade_link = '<' + url + holding_id + '/trades/' + trade_id + '/edit' + '|' + verb + '>'
            else:
                holding_link = f"({symbol})"
                trade_link = ''
            payload.append(f"{emoji} {portfolio} {trade_link} {currency} {value} of {holding_link} {flag}")

        if os.path.isfile(file):
            write_trades_file(file, newtrades, "a")
        else:
            write_trades_file(file, newtrades, "w")
        return payload
    
    def webhook_write(url, payload):
        headers = {'Content-type': 'application/json'}
        payload = {'text': payload}
        if 'hooks.slack.com' in url:
            headers = {**headers, **{'unfurl_links': 'false', 'unfurl_media': 'false'}} # FIX python 3.9
        elif 'api.telegram.org' in url:
            payload = {**payload, **{'parse_mode': 'HTML', 'disable_web_page_preview': 'true', 'disable_notification': 'true'}}
        try:
            r = requests.post(url, headers=headers, json=payload)
        except:
            print("Failure executing request:", url, headers, payload)
            return False
        if r.status_code == 200:
            print(r.status_code, "success", service)
        else:
            print(r.status_code, "error", service)
            return False
    
    def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))

    def prepare_price_payload(service, market_data):
        payload = []
        if service == 'telegram':
            payload.append("<b>Price alerts (day change):</b>")
        elif service == 'slack':
            payload.append("*Price alerts (day change):*")
        elif service == 'discord':
            payload.append("**Price alerts (day change):**")
        else:
            payload.append("Price alerts (day change):")
        for ticker in market_data:
            percent = market_data[ticker]['percent_change']
            title = market_data[ticker]['title']
            if abs(float(percent)) >= config_price_updates_percent:
                url = 'https://finance.yahoo.com/quote/' + ticker
                if percent < 0:
                    emoji = "🔻 "
                else:
                    emoji = "⬆️  "
                percent = str(round(percent))
                if service == 'telegram':
                    payload.append(emoji + title + ' (<a href="' + url + '">' + ticker + '</a>) ' + percent + '%')
                elif service in ['slack', 'discord']:
                    payload.append(emoji + title + ' (<' + url + '|' + ticker + '>) ' + percent + '%')
                else:
                    payload.append(emoji + title + ' (' + ticker + ') ' + percent + '%')
        print(len(payload)-1, f"holdings moved by {config_price_updates_percent}% or more") # -1 ignores header
        return payload

    def payload_wrapper(service, url, chunks):
        count=0
        for payload_chunk in chunks: # workaround potential max length
            count=count+1
            payload_chunk = '\n'.join(payload_chunk)
            webhook_write(url, payload_chunk)
            if count < len(list(chunks)):
                time.sleep(1) # workaround potential API throttling

    def prepare_earnings_payload(service):
        payload = []
        emoji = "📣 "
        finviz_date_list = []
        now = int(time.time())
        soon = now + config_earnings_days * 86400
        today = datetime.datetime.today()
        this_month = str(today.strftime('%b'))
        this_year = str(today.strftime('%Y'))
        next_year = str(int(this_year) + 1)
        if service == 'telegram':
            payload.append("<b>Upcoming earnings:</b>")
        elif service == 'slack':
            payload.append("*Upcoming earnings:*")
        elif service == 'discord':
            payload.append("**Upcoming earnings:**")
        else:
            payload.append("Upcoming earnings:")
        for ticker in market_data:
            title = market_data[ticker]['title']
            url = 'https://finance.yahoo.com/quote/' + ticker
            before_after_close = ''
            try:
                earnings_date = market_data[ticker]['earnings_date']
            except KeyError:
                continue
            if earnings_date == '-':
                continue
            if earnings_date:
                if '/a' in str(earnings_date) or '/b' in str(earnings_date):
                    human_date = earnings_date
                    finviz_date_list = str(earnings_date).split('/')
                    finviz_suffix = finviz_date_list[1]
                    finviz_date_list = finviz_date_list[0].split(' ')
                    finviz_month = finviz_date_list[0]
                    finviz_day = finviz_date_list[1]
                    if this_month in ('Oct','Nov','Dec') and finviz_month in ('Jan','Feb','Mar'):
                        finviz_year = next_year # guess Finviz year
                    else:
                        finviz_year = this_year
                    finviz_date = finviz_year + finviz_month + finviz_day
                    data_seconds = time.mktime(datetime.datetime.strptime(finviz_date,"%Y%b%d").timetuple())
                    if finviz_suffix == 'b':
                        data_seconds = data_seconds + 3600 * 9 # 9 AM
                    if finviz_suffix == 'a':
                        data_seconds = data_seconds + 3600 * 18 # 6 PM
                else: # yahoo
                    data_seconds = int(earnings_date)
                    data_seconds = data_seconds + 3600 * 4 # allow for Yahoo's inaccuracy
                    human_date = time.strftime('%b %d', time.localtime(data_seconds)) # Sep 08
                if data_seconds > now and data_seconds < soon:
                    if service == 'telegram':
                        payload.append(emoji + title + ' (<a href="' + url + '">' + ticker + '</a>) ' + human_date)
                    elif service in ['slack', 'discord']:
                        payload.append(emoji + title + ' (<' + url + '|' + ticker + '>) ' + human_date)
                    else:
                        payload.append(emoji + title + ' (' + ticker + ') ' + human_date)
        return payload

    def prepare_ex_dividend_payload(service, market_data):
        payload = []
        emoji = "🤑 "
        now = int(time.time())
        soon = now + config_ex_dividend_days * 86400
        if service == 'telegram':
            payload.append("<b>Ex-dividend dates. Avoid buy on:</b>")
        elif service == 'slack':
            payload.append("*Ex-dividend dates. Avoid buy on:*")
        elif service == 'discord':
            payload.append("**Ex-dividend dates. Avoid buy on:**")
        else:
            payload.append("Ex-dividend dates. Avoid buy on:")
        for ticker in market_data:
            try:
                timestamp = market_data[ticker]['ex_dividend_date']
            except KeyError:
                continue
            url = 'https://finance.yahoo.com/quote/' + ticker
            title = market_data[ticker]['title']
            if timestamp > now and timestamp < soon:
                human_date = time.strftime('%b %d', time.localtime(timestamp)) # Sep 08
                if service == 'telegram':
                    payload.append(emoji + title + ' (<a href="' + url + '">' + ticker + '</a>) ' + human_date)
                elif service in ['slack', 'discord']:
                    payload.append(emoji + title + ' (<' + url + '|' + ticker + '>) ' + human_date)
                else:
                    payload.append(emoji + title + ' (' + ticker + ') ' + human_date)
        return payload

    def fetch_yahoo(tickers):
        print("Fetching Yahoo data for " + str(len(tickers)) + " global holdings")
        yahoo_output = {}
        yahoo_urls = ['https://query1.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers)]
        yahoo_urls.append('https://query2.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers))
        headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        for url in yahoo_urls:
            try:
                r = requests.get(url, headers=headers)
            except Exception as e:
                print(e)
            else:
                if r.status_code == 200:
                    print(r.status_code, "success yahoo")
                else:
                    print(r.status_code, "returned by", url)
                    continue
                break
        else:
            print("Exhausted Yahoo API attempts. Giving up")
            return False
        data = r.json()
        data = data['quoteResponse']
        data = data['result']
        for item in data:
            ticker = item['symbol']
            title = item['longName']
            percent_change = item['regularMarketChangePercent']
            try:
                dividend = float(item['trailingAnnualDividendRate'])
            except (KeyError, IndexError):
                dividend = float(0)
            title = transform_title(title)
            try:
                earningsTimestamp = item['earningsTimestamp']
                earningsTimestampStart = item['earningsTimestampStart']
                earningsTimestampEnd = item['earningsTimestampEnd']
            except (KeyError, IndexError):
                yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend} # no date
                continue
            if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd:
                yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend, 'earnings_date': earningsTimestamp}
            else: # approximate date
                yahoo_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'dividend': dividend}
        return yahoo_output

    def transform_title(title):
            # shorten long names to reduce line wrap on mobile
            title = title.replace('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'Clean Energy ETF')
            title = title.replace('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable')
            title = title.replace('Flight Centre Travel', 'Flight Centre')
            title = title.replace('Global X ', '')
            title = title.replace('The ', '')
            title = title.replace(' Australian', ' Aus')
            title = title.replace(' Australia', ' Aus')
            title = title.replace(' Infrastructure', 'Infra')
            title = title.replace(' Manufacturing Company', ' ')
            title = title.replace(' Limited', ' ')
            title = title.replace(' Ltd', ' ')
            title = title.replace(' Holdings', ' ')
            title = title.replace(' Corporation', ' ')
            title = title.replace(' Incorporated', ' ')
            title = title.replace(' incorporated', ' ')
            title = title.replace(' Technologies', ' ')
            title = title.replace(' Technology', ' ')
            title = title.replace(' Enterprises', ' ')
            title = title.replace(' Ventures', ' ')
            title = title.replace(' Co.', ' ')
            title = title.replace(' Tech ', ' ')
            title = title.replace(' Company', ' ')
            title = title.replace(' Tech ', ' ')
            title = title.replace(' Group', ' ')
            title = title.replace(', Inc', ' ')
            title = title.replace(' Inc', ' ')
            title = title.replace(' Plc', ' ')
            title = title.replace(' plc', ' ')
            title = title.replace(' Index', ' ')
            title = title.replace(' .', ' ')
            title = title.replace(' ,', ' ')
            title = title.replace('  ', ' ')
            title = title.rstrip()
            return title

    def fetch_yahoo_ex_dividends(market_data):
        print("Fetching ex-dividend dates from Yahoo")
        base_url = 'https://query1.finance.yahoo.com/v10/finance/quoteSummary/'
        headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        for ticker in market_data:
            yahoo_urls = [base_url + ticker + '?modules=summaryDetail']
            yahoo_urls.append(base_url + ticker + '?modules=summaryDetail')
            if market_data[ticker]['dividend'] > 0:
                for url in yahoo_urls:
                    try:
                        r = requests.get(url, headers=headers)
                    except Exception as e:
                        print(e)
                    else:
                        if r.status_code != 200:
                            print(r.status_code, "error", ticker, url)
                            continue
                        break
                else:
                    print("Exhausted Yahoo API attempts. Giving up")
                    return False
                data = r.json()
                data = data['quoteSummary']
                data = data['result']
                for item in data:
                    try:
                        timestamp = item['summaryDetail']['exDividendDate']['raw']
                    except (KeyError, TypeError):
                        timestamp == ''
                    market_data[ticker]['ex_dividend_date'] = timestamp # naughty update global dict
        return

    def prepare_shorts_payload(service, market_data):
        payload = []
        emoji = "⚠️  "
        if service == 'telegram':
            payload.append("<b>Highly shorted stock warning:</b>")
        elif service == 'slack':
            payload.append("*Highly shorted stock warning:*")
        elif service == 'discord':
            payload.append("**Highly shorted stock warning:**")
        else:
            payload.append("Highly shorted stock warning:")
        for ticker in tickers:
            try:
                percent_short = market_data[ticker]['percent_short']
            except:
                continue
            if '.AX' in ticker:
                url = 'https://www.shortman.com.au/stock?q=' + ticker.replace('.AX','') # FIX python 3.9
            else:
                url = 'https://finviz.com/quote.ashx?t=' + ticker
            if float(percent_short) > config_shorts_percent:
                title = market_data[ticker]['title']
                percent_short = str(round(percent_short))
                if service == 'telegram':
                    payload.append(emoji + title + ' (<a href="' + url + '">' + ticker + '</a>) ' + percent_short + '%')
                elif service in ['slack', 'discord']:
                    payload.append(emoji + title + ' (<' + url + '|' + ticker + '>) ' + percent_short + '%')
                else:
                    payload.append(emoji + title + ' (' + ticker + ') ' + percent_short + '%')
        return payload

    def fetch_finviz(chunk):
        finviz_output = {}
        chunk_string=','.join(chunk)
        url = 'https://finviz.com/screener.ashx?v=150&c=0,1,2,30,66,68,14&t=' + chunk_string
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            print(r.status_code, "success finviz chunk")
        else:
            print(r.status_code, "error finviz chunk")
        soup = BeautifulSoup(r.content, "html.parser")
        main_div = soup.find('div', attrs={'id': 'screener-content'})
        table = main_div.find('table')
        sub = table.findAll('tr')
        rows = sub[5].findAll("tr")
        rows = rows[0].findAll("tr")
        for row in rows:
            item = row.findAll('a')
            count = item[0].text
            ticker = item[1].text
            title = item[2].text
            title = transform_title(title)
            percent_short = item[3].text.replace('%', '') # FIX python 3.9
            percent_change = item[4].text.replace('%', '')
            earnings_date = item[5].text
            dividend = item[6].text.replace('%', '')
            try:
                percent_short = float(percent_short)
            except ValueError:
                percent_short = float(0)
            try:
                percent_change = float(percent_change)
            except ValueError:
                percent_change = float(0)
            try:
                dividend = float(dividend)
            except ValueError:
                dividend = float(0)
            finviz_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'earnings_date': earnings_date, 'percent_short': percent_short, 'dividend': dividend}
        return finviz_output

    def fetch_shortman(market_data):
        print("Fetching ASX shorts from Shortman")
        content = {}
        url = 'https://www.shortman.com.au/downloadeddata/latest.csv'
        try:
            r = requests.get(url)
        except:
            print("Failure fetching", url)
            return {}
        if r.status_code == 200:
            print(r.status_code, "success shortman")
        else:
            print(r.status_code, "error communicating with", url)
            return {}
        csv = r.content.decode('utf-8')
        csv = csv.split('\r\n')
        csv.pop(0) # remove header
        del csv[-1] # remove junk
        for line in csv:
            cells = line.split(',')
            title = cells[0]
            ticker = cells[1]
            positions = cells[2]
            on_issue = cells[3]
            short_percent = cells[4]
            content[ticker] = float(short_percent)
            ticker_yahoo = ticker.replace('.AX', '') # FIX python 3.9
            if ticker_yahoo in market_data:
                market_data[ticker_yahoo]['percent_short'] = float(short_percent) # naughty update global dict
        return

    def open_trades_file(file):
        with open(file, "r") as f:
            lines = f.read().splitlines()
            return lines
    
    def write_trades_file(file, trades, action):
        with open(file, action) as f:
            for trade in trades:
                f.write(f"{trade}\n")

# MAIN #
    token = sharesight_get_token(sharesight_auth)
    portfolios = sharesight_get_portfolios()
    weekday = datetime.datetime.today().strftime('%A')

    # Get trades from Sharesight
    if config_trade_updates:
        trades = []
        for portfolio_name in portfolios:
            portfolio_id = portfolios[portfolio_name]
            trades = trades + sharesight_get_trades(portfolio_name, portfolio_id)
        if trades:
            print(len(trades), "trades found from", start_date, "until", today)
        else:
            print("No trades found for", date)

    # Fetch holdings from Sharesight, and market data from Yahoo/Finviz
    if config_price_updates or config_earnings or config_ex_dividend or config_shorts:
        holdings = {}
        tickers = []    
        tickers_us = [] # used by fetch_finviz()
        tickers_au = [] # used by fetch_shortman()
        tickers_world = [] # used by fetch_yahoo()
        finviz_output = {}
        for portfolio_name in portfolios:
            portfolio_id = portfolios[portfolio_name]
            holdings = {**holdings, **sharesight_get_holdings(portfolio_name, portfolio_id)}
        tickers = transform_tickers_for_yahoo(holdings)
        for ticker in tickers:
            if '.AX' in ticker:
                tickers_au.append(ticker)
            if '.' in ticker:
                tickers_world.append(ticker)
            else:
                tickers_us.append(ticker)
        yahoo_output = fetch_yahoo(tickers_world)
        chunks = chunker(tickers_us, 20)
        print("Fetching", len(tickers_us), "holdings from Finviz")
        for chunk in chunks:
            finviz_output = {**finviz_output, **fetch_finviz(chunk)}
        market_data = {**yahoo_output, **finviz_output} # FIX python 3.9

    # Fetch ASX shorts
    if config_shorts and tickers_au and config_shorts_weekday.lower() in {'any', 'all', weekday.lower()}:
        fetch_shortman(market_data)

    # Fetch ex_dividend_dates from Yahoo
    if config_ex_dividend:
        fetch_yahoo_ex_dividends(market_data)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        url = webhooks[service]
        if config_trade_updates:
            if trades:
                print(service, "Preparing trade payload")
                payload = prepare_trade_payload(service, trades)
                if len(payload) > 1: # ignore header
                    payload_string = '\n'.join(payload)
                    print(payload_string)
                    chunks = chunker(payload, 20)
                    payload_wrapper(service, url, chunks)
                else:
                    print("No new trades for specified date range.")
        if config_price_updates:
            if tickers:
                print(service, "Preparing price change payload")
                payload = prepare_price_payload(service, market_data)
                if len(payload) > 1: # ignore header
                    payload_string = '\n'.join(payload)
                    print(payload_string)
                    chunks = chunker(payload, 20)
                    payload_wrapper(service, url, chunks)
                else:
                    print("No holdings changed by", config_price_updates_percent, "% or more in the last session.")
        if config_earnings:
            if config_earnings_weekday.lower() in {'any', 'all', weekday.lower()}:
                print(service, "Preparing earnings date payload")
                payload = prepare_earnings_payload(service)
                if len(payload) > 1: # ignore header
                    payload_string = '\n'.join(payload)
                    print(payload_string)
                    chunks = chunker(payload, 20)
                    payload_wrapper(service, url, chunks)
            else:
                print("Skipping earnings date because today is", weekday, "but earnings_weekday is set to", config_earnings_weekday)
        if config_ex_dividend:
            if config_ex_dividend_weekday.lower() in {'any', 'all', weekday.lower()}:
                print(service, "Preparing ex-dividend date payload")
                payload = prepare_ex_dividend_payload(service, market_data)
                if len(payload) > 1: # ignore header
                    payload_string = '\n'.join(payload)
                    print(payload_string)
                    chunks = chunker(payload, 20)
                    payload_wrapper(service, url, chunks)
            else:
                print("Skipping ex-dividend: today is", weekday, "but ex_dividend_weekday is set to", config_ex_dividend_weekday)
        if config_shorts:
            if config_shorts_weekday.lower() in {'any', 'all', weekday.lower()}:
                print(service, "Preparing shorts payload")
                payload = prepare_shorts_payload(service, market_data)
                if len(payload) > 1: # ignore header
                    payload_string = '\n'.join(payload)
                    print(payload_string)
                    chunks = chunker(payload, 20)
                    payload_wrapper(service, url, chunks)
            else:
                print("Skipping short warnings because today is", weekday, "but shorts_weekday is set to", config_shorts_weekday)
