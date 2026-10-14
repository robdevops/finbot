#!/usr/bin/env python3

import json, os, random, sys, re
import datetime

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, days=UNSET, service=None, user='', portfolio_select=None, message_id=None, interactive=False):
	if days is UNSET:
		days = config_past_days
	start_date = datetime.datetime.now() - datetime.timedelta(days=days)
	start_date = start_date.strftime('%Y-%m-%d') # 2022-08-20
	state_file = "finbot_sharesight_trades.json"

	def prepare_trade_payload(service, trades):
		if not len(trades):
			print("No trades provided to prepare_trade_payload()", file=sys.stderr)
			return None
		payload_staging = []
		dates = set()
		wanted = [] # the trades to report: buys and sells in the chosen portfolio that are new (or all of them, when interactive)
		for trade in trades:
			if trade['transaction_type'] not in {'BUY', 'SELL'}:
				continue
			if portfolio_select and trade['portfolio'].lower() != portfolio_select.lower():
				continue
			if not interactive and int(trade['id']) in known_trades:
				print("Skipping known trade_id:", trade['id'], trade['transaction_date'], trade['portfolio'], trade['transaction_type'], trade['symbol'])
				continue
			wanted.append(trade)
		if not wanted: # the usual case on a scheduled run
			return []
		market_data = {}
		if config_trades_use_yahoo:
			tickers = {util.transform_to_yahoo(trade['symbol'], trade['market']) for trade in wanted} # one yahoo.fetch for all
			try:
				print("Fetching tickers from Yahoo: ", tickers, file=sys.stderr)
				market_data = yahoo.fetch(tickers)
			except Exception as e:
				print("Warning: could not fetch Yahoo:", e, file=sys.stderr)

		for trade in wanted:
			portfolio_name = trade['portfolio'] # custom field
			trade_id = int(trade['id'])
			date = trade['transaction_date'] # 2023-12-30
			transactionType = trade['transaction_type']
			symbol = trade['symbol']
			action=''
			emoji=''
			market = trade['market']
			if transactionType == 'BUY':
				action = 'bought'
				emoji = '💸'
			else: # SELL
				action = 'sold'
				emoji = '🤑'
			units = float(trade['quantity'])
			price = float(trade['price'])
			currency = trade['brokerage_currency_code']
			if config_trades_use_yahoo:
				ticker = util.transform_to_yahoo(symbol, market)
				try:
					market = market_data[ticker]['profile_exchange']
				except Exception as e:
					print("Warning: could not get market for", ticker, "from Yahoo:", e, file=sys.stderr)
			value = round(price * units) # not Sharesight's trade value, which it converts to the portfolio's currency
			holding_id = str(trade['holding_id'])
			ticker = util.transform_to_yahoo(symbol, market)
			dt_date = datetime.datetime.strptime(date, '%Y-%m-%d').date() # (2023, 12, 30)

			newtrades.add(trade_id) # sneaky update global set
			dates.add(dt_date)

			flag = util.flag_from_market(market)
			# lookup currency or fall back to less reliable sharesight currency
			currency_temp = util.currency_from_market(market)
			if currency_temp:
				currency = currency_temp
			sharesight_url = "https://portfolio.sharesight.com/holdings/"
			trade_url = sharesight_url + holding_id + '/dashboard/transactions'
			trade_link = util.link(trade_url, action, service)
			holding_link = util.finance_link(symbol, market, service)
			payload_staging.append([dt_date, trade_id, emoji, portfolio_name, trade_link, currency, f'{value}', holding_link, flag])

		payload = []
		payload_staging.sort()
		for date in sorted(dates):
			if len(dates) > 1 or (interactive and days > 1):
				human_date = date.strftime('%b %d') # Dec 30
				payload.append("")
				payload.append(webhook.bold(human_date, service))
			for trade in payload_staging:
				if date == trade[0]:
					payload.append(' '.join(trade[2:]))

		return payload

	# MAIN #
	newtrades = set()
	portfolios = sharesight.get_portfolios()
	known_trades = set(util.json_load(state_file, persist=True) or ())
	if portfolio_select:
		found = sharesight.find_portfolio(portfolios, portfolio_select)
		if not found:
			print("Portfolio not found:", portfolio_select, file=sys.stderr)
			raise ValueError(f"portfolio not found: {portfolio_select}")
		portfolio_select = found[0] # as Sharesight spells it
		portfolios = dict([found])
	trades = [trade for name, portfolio_id in portfolios.items() for trade in sharesight.get_trades(name, portfolio_id, days)]

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		if interactive and not trades:
			payload = [f"{user} No trades {util.days_english(days, 'in the past ')}. {random.choice(noTradesVerb)}"]
		else:
			payload = prepare_trade_payload(service, trades)
		webhook.send(service, url, chat, payload, message_id=message_id)

	# write state file
	if newtrades and not interactive:
		known_trades.update(newtrades)
		util.json_write(state_file, list(known_trades), persist=True)

	# make google cloud happy
	return True

def job(argv):
	return 'trades.py', {}

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
