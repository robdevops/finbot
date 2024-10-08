#!/usr/bin/env python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo
from lib import shortman

def lambda_handler(chat_id=config_telegramChatID, threshold=config_shorts_percent, specific_stock=None, service=None, interactive=False):
	def prepare_shorts_payload(service, market_data):
		payload = []
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

		def last_element(e):
			return e[-1]
		payload.sort(key=last_element)
		for i, e in enumerate(payload):
			e[-1] = str(round(e[-1])) + '%'
			payload[i] = ' '.join(e)

		if payload:
			if not specific_stock:
				message = f'Tracked stocks shorted over {threshold}%:'
				message = webhook.bold(message, service)
				payload.insert(0, message)
		else:
			if interactive:
				if specific_stock:
					payload = [f"{emoji}No short interest found for {tickers[0]}"]
				else:
					payload = [f"{emoji}No stocks shorted over {threshold}%. Try specifying a number."]
		return payload

	# MAIN #

	if specific_stock:
		ticker = util.transform_to_yahoo(specific_stock)
		tickers = [ticker]
	else:
		tickers = util.get_holdings_and_watchlist()

	market_data = yahoo.fetch(tickers)
	for ticker in tickers:
		if '.' not in ticker:
			try:
				market_data = market_data | yahoo.fetch_detail(ticker)
			except TypeError:
				pass
	print("")
	market_data = shortman.fetch(market_data)

	# Prep and send payloads
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	if interactive:
		payload = prepare_shorts_payload(service, market_data)
		url = webhooks[service]
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = url + "sendMessage?chat_id=" + str(chat_id)
		webhook.payload_wrapper(service, url, payload, chat_id)
	else:
		for service, url in webhooks.items():
			payload = prepare_shorts_payload(service, market_data)
			if service == "telegram":
				url = url + "sendMessage?chat_id=" + str(chat_id)
			webhook.payload_wrapper(service, url, payload, chat_id)

	# make google cloud happy
	return True

if __name__ == "__main__":
	lambda_handler()
