"""The watchlist: tickers followed beside the Sharesight holdings, in DATA_DIR/finbot_watchlist.json. Every call reads
the file, so the bot and its scheduled reports (other processes) always see the same list."""
from lib import config
from lib import markets
from lib import sharesight
from lib import state

FILE = 'finbot_watchlist.json'


def tickers():
	"""The watched tickers, in the order they were added."""
	return state.load(FILE, [])


def watched(typed):
	"""The watched ticker that a ticker as written names: BHP.AX as written, or BHP on the local exchange (the
	exchange_suffix preference) when only BHP.AX is watched; else Yahoo's spelling of what was written. Yahoo is not
	asked, so a ticker it no longer knows can still be removed."""
	ticker = markets.transform_to_yahoo(typed.upper())
	local = f'{ticker}.{config.prefs.exchange_suffix}'
	if ticker not in tickers() and config.prefs.exchange_suffix and '.' not in ticker and local in tickers():
		return local
	return ticker


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


def covered(ticker=None):
	"""The tickers a report covers: the one asked about, else every stock followed (with_holdings)."""
	return [ticker] if ticker else with_holdings()


def with_holdings():
	"""The watchlist and every Sharesight holding: the tickers the scheduled reports cover, sorted."""
	followed = set(sharesight.tickers()) | set(tickers())
	if 'GOOG' in followed and 'GOOGL' in followed:
		followed.remove("GOOGL")
	return sorted(followed)
