"""A period button pressed: the chart rebuilt for that period."""
from lib import answer
from lib import buttons
from lib import formats
from lib import links
from lib import yahoo
from lib.reports import history, performance, price

def build(kind, tickers, period, service):
	"""(caption, image) for a chart kind at a button period; period None = the command's default view."""
	days = buttons.PERIODS[period][1] if period else None
	if kind == 'h':
		ticker = tickers[0]
		lines, table, image = history.history_payload(ticker, service, buttons.PERIODS[period or 'x'][0], graph=not days) # default view is the full history
		if table is None:
			raise answer.Answer(*lines)
		if days:
			_, image = yahoo.price_history(ticker, days)
		return '\n'.join(lines), image
	if kind == 'p':
		ticker = tickers[0]
		market_data = yahoo.fetch([ticker])
		if ticker not in market_data:
			raise answer.Answer(f"no data found for {ticker}")
		percent, image = yahoo.price_history(ticker, days, graphCache=False)
		percent = float(percent.get(days, percent.get('Max', next(iter(percent.values()), 0))))
		link = links.quote_link(ticker, market_data[ticker]['profile_exchange'], service, days=days)
		return f"{formats.get_emoji(percent)} {market_data[ticker]['profile_title']} ({link}) {formats.signed_percent(round(percent))}", image
	if kind == 'c':
		args = list(tickers) + ([f'{days}d'] if days else ['max'])
		caption, image, *_ = history.prepare_compare(service, args)
		if not image:
			raise answer.Answer(*caption)
		return '\n'.join(caption), image
	if kind == 'f': # performance: tickers = [portfolio name or '']
		payload, image = performance.report(service, days or buttons.MAX_DAYS, tickers[0] or None, interactive=True)
		if not image:
			raise answer.Answer(*(payload or ['no performance data']))
		return '\n'.join(payload), image
	if kind == 'l': # price list: tickers = [threshold, top]
		span = {'interday': True} if period == 'd' else {'days': days or buttons.MAX_DAYS} # 'd' is today's moves: the command's default view, not a 1-day lookback
		payload, image = price.report(service, threshold=float(tickers[0]), interactive=True, top=int(tickers[1]) or None, **span)
		if not image:
			raise answer.Answer(*(payload or ['no price data']))
		return '\n'.join(payload), image
	raise ValueError(f"unknown chart kind {kind}")
