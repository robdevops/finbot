import sys
from lib.config import *
from lib import net

def fetch(market_data):
    local_market_data = market_data.copy()
    print("Fetching ASX shorts from Shortman")
    url = 'https://www.shortman.com.au/downloadeddata/latest.csv'
    try:
        r = net.get(url, timeout=config_http_timeout)
    except Exception as e:
        print("Failure fetching", url, net.redact(e), file=sys.stderr)
        return market_data # the ASX short interest is missing, the rest of the report is not
    if r.status_code == 200:
        print(r.status_code, "success shortman")
    else:
        print(r.status_code, "error communicating with", url, file=sys.stderr)
        return market_data
    csv = r.content.decode('utf-8')
    csv = csv.split('\r\n')
    csv.pop(0) # remove header
    del csv[-1] # remove junk
    for line in csv:
        cells = line.split(',') # title, code, positions, on issue, percent shorted
        ticker = cells[1] + '.AX'
        short_percent = float(cells[4]) # every row, so a malformed one still fails the fetch
        if ticker in market_data:
            local_market_data[ticker]['short_percent'] = short_percent
    return local_market_data
