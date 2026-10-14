"""The watchlist: tickers followed beside the Sharesight holdings, in DATA_DIR/finbot_watchlist.json. Every call reads the file,
so the bot and its scheduled reports (other processes) always see the same list."""
from lib import state
from lib import yahoo

FILE = 'finbot_watchlist.json'


def tickers():
	"""The watched tickers, in the order they were added."""
	return state.load(FILE, [])


def find(ticker):
	"""(ticker, its Yahoo quote) for a ticker Yahoo knows, tried on the ASX when a bare symbol is unknown (BHP: BHP.AX); the
	quote is None when Yahoo knows neither."""
	ticker, found = yahoo.resolve(ticker, lambda symbol: yahoo.fetch([symbol]))
	return ticker, found.get(ticker)


def add(ticker):
	"""Watch a ticker (check it with find first). False when it was already watched."""
	with state.edit(FILE, []) as watched:
		if ticker in watched:
			return False
		watched.append(ticker)
	return True


def remove(ticker):
	"""Stop watching a ticker. False when it was not watched."""
	with state.edit(FILE, []) as watched:
		if ticker not in watched:
			return False
		watched.remove(ticker)
	return True
