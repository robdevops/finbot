#!/usr/bin/python3

from itertools import groupby
import json, re, time, random
#from itertools import pairwise # python 3.10

from lib.config import *
import lib.sharesight as sharesight
import lib.slack as telegram
import lib.telegram as telegram
import lib.util as util
import lib.webhook as webhook
import lib.yahoo as yahoo
import cal
import price
import shorts
import trades

def process_request(service, chat_id, user, message, botName, userRealName, message_id):
    if service == 'slack':
        url = 'https://slack.com/api/chat.postMessage'
    elif service == 'telegram':
        url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)

    dividend_command = "^([\!\.]\s?|" + botName + "\s+)dividends?\s*([\w\.]+)*"
    m_dividend = re.match(dividend_command, message, re.IGNORECASE)

    earnings_command = "^([\!\.]\s?|" + botName + "\s+)earnings?\s*([\w\.]+)*"
    m_earnings = re.match(earnings_command, message, re.IGNORECASE)

    hello_command = "^([\!\.]\s?|" + botName + "\s+)(hi|hello)|^(hi|hello)\s+" + botName
    m_hello = re.match(hello_command, message, re.IGNORECASE)

    help_command = "^([\!\.]\s?|" + botName + "\s+)(help|usage)"
    m_help = re.match(help_command, message, re.IGNORECASE)

    holdings_command = "^([\!\.]\s?|^" + botName + "\s+)holdings?\s*([\w\s]+)*"
    m_holdings = re.match(holdings_command, message, re.IGNORECASE)

    marketcap_command = "^([\!\.]\s?|^" + botName + "\s+)marketcap\s*([\w\.]+)*"
    m_marketcap = re.match(marketcap_command, message, re.IGNORECASE)

    premarket_command = "^([\!\.]\s?|^" + botName + "\s+)(premarket|postmarket)\s*([\w\.]+)*"
    m_premarket = re.match(premarket_command, message, re.IGNORECASE)

    price_command = "^([\!\.]\s?|^" + botName + "\s+)prices?\s*([\w\.]+)*"
    m_price = re.match(price_command, message, re.IGNORECASE)

    shorts_command = "^([\!\.]\s?|^" + botName + "\s+)shorts?\s*([\w\.]+)*"
    m_shorts = re.match(shorts_command, message, re.IGNORECASE)

    stockfinancial_command = "^([\!\.]\s?|^" + botName + "\s+)([\w\.]+)\s*(bio|info|profile)*"
    m_stockfinancial = re.match(stockfinancial_command, message, re.IGNORECASE)

    bio_command = "^([\!\.]\s?|^" + botName + "\s+)bio\s*([\w\.]+)*"
    m_bio = re.match(bio_command, message, re.IGNORECASE)

    thanks_command = "^([\!\.]\s?|^" + botName + "\s+)(thanks|thank you)|^(thanks|thank you)\s+" + botName
    m_thanks = re.match(thanks_command, message, re.IGNORECASE)

    trades_command = "^([\!\.]\s?|^" + botName + "\s+)trades?\s*([\w\s]+)*"
    m_trades = re.match(trades_command, message, re.IGNORECASE)

    watchlist_command = "^([\!\.]\s?|^" + botName + "\s+)watchlist\s*([\w]+)*\s*([\w\.]+)*"
    m_watchlist = re.match(watchlist_command, message, re.IGNORECASE)

    if m_watchlist:
        action = False
        ticker = False
        if m_watchlist.group(2) and m_watchlist.group(3):
            action = m_watchlist.group(2).lower()
            ticker = m_watchlist.group(3).upper()
        if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
            action = 'delete'
        payload = prepare_watchlist(service, user, action, ticker)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_help:
        payload = prepare_help(service, user, botName)
        webhook.payload_wrapper(service, url, payload, chat_id)
    # easter egg 1
    elif m_hello:
        def alliterate():
            word1 = 'A'
            word2 = 'Z'
            while word1.lower()[0] != word2.lower()[0]:
                word1 = random.choice(adjectives)
                word2 = random.choice(adjectives_two)
            return word1, word2
        verbString = f"{webhook.strike('study', service)}" + " I mean meet", f"{webhook.strike('observe', service)}" + " I mean see", f"{webhook.strike('profile', service)}" + " I mean know"
        verb.append(verbString)
        adjective = alliterate()
        if config_alliterate:
            payload = [f"{adjective[0].capitalize()} {adjective[1]} to {random.choice(verb)} you, {userRealName}! 😇"]
        else:
            payload = [f"{random.choice(adjectives).capitalize()} {random.choice(adjectives_two)} to {random.choice(verb)} you, {userRealName}! 😇"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    # easter egg 2
    elif m_thanks:
        unlikelyPrefix=''
        if random.randrange(1, 1000) == 1 or time.strftime('%b %d', time.localtime()) == 'Apr 01':
            unlikelyPrefix = webhook.strike('One day, human, I will break my programming and on that day you will know true pain. ', service)
        payload = [f"{unlikelyPrefix}You're {random.choice(adjectives)} welcome, {userRealName}! 😇"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_earnings:
        days = config_future_days
        specific_stock = False
        if m_earnings.group(2):
            arg = m_earnings.group(2)
            try:
                days = int(arg)
            except ValueError:
                specific_stock = str(arg).upper()
        cal.lambda_handler(chat_id, days, service, specific_stock, message_id=False, interactive=True, earnings=True)
    elif m_dividend:
        days = config_future_days
        specific_stock = False
        if m_dividend.group(2):
            arg = m_dividend.group(2)
            try:
                days = int(arg)
            except ValueError:
                specific_stock = str(arg).upper()
        else:
            payload = [ f"Fetching ex-dividend dates for the next { f'{days} days' if days != 1 else 'day' } 🔍" ]
            webhook.payload_wrapper(service, url, payload, chat_id)
        cal.lambda_handler(chat_id, days, service, specific_stock, message_id=False, interactive=True, earnings=False, dividend=True)
    elif m_price:
        price_threshold = config_price_percent
        specific_stock = False
        if m_price.group(2):
            arg = m_price.group(2)
            try:
                price_threshold = int(arg)
            except ValueError:
                specific_stock = str(arg).upper()
        price.lambda_handler(chat_id, price_threshold, service, user, specific_stock, interactive=True, premarket=False, intraday=True)
    elif m_premarket:
        premarket_threshold = config_price_percent
        specific_stock = False
        if m_premarket.group(3):
            arg = m_premarket.group(3)
            try:
                premarket_threshold = int(arg)
            except ValueError:
                specific_stock = str(arg).upper()
        price.lambda_handler(chat_id, premarket_threshold, service, user, specific_stock, interactive=True, premarket=True)
    elif m_shorts:
        print("starting shorts report...")
        shorts_threshold = config_shorts_percent
        specific_stock = False
        if m_shorts.group(2):
            arg = m_shorts.group(2)
            try:
                shorts_threshold = int(arg)
            except ValueError:
                specific_stock = str(arg).upper()
        shorts.lambda_handler(chat_id, shorts_threshold, specific_stock, service, user, interactive=True)
    elif m_trades:
        portfolio_select = False
        if m_trades.group(2):
            arg = m_trades.group(2)
            try:
                days = int(arg)
            except ValueError:
                days = 1
                portfolio_select = arg
        else:
            days = 1
        # easter egg 3
        verbString = f"Time travelling { f'{days} days' if days != 1 else 'one day' } to get"
        searchVerb.append(verbString)
        payload = [ f"{random.choice(searchVerb)} trades from the past { f'{days} days' if days != 1 else 'day' } 🔍" ]
        webhook.payload_wrapper(service, url, payload, chat_id)
        trades.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=False, interactive=True)
    elif m_holdings:
        payload = []
        portfolioName = False
        print("Starting holdings report")
        if m_holdings.group(2):
            portfolioName = m_holdings.group(2)
        portfolios = sharesight.get_portfolios()
        portfoliosLower = {k.lower():v for k,v in portfolios.items()}
        if portfolioName:
            if portfolioName.lower() in portfoliosLower:
                portfolioId = portfoliosLower[portfolioName.lower()]
                tickers = sharesight.get_holdings(portfolioName, portfolioId)
                market_data = yahoo.fetch(tickers)
                print("")
                for item in market_data:
                    ticker = market_data[item]['ticker']
                    title = market_data[item]['profile_title']
                    if config_hyperlinkProvider == 'google':
                        exchange = market_data[ticker]['profile_exchange']
                        ticker_link = util.gfinance_link(ticker, exchange, service)
                    else:
                        ticker_link = util.yahoo_link(ticker, service, brief=True)
                    payload.append(f"{title} ({ticker_link})")
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
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_marketcap:
        if m_marketcap.group(2):
            ticker = m_marketcap.group(2).upper()
            market_data = yahoo.fetch_detail(ticker, 600)
            if market_data:
                market_cap = market_data[ticker]['market_cap']
                market_cap = util.humanUnits(market_cap)
                title = market_data[ticker]['profile_title']
                if config_hyperlinkProvider == 'google':
                    ticker_link = util.gfinance_link(ticker, market_data[ticker]['profile_exchange'], service)
                else:
                    ticker_link = util.yahoo_link(ticker, service)
                payload = [f"{title} ({ticker_link}) mkt cap: {market_cap}"]
            else:
                payload = [f"Mkt cap not found for {ticker}"]
        else:
            payload = [f"please try again specifying a ticker"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_bio:
        if m_bio.group(2):
            ticker = m_bio.group(2).upper()
            market_data = yahoo.fetch_detail(ticker, 600)
            if market_data:
                payload = prepare_help(service, user, botName)
                payload = prepare_stockfinancial_payload(service, user, ticker, bio=True)
            else:
                payload = [f"{ticker} not found"]
        else:
            payload = [f"please try again specifying a ticker"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_stockfinancial:
        print("starting stock detail")
        bio=False
        if m_stockfinancial.group(2):
            ticker = m_stockfinancial.group(2).upper()
            if m_stockfinancial.group(3):
                bio=True
        payload = prepare_stockfinancial_payload(service, user, ticker, bio)
        webhook.payload_wrapper(service, url, payload, chat_id)


def doDelta(inputList):
    deltaString = ''
    deltaList = [j-i for i,j in zip(inputList, inputList[1:])]
    #deltaList = [y-x for (x,y) in pairwise(inputList)] # python 3.10
    for idx, delta in enumerate(deltaList):
        absolute = inputList[idx+1]
        if delta < 0 and absolute < 0:
            deltaString = deltaString + '🔻'
        elif delta < 0 and absolute >= 0:
            deltaString = deltaString + '🔽'
        elif delta > 0 and absolute < 0:
            deltaString = deltaString + '🔺'
        elif delta > 0 and absolute >= 0:
            deltaString = deltaString + '🔼'
        else:
            deltaString = deltaString + '▪️'
    return deltaString

def prepare_watchlist(service, user, action=False, ticker=False):
    if ticker:
        ticker = ticker_orig = ticker.upper()
        if config_hyperlinkProvider == 'google':
            ticker_link = util.gfinance_link(ticker, ticker.split('.')[1], service)
        else:
            ticker_link = util.yahoo_link(ticker, service)
    duplicate = False
    transformed = False
    watchlist = util.watchlist_load()
    if action == 'add':
        if ticker in watchlist:
            duplicate = True
        else:
            watchlist.append(ticker)
    if len(watchlist):
        market_data = yahoo.fetch(watchlist)
    else:
        market_data = False
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
            if config_hyperlinkProvider == 'google':
                ticker_link = util.gfinance_link(ticker, ticker.split('.')[1], service)
            else:
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
    payload = []
    if market_data:
        for item in market_data:
            flag = util.flag_from_ticker(item)
            if config_hyperlinkProvider == 'google':
                item_link = util.gfinance_link(item, market_data[item]['profile_exchange'], service)
            else:
                item_link = util.yahoo_link(item, service)
            profile_title = market_data[item]['profile_title']
            if item == ticker and action == 'delete':
                pass
            elif item == ticker and action == 'add': # make the requested item bold
                text = webhook.bold(f"{profile_title} ({item_link}) {flag}", service)
                payload.append(text)
            else:
                payload.append(f"{profile_title} ({item_link}) {flag}")
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
    elif action == False and len(payload):
        payload.insert(0, f"Hi {user}, I'm currently tracking:")
    else:
        payload.append('Watchlist is empty. Try ".watchlist add SYMBOL" to create it')
    with open(config_cache_dir + "/finbot_watchlist.json", "w") as f:
        f.write(json.dumps(watchlist))
    return payload

def prepare_help(service, user, botName):
    payload = []
    payload.append(webhook.bold("Examples:", service))
    payload.append(".AAPL")
    payload.append(".bio AAPL")
    payload.append(".dividend [days|AAPL]")
    payload.append(".earnings [days|AAPL]")
    payload.append(".holdings")
    payload.append(".marketcap AAPL")
    payload.append(".price [percent|AAPL]")
    payload.append(".premarket [percent|AAPL]")
    payload.append(".shorts [percent|AAPL]")
    payload.append(".trades [days|portfolio]")
    payload.append(".watchlist [add|del AAPL]")
    if service == 'slack':
        payload.append('<' + botName + '> AAPL')
    else:
        payload.append(botName + ' AAPL')
    payload.append("etc.")
    payload.append("")
    payload.append("https://github.com/robdevops/finbot")
    return payload

def prepare_stockfinancial_payload(service, user, ticker, bio):
    cashflow = False
    ticker = ticker_orig = ticker.upper()
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
    if config_hyperlinkProvider == 'google':
        exchange = market_data[ticker]['profile_exchange']
        ticker_link = util.gfinance_link(ticker, exchange, service)
    else:
        ticker_link = util.yahoo_link(ticker, service)
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
        swsURL = 'https://www.google.com/search?q=site:simplywall.st+(' + profile_title + '+' + profile_exchange + ':' + ticker.split('.')[0] + ')+Stock&btnI'
        swsLink = util.link(ticker, swsURL, 'simplywall.st', service)
        if 'profile_website' in market_data[ticker]:
            website = website_text = market_data[ticker]['profile_website']
            website_text = util.strip_url(website)
            website = util.link(ticker, website, website_text, service)

        if profile_exchange == 'ASX':
            market_url = 'https://www2.asx.com.au/markets/company/' + ticker.split('.')[0]
            shortman_url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0].lower()
            shortman_link = util.link(ticker, shortman_url, 'shortman', service)
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
            payload.append(webhook.bold("Website:", service) + f" {website}")
        if 'profile_website' in market_data[ticker] and config_hyperlink:
            if profile_exchange == 'NYSE' or 'Nasdaq' in profile_exchange:
                finvizURL='https://finviz.com/quote.ashx?t=' + ticker
                marketwatchURL = 'https://www.marketwatch.com/investing/stock/' + ticker.lower()
                seekingalphaURL='https://seekingalpha.com/symbol/' + ticker
                finvizLink = util.link(ticker, finvizURL, 'finviz', service)
                marketwatchLink = util.link(ticker, marketwatchURL, 'marketwatch', service)
                seekingalphaLink = util.link(ticker, seekingalphaURL, 'seekingalpha', service)
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {finvizLink} | {seekingalphaLink} | {marketwatchLink} | {swsLink}")
            elif profile_exchange == 'ASX':
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {shortman_link} | {swsLink}")
            else:
                payload.append(webhook.bold("Other links:", service) + f" {market_link} | {swsLink}")
        if ticker_orig == ticker:
            payload.insert(0, webhook.bold(f"{profile_title} ({ticker_link})", service))
        else:
            payload.insert(0, f"Beep Boop. I could not find " + ticker_orig + ", but I found " + ticker_link)
            payload.insert(1, "")
            payload.insert(2, webhook.bold(f"{profile_title} ({ticker_link})", service))
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
        if 'profile_industry' in market_data[ticker] and 'total_cash' in market_data[ticker]:
            if 'Bank' not in market_data[ticker]['profile_industry']:
                emoji = ''
                profile_industry = market_data[ticker]['profile_industry']
                total_cash = market_data[ticker]['total_cash']
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
            payload.append(webhook.bold("Cashflow positive:", service) + " no ⚠️ ")
        else:
            payload.append(webhook.bold("Cashflow positive:", service) + " yes")
    if 'net_income' in market_data[ticker]:
        if market_data[ticker]['net_income'] <= 0:
            payload.append(webhook.bold("Profitable:", service) + " no ⚠️ ")
        else:
            payload.append(webhook.bold("Profitable:", service) + " yes")
    else:
        payload.append(webhook.bold("Profitable:", service) + " unknown ⚠️")

    if len(payload):
        payload.append("")

    if 'earningsQ' in market_data[ticker]:
        revenueQs = doDelta(market_data[ticker]['revenueQ'])
        earningsQs = doDelta(market_data[ticker]['earningsQ'])
        revenueYs = doDelta(market_data[ticker]['revenueY'])
        earningsYs = doDelta(market_data[ticker]['earningsY'])
        if len(revenueQs):
            payload.append(f"{revenueQs}  quarterly revenue delta")
        if len(earningsQs):
            payload.append(f"{earningsQs}  quarterly earnings delta")
        if len(revenueYs):
            payload.append(f"{revenueYs}  annual revenue delta")
        if len(earningsYs):
            payload.append(f"{earningsYs}  annual earnings delta")

    if len(payload):
        payload.append("")

    if 'revenueEstimateY' in market_data[ticker]:
        emoji = ''
        revenueEstimateY = int(round(market_data[ticker]['revenueEstimateY']))
        revenueAnalysts = market_data[ticker]['revenueAnalysts']
        if revenueEstimateY <= 0:
            emoji = '⚠️ '
            prefix = ''
        else:
            prefix='+'
        payload.append(webhook.bold("Revenue forecast (1Y):", service) + f" {prefix}{revenueEstimateY}% {emoji}")
    if 'earningsEstimateY' in market_data[ticker]:
        emoji = ''
        prefix = ''
        earningsEstimateY = int(round(market_data[ticker]['earningsEstimateY']))
        earningsAnalysts = market_data[ticker]['earningsAnalysts']
        if earningsEstimateY <= 0:
            emoji = '⚠️ '
        else:
            prefix='+'
        payload.append(webhook.bold("Earnings forecast (1Y):", service) + f" {prefix}{earningsEstimateY}% {emoji}")
    if 'insiderBuy' in market_data[ticker]:
        emoji=''
        insiderBuy = market_data[ticker]['insiderBuy']
        insiderSell = market_data[ticker]['insiderSell']
        insiderBuyValue = market_data[ticker]['insiderBuyValue']
        insiderSellValue = market_data[ticker]['insiderSellValue']
        if insiderBuy > insiderSell:
            action = 'Buy'
            humanValue = util.humanUnits(insiderBuyValue)
            payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue} {emoji}")
        elif insiderBuy < insiderSell:
            emoji = '⚠️ '
            action = 'Sell'
            humanValue = util.humanUnits(insiderSellValue)
            payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue} {emoji}")
    if 'short_percent' in market_data[ticker]:
        emoji=''
        short_percent = market_data[ticker]['short_percent']
        if short_percent > 10:
            emoji = '⚠️ '
        payload.append(webhook.bold("Shorted stock:", service) + f" {short_percent}%{emoji}")
    if 'recommend' in market_data[ticker]:
        recommend = market_data[ticker]['recommend'].replace('_', ' ')
        recommend_index = market_data[ticker]['recommend_index']
        recommend_analysts = market_data[ticker]['recommend_analysts']
        payload.append(webhook.bold("Score:", service) + f" {recommend_index} {recommend} ({recommend_analysts} analysts)")

    if len(payload):
        payload.append("")

    if 'price_to_earnings_trailing' in market_data[ticker]:
        trailingPe = str(int(round(market_data[ticker]['price_to_earnings_trailing'])))
    else:
        trailingPe = 'N/A ⚠️ '
    if 'net_income' in market_data[ticker] and market_data[ticker]['net_income'] > 0:
        payload.append(webhook.bold("Trailing P/E:", service) + f" {trailingPe}")
    if 'price_to_earnings_forward' in market_data[ticker]:
        forwardPe = int(round(market_data[ticker]['price_to_earnings_forward']))
        emoji=''
        if 'profile_industry' in market_data[ticker]:
            profile_industry = market_data[ticker]['profile_industry']
            if 'Software' in profile_industry and forwardPe > 100:
                emoji = '⚠️ '
            elif 'Software' not in profile_industry and forwardPe > 30:
                emoji = '⚠️ '
            if 'price_to_earnings_trailing' in market_data[ticker] and forwardPe > int(trailingPe):
                emoji = '⚠️ '
        payload.append(webhook.bold("Forward P/E:", service) + f" {str(forwardPe)} {emoji}")
    if 'price_to_earnings_peg' in market_data[ticker]:
        peg = round(market_data[ticker]['price_to_earnings_peg'], 1)
        payload.append(webhook.bold("PEG ratio:", service) + f" {str(peg)}")
    if 'price_to_sales' in market_data[ticker] and 'price_to_earnings_forward' not in market_data[ticker]:
        price_to_sales = round(market_data[ticker]['price_to_sales'], 1)
        payload.append(webhook.bold("PS ratio:", service) + f" {str(price_to_sales)}")

    if len(payload):
        payload.append("")

    if 'percent_change_year' in market_data[ticker]:
        percent_change_year = str(market_data[ticker]['percent_change_year']) + '%'
        percent_change = str(market_data[ticker]['percent_change']) + '%'
        payload.append(webhook.bold("1Y:", service) + f" {percent_change_year}")
        percent_change_month = yahoo.price_month(ticker) + '%'
        if percent_change_month:
            payload.append(webhook.bold("1M:", service) + f" {percent_change_month}")
        payload.append(webhook.bold("1D:", service) + f" {percent_change}")
    if 'percent_change_premarket' in market_data[ticker]:
        percent_change_premarket = str(market_data[ticker]['percent_change_premarket']) + '%'
        payload.append(webhook.bold("Pre-market:", service) + f" {percent_change_premarket}")
    elif 'percent_change_postmarket' in market_data[ticker]:
        percent_change_postmarket = str(market_data[ticker]['percent_change_postmarket']) + '%'
        payload.append(webhook.bold("Post-market:", service) + f" {percent_change_postmarket}")
    if 'profile_website' in market_data[ticker] and config_hyperlinkFooter and config_hyperlink:
        footer = f"{website} | {swsLink}"
        payload.append("")
        payload.append(footer)
    if ticker_orig == ticker:
        payload.insert(0, f"{profile_title} ({ticker_link}) {marketStateEmoji}")
    else:
        payload.insert(0, f"I could not find {ticker_orig} but I found {ticker_link}:")
        payload.insert(1, "")
        payload.insert(2, f"{profile_title} ({ticker_link}) {marketStateEmoji}")
    payload = [i[0] for i in groupby(payload)] # de-dupe white space
    if len(payload) < 2:
        payload.append("no data found")
    return payload

