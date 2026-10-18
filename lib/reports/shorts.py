""".shorts: the most shorted stocks followed, from Short Man (ASX) and Yahoo (scheduled: shorts)."""
from lib import answer
from lib import config
from lib import delivery
from lib import formats
from lib import render
from lib import watchlist
from lib import yahoo
from lib import shortman

def run(chat, *, threshold=None, specific_stock=None):
	"""Post the stocks a chat follows whose short interest is over `threshold` percent (the shorts_percent setting
	when None), or one stock's (Yahoo's symbol), to the chat (a command's or a job's). Raises answer.Nothing where
	there are none."""
	if threshold is None:
		threshold = config.settings.shorts_percent
	tickers = watchlist.covered(chat.key, specific_stock)
	market_data = gather(tickers, specific_stock)
	delivery.deliver(chat, delivery.Report(*report(chat.dialect, tickers, market_data, threshold, specific_stock)))

def gather(tickers, specific_stock):
	"""The quotes of tickers (the stocks a chat follows, or the one asked about), with their short interest: Short Man
	has the ASX's figures, Yahoo's details the US's."""
	market_data = yahoo.fetch(tickers)
	market_data |= yahoo.fetch_details((ticker for ticker in tickers if '.' not in ticker), strict=bool(specific_stock))
	return shortman.fetch(market_data)

def report(service, tickers, market_data, threshold, specific_stock):
	"""(the report in one network's markup, its chart or None), the most shorted first. Raises answer.Nothing where
	none is."""
	found = [] # (percent, line, chart label)
	for ticker in tickers:
		try:
			short_percent = float(market_data[ticker]['short_percent'])
		except (KeyError, ValueError):
			continue
		if short_percent > threshold or specific_stock:
			code = ticker.split('.')[0]
			if ticker.endswith('.AX'):
				url = 'https://www.shortman.com.au/stock?q=' + code
			else:
				url = 'https://finance.yahoo.com/quote/' + ticker + '/key-statistics?p=' + ticker
			title = formats.short_name(market_data[ticker]['profile_title'])
			found.append((short_percent, f"🩳 {title} ({service.link(url, code)}) {round(short_percent)}%", code))
	found.sort(key=lambda row: row[0], reverse=True) # largest first, as the chart has them
	if not found and specific_stock:
		raise answer.Nothing(f"🩳 No short interest found for {tickers[0]}")
	if not found:
		raise answer.Nothing(f"🩳 No stocks shorted over {threshold:g}%. Try specifying a number.")
	lines = [line for _, line, _ in found]
	if specific_stock:
		return lines, None
	return [service.bold(f'Tracked stocks shorted over {threshold:g}%')] + lines, render.Chart('shorts',
		rows=tuple((code, percent) for percent, _, code in found), threshold=threshold)
