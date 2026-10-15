""".earnings and .dividend: upcoming earnings and ex-dividend dates (scheduled: cal.py earnings | ex-dividend)."""
import datetime
import sys

from lib import config
from lib import telegram
from lib import formats
from lib import links
from lib import markets
from lib import watchlist
from lib import webhook
from lib import yahoo

def primary_listings():
	"""{ADR or second listing: its primary listing}, from finbot_adr.json: read when used, so an edit is seen without a restart."""
	return config.data_json('finbot_adr.json', {})

EVENTS = {'earnings': ('earnings_date', 'Upcoming earnings'), 'ex-dividend': ('ex_dividend_date', 'Upcoming ex-dividends')} # -> (field, heading)

def lambda_handler(chat_id=None, days=None, service=None, specific_stock=None, interactive=False, event='earnings'):
	"""The tracked stocks' (or one stock's) upcoming earnings or ex-dividend dates, as `event` says. A scheduled earnings report
	is pinned on Telegram."""
	if days is None:
		days = config.prefs.future_days
	field, heading = EVENTS[event]
	def prepare_payload(service, market_data):
		"""The report in one network's markup: the events within `days`, grouped by date. An ADR or a second listing
		without a date of its own takes its primary listing's."""
		now = datetime.datetime.now()
		soon = now + datetime.timedelta(days=days)
		found = [] # (when, flag, title, link)
		for ticker in list(market_data):
			if market_data[ticker]['quoteType'] == 'ETF':
				continue
			ticker_primary = ticker
			if field not in market_data[ticker]: # an ADR or a second listing: its primary listing may have the date
				title_orig = market_data[ticker]['profile_title']
				if ticker in primary_listings():
					ticker_primary = primary_listings()[ticker]
				elif ticker.endswith('.AX') and market_data[ticker].get('financialCurrency') == 'NZD':
					ticker_primary = ticker.replace('.AX', '.NZ') # fixes GTK.AX and SKO.AX
				market_data = market_data | yahoo.fetch_detail(ticker_primary)
				country = market_data.get(ticker_primary, {}).get('profile_country') # only in the details
				if country in markets.YAHOO_COUNTRY and '.' not in ticker_primary:
					ticker_primary = ticker_primary + '.' + markets.YAHOO_COUNTRY[country] # fixes ASML and INFY
					market_data = market_data | yahoo.fetch_detail(ticker_primary)
				primary = market_data.get(ticker_primary, {})
				if primary.get('profile_title') != title_orig or field not in primary: # not the same company, or no date there either
					continue
			when = datetime.datetime.fromtimestamp(market_data[ticker_primary][field])
			if now < when < soon or specific_stock:
				found.append((when, markets.flag_from_ticker(ticker_primary), market_data[ticker]['profile_title'], links.yahoo_link(ticker, service)))
		found.sort(key=lambda item: item[0])
		payload = []
		for date in sorted({when.date() for when, *_ in found}):
			if not specific_stock:
				payload += ["", service.bold(f"{date:%b %d}")]
			for when, flag, title, link in found:
				if when.date() == date:
					payload.append(f"{flag} {date:%b %d} {title} ({link})" if specific_stock else f"{flag} {title} ({link})")
		if payload and not specific_stock:
			payload.insert(0, service.bold(f"{heading} {formats.days_english(days, 'for the next ')}:"))
		elif not payload and interactive:
			payload = [f"No events found for {tickers[0]}" if specific_stock else f"No events found {formats.days_english(days, 'for the next ')}"]
		return payload

	def pin_if_earnings(service, results):
		"""Pin every message of the Telegram earnings report (several if it was chunked)."""
		if not (event == 'earnings' and not specific_stock and service == 'telegram' and results):
			return
		sent = []
		for result in results:
			try:
				sent.append((result['result']['chat']['id'], result['result']['message_id']))
			except (KeyError, TypeError):
				print("Unable to pin: unexpected response", file=sys.stderr)
		for chat, message_id in reversed(sent): # pin last-to-first so the report's first message ends up on top
			telegram.pinChatMessage(chat, message_id)

	# MAIN #
	tickers = [markets.transform_to_yahoo(specific_stock)] if specific_stock else watchlist.with_holdings()
	if event == 'earnings':
		market_data = yahoo.fetch(tickers)
	else: # ex-dividend dates are in Yahoo's details
		market_data = yahoo.fetch_details(tickers, strict=bool(specific_stock))

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		pin_if_earnings(service, webhook.send(service, url, chat, prepare_payload(service, market_data)))

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case ['earnings' | 'ex-dividend' as event]:
			return f'cal.py {event}', {'event': event}
		case _:
			raise ValueError('[earnings|ex-dividend]')
