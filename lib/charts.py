"""Period buttons (Week | Month | Quarter | Max) for Telegram chart messages, and the rebuild behind them."""
import hashlib
import json
import sys
import threading

from lib import util
from lib import webhook
from lib import yahoo
from lib import reports

PERIODS = {'d': ('1D', 1), 'w': ('7D', 7), 'm': ('1M', 30), 'q': ('3M', 90), 'y': ('1Y', 365), 'x': ('Max', None)}
BUTTONS = {'h': 'wmqyx', 'p': 'wmqyx', 'c': 'wmqyx', 'f': 'wmqyx', 'l': 'dwmqyx'} # chart kind -> buttons offered (h=history, p=price chart, c=compare, f=performance, l=price list)
MAX_DAYS = 3650 # what Max means for the Sharesight-based reports
MAX_CALLBACK_BYTES = 64 # Telegram limit on callback_data
REF_FILE = 'finbot_chart_buttons.json'

def period_for_days(days, default=None):
	"""Button key for a day count, if it is one of the button periods; `default` when it is not (or days is None)."""
	for key, (_, d) in PERIODS.items():
		if d and d == days:
			return key
	return default

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

COMMAND_BUTTONS = sorted(['.watchlist', '.dividend', '.earnings', '.marketcap', '.beta', '.performance', '.price', '.session', '.premarket', '.buy', '.sell', '.pe', '.peg', '.shorts', '.trades'])

def command_keyboard(per_row=3):
	"""Persistent reply keyboard of the common commands (Telegram DMs); a press sends the command text as a message."""
	rows = [[{'text': c} for c in COMMAND_BUTTONS[i:i + per_row]] for i in range(0, len(COMMAND_BUTTONS), per_row)]
	return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}

KEYBOARD_FILE = 'finbot_keyboards.json' # chat id -> version of the command keyboard that chat last received
_keyboard_lock = threading.Lock()

def keyboard_version():
	return hashlib.sha1(json.dumps(command_keyboard(), sort_keys=True).encode()).hexdigest()[:8]

def mark_keyboard(chat_id):
	"""Record that this chat now has the current command keyboard."""
	with _keyboard_lock:
		state = util.json_load(KEYBOARD_FILE, persist=True) or {}
		state[str(chat_id)] = keyboard_version()
		util.json_write(KEYBOARD_FILE, state, persist=True)

def push_keyboard(chat_id):
	"""Telegram can only change a reply keyboard by sending a message, so send a short one carrying it."""
	result = webhook.write('telegram', webhook.chat_url('telegram', chat_id), '⌨️ Keyboard updated', chat_id, reply_markup=command_keyboard())
	if result is not None:
		mark_keyboard(chat_id)
	return result

def ensure_keyboard(chat_id):
	"""DMs only (positive chat ids): bring a chat's keyboard up to date if its buttons have changed or it never had them."""
	if int(chat_id) <= 0:
		return
	with _keyboard_lock:
		current = (util.json_load(KEYBOARD_FILE, persist=True) or {}).get(str(chat_id)) == keyboard_version()
	if not current:
		push_keyboard(chat_id)

def refresh_keyboards():
	"""At startup: update every chat we know of whose keyboard is out of date."""
	with _keyboard_lock:
		state = util.json_load(KEYBOARD_FILE, persist=True) or {}
	for chat_id, version in state.items():
		if version != keyboard_version():
			try:
				push_keyboard(chat_id)
			except Exception as e:
				print("keyboard refresh failed for", chat_id, e, file=sys.stderr)

def keyboard(kind, tickers, active=None):
	"""Telegram inline keyboard; the active period is marked."""
	ref = _ref(tickers)
	row = []
	for key in BUTTONS[kind]:
		label = PERIODS[key][0]
		row.append({'text': ('● ' + label) if key == active else label, 'callback_data': f"c|{kind}|{key}|{ref}"})
	return {'inline_keyboard': [row]}

def history_payload(ticker, service, highlight=None, graph=False):
	"""Caption lines for .history: performance table, with the selected interval in bold. Returns (lines, percent table, image):
	the full history's chart with graph=True (if the graph preference is on), else None."""
	market_data = yahoo.fetch_detail(ticker, 600)
	title = market_data.get(ticker, {}).get('profile_title', '')
	ticker_link = util.finance_link(ticker, market_data.get(ticker, {}).get('profile_exchange', ''), service, days=1825, brief=False)
	if ticker not in market_data or 'percent_change' not in market_data[ticker]:
		return [f".history: no data found for ticker {ticker}"], None, None
	table, image = yahoo.price_history(ticker) if graph else yahoo.price_history(ticker, graph=False)
	lines = [webhook.bold(f"{title} ({ticker_link}) performance history", service)]
	for interval in ('Max', '10Y', '5Y', '3Y', '1Y', 'YTD', '6M', '3M', '1M', '7D', '1D'):
		if interval in table:
			percent = table[interval]
			label = webhook.bold(interval + ':', service)
			if interval == highlight:
				label = '● ' + label
			lines.append(f"{util.get_emoji(percent)} {label} {util.signed_percent(percent)}")
	return lines, table, image

def build(kind, tickers, period, service='telegram'):
	"""(caption, image) for a chart kind at a button period; period None = the command's default view."""
	days = PERIODS[period][1] if period else None
	if kind == 'h':
		ticker = tickers[0]
		lines, table, image = history_payload(ticker, service, PERIODS[period or 'x'][0], graph=not days) # default view is the full history
		if table is None:
			raise RuntimeError(lines[0])
		if days:
			_, image = yahoo.price_history(ticker, days)
		return '\n'.join(lines), image
	if kind == 'p':
		ticker = tickers[0]
		market_data = yahoo.fetch([ticker])
		if ticker not in market_data:
			raise RuntimeError(f"no data found for {ticker}")
		percent, image = yahoo.price_history(ticker, days, graphCache=False)
		percent = float(percent.get(days, percent.get('Max', next(iter(percent.values()), 0))))
		link = util.quote_link(ticker, market_data[ticker]['profile_exchange'], service, days=days)
		return f"{util.get_emoji(percent)} {market_data[ticker]['profile_title']} ({link}) {util.signed_percent(round(percent))}", image
	if kind == 'c':
		args = list(tickers) + ([f'{days}d'] if days else ['max'])
		caption, image, *_ = reports.prepare_compare(service, args)
		if not image:
			raise RuntimeError(caption[0])
		return '\n'.join(caption), image
	if kind == 'f': # performance: tickers = [portfolio name or '']
		import performance
		payload, image = performance.report(service, days or MAX_DAYS, tickers[0] or None, interactive=True)
		if not image:
			raise RuntimeError(payload[0] if payload else 'no performance data')
		return '\n'.join(payload), image
	if kind == 'l': # price list: tickers = [threshold, top]
		import price
		span = {'interday': True} if period == 'd' else {'days': days or MAX_DAYS} # 'd' is today's moves: the command's default view, not a 1-day lookback
		payload, image = price.report(service, threshold=float(tickers[0]), interactive=True, top=int(tickers[1]) or None, **span)
		if not image:
			raise RuntimeError(payload[0] if payload else 'no price data')
		return '\n'.join(payload), image
	raise ValueError(f"unknown chart kind {kind}")
