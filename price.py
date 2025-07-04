#!/usr/bin/env python3

import json, re, sys, os
import datetime

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo
from lib import telegram

def lambda_handler(chat_id=config_telegramChatID, threshold=config_price_percent, service=None, user='', specific_stock=None, interactive=False, midsession=False, premarket=False, interday=False, days=None, close=False):
	def prepare_price_payload(service, market_data, threshold):
		payload = []
		graph = False
		marketStates = []
		skipped_volatile = []
		exchange_set = set()
		multiplier = config_volatility_multiplier
		for ticker in market_data:
			marketState = market_data[ticker]['marketState']
			marketStates.append(marketState)
			regularMarketTime = datetime.datetime.fromtimestamp(market_data[ticker]['regularMarketTime'])
			now = datetime.datetime.now()
			if midsession and marketState != "REGULAR":
				# skip stocks not in session
				# Possible market states: PREPRE PRE REGULAR POST POSTPOST CLOSED
				continue
			if interday and not interactive and now - regularMarketTime > datetime.timedelta(days=1):
				# avoid repeating on market holidays
				print(ticker + '⏭', sep='', end=' ', flush=True)
				continue
			if close and not interactive and (now - regularMarketTime > datetime.timedelta(hours=1.5) or marketState in ('PREPRE', 'PRE', 'REGULAR')):
				# avoid markets that didn't recently close
				print(ticker + '⏭', sep='', end=' ', flush=True)
				continue
			if premarket:
				if 'percent_change_premarket' in market_data[ticker]:
					percent = market_data[ticker]['percent_change_premarket']
				elif 'percent_change_postmarket' in market_data[ticker]:
					percent = market_data[ticker]['percent_change_postmarket']
				else:
					continue
			elif days:
				try:
					percent = market_data[ticker]['percent_change_period'] # sharesight value
				except KeyError:
					if config_performance_use_sharesight:
						continue
					# wishlist items will come here
					print("Could not find", ticker, "in Sharesight data. Trying Yahoo", file=sys.stderr) if debug else None
					if specific_stock:
						percent, graph = yahoo.price_history(ticker, days, graphCache=False)
						if isinstance(percent, str) and interactive:
							errormessage = percent
							print("Error", errormessage, file=sys.stderr)
							if service == "slack":
								url = 'https://slack.com/api/chat.postMessage'
							elif service == "telegram":
								url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
							webhook.payload_wrapper(service, url, [errormessage], chat_id)
							sys.exit(1)
					else:
						percent, graph = yahoo.price_history(ticker, days, graph=False)
						if isinstance(percent, str) and interactive:
							continue
					try:
						percent = percent[days]
					except KeyError:
						percent = percent['Max']
			else:
				percent = market_data[ticker]['percent_change']
			title = market_data[ticker]['profile_title']
			percent = float(percent)
			if percent < 0:
				emoji = "🔻"
			elif percent > 0:
				emoji = '🔼'
			else:
				emoji = "▪️"
			exchange = exchange_human = market_data[ticker]['profile_exchange']
			exchange_human = util.exchange_human(exchange)
			if exchange in ('Taipei Exchange', 'CCC') or ticker.startswith('^'):
				ticker_link = util.yahoo_link(ticker, service)
			elif config_hyperlinkProvider == 'google':
				ticker_link = util.gfinance_link(ticker, exchange, service, days=days)
			else:
				ticker_link = util.yahoo_link(ticker, service)
			if not interactive and not payload and config_demote_leveraged and '2x' in title.lower():
				if abs(percent) >= threshold * 1.3:
					payload.append([emoji, title, f'({ticker_link})', percent])
					exchange_set.add(exchange_human)
				elif abs(percent) >= threshold:
					skipped_volatile.append(ticker)
			elif not interactive and not payload and config_demote_leveraged and '3x' in title.lower():
				if abs(percent) >= threshold * 1.3:
					payload.append([emoji, title, f'({ticker_link})', percent])
					exchange_set.add(exchange_human)
				elif abs(percent) >= threshold:
					skipped_volatile.append(ticker)
			#if not interactive and config_demote_volatile and 'market_cap' in market_data[ticker] and market_data[ticker]['market_cap'] < 1000000000:
			elif not interactive and not payload and config_demote_volatile and 'market_cap' in market_data[ticker] and market_data[ticker]['market_cap'] < 1000000000: # 1B
				if market_data[ticker]['market_cap'] < 150000000: # 150M
					if market_data[ticker]['market_cap'] < 10000000: # 10M
						if abs(percent) >= threshold * (multiplier * 1.3):
							payload.append([emoji, title, f'({ticker_link})', percent])
							exchange_set.add(exchange_human)
					elif abs(percent) >= threshold * multiplier:
						payload.append([emoji, title, f'({ticker_link})', percent])
						exchange_set.add(exchange_human)
					elif abs(percent) >= threshold:
						skipped_volatile.append(ticker)
				else: # < 1B
					market_data = market_data | yahoo.fetch_detail(ticker)
					if not 'beta' in market_data[ticker] or market_data[ticker]['beta'] > 1.5:
						if abs(percent) >= threshold * multiplier:
							payload.append([emoji, title, f'({ticker_link})', percent])
							exchange_set.add(exchange_human)
						elif abs(percent) >= threshold:
							skipped_volatile.append(ticker)
					elif abs(percent) >= threshold:
						payload.append([emoji, title, f'({ticker_link})', percent])
						exchange_set.add(exchange_human)
			elif abs(percent) >= threshold: # abs catches negative percentages
				payload.append([emoji, title, f'({ticker_link})', percent])
				exchange_set.add(exchange_human)
			elif specific_stock and interactive:
				payload.append([emoji, title, f'({ticker_link})', percent])
				exchange_set.add(exchange_human)
		def last_element(e):
			return e[-1]
		payload.sort(key=last_element)
		for i, e in enumerate(payload):
			e[-1] = f'{round(e[-1]):,}%'
			payload[i] = ' '.join(e)
		if payload:
			if not specific_stock:
				if skipped_volatile:
					# run through again, since we already have a payload. only triggers if the first ticker met volatilty threshold
					market_data = yahoo.fetch(skipped_volatile)
					payload, graph = payload + prepare_price_payload(service, market_data, threshold)[0], graph
				if midsession:
					message = f'Tracking ≥ {threshold}% ({", ".join(exchange_set)}):'
				elif premarket:
					message = f'Tracking ≥ {threshold}% pre-market ({", ".join(exchange_set)}):'
				elif close:
					message = f'≥ {threshold}% at close ({", ".join(exchange_set)}):'
				elif days:
					message = f'Moved ≥ {threshold}% {util.days_english(days, "in ", "a ")}:'
				else:
					message = f'Day change ≥ {threshold}%:'
				message = webhook.bold(message, service)
				payload.insert(0, message)
		else:
			if interactive:
				if specific_stock:
					if midsession:
						payload = [f"{tickers[0]} not found or not in session"]
					elif premarket:
						payload = [f"No premarket price found for {tickers[0]}"]
					else:
						payload = [f"No interday price found for {tickers[0]}"]
				elif premarket:
					payload = [f"No pre-market price movements meet threshold {threshold}%"]
				elif midsession:
					if 'REGULAR' not in marketStates:
						payload = [f"{user}, no tracked stocks are currently in session."]
					else:
						payload = [f"{user}, no in-session securities meet threshold {threshold}%"]
				else:
					payload = [f"{user}, no price movements meet threshold {threshold}%"]
		return payload, graph


	# MAIN #
	if specific_stock:
		specific_stock = util.transform_to_yahoo(specific_stock)
		tickers = [specific_stock]
	else:
		tickers = util.get_holdings_and_watchlist()
	market_data = yahoo.fetch(tickers)

	# Yahoo market_data (specific_stock) or yahoo.price_history (days) is faster
	# Note: Sharesight only works if specific_stock is a holding.
	# Note2: Sharesight can only report performance for the time you bought it
	#	so if you held NVDA for 1Y and request 5Y, you will only get 1Y performance
	if (not specific_stock and days) or (config_performance_use_sharesight and days):
		performance = sharesight.get_performance_wrapper(days)
		for portfolio_id, data in performance.items():
			for holding in data['report']['holdings']:
				symbol = holding['instrument']['code']
				market = holding['instrument']['market_code']
				percent = float(holding['capital_gain_percent'])
				ticker = util.transform_to_yahoo(symbol, market)
				if ticker not in tickers:
					continue # when using specific_stock
				try:
					#print("DEBUG injecting sharesight price into market_data:", ticker, file=sys.stderr)
					market_data[ticker]['percent_change_period'] = percent # inject sharesight value
				except KeyError:
					print("Notice:", os.path.basename(__file__), ticker, "has no data", file=sys.stderr)
					continue

	# Prep and send payloads
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	if interactive:
		payload, graph = prepare_price_payload(service, market_data, threshold)
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
		if graph:
			caption = '\n'.join(payload)
			webhook.sendPhoto(chat_id, graph, caption, service)
		else:
			webhook.payload_wrapper(service, url, payload, chat_id)
	else:
		for service, url in webhooks.items():
			payload, graph = prepare_price_payload(service, market_data, threshold)
			if service == "telegram":
				url = url + "sendMessage?chat_id=" + str(chat_id)
			webhook.payload_wrapper(service, url, payload, chat_id)

if __name__ == "__main__":
	if len(sys.argv) > 1:
		match sys.argv[1]:
			case 'midsession':
				lambda_handler(midsession=True)
			case 'interday':
				lambda_handler(interday=True)
			case 'premarket':
				lambda_handler(premarket=True)
			case 'close':
				lambda_handler(close=True)
			case other:
				print("Usage:", sys.argv[0], "[midsession|interday|premarket|close]", file=sys.stderr)

	else:
		print("Usage:", sys.argv[0], "[midsession|interday|premarket|close|days (int)]", file=sys.stderr)
