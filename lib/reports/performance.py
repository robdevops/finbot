""".performance: each portfolio's return over a period, beside two benchmarks (scheduled: performance.py [days])."""
import sys

from lib import config
from lib import sharesight
from lib import delivery
from lib import formats
from lib import links
from lib import render
from lib import yahoo
from lib import buttons

BENCHMARKS = (('SPY', 'NYSEARCA', 'S&P 500'), ('QQQ', 'NasdaqGM', 'NASDAQ 100'))

def gather(past_days, portfolio_select=None):
	"""{portfolio id: (its name, Sharesight's performance report over past_days)} of every portfolio, or of the one named (in any
	case). Raises sharesight.PortfolioNotFound for a name that is none of them, and RuntimeError when there is no report."""
	performance = {portfolio.id: (portfolio.name, portfolio.performance(past_days))
		for portfolio in sharesight.portfolios(portfolio_select)}
	if not performance:
		print("Error: no Sharesight data found", file=sys.stderr)
		raise RuntimeError("no Sharesight data found")
	return performance

def benchmark(ticker, market, text, past_days, service):
	"""(report line, percent) of a benchmark over past_days; percent is None, and the line says so, when it has no history."""
	try:
		percent = yahoo.price_history(ticker, days=past_days)[0][past_days]
	except Exception as e: # the rest of the report still goes out
		print(ticker, e, file=sys.stderr)
		return f"⚠️ {text}: no price history", None
	link = links.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
	return f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}", percent

def report(service, past_days, portfolio_select=None, performance=None):
	"""(payload, chart) of the performance report for one service: each portfolio and the benchmarks, best first. performance:
	gather()'s, fetched when not given."""
	if performance is None:
		performance = gather(past_days, portfolio_select)
	rows = [] # (percent or None, line, chart label), one list for the caption and the chart, best first
	for portfolio_id, (name, data) in performance.items(): # the name from the portfolio list: one with no holdings names none
		link = service.link("https://portfolio.sharesight.com/portfolios/" + str(portfolio_id), name)
		percent = float(data['report']['capital_gain_percent'])
		rows.append((percent, f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}", name))
	for ticker, market, text in BENCHMARKS:
		line, percent = benchmark(ticker, market, text, past_days, service)
		rows.append((None if percent is None else float(percent), line, text))
	rows.sort(key=lambda row: float('-inf') if row[0] is None else row[0], reverse=True) # an error line sorts last
	period = formats.days_english(past_days)
	payload = [service.bold(f"Performance over {period}")] + [line for _, line, _ in rows]
	chart_rows = [(label, percent) for percent, _, label in rows if percent is not None]
	span = f"% change {'' if period == 'today' else 'over '}{period}"
	return payload, render.Chart('bars', "Performance", span, tuple(chart_rows), value_format='percent2')

def run(dest=None, *, past_days=None, user='', portfolio_select=None):
	"""Post each portfolio's performance over past_days (the past_days preference when None), or the one named, beside
	the benchmarks: to the chat that asked (dest), else to the default chats, with its chart and period buttons where
	they can go."""
	if past_days is None:
		past_days = config.prefs.past_days
	performance = gather(past_days, portfolio_select)
	for chat in delivery.targets(dest):
		payload, graph = report(chat.dialect, past_days, portfolio_select, performance)
		markup = None
		if graph and chat.takes_buttons:
			markup = buttons.keyboard('f', [portfolio_select or ''], buttons.period_for_days(past_days))
		delivery.deliver(chat, delivery.Report(payload, graph, markup))

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case []:
			return 'performance.py', {}
		case [days] if days.isdigit():
			return f'performance.py {days}', {'past_days': int(days)}
		case _:
			raise ValueError('[integer]')
