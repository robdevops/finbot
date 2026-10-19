"""The watchlist: each chat's tickers followed beside the Sharesight holdings, in DATA_DIR/finbot_watchlist.json, by
the chat's key ({'chats': {chat key: [tickers]}}, as state.load_for keeps it). Every call reads the file, so every
thread sees the same lists. The holdings are the same for every chat: a portfolio is not a chat's."""
from lib import config
from lib import markets
from lib import sharesight
from lib import state

FILE = 'finbot_watchlist.json'


def tickers(chat):
	"""A chat's watched tickers (by its key), in the order they were added."""
	return state.load_for(chat, FILE, [])


def watched(chat, typed):
	"""The ticker of a chat's watchlist that a ticker as written names: BHP.AX as written, or BHP on the local exchange
	(the exchange_suffix setting) when only BHP.AX is watched; else Yahoo's spelling of what was written. Yahoo is
	not asked, so a ticker it no longer knows can still be removed."""
	ticker, watching = markets.transform_to_yahoo(typed.upper()), tickers(chat)
	local = f'{ticker}.{config.settings.exchange_suffix}'
	if ticker not in watching and config.settings.exchange_suffix and '.' not in ticker and local in watching:
		return local
	return ticker


def add(chat, ticker):
	"""Add a ticker to a chat's watchlist (check it with find first). False when it was there already."""
	with state.edit_for(chat, FILE, []) as watching:
		if ticker in watching:
			return False
		watching.append(ticker)
	return True


def remove(chat, ticker):
	"""Take a ticker off a chat's watchlist. False when it was not on it."""
	with state.edit_for(chat, FILE, []) as watching:
		if ticker not in watching:
			return False
		watching.remove(ticker)
	return True


def covered(chat, ticker=None):
	"""The tickers a report covers in a chat: the one asked about, else every stock the chat follows (with_holdings)."""
	return [ticker] if ticker else with_holdings(chat)


def with_holdings(chat):
	"""A chat's watchlist and every Sharesight holding: the tickers its reports cover, sorted."""
	return _followed(tickers(chat))


def all_watched():
	"""Every chat's watched tickers, each once, sorted."""
	return sorted({ticker for watching in state.records(FILE).values() for ticker in watching})


def all_followed():
	"""Every chat's watchlist and every Sharesight holding, sorted: what yahoo_warm keeps warm."""
	return _followed(all_watched())


def _followed(watching):
	"""The holdings and the tickers watched, sorted; GOOGL left out beside GOOG, its other class of shares."""
	followed = set(sharesight.tickers()) | set(watching)
	if 'GOOG' in followed and 'GOOGL' in followed:
		followed.remove("GOOGL")
	return sorted(followed)
