import os
import io
import datetime
import json
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from lib.config import *

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def transform_title(title):
    title = title.replace(' FPO', '')
    if title.isupper() or title.islower():
        title = title.title()
    title = title.replace(' - ', ' ')
    title = title.replace('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'First Trust Clean Energy')
    title = title.replace('First Trust Exchange-Traded Fund III First Trust Nasdaq Clean Edge Clean Energy Index Fund', 'First Trust Green Energy')
    title = title.replace('Mirae Asset Global Investments (Hong Kong) Limited', '')
    title = title.replace('New York Shares', '')
    title = title.replace('China Electric Vehicle and Battery ETF', 'China EV ETF')
    title = title.replace('China Electric Vehicle ETF', 'China EV ETF')
    title = title.replace('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable')
    title = title.replace('Advanced Micro Devices', 'AMD')
    title = title.replace('Taiwan Semiconductor Manufacturing', 'TSM')
    title = title.replace('Flight Centre Travel', 'Flight Centre')
    title = title.replace('Global X Funds ', '')
    title = title.replace(' of Australia', '')
    title = title.replace('National Australia Bank', 'NAB')
    title = title.replace(' PLC', '')
    title = title.replace(' p.l.c.', '')
    title = title.replace(' P.l.c.', '')
    title = title.replace(' P.L.C.', '')
    if title.endswith(' AG'):
        title = title.replace(' AG', '')
    if title.endswith(' SE'):
        title = title.replace(' SE', '')
    if title.endswith(' Se'):
        title = title.replace(' SE', '')
    title = title.replace('Microbalifesciences', 'Microba Life Sciences')
    title = title.replace('Walt Disney Co (The)', 'Disney')
    title = title.replace('Lisenergylimited', 'LI-S Energy')
    title = title.replace('VanEck ETF Trust ', '')
    title = title.replace('Invesco Capital Management LLC ', '')
    title = title.replace('QUALCOMM', 'Qualcomm')
    title = title.replace('Ordinary Shares Class A', '')
    title = title.replace('Ordinary Shares Class C', '')
    title = title.replace('Lbt Innovations', 'LBT Innovations')
    title = title.replace('The ', '')
    title = title.replace('Rea ', 'REA ')
    title = title.replace('Csl ', 'CSL ')
    title = title.replace('Battery ', 'Batt ')
    title = title.replace('Etf', '')
    title = title.replace('ETF', '')
    title = title.replace('N.V.', '')
    title = title.replace(' NV ', ' ')
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
    title = title.replace(' Enterprise', ' ')
    title = title.replace(' Enterpr', ' ')
    title = title.replace(' Ventures', ' ')
    title = title.replace(' Co.', ' ')
    title = title.replace(' Corp.', ' ')
    title = title.replace(' Corp', ' ')
    title = title.replace(' Tech ', ' ')
    title = title.replace(' Company', ' ')
    title = title.replace(' Group', ' ')
    title = title.replace(', Inc', ' ')
    title = title.replace(' Inc', ' ')
    title = title.replace(' Plc', ' ')
    title = title.replace(' plc', ' ')
    title = title.replace(' Index', ' ')
    title = title.replace(' ADR', ' ')
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
    cacheFile = config_cache_dir + "/" + cacheFile
    if os.path.isfile(cacheFile):
        maxSeconds = datetime.timedelta(seconds=maxSeconds)
        cacheFileMtime = datetime.datetime.fromtimestamp(os.path.getmtime(cacheFile))
        cacheFileAge = datetime.datetime.now() - cacheFileMtime
        if cacheFileAge < maxSeconds:
            if debug:
                ttl = round((maxSeconds - cacheFileAge).total_seconds() / 60)
                print(cacheFile, "TTL:", ttl, "minutes", file=sys.stderr)
            with open(cacheFile, "r", encoding="utf-8") as f:
                cacheDict = json.loads(f.read())
            return cacheDict
        if debug:
            print("cache expired:", cacheFile, file=sys.stderr)
        return False
    print("Cache file does not exist:", cacheFile, "first run?", file=sys.stderr)
    return False

def json_write(filename, data):
    filename = config_cache_dir + "/" + filename
    os.umask(0)
    def opener(filename, flags):
        return os.open(filename, flags, 0o640)
    with open(filename, "w", opener=opener, encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4))
    os.umask(0o022)

def json_load(filename):
    filename = config_cache_dir + "/" + filename
    if os.path.isfile(filename):
        with open(filename, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    else:
        data = None
    return data

def read_binary_cache(cacheFile, maxSeconds=config_cache_seconds):
    cacheFile = config_cache_dir + "/" + cacheFile
    if os.path.isfile(cacheFile):
        maxSeconds = datetime.timedelta(seconds=maxSeconds)
        cacheFileMtime = datetime.datetime.fromtimestamp(os.path.getmtime(cacheFile))
        cacheFileAge = datetime.datetime.now() - cacheFileMtime
        if cacheFileAge < maxSeconds:
            if debug:
                ttl = round((maxSeconds - cacheFileAge).total_seconds() / 60)
                print(cacheFile, "TTL:", ttl, "minutes", file=sys.stderr)
            with open(cacheFile, "rb") as f:
                data = io.BytesIO(f.read())
            return data
        if debug:
            print("cache expired:", cacheFile, file=sys.stderr)
        return False
    print("Cache file does not exist:", cacheFile, "first run?", file=sys.stderr)
    return False

def write_binary_cache(cacheFile, data):
    cacheFile = config_cache_dir + "/" + cacheFile
    os.umask(0)
    def opener(path, flags):
        return os.open(path, flags, 0o640)
    with open(cacheFile, "wb", opener=opener) as f:
        data.seek(0)
        f.write(data.getbuffer())
    os.umask(0o022)

def humanUnits(value, decimal_places=0):
    for unit in ['', 'K', 'M', 'B', 'T', 'Q']:
        if value < 1000.0 or unit == 'Q':
            break
        value /= 1000.0
    return f"{value:.{decimal_places}f} {unit}"

def yahoo_link(ticker, service='telegram', brief=True, text=False):
    yahoo_url = "https://au.finance.yahoo.com/quote/"
    if brief and not text:
        text = ticker.split('.')[0]
    elif not text:
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

def finance_link(symbol, exchange, service='telegram', days=1, brief=True, text=False):
    if config_hyperlinkProvider == 'google':
        link = gfinance_link(symbol, exchange, service, days, brief, text)
    else:
        link = yahoo_link(ticker, service, brief, text)
    return link

def gfinance_link(symbol, exchange, service='telegram', days=1, brief=True, text=False):
    window = '1D'
    if days > 1:
        window = '5D'
    if days > 7:
        window = '1M'
    if days > 31:
        window = '6M'
    if days > 183:
        window = '1Y'
    if days > 365:
        window = '5Y'
    if days > 1825:
        window = 'Max'
    url = "https://www.google.com/finance/quote/"
    if '.' in exchange:
        exchange = exchange.split('.')[1]
    exchange = transform_to_google(exchange)
    symbol_short = symbol.replace(':', '.').split('.')[0]
    symbol_short = symbol_short.replace('-', '.') # class shares e.g. BRK.A
    ticker = symbol_short + ':' + exchange
    if brief and not text:
        text = symbol_short
    elif not text:
        if '.' in symbol:
            text = ticker
        else:
            text = symbol # US
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
    if market == 'TAI': # Taiwan in YF, Sharesight
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
    if market in {'A', 'B', 'C'}: # class shares
        return ticker + '-' + market
    ticker = ticker + '.' + market
    return ticker

def strip_url(url):
    url = url.removeprefix('https://www.')
    url = url.removeprefix('http://www.')
    url = url.removeprefix('https://')
    url = url.removeprefix('http://')
    return url

def make_paragraphs(walloftext):
    buffer = []
    output = []
    for word in walloftext.split():
        buffer.append(word)
        if word.endswith(('!', '.')) and len(buffer) > 22:
            output.append(' '.join(buffer))
            buffer = []
    output = '\n\n'.join(output)
    return output

def days_english(days, prefix='the past ', article=''):
    if days == 0:
        return 'today'
    elif days == 1:
        return prefix + article + 'day'
    elif days == 7:
        return prefix + article + 'week'
    elif days == 30:
        return prefix + article + 'month'
    elif days == 365:
        return prefix + article + 'year'
    elif days % 7 == 0:
        return prefix + str(int(days/7)) + ' weeks'
    elif days % 30 == 0:
        return prefix + str(int(days/30)) + ' months'
    elif days % 365 == 0:
        return prefix + str(int(days/365)) + ' years'
    else:
        return prefix + str(days) + ' days'

def graph(df, title, market_data):
    def annote(x,y, atype, ax=None):
        if atype == 'min':
            xpoint = x[np.argmin(y)]
            ypoint = y.min()
            text = f"Min {ypoint:.2f}\n{xpoint}"
            if ypoint < y.max()/4 or np.where(x == xpoint)[0] < np.size(x)*0.1:
                xytext = (50,50)
            else:
                xytext = (30,-30)
            if debug:
                print("Min", np.argmin(x), np.argmin(y), file=sys.stderr)
        elif atype == 'max':
            xpoint = x[np.argmax(y)]
            ypoint = y.max()
            text = f"Max {ypoint:.2f}\n{xpoint}"
            xytext=(50,50)
            if debug:
                print("Max", np.argmax(x), np.argmax(y), file=sys.stderr)
        elif atype == 'last':
            xpoint = x.iloc[-1]
            ypoint = y.iloc[-1]
            text = f"Last {ypoint:.2f}\n{xpoint}"
            xytext=(30,-30)
            if debug:
                print("Last", df.index[-1], df['Close'].index[-1], file=sys.stderr)
        if not ax:
            ax=plt.gca()
        bbox_props = dict(boxstyle="square,pad=0.3", fc="w", ec="k", lw=0.72)
        arrowprops=dict(arrowstyle="->",connectionstyle="angle,angleA=0,angleB=60")
        kw = dict(arrowprops=arrowprops, bbox=bbox_props, ha="right", va="top")
        #ax.annotate(text, xy=(mdates.date2num(xpoint), ypoint), xytext=xytext, textcoords='offset points', **kw)
        ax.annotate(text, xy=(xpoint, ypoint), xytext=xytext, textcoords='offset points', **kw)
        if atype == 'max':
            ax.set_ylim(top=ypoint+(ypoint/4))

    x = df['Date']
    y = df['Close']
    first = df['Close'].iloc[0]
    last = df['Close'].iloc[-1]
    if first > last:
        color = 'red' # red
    elif first < last:
        color = 'green' # green
    else:
        color = 'grey' # black if unchanged
    plt.title(title)
    plt.ylabel(market_data['currency'])
    df['Date'] = df['Date'].map(lambda x: datetime.datetime.strptime(str(x), '%Y-%m-%d'))
    plt.gcf().autofmt_xdate()
    plt.fill_between(x,y, color=color, alpha=0.3, linewidth=0.5)
    plt.plot(x,y, color=color, alpha=0.9, linewidth=0.7)
    plt.grid(color='grey', linestyle='-', alpha=0.4, linewidth=0.2)
    plt.box(False)
    plt.tight_layout()
    annote(x,y, atype='min')
    annote(x,y, atype='max')
    annote(x,y, atype='last')
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.clf()
    return buf

def get_emoji(number):
    if number > 0:
        #return '🔺'
        return '🔼'
    elif number < 0:
        return '🔻'
    else:
        return '▪️'

def days_from_human_days(arg):
    try:
        days = int(arg.removesuffix('d').removesuffix('D'))
    except ValueError:
        try:
            days = int(arg.removesuffix('w').removesuffix('W')) * 7
        except ValueError:
            try:
                days = int(arg.removesuffix('m').removesuffix('M')) * 30
            except ValueError:
                days = int(arg.removesuffix('y').removesuffix('Y')) * 365
    return days
