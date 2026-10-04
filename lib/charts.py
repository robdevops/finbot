"""Period buttons (Week | Month | Quarter | Max) for Telegram chart messages, and the rebuild behind them."""
import hashlib
import sys

from lib.config import *
from lib import util
from lib import webhook
from lib import yahoo
from lib import reports

PERIODS = {'w': ('1W', 7), 'm': ('1M', 30), 'q': ('3M', 90), 'y': ('1Y', 365), 'x': ('Max', None)}
BUTTONS = {'h': 'wmqyx', 'p': 'wmqy', 'c': 'wmqyx'} # chart kind -> buttons offered (h=history, p=price, c=compare)
HIGHLIGHT = {'w': '7D', 'm': '1M', 'q': '3M', 'y': '1Y', 'x': 'Max'} # history table row for each button
MAX_CALLBACK_BYTES = 64 # Telegram limit on callback_data
REF_FILE = 'finbot_chart_buttons.json'

def period_for_days(days):
	"""Button key for a day count, if it is one of the button periods."""
	for key, (_, d) in PERIODS.items():
		if d and d == days:
			return key

def _ref(tickers):
	"""Tickers as callback data: inline if it fits, else a short id persisted to disk."""
	inline = ','.join(tickers)
	if len(('c|h|w|' + inline).encode()) <= MAX_CALLBACK_BYTES:
		return inline
	key = hashlib.sha1(inline.encode()).hexdigest()[:10]
	refs = util.json_load(REF_FILE, persist=True) or {}
	if refs.get(key) != tickers:
		refs[key] = tickers
		util.json_write(REF_FILE, refs, persist=True)
	return '#' + key

def resolve(ref):
	if ref.startswith('#'):
		tickers = (util.json_load(REF_FILE, persist=True) or {}).get(ref[1:])
		if not tickers:
			raise KeyError("these buttons have expired, please re-run the command")
		return tickers
	return ref.split(',')

def keyboard(kind, tickers, active=None):
	"""Telegram inline keyboard; the active period is marked."""
	ref = _ref(tickers)
	row = []
	for key in BUTTONS[kind]:
		label = PERIODS[key][0]
		row.append({'text': ('● ' + label) if key == active else label, 'callback_data': f"c|{kind}|{key}|{ref}"})
	return {'inline_keyboard': [row]}

def history_payload(ticker, service, highlight=None):
	"""Caption lines for .history: performance table, with the selected interval in bold. Returns (lines, percent table)."""
	market_data = yahoo.fetch_detail(ticker, 600)
	title = market_data.get(ticker, {}).get('profile_title', '')
	ticker_link = util.finance_link(ticker, market_data.get(ticker, {}).get('profile_exchange', ''), service, days=1825, brief=False)
	if ticker not in market_data or 'percent_change' not in market_data[ticker]:
		return [f".history: no data found for ticker {ticker}"], None
	table, _ = yahoo.price_history(ticker, graph=False)
	if isinstance(table, str):
		raise RuntimeError(table)
	lines = [webhook.bold(f"{title} ({ticker_link}) performance history", service)]
	for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
		if interval in table:
			percent = table[interval]
			label = webhook.bold(interval + ':', service)
			if interval == highlight:
				label = '● ' + label
			lines.append(f"{util.get_emoji(percent)} {label} {util.signed_percent(percent)}")
	return lines, table

def build(kind, tickers, period, service='telegram'):
	"""(caption, image) for a chart kind at a button period; period None = the command's default view."""
	days = PERIODS[period][1] if period else None
	if kind == 'h':
		ticker = tickers[0]
		lines, table = history_payload(ticker, service, HIGHLIGHT.get(period or 'x')) # default view is the full history
		if table is None:
			raise RuntimeError(lines[0])
		percent, image = yahoo.price_history(ticker, days) if days else yahoo.price_history(ticker)
		if isinstance(percent, str):
			raise RuntimeError(percent)
		return '\n'.join(lines), image
	if kind == 'p':
		ticker = tickers[0]
		market_data = yahoo.fetch([ticker])
		if ticker not in market_data:
			raise RuntimeError(f"no data found for {ticker}")
		percent, image = yahoo.price_history(ticker, days, graphCache=False)
		if isinstance(percent, str):
			raise RuntimeError(percent)
		percent = float(percent.get(days, percent.get('Max')))
		title = market_data[ticker]['profile_title']
		exchange = market_data[ticker]['profile_exchange']
		if exchange in ('Taipei Exchange', 'CCC') or ticker.startswith('^'):
			link = util.yahoo_link(ticker, service)
		elif config_hyperlinkProvider == 'google':
			link = util.gfinance_link(ticker, exchange, service, days=days)
		else:
			link = util.yahoo_link(ticker, service)
		emoji = '🔻' if percent < 0 else '🔼' if percent > 0 else '▪️'
		return f"{emoji} {title} ({link}) {util.signed_percent(round(percent))}", image
	if kind == 'c':
		args = list(tickers) + ([f'{days}d'] if days else ['max'])
		caption, image = reports.prepare_compare(service, args)
		if not image:
			raise RuntimeError(caption[0])
		return '\n'.join(caption), image
	raise ValueError(f"unknown chart kind {kind}")
