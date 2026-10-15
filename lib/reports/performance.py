""".performance: each portfolio's return over a period, beside two benchmarks (scheduled: performance.py [days])."""
import sys

from lib import config
from lib import sharesight
from lib import webhook
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
		percent = yahoo.price_history(ticker, days=past_days, graph=False)[0][past_days]
	except Exception as e: # the rest of the report still goes out
		print(ticker, e, file=sys.stderr)
		return f"⚠️ {text}: no price history", None
	link = links.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
	return f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}", percent

def report(service, past_days=None, portfolio_select=None, interactive=False, performance=None):
	"""(payload, chart) of the performance report for one service: each portfolio and the benchmarks, best first. performance:
	gather()'s, fetched when not given."""
	if past_days is None:
		past_days = config.prefs.past_days
	if performance is None:
		performance = gather(past_days, portfolio_select)
	lines = [] # (percent, text), sorted into the payload below
	chart_rows = []
	for portfolio_id, (name, data) in performance.items(): # the name from the portfolio list: one with no holdings names none
		link = service.link("https://portfolio.sharesight.com/portfolios/" + str(portfolio_id), name)
		percent = float(data['report']['capital_gain_percent'])
		lines.append((percent, f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}"))
		chart_rows.append((name, percent))
	if not lines:
		return [], None
	for ticker, market, text in BENCHMARKS:
		line, percent = benchmark(ticker, market, text, past_days, service)
		lines.append((float('-inf') if percent is None else float(percent), line)) # an error line sorts last
		if percent is not None:
			chart_rows.append((text, float(percent)))
	lines.sort(key=lambda item: item[0], reverse=True)
	period = formats.days_english(past_days)
	payload = [service.bold(f"Performance over {period}")] + [line for _, line in lines]
	graph = None
	if webhook.takes_charts(service, interactive):
		chart_rows.sort(key=lambda row: row[1], reverse=True) # best first
		graph = render.rows_chart(chart_rows, "Performance", f"% change {'' if period == 'today' else 'over '}{period}", value_fmt=lambda v: formats.signed_percent(v, 2))
	return payload, graph

def lambda_handler(chat_id=None, past_days=None, service=None, user='', portfolio_select=None, interactive=False):
	"""Post each portfolio's performance over past_days (the past_days preference when None), or the one named, beside
	the benchmarks: to the chat that asked (interactive), else to the default chats, with its chart and on Telegram
	period buttons."""
	if past_days is None:
		past_days = config.prefs.past_days
	performance = gather(past_days, portfolio_select)
	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, graph = report(service, past_days, portfolio_select, interactive, performance)
		markup = buttons.keyboard('f', [portfolio_select or ''], buttons.period_for_days(past_days)) if graph and service == 'telegram' else None
		webhook.send(service, url, chat, payload, graph, reply_markup=markup)

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case []:
			return 'performance.py', {}
		case [days] if days.isdigit():
			return f'performance.py {days}', {'past_days': int(days)}
		case _:
			raise ValueError('[integer]')
