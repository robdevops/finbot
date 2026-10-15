"""Buttons under a message: the period buttons (1D | 7D | 1M | 1Y | Max) of a chart, and the callback data that carries
what its builder needs (charts.BUILDERS). Each transport draws Button rows its own way."""
import hashlib
import typing

from lib import state

class Button(typing.NamedTuple):
	"""One button: its label, the data a press sends back, and whether it is the one shown now (marked)."""
	label: str
	data: str
	active: bool = False


PERIODS = {'d': ('1D', 1), 'w': ('7D', 7), 'm': ('1M', 30), 'y': ('1Y', 365), 'x': ('Max', None)}
BUTTONS = {'h': 'wmyx', 'p': 'wmyx', 'c': 'wmyx', 'f': 'wmyx', 'l': 'dwmyx'} # chart kind -> its buttons, five at most
# (Discord's limit for a row): h history, p a stock's price chart, c compare, f performance, l the price list
MAX_DAYS = 3650 # what Max means for the Sharesight-based reports
MAX_CALLBACK_BYTES = 64 # Telegram limit on callback_data
REF_FILE = 'finbot_chart_buttons.json'
REF_LIMIT = 500 # the stored argument lists kept: a button older than that says it has expired

def period_for_days(days, default=None):
	"""Button key for a day count, if it is one of the button periods; `default` when it is not (or days is None)."""
	for key, (_, d) in PERIODS.items():
		if d and d == days:
			return key
	return default

def _ref(args):
	"""A builder's arguments as callback data: inline if they fit, else a short id of the list, stored on disk with the
	newest REF_LIMIT others."""
	inline = ','.join(args)
	if len(('c|h|w|' + inline).encode()) <= MAX_CALLBACK_BYTES:
		return inline
	key = hashlib.sha1(inline.encode()).hexdigest()[:10]
	with state.edit(REF_FILE, {}) as refs:
		refs[key] = args
		for old in list(refs)[:-REF_LIMIT]:
			del refs[old]
	return '#' + key

def resolve(ref):
	"""The arguments a button's callback data carries: listed inline ('T1,T2'), or a stored list's '#id' (see _ref).
	Raises KeyError when the stored list is gone."""
	if ref.startswith('#'):
		args = state.load(REF_FILE, {}).get(ref[1:])
		if not args:
			raise KeyError("these buttons have expired, please re-run the command")
		return args
	return ref.split(',')

def keyboard(kind, args, active=None):
	"""A chart's period buttons, one row, the active period marked. args: what the kind's builder takes
	(charts.BUILDERS): a ticker, tickers, a portfolio, or a price list's threshold and top, as strings."""
	ref = _ref(args)
	return [[Button(PERIODS[key][0], f"c|{kind}|{key}|{ref}", key == active) for key in BUTTONS[kind]]]
