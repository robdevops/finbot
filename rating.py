#!/usr/bin/env python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
	def prepare_rating_payload(service, market_data):
		def get_emoji(old, new):
			if old > new:
				return '📈'
			if old < new:
				return '📉'
			else:
				return '▪️'
		payload = []
		new = {}
		old = util.json_load('finbot_rating.json', persist=True)
		for ticker in tickers:
			old_action=None
			old_index = float()
			try:
				action = market_data[ticker]['recommend'].replace('_', ' ')
				index = round(float(market_data[ticker]['recommend_index']), 1)
				analysts = market_data[ticker]['recommend_analysts']
			except (KeyError, ValueError):
				continue
			title = market_data[ticker]['profile_title']
			ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service, brief=False)
			new[ticker] = [action, index]
			try:
				old_action = old[ticker][0]
				old_index = old[ticker][1]
			except (KeyError, TypeError):
				pass
			if old_action and action != old_action:
				emoji = get_emoji(old_index, index)
				message = f"{webhook.bold(f'{old_index} {old_action}', service)} to {webhook.bold(f'{index} {action}', service)} ({analysts} analysts)"
				payload.append(f"{emoji} {title} ({ticker_link}) changed from {message}")
		payload.sort()
		if payload:
			if not specific_stock:
				message = f'Consensus rating changes:'
				message = webhook.bold(message, service)
				payload.insert(0, message)
		else:
			if interactive:
				if specific_stock:
					payload = [f"No rating changes found for {tickers[0]}"]
				else:
					payload = ["No rating changes found"]
		return payload, new

	# MAIN #

	tickers = [util.transform_to_yahoo(specific_stock)] if specific_stock else util.get_holdings_and_watchlist()
	market_data = {}
	for ticker, detail in zip(tickers, yahoo.fetch_each(yahoo.fetch_detail, tickers)): # fetched together
		if isinstance(detail, Exception):
			print(ticker, detail, file=sys.stderr)
		else:
			market_data |= detail

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, new = prepare_rating_payload(service, market_data)
		webhook.send(service, url, chat, payload)

	if new:
		util.json_write('finbot_rating.json', new, persist=True)

	# make google cloud happy
	return True

def job(argv):
	return 'rating.py', {}

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
