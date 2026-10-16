""".earnings and .dividend: upcoming earnings and ex-dividend dates (scheduled: cal earnings | ex-dividend)."""
import datetime

from lib import config
from lib import formats
from lib import links
from lib import markets
from lib import watchlist
from lib import delivery
from lib import yahoo

def primary_listings():
	"""{ADR or second listing: its primary listing}, from finbot_adr.json, read when used: an edit needs no restart."""
	return config.data_json('finbot_adr.json', {})

EVENTS = {'earnings': ('earnings_date', 'Upcoming earnings'),
	'ex-dividend': ('ex_dividend_date', 'Upcoming ex-dividends')} # -> (field, heading)

def run(dest=None, *, days=None, specific_stock=None, event='earnings'):
	"""Post the earnings or ex-dividend dates ahead (`event`) for the stocks a chat follows or one (Yahoo's symbol): to
	the chat that asked or whose job it is (dest). The scheduled earnings report is pinned where
	the network can; a reply is not, or the chat would collect pinned copies."""
	interactive = delivery.interactive(dest)
	if days is None:
		days = config.prefs.future_days
	for chat in delivery.targets(dest):
		events = gather(watchlist.covered(chat.key, specific_stock), days, specific_stock, event)
		payload = report(chat.dialect, events, days, specific_stock, interactive, event)
		answers = delivery.deliver(chat, delivery.Report(payload))
		if event == 'earnings' and not specific_stock and not interactive and hasattr(chat, 'pin'):
			chat.pin(answers) # the scheduled earnings report stays on top, where the network can pin

def gather(tickers, days, specific_stock, event):
	"""The dates of `event` within `days` (any date for one stock), soonest first: [(when, flag, title, ticker)]. ETFs
	are left out; an ADR or a second listing without a date of its own takes its primary listing's."""
	field = EVENTS[event][0]
	if event == 'earnings':
		market_data = yahoo.fetch(tickers)
	else: # ex-dividend dates are in Yahoo's details
		market_data = yahoo.fetch_details(tickers, strict=bool(specific_stock))
	now = datetime.datetime.now()
	soon = now + datetime.timedelta(days=days)
	found = []
	for ticker, data in market_data.items():
		if data['quoteType'] == 'ETF':
			continue
		primary, dated = (ticker, data) if field in data else primary_listing(ticker, data, field)
		if primary is None:
			continue
		when = datetime.datetime.fromtimestamp(dated[field])
		if now < when < soon or specific_stock:
			found.append((when, markets.flag_from_ticker(primary), data['profile_title'], ticker))
	return sorted(found, key=lambda item: item[0])

def primary_listing(ticker, data, field):
	"""(a listing's ticker, its Yahoo details) with a `field` that a ticker's quote lacks, or (None, None). The ticker's
	own details: what is held is that listing, so its own date counts, and a foreign company's US listing (ARM, CLBT)
	is never swapped for its home market's (ARM.L, CLBT.TA). Only when it has none, the listing that finbot_adr.json
	names, or the NZX's for an ASX ticker reporting in NZD (GTK.AX, SKO.AX)."""
	own = yahoo.fetch_detail(ticker).get(ticker, {})
	listings = [ticker]
	if mapped := primary_listings().get(ticker):
		listings.append(mapped)
	elif ticker.endswith('.AX') and data.get('financialCurrency') == 'NZD':
		listings.append(ticker.replace('.AX', '.NZ'))
	for listing in listings:
		details = own if listing == ticker else yahoo.fetch_detail(listing).get(listing, {})
		if details.get('profile_title') == data['profile_title'] and field in details: # the same company, with a date
			return listing, details
	return None, None

def report(service, events, days, specific_stock, interactive, event):
	"""The events in one network's markup, grouped by date under a heading (one stock's carry their dates instead)."""
	heading = EVENTS[event][1]
	blocks = []
	for date in sorted({when.date() for when, *_ in events}):
		day = f"{date:%b %d} " if specific_stock else '' # one stock's events carry their date
		lines = [f"{flag} {day}{formats.short_name(title)} ({links.yahoo_link(ticker, service)})"
			for when, flag, title, ticker in events if when.date() == date]
		blocks.append(lines if specific_stock else [service.bold(f"{date:%b %d}")] + lines)
	payload = sum(blocks, []) if specific_stock else formats.sections(*blocks)
	if payload and not specific_stock:
		payload = formats.sections([service.bold(f"{heading} {formats.days_english(days, 'for the next ')}:")], payload)
	elif not payload and interactive:
		ahead = formats.days_english(days, 'for the next ')
		payload = [f"No events found for {specific_stock}" if specific_stock else f"No events found {ahead}"]
	return payload

ARGUMENTS = 'earnings|ex-dividend' # what a scheduled run takes

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case ['earnings' | 'ex-dividend' as event]:
			return f'cal {event}', {'event': event}
		case _:
			raise ValueError(ARGUMENTS)
