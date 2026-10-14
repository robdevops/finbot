#!/usr/bin/env python3

import sys

from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo
from lib import charts

BENCHMARKS = (('SPY', 'NYSEARCA', 'S&P 500'), ('QQQ', 'NasdaqGM', 'NASDAQ 100'))

def gather(past_days, portfolio_select=None):
	"""{portfolio id: (its name, Sharesight's performance report over past_days)} of every portfolio, or of the one named (in any
	case). Raises sharesight.PortfolioNotFound for a name that is none of them, and RuntimeError when there is no report."""
	portfolios = sharesight.pick_portfolios(portfolio_select)
	performance = {portfolio_id: (name, sharesight.get_performance(portfolio_id, past_days)) for name, portfolio_id in portfolios.items()}
	if not performance:
		print("Error: no Sharesight data found", file=sys.stderr)
		raise RuntimeError("no Sharesight data found")
	return performance

def benchmark(ticker, market, text, past_days, service):
	"""(report line, percent) of a benchmark over past_days; percent is None, and the line says so, when it has no history."""
	try:
		percent = yahoo.price_history(ticker, days=past_days, graph=False)[0][past_days]
	except Exception as e: # the rest of the report still goes out
		print(ticker, e, file=sys.stderr)
		return f"⚠️ {text}: no price history", None
	link = util.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
	return f"{util.get_emoji(percent)} {link} {util.signed_percent(percent, 2)}", percent

def report(service, past_days=UNSET, portfolio_select=None, interactive=False, performance=None):
	"""(payload, chart) of the performance report for one service: each portfolio and the benchmarks, best first. performance:
	gather()'s, fetched when not given."""
	if past_days is UNSET:
		past_days = config_past_days
	if performance is None:
		performance = gather(past_days, portfolio_select)
	lines = [] # (percent, text), sorted into the payload below
	chart_rows = []
	for portfolio_id, (name, data) in performance.items(): # the name from the portfolio list: one with no holdings names none
		link = util.link("https://portfolio.sharesight.com/portfolios/" + str(portfolio_id), name, service)
		percent = float(data['report']['capital_gain_percent'])
		lines.append((percent, f"{util.get_emoji(percent)} {link} {util.signed_percent(percent, 2)}"))
		chart_rows.append((name, percent))
	if not lines:
		return [], None
	for ticker, market, text in BENCHMARKS:
		line, percent = benchmark(ticker, market, text, past_days, service)
		lines.append((float('-inf') if percent is None else float(percent), line)) # an error line sorts last
		if percent is not None:
			chart_rows.append((text, float(percent)))
	lines.sort(key=lambda item: item[0], reverse=True)
	period = util.days_english(past_days)
	payload = [webhook.bold(f"Performance over {period}", service)] + [line for _, line in lines]
	graph = None
	if webhook.takes_charts(service, interactive):
		chart_rows.sort(key=lambda row: row[1], reverse=True) # best first
		graph = util.rows_chart(chart_rows, "Performance", f"% change {'' if period == 'today' else 'over '}{period}", value_fmt=lambda v: util.signed_percent(v, 2))
	return payload, graph

def lambda_handler(chat_id=config_telegramChatID, past_days=UNSET, service=None, user='', portfolio_select=None, message_id=None, interactive=False):
	if past_days is UNSET:
		past_days = config_past_days
	performance = gather(past_days, portfolio_select)
	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, graph = report(service, past_days, portfolio_select, interactive, performance)
		buttons = charts.keyboard('f', [portfolio_select or ''], charts.period_for_days(past_days)) if graph and service == 'telegram' else None
		webhook.send(service, url, chat, payload, graph, reply_markup=buttons, message_id=message_id)

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case []:
			return 'performance.py', {}
		case [days] if days.isdigit():
			return f'performance.py {days}', {'past_days': int(days)}
		case _:
			raise ValueError('[integer]')

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
