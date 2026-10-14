#!/usr/bin/env python3

import datetime
import sys

from lib.config import *
from lib import telegram
from lib import util
from lib import webhook
from lib import yahoo

EVENTS = {'earnings': ('earnings_date', 'Upcoming earnings'), 'ex-dividend': ('ex_dividend_date', 'Upcoming ex-dividends')} # -> (field, heading)

def lambda_handler(chat_id=config_telegramChatID, days=UNSET, service=None, specific_stock=None, message_id=None, interactive=False, event='earnings'):
	"""The tracked stocks' (or one stock's) upcoming earnings or ex-dividend dates, as `event` says. A scheduled earnings report
	is pinned on Telegram."""
	if days is UNSET:
		days = config_future_days
	field, heading = EVENTS[event]
	def prepare_payload(service, market_data):
		now = datetime.datetime.now()
		soon = now + datetime.timedelta(days=days)
		found = [] # (when, flag, title, link)
		for ticker in list(market_data):
			if market_data[ticker]['quoteType'] == 'ETF':
				continue
			ticker_primary = ticker
			if field not in market_data[ticker]: # an ADR or a second listing: its primary listing may have the date
				title_orig = market_data[ticker]['profile_title']
				if ticker in primary_listing: # dict from lib.config
					ticker_primary = primary_listing[ticker]
				elif ticker.endswith('.AX') and market_data[ticker].get('financialCurrency') == 'NZD':
					ticker_primary = ticker.replace('.AX', '.NZ') # fixes GTK.AX and SKO.AX
				market_data = market_data | yahoo.fetch_detail(ticker_primary)
				country = market_data.get(ticker_primary, {}).get('profile_country') # only in the details
				if country in yahoo_country and '.' not in ticker_primary: # dict from lib.config
					ticker_primary = ticker_primary + '.' + yahoo_country[country] # fixes ASML and INFY
					market_data = market_data | yahoo.fetch_detail(ticker_primary)
				primary = market_data.get(ticker_primary, {})
				if primary.get('profile_title') != title_orig or field not in primary: # not the same company, or no date there either
					continue
			when = datetime.datetime.fromtimestamp(market_data[ticker_primary][field])
			if now < when < soon or specific_stock:
				found.append((when, util.flag_from_ticker(ticker_primary), market_data[ticker]['profile_title'], util.yahoo_link(ticker, service)))
		found.sort(key=lambda item: item[0])
		payload = []
		for date in sorted({when.date() for when, *_ in found}):
			if not specific_stock:
				payload += ["", webhook.bold(f"{date:%b %d}", service)]
			for when, flag, title, link in found:
				if when.date() == date:
					payload.append(f"{flag} {date:%b %d} {title} ({link})" if specific_stock else f"{flag} {title} ({link})")
		if payload and not specific_stock:
			payload.insert(0, webhook.bold(f"{heading} {util.days_english(days, 'for the next ')}:", service))
		elif not payload and interactive:
			payload = [f"No events found for {tickers[0]}" if specific_stock else f"No events found {util.days_english(days, 'for the next ')}"]
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
	tickers = [util.transform_to_yahoo(specific_stock)] if specific_stock else util.get_holdings_and_watchlist()
	if event == 'earnings':
		market_data = yahoo.fetch(tickers)
	else: # ex-dividend dates are in Yahoo's details
		market_data = yahoo.fetch_details(tickers, strict=bool(specific_stock))
		print("")

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		pin_if_earnings(service, webhook.send(service, url, chat, prepare_payload(service, market_data), message_id=message_id))

	# make google cloud happy
	return True

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case ['earnings' | 'ex-dividend' as event]:
			return f'cal.py {event}', {'event': event}
		case _:
			raise ValueError('[earnings|ex-dividend]')

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
