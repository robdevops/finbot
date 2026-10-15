"""A period button pressed: the chart rebuilt for that period."""
from lib import answer
from lib import buttons
from lib import formats
from lib import links
from lib import yahoo
from lib.reports import history, performance, price

def build(kind, tickers, period, service):
	"""(caption, chart spec or None) for a chart kind at a button period; period None = the command's default view."""
	days = buttons.PERIODS[period][1] if period else None
	if kind == 'h':
		ticker = tickers[0]
		highlight = buttons.PERIODS[period or 'x'][0]
		lines, _, chart = history.history_payload(ticker, service, highlight, graph=not days) # default view: it all
		if days:
			changes, line = yahoo.price_history(ticker, days)
			chart = history.line_chart(ticker, changes, line, days)
		return '\n'.join(lines), chart
	if kind == 'p':
		ticker = tickers[0]
		market_data = yahoo.fetch([ticker])
		if ticker not in market_data:
			raise answer.Answer(f"no data found for {ticker}")
		changes, line = yahoo.price_history(ticker, days)
		percent = float(changes.get(days, changes.get('Max', next(iter(changes.values()), 0))))
		link = links.quote_link(ticker, market_data[ticker]['profile_exchange'], service, days=days)
		title = market_data[ticker]['profile_title']
		caption = f"{formats.get_emoji(percent)} {title} ({link}) {formats.signed_percent(round(percent))}"
		return caption, history.line_chart(ticker, changes, line, days)
	if kind == 'c':
		args = list(tickers) + ([f'{days}d'] if days else ['max'])
		caption, chart, *_ = history.prepare_compare(service, args)
		if not chart:
			raise answer.Answer(*caption)
		return '\n'.join(caption), chart
	if kind == 'f': # performance: tickers = [portfolio name or '']
		payload, chart = performance.report(service, days or buttons.MAX_DAYS, tickers[0] or None)
		if not chart:
			raise answer.Answer(*(payload or ['no performance data']))
		return '\n'.join(payload), chart
	if kind == 'l': # price list: tickers = [threshold, top]
		span = {'interday': True} if period == 'd' else {'days': days or buttons.MAX_DAYS} # 'd' is today's moves: the command's default view, not a 1-day lookback
		threshold, top = float(tickers[0]), int(tickers[1]) or None
		payload, chart = price.report(service, threshold=threshold, interactive=True, top=top, **span)
		if not chart:
			raise answer.Answer(*(payload or ['no price data']))
		return '\n'.join(payload), chart
	raise ValueError(f"unknown chart kind {kind}")
