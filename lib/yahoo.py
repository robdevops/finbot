#!/usr/bin/python3

import json
import requests
import datetime
import time

from lib.config import *
import lib.util as util

time_now = datetime.datetime.today()
now = time_now.timestamp()

def transform_ticker_wrapper(holdings):
    tickers = set()
    for holding in holdings:
        symbol = holdings[holding]['code']
        market = holdings[holding]['market_code']
        ticker = transform_ticker(symbol, market)
        tickers.add(ticker)
    tickers = list(tickers)
    tickers.sort()
    tickers = set(tickers)
    return tickers
    
def transform_ticker(ticker, market):
    if market == 'ASX':
        ticker = ticker + '.AX'
    if market == 'HKG':
        ticker = ticker + '.HK'
    if market == 'KRX':
        ticker = ticker + '.KS'
    if market == 'KOSDAQ':
        ticker = ticker + '.KQ'
    if market == 'LSE':
        ticker = ticker + '.L'
    if market == 'TAI':
        ticker = ticker + '.TW'
    return ticker

def fetch(tickers):
    # NEVER CACHE THIS
    print("Fetching Yahoo data for " + str(len(tickers)) + " global holdings")
    yahoo_output = {}
    yahoo_urls = ['https://query2.finance.yahoo.com/v7/finance/quote?symbols=' + ','.join(tickers)]
    yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
    headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    for url in yahoo_urls:
        print("Fetching", url)
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
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
        try:
            profile_title = item['longName']
        except (KeyError, IndexError):
            continue
        try:
            percent_change = round(float(item['regularMarketChangePercent']), 2)
        except (KeyError, IndexError):
            pass
        try:
            currency = item['currency']
        except (KeyError, IndexError):
            pass
        try:
            dividend = round(float(item['trailingAnnualDividendRate']), 1)
        except (KeyError, IndexError):
            dividend = float(0)
        profile_title = util.transform_title(profile_title)
        yahoo_output[ticker] = { 'profile_title': profile_title, 'ticker': ticker, 'percent_change': percent_change, 'dividend': dividend, 'currency': currency }
        # optional fields
        try:
            percent_change_premarket = item['preMarketChangePercent']
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["percent_change_premarket"] = round(percent_change_premarket, 2)
        try:
            percent_change_postmarket = item['postMarketChangePercent']
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["percent_change_postmarket"] = round(percent_change_postmarket, 2)
        try:
            market_cap = round(float(item['marketCap']))
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["market_cap"] = market_cap
        try:
            yahoo_output[ticker]["forward_pe"] = round(item['forwardPE'])
        except:
            pass
        try:
            yahoo_output[ticker]["trailing_pe"] = round(item['trailingPE'])
        except:
            pass
        try:
            earningsTimestamp = item['earningsTimestamp']
            earningsTimestampStart = item['earningsTimestampStart']
            earningsTimestampEnd = item['earningsTimestampEnd']
            if earningsTimestamp == earningsTimestampStart == earningsTimestampEnd:
                yahoo_output[ticker]["earnings_date"] = earningsTimestamp
        except (KeyError, IndexError):
            pass
    return yahoo_output

def fetch_detail(ticker, seconds=config_cache_seconds):
    local_market_data = {}
    base_url = 'https://query2.finance.yahoo.com/v11/finance/quoteSummary/'
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    local_market_data[ticker] = {}
    cache_file = config_cache_dir + "/sharesight_detail_cache_" + ticker
    cacheData = util.read_cache(cache_file, seconds)
    if config_cache and cacheData:
        print('.', sep=' ', end='', flush=True)
        data = cacheData
    else:
        print('↓', sep=' ', end='', flush=True)
        yahoo_urls = [base_url + ticker + '?modules=calendarEvents,defaultKeyStatistics,balanceSheetHistoryQuarterly,financialData,summaryProfile,summaryDetail,price,earnings,earningsTrend,insiderTransactions']
        yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
        for url in yahoo_urls:
            try:
                r = requests.get(url, headers=headers, timeout=config_http_timeout)
            except Exception as e:
                print(e)
            else:
                if r.status_code != 200:
                    #print(r.status_code, "error", ticker, url)
                    print('x', sep=' ', end='', flush=True)
                    continue
                break
        else:
            print(ticker + '†', sep=' ', end='', flush=True)
            return False # catches some delisted stocks like "DRNA"
        data = r.json()
        util.write_cache(cache_file, data)
        # might be interesting:
            # majorHoldersBreakdown
            # netSharePurchaseActivity
            # upgradeDowngradeHistory
    try:
        profile_title = data['quoteSummary']['result'][0]['price']['longName']
    except (KeyError, IndexError, ValueError):
        print(ticker + '†', sep=' ', end='', flush=True)
        return False
    else:
        if profile_title is None: # catches some delisted stocks like "DUB"
            print(f"{ticker}†", sep=' ', end='', flush=True)
            return False
        profile_title = util.transform_title(profile_title)
        local_market_data[ticker]['profile_title'] = profile_title
    try:
        profile_bio = data['quoteSummary']['result'][0]['summaryProfile']['longBusinessSummary']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_bio'] = profile_bio
    try:
        profile_city = data['quoteSummary']['result'][0]['summaryProfile']['city']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_city'] = profile_city
    try:
        profile_country = data['quoteSummary']['result'][0]['summaryProfile']['country']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_country'] = profile_country
    try:
        profile_state = data['quoteSummary']['result'][0]['summaryProfile']['state']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_state'] = profile_state
    try:
        profile_industry = data['quoteSummary']['result'][0]['summaryProfile']['industry']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_industry'] = profile_industry
    try:
        profile_sector = data['quoteSummary']['result'][0]['summaryProfile']['sector']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_sector'] = profile_sector
    try:
        profile_employees = data['quoteSummary']['result'][0]['summaryProfile']['fullTimeEmployees']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_employees'] = profile_employees
    try:
        profile_website = data['quoteSummary']['result'][0]['summaryProfile']['website']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_website'] = profile_website
    try:
        currency = data['quoteSummary']['result'][0]['summaryDetail']['currency']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['currency'] = currency
    try:
        market_cap = int(data['quoteSummary']['result'][0]['summaryDetail']['marketCap']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['market_cap'] = market_cap
    try:
        dividend = data['quoteSummary']['result'][0]['summaryDetail']['dividendYield']['raw']
    except (KeyError, IndexError):
        pass
    else:
        dividend = dividend * 100
        local_market_data[ticker]['dividend'] = round(dividend, 1)
    try:
        price_to_earnings_trailing = int(data['quoteSummary']['result'][0]['summaryDetail']['trailingPE']['raw'])
    except (KeyError, IndexError, ValueError):
        pass
    else:
        local_market_data[ticker]['price_to_earnings_trailing'] = price_to_earnings_trailing
    try:
        price_to_earnings_forward = data['quoteSummary']['result'][0]['summaryDetail']['forwardPE']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['price_to_earnings_forward'] = price_to_earnings_forward
    try:
        ex_dividend_date = data['quoteSummary']['result'][0]['calendarEvents']['exDividendDate']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['ex_dividend_date'] = ex_dividend_date
    try:
        dividend_date = data['quoteSummary']['result'][0]['calendarEvents']['DividendDate']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['dividend_date'] = dividend_date
    try:
        earnings_date = data['quoteSummary']['result'][0]['calendarEvents']['earnings']['earningsDate'][0]['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['earnings_date'] = earnings_date
    try:
        percent_change = data['quoteSummary']['result'][0]['price']['regularMarketChangePercent']['raw']
    except (KeyError, IndexError):
        pass
    else:
        percent_change = percent_change * 100
        local_market_data[ticker]['percent_change'] = round(percent_change, 1)
    try:
        percent_change_year = float(data['quoteSummary']['result'][0]['defaultKeyStatistics']['52WeekChange']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        percent_change_year = percent_change_year * 100
        local_market_data[ticker]['percent_change_year'] = round(percent_change_year, 1)
    try:
        percent_change_premarket = float(data['quoteSummary']['result'][0]['price']['preMarketChangePercent']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        percent_change_premarket = percent_change_premarket * 100
        local_market_data[ticker]['percent_change_premarket'] = round(percent_change_premarket, 1)
    try:
        percent_change_postmarket = float(data['quoteSummary']['result'][0]['price']['postMarketChangePercent']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        percent_change_postmarket = percent_change_postmarket * 100
        local_market_data[ticker]['percent_change_postmarket'] = round(percent_change_postmarket, 1)
    try:
        profile_exchange = data['quoteSummary']['result'][0]['price']['exchangeName']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profile_exchange'] = profile_exchange
    try:
        short_percent = float(data['quoteSummary']['result'][0]['defaultKeyStatistics']['shortPercentOfFloat']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        short_percent = short_percent * 100
        local_market_data[ticker]['short_percent'] = round(short_percent, 1)
    try:
        price_to_book = data['quoteSummary']['result'][0]['defaultKeyStatistics']['priceToBook']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['price_to_book'] = price_to_book
    try:
        earnings_growth_q = data['quoteSummary']['result'][0]['defaultKeyStatistics']['earningsQuarterlyGrowth']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['earnings_growth_q'] = earnings_growth_q
    try:
        price_to_earnings_peg = data['quoteSummary']['result'][0]['defaultKeyStatistics']['pegRatio']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['price_to_earnings_peg'] = price_to_earnings_peg
    try:
        profit_margin = data['quoteSummary']['result'][0]['defaultKeyStatistics']['profitMargins']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['profit_margin'] = profit_margin
    try:
        net_income = data['quoteSummary']['result'][0]['defaultKeyStatistics']['netIncomeToCommon']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['net_income'] = net_income
    try:
        shareholder_equity = data['quoteSummary']['result'][0]['balanceSheetHistoryQuarterly']['balanceSheetStatements'][0]['totalStockholderEquity']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['shareholder_equity'] = shareholder_equity
    try:
        total_debt = data['quoteSummary']['result'][0]['financialData']['totalDebt']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['total_debt'] = total_debt
    try:
        total_cash = data['quoteSummary']['result'][0]['financialData']['totalCash']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['total_cash'] = total_cash
    try:
        free_cashflow = data['quoteSummary']['result'][0]['financialData']['freeCashflow']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['free_cashflow'] = free_cashflow
    try:
        operating_cashflow = data['quoteSummary']['result'][0]['financialData']['operatingCashflow']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['operating_cashflow'] = operating_cashflow
    try:
        recommend = data['quoteSummary']['result'][0]['financialData']['recommendationKey']
        recommend_index = data['quoteSummary']['result'][0]['financialData']['recommendationMean']['raw']
        recommend_analysts = data['quoteSummary']['result'][0]['financialData']['numberOfAnalystOpinions']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['recommend'] = recommend
        local_market_data[ticker]['recommend_index'] = recommend_index
        local_market_data[ticker]['recommend_analysts'] = recommend_analysts
    try:
        price_to_sales = data['quoteSummary']['result'][0]['summaryDetail']['priceToSalesTrailing12Months']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['price_to_sales'] = price_to_sales
    try:
        data['quoteSummary']['result'][0]['earningsTrend']['trend'][0]['growth']['raw']
    except (KeyError, IndexError):
        pass
    else:
        for item in data['quoteSummary']['result'][0]['earningsTrend']['trend']:
            if item['period'] == '+1y':
                try:
                    revenueEstimateY = item['revenueEstimate']['growth']['raw']
                    earningsEstimateY = item['earningsEstimate']['growth']['raw']
                    revenueAnalysts = item['revenueEstimate']['numberOfAnalysts']['raw']
                    earningsAnalysts = item['earningsEstimate']['numberOfAnalysts']['raw']
                except (KeyError):
                    break
        try:
            earningsEstimateY = earningsEstimateY * 100
            revenueEstimateY = revenueEstimateY * 100
            local_market_data[ticker]['revenueEstimateY'] = round(revenueEstimateY, 2)
            local_market_data[ticker]['earningsEstimateY'] = round(earningsEstimateY, 2)
            local_market_data[ticker]['revenueAnalysts'] = revenueAnalysts
            local_market_data[ticker]['earningsAnalysts'] = earningsAnalysts
        except (UnboundLocalError):
            print(f'{ticker}†', sep=' ', end='', flush=True)
    try:
        data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][0]['revenue']['raw']
    except (KeyError, IndexError):
        print(f'{ticker}†', sep=' ', end='', flush=True)
        pass
    else:
        earningsQ = []
        revenueQ = []
        earningsY = []
        revenueY = []
        for item in data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly']:
            earningsQ.append(item['earnings']['raw'])
            revenueQ.append(item['revenue']['raw'])
        for item in data['quoteSummary']['result'][0]['earnings']['financialsChart']['yearly']:
            earningsY.append(item['earnings']['raw'])
            revenueY.append(item['revenue']['raw'])
        local_market_data[ticker]['earningsQ'] = earningsQ
        local_market_data[ticker]['revenueQ'] = revenueQ
        local_market_data[ticker]['earningsY'] = earningsY
        local_market_data[ticker]['revenueY'] = revenueY
    try:
        data['quoteSummary']['result'][0]['insiderTransactions']['transactions'][0]['startDate']['raw']
    except (KeyError, IndexError):
        pass
    else:
        buyTotal = 0
        buyValue = 0
        sellTotal = 0
        sellValue = 0
        for item in data['quoteSummary']['result'][0]['insiderTransactions']['transactions']:
            if item['startDate']['raw'] > now - 7884000:
                if 'Buy' in item['transactionText']:
                    buyTotal = buyTotal + item['shares']['raw']
                    buyValue = buyValue + item['value']['raw']
                if 'Sale' in item['transactionText']:
                    sellTotal = sellTotal + item['shares']['raw']
                    sellValue = sellValue + item['value']['raw']
        local_market_data[ticker]['insiderBuy'] = buyTotal
        local_market_data[ticker]['insiderSell'] = sellTotal
        local_market_data[ticker]['insiderBuyValue'] = buyValue
        local_market_data[ticker]['insiderSellValue'] = sellValue

    #print("")
    local_market_data[ticker] = dict(sorted(local_market_data[ticker].items()))
    return local_market_data

