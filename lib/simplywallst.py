from urllib.parse import quote_plus

from lib import config

# the first to list a ticker wins
FILES = ['finbot_sws_custom.json', 'finbot_sws_asx200.json', 'finbot_sws_sp500.json', 'finbot_sws_nasdaq100.json']

def get_url(symbol, name, exchange):
	"""The ticker's page on simplywall.st, from the lists in FILES; without one, a search that lands on it."""
	for file in FILES:
		url = config.data_json(file, {}).get(symbol)
		if url:
			return url
	query = quote_plus(f"site:simplywall.st ({name} {exchange}:{symbol.split('.')[0]}) Stock", safe=':()')
	return 'https://www.google.com/search?q=' + query + '&btnI'

