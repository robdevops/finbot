import json
import requests
from lib.config import *

def fetch(market_data):
    local_market_data = market_data.copy()
    print("Fetching ASX shorts from Shortman")
    content = {}
    url = 'https://www.shortman.com.au/downloadeddata/latest.csv'
    try:
        r = requests.get(url, timeout=config_http_timeout)
    except:
        print("Failure fetching", url)
        return {}
    if r.status_code == 200:
        print(r.status_code, "success shortman")
    else:
        print(r.status_code, "error communicating with", url)
        return {}
    csv = r.content.decode('utf-8')
    csv = csv.split('\r\n')
    csv.pop(0) # remove header
    del csv[-1] # remove junk
    for line in csv:
        cells = line.split(',')
        title = cells[0]
        ticker = cells[1] + '.AX'
        positions = cells[2]
        on_issue = cells[3]
        short_percent = cells[4]
        content[ticker] = float(short_percent)
        if ticker in market_data:
            local_market_data[ticker]['short_percent'] = float(short_percent)
    return local_market_data
