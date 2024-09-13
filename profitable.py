#!/usr/bin/env python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

# BUGS:
# - need to handle stock splits: flush cache if we see a split in yahoo
# https://finance.yahoo.com/quote/TSLA/history?period1=0&period2=1707609600&filter=split

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
	def prepare_ath_payload(service, market_data):
		emoji = '⭐'
		payload = []
		payloadhigh = []
		payloadlow = []
		oldhigh = float()
		oldlow = float()
		records = util.json_load('finbot_ath.json', persist=True)
		if records is None:
			records = {}
		for ticker in tickers:
			try:
				oldhigh = records[ticker]['high']
				oldlow = records[ticker]['low']
			except (KeyError, TypeError):
				records[ticker] = {}
				records[ticker]['high'] = float()
				records[ticker]['low'] = float()
				try:
					oldhigh, oldlow = yahoo.historic_high(ticker, market_data) # first run to prime cache file
				except (KeyError, TypeError):
					continue
			try:
				newhigh = round(market_data[ticker]['fiftyTwoWeekHigh'], 2)
				newlow = round(market_data[ticker]['fiftyTwoWeekLow'], 2)
			except (KeyError, ValueError):
				continue
			title = market_data[ticker]['profile_title']
			ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
			emoji = util.flag_from_ticker(ticker)
			records[ticker]['high'] = oldhigh
			records[ticker]['low'] = oldlow
			if newhigh > oldhigh:
				if debug:
					print("DEBUG", ticker, newhigh, "is higher than", oldhigh)
				records[ticker]['high'] = newhigh
				payloadhigh.append(f"{emoji} {title} ({ticker_link})")
			if newlow < oldlow:
				if debug:
					print("DEBUG", ticker, newlow, "is lower than", oldlow)
				records[ticker]['low'] = newlow
				payloadlow.append(f"{emoji} {title} ({ticker_link})")
		payloadlow.sort()
		payloadhigh.sort()
		if payloadhigh:
			message = 'Record high:'
			message = webhook.bold(message, service)
			payload.append(message)
			payload = payload + payloadhigh
		if payloadlow:
			if payloadhigh:
				payload.append("")
			message = 'Record Low:'
			message = webhook.bold(message, service)
			payload.append(message)
			payload = payload + payloadlow
		return payload, records

	# MAIN #

	market_data = {}
	if specific_stock:
		ticker = util.transform_to_yahoo(specific_stock)
		tickers = [ticker]
	else:
		tickers = util.get_holdings_and_watchlist()
		market_data = yahoo.fetch(tickers)

	# Prep and send payloads
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	else:
		for service, url in webhooks.items():
			payload, records = prepare_ath_payload(service, market_data)
			if service == "telegram":
				url = url + "sendMessage?chat_id=" + str(chat_id)
			webhook.payload_wrapper(service, url, payload, chat_id)

	if payload:
		util.json_write('finbot_fin.json', records, persist=True)

	# make google cloud happy
	return True

if __name__ == "__main__":
	lambda_handler()
