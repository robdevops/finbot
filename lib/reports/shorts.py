""".shorts: the most shorted stocks followed, from Short Man (ASX) and Yahoo (scheduled: shorts)."""
from lib import config
from lib import delivery
from lib import formats
from lib import render
from lib import watchlist
from lib import yahoo
from lib import shortman

def run(dest=None, *, threshold=None, specific_stock=None):
	"""Post the stocks a chat follows whose short interest is over `threshold` percent (the shorts_percent setting
	when None), or one stock's (Yahoo's symbol): to the chat that asked or whose job it is (dest)."""
	interactive = delivery.interactive(dest)
	if threshold is None:
		threshold = config.settings.shorts_percent
	for chat in delivery.targets(dest):
		tickers = watchlist.covered(chat.key, specific_stock)
		market_data = gather(tickers, specific_stock)
		payload, graph = report(chat.dialect, tickers, market_data, threshold, specific_stock, interactive)
		delivery.deliver(chat, delivery.Report(payload, graph))

def gather(tickers, specific_stock):
	"""The quotes of tickers (the stocks a chat follows, or the one asked about), with their short interest: Short Man
	has the ASX's figures, Yahoo's details the US's."""
	market_data = yahoo.fetch(tickers)
	market_data |= yahoo.fetch_details((ticker for ticker in tickers if '.' not in ticker), strict=bool(specific_stock))
	return shortman.fetch(market_data)

def report(service, tickers, market_data, threshold, specific_stock, interactive):
	"""(the report in one network's markup, its chart or None), the most shorted first."""
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
	payload, graph = [line for _, line, _ in found], None
	if payload and not specific_stock:
		payload.insert(0, service.bold(f'Tracked stocks shorted over {threshold:g}%'))
		graph = render.Chart('shorts', rows=tuple((code, percent) for percent, _, code in found), threshold=threshold)
	elif not payload and interactive:
		if specific_stock:
			payload = [f"🩳 No short interest found for {tickers[0]}"]
		else:
			payload = [f"🩳 No stocks shorted over {threshold:g}%. Try specifying a number."]
	return payload, graph

ARGUMENTS = '' # what a scheduled run takes: none

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); shorts takes none, and an argument raises
	ValueError."""
	if argv:
		raise ValueError('no arguments')
	return 'shorts', {}
