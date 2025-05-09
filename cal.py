#!/usr/bin/env python3

import json
import datetime
import sys

from lib.config import *
from lib import util
from lib import webhook
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, days=config_future_days, service=None, specific_stock=None, message_id=None, interactive=False, earnings=False, dividend=False):
	def prepare_payload(service, market_data, days):
		payload_staging = []
		emoji = "📣"
		now = datetime.datetime.now()
		soon = now + datetime.timedelta(days=days)
		dates = set()
		for ticker in market_data.copy():
			ticker_primary = ticker
			emoji = util.flag_from_ticker(ticker)
			if market_data[ticker]['quoteType'] == 'ETF':
				continue
			try:
				if earnings:
					timestamp = market_data[ticker]['earnings_date']
				elif dividend:
					timestamp = market_data[ticker]['ex_dividend_date']
				timestamp = datetime.datetime.fromtimestamp(timestamp)
			except (KeyError):
				title_orig = market_data[ticker]['profile_title']
				if ticker in primary_listing: # dict from lib.config
					ticker_primary = primary_listing[ticker]
				elif ticker.endswith('.AX') and 'financialCurrency' in market_data[ticker] and market_data[ticker]['financialCurrency'] == 'NZD':
					ticker_primary = ticker.replace('.AX', '.NZ') # fixes GTK.AX and SKO.AX
				market_data = market_data | yahoo.fetch_detail(ticker_primary)
				if 'profile_country' in market_data[ticker_primary]: # country is only available after fetch_detail
					country = market_data[ticker_primary]['profile_country']
					if country in yahoo_country and '.' not in ticker_primary: # yahoo_country dict in lib.conig
						ticker_primary = ticker_primary + '.' + yahoo_country[country] # fixes ASML and INFY
						market_data = market_data | yahoo.fetch_detail(ticker_primary)
				if ticker_primary not in market_data or title_orig != market_data[ticker_primary]['profile_title']:
					continue
				try:
					if earnings:
						timestamp = market_data[ticker_primary]['earnings_date']
					elif dividend:
						timestamp = market_data[ticker_primary]['ex_dividend_date']
					timestamp = datetime.datetime.fromtimestamp(timestamp)
				except (KeyError):
					continue
			if (timestamp > now and timestamp < soon) or specific_stock:
				title = market_data[ticker]['profile_title']
				ticker_link = util.yahoo_link(ticker, service)
				dates.add(timestamp.date()) # (2023, 12, 30)
				emoji = util.flag_from_ticker(ticker_primary)
				payload_staging.append([emoji, title, f'({ticker_link})', timestamp])

		def numeric_date(e):
			return e[3]
		payload_staging.sort(key=numeric_date)

		payload = []
		for date in sorted(dates):
			human_date = date.strftime('%b %d') # Dec 30
			if not specific_stock:
				payload.append("")
				payload.append(webhook.bold(human_date, service))
			for e in payload_staging:
				if date == e[3].date():
					if specific_stock:
						e.insert(1, human_date)
					payload.append(' '.join(e[:-1]))

		if payload:
			if not specific_stock:
				if earnings:
					message = f"Upcoming earnings {util.days_english(days, 'for the next ')}:"
				elif dividend:
					message = f"Upcoming ex-dividends {util.days_english(days, 'for the next ')}:"
				message = webhook.bold(message, service)
				payload.insert(0, message)
		else:
			if interactive:
				if specific_stock:
					payload = [f"No events found for {tickers[0]}"]
				else:
					payload = [f"No events found for the next { f'{days} days' if days != 1 else 'day' }"]
		return payload

	# MAIN #
	if specific_stock:
		ticker = util.transform_to_yahoo(specific_stock)
		tickers = [ticker]
	else:
		tickers = util.get_holdings_and_watchlist()

	if earnings:
		market_data = yahoo.fetch(tickers)
	elif dividend:
		market_data = {}
		for ticker in tickers:
			try:
				market_data = market_data | yahoo.fetch_detail(ticker)
			except TypeError:
				pass
		print("")

	# Prep and send payloads
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	if interactive:
		payload = prepare_payload(service, market_data, days)
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
		webhook.payload_wrapper(service, url, payload, chat_id, message_id)
	else:
		for service, url in webhooks.items():
			payload = prepare_payload(service, market_data, config_future_days)
			if service == "telegram":
				url = url + "sendMessage?chat_id=" + config_telegramChatID
			webhook.payload_wrapper(service, url, payload)

	# make google cloud happy
	return True

if __name__ == "__main__":
	if len(sys.argv) > 1:
		match sys.argv[1]:
			case 'earnings':
				lambda_handler(earnings=True)
			case 'ex-dividend':
				lambda_handler(dividend=True)
			case other:
				print("Usage:", sys.argv[0], "[earnings|ex-dividend]", file=sys.stderr)
	else:
		print("Usage:", sys.argv[0], "[earnings|ex-dividend]", file=sys.stderr)
