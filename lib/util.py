import os
import time
import json
from lib.config import *

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def transform_title(title):
    title = title.replace(' FPO', '')
    if title.isupper() or title.islower():
        title = title.title()
    title = title.replace(' - ', ' ')
    title = title.replace('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'Clean Energy ETF')
    title = title.replace('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable')
    title = title.replace('Advanced Micro Devices', 'AMD')
    title = title.replace('Taiwan Semiconductor Manufacturing', 'TSM')
    title = title.replace('Flight Centre Travel', 'Flight Centre')
    title = title.replace('Global X ', '')
    title = title.replace('The ', '')
    title = title.replace('N.V.', '')
    title = title.replace('New York Re', '')
    title = title.replace(' Australian', ' Aus')
    title = title.replace(' Australia', ' Aus')
    title = title.replace(' Infrastructure', 'Infra')
    title = title.replace(' Manufacturing Company', ' ')
    title = title.replace(' Limited', ' ')
    title = title.replace(' Ltd', ' ')
    title = title.replace(' Holdings', ' ')
    title = title.replace(' Holding', ' ')
    title = title.replace(' Corporation', ' ')
    title = title.replace(' Incorporated', ' ')
    title = title.replace(' incorporated', ' ')
    title = title.replace(' Technologies', ' ')
    title = title.replace(' Technology', ' ')
    title = title.replace(' Enterprises', ' ')
    title = title.replace(' Ventures', ' ')
    title = title.replace(' Co.', ' ')
    title = title.replace(' Corp.', ' ')
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
    if title.islower():
        title = title.title()
    title = title.strip()
    return title

def categorise_tickers(tickers):
    tickers_us = [] # used by fetch_finviz()
    tickers_au = [] # used by fetch_shortman()
    tickers_world = [] # used by fetch_yahoo()
    for ticker in tickers:
        if '.AX' in ticker:
            tickers_au.append(ticker)
        if '.' in ticker:
            tickers_world.append(ticker)
        else:
            tickers_us.append(ticker)
    return tickers_au, tickers_world, tickers_us

def flag_from_market(market):
    flag=''
    if market == 'ASX':
        flag = '🇦🇺'
    elif market in {'BOM', 'NSE'}:
        flag = '🇮🇳'
    elif market in {'BMV'}:
        flag = '🇲🇽'
    elif market in {'BKK'}:
        flag = '🇹🇭'
    elif market in {'BVMF'}:
        flag = '🇧🇷'
    elif market in {'SHE', 'SGX', 'SHA'}:
        flag = '🇨🇳'
    elif market == 'CPSE':
        flag = '🇩🇰'
    elif market in {'EURONEXT','AMS','ATH','BIT','BME','DUB','EBR','EPA','ETR','FWB','FRA','VIE'}:
        flag = '🇪🇺'
    elif market == 'HKG':
        flag = '🇭🇰'
    elif market == 'ICSE':
        flag = '🇮🇸'
    elif market in {'JSE'}:
        flag = '🇿🇦'
    elif market in {'KRX', 'KOSDAQ'}:
        flag = '🇰🇷'
    elif market == 'LSE':
        flag = '🇬🇧'
    elif market == 'MISX':
        flag = '🇷🇺'
    elif market in {'OM', 'STO'}:
        flag = '🇸🇪'
    elif market == 'SGX':
        flag = '🇸🇬'
    elif market in {'SWX', 'VTX'}:
        flag = '🇨🇭'
    elif market in {'TAI', 'TPE'}:
        flag = '🇹🇼'
    elif market == 'TASE':
        flag = '🇮🇱'
    elif market == 'OB':
        flag = '🇳🇴'
    elif market == 'TSE':
        flag = '🇯🇵'
    elif market == 'TSX':
        flag = '🇨🇦'
    elif market in {'NASDAQ', 'NYSE', 'BATS'}:
        flag = '🇺🇸'
    elif market in {'WAR'}:
        flag = '🇵🇱'
    return flag

def flag_from_ticker(ticker):
    flag = ''
    if '.' in ticker:
        suffix = ticker.split('.')[1]
        if suffix == 'AX':
            flag = '🇦🇺'
        elif suffix == 'HK':
            flag = '🇭🇰'
        elif suffix in ('KS', 'KQ'):
            flag = '🇰🇷'
        elif suffix == 'L':
            flag = '🇬🇧'
        elif suffix in ('TW', 'TWO'):
            flag = '🇹🇼'
        elif suffix == 'TO':
            flag = '🇨🇦'
    else:
        flag = '🇺🇸'
    return flag

def currency_from_market(market):
    if market == 'ASX':
        currency = 'AUD'
    elif market in {'BOM', 'NSE'}:
        currency = 'INR'
    elif market in {'BMV'}:
        currency = 'MXN'
    elif market in {'BKK'}:
        currency = 'THB'
    elif market in {'BVMF'}:
        currency = 'BRL'
    elif market in {'SHE', 'SGX', 'SHA'}:
        currency = 'CNY'
    elif market == 'CPSE':
        currency = 'DEK'
    elif market in {'EURONEXT','AMS','ATH','BIT','BME','DUB','EBR','EPA','ETR','FWB','FRA','VIE'}:
        currency = 'EUR'
    elif market == 'ICSE':
        currency = 'ISK'
    elif market in {'JSE'}:
        currency = 'ZAR'
    elif market in {'KRX', 'KOSDAQ'}:
        currency = 'KRW'
    elif market == 'MISX':
        currency = 'RUB'
    elif market in {'OM', 'STO'}:
        currency = 'SEK'
    elif market == 'SGX':
        currency = 'SGD'
    elif market in {'SWX', 'VTX'}:
        currency = 'CHF'
    elif market in {'TAI', 'TPE'}:
        currency = 'TWD'
    elif market == 'TASE':
        currency = 'ILS'
    elif market == 'OB':
        currency = 'NOK'
    elif market == 'TSE':
        currency = 'JPY'
    elif market == 'TSX':
        currency = 'CAD'
    elif market in {'NASDAQ', 'NYSE', 'BATS'}:
        currency = 'USD'
    elif market in {'WAR'}:
        currency = 'PLN'
    else:
        # note: LSE and HKE allow non-home currencies
        return False
    return currency

def get_currency_symbol(currency):
    currency_symbol=''
    if currency in {'AUD', 'CAD', 'HKD', 'NZD', 'SGD', 'TWD', 'USD'}:
        currency_symbol = '$'
    elif currency_symbol in {'CNY', 'JPY'}:
        currency_symbol = '¥'
    elif currency == 'EUR':
        currency_symbol = '€'
    elif currency == 'GBP':
        currency_symbol = '£'
    elif currency_symbol == 'KRW':
        currency_symbol = '₩'
    elif currency == 'RUB':
        currency_symbol = '₽'
    elif currency == 'THB':
        currency_symbol = '฿'
    return currency_symbol

def read_cache(cacheFile, maxSeconds=config_cache_seconds):
    if os.path.isfile(cacheFile):
        cacheFileSeconds = time.time() - os.path.getmtime(cacheFile)
        cacheTTL = maxSeconds - cacheFileSeconds
        if cacheTTL > 0:
            if debug:
                print(cacheFile, "TTL:", int(round(cacheTTL/60, 0)), "minutes")
            with open(cacheFile, "r", encoding="utf-8") as f:
                cacheDict = json.loads(f.read())
            return cacheDict
        if debug:
            print("cache expired:", cacheFile)
        return False
    print("Cache file does not exist:", cacheFile, "first run?")
    return False

def write_cache(cache_file, fresh_dict):
    os.umask(0)
    def opener(path, flags):
        return os.open(path, flags, 0o640)
    with open(cache_file, "w", opener=opener, encoding="utf-8") as f:
        f.write(json.dumps(fresh_dict))
    os.umask(0o022)

def humanUnits(value, decimal_places=0):
    for unit in ['', 'K', 'M', 'B', 'T', 'Q']:
        if value < 1000.0 or unit == 'Q':
            break
        value /= 1000.0
    return f"{value:.{decimal_places}f} {unit}"

def yahoo_link(ticker, service='telegram', brief=False):
    yahoo_url = "https://au.finance.yahoo.com/quote/"
    if brief:
        text = ticker.split('.')[0]
    else:
        text = ticker
    if service == 'telegram' and config_hyperlink:
        ticker_link = '<a href="' + yahoo_url + ticker + '">' + text + '</a>'
    elif service in {'discord', 'slack'} and config_hyperlink:
        ticker_link = '<' + yahoo_url + ticker + '|' + text + '>'
    else:
        ticker_link = text
    return ticker_link

def link(url, text, service='telegram'):
    if service == 'telegram' and config_hyperlink:
        hyperlink = '<a href="' + url + '">' + text + '</a>'
    elif service in {'discord', 'slack'} and config_hyperlink:
        hyperlink = '<' + url + '|' + text + '>'
    else:
        hyperlink = text
    return hyperlink

def gfinance_link(symbol, market, service='telegram', days=1, brief=False):
    window = '1D'
    if days > 1:
        window = '5D'
    if days > 7:
        window = '1M'
    if days > 31:
        window = '6M'
    if days > 183:
        window = '1Y'
    url = "https://www.google.com/finance/quote/"
    market = transform_to_google(market)
    if ':' in symbol:
        return symbol
    ticker = symbol.split('.')[0] + ':' + market
    if brief:
        text = symbol
    else:
        if '.' in symbol:
            text = ticker
        else:
            text = symbol
    if service == 'telegram' and config_hyperlink:
        ticker_link = '<a href="' + url + ticker + '?window=' + window + '">' + text + '</a>'
    elif service in {'discord', 'slack'} and config_hyperlink:
        ticker_link = '<' + url + ticker + '?window=' + window + '|' + text + '>'
    else:
        ticker_link = symbol
    return ticker_link

def transform_to_google(exchange):
    if 'Nasdaq' in exchange:
        exchange = 'NASDAQ'
    elif exchange in {'OTC', 'PNK', 'Other OTC', 'OTCPK'}:
        exchange = 'OTCMKTS'
    elif exchange in {'TO', 'TOR', 'Toronto'}:
        exchange = 'TSE'
    elif exchange in {'TW', 'TWO', 'TAI', 'Taiwan', 'Taipei Exchange', 'Taipei'}:
        exchange = 'TPE'
    elif exchange in {'HK', 'HKG', 'HKSE'}:
        exchange = 'HKG'
    elif exchange in {'KQ', 'KOE', 'KOSDAQ'}:
        exchange = 'KOSDAQ'
    elif exchange in {'KS', 'KRX', 'KSE', 'KSC'}:
        exchange = 'KRX'
    elif exchange in {'L', 'LSE', 'London'}:
        exchange = 'LON'
    elif exchange in {'T', 'TYO', 'JPX', 'Tokyo'}:
        exchange = 'TYO'
    elif exchange in {'TA', 'TLV', 'Tel Aviv'}:
        exchange = 'TLV'
    return exchange

def transform_to_yahoo(ticker, market=False):
    split = ticker.replace(':', '.').split('.')
    if len(split) > 1:
        ticker = split[0]
        market = split[1]
    if not market:
        return ticker
    if market == 'ASX':
        market = 'AX'
    if market == 'HKG':
        market = 'HK'
    if market == 'KRX':
        market = 'KS'
    if market == 'KOSDAQ':
        market = 'KQ'
    if market == 'LSE':
        market = 'L'
    if market in 'TAI': # Taiwan in YF, Sharesight
        market = 'TW' # TPE in GF
    if market == 'TPE': # Taipei in YF, Taiwan in GF. GF format will not work as input
        market = 'TWO' # missing from GF
    if market == 'TSE':
        market = 'TO'
    if market == 'TYO':
        market = 'T'
    if market == 'TLV':
        market = 'TA'
    if market in {'NASDAQ', 'NYSE', 'BATS', 'OTCMKTS'}:
        return ticker
    ticker = ticker + '.' + market
    return ticker

def watchlist_load():
    cache_file = config_cache_dir + "/finbot_watchlist.json"
    if os.path.isfile(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            watchlist = json.loads(f.read())
    else:
        watchlist = []
    return watchlist

def strip_url(url):
    url = url.removeprefix('https://www.')
    url = url.removeprefix('http://www.')
    url = url.removeprefix('https://')
    url = url.removeprefix('http://')
    return url
