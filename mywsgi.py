#!/usr/bin/python3

from gevent import pywsgi
from itertools import groupby
from urllib.parse import parse_qs
import datetime
import json, re, time, random
import threading
#from itertools import pairwise # python 3.10

from lib.config import *
import lib.sharesight as sharesight
import lib.slack as telegram
import lib.telegram as telegram
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo
import premarket
import shorts
import trades

def main(environ, start_response):
    request_body = environ['wsgi.input'].read()
    inbound = json.loads(request_body)

    # Set the response status code and headers
    status = '200 OK'
    headers = [('Content-type', 'application/json')]
    start_response(status, headers)

    # handle incoming request
    timestamp = datetime.datetime.today()
    timestamp = str(timestamp.strftime('%H:%M:%S')) # 2022-09-20

    uri = environ['PATH_INFO']
    if debug:
        try:
            print(f"[{timestamp}]: inbound {uri}", json.dumps(inbound, indent=4))
        except Exception as e:
            print(e, "raw body: ", inbound)

    # first pass
    user=''
    userRealName=''
    if uri == '/telegram':
        botName = '@' + telegram.getBotName()
        service = 'telegram'
        if "message" in inbound:
            if "text" in inbound["message"]:
                message = inbound["message"]["text"]
                chat_id = inbound["message"]["chat"]
                chat_id = str(chat_id["id"])
                if "username" in inbound["message"]["from"]:
                    user = '@' + inbound["message"]["from"]["username"]
                    userRealName = inbound["message"]["from"]["first_name"]
                else:
                    user = '@' + inbound["message"]["from"]["first_name"]
                print(f"[{timestamp} {service}]:", user, message)
            else:
                print(f"[{timestamp} {service}]: unhandled: 'message' without 'text'")
                return [b'<h1>Unhandled</h1>']
        elif "edited_message" in inbound:
            if "text" in inbound["edited_message"]:
                message = inbound["edited_message"]["text"]
                chat_id = inbound["edited_message"]["chat"]
                chat_id = str(chat_id["id"])
                if "username" in inbound["edited_message"]["from"]:
                    user = inbound["edited_message"]["from"]["username"]
                else:
                    user = inbound["edited_message"]["from"]["first_name"]
                print(f"[{timestamp} {service}]:", service, user, "[edit]", message)
            else:
                print(f"[{timestamp} {service}]: unhandled: 'edited_message' without 'text'")
                return [b'<h1>Unhandled</h1>']
        elif "channel_post" in inbound:
            message = inbound["channel_post"]["text"]
            chat_id = inbound["channel_post"]["chat"]["id"]
            user = ''
            print(f"[{timestamp} {service}]:", service, message)
        else:
            print(f"[{timestamp} {service}]: unhandled: not 'message' nor 'channel_post'")
            return [b'<h1>Unhandled</h1>']
    elif uri == '/slack':
        service = 'slack'
        if 'type' in inbound:
            if inbound['type'] == 'url_verification':
                response = json.dumps({"challenge": inbound["challenge"]})
                print("replying with", response)
                response = bytes(response, "utf-8")
                return [response]
            if inbound['type'] == 'event_callback':
                message = inbound['event']['text']
                message = re.sub(r'<http://.*\|([\w\.]+)>', '\g<1>', message) # <http://dub.ax|dub.ax> becomes dub.ax
                message = re.sub(r'<(@[\w\.]+)>', '\g<1>', message) # <@QWERTY> becomes @QWERTY
                user = '<@' + inbound['event']['user'] + '>' # ZXCVBN becomes <@ZXCVBN>
                botName = '@' + inbound['authorizations'][0]['user_id'] # QWERTY becomes @QWERTY
                chat_id = inbound['event']['channel']
                print(f"[{timestamp} {service}]:", service, user, message)
            else:
                print(f"[{timestamp} {service}]: unhandled 'type'")
                return [b'<h1>Unhandled</h1>']
        else:
            print(f"[{timestamp} {service}]: unhandled: no 'type'")
            return [b'Unhandled']
    else:
        print(timestamp, "Unknown URI", uri)
        status = "404 Not Found"
        start_response(status, headers)
        return [b'<h1>404</h1>']

    def worker():
        process_request(service, chat_id, user, message, botName, userRealName)

    # process in a background thread so we don't keep the requesting client waiting
    t = threading.Thread(target=worker)
    t.start()

    # Return an empty response to the client
    print(status, "closing inbound from", service)
    return [b'']

def process_request(service, chat_id, user, message, botName, userRealName):
    interactive=True
    if not len(userRealName):
        userRealName = user
    stockfinancial_command = "^\!([\w\.]+)\s*(bio|info|profile)*|^" + botName + "\s+([\w\.]+)\s*(bio|info|profile)*"
    watchlist_command = "^\!watchlist\s*([\w]+)*\s*([\w\.]+)*|^" + botName + "\s+watchlist\s*(\w+)*\s*([\w\.]+)*"
    trades_command = "^\!trades\s*(\d+)*|^" + botName + "\s+trades\s*(\d+)*"
    holdings_command = "^\!holdings\s*([\w\s]+)*|^" + botName + "\s+holdings\s*([\w\s]+)*"
    shorts_command = "^\!shorts\s*([\d]+)*|^" + botName + "\s+shorts\s*([\d]+)*"
    premarket_command = "^\!premarket\s*([\d]+)*|^" + botName + "\s+premarket\s*([\d]+)*"
    m_stockfinancial = re.match(stockfinancial_command, message)
    m_watchlist = re.match(watchlist_command, message)
    m_trades = re.match(trades_command, message)
    m_holdings = re.match(holdings_command, message)
    m_shorts = re.match(shorts_command, message)
    m_premarket = re.match(premarket_command, message)
    if m_watchlist:
        action = False
        ticker = False
        if m_watchlist.group(3) and m_watchlist.group(4):
            action = m_watchlist.group(3).lower()
            ticker = m_watchlist.group(4).upper()
        elif m_watchlist.group(1) and m_watchlist.group(2):
            action = m_watchlist.group(1).lower()
            ticker = m_watchlist.group(2).upper()
        if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
            action = 'delete'
        payload = prepare_watchlist(service, user, action, ticker)
        url = webhooks[service]
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        elif service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif message in ("!help", "!usage", botName + " help", botName + " usage"):
        payload = prepare_help(service, user, botName)
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        elif service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    # easter egg 1
    elif message in ("!thanks", "!thankyou", "!thank you", "!tyvm", "TYVM", botName + " thanks", botName + " thankyou", botName + " thank you", botName + " tyvm", botName + " TYVM"):
        time.sleep(3) # pause for realism
        payload = [f"You're very welcome, {userRealName}! 😇"]
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        elif service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_premarket:
        premarket_threshold = config_price_percent
        if m_premarket.group(2):
            premarket_threshold = int(m_premarket.group(2))
        elif m_premarket.group(1):
            premarket_threshold = int(m_premarket.group(1))
        premarket.lambda_handler(chat_id, premarket_threshold, interactive, service, user)
    elif m_shorts:
        print("starting shorts report...")
        shorts_threshold = config_shorts_percent
        if m_shorts.group(2):
            shorts_threshold = int(m_shorts.group(2))
        elif m_shorts.group(1):
            shorts_threshold = int(m_shorts.group(1))
        shorts.lambda_handler(chat_id, shorts_threshold, interactive, service, user)
    elif m_trades:
        if m_trades.group(2):
            days = int(m_trades.group(2))
        elif m_trades.group(1):
            days = int(m_trades.group(1))
        else:
            days = 1
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        if service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        # easter egg 2
        searchVerb = [
                'Asking ChatGPT to help me find',
                'Avoiding eye contact with',
                'Carrying the 1 on',
                'Combing through',
                'Conjuring up',
                'Digging up',
                'Dispatching fluffy dogs to sniff down',
                'Entering metaverse for maximum inefficiency on',
                'Excavating',
                'Foraging for',
                'Hiring developers to troubleshoot',
                'Loading backup tapes for',
                'Manifesting', 'Massaging data for',
                'Panning for',
                'Performing expert calculus on',
                'Plucking',
                'Poking a stick at',
                'Praying for',
                'Raking up',
                'Reciting incantations on',
                'Repairing file-system to restore',
                'Resetting Sharesight password to get',
                'Rummaging for',
                'SELECT * FROM topsecret WHERE',
                'Sacrificing wildebeest to recover',
                'Shooing rodents to access',
                'Sifting through', 'Summoning',
                'Training pigeons to fetch',
                'Transcribing Hebrew for',
                'Unshredding documents for',
                'Unspilling coffee to read',
                'ls -l /var/lib/topsecret/ | grep'
                ]
        payload = [ f"{random.choice(searchVerb)} trades from the past { f'{days} days' if days != 1 else 'day' } 🔍" ]
        #payload = [ f"{user} beep boop. Rummaging for trades from the past {days} days 🔍" ]
        webhook.payload_wrapper(service, url, payload, chat_id)
        trades.lambda_handler(chat_id, days, interactive, service, user)
    elif m_holdings:
        payload = []
        portfolioName = False
        print("Starting holdings report")
        if m_holdings.group(2):
            portfolioName = m_holdings.group(2)
        elif m_holdings.group(1):
            portfolioName = m_holdings.group(1)
        portfolios = sharesight.get_portfolios()
        portfoliosLower = {k.lower():v for k,v in portfolios.items()}
        if portfolioName:
            if portfolioName.lower() in portfoliosLower:
                portfolioId = portfoliosLower[portfolioName.lower()]
                tickers = sharesight.get_holdings(portfolioName, portfolioId)
                market_data = yahoo.fetch(tickers)
                print("")
                brief = True
                for item in market_data:
                    ticker = market_data[item]['ticker']
                    title = market_data[item]['profile_title']
                    yahoo_link = util.yahoo_link(ticker, service, brief)
                    payload.append(f"{title} ({yahoo_link})")
                portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
                payload.sort()
                if len(payload):
                    payload.insert(0, webhook.bold("Holdings for " + portfoliosReverseLookup[portfolioId], service))
            else:
                payload = [ f"{user} {portfolioName} portfolio not found. I only know about:" ]
                for item in portfolios:
                    payload.append( item )
        else:
            payload = [ f"{user} Please try again specifying a portfolio:" ]
            for item in portfolios:
                payload.append( item )
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        elif service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_stockfinancial:
        print("starting stock detail")
        bio=False
        if m_stockfinancial.group(3):
            ticker = m_stockfinancial.group(3).upper()
            if m_stockfinancial.group(4):
                bio=True
        elif m_stockfinancial.group(1):
            ticker = m_stockfinancial.group(1).upper()
            if m_stockfinancial.group(2):
                bio=True
        payload = prepare_stockfinancial_payload(service, user, ticker, bio)
        if service == 'slack':
            url = 'https://slack.com/api/chat.postMessage'
        elif service == 'telegram':
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
        webhook.payload_wrapper(service, url, payload, chat_id)

def doDelta(inputList):
    deltaString = ''
    deltaList = [j-i for i,j in zip(inputList, inputList[1:])]
    #deltaList = [y-x for (x,y) in pairwise(inputList)] # python 3.10
    for delta in deltaList:
        if delta < 0:
            deltaString = deltaString + '🔻'
        elif delta > 0:
            deltaString = deltaString + '🔼'
        else:
            deltaString = deltaString + '▪️'
    return deltaString

def prepare_watchlist(service, user, action=False, ticker=False):
    if ticker:
        ticker_link = util.yahoo_link(ticker, service)
        ticker_orig = ticker.upper()
        ticker = ticker.upper()
    duplicate = False
    transformed = False
    tickers.update(util.watchlist_load())
    print(watchlist)
    if action == 'add':
        if ticker in watchlist:
            duplicate = True
        else:
            watchlist.append(ticker)
    market_data = yahoo.fetch(watchlist)
    print("")
    if action == 'delete':
        if ticker in watchlist:
            watchlist.remove(ticker)
        else:
            print(ticker, "not in watchlist")
    if action == 'add':
        if '.' not in ticker and ticker not in market_data:
            watchlist.remove(ticker)
            ticker = ticker + '.AX'
            transformed = True
            ticker_link = util.yahoo_link(ticker, service)
            print(ticker_orig, "not found. Trying", ticker)
            if ticker in watchlist:
                print(ticker, "already in watchlist")
                duplicate = True
            else:
                watchlist.append(ticker)
                market_data = yahoo.fetch(watchlist)
                print("")
                if ticker in market_data:
                    print("found", ticker)
                else:
                    watchlist.remove(ticker)
                    print(ticker, "not found")
        elif ticker not in market_data:
            watchlist.remove(ticker)
    print(watchlist)
    payload = []
    for item in market_data:
        item_link = util.yahoo_link(item, service)
        profile_title = market_data[item]['profile_title']
        if item == ticker and action == 'delete':
            pass
        elif item == ticker and action == 'add': # make the requested item bold
            text = webhook.bold(f"{profile_title} ({item_link})", service)
            payload.append(text)
        else:
            payload.append(f"{profile_title} ({item_link})")
    def profile_title(e): # disregards markup in sort command
        return re.findall('[A-Z].*', e)
    payload.sort(key=profile_title)
    if action == 'delete':
        if ticker not in market_data:
            payload.insert(0, f"Beep Boop. I could not find " + webhook.bold(ticker, service) + " to remove it")
        else:
            payload.insert(0, f"Ok {user}, I deleted " + webhook.bold(ticker_link, service))
    elif action == 'add':
        if ticker not in market_data:
            payload = [f"Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " to add it"]
        elif transformed and duplicate:
            payload.insert(0, f"Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " and I'm already tracking " + webhook.bold(ticker_link, service))
        elif transformed:
            payload.insert(0, f"Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " so I added " + webhook.bold(ticker_link, service))
        elif duplicate:
            payload.insert(0, f"{user}, I'm already tracking " + webhook.bold(ticker_link, service))
        else:
            payload.insert(0, f"Ok {user}, I added " + webhook.bold(ticker_link, service))
    elif action == False:
        payload.insert(0, f"Hi {user}, I'm currently tracking:")
    with open(cache_file, "w") as f:
        f.write(json.dumps(watchlist))
    return payload

def prepare_help(service, user, botName):
    payload = []
    payload.append(webhook.bold("Examples:", service))
    payload.append("!AAPL")
    payload.append("!AAPL bio")
    payload.append("!holdings")
    payload.append("!premarket [percent]")
    payload.append("!shorts [percent]")
    payload.append("!trades [days]")
    payload.append("!watchlist")
    payload.append("!watchlist [add|del] AAPL")
    if service == 'slack':
        payload.append('<' + botName + '> AAPL')
        payload.append('<' + botName + '> AAPL bio')
    else:
        payload.append(botName + ' AAPL')
        payload.append(botName + ' AAPL bio')
    payload.append("etc.")
    return payload

def prepare_stockfinancial_payload(service, user, ticker, bio):
    cashflow = False
    ticker_orig = ticker
    tickerNative = ticker.split('.')[0]
    now = int(time.time())
    payload = []
    market_data = yahoo.fetch_detail(ticker, 600)
    print("")
    if not market_data and '.' not in ticker:
        ticker = ticker + '.AX'
        print("trying again with", ticker)
        market_data = yahoo.fetch_detail(ticker, 600)
        print("")
    if not market_data:
        payload = [ f"{user} 🛑 Beep Boop. I could not find {ticker_orig}" ]
        return payload
    if debug:
        print("Yahoo data:", json.dumps(market_data, indent=4))
    yahoo_link = util.yahoo_link(ticker, service)
    profile_title = market_data[ticker]['profile_title']
    if 'marketState' in market_data[ticker]:
        marketState = market_data[ticker]['marketState'].rstrip()
        if marketState == 'REGULAR':
            marketStateEmoji = '🟢'
        elif marketState in {'PRE', 'POST'}:
            marketStateEmoji = '🟠'
        else:
            marketStateEmoji = '🔴'
    if 'profile_exchange' in market_data[ticker]:
        profile_exchange = market_data[ticker]['profile_exchange']
        swsURL = 'https://www.google.com/search?q=site:simplywall.st+(' + profile_title + '+' + profile_exchange + ':' + ticker.split('.')[0] + ')+Stock+Price+Quote+Analysis&btnI'
        swsLink = util.link(ticker, swsURL, 'Simply Wall St', service)
        if profile_exchange == 'ASX':
            market_url = 'https://www2.asx.com.au/markets/company/' + ticker.split('.')[0]
            shortman_url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0].lower()
            shortman_link = util.link(ticker, shortman_url, 'ShortMan', service)
        elif profile_exchange == 'HKSE':
            market_url = 'https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=' + ticker.split('.')[0] + '&sc_lang=en'
        elif 'Nasdaq' in profile_exchange:
            market_url = 'https://www.nasdaq.com/market-activity/stocks/' + ticker.lower()
        elif profile_exchange == 'NYSE':
            market_url = 'https://www.nyse.com/quote/XNYS:' + ticker
        elif profile_exchange == 'Taiwan':
            profile_exchange = 'TWSE'
            market_url = 'https://mis.twse.com.tw/stock/fibest.jsp?stock=' + ticker.split('.')[0] + '&lang=en_us'
        elif profile_exchange == 'Tokyo':
            profile_exchange = 'JPX'
            market_url = 'https://quote.jpx.co.jp/jpx/template/quote.cgi?F=tmp/e_stock_detail&MKTN=T&QCODE=' + ticker.split('.')[0]
        else:
            market_url = 'https://www.google.com/search?q=stock+exchange+' + profile_exchange + '+' + ticker.split('.')[0] + '&btnI'
        market_link = util.link(ticker, market_url, profile_exchange, service)
    if bio:
        location = []
        if 'profile_city' in market_data[ticker]:
            location.append(market_data[ticker]['profile_city'])
        if 'profile_state' in market_data[ticker]:
            location.append(market_data[ticker]['profile_state'])
        if 'profile_country' in market_data[ticker]:
            profile_country = market_data[ticker]['profile_country']
            location.append(profile_country)
        if 'profile_bio' in market_data[ticker]:
            payload.append(f"{market_data[ticker]['profile_bio']}")

        if len(payload):
            payload.append("")

        if location:
            payload.append(webhook.bold("Location:", service) + " " + ', '.join(location))
        if 'profile_industry' in market_data[ticker] and 'profile_sector' in market_data[ticker]:
            payload.append(webhook.bold("Classification:", service) + f" {market_data[ticker]['profile_industry']}, {market_data[ticker]['profile_sector']}")
        if 'profile_employees' in market_data[ticker]:
            payload.append(webhook.bold("Employees:", service) + f" {market_data[ticker]['profile_employees']:,}")
        if 'profile_website' in market_data[ticker]:
            payload.append(webhook.bold("Website:", service) + f" {market_data[ticker]['profile_website']}")
        if 'profile_website' in market_data[ticker]:
            if profile_exchange == 'NYSE' or 'Nasdaq' in profile_exchange:
                finvizURL='https://finviz.com/quote.ashx?t=' + ticker
                marketwatchURL = 'https://www.marketwatch.com/investing/stock/' + ticker.lower()
                seekingalphaURL='https://seekingalpha.com/symbol/' + ticker
                finvizLink = util.link(ticker, finvizURL, 'Finviz', service)
                marketwatchLink = util.link(ticker, marketwatchURL, 'MarketWatch', service)
                seekingalphaLink = util.link(ticker, seekingalphaURL, 'Seeking Alpha', service)
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {finvizLink} | {seekingalphaLink} | {marketwatchLink} | {swsLink}")
            elif profile_exchange == 'ASX':
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {shortman_link} | {swsLink}")
            else:
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {swsLink}")
        if ticker_orig == ticker:
            payload.insert(0, webhook.bold(f"{profile_title} ({yahoo_link})", service))
        else:
            payload.insert(0, f"Beep Boop. I could not find " + ticker_orig + ", but I found " + yahoo_link)
            payload.insert(1, "")
            payload.insert(2, webhook.bold(f"{profile_title} ({yahoo_link})", service))
        if len(payload) < 2:
            payload.append("no data found")
        payload = [i[0] for i in groupby(payload)] # de-dupe white space
        return payload
    if 'currency' in market_data[ticker] and 'market_cap' in market_data[ticker]:
        currency = market_data[ticker]['currency']
        market_cap = market_data[ticker]['market_cap']
        market_cap = util.humanUnits(market_cap)
        payload.append(webhook.bold("Mkt cap:", service) + f" {currency} {market_cap}")
    if 'free_cashflow' in market_data[ticker]:
        cashflow = market_data[ticker]['free_cashflow']
    elif 'operating_cashflow' in market_data[ticker]:
        cashflow = market_data[ticker]['operating_cashflow']
    if 'shareholder_equity' in market_data[ticker] and 'total_debt' in market_data[ticker]:
        total_debt = market_data[ticker]['total_debt']
        shareholder_equity = market_data[ticker]['shareholder_equity']
        debt_equity_ratio = round(total_debt / shareholder_equity * 100)
        profile_industry = market_data[ticker]['profile_industry']
        if 'total_cash' in market_data[ticker]:
            total_cash = market_data[ticker]['total_cash']
            if 'Bank' not in profile_industry:
                emoji = ''
                net_debt_equity_ratio = round(((total_debt - total_cash) / shareholder_equity * 100))
                if net_debt_equity_ratio > 40:
                    emoji = '⚠️ '
                if net_debt_equity_ratio > 0:
                    payload.append(webhook.bold("Net debt/equity ratio:", service) + f" {net_debt_equity_ratio}%{emoji}")
    if 'earnings_date' in market_data[ticker]:
        earnings_date = market_data[ticker]['earnings_date']
        human_earnings_date = time.strftime('%b %d', time.localtime(earnings_date))
        if earnings_date > now:
            payload.append(webhook.bold("Earnings date:", service) + f" {human_earnings_date}")
        else:
            print("Skipping past earnings:", ticker, human_earnings_date)
    if 'dividend' in market_data[ticker]:
        dividend = market_data[ticker]['dividend']
        if market_data[ticker]['dividend'] > 0:
            dividend = str(market_data[ticker]['dividend']) + '%'
            payload.append(webhook.bold("Dividend:", service) + f" {dividend}")
            if 'ex_dividend_date' in market_data[ticker]:
                ex_dividend_date = market_data[ticker]['ex_dividend_date']
                human_exdate = time.strftime('%b %d', time.localtime(ex_dividend_date))
                if ex_dividend_date > now:
                    payload.append(webhook.bold("Ex-dividend date:", service) + f" {human_exdate}")
                else:
                    print("Skipping past ex-dividend:", ticker, human_exdate)
    if cashflow:
        if cashflow < 0:
            payload.append(webhook.bold("Cashflow positive:", service) + " no⚠️ ")
        else:
            payload.append(webhook.bold("Cashflow positive:", service) + " yes")
    if 'net_income' in market_data[ticker]:
        if market_data[ticker]['net_income'] < 0:
            payload.append(webhook.bold("Profitable:", service) + " no ⚠️ ")
        else:
            payload.append(webhook.bold("Profitable:", service) + " yes")

    if len(payload):
        payload.append("")

    if 'earningsQ' in market_data[ticker]:
        revenueQs = doDelta(market_data[ticker]['earningsQ'])
        earningsQs = doDelta(market_data[ticker]['revenueQ'])
        revenueYs = doDelta(market_data[ticker]['revenueY'])
        earningsYs = doDelta(market_data[ticker]['earningsY'])
        payload.append(f"{revenueQs}  quarterly revenue")
        payload.append(f"{earningsQs}  quarterly earnings")
        payload.append(f"{revenueYs}  yearly revenue")
        payload.append(f"{earningsYs}  yearly earnings")

    if len(payload):
        payload.append("")

    if 'revenueEstimateY' in market_data[ticker]:
        revenueEstimateY = int(round(market_data[ticker]['revenueEstimateY']))
        earningsEstimateY = int(round(market_data[ticker]['earningsEstimateY']))
        revenueAnalysts = market_data[ticker]['revenueAnalysts']
        earningsAnalysts = market_data[ticker]['earningsAnalysts']
        payload.append(webhook.bold("Revenue growth forecast (1Y):", service) + f" {revenueEstimateY}%")
        payload.append(webhook.bold("Earnings growth forecast (1Y):", service) + f" {earningsEstimateY}%")
    if 'insiderBuy' in market_data[ticker]:
        emoji=''
        insiderBuy = market_data[ticker]['insiderBuy']
        insiderSell = market_data[ticker]['insiderSell']
        insiderBuyValue = market_data[ticker]['insiderBuyValue']
        insiderSellValue = market_data[ticker]['insiderSellValue']
        if insiderBuy > insiderSell:
            action = 'Buy'
            humanValue = util.humanUnits(insiderBuyValue)
            payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue}{emoji}")
        elif insiderBuy < insiderSell:
            emoji = '⚠️ '
            action = 'Sell'
            humanValue = util.humanUnits(insiderSellValue)
            payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue}{emoji}")
    if 'short_percent' in market_data[ticker]:
        emoji=''
        short_percent = market_data[ticker]['short_percent']
        if short_percent > 10:
            emoji = '⚠️ '
        payload.append(webhook.bold("Shorted stock:", service) + f" {short_percent}%{emoji}")
    if 'recommend' in market_data[ticker]:
        recommend = market_data[ticker]['recommend']
        recommend_index = market_data[ticker]['recommend_index']
        recommend_analysts = market_data[ticker]['recommend_analysts']
        payload.append(webhook.bold("Score:", service) + f" {recommend_index} {recommend} ({recommend_analysts} analysts)")

    if len(payload):
        payload.append("")

    if 'price_to_earnings_trailing' in market_data[ticker]:
        trailingPe = str(int(round(market_data[ticker]['price_to_earnings_trailing'])))
        payload.append(webhook.bold("Trailing P/E:", service) + f" {trailingPe}")
    if 'price_to_earnings_forward' in market_data[ticker]:
        forwardPe = int(round(market_data[ticker]['price_to_earnings_forward']))
        emoji=''
        if 'Software' in market_data[ticker]['profile_industry'] and forwardPe > 100:
            emoji = '⚠️ '
        elif 'Software' not in market_data[ticker]['profile_industry'] and forwardPe > 30:
            emoji = '⚠️ '
        payload.append(webhook.bold("Forward P/E:", service) + f" {str(forwardPe)}{emoji}")
    if 'price_to_earnings_peg' in market_data[ticker]:
        peg = round(market_data[ticker]['price_to_earnings_peg'], 1)
        payload.append(webhook.bold("PEG ratio:", service) + f" {str(peg)}")
    if 'price_to_sales' in market_data[ticker]:
        price_to_sales = round(market_data[ticker]['price_to_sales'], 1)
        payload.append(webhook.bold("PS ratio:", service) + f" {str(price_to_sales)}")

    if len(payload):
        payload.append("")

    if 'percent_change_year' in market_data[ticker]:
        percent_change_year = str(market_data[ticker]['percent_change_year']) + '%'
        percent_change = str(market_data[ticker]['percent_change']) + '%'
        payload.append(webhook.bold("1Y:", service) + f" {percent_change_year}")
        payload.append(webhook.bold("1D:", service) + f" {percent_change}")
    if 'percent_change_premarket' in market_data[ticker]:
        percent_change_premarket = str(market_data[ticker]['percent_change_premarket']) + '%'
        payload.append(webhook.bold("Pre-market:", service) + f" {percent_change_premarket}")
    elif 'percent_change_postmarket' in market_data[ticker]:
        percent_change_postmarket = str(market_data[ticker]['percent_change_postmarket']) + '%'
        payload.append(webhook.bold("Post-market:", service) + f" {percent_change_postmarket}")
    if ticker_orig == ticker:
        payload.insert(0, f"{profile_title} ({yahoo_link}) {marketStateEmoji}")
    else:
        payload.insert(0, f"I could not find {ticker_orig} but I found {yahoo_link}:")
        payload.insert(1, "")
        payload.insert(2, f"{profile_title} ({yahoo_link}) {marketStateEmoji}")
    payload = [i[0] for i in groupby(payload)] # de-dupe white space
    if len(payload) < 2:
        payload.append("no data found")
    return payload


ip="127.0.0.1"
port=5000
server = pywsgi.WSGIServer((ip, port), main)
print(f'Listening on http://{ip}:{port}')
# to start the server asynchronously, call server.start()
# we use blocking serve_forever() here because we have no other jobs
server.serve_forever()
