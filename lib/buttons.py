"""Buttons under a message, what their data says when one is pressed (parse), and what a press is told at once
(toast): a chart's period buttons (1D | 7D | 1M | 1Y | Max), whose data carries what its builder needs
(charts.BUILDERS); the .jobs menu's (menu_button); the pickers of a command typed with nothing to say what it is
about (pick_button); and the rows and page buttons of both (chunks, page_buttons). Each transport draws Button rows
its own way."""
import hashlib
import typing
import zlib

from lib import answer
from lib import state

ON, OFF = 'on', 'off' # a toggle's state, as a button's tone: drawn green and red where the network colours buttons
ACTIVE = 'active' # the look of the button shown now, which a tone overrides


class Button(typing.NamedTuple):
	"""One button: its label, the data a press sends back, whether it is the one shown now (marked), and for a toggle
	its state (tone: ON or OFF; none for any other button)."""
	label: str
	data: str
	active: bool = False
	tone: str = ''


def look(button):
	"""How a network should draw a button: its toggle tone (ON or OFF) if it has one, else ACTIVE for the one shown now,
	else '' for the rest; each transport maps these to its own styles."""
	return button.tone or (ACTIVE if button.active else '')


def tone(on):
	"""A toggle's tone: plain when it is on, OFF (red) when it is off."""
	return '' if on else OFF


class ChartPress(typing.NamedTuple):
	"""A chart's period button pressed: the chart's kind, the period, and its builder's arguments (resolve them)."""
	kind: str
	period: str
	ref: str


class MenuPress(typing.NamedTuple):
	"""A press in the .jobs menu: the screen it asks for, what it says besides (a page, a job's number, the choices of
	Add so far), and the checksum of the list it was drawn for (jobs.list_checksum), stale once the list changes."""
	screen: str
	args: tuple
	checksum: str


class PickPress(typing.NamedTuple):
	"""A press in a picker (lib/reports/pick.py): the command it picks for (a key of PICKERS), how it groups (a
	treemap's: a key of GROUPS, or 0 for neither), the period (a key of PERIODS, or 0), what the message shows
	(shown: 0 nothing yet, an item's number plus one, or the ticked tickers packed), the items ticked (a bit of the mask
	each), what the press asks for (act: a letter of ACTS and a number) and the checksum of the list of items it was
	drawn for, stale once that changes."""
	cmd: str
	group: str
	period: str
	shown: int
	mask: int
	act: str
	checksum: str


MENU_SCREENS = ('top', 'edit', 'run', 'add', 'next')
# the .jobs menu's screens (lib/reports/about.py)


GROUPS = {'s': 'sector', 'i': 'industry', 'c': 'country', 'u': 'currency', 'm': 'market'} # a treemap's menu, by key
PICKERS = {'t': 'treemap', 'h': 'holdings', 'c': 'price', 'w': 'watchlist'} # command key -> its name
MAX_PICKED = 8 # tickers .price takes
TOO_MANY = f"⚠️ Max {MAX_PICKED} tickers: untick one first"


class Act(typing.NamedTuple):
	"""What a picker's press asks for, by the letter of its act (ACTS): the screen it shows (p the first, m the
	tickers', g a treemap's menu of groupings, e the watchlist's editing); what the number after the letter is (PAGE,
	the screen's page; ITEM, an item to answer for, on the screen's page that has it) or that the press acts on the
	ticked items (TICKED), the screen at its first page; the pickers whose buttons have it (keys of PICKERS); whether
	it changes the buttons alone, the answer kept as it is, where the network can (Transport.edit_buttons); and what
	the press is told at once, or refused with (bot.take), the message left as it is."""
	view: str
	on: str
	pickers: str
	alone: bool = False
	toast: str = 'Updating…'
	refused: str = None


PAGE, ITEM, TICKED = 'page', 'item', 'ticked'
ACTS = {
	'p': Act('p', PAGE, 'thcw'), # the first screen (the watchlist's Cancel: its list)
	'm': Act('m', PAGE, 'c', alone=True), # the tickers' screen: a tick, another page
	'n': Act('m', PAGE, 'c'), # as m, under a message showing a note, which it takes away
	'f': Act('m', PAGE, 'c', refused=TOO_MANY), # a tick past MAX_PICKED
	'h': Act('p', TICKED, 'c', toast='Loading…'), # the ticked tickers answered for (OK)
	'r': Act('p', ITEM, 'th', toast='Loading…'), # a portfolio answered for
	'g': Act('g', PAGE, 't', alone=True), # a treemap's menu of groupings
	'q': Act('g', PAGE, 't'), # a grouping chosen in that menu: the chart again, the menu kept
	'e': Act('e', PAGE, 'w'), # the watchlist's editing screen: Edit, a tick, another page
	'd': Act('p', TICKED, 'w'), # the watchlist's ticked tickers deleted (Delete)
}

PERIODS = {'d': ('1D', 1), 'w': ('7D', 7), 'm': ('1M', 30), 'y': ('1Y', 365), 'x': ('Max', None)}
# chart kind -> its buttons, five at most (Discord's limit for a row): c price (one stock's line too), f performance,
# l the movers list, r the trades
BUTTONS = {'c': 'wmyx', 'f': 'wmyx', 'l': 'dwmyx', 'r': 'dwm'}
# each kind's period when none is typed: a stock's whole history (Max; .price's picker starts on 7D), a month of
# performance, today's moves and the day's trades
DEFAULT_PERIOD = {'c': 'x', 'f': 'm', 'l': 'd', 'r': 'd'}
MAX_DAYS = 3650 # what Max means for the Sharesight-based reports
MAX_CALLBACK_BYTES = 64 # Telegram limit on callback_data
REF_FILE = 'finbot_chart_buttons.json'
REF_LIMIT = 500 # the stored argument lists kept: a button older than that says it has expired

def checksum(items):
	"""A short stand-in for a list of strings in a button's data (Telegram allows 64 bytes), which tells any change of
	the list: a button drawn for another list (of a chat's jobs, a picker's items) acts on nothing."""
	return format(zlib.crc32('\n'.join(items).encode()) & 0xffff, '04x')

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
		refs.pop(key, None) # stored again as the newest: a list sent every day must not age out as the oldest
		refs[key] = args
		for old in list(refs)[:-REF_LIMIT]:
			del refs[old]
	return '#' + key

def resolve(ref):
	"""The arguments a button's callback data carries: listed inline ('T1,T2'), or a stored list's '#id' (see _ref).
	Raises answer.Answer when the stored list is gone: the chat is told to send the command again."""
	if ref.startswith('#'):
		args = state.load(REF_FILE, {}).get(ref[1:])
		if not args:
			raise answer.Answer("These buttons have expired: send the command again")
		return args
	return ref.split(',')

def keyboard(kind, args, active=None):
	"""A chart's period buttons, one row, the active period marked. args: what the kind's builder takes
	(charts.BUILDERS): a ticker, tickers, a portfolio, or the movers list's threshold and top, as strings."""
	ref = _ref(args)
	return [[Button(PERIODS[key][0], f"c|{kind}|{key}|{ref}", key == active) for key in BUTTONS[kind]]]

def menu_button(label, screen, args, checksum, tone=''):
	"""A button of the .jobs menu: its label, cut to 40 characters, and its data the screen it asks for, what it says
	besides (words, numbers) and the list's checksum: 'm|on|0|5|a1b2'; tone, a job's state where it is a toggle."""
	return Button(label[:40], '|'.join(['m', screen, *map(str, args), checksum]), tone=tone)

def pick_button(label, press, active=False, tone=''):
	"""A picker's button: its label (cut to 40 characters) and a PickPress as its data: 'k|c|0|x|1|3|p0|a1b2'; tone,
	the state of a ticker's toggle."""
	data = '|'.join(['k', press.cmd, press.group, press.period, format(press.shown, 'x'), format(press.mask, 'x'),
		press.act, press.checksum])
	return Button(label[:40], data, active, tone)

def chunks(row, size):
	"""A list of buttons as rows of at most `size`."""
	return [row[i:i + size] for i in range(0, len(row), size)]

def page_buttons(page, pages, to):
	"""The ◀ and ▶ buttons of a screen at `page` of `pages`, each made by to(label, the page it goes to); none for a
	side with no page."""
	return ([to('◀', page - 1)] if page else []) + ([to('▶', page + 1)] if page < pages - 1 else [])

def parse(data):
	"""What a pressed button's data asks for: a PickPress for a picker's button of a known command, with an act its
	buttons have (ACTS); a MenuPress for a .jobs menu's button of a known screen, its parts plain letters and digits; a
	ChartPress for a period button of a known kind and period; or None for data of none of them (from an older finbot,
	or forged)."""
	kind, _, rest = data.partition('|')
	if kind == 'k':
		parts = rest.split('|')
		if (len(parts) == 7 and parts[0] in PICKERS and parts[1] in ('0', *GROUPS) and (parts[2] in PERIODS or
				parts[2] == '0') and len(parts[3]) <= 2 * MAX_PICKED and len(parts[4]) <= 25 and
				parts[5][:1] in ACTS and parts[0] in ACTS[parts[5][0]].pickers and
				parts[5][1:].isdigit() and all(part.isascii() and part.isalnum() for part in parts) and
				len(data.encode()) <= MAX_CALLBACK_BYTES):
			try:
				return PickPress(parts[0], parts[1], parts[2], int(parts[3], 16), int(parts[4], 16), parts[5],
					parts[6])
			except ValueError:
				return None
		return None
	if kind == 'm':
		parts = rest.split('|')
		if (len(parts) >= 2 and parts[0] in MENU_SCREENS and len(data.encode()) <= MAX_CALLBACK_BYTES and
				all(part.isascii() and part.isalnum() for part in parts[1:])):
			return MenuPress(parts[0], tuple(parts[1:-1]), parts[-1])
		return None
	parts = rest.split('|', 2)
	if kind == 'c' and len(parts) == 3 and parts[0] in BUTTONS and parts[1] in BUTTONS[parts[0]]:
		return ChartPress(*parts)
	return None

def refusal(data):
	"""What a press is refused with, from the button's data alone: a picker's act's (TOO_MANY for a tick past
	MAX_PICKED), else None."""
	pressed = parse(data)
	return ACTS[pressed.act[0]].refused if isinstance(pressed, PickPress) else None

def toast(data):
	"""What a press is told at once, from the button's data alone (the network acknowledges a press before finbot
	knows more): 'Loading 1Y…' for a period button, 'Updating…' for the .jobs menu's, a picker's act's ('Loading…' or
	'Updating…'), None for data of none of them."""
	pressed = parse(data)
	if isinstance(pressed, PickPress):
		return ACTS[pressed.act[0]].toast
	if isinstance(pressed, MenuPress):
		return 'Updating…'
	return f"Loading {PERIODS[pressed.period][0]}…" if pressed else None
