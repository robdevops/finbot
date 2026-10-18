"""Record highs and lows (all-time) among the stocks followed (scheduled: milestone)."""
from lib import answer
from lib import state
from lib import delivery
from lib import formats
from lib import links
from lib import watchlist
from lib import yahoo

STATE_FILE = 'finbot_milestone.json' # each chat's {ticker: {'all_time_high': ..., 'all_time_low': ...}}

def run(chat):
	"""Post the stocks a chat follows that set an all-time high or low, against its record, to the job's chat, and
	record the chat's new records. Raises answer.Nothing, once they are recorded, where none set one."""
	tickers = watchlist.with_holdings(chat.key)
	market_data = yahoo.fetch(tickers)
	highs, lows, changed = compare(tickers, market_data, state.load_for(chat.key, STATE_FILE, {}))
	payload = report(chat.dialect, market_data, highs, lows)
	if payload:
		delivery.deliver(chat, delivery.Report(payload))
	if changed:
		with state.edit_for(chat.key, STATE_FILE, {}) as recorded:
			recorded.update(changed)
	if not payload:
		raise answer.Nothing("No new record highs or lows")

def compare(tickers, market_data, records):
	"""(the tickers at a record high, those at a record low, {ticker: its records after this run}): each one's 52-week
	range (market_data, the quotes) against its all-time record in a chat's records, which a first sighting takes from
	its history."""
	highs, lows, changed = [], [], {}
	for ticker in tickers:
		try:
			oldhigh, oldlow = records[ticker]['all_time_high'], records[ticker]['all_time_low']
		except (KeyError, TypeError): # first sighting, or a record of old: 52 weeks (high, low), 10 years (record_high)
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
		changed[ticker] = {'all_time_high': max(oldhigh, newhigh), 'all_time_low': min(oldlow, newlow)}
		if newhigh > oldhigh:
			highs.append(ticker)
		if newlow < oldlow:
			lows.append(ticker)
	return highs, lows, changed

def report(service, market_data, highs, lows):
	"""The records in one network's markup: the record highs, then the record lows, each list sorted."""
	def line(ticker):
		"""A stock's flag, name and link."""
		return links.stock_line(ticker, market_data[ticker], service)
	return formats.sections(highs and [service.bold('Record high:')] + sorted(line(ticker) for ticker in highs),
		lows and [service.bold('Record low:')] + sorted(line(ticker) for ticker in lows))
