import datetime
import time
import json
import requests
import sys

from lib.config import *
from lib import util

def getCrumb(seconds=config_cache_seconds):
    cache_file = config_cache_dir + "/finbot_yahoo_cookie.json"
    cache = util.read_cache(cache_file, seconds)
    if config_cache and cache:
        return cache
    headers = {'cookie': 'A3=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng; A2=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng;', 'User-Agent': 'Mozilla/5.0'}
    yahoo_urls = ['https://query2.finance.yahoo.com/v1/test/getcrumb']
    yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
    for url in yahoo_urls:
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
        except Exception as e:
            print(e, file=sys.stderr)
        else:
            if r.status_code != 200:
                print(r.status_code, "returned by", url, file=sys.stderr)
                continue
            break
    else:
        print("Exhausted Yahoo API attempts. Giving up", file=sys.stderr)
        sys.exit(1)
    util.write_cache(cache_file, r.text)
    return r.text

def fetch(tickers):
    # NEVER CACHE THIS
    print("Fetching Yahoo data for " + str(len(tickers)) + " global holdings")
    now = int(time.time())
    yahoo_output = {}
    crumb = getCrumb()
    yahoo_urls = ['https://query2.finance.yahoo.com/v7/finance/quote?crumb=' + crumb + '&symbols=' + ','.join(tickers)]
    yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
    headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0', 'cookie': 'A3=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng; A2=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng;'}
    for url in yahoo_urls:
        print("Fetching", url)
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
        except Exception as e:
            print(e, file=sys.stderr)
        else:
            if r.status_code == 200:
                print(r.status_code, "success yahoo")
            else:
                print(r.status_code, "returned by", url, file=sys.stderr)
                continue
            break
    else:
        print("Exhausted Yahoo API attempts. Giving up", file=sys.stderr)
        sys.exit(1)
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
            percent_change = 0
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
            yahoo_output[ticker]["market_cap"] = round(float(item['marketCap']))
        except (KeyError, IndexError):
            pass
        try:
            yahoo_output[ticker]["forward_pe"] = round(item['forwardPE'])
        except:
            pass
        try:
            yahoo_output[ticker]["trailing_pe"] = round(item['trailingPE'])
        except:
            pass
        try:
            yahoo_output[ticker]["marketState"] = item['marketState']
        except:
            pass
        try:
            yahoo_output[ticker]["profile_exchange"] = item['fullExchangeName']
        except:
            pass
        try:
            yahoo_output[ticker]["exchangeTimezoneName"] = item['exchangeTimezoneName']
        except:
            pass
        try:
            yahoo_output[ticker]["regularMarketTime"] = item['regularMarketTime']
        except:
            pass
        try:
            earningsTimestamp = item['earningsTimestamp']
            earningsTimestampStart = item['earningsTimestampStart']
            earningsTimestampEnd = item['earningsTimestampEnd']
            if earningsTimestamp > now:
                yahoo_output[ticker]["earnings_date"] = earningsTimestamp
            elif earningsTimestampStart > now:
                yahoo_output[ticker]["earnings_date"] = earningsTimestampStart
            elif earningsTimestampEnd > now:
                yahoo_output[ticker]["earnings_date"] = earningsTimestampEnd
        except (KeyError, IndexError):
            pass
    return yahoo_output

def fetch_detail(ticker, seconds=config_cache_seconds):
    time_now = datetime.datetime.now()
    now = time_now.timestamp()
    local_market_data = {}
    base_url = 'https://query2.finance.yahoo.com/v11/finance/quoteSummary/'
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    local_market_data[ticker] = {}
    cache_file = config_cache_dir + "/finbot_yahoo_detail_" + ticker + '.json'
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
                print(e, file=sys.stderr)
            else:
                if r.status_code != 200:
                    print('x', sep=' ', end='', flush=True, file=sys.stderr)
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
        print(ticker + '†', sep=' ', end='', flush=True, file=sys.stderr)
        return False
    if profile_title is None: # catches some delisted stocks like "DUB"
        print(f"{ticker}†", sep=' ', end='', flush=True, file=sys.stderr)
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
        marketState = data['quoteSummary']['result'][0]['price']['marketState']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['marketState'] = marketState
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
        if data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['fmt'] is None:
            raise TypeError('quarterly earnings is null')
        else:
            net_income = data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['raw']
    except (KeyError, IndexError, TypeError):
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
                except KeyError:
                    break
        try:
            earningsEstimateY = earningsEstimateY * 100
            revenueEstimateY = revenueEstimateY * 100
            local_market_data[ticker]['revenueEstimateY'] = round(revenueEstimateY, 2)
            local_market_data[ticker]['earningsEstimateY'] = round(earningsEstimateY, 2)
            local_market_data[ticker]['revenueAnalysts'] = revenueAnalysts
            local_market_data[ticker]['earningsAnalysts'] = earningsAnalysts
        except UnboundLocalError:
            print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
    try:
        data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][0]['revenue']['raw']
    except (KeyError, IndexError):
        print(f'{ticker}†', sep=' ', end='', flush=True, file=sys.stderr)
    else:
        earningsQ = []
        revenueQ = []
        earningsY = []
        revenueY = []
        for item in data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly']:
            if item['earnings']['fmt'] is None: # bad data
                #if len(earningsQ): # may fix weirdness in dodelta()
                earningsQ.append(None)
                #if len(revenueQ):
                revenueQ.append(None)
            else:
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

    local_market_data[ticker] = dict(sorted(local_market_data[ticker].items()))
    return local_market_data

def price_history(ticker, days=27, seconds=config_cache_seconds):
    cache_file = config_cache_dir + "/finbot_yahoo_price_history_" + ticker + "_" + str(days) + ".json"
    cache = util.read_cache(cache_file, seconds)
    if config_cache and cache:
        return cache
    crumb = getCrumb()
    now = int(time.time())
    url = 'https://query1.finance.yahoo.com/v7/finance/download/' + ticker
    if days < 90:
        interval = '1d'
    else:
        interval = '1mo'
    url = url + '?period1=' + str(now - 86400 * days) + '&period2=' + str(now) + '&interval=' + interval + '&events=history&includeAdjustedClose=true'
    url = url + '&crumb=' + crumb
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=config_http_timeout)
    except:
        print("Failure fetching", url, file=sys.stderr)
        return False
    if r.status_code == 200:
        print('↓', sep=' ', end='', flush=True)
    else:
        print(ticker, r.status_code, "error communicating with", url, file=sys.stderr)
        return False
    csv = r.content.decode('utf-8').split('\n')
    price = []
    for line in csv[1:]:
        cells = line.split(',')
        try:
            price.append(float(cells[5]))
        except ValueError:
            continue
    percent = round(100 * (price[-1] - price[0]) / price[0], 2)
    util.write_cache(cache_file, percent)
    return percent
