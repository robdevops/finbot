"""Links to a stock's page on Yahoo or Google Finance, in the markup of `service` (a dialect: see lib/dialects.py)."""
from lib import config
from lib import markets

def yahoo_link(ticker, service, brief=True, text=None):
	if not text:
		text = ticker.split('.')[0] if brief else ticker
	return service.link("https://au.finance.yahoo.com/quote/" + ticker, text)

def finance_link(symbol, exchange, service, days=1, brief=True, text=None):
	if config.prefs.hyperlinkProvider == 'google':
		return gfinance_link(symbol, exchange, service, days, brief, text)
	return yahoo_link(symbol, service, brief, text)

def quote_link(ticker, exchange, service, days=1):
	"""finance_link, but to Yahoo for what Google Finance has no page for: Taipei Exchange, crypto (CCC) and indices (^)."""
	if exchange in ('Taipei Exchange', 'CCC') or ticker.startswith('^'):
		return yahoo_link(ticker, service)
	return finance_link(ticker, exchange, service, days=days)

def gfinance_link(symbol, exchange, service, days=1, brief=True, text=None):
	window = '1D'
	if not days:
		days = 1
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
	exchange = markets.transform_to_google(exchange)
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
	if config.prefs.hyperlink:
		return service.link(url + ticker + '?window=' + window, text)
	return symbol
