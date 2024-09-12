#!/usr/bin/env python3

import sys
import json

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

def lambda_handler(chat_id=config_telegramChatID, past_days=config_past_days, service=None, user='', portfolio_select=None, message_id=None, interactive=False):
	def get_emoji(percent):
		if percent < 0:
			emoji = "🔻"
		elif percent > 0:
			emoji = '🔼'
		else:
			emoji = "▪️"
		return emoji
	def stock_performance(ticker, market, text):
		try:
			percent, graph = yahoo.price_history(ticker, days=past_days, graph=False)
		except Exception as e:
			errorstring=f"error: {e}"
→   →   →   print(errorstring, file=sys.stderr)
→   →   if isinstance(percent, str):
→   →		errorstring=price_history
→   →   →   print(errorstring, file=sys.stderr)
→   →   →   return errorstring
→   →   else:
			percent = percent[past_days]
			emoji = get_emoji(percent)
			link = util.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
			return f"{emoji} {link} {percent}%"
	def prepare_performance_payload(service, performance, portfolios):
		payload = []
		for portfolio_id in performance:
			portfolio_url = "https://portfolio.sharesight.com/portfolios/" + str(portfolio_id)
			portfolio_name = performance[portfolio_id]['report']['holdings'][0]['portfolio']['name']
			portfolio_link = util.link(portfolio_url, portfolio_name, service)
			currency_percent = float(performance[portfolio_id]['report']['currency_gain_percent'])
			percent = float(performance[portfolio_id]['report']['capital_gain_percent'])
			total_percent = float(performance[portfolio_id]['report']['total_gain_percent'])
			emoji = get_emoji(percent)
			payload.append(f"{emoji} {portfolio_link} {percent}%")
		if len(payload):
			payload.append(stock_performance('SPY', 'NYSEARCA', 'S&P 500'))
			payload.append(stock_performance('QQQ', 'NasdaqGM', 'NASDAQ 100'))
			message = f"Performance over {util.days_english(past_days)}"
			message = webhook.bold(message, service)
			payload.insert(0, message)
		return payload

	# MAIN #
	portfolios = sharesight.get_portfolios()
	performance = {}

	if portfolio_select:
		portfoliosLower = {k.lower():v for k,v in portfolios.items()}
		if portfolio_select.lower() in portfoliosLower:
			portfolio_id = portfoliosLower[portfolio_select.lower()] # any-case input
			performance[portfolio_id] = sharesight.get_performance(portfolio_id, past_days)
	else:
		for portfolio, portfolio_id in portfolios.items():
			performance[portfolio_id] = sharesight.get_performance(portfolio_id, past_days)

	# Prep and send payloads
	if not len(performance):
		print("Error: no Sharesight data found", file=sys.stderr)
		sys.exit(1)
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	if interactive:
		payload = prepare_performance_payload(service, performance, portfolios)
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
		webhook.payload_wrapper(service, url, payload, chat_id, message_id)
	else:
		for service, url in webhooks.items():
			payload = prepare_performance_payload(service, performance, portfolios)
			if service == "telegram":
				chat_id = config_telegramChatID
				url = url + "sendMessage?chat_id=" + str(chat_id)
			else:
				chat_id = None
			webhook.payload_wrapper(service, url, payload, chat_id)

	# make google cloud happy
	return True

if __name__ == "__main__":
	if len(sys.argv) > 1:
		try:
			days = int(sys.argv[1])
		except ValueError:
			print("Usage:", sys.argv[0], "[integer]", file=sys.stderr)
			sys.exit(1)
		lambda_handler(past_days=days)
	else:
		lambda_handler()

