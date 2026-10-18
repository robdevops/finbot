""".performance: each portfolio's return over a period, beside two benchmarks (scheduled: performance [days])."""

from lib import log
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
	"""[(portfolio, its capital gain over past_days in percent)] of every portfolio, or of the one named (in any case).
	Raises sharesight.PortfolioNotFound for a name that is none of them."""
	return [(portfolio, portfolio.gain(past_days)) for portfolio in sharesight.portfolios(portfolio_select)]

def benchmark(ticker, market, text, past_days, service):
	"""(report line, percent) of a benchmark over past_days; percent None, and the line saying so, without history."""
	try:
		percent = yahoo.price_history(ticker, days=past_days)[0][past_days]
	except Exception as e: # the rest of the report still goes out
		log.warn(ticker, e)
		return f"⚠️ {text}: no price history", None
	link = links.finance_link(ticker, market, service=service, days=past_days, brief=True, text=text)
	return f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}", percent

def report(service, past_days, portfolio_select=None):
	"""(payload, chart) of the performance report for one service: each portfolio by name, in any case, then the
	benchmarks."""
	rows = [] # (percent or None, line, chart label), one list for the caption and the chart, in the same order
	for portfolio, percent in sorted(gather(past_days, portfolio_select), key=lambda each: each[0].name.casefold()):
		link = service.link(f"https://portfolio.sharesight.com/portfolios/{portfolio.id}", portfolio.name)
		line = f"{formats.get_emoji(percent)} {link} {formats.signed_percent(percent, 2)}"
		rows.append((percent, line, portfolio.name))
	for ticker, market, text in BENCHMARKS:
		line, percent = benchmark(ticker, market, text, past_days, service)
		rows.append((None if percent is None else float(percent), line, text))
	period = formats.days_english(past_days)
	payload = [service.bold(f"Performance over {period}")] + [line for _, line, _ in rows]
	chart_rows = [(label, percent) for percent, _, label in rows if percent is not None]
	span = f"% change {'' if period == 'today' else 'over '}{period}"
	return payload, render.Chart('bars', "Performance", span, tuple(chart_rows), value_format='percent2')

def run(dest=None, *, past_days=None, portfolio_select=None):
	"""Post each portfolio's performance over past_days (the past_days setting when None), or the one named, beside
	the benchmarks: to the chat that asked or whose job it is (dest), with its chart and period buttons where they can
	go."""
	chat = delivery.target(dest)
	if past_days is None:
		past_days = config.settings.past_days
	payload, graph = report(chat.dialect, past_days, portfolio_select)
	markup = buttons.keyboard('f', [portfolio_select or ''], buttons.period_for_days(past_days))
	delivery.deliver(chat, delivery.Report(payload, graph, markup))

ARGUMENTS = '[DAYS]' # what a scheduled run takes

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case []:
			return 'performance', {}
		case [days] if days.isdigit():
			return f'performance {days}', {'past_days': int(days)}
		case _:
			raise ValueError(ARGUMENTS)
