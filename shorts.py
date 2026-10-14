#!/usr/bin/env python3

import sys
from lib.config import *
from lib import webhook
from lib import util
from lib import yahoo
from lib import shortman

def lambda_handler(chat_id=config_telegramChatID, threshold=UNSET, specific_stock=None, service=None, interactive=False):
	if threshold is UNSET:
		threshold = config_shorts_percent
	def prepare_shorts_payload(service, market_data):
		payload = []
		chart_rows = []
		graph = False
		emoji = "🩳"
		for ticker in tickers:
			try:
				short_percent = float(market_data[ticker]['short_percent'])
			except (KeyError, ValueError):
				continue
			if '.AX' in ticker:
				url = 'https://www.shortman.com.au/stock?q=' + ticker.split('.')[0]
				short_interest_link = util.link(url, ticker.split('.')[0], service)
			else:
				url = 'https://finance.yahoo.com/quote/' + ticker + '/key-statistics?p=' + ticker
				short_interest_link = util.link(url, ticker.split('.')[0], service)
			title = market_data[ticker]['profile_title']
			if short_percent > threshold or specific_stock:
				payload.append([emoji, title, f'({short_interest_link})', short_percent])
				chart_rows.append((ticker.split('.')[0], short_percent))

		def last_element(e):
			return e[-1]
		payload.sort(key=last_element, reverse=True) # largest first, matching the chart
		for i, e in enumerate(payload):
			e[-1] = str(round(e[-1])) + '%'
			payload[i] = ' '.join(e)

		if payload:
			if not specific_stock:
				message = f'Tracked stocks shorted over {threshold:g}%'
				message = webhook.bold(message, service)
				payload.insert(0, message)
				if chart_rows and webhook.takes_charts(service, interactive):
					chart_rows.sort(key=lambda row: row[1], reverse=True)
					graph = util.shorts_chart(chart_rows, threshold)
		else:
			if interactive:
				if specific_stock:
					payload = [f"{emoji}No short interest found for {tickers[0]}"]
				else:
					payload = [f"{emoji}No stocks shorted over {threshold:g}%. Try specifying a number."]
		return payload, graph

	# MAIN #

	if specific_stock:
		ticker = util.transform_to_yahoo(specific_stock)
		tickers = [ticker]
	else:
		tickers = util.get_holdings_and_watchlist()

	market_data = yahoo.fetch(tickers)
	market_data |= yahoo.fetch_details((ticker for ticker in tickers if '.' not in ticker), strict=bool(specific_stock)) # US short interest; Short Man has the ASX's
	print("")
	market_data = shortman.fetch(market_data)

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, graph = prepare_shorts_payload(service, market_data)
		webhook.send(service, url, chat, payload, graph)

	# make google cloud happy
	return True

def job(argv):
	return 'shorts.py', {}

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
