"""Buttons under a message, what their data says when one is pressed (parse), and what a press is told at once
(toast): a chart's period buttons (1D | 7D | 1M | 1Y | Max), whose data carries what its builder needs
(charts.BUILDERS); the .jobs menu's (menu_button); and the job buttons of older .jobs lists, which still work. Each
transport draws Button rows its own way."""
import hashlib
import typing

from lib import state

class Button(typing.NamedTuple):
	"""One button: its label, the data a press sends back, and whether it is the one shown now (marked)."""
	label: str
	data: str
	active: bool = False


class ChartPress(typing.NamedTuple):
	"""A chart's period button pressed: the chart's kind, the period, and its builder's arguments (resolve them)."""
	kind: str
	period: str
	ref: str


class JobPress(typing.NamedTuple):
	"""A job's button pressed: the job's number in its chat's list and its checksum, both for jobs.Scheduler.pick to
	check, and what to do with it: run it now, or switch it on or off (toggle)."""
	number: str
	checksum: str
	action: str = 'run'


class MenuPress(typing.NamedTuple):
	"""A press in the .jobs menu: the screen it asks for, what it says besides (a page, a job's number, the choices of
	Add so far), and the checksum of the list it was drawn for (jobs.list_checksum), stale once the list changes."""
	screen: str
	args: tuple
	checksum: str


JOB_ACTIONS = {'j': 'run', 'e': 'toggle'} # an older job button's kind, its data's first letter, and what it does
MENU_SCREENS = ('top', 'on', 'del', 'run', 'add', 'next') # the .jobs menu's screens (lib/reports/about.py)


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

def menu_button(label, screen, args, checksum):
	"""A button of the .jobs menu: its label, cut to 40 characters, and its data the screen it asks for, what it says
	besides (words, numbers) and the list's checksum: 'm|on|0|5|a1b2'."""
	return Button(label[:40], '|'.join(['m', screen, *map(str, args), checksum]))

def parse(data):
	"""What a pressed button's data asks for: a MenuPress for a .jobs menu's button of a known screen, its parts plain
	letters and digits; a JobPress for an older job button (whatever follows 'j|' or 'e|', which pick refuses unless
	it is a job's number and checksum); a ChartPress for a period button of a known kind and period; or None for data
	of none of them (from an older finbot, or forged)."""
	kind, _, rest = data.partition('|')
	if kind == 'm':
		parts = rest.split('|')
		if (len(parts) >= 2 and parts[0] in MENU_SCREENS and len(data.encode()) <= MAX_CALLBACK_BYTES and
				all(part.isascii() and part.isalnum() for part in parts[1:])):
			return MenuPress(parts[0], tuple(parts[1:-1]), parts[-1])
		return None
	if kind in JOB_ACTIONS:
		number, _, checksum = rest.partition('|')
		return JobPress(number, checksum, JOB_ACTIONS[kind])
	parts = rest.split('|', 2)
	if kind == 'c' and len(parts) == 3 and parts[0] in BUTTONS and parts[1] in BUTTONS[parts[0]]:
		return ChartPress(*parts)
	return None

def toast(data):
	"""What a press is told at once, from the button's data alone (the network acknowledges a press before finbot
	knows more): 'Loading 1Y…' for a period button, 'Updating…' for the .jobs menu's, 'Running…' or 'Switching…' for an
	older job button, None for data of none of them."""
	pressed = parse(data)
	if isinstance(pressed, MenuPress):
		return 'Updating…'
	if isinstance(pressed, JobPress):
		return 'Running…' if pressed.action == 'run' else 'Switching…'
	return f"Loading {PERIODS[pressed.period][0]}…" if pressed else None
