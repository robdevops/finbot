"""Period buttons (Week | Month | Quarter | Max) under a chart: their markup, and the callback data that names the tickers."""
import hashlib

from lib import state

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
	with state.edit(REF_FILE, {}) as refs:
		refs[key] = tickers
	return '#' + key

def resolve(ref):
	"""The tickers a button's callback data names: listed inline ('T1,T2'), or a stored list's '#id' (see _ref). Raises
	KeyError when the stored list is gone."""
	if ref.startswith('#'):
		tickers = state.load(REF_FILE, {}).get(ref[1:])
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
