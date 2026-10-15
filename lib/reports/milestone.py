"""Record highs and lows (all-time) among the stocks followed (scheduled: milestone.py)."""
from itertools import groupby
from lib import state
from lib import delivery
from lib import links
from lib import watchlist
from lib import yahoo

# BUGS:
# - need to handle stock splits: flush cache if we see a split in the data
# https://finance.yahoo.com/quote/TSLA/history?period1=0&period2=1707609600&filter=split

STATE_FILE = 'finbot_milestone.json' # {ticker: {'record_high': ..., 'record_low': ...}}

def run(dest=None):
	"""Post the stocks followed that set an all-time high or low to the default chats (or dest), and record the new
	records."""
	market_data, highs, lows, changed = gather()
	for chat in delivery.targets(dest):
		delivery.deliver(chat, delivery.Report(report(chat.dialect, market_data, highs, lows)))
	if changed:
		with state.edit(STATE_FILE, {}) as recorded:
			recorded.update(changed)

def gather():
	"""(the quotes, the tickers at a record high, those at a record low, {ticker: its records after this run}) of the
	stocks followed: each one's 52-week range against its all-time record, which a first sighting takes from its
	history."""
	tickers = watchlist.with_holdings()
	market_data = yahoo.fetch(tickers)
	records = state.load(STATE_FILE, {})
	highs, lows, changed = [], [], {}
	for ticker in tickers:
		try:
			oldhigh, oldlow = records[ticker]['record_high'], records[ticker]['record_low']
		except (KeyError, TypeError): # first sighting, or a 52-week record of old, under 'high' and 'low'
			try:
				oldhigh, oldlow = yahoo.historic_high(ticker) # its history so far
			except (RuntimeError, KeyError, IndexError, ValueError):
				continue # no usable history: nothing recorded, so a later run cannot take zeros for its record
		try:
			newhigh = round(market_data[ticker]['fiftyTwoWeekHigh'], 2)
			newlow = round(market_data[ticker]['fiftyTwoWeekLow'], 2)
		except (KeyError, ValueError):
			continue # likewise: a ticker is recorded only with both of its new values
		# all-time: a 52-week high below the record is no record
		changed[ticker] = {'record_high': max(oldhigh, newhigh), 'record_low': min(oldlow, newlow)}
		if newhigh > oldhigh:
			highs.append(ticker)
		if newlow < oldlow:
			lows.append(ticker)
	return market_data, highs, lows, changed

def report(service, market_data, highs, lows):
	"""The records in one network's markup: the record highs, then the record lows, each list sorted."""
	def line(ticker):
		"""A stock's flag, name and link."""
		return links.stock_line(ticker, market_data[ticker], service)
	payload = []
	if highs:
		payload += [service.bold('Record high:')] + sorted(line(ticker) for ticker in highs)
	if lows:
		payload += ["", service.bold('Record low:')] + sorted(line(ticker) for ticker in lows)
	return [i[0] for i in groupby(payload)] # de-dupe white space

def job(argv):
	"""Arguments of a scheduled run: milestone.py takes none."""
	return 'milestone.py', {}
