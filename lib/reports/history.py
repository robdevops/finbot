"""Price history: .history (one stock over every period) and .compare (two to six stocks, rebased)."""
import hashlib
import datetime
from lib import config
from lib import cache
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import yahoo

def prepare_compare(service, args):
	"""Compare 2-6 tickers as rebased % change. A trailing time period (3m/1y/90d/ytd) is optional;
	without one, the span is the earliest date covered by every ticker. Returns (caption lines, image, tickers, period days)."""
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
	spec = period_days or ('max' if full_history else 'default')
	cache_key = hashlib.sha1(f"{service}|{','.join(tickers)}|{spec}".encode()).hexdigest()[:16]
	image_cache_file, caption_cache_file = f"finbot_compare_{cache_key}.png", f"finbot_compare_{cache_key}.json"
	if config.prefs.cache:
		cached_image = cache.read_bytes(image_cache_file)
		cached_caption = cache.read(caption_cache_file)
		if cached_image and cached_caption:
			return cached_caption, cached_image, tickers, period_days
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
		raise RuntimeError("not enough price history in that period to compare")
	span_days = (datetime.datetime.now().date() - start.date()).days
	period_label = formats.days_english(period_days) if period_days and not note else f"{span_days} days"
	by_performance = sorted(cropped, key=lambda item: item[1].iloc[-1] / item[1].iloc[0], reverse=True)
	title = ' vs '.join(t.split('.')[0] for t, _ in by_performance) # best first; line colours stay tied to input order
	subtitle = f"% change over {period_label}, since {start:%d %b %Y}" + note
	image = render.compare_graph([(t.split('.')[0], series) for t, series in cropped], title, subtitle)
	image.seek(0)
	caption = [service.bold(f"{period_label}, since {start:%d %b %Y}") + note]
	results = sorted(((series.iloc[-1] / series.iloc[0] - 1) * 100, t) for t, series in cropped)
	for pct, t in reversed(results):
		link = links.finance_link(t, exchanges[t], service, days=span_days, brief=False)
		caption.append(f"{formats.get_emoji(pct)} {names[t]} ({link}): {pct:+,.1f}%")
	if config.prefs.cache:
		cache.write_bytes(image_cache_file, image)
		cache.write(caption_cache_file, caption)
		image.seek(0)
	return caption, image, tickers, period_days

def history_payload(ticker, service, highlight=None, graph=False):
	"""Caption lines for .history: performance table, with the selected interval in bold. Returns (lines, percent table, image):
	the full history's chart with graph=True (if the graph preference is on), else None."""
	market_data = yahoo.fetch_detail(ticker, 600)
	title = market_data.get(ticker, {}).get('profile_title', '')
	ticker_link = links.finance_link(ticker, market_data.get(ticker, {}).get('profile_exchange', ''), service, days=1825, brief=False)
	if ticker not in market_data or 'percent_change' not in market_data[ticker]:
		return [f".history: no data found for ticker {ticker}"], None, None
	table, image = yahoo.price_history(ticker) if graph else yahoo.price_history(ticker, graph=False)
	lines = [service.bold(f"{title} ({ticker_link}) performance history")]
	for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
		if interval in table:
			percent = table[interval]
			label = service.bold(interval + ':')
			if interval == highlight:
				label = '● ' + label
			lines.append(f"{formats.get_emoji(percent)} {label} {formats.signed_percent(percent)}")
	return lines, table, image
