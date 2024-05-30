#!/usr/bin/env python3

import googlesearch
import json
import time
import os

def get_symbols(file):
    symbols = []
    with open(file) as file:
        while line := file.readline():
            symbol = line.rstrip()
            symbols.append(symbol)
    return symbols

def get_sws(symbol, market):
    query = "site:simplywall.st " + market + " " + symbol + " Stock Price, News & Analysis"
    url = googlesearch.lucky(query)
    print(symbol, url)
    return url

def build_dict(symbols, market):
    count=1
    mydict = {}
    for symbol in symbols:
        if count % 40 == 0:
            print("Sleeping for 30 minutes")
            time.sleep(30 * 60)
        count = count + 1
        url = get_sws(symbol, market)
        if market == 'ASX':
            symbol = symbol + '.' + 'AX'
        mydict[symbol] = url
    return mydict

def do_sws_bulk(file):
    market = ''
    if 'asx' in file or 'ASX' in file:
        market = 'ASX'
    symbols = get_symbols(file)
    mydict = build_dict(symbols, market)
    cache_file = 'finbot_sws_' + file.split('.')[0] + '.json'
    write_cache(mydict, cache_file)
    return mydict

def write_cache(mydict, cache_file):
    os.umask(0)
    def opener(path, flags):
        return os.open(path, flags, 0o640)
    with open(cache_file, "w", opener=opener, encoding="utf-8") as f:
        f.write(json.dumps(mydict))
    os.umask(0o022)

files = ['nasdaq100', 'sp500', 'asx200'] 
for idx, file in enumerate(files):
    print("Starting", file)
    mydict = do_sws_bulk(file)
    print("Completed", file, "as finbot_sws_" + file.split('.')[0] + ".json")
    if idx + 1 < len(files):
        print("Sleeping for 15 minutes")
        time.sleep(15 * 60)

