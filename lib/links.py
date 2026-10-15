"""Links to a stock's page on Yahoo or Google Finance, in the markup of `service` (a dialect: see lib/dialects.py)."""
from lib import config
from lib import markets

NO_GOOGLE_PAGE = ('Taipei Exchange', 'CCC') # exchanges Google Finance has no pages for (CCC: crypto), nor indices (^)
WINDOWS = ((1825, 'Max'), (365, '5Y'), (183, '1Y'), (31, '6M'), (7, '1M'), (1, '5D')) # over that many days, that window

def yahoo_link(ticker, service, brief=True, text=None):
	"""A link to the ticker's Yahoo Finance page reading `text`, else the bare symbol (brief) or the whole ticker."""
	if not text:
		text = ticker.split('.')[0] if brief else ticker
	return service.link("https://au.finance.yahoo.com/quote/" + ticker, text)

def finance_link(symbol, exchange, service, days=1, brief=True, text=None):
	"""A link to the stock's page on the site hyperlinkProvider names, Google Finance (google) or Yahoo, and on Yahoo
	for what Google has no page for (NO_GOOGLE_PAGE, indices)."""
	if config.prefs.hyperlinkProvider == 'google' and exchange not in NO_GOOGLE_PAGE and not symbol.startswith('^'):
		return gfinance_link(symbol, exchange, service, days, brief, text)
	return yahoo_link(symbol, service, brief, text)

def gfinance_link(symbol, exchange, service, days=1, brief=True, text=None):
	"""A link to the stock's Google Finance page, its chart window the one nearest to `days`, reading `text`, else the
	symbol (brief) or SYMBOL:EXCHANGE (a US listing: the symbol). Just that text with the hyperlink preference off."""
	window = next((window for limit, window in WINDOWS if (days or 1) > limit), '1D')
	if '.' in exchange:
		exchange = exchange.split('.')[1]
	exchange = markets.transform_to_google(exchange)
	symbol_short = symbol.replace(':', '.').split('.')[0]
	symbol_short = symbol_short.replace('-', '.') # class shares e.g. BRK.A
	ticker = symbol_short + ':' + exchange
	if brief and not text:
		text = symbol_short
	elif not text:
		text = ticker if '.' in symbol else symbol # a US listing: the symbol
	return service.link("https://www.google.com/finance/quote/" + ticker + '?window=' + window, text)
