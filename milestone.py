#!/usr/bin/env python3

import sys
from itertools import groupby
from lib import config
from lib import state
from lib import webhook
from lib import util
from lib import yahoo

# BUGS:
# - need to handle stock splits: flush cache if we see a split in the data
# https://finance.yahoo.com/quote/TSLA/history?period1=0&period2=1707609600&filter=split

def lambda_handler():
	def prepare_milestone_payload(service, market_data):
		payload = []
		payloadhigh = []
		payloadlow = []
		records = state.load('finbot_milestone.json') or {}
		for ticker in tickers:
			try:
				oldhigh, oldlow = records[ticker]['record_high'], records[ticker]['record_low']
			except (KeyError, TypeError): # first sighting, or a record kept before records were all-time (52-week, under 'high'/'low')
				try:
					oldhigh, oldlow = yahoo.historic_high(ticker) # its history so far
				except (RuntimeError, KeyError, IndexError, ValueError):
					continue # no usable history: nothing recorded, so a later run cannot take zeros for its record
			try:
				newhigh = round(market_data[ticker]['fiftyTwoWeekHigh'], 2)
				newlow = round(market_data[ticker]['fiftyTwoWeekLow'], 2)
			except (KeyError, ValueError):
				continue # likewise: a ticker is recorded only with both of its new values
			title = market_data[ticker]['profile_title']
			ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
			emoji = util.flag_from_ticker(ticker)
			records[ticker] = {'record_high': max(oldhigh, newhigh), 'record_low': min(oldlow, newlow)} # all-time: a 52-week high below it is no record
			if newhigh > oldhigh:
				print("DEBUG", ticker, newhigh, "is higher than", oldhigh) if config.prefs.debug else None
				payloadhigh.append(f"{emoji} {title} ({ticker_link})")
			if newlow < oldlow:
				print("DEBUG", ticker, newlow, "is lower than", oldlow) if config.prefs.debug else None
				payloadlow.append(f"{emoji} {title} ({ticker_link})")
		payloadlow.sort()
		payloadhigh.sort()
		if payloadhigh:
			message = 'Record high:'
			message = webhook.bold(message, service)
			payload.append(message)
			payload = payload + payloadhigh
		if payloadlow:
			payload.append("")
			message = 'Record low:'
			message = webhook.bold(message, service)
			payload.append(message)
			payload = payload + payloadlow
		payload = [i[0] for i in groupby(payload)] # de-dupe white space
		return payload, records

	# MAIN #

	tickers = util.get_holdings_and_watchlist()
	market_data = yahoo.fetch(tickers)
	for service, url, chat in webhook.default_chats():
		payload, records = prepare_milestone_payload(service, market_data)
		webhook.send(service, url, chat, payload)

	if records:
		state.save('finbot_milestone.json', records)

def job(argv):
	return 'milestone.py', {}

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
