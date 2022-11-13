#!/usr/bin/python3

import json, os, time, re
import datetime
#from dotenv import load_dotenv
import pytz
import requests
from bs4 import BeautifulSoup

from lib.config import *
import lib.util as util

time_now = datetime.datetime.today()
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20

def fetch(chunk):
    finviz_output = {}
    chunk_string=','.join(chunk)
    url = 'https://finviz.com/screener.ashx?v=150&c=0,1,2,30,66,68,14&t=' + chunk_string
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=config_http_timeout)
    if r.status_code == 200:
        print(r.status_code, "success finviz chunk")
    else:
        print(r.status_code, "error finviz chunk")
    soup = BeautifulSoup(r.content, "html.parser")
    main_div = soup.find('div', attrs={'id': 'screener-content'})
    table = main_div.find('table')
    sub = table.findAll('tr')
    rows = sub[5].findAll("tr")
    rows = rows[0].findAll("tr")
    for row in rows:
        item = row.findAll('a')
        count = item[0].text
        ticker = item[1].text
        title = item[2].text
        title = util.transform_title(title)
        percent_short = item[3].text.replace('%', '') # FIX python 3.9
        percent_change = item[4].text.replace('%', '')
        earnings_date = item[5].text
        dividend = item[6].text.replace('%', '')
        try:
            percent_short = float(percent_short)
        except ValueError:
            percent_short = float(0)
        try:
            percent_change = float(percent_change)
        except ValueError:
            percent_change = float(0)
        try:
            dividend = float(dividend)
        except ValueError:
            dividend = float(0)
        finviz_output[ticker] = { 'ticker': ticker, 'title': title, 'percent_change': percent_change, 'earnings_date': earnings_date, 'percent_short': percent_short, 'dividend': dividend}
    return finviz_output

def wrapper(tickers_us):
    finviz_output = {}
    chunks = util.chunker(tickers_us, 20)
    print("Fetching", len(tickers_us), "holdings from Finviz")
    for chunk in chunks:
        finviz_output = {**finviz_output, **fetch(chunk)} # FIX python 3.9
    return finviz_output

