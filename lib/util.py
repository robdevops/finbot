#!/usr/bin/python3

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import datetime
import json
import os

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
        title = title.rstrip()
        return title

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

def categorise_tickers(tickers):
    tickers_us = [] # used by fetch_finviz()
    tickers_au = [] # used by fetch_shortman()
    tickers_world = [] # used by fetch_yahoo()
    finviz_output = {}
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
                flag == '🇪🇺'
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
        elif suffix == 'TW':
            flag = '🇹🇼'
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

def currency_symbol(currency):
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
    time_now = datetime.datetime.today()
    now = time_now.timestamp()
    if os.path.isfile(cacheFile):
        cacheFileSeconds = now - int(os.path.getmtime(cacheFile))
        cacheTTL = maxSeconds - cacheFileSeconds
        if cacheTTL > 0:
            #print(cacheFile, "TTL:", int(round(cacheTTL/60, 0)), "minutes")
            with open(cacheFile, "r") as f:
                cacheDict = json.loads(f.read())
            return cacheDict

def write_cache(cache_file, fresh_dict):
    os.umask(0)
    def opener(path, flags):
        return os.open(path, flags, 0o640)
    with open(cache_file, "w", opener=opener) as f:
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
    if service == 'telegram':
            ticker_link = '<a href="' + yahoo_url + ticker + '">' + text + '</a>'
    elif service in {'discord', 'slack'}:
        ticker_link = '<' + yahoo_url + ticker + '|' + text + '>'
    else:
        ticker_link = item
    return ticker_link

def link(ticker, url, text, service='telegram'):
    if service == 'telegram':
        link = '<a href="' + url + '">' + text + '</a>'
    elif service in {'discord', 'slack'}:
        link = '<' + url + '|' + text + '>'
    else:
        link = ticker
    return link

