import datetime
from dateutil.relativedelta import relativedelta
import hashlib
import io
import json
import requests
import pandas as pd
import pytz
from pandas.tseries.offsets import BDay as businessday
import sys
import lib.telegram as telegram
from lib.config import *
from lib import util

def getCrumb(seconds=config_cache_seconds):
    cache_file = "finbot_yahoo_cookie.json"
    cache = util.read_cache(cache_file, seconds)
    if config_cache and cache:
        return cache
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36', 'Cookie': 'GUC=AQEBCAFkpQZkz0IgwQSu&s=AQAAAP2Vnw8z&g=ZKO-Qw; A1=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBCAEGpWTPZA3sbmUB_eMBAAcI88A8ZLRyLcI&S=AQAAAmdorBhpNjsvOXeGN1RBvX8; A3=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBCAEGpWTPZA3sbmUB_eMBAAcI88A8ZLRyLcI&S=AQAAAmdorBhpNjsvOXeGN1RBvX8; A1S=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBCAEGpWTPZA3sbmUB_eMBAAcI88A8ZLRyLcI&S=AQAAAmdorBhpNjsvOXeGN1RBvX8&j=WORLD; cmp=t=1689038249&j=0&u=1---; PRF=t%3DBILL.AX%252BIVV.AX%252BSPY%252BNVDA%252BCHPT%252BAAPL%252BSEDG%252BGME%252BASO.AX%252BRMBS%252BAI%252BRBLX%252BNTDOY%252BPYPL%252BAMPX%26newChartbetateaser%3D1'}
    yahoo_urls = ['https://query2.finance.yahoo.com/v1/test/getcrumb']
    yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
    for url in yahoo_urls:
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
        except Exception as e:
            print(e, file=sys.stderr)
        else:
            if r.status_code != 200:
                print(r.status_code, r.text, "returned by", url, file=sys.stderr)
                continue
            break
    else:
        print("Exhausted Yahoo API attempts. Giving up", file=sys.stderr)
        sys.exit(1)
    if config_cache:
        util.json_write(cache_file, r.text)
    return r.text

def fetch(tickers):
    # DO NOT CACHE MORE THAN 5 mins
    #print("Fetching Yahoo data for " + str(len(tickers)) + " global holdings")
    tickers = list(tickers)
    tickers.sort()
    tickers_sha256 = hashlib.sha256(str.encode("_".join(tickers))).hexdigest()
    cache_file = "finbot_yahoo_" + tickers_sha256 + '.json'
    cacheData = util.read_cache(cache_file, 60)
    if config_cache and cacheData:
        return cacheData
    now = datetime.datetime.now().timestamp()
    yahoo_output = {}
    crumb = getCrumb()
    yahoo_urls = ['https://query2.finance.yahoo.com/v7/finance/quote?crumb=' + crumb + '&symbols=' + ','.join(tickers)]
    yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
    headers = {'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0', 'cookie': 'A3=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng; A2=d=AQABBPPAPGQCEEJFcoEDblUBAaI8dLRyLcIFEgEBAQESPmRGZAAAAAAA_eMAAA&S=AQAAAmG1EiWmVUILE2HuXk4v6Ng;'}
    for url in yahoo_urls:
        if debug:
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
    if data['result'] is None or data['error'] is not None:
        print(f"{tickers}†", sep=' ', end='', flush=True, file=sys.stderr)
        return None
    for item in data['result']:
        ticker = item['symbol']
        try:
            profile_title = item['longName']
        except (KeyError, IndexError):
            try:
                profile_title = item['shortName']
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
            regularMarketPrice = item['regularMarketPrice']
        except (KeyError, IndexError):
            continue
        try:
            dividend = round(float(item['trailingAnnualDividendRate']), 1)
        except (KeyError, IndexError):
            dividend = float(0)
        profile_title = util.transform_title(profile_title)
        yahoo_output[ticker] = { 'profile_title': profile_title, 'ticker': ticker, 'percent_change': percent_change, 'dividend': dividend, 'currency': currency, 'regularMarketPrice': regularMarketPrice }
        # optional fields
        try:
            percent_change_premarket = item['preMarketChangePercent']
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["percent_change_premarket"] = round(percent_change_premarket, 2)
        try:
            quoteType = item['quoteType']
        except (KeyError, IndexError):
            pass
        else:
            yahoo_output[ticker]["quoteType"] = quoteType
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
            yahoo_output[ticker]["price_to_earnings_forward"] = round(item['forwardPE'])
        except:
            pass
        try:
            yahoo_output[ticker]["price_to_earnings_trailing"] = round(item['trailingPE'])
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
            yahoo_output[ticker]["financialCurrency"] = item['financialCurrency']
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
            else:
                yahoo_output[ticker]["earnings_date"] = earningsTimestamp
        except (KeyError, IndexError):
            pass
    if config_cache:
        util.json_write(cache_file, yahoo_output)
    return yahoo_output

def fetch_detail(ticker, seconds=config_cache_seconds):
    now = datetime.datetime.now()
    local_market_data = {}
    crumb = getCrumb()
    base_url = 'https://query2.finance.yahoo.com/v10/finance/quoteSummary/'
    #headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7', 'Cookie': 'tbla_id=c3e7a9b8-6497-4f07-b420-ab1e6e014111-tuctb38a4b1; B=b7sv001i3u7ph&b=3&s=5k; gam_id=y-RMVTvFpE2uLFxS5dbbxRfcv6TBoCtMen~A; A1=d=AQABBDEfP2QCEKF41xDYjU9cCqCPIQDg87MFEgEBCAFejGS-ZA3sbmUB_eMBAAcIMR8_ZADg87M&S=AQAAAhnXBZlUXHqF945okeljNQc; A3=d=AQABBDEfP2QCEKF41xDYjU9cCqCPIQDg87MFEgEBCAFejGS-ZA3sbmUB_eMBAAcIMR8_ZADg87M&S=AQAAAhnXBZlUXHqF945okeljNQc; GUC=AQEBCAFkjF5kvkIc5QQ0; cmp=t=1688194850&j=0&u=1---; PRF=t%3DQQQ%252BQQQM%252BNVDA%252BAMD%252BBAM%252BLSIP.JK%252BEPCC.F%252BCPAC%252BEPCC.BE%252BEPCC.SG%252BMTS.MC%252BMT.AS%252BBCOLOMBIA.CL%252BPFBCOLOM.CL%252BACAP.BK%26newChartbetateaser%3D1; A1S=d=AQABBDEfP2QCEKF41xDYjU9cCqCPIQDg87MFEgEBCAFejGS-ZA3sbmUB_eMBAAcIMR8_ZADg87M&S=AQAAAhnXBZlUXHqF945okeljNQc&j=WORLD'}
    local_market_data[ticker] = dict()
    cache_file = "finbot_yahoo_detail_" + ticker + '.json'
    cacheData = util.read_cache(cache_file, seconds)
    if config_cache and cacheData:
        print('.', sep=' ', end='', flush=True)
        data = cacheData
    else:
        print('↓', sep=' ', end='', flush=True)
        yahoo_urls = [base_url + ticker + '?modules=calendarEvents,defaultKeyStatistics,balanceSheetHistoryQuarterly,financialData,summaryProfile,summaryDetail,price,earnings,earningsTrend,insiderTransactions' + '&crumb=' + crumb]
        yahoo_urls.append(yahoo_urls[0].replace('query2', 'query1'))
        for url in yahoo_urls:
            if debug:
                print(url)
            try:
                r = requests.get(url, headers=headers, timeout=config_http_timeout)
            except Exception as e:
                print(e, file=sys.stderr)
            else:
                if r.status_code != 200:
                    print('x', sep=' ', end='', flush=True, file=sys.stderr)
                    if debug:
                        print(r.text)
                    continue
                break
        else:
            print(ticker + '†', sep=' ', end='', flush=True)
            return {} # catches some delisted stocks like "DRNA"
        data = r.json()
        if config_cache:
            util.json_write(cache_file, data)
        # might be interesting:
            # majorHoldersBreakdown
            # netSharePurchaseActivity
            # upgradeDowngradeHistory
    try:
        profile_title = data['quoteSummary']['result'][0]['price']['longName']
    except (KeyError, IndexError, ValueError):
        print(ticker + 'x', sep=' ', end='', flush=True, file=sys.stderr)
        return {}
    if profile_title is None:
        try:
            profile_title = data['quoteSummary']['result'][0]['price']['shortName']
        except (KeyError, IndexError, ValueError):
            print(ticker + '†', sep=' ', end='', flush=True, file=sys.stderr)
            return {}
    if profile_title is None: # catches some delisted stocks like "DUB"
        print(f"{ticker}†", sep=' ', end='', flush=True, file=sys.stderr)
        return {}
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
        beta = data['quoteSummary']['result'][0]['summaryDetail']['beta']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['beta'] = beta
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
        quoteType = data['quoteSummary']['result'][0]['price']['quoteType']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['quoteType'] = quoteType
    try:
        regularMarketPrice = data['quoteSummary']['result'][0]['price']['regularMarketPrice']['raw']
    except (KeyError, IndexError):
        return {} # catches junk
    else:
        local_market_data[ticker]['regularMarketPrice'] = regularMarketPrice
    try:
        preMarketPrice = float(data['quoteSummary']['result'][0]['price']['preMarketPrice']['raw'])
    except (KeyError, IndexError, ValueError):
        pass
    else:
        local_market_data[ticker]['prePostMarketPrice'] = preMarketPrice
    try:
        postMarketPrice = float(data['quoteSummary']['result'][0]['price']['postMarketPrice']['raw'])
    except (KeyError, IndexError, ValueError):
        pass
    else:
        local_market_data[ticker]['prePostMarketPrice'] = postMarketPrice
    try:
        netIncomeToCommon = data['quoteSummary']['result'][0]['defaultKeyStatistics']['netIncomeToCommon']['raw']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['netIncomeToCommon'] = netIncomeToCommon
    try:
        sharesOutstanding = float(data['quoteSummary']['result'][0]['defaultKeyStatistics']['sharesOutstanding']['raw'])
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['sharesOutstanding'] = sharesOutstanding
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
        if data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['fmt'] is not None:
            net_income = data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-1]['earnings']['raw']
        elif data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-2]['earnings']['fmt'] is not None:
            net_income = data['quoteSummary']['result'][0]['earnings']['financialsChart']['quarterly'][-2]['earnings']['raw']
        else:
            raise TypeError('quarterly earnings is null')
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
        financialCurrency = data['quoteSummary']['result'][0]['financialData']['financialCurrency']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['financialCurrency'] = financialCurrency
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
        currency = data['quoteSummary']['result'][0]['summaryDetail']['currency']
    except (KeyError, IndexError):
        pass
    else:
        local_market_data[ticker]['currency'] = currency
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
            dt_startDate = datetime.datetime.fromtimestamp(item['startDate']['raw'])
            if dt_startDate > now - datetime.timedelta(days=90):
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

def price_history(ticker, days=None, seconds=config_cache_seconds, graph=config_graph):
    image_data = None
    percent_dict = {}
    market_data = fetch([ticker])
    tz = pytz.timezone(market_data[ticker]['exchangeTimezoneName'])
    regularMarketTime = datetime.datetime.fromtimestamp(market_data[ticker]['regularMarketTime']).astimezone(tz).date()
    regularMarketPrice = market_data[ticker]['regularMarketPrice']
    now = datetime.datetime.now()
    cache_file = "finbot_yahoo_price_history_" + ticker + ".json"
    cache = util.read_cache(cache_file, seconds)
    if config_cache and cache:
        csv = cache
    else:
        crumb = getCrumb()
        start =  str(int((now - datetime.timedelta(days=1836)).timestamp())) # 5 years inc leap year
        end = str(int(now.timestamp()))
        interval = '1d'
        url = 'https://query1.finance.yahoo.com/v7/finance/download/' + ticker
        url = url + '?period1=' + start + '&period2=' + end + '&interval=' + interval + '&events=history&includeAdjustedClose=true'
        url = url + '&crumb=' + crumb
        if debug: print(url)
        headers={'Content-type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        try:
            r = requests.get(url, headers=headers, timeout=config_http_timeout)
        except:
            print("Failure fetching", url, file=sys.stderr)
            return None
        if r.status_code == 200:
            print('↓', sep=' ', end='', flush=True)
        else:
            print(ticker, r.status_code, "error communicating with", url, file=sys.stderr)
            return None
        csv = r.content.decode('utf-8')
    df = pd.read_csv(io.StringIO(csv))
    df['Date'] = pd.to_datetime(df['Date']).dt.date
    if df['Date'].iloc[-1] == regularMarketTime:
        if df['Close'].iloc[-1] != regularMarketPrice:
            print("Updating", df['Close'].iloc[-1], "to", regularMarketPrice)
            df['Close'].loc[-1] = regularMarketPrice
    else:
        print (ticker, "inserting", regularMarketTime, "after", df['Date'].iloc[-1], file=sys.stderr)
        previous_close = df['Close'].iloc[-1]
        df.loc[len(df)] = {'Date': regularMarketTime, 'Open': previous_close, 'High': None, 'Low': None, 'Close': regularMarketPrice, 'Adj Close': regularMarketPrice, 'Volume': None}
    df = df[df.Close.notnull()]
    #df.sort_values(by='Date', inplace = True)
    df.reset_index(drop=True, inplace=True)
    price = []
    interval = ('5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '5D', '1D')
    if days:
        seek_date = now - datetime.timedelta(days = days)
        seek_dt = seek_date.date()
        mask = df['Date'] >= seek_dt
        df = df.loc[mask]
        past_price = df[df.loc[mask]['Date'] >= seek_dt]['Close'].iloc[0]
        df.reset_index(drop=True, inplace=True)
        percent = (regularMarketPrice - past_price) / past_price * 100
        percent_dict[days] = round(percent, 2)
    else:
        default_price = df['Close'].iloc[0]
        default_percent = round((regularMarketPrice - default_price) / default_price * 100)
        for period in interval:
            # try to align with google finance
            if period == 'YTD':
                seek_dt = now.replace(day=1, month=1).date()
                try:
                    past_price = df[df['Date'] >= seek_dt]['Close'].iloc[0]
                except IndexError:
                    percent_dict['Max'] = default_percent
                    continue
            elif period == '1D':
                    percent_dict['1D'] = market_data[ticker]['percent_change']
            elif period == '5D':
                #seek_date = now - datetime.timedelta(days = 5)
                seek_date = now - businessday(5)
                seek_dt = seek_date.date()
                try:
                    past_price = df[df['Date'] <= seek_dt]['Open'].iloc[-1]
                except IndexError:
                    percent_dict['Max'] = default_percent
                    continue
            elif period.endswith('M'):
                months = int(period.removesuffix('M'))
                seek_date = now - relativedelta(months=months)
                seek_dt = seek_date.date()
                try:
                    past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
                except IndexError:
                    percent_dict['Max'] = default_percent
                    continue
            elif period.endswith('Y'):
                years = int(period.removesuffix('Y'))
                seek_date = now - relativedelta(years=years)
                seek_dt = seek_date.date()
                try:
                    past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
                except IndexError:
                    percent_dict['Max'] = default_percent
                    continue
            else:
                seek_date = now - datetime.timedelta(days = int(period.removesuffix('D')))
                seek_dt = seek_date.date()
                #print(df[df['Date'] <= seek_dt].tail(1))
                try:
                    past_price = df[df['Date'] <= seek_dt]['Close'].iloc[-1]
                except IndexError:
                    percent_dict['Max'] = default_percent
                    continue
            percent = (regularMarketPrice - past_price) / past_price * 100
            percent_dict[period] = round(percent)
    if graph:
        if days and days < 2:
            return percent_dict, None
        caption = []
        profile_title = market_data[ticker]['profile_title']
        if days:
            title = profile_title + " (" + ticker + ") " + str(days) + " days " + str(percent_dict[days]) + '%'
            caption.append(title)
        else:
            for k,v in percent_dict.items():
                caption.append(str(k) + ": " + str(v) + '%')
            if 'Max' in percent_dict:
                title = profile_title + " (" + ticker + ") Max " + str(percent_dict['Max']) + '%'
            else:
                title = profile_title + " (" + ticker + ") 5Y " + str(percent_dict['5Y']) + '%'
        caption = '\n'.join(caption)
        image_cache_file = "finbot_graph_" + ticker + "_" + str(days) + ".png"
        image_cache = util.read_binary_cache(image_cache_file, seconds)
        if config_cache and image_cache:
            image_data = image_cache
        else:
            buf = util.graph(df, title, market_data[ticker])
            #bytesio_to_file(buf, 'temp.png')
            buf.seek(0)
            image_data = buf
            util.write_binary_cache(image_cache_file, image_data)
            buf.seek(0)
    if config_cache:
        util.json_write(cache_file, csv)
    return percent_dict, image_data

