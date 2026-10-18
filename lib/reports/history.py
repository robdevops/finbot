"""Price history: .price's two to eight stocks, rebased (.compare and .history are other names for it), and one stock's
price line, which a .price of one stock draws, and whose change over a period the movers list takes."""
import bisect
import datetime
from lib import answer
from lib import buttons
from lib import formats
from lib import links
from lib import render
from lib import yahoo

def prepare_compare(service, tickers, period_days=None):
	"""(caption lines, chart spec): two to eight tickers (Yahoo's symbols) as rebased % change over the last
	`period_days`, else 10 years (as Max is on every chart), from no earlier than the first date every one of them
	covers, titled 'T1 vs T2', the best first."""
	names, exchanges, closes = {}, {}, {}
	for ticker, history in zip(tickers, yahoo.fetch_each(yahoo.price_series, tickers)): # downloaded at the same time
		if isinstance(history, Exception):
			raise history
		names[ticker], exchanges[ticker], closes[ticker] = history
	limiting = max(closes, key=lambda t: closes[t][0][0]) # ticker with the shortest history
	common_start = closes[limiting][0][0]
	requested = formats.today() - datetime.timedelta(days=period_days or buttons.MAX_DAYS)
	start = max(common_start, requested)
	note = f" (limited by {limiting} history)" if period_days and requested < common_start else ''
	cropped = []
	for ticker in tickers:
		rows = closes[ticker]
		before = bisect.bisect_right([day for day, _ in rows], start) # the closes on or before the start date
		base_value = rows[before - 1][1] if before else rows[0][1] # the last of them, else the first close
		cropped.append((ticker, ((start, base_value), *rows[before:])))
	if any(len(rows) < 2 for _, rows in cropped):
		raise answer.Answer("not enough price history in that period to compare")
	span_days = (formats.today() - start).days
	period_label = formats.days_english(period_days) if period_days and not note else f"{span_days} days"
	growth = lambda rows: rows[-1][1] / rows[0][1] # last close over first
	by_performance = sorted(cropped, key=lambda item: growth(item[1]), reverse=True)
	title = ' vs '.join(formats.short_ticker(t) for t, _ in by_performance) # best first; colours keep input order
	subtitle = f"% change over {period_label}, since {start:%-d %b %Y}" + note
	lines = tuple((formats.short_ticker(t), tuple((f"{day:%Y-%m-%d}", float(close)) for day, close in rows))
		for t, rows in cropped)
	chart = render.Chart('compare', title, subtitle, lines)
	caption = [service.bold(f"{period_label}, since {start:%-d %b %Y}") + note]
	results = sorted(((growth(rows) - 1) * 100, t) for t, rows in cropped)
	for pct, t in reversed(results):
		link = links.finance_link(t, exchanges[t], service, days=span_days, brief=False)
		caption.append(f"{formats.get_emoji(pct)} {names[t]} ({link}): {formats.signed_percent(pct, 1)}")
	return caption, chart

def line_chart(ticker, changes, line, days=None):
	"""The line chart of a price_history (its changes and Line), titled with the company and the span; beneath, the
	price and the change over the span, the figures the caption gives. None for a span under 2 days or fewer than 2
	closes."""
	if len(line.closes) < 2 or (days and days < 2):
		return None
	if days:
		span, change = f"{min(days, buttons.MAX_DAYS)} days", changes[days]
	else:
		span = "Max" if "Max" in changes else "10Y"
		change = changes[span]
	arrow = '▲' if change > 0 else '▼' if change < 0 else '■'
	price = ' '.join(filter(None, (formats.price(line.price), line.currency)))
	subtitle = f"{price}   {arrow} {abs(change):,g}%"
	return render.Chart('line', f"{line.name} ({ticker}) {span}", subtitle, line.closes, change=float(change))

def price_line(ticker, days=None, quote=None):
	"""(its changes, its line chart or None) of a ticker over `days`, else over its whole history, to the price of its
	quote (else the chart's): price_history and line_chart."""
	changes, line = yahoo.price_history(ticker, days, quote=quote)
	return changes, line_chart(ticker, changes, line, days)
