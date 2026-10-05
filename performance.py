#!/usr/bin/env python3

import sys
import json

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo
from lib import charts

def lambda_handler(chat_id=config_telegramChatID, past_days=config_past_days, service=None, user='', portfolio_select=None, message_id=None, interactive=False, return_result=False):
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
			print(errorstring, file=sys.stderr)
		if isinstance(percent, str):
			errorstring=percent
			print(errorstring, file=sys.stderr)
			return errorstring, None
		else:
			percent = percent[past_days]
			emoji = get_emoji(percent)
			link = util.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
			return f"{emoji} {link} {util.signed_percent(percent, 2)}", percent
	def prepare_performance_payload(service, performance, portfolios):
		payload = []
		lines = [] # (percent, text), sorted into payload below
		chart_rows = []
		graph = False
		for portfolio_id in performance:
			portfolio_url = "https://portfolio.sharesight.com/portfolios/" + str(portfolio_id)
			portfolio_name = performance[portfolio_id]['report']['holdings'][0]['portfolio']['name']
			portfolio_link = util.link(portfolio_url, portfolio_name, service)
			currency_percent = float(performance[portfolio_id]['report']['currency_gain_percent'])
			percent = float(performance[portfolio_id]['report']['capital_gain_percent'])
			total_percent = float(performance[portfolio_id]['report']['total_gain_percent'])
			emoji = get_emoji(percent)
			lines.append((percent, f"{emoji} {portfolio_link} {util.signed_percent(percent, 2)}"))
			chart_rows.append((portfolio_name, percent))
		if len(lines):
			for ticker, market, text in (('SPY', 'NYSEARCA', 'S&P 500'), ('QQQ', 'NasdaqGM', 'NASDAQ 100')):
				line, benchmark_percent = stock_performance(ticker, market, text)
				if benchmark_percent is not None:
					lines.append((float(benchmark_percent), line))
					chart_rows.append((text, float(benchmark_percent)))
				else:
					lines.append((float('-inf'), line)) # an error message sorts last
			lines.sort(key=lambda item: item[0], reverse=True)
			payload = [line for _, line in lines]
			period = util.days_english(past_days)
			message = webhook.bold(f"Performance over {period}", service)
			payload.insert(0, message)
			if chart_rows and (interactive or service == 'telegram'): # Slack/Discord cron posts have no way to upload an image
				subtitle = f"% change {'' if period == 'today' else 'over '}{period}"
				chart_rows.sort(key=lambda row: row[1], reverse=True) # best first
				graph = util.rows_chart(chart_rows, "Performance", subtitle, value_fmt=lambda v: util.signed_percent(v, 2))
		return payload, graph

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
		raise RuntimeError("no Sharesight data found")
	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	if interactive:
		payload, graph = prepare_performance_payload(service, performance, portfolios)
		if return_result: # period buttons rebuild the report without sending it
			return payload, graph
		if service == "slack":
			url = 'https://slack.com/api/chat.postMessage'
		elif service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + str(chat_id)
		if graph:
			markup = charts.keyboard('f', [portfolio_select or ''], charts.period_for_days(past_days)) if service == 'telegram' else None
			webhook.sendPhoto(chat_id, graph, '\n'.join(payload), service, reply_markup=markup)
		else:
			webhook.payload_wrapper(service, url, payload, chat_id, message_id)
	else:
		for service, url in webhooks.items():
			payload, graph = prepare_performance_payload(service, performance, portfolios)
			if service == "telegram":
				chat_id = config_telegramChatID
				url = url + "sendMessage?chat_id=" + str(chat_id)
			else:
				chat_id = None
			if graph:
				markup = charts.keyboard('f', [''], charts.period_for_days(past_days)) if service == 'telegram' else None
				webhook.sendPhoto(chat_id, graph, '\n'.join(payload), service, reply_markup=markup)
				continue
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
		webhook.guarded('performance.py', lambda_handler, past_days=days)
	else:
		webhook.guarded('performance.py', lambda_handler)

