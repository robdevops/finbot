from lib import log
from lib import net

def fetch(market_data):
	"""market_data with each ASX ticker's short interest added from Short Man's daily CSV (as it was if unreachable)."""
	url = 'https://www.shortman.com.au/downloadeddata/latest.csv'
	try:
		r = net.get(url)
	except Exception as e:
		log.warn("Failure fetching", url, net.redact(e))
		return market_data # the ASX short interest is missing, the rest of the report is not
	if r.status_code != 200:
		log.warn(r.status_code, "error communicating with", url)
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
			market_data[ticker]['short_percent'] = short_percent
	return market_data
