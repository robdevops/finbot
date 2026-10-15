"""Price history: .history (one stock over every period) and .compare (two to six stocks, rebased)."""
import datetime
from lib import answer
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import yahoo

def prepare_compare(service, args):
	"""Compare 2-6 tickers as rebased % change. A trailing time period (3m/1y/90d/ytd) is optional;
	without one, the span is the earliest date covered by every ticker. Returns (caption lines, chart spec, tickers,
	period days)."""
	import pandas as pd
	usage = ['Usage: .compare SYMBOL SYMBOL [SYMBOL...up to 6] [period|max]  (default: 10 years)']
	period_days = None
	full_history = False
	args = list(args)
	if args:
		if args[-1].lower() in ('max', 'all'):
			full_history = True
			args.pop()
		else:
			try:
				period_days = formats.days_from_human_days(args[-1])
				args.pop()
			except ValueError:
				pass
	tickers = list(dict.fromkeys(markets.transform_to_yahoo(a.upper()) for a in args)) # de-duplicated, order kept
	if not 2 <= len(tickers) <= 6:
		return usage, None, tickers, period_days
	names, exchanges, closes = {}, {}, {}
	for ticker, history in zip(tickers, yahoo.fetch_each(yahoo.price_series, tickers)): # downloaded at the same time
		if isinstance(history, Exception):
			raise history
		names[ticker], exchanges[ticker], closes[ticker] = history
	limiting = max(closes, key=lambda t: closes[t].index[0]) # ticker with the shortest history
	common_start = closes[limiting].index[0]
	start = common_start
	note = ''
	if not period_days and not full_history: # default window; ask for a longer period (or max) to go further
		default_start = pd.Timestamp(datetime.datetime.now().date() - datetime.timedelta(days=3655))
		start = max(common_start, default_start)
	if period_days:
		requested = pd.Timestamp(datetime.datetime.now().date() - datetime.timedelta(days=period_days))
		if requested >= common_start:
			start = requested
		else:
			note = f" (limited by {limiting} history)"
	cropped = []
	for ticker in tickers:
		series = closes[ticker]
		base = series[series.index <= start]
		base_value = base.iloc[-1] if len(base) else series.iloc[0] # last close on/before the start date
		series = pd.concat([pd.Series([base_value], index=[start]), series[series.index > start]])
		cropped.append((ticker, series))
	if any(len(series) < 2 for _, series in cropped):
		raise answer.Answer("not enough price history in that period to compare")
	span_days = (datetime.datetime.now().date() - start.date()).days
	period_label = formats.days_english(period_days) if period_days and not note else f"{span_days} days"
	by_performance = sorted(cropped, key=lambda item: item[1].iloc[-1] / item[1].iloc[0], reverse=True)
	title = ' vs '.join(t.split('.')[0] for t, _ in by_performance) # best first; line colours stay tied to input order
	subtitle = f"% change over {period_label}, since {start:%d %b %Y}" + note
	lines = tuple((t.split('.')[0], tuple((f"{day:%Y-%m-%d}", float(close)) for day, close in series.items()))
		for t, series in cropped)
	chart = render.Chart('compare', title, subtitle, lines)
	caption = [service.bold(f"{period_label}, since {start:%d %b %Y}") + note]
	results = sorted(((series.iloc[-1] / series.iloc[0] - 1) * 100, t) for t, series in cropped)
	for pct, t in reversed(results):
		link = links.finance_link(t, exchanges[t], service, days=span_days, brief=False)
		caption.append(f"{formats.get_emoji(pct)} {names[t]} ({link}): {formats.signed_percent(pct, 1)}")
	return caption, chart, tickers, period_days

def history_payload(ticker, service, highlight=None, graph=False):
	"""(lines, percent table, chart): .history's caption, the change over every period with the `highlight` one marked,
	and with graph=True the line chart of the whole history (else None). The name and exchange come from the chart."""
	table, line = yahoo.price_history(ticker)
	ticker_link = links.finance_link(ticker, line.exchange, service, days=1825, brief=False)
	lines = [service.bold(f"{line.name} ({ticker_link}) performance history")]
	for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
		if interval in table:
			percent = table[interval]
			label = service.bold(interval + ':')
			if interval == highlight:
				label = '● ' + label
			lines.append(f"{formats.get_emoji(percent)} {label} {formats.signed_percent(percent)}")
	return lines, table, line_chart(ticker, table, line) if graph else None

def line_chart(ticker, changes, line, days=None):
	"""The line chart of a price_history (its changes and Line), titled with the company, the change over the span and
	the last price; None for a span under 2 days or fewer than 2 closes."""
	if len(line.closes) < 2 or (days and days < 2):
		return None
	if days:
		span, change = f"{min(days, 3655)} days", changes[days]
	else:
		span = "Max" if "Max" in changes else "10Y"
		change = changes[span]
	title = f"{line.name} ({ticker}) {span} {formats.signed_percent(change)} Last: {line.price}"
	return render.Chart('line', title, rows=line.closes, unit=line.currency)
