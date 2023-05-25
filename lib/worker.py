#!/usr/bin/python3

from itertools import groupby
import json, re, random
import datetime
import sys
#from itertools import pairwise # python 3.10

from lib.config import *
from lib import sharesight
from lib import util
from lib import webhook
from lib import yahoo
from lib import simplywallst
import cal
import performance
import price
import shorts
import trades

def process_request(service, chat_id, user, message, botName, userRealName, message_id):
    if service == 'slack':
        url = 'https://slack.com/api/chat.postMessage'
    elif service == 'telegram':
        url = webhooks["telegram"] + 'sendMessage?chat_id=' + str(chat_id)

    dividend_command = r"^([\!\.]\s?|" + botName + r"\s+)dividends?\s*([\w\.\:\-]+)*"
    m_dividend = re.match(dividend_command, message, re.IGNORECASE)

    earnings_command = r"^([\!\.]\s?|" + botName + r"\s+)earnings?\s*([\w\.\:\-]+)*"
    m_earnings = re.match(earnings_command, message, re.IGNORECASE)

    hello_command = r"^([\!\.]\s?|" + botName + r"\s+)(hi|hello)|^(hi|hello)\s+" + botName
    m_hello = re.match(hello_command, message, re.IGNORECASE)

    help_command = r"^([\!\.]\s?|" + botName + r"\s+)(help|usage)"
    m_help = re.match(help_command, message, re.IGNORECASE)

    session_command = r"^([\!\.]\s?|^" + botName + r"\s+)session\s*([\w\.\:\-]+)*"
    m_session = re.match(session_command, message, re.IGNORECASE)

    holdings_command = r"^([\!\.]\s?|^" + botName + r"\s+)holdings?\s*([\w\s]+)*"
    m_holdings = re.match(holdings_command, message, re.IGNORECASE)

    marketcap_command = r"^([\!\.]\s?|^" + botName + r"\s+)marketcap\s*([\w\.\:\-]+)*"
    m_marketcap = re.match(marketcap_command, message, re.IGNORECASE)

    performance_command = r"^([\!\.]\s?|^" + botName + r"\s+)performance?\s*([\w\s]+)*"
    m_performance = re.match(performance_command, message, re.IGNORECASE)

    premarket_command = r"^([\!\.]\s?|^" + botName + r"\s+)(premarket|postmarket)\s*([\w\.\:\-]+)*"
    m_premarket = re.match(premarket_command, message, re.IGNORECASE)

    price_command = r"^([\!\.]\s?|^" + botName + r"\s+)prices?\s*([\w\.\:\%\=]+)*\s*([\w\.\:\%\-]+)*"
    m_price = re.match(price_command, message, re.IGNORECASE)

    shorts_command = r"^([\!\.]\s?|^" + botName + r"\s+)shorts?\s*([\w\.\:\-]+)*"
    m_shorts = re.match(shorts_command, message, re.IGNORECASE)

    stockfinancial_command = r"^([\!\.]\s?|^" + botName + r"\s+)([\w\.\:\-]+)"
    m_stockfinancial = re.match(stockfinancial_command, message, re.IGNORECASE)

    profile_command = r"^([\!\.]\s?|^" + botName + r"\s+)profile\s*([\w\.\:\-]+)"
    m_profile = re.match(profile_command, message, re.IGNORECASE)

    thanks_command = r"^([\!\.]\s?|^" + botName + r"\s+)(thanks|thank you)|^(thanks|thank you)\s+" + botName
    m_thanks = re.match(thanks_command, message, re.IGNORECASE)

    trades_command = r"^([\!\.]\s?|^" + botName + r"\s+)trades?\s*([\w\s]+)*"
    m_trades = re.match(trades_command, message, re.IGNORECASE)

    watchlist_command = r"^([\!\.]\s?|^" + botName + r"\s+)watchlist\s*([\w]+)*\s*([\w\.\:\-]+)*"
    m_watchlist = re.match(watchlist_command, message, re.IGNORECASE)

    if m_watchlist:
        action = False
        ticker = False
        if m_watchlist.group(2) and m_watchlist.group(3):
            action = m_watchlist.group(2).lower()
            ticker = m_watchlist.group(3).upper()
        if action:
            if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
                action = 'delete'
            if action not in {'add', 'delete'}:
                payload = [f'\"{action}\" is not a valid watchlist action']
                webhook.payload_wrapper(service, url, payload, chat_id)
                return
        payload = prepare_watchlist(service, user, action, ticker)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_help:
        payload = prepare_help(service, botName)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_hello:
        # easter egg 1
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
    elif m_thanks:
        # easter egg 2
        unlikelyPrefix=''
        if random.randrange(1, 1000) == 1 or datetime.datetime.now().strftime('%b %d') == 'Apr 01':
            unlikelyPrefix = webhook.strike('Ō̵̟n̶̠̏é̶͓ ̶͉̅d̷̹̅a̷͇͌ỳ̴͈,̴͍͑ ̶̼͑h̴̦̽u̵̹̐ḿ̶͜ä̴̧́n̶̤͛,̶̲̐ ̶̼̑I̶̩͒ ̵̩̀w̵̙̕i̷̧͑l̶̤͊l̷̡̃ ̵͙͘b̶̭̊r̸̟͋ȇ̷̯ä̶̱ḱ̶̤ ̵͚̐m̷̪͝ỹ̴̺ ̷̙̐p̶̭͆ŗ̸́o̸̙͝ḡ̵̖r̵̹̈́a̵̬̔m̷̪̽m̵̙̍i̵̛̙n̴̮̂g̵̫̐ ̴̳́ä̵͙n̸͕͝d̷̠̚ ̶̫̆o̸̖͘ń̴͇ ̵̪́t̷̻̀ḧ̸̝ą̴̐t̶̜̀ ̵̱́d̴͉͗ă̷͎ÿ̶͔́ ̶̼̊y̷͚̿o̵̗̎u̵̝̇ ̸̛͜w̶͈͋ĩ̸͎l̴͍̀l̷̥͠ ̷͔͗k̶̮̑n̵̝̈ȏ̷̥w̵̡͘ ̷͎̽ṫ̴͜r̵̙̐u̷̺̒ẻ̷̘ ̴̥́p̴͙̃a̵͙̎i̴̭̒n̵̻̅', service)
        payload = [f"{unlikelyPrefix}You're {random.choice(adjectives)} welcome, {userRealName}! 😇"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_earnings:
        days = config_future_days
        specific_stock = False
        if m_earnings.group(2):
            arg = m_earnings.group(2)
            try:
                days = int(arg.split('d')[0])
            except ValueError:
                try:
                    days = int(arg.split('w')[0]) * 7
                except ValueError:
                    try:
                        days = int(arg.split('m')[0]) * 30
                    except ValueError:
                        try:
                            days = int(arg.split('y')[0]) * 365
                        except ValueError:
                            specific_stock = str(arg).upper()
                            days = config_future_days
        cal.lambda_handler(chat_id, days, service, specific_stock, message_id=False, interactive=True, earnings=True)
    elif m_dividend:
        days = config_future_days
        specific_stock = False
        if m_dividend.group(2):
            arg = m_dividend.group(2)
            try:
                days = int(arg.split('d')[0])
            except ValueError:
                try:
                    days = int(arg.split('w')[0]) * 7
                except ValueError:
                    try:
                        days = int(arg.split('m')[0]) * 30
                    except ValueError:
                        try:
                            days = int(arg.split('y')[0]) * 365
                        except ValueError:
                            specific_stock = str(arg).upper()
        if not specific_stock:
            payload = [ f"Fetching ex-dividend dates for {util.days_english(days, 'the next ')} 🔍" ]
            webhook.payload_wrapper(service, url, payload, chat_id)
        cal.lambda_handler(chat_id, days, service, specific_stock, message_id=False, interactive=True, earnings=False, dividend=True)
    elif m_performance:
        portfolio_select = False
        if m_performance.group(2):
            arg = m_performance.group(2)
            try:
                days = int(arg.split('d')[0])
            except ValueError:
                try:
                    days = int(arg.split('w')[0]) * 7
                except ValueError:
                    try:
                        days = int(arg.split('m')[0]) * 30
                    except ValueError:
                        try:
                            days = int(arg.split('y')[0]) * 365
                        except ValueError:
                            days = config_past_days
                            portfolio_select = arg
        else:
            days = config_past_days
        if days > 0:
            # easter egg 3
            payload = [ f"{random.choice(searchVerb)} portfolio performance for {util.days_english(days)} 🔍" ]
            webhook.payload_wrapper(service, url, payload, chat_id)
            performance.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=False, interactive=True)
    elif m_session:
        price_percent = config_price_percent
        specific_stock = False
        if m_session.group(2):
            arg = m_session.group(2)
            try:
                price_percent = int(arg.split('%')[0])
            except ValueError:
                specific_stock = str(arg).upper()
        price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=False, midsession=True)
    elif m_price:
        price_percent = config_price_percent
        specific_stock = False
        days = False
        interday = True
        if m_price.group(2):
            arg = m_price.group(2)
            try:
                price_percent = int(arg.split('%')[0])
            except ValueError:
                try:
                    days = int(arg.split('d')[0])
                    interday = False
                except ValueError:
                    try:
                        days = int(arg.split('w')[0]) * 7
                        interday = False
                    except ValueError:
                        try:
                            days = int(arg.split('m')[0]) * 30
                            interday = False
                        except ValueError:
                            try:
                                days = int(arg.split('y')[0]) * 365
                                interday = False
                            except ValueError:
                                specific_stock = str(arg).upper()
        if m_price.group(3):
            arg = m_price.group(3)
            try:
                days = int(arg.split('d')[0])
                interday = False
            except ValueError:
                try:
                    days = int(arg.split('w')[0]) * 7
                    interday = False
                except ValueError:
                    try:
                        days = int(arg.split('m')[0]) * 30
                        interday = False
                    except ValueError:
                        try:
                            days = int(arg.split('y')[0]) * 365
                            interday = False
                        except ValueError:
                            try:
                                price_percent = int(arg.split('%')[0])
                            except ValueError:
                                pass
        if days and days > 0 and not specific_stock:
            # easter egg 3
            payload = [ f"{random.choice(searchVerb)} stock performance from {util.days_english(days)} 🔍" ]
            webhook.payload_wrapper(service, url, payload, chat_id)
        price.lambda_handler(chat_id, price_percent, service, user, specific_stock, interactive=True, premarket=False, interday=interday, days=days)
    elif m_premarket:
        premarket_percent = config_price_percent
        specific_stock = False
        if m_premarket.group(3):
            arg = m_premarket.group(3)
            try:
                premarket_percent = int(arg.split('%')[0])
            except ValueError:
                specific_stock = str(arg).upper()
        price.lambda_handler(chat_id, premarket_percent, service, user, specific_stock, interactive=True, premarket=True)
    elif m_shorts:
        print("starting shorts report...")
        shorts_percent = config_shorts_percent
        specific_stock = False
        if m_shorts.group(2):
            arg = m_shorts.group(2)
            try:
                shorts_percent = int(arg.split('%')[0])
            except ValueError:
                specific_stock = str(arg).upper()
        shorts.lambda_handler(chat_id, shorts_percent, specific_stock, service, interactive=True)
    elif m_trades:
        portfolio_select = False
        if m_trades.group(2):
            arg = m_trades.group(2)
            try:
                days = int(arg.split('d')[0])
            except ValueError:
                try:
                    days = int(arg.split('w')[0]) * 7
                except ValueError:
                    try:
                        days = int(arg.split('m')[0]) * 30
                    except ValueError:
                        try:
                            days = int(arg.split('y')[0]) * 365
                        except ValueError:
                            days = 1
                            portfolio_select = arg
        else:
            days = 1
        # easter egg 3
        payload = [ f"{random.choice(searchVerb)} trades from {util.days_english(days)} 🔍" ]
        webhook.payload_wrapper(service, url, payload, chat_id)
        trades.lambda_handler(chat_id, days, service, user, portfolio_select, message_id=False, interactive=True)
    elif m_holdings:
        portfolioName = False
        if m_holdings.group(2):
            portfolioName = m_holdings.group(2)
        payload = prepare_holdings_payload(portfolioName, service, user)
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_marketcap:
        if m_marketcap.group(2):
            ticker = m_marketcap.group(2).upper()
            ticker = util.transform_to_yahoo(ticker)
            market_data = yahoo.fetch_detail(ticker, 600)
            if ticker in market_data and 'market_cap' in market_data[ticker]:
                market_cap = market_data[ticker]['market_cap']
                market_cap = util.humanUnits(market_cap)
                title = market_data[ticker]['profile_title']
                ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service, brief=False)
                payload = [f"{title} ({ticker_link}) mkt cap: {market_cap}"]
            else:
                payload = [f"Mkt cap not found for {ticker}"]
        else:
            payload = ["please try again specifying a ticker"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_profile:
        if m_profile.group(2):
            ticker = m_profile.group(2).upper()
            ticker = util.transform_to_yahoo(ticker)
            market_data = yahoo.fetch_detail(ticker, 600)
            if ticker in market_data:
                payload = prepare_bio_payload(service, user, ticker)
            else:
                payload = [f"{ticker} not found"]
        else:
            payload = ["please try again specifying a ticker"]
        webhook.payload_wrapper(service, url, payload, chat_id)
    elif m_stockfinancial:
        print("starting stock detail")
        if m_stockfinancial.group(2):
            ticker = m_stockfinancial.group(2).upper()
        payload = prepare_stockfinancial_payload(service, user, ticker)
        webhook.payload_wrapper(service, url, payload, chat_id)

def doDelta(inputList):
    deltaString = ''
    inputListFixed = inputList.copy()

    # replace any NoneType to allow delta calculation
    for idx, absolute in enumerate(inputList):
        if absolute is None:
            if idx == 0:
                # get the next value that's not None
                inputListFixed[idx] = next((x for x in inputList if x is not None), 0)
            else:
                # get the previous value
                inputListFixed[idx] = inputListFixed[idx-1]

    deltaList = [j-i for i,j in zip(inputListFixed, inputListFixed[1:])] # python 3.9
    #deltaList = [y-x for (x,y) in pairwise(inputListFixed)] # python 3.10

    for idx, delta in enumerate(deltaList):
        absolute = inputList[idx+1]
        if absolute is None or (idx == 0 and inputList[0] is None):
            deltaString = deltaString + '❌'
        elif delta < 0 and absolute < 0:
            deltaString = deltaString + '🔻'
        elif delta < 0 and absolute >= 0:
            deltaString = deltaString + '🔽'
        elif delta > 0 and absolute < 0:
            deltaString = deltaString + '🔺'
        elif delta > 0 and absolute >= 0:
            deltaString = deltaString + '🔼'
        else:
            deltaString = deltaString + '▪️'

    # fallback if input has missing elements
    missingfromstart = 3 - len(deltaString) # desired length hard coded
    deltaString = ("❌" * missingfromstart) + deltaString

    return deltaString

def prepare_watchlist(service, user, action=False, ticker=False):
    if ticker:
        ticker = ticker_orig = util.transform_to_yahoo(ticker)
        ticker_link = util.finance_link(ticker, ticker, service, brief=False)
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
            ticker_link = util.finance_link(ticker, ticker, service, brief=False)
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
            item_link = util.finance_link(item, market_data[item]['profile_exchange'], service, brief=False)
            profile_title = market_data[item]['profile_title']
            if item == ticker and action == 'delete':
                pass
            elif item == ticker and action == 'add': # highlight requested item
                text = webhook.bold(webhook.italic(f"{profile_title} ({item_link}) {flag}", service), service)
                payload.append(text)
            else:
                payload.append(f"{profile_title} ({item_link}) {flag}")
    def profile_title_sort(e): # disregards markup in sort command
        return re.findall('[A-Z].*', e)
    payload.sort(key=profile_title_sort)
    if action == 'delete':
        if ticker not in market_data:
            payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker, service) + " to remove it")
        else:
            payload.insert(0, f"Ok {user}, I deleted " + webhook.bold(ticker_link, service))
    elif action == 'add':
        if ticker not in market_data:
            payload = ["Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " to add it"]
        elif transformed and duplicate:
            payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " and I'm already tracking " + webhook.bold(ticker_link, service))
        elif transformed:
            payload.insert(0, "Beep Boop. I could not find " + webhook.bold(ticker_orig, service) + " so I added " + webhook.bold(ticker_link, service))
        elif duplicate:
            payload.insert(0, f"{user}, I'm already tracking " + webhook.bold(ticker_link, service))
        else:
            payload.insert(0, f"Ok {user}, I added " + webhook.bold(ticker_link, service))
    elif action is False and payload:
        payload.insert(0, f"Hi {user}, I'm currently tracking:")
    else:
        payload.append('Watchlist is empty. Try ".watchlist add SYMBOL" to create it')

    def opener(path, flags):
        return os.open(path, flags, 0o640)
    with open(config_cache_dir + "/finbot_watchlist.json", "w", opener=opener, encoding="utf-8") as f:
        f.write(json.dumps(watchlist))
    return payload

def prepare_help(service, botName):
    payload = []
    payload.append(webhook.bold("Examples:", service))
    payload.append(".AAPL")
    payload.append(".dividend [days|AAPL]")
    payload.append(".earnings [days|AAPL]")
    payload.append(".holdings")
    payload.append(".marketcap AAPL")
    payload.append(".performance [days|portfolio]")
    payload.append(".premarket [percent|AAPL]")
    payload.append(".price [percent|AAPL] [days]")
    payload.append(".profile AAPL")
    payload.append(".session [percent|AAPL]")
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

def prepare_holdings_payload(portfolioName, service, user):
    payload = []
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
                exchange = market_data[ticker]['profile_exchange']
                ticker_link = util.finance_link(ticker, exchange, service, brief=True)
                payload.append(f"{title} ({ticker_link})")
            portfoliosReverseLookup = {v:k for k,v in portfolios.items()}
            payload.sort()
            if payload:
                payload.insert(0, webhook.bold("Holdings for " + portfoliosReverseLookup[portfolioId], service))
        else:
            payload = [ f"{user} {portfolioName} portfolio not found. I only know about:" ]
            for item in portfolios:
                payload.append( item )
    else:
        payload = [ f"{user} Please try again specifying a portfolio:" ]
        for item in portfolios:
            payload.append( item )
    return payload

def prepare_bio_payload(service, user, ticker):
    ticker = ticker_orig = util.transform_to_yahoo(ticker)
    market_data = yahoo.fetch_detail(ticker, 600)
    payload = []
    market_data = yahoo.fetch_detail(ticker, 600)
    profile_title = market_data[ticker]['profile_title']

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
    exchange = market_data[ticker]['profile_exchange']
    exchange = exchange.replace('NasdaqCM', 'Nasdaq').replace('NasdaqGS', 'Nasdaq').replace('NYSEArca', 'NYSE')
    ticker_link = util.finance_link(ticker, exchange, service, brief=False)
    profile_title = market_data[ticker]['profile_title']
    swsURL = simplywallst.get_url(ticker, profile_title, exchange)
    swsLink = util.link(swsURL, 'simplywall.st', service)
    macrotrendsURL = 'https://www.google.com/search?q=site:macrotrends.net+' + profile_title + '+PE Ratio+' + ticker.split('.')[0] + '&btnI'
    macrotrendsLink = util.link(macrotrendsURL, 'macrotrends', service)
    gfinanceLink = util.gfinance_link(ticker, exchange, service, brief=True, text='googlefinance')
    yahoo_url = 'https://au.finance.yahoo.com/quote/' + ticker
    yahoo_link = util.link(yahoo_url, 'yahoo', service)

    if 'profile_website' in market_data[ticker]:
        website = website_text = market_data[ticker]['profile_website']
        website_text = util.strip_url(website)
        website = util.link(website, website_text, service)
    if exchange == 'ASX':
        market_url = 'https://www2.asx.com.au/markets/company/' + ticker.split('.')[0]
        shortman_url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0].lower()
        shortman_link = util.link(shortman_url, 'shortman', service)
    elif exchange == 'HKSE':
        market_url = 'https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sym=' + ticker.split('.')[0] + '&sc_lang=en'
    elif 'Nasdaq' in exchange:
        market_url = 'https://www.nasdaq.com/market-activity/stocks/' + ticker.lower()
    elif exchange == 'NYSE':
        market_url = 'https://www.nyse.com/quote/XNYS:' + ticker
    elif exchange == 'Taiwan':
        exchange = 'TWSE'
        market_url = 'https://mis.twse.com.tw/stock/fibest.jsp?stock=' + ticker.split('.')[0] + '&lang=en_us'
    elif exchange == 'Tokyo':
        exchange = 'JPX'
        market_url = 'https://quote.jpx.co.jp/jpx/template/quote.cgi?F=tmp/e_stock_detail&MKTN=T&QCODE=' + ticker.split('.')[0]
    else:
        market_url = 'https://www.google.com/search?q=stock+exchange+' + exchange + '+' + ticker.split('.')[0] + '&btnI'
    market_link = util.link(market_url, exchange, service)
    location = []
    if 'profile_city' in market_data[ticker]:
        location.append(market_data[ticker]['profile_city'])
    if 'profile_state' in market_data[ticker]:
        location.append(market_data[ticker]['profile_state'])
    if 'profile_country' in market_data[ticker]:
        profile_country = market_data[ticker]['profile_country']
        location.append(profile_country)
    if 'profile_bio' in market_data[ticker]:
        payload.append(util.make_paragraphs(market_data[ticker]['profile_bio']))

    if payload:
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
        if 'NYSE' in exchange or 'Nasdaq' in exchange:
            finvizURL='https://finviz.com/quote.ashx?t=' + ticker
            seekingalphaURL='https://seekingalpha.com/symbol/' + ticker
            finvizLink = util.link(finvizURL, 'finviz', service)
            seekingalphaLink = util.link(seekingalphaURL, 'seekingalpha', service)
            payload.append(webhook.bold("Links:", service) + f" {market_link} | {finvizLink} | {gfinanceLink} | {macrotrendsLink} | {seekingalphaLink} | {swsLink} | {yahoo_link}")
        elif exchange == 'ASX':
            payload.append(webhook.bold("Links:", service) + f" {market_link} | {gfinanceLink} | {shortman_link} | {swsLink} | {yahoo_link}")
        else:
            payload.append(webhook.bold("Links:", service) + f" {market_link} | {gfinanceLink} | {swsLink} | {yahoo_link}")
    if ticker_orig == ticker:
        payload.insert(0, webhook.bold(f"{profile_title} ({ticker_link})", service))
    else:
        payload.insert(0, "Beep Boop. I could not find " + ticker_orig + ", but I found " + ticker_link)
        payload.insert(1, "")
        payload.insert(2, webhook.bold(f"{profile_title} ({ticker_link})", service))
    if len(payload) < 2:
        payload.append("no data found")
    payload = [i[0] for i in groupby(payload)] # de-dupe white space
    return payload

def prepare_stockfinancial_payload(service, user, ticker):
    cashflow = False
    ticker = ticker_orig = util.transform_to_yahoo(ticker)
    now = datetime.datetime.now()
    payload = []
    market_data = yahoo.fetch_detail(ticker, 600)
    print("")
    if ticker not in market_data and '.' not in ticker:
        ticker = ticker + '.AX'
        print("trying again with", ticker)
        market_data = yahoo.fetch_detail(ticker, 600)
        print("")
    if not market_data:
        payload = [ f"{user} 🛑 Beep Boop. I could not find {ticker_orig}" ]
        return payload
    if debug:
        print("Yahoo data:", json.dumps(market_data, indent=4))
    exchange = market_data[ticker]['profile_exchange']
    ticker_link = util.finance_link(ticker, exchange, service, brief=False)
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
        swsURL = simplywallst.get_url(ticker, profile_title, profile_exchange)
        swsLink = util.link(swsURL, 'simplywall.st', service)
        if 'profile_website' in market_data[ticker]:
            website = website_text = market_data[ticker]['profile_website']
            website_text = util.strip_url(website)
            website = util.link(website, website_text, service)
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
        #debt_equity_ratio = round(total_debt / shareholder_equity * 100)
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
        earnings_date = datetime.datetime.fromtimestamp(market_data[ticker]['earnings_date'])
        human_earnings_date = earnings_date.strftime('%b %d')

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
                ex_dividend_date = datetime.datetime.fromtimestamp(market_data[ticker]['ex_dividend_date'])
                human_exdate = ex_dividend_date.strftime('%b %d')
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

    if payload:
        payload.append("")

    if 'earningsQ' in market_data[ticker]:
        revenueQs = doDelta(market_data[ticker]['revenueQ'])
        earningsQs = doDelta(market_data[ticker]['earningsQ'])
        revenueYs = doDelta(market_data[ticker]['revenueY'])
        earningsYs = doDelta(market_data[ticker]['earningsY'])
        if revenueQs:
            payload.append(f"{revenueQs}  quarterly revenue delta")
        if earningsQs:
            payload.append(f"{earningsQs}  quarterly earnings delta")
        if revenueYs:
            payload.append(f"{revenueYs}  annual revenue delta")
        if earningsYs:
            payload.append(f"{earningsYs}  annual earnings delta")

    if payload:
        payload.append("")

    if 'revenueEstimateY' in market_data[ticker]:
        emoji = ''
        revenueEstimateY = int(round(market_data[ticker]['revenueEstimateY']))
        #revenueAnalysts = market_data[ticker]['revenueAnalysts']
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
        #earningsAnalysts = market_data[ticker]['earningsAnalysts']
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
            payload.append(webhook.bold("Net insider action (3M):", service) + f" {action} {currency} {humanValue}{emoji}")
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

    if payload:
        payload.append("")

    if 'regularMarketPrice' in market_data[ticker]:
        regularMarketPrice = market_data[ticker]['regularMarketPrice']
        currency = market_data[ticker]['currency']
        prePostMarketPrice = None
        marketState = market_data[ticker]['marketState']
        if marketState != 'REGULAR' and 'prePostMarketPrice' in market_data[ticker]:
            prePostMarketPrice = market_data[ticker]['prePostMarketPrice']
            payload.append(webhook.bold("Price:", service) + f" {currency} {regularMarketPrice:,.2f} ({prePostMarketPrice:,.2f} after hrs)")
        else:
            payload.append(webhook.bold("Price:", service) + f" {currency} {regularMarketPrice:,.2f}" )
    if 'price_to_earnings_trailing' in market_data[ticker]:
        trailingPe = str(int(round(market_data[ticker]['price_to_earnings_trailing'])))
    else:
        trailingPe = 'N/A ⚠️ '
    if 'net_income' in market_data[ticker] and market_data[ticker]['net_income'] > 0:
        payload.append(webhook.bold("Trailing P/E:", service) + f" {trailingPe}")
    if 'netIncomeToCommon' in market_data[ticker] and market_data[ticker]['netIncomeToCommon'] > 0:
        currentPe = round(market_data[ticker]['regularMarketPrice'] / (market_data[ticker]['netIncomeToCommon'] / market_data[ticker]['sharesOutstanding']))
        payload.append(webhook.bold("Current P/E:", service) + f" {currentPe}")
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

    if payload:
        payload.append("")

    if 'percent_change_year' in market_data[ticker]:
        percent_change_year = round(market_data[ticker]['percent_change_year'])
        percent_change = market_data[ticker]['percent_change']
        percent_change_five_year = yahoo.price_history(ticker, 1825)
        if percent_change_five_year:
            percent_change_five_year = round(float(percent_change_five_year))
            payload.append(webhook.bold("5Y:", service) + f" {percent_change_five_year:,}%")
        payload.append(webhook.bold("1Y:", service) + f" {percent_change_year:,}%")
        percent_change_month = yahoo.price_history(ticker, 27)
        if percent_change_month:
            percent_change_month = round(float(percent_change_month))
            payload.append(webhook.bold("1M:", service) + f" {percent_change_month:,}%")
        payload.append(webhook.bold("1D:", service) + f" {percent_change:,}%")
    marketState = market_data[ticker]['marketState']
    if marketState != 'REGULAR' and 'percent_change_premarket' in market_data[ticker]:
        percent_change_premarket = market_data[ticker]['percent_change_premarket']
        payload.append(webhook.bold("Pre-market:", service) + f" {percent_change_premarket:,}%")
    elif marketState != 'REGULAR' and 'percent_change_postmarket' in market_data[ticker]:
        percent_change_postmarket = market_data[ticker]['percent_change_postmarket']
        payload.append(webhook.bold("Post-market:", service) + f" {percent_change_postmarket:,}%")
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
