"""Short Man's daily short interest of ASX stocks (shortman.com.au): its CSV, cached as sent."""
import csv
import io

from lib import cache
from lib import log
from lib import net

URL = 'https://www.shortman.com.au/downloadeddata/latest.csv'
CACHE = 'finbot_shortman.json' # the CSV as sent, a day's figures: good for the cache_seconds setting

def fetch(market_data):
	"""market_data with each ASX ticker's short interest added from Short Man's daily CSV (as it was where Short Man
	cannot be had); a row that is not a stock's is left out, with a warning."""
	try:
		text = cache.cached(CACHE, None, _csv)
	except RuntimeError as e:
		log.warn(e)
		return market_data # the ASX short interest is missing, the rest of the report is not
	rows = csv.reader(io.StringIO(text))
	next(rows, None) # the header
	for row in filter(None, rows): # title, code, positions, on issue, percent shorted
		try:
			ticker, percent = row[1] + '.AX', float(row[4])
		except (IndexError, ValueError):
			log.warn("Short Man: a row that is not a stock's:", log.cut(','.join(row)))
			continue
		if ticker in market_data:
			market_data[ticker]['short_percent'] = percent
	return market_data

def _csv():
	"""Short Man's CSV, as sent. Raises RuntimeError when it cannot be had."""
	r = net.answer('Short Man', 'short interest', URL)
	if r.status_code != 200:
		raise RuntimeError(f"Short Man short interest: a {r.status_code} answer")
	return r.content.decode('utf-8')
