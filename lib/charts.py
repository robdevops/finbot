"""A chart with period buttons, built by its kind's builder: the command's first view, and again for the period of a
button pressed, so that both look alike."""
from lib import answer
from lib import buttons
from lib import formats
from lib import links
from lib import yahoo
from lib.reports import history, performance, price

def history_chart(service, period, days, ticker):
	""".history: the change over every period, the chosen one marked, and the line of that period (or of it all)."""
	lines, chart = history.history_payload(ticker, service, days)
	return '\n'.join(lines), chart

def price_chart(service, period, days, ticker):
	""".price SYMBOL [period]: one stock's change over the period (all its history for Max), from Yahoo, and its
	line."""
	market_data = yahoo.fetch([ticker])
	if ticker not in market_data:
		raise answer.Answer(f"no data found for {ticker}")
	changes, chart = history.price_line(ticker, days, market_data[ticker])
	percent = float(changes.get(days, changes.get('Max', next(iter(changes.values()), 0))))
	link = links.finance_link(ticker, market_data[ticker]['profile_exchange'], service, days=days)
	title = market_data[ticker]['profile_title']
	caption = f"{formats.get_emoji(percent)} {title} ({link}) {formats.signed_percent(round(percent))}"
	return caption, chart

def compare_chart(service, period, days, *tickers):
	""".compare: the stocks' changes over the period, rebased on one chart."""
	caption, chart = history.prepare_compare(service, list(tickers), days)
	return '\n'.join(caption), chart

def performance_chart(service, period, days, portfolio):
	""".performance: each portfolio over the period, or the one named ('' for all)."""
	payload, chart = performance.report(service, days or buttons.MAX_DAYS, portfolio or None)
	return '\n'.join(payload), chart

def price_list_chart(service, period, days, threshold, top):
	""".price: the moves past `threshold`, or the top and bottom `top` ('0': not a top list), over the period; period
	'd' is today's moves, the command's default view, not a lookback of one day."""
	span = {'mode': 'interday'} if period == 'd' else {'mode': 'period', 'days': days or buttons.MAX_DAYS}
	threshold, top = float(threshold), int(top) or None
	found = price.moves(threshold=threshold, interactive=True, **span)
	payload, chart = price.report(service, found, threshold=threshold, interactive=True, top=top, **span)
	if not chart:
		raise answer.Answer(*(payload or ['no price data']))
	return '\n'.join(payload), chart

BUILDERS = {'h': history_chart, 'p': price_chart, 'c': compare_chart, 'f': performance_chart, 'l': price_list_chart}

def build(kind, args, service, period=None, days=None):
	"""(caption, chart spec or None) of a chart kind from the arguments its buttons carry (buttons.keyboard): over a
	button period, or over `days` (a command's own span: .compare 3m), or the command's default view."""
	if kind not in BUILDERS:
		raise ValueError(f"unknown chart kind {kind}")
	return BUILDERS[kind](service, period, buttons.PERIODS[period][1] if period else days, *args)
