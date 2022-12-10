# Import the necessary modules
from wsgiref.simple_server import make_server
from gevent import pywsgi
from html import escape
import numpy
#from itertools import pairwise # python 3.10

import json, re, time
from lib.config import *
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo
import lib.telegram as telegram

def main(env, start_response):
    user=''
    request_body = env['wsgi.input'].read()
    inbound = json.loads(request_body)
    
    # Set the response status code and headers
    status = '200 OK'
    headers = [('Content-type', 'application/json')]
    start_response(status, headers)
    
    # Return the response body
    try:
        print("Incoming request:", json.dumps(inbound, indent=4))
    except Exception as e:
        print(e, "raw body: ", inbound)

    # read telegram message
    if "message" in inbound:
        if "text" in inbound["message"]:
            message = inbound["message"]["text"]
            chat_id = inbound["message"]["chat"]
            chat_id = str(chat_id["id"])
            if "username" in inbound["message"]["from"]:
                user = inbound["message"]["from"]["username"]
            else:
                user = inbound["message"]["from"]["first_name"]
        else:
            print("unhandled 'message' without 'text'")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [b'<h1>Unhandled</h1>']
    elif "channel_post" in inbound:
        message = inbound["channel_post"]["text"]
        chat_id = inbound["channel_post"]["chat"]["id"]
        user = ''
    else:
        print("unhandled not 'message' nor 'channel_post'")
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [b'<h1>Unhandled</h1>']

    # read bot command
    stockfinancial_command = "^\!([\w\.]+)\s*(bio|info|profile)*|^@{} ([\w\.]+)".format(config_telegram_botname)
    bio_command = "^\!(desc|descr|describe|info|detail|bio|profile) ([\w\W\.]+)|^@{} info ([\w\W\.+]+)".format(config_telegram_botname)
    watchlist_command = "^\!watchlist$|^\!watchlist ([\w]+) ([\w\.]+)|^@{} watchlist (\w+)\s+([\w\.]+)".format(config_telegram_botname)
    m_stockfinancial = re.match(stockfinancial_command, message)
    m_watchlist = re.match(watchlist_command, message)
    m_bio = re.match(bio_command, message)
    if m_watchlist:
        action = False
        ticker = False
        if m_watchlist.group(1) and m_watchlist.group(2):
            action = m_watchlist.group(1)
            ticker = m_watchlist.group(2)
        for service in webhooks:
            payload = prepare_watchlist("telegram", user, action, ticker)
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
            webhook.payload_wrapper("telegram", url, payload)
            return [b"<b>OK</b>"]
    elif message in ("!help", "!usage", config_telegram_botname + " help", config_telegram_botname + " usage"):
        for service in webhooks:
            payload = prepare_help("telegram", user)
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
            webhook.payload_wrapper("telegram", url, payload)
            return [b"<b>OK</b>"]
    elif message in ("!todo", "!roadmap", config_telegram_botname + " todo", config_telegram_botname + " roadmap"):
        for service in webhooks:
            payload = prepare_todo("telegram", user)
            url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
            webhook.payload_wrapper("telegram", url, payload)
            return [b"<b>OK</b>"]
    elif m_stockfinancial:
        if m_stockfinancial.group(1):
            print("starting stock detail")
            bio=False
            ticker = m_stockfinancial.group(1).upper()
            if m_stockfinancial.group(2):
                bio=True
            for service in webhooks:
                payload = prepare_stockfinancial_payload("telegram", user, ticker, bio)
                url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)
                webhook.payload_wrapper("telegram", url, payload)
                return [b"<b>OK</b>"]
    else:
        print(message, "is not a bot command")
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [b"<b>OK</b>"]

def doDelta(inputList):
    deltaString = ''
    #deltaList = [j-i for i,j in zip(inputList, inputList[1:])]
    #deltaList = [t[i+1]-t[i] for i in range(len(inputList)-1)]
    #deltaList = [y-x for (x, y) in pairwise(inputList)]
    deltaList = numpy.diff(inputList)
    for delta in deltaList:
        if delta < 0:
            deltaString = deltaString + '🔻'
        elif delta > 0:
            deltaString = deltaString + '🔼'
        else:
            deltaString = deltaString + '▪️'
    return deltaString

def prepare_watchlist(service, user, action, ticker):
    duplicate = False
    missing = False
    transformed = False
    tickerau = False
    ticker_orig = ticker
    cache_file = config_cache_dir + "/sharesight_watchlist.txt"
    if os.path.isfile(cache_file):
        with open(cache_file, "r") as f:
            watchlist = json.loads(f.read())
    else:
        watchlist = list(config_watchlist)
    print(watchlist)
    if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
        if ticker in watchlist:
            watchlist.remove(ticker)
        else:
            print(ticker, "not in watchlist")
            missing = True
    elif action == 'add':
        if ticker in watchlist:
            duplicate = True
        else:
            watchlist.append(ticker)
    market_data = yahoo.fetch(watchlist)
    if action == 'add':
        if '.' not in ticker and ticker not in market_data:
            tickerau = ticker + '.AX'
            print(ticker, "not found. Trying", tickerau)
            watchlist.remove(ticker)
            if tickerau in watchlist:
                print(tickerau, "already in watchlist")
                duplicate = True
            else:
                watchlist.append(tickerau)
                transformed = True
                market_data = yahoo.fetch(watchlist)
                if tickerau in market_data:
                    print("found", tickerau)
                    ticker = tickerau
                else:
                    print(tickerau, "not found")
                    watchlist.remove(tickerau)
                    missing = True
        elif ticker not in market_data:
            watchlist.remove(ticker)
            missing = True
    print(watchlist)
    yahoo_url = "https://au.finance.yahoo.com/quote/"
    payload = []
    for item in market_data:
        profile_title = market_data[item]['profile_title']
        if service == 'telegram':
            holding_link = '<a href="' + yahoo_url + item + '">' + item + '</a>'
        elif service in {'discord', 'slack'}:
            holding_link = '<' + yahoo_url + item + '|' + item + '>'
        else:
            holding_link = item
        # make the requested item bold
        if action == 'add' and ticker == item:
            payload.append(f"<b>{profile_title} ({holding_link})</b>")
        elif action == 'add' and tickerau == item:
            payload.append(f"<b>{profile_title} ({holding_link})</b>")
        else:
            payload.append(f"{profile_title} ({holding_link})")
    def profile_title(e): # disregards the <b> in sort command
        return re.findall('[A-Z].*', e)
    payload.sort(key=profile_title)
    if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
        if missing:
            payload.insert(0, f"Beep Boop. I could not find <b>{ticker}</b> to remove it")
        else:
            payload.insert(0, f"Ok @{user}, I deleted <b>{ticker}</b>")
    elif action == 'add':
        if tickerau and duplicate:
            payload.insert(0, f"Beep Boop. I could not find <b>{ticker}</b> and I'm already tracking {tickerau}")
        elif transformed:
            payload.insert(0, f"Beep Boop. I could not find {ticker_orig} so I added <b>{tickerau}</b>")
        elif duplicate:
            payload.insert(0, f"@{user}, I'm already tracking <b>{ticker}</b>")
        elif ticker not in market_data:
            payload = [f"@{user}"]
            payload.append(f"Beep Boop. I could not find <b>{ticker}</b> to add it")
        else:
            payload.insert(0, f"Ok @{user}, I added <b>{ticker}</b>")
    elif action == False:
        payload.insert(0, f"Hi @{user}, I'm currently tracking:")
    with open(cache_file, "w") as f:
        f.write(json.dumps(watchlist))
    print(json.dumps(payload))
    return payload

def prepare_help(service, user):
    payload = []
    payload.append("<b>Examples:</b>")
    payload.append("!AAPL")
    payload.append("!AAPL bio")
    payload.append("!watchlist")
    payload.append("!watchlist add GOOGL")
    payload.append("!watchlist del GOOGL")
    return payload

def prepare_todo(service, user):
    lessthan = escape("<")
    greaterthan = escape(">")
    payload = []
    payload.append(f"<b>!holdings {lessthan}portfolio name{greaterthan}</b> (not implemented)")
    payload.append("<b>!trades [days]</b> (not implemented)")
    payload.append("<b>!premarket [percent]</b> (not implemented)")
    payload.append("<b>!shorts [percent]</b> (not implemented)")
    payload.sort()
    return payload

def prepare_stockfinancial_payload(service, user, ticker, bio):
    cashflow = False
    ticker_orig = ticker
    now = int(time.time())
    payload = []
    market_data = yahoo.fetch_detail(ticker)
    if not market_data and '.' not in ticker:
        ticker = ticker + '.AX'
        print("trying again with", ticker)
        market_data = yahoo.fetch_detail(ticker)
    if not market_data:
        payload = [ f"Beep Boop. I could not find {ticker_orig}" ]
        payload.insert(0, f"@{user}")
        return payload
    print("Yahoo data:", json.dumps(market_data, indent=4))
    yahoo_url = "https://finance.yahoo.com/quote/" + ticker
    ticker_link = '<a href="' + yahoo_url + '">' + ticker + '</a>'
    profile_title = market_data[ticker]['profile_title']
    if bio:
        city = market_data[ticker]['profile_city']
        country = market_data[ticker]['profile_country']
        state = ''
        if 'profile_state' in market_data[ticker]:
            state = market_data[ticker]['profile_state']
        payload.append(f"{market_data[ticker]['profile_bio']}")
        payload.append("")
        payload.append(f"<b>Location:</b> {city}, {state}, {country}")
        payload.append(f"<b>Classification:</b> {market_data[ticker]['profile_industry']}, {market_data[ticker]['profile_sector']}")
        if 'profile_employees' in market_data[ticker]:
            payload.append(f"<b>Employees:</b> {market_data[ticker]['profile_employees']:,}")
        if 'profile_website' in market_data[ticker]:
            payload.append(f"<b>Website:</b> {market_data[ticker]['profile_website']}")
        if ticker_orig == ticker:
            payload.insert(0, profile_title + " (" + ticker_link + ")")
        else:
            payload.insert(0, f"Beep Boop. I could not find " + ticker_orig + ", but I found " + ticker_link)
        return payload
    currency = market_data[ticker]['currency']
    market_cap = market_data[ticker]['market_cap']
    payload.append(f"<b>Mkt cap:</b> {currency} {market_cap:,}")
    if 'free_cashflow' in market_data[ticker]:
        cashflow = market_data[ticker]['free_cashflow']
    elif 'operating_cashflow' in market_data[ticker]:
        cashflow = market_data[ticker]['operating_cashflow']
    if 'shareholder_equity' in market_data[ticker] and 'total_debt' in market_data[ticker]:
        total_debt = market_data[ticker]['total_debt']
        shareholder_equity = market_data[ticker]['shareholder_equity']
        debt_equity_ratio = round(total_debt / shareholder_equity * 100)
        profile_industry = market_data[ticker]['profile_industry']
        emoji = ''
        # debt
        if 'Bank' not in profile_industry:
            if debt_equity_ratio > 100:
                emoji = '⚠️ '
            payload.append(f"<b>Debt/Equity Ratio:</b> {debt_equity_ratio}%{emoji}")
            if 'total_cash' in market_data[ticker]:
                emoji=''
                total_cash = market_data[ticker]['total_cash']
                net_debt_equity_ratio = round(((total_debt - total_cash) / shareholder_equity * 100))
                if net_debt_equity_ratio > 40:
                    emoji = '⚠️ '
                payload.append(f"<b>Net Debt/Equity Ratio:</b> {net_debt_equity_ratio}%{emoji}")
    if cashflow:
        if cashflow < 0:
            payload.append(f"<b>Cashflow positive:</b> no⚠️ ")
        else:
            payload.append(f"<b>Cashflow positive:</b> yes")
    if 'net_income' in market_data[ticker]:
        if market_data[ticker]['net_income'] < 0:
            payload.append(f"<b>Profitable:</b> no ⚠️ ")
        else:
            payload.append(f"<b>Profitable:</b> yes")

    if 'earningsQ' in market_data[ticker]:
        revenueQs = doDelta(market_data[ticker]['earningsQ'])
        earningsQs = doDelta(market_data[ticker]['revenueQ'])
        revenueYs = doDelta(market_data[ticker]['revenueY'])
        earningsYs = doDelta(market_data[ticker]['earningsY'])
        payload.append("")
        payload.append(f"{revenueQs} quarterly revenue")
        payload.append(f"{earningsQs} quarterly earnings")
        payload.append(f"{revenueYs} yearly revenue")
        payload.append(f"{earningsYs} yearly earnings")
        payload.append("")
    if 'earnings_date' in market_data[ticker]:
        earnings_date = market_data[ticker]['earnings_date']
        human_earnings_date = time.strftime('%b %d', time.localtime(earnings_date))
        if earnings_date > now:
            payload.append(f"<b>Earnings date:</b> {human_earnings_date}")
        else:
            print("Skipping past earnings:", human_earnings_date)
    if 'dividend' in market_data[ticker]:
        dividend = market_data[ticker]['dividend']
        if market_data[ticker]['dividend'] > 0:
            dividend = str(market_data[ticker]['dividend']) + '%'
            payload.append(f"<b>Dividend:</b> {dividend}")
            if 'ex_dividend_date' in market_data[ticker]:
                ex_dividend_date = market_data[ticker]['ex_dividend_date']
                human_exdate = time.strftime('%b %d', time.localtime(ex_dividend_date))
                if ex_dividend_date > now:
                    payload.append(f"<b>Ex-dividend date:</b> {human_exdate}")
                else:
                    print("Skipping past ex-dividend:", human_exdate)
    if 'price_to_earnings_trailing' in market_data[ticker]:
        payload.append(f"<b>Trailing P/E:</b> {market_data[ticker]['price_to_earnings_trailing']}")
    if 'price_to_earnings_forward' in market_data[ticker]:
        emoji=''
        if 'Software' in market_data[ticker]['profile_industry'] and market_data[ticker]['price_to_earnings_forward'] > 100:
            emoji = '⚠️ '
        elif 'Software' not in market_data[ticker]['profile_industry'] and market_data[ticker]['price_to_earnings_forward'] > 30:
            emoji = '⚠️ '
        payload.append(f"<b>Forward P/E:</b> {market_data[ticker]['price_to_earnings_forward']}{emoji}")
    if 'price_to_earnings_peg' in market_data[ticker]:
        payload.append(f"<b>PEG ratio:</b> {market_data[ticker]['price_to_earnings_peg']}")
    if 'short_percent' in market_data[ticker]:
        emoji=''
        short_percent = market_data[ticker]['short_percent']
        if short_percent > 10:
            emoji = '⚠️ '
        payload.append(f"<b>Percent shorted:</b> {short_percent}%{emoji}")
    if 'earnings_growth_forecast' in market_data[ticker]:
        payload.append(f"<b>Revenue growth forecast:</b> {market_data[ticker]['revenue_growth_forecast']}%")
        payload.append(f"<b>Earnings growth forecast:</b> {market_data[ticker]['earnings_growth_forecast']}%")
    if 'recommend' in market_data[ticker]:
        recommend = market_data[ticker]['recommend']
        recommend_index = market_data[ticker]['recommend_index']
        recommend_analysts = market_data[ticker]['recommend_analysts']
        payload.append(f"<b>Score:</b> {recommend_index}: {recommend} ({recommend_analysts} analysts)")
    if 'percent_change_year' in market_data[ticker]:
        percent_change_year = str(market_data[ticker]['percent_change_year']) + '%'
        payload.append("")
        payload.append(f"<b>1Y:</b> {percent_change_year}")
        payload.append(f"<b>1D:</b> {market_data[ticker]['percent_change']}%")
    if 'percent_change_premarket' in market_data[ticker]:
        percent_change_premarket = str(market_data[ticker]['percent_change_premarket']) + '%'
        payload.append(f"<b>Pre-market:</b> {percent_change_premarket}")
    if 'percent_change_postmarket' in market_data[ticker]:
        percent_change_postmarket = str(market_data[ticker]['percent_change_postmarket']) + '%'
        payload.append(f"<b>Post-market:</b> {percent_change_postmarket}")
    if ticker_orig == ticker:
        payload.insert(0, profile_title + " (" + ticker_link + ")")
    else:
        payload.insert(0, f"Beep Boop. I could not find " + ticker_orig + ", but I found " + ticker_link)
        payload.insert(0, f"@{user}")
    return payload

ip="127.0.0.1"
port=5000
print(f'Serving on https://{ip}:{port}')
server = pywsgi.WSGIServer((ip, port), main)
# to start the server asynchronously, call server.start()
# we use blocking serve_forever() here because we have no other jobs
server.serve_forever()
