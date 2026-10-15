"""A period button pressed: the chart rebuilt for that period. And the Telegram command keyboard, kept current in every DM."""
import hashlib
import json
import sys

from lib import answer
from lib import buttons
from lib import formats
from lib import links
from lib import state
from lib import transports
from lib import yahoo
from lib.reports import history, performance, price

COMMAND_BUTTONS = sorted(['.beta', '.buy & sell', '.dividend', '.earnings', '.forward pe', '.marketcap', '.pe', '.peg', '.performance', '.premarket',
	'.price', '.session', '.shorts', '.trades', '.watchlist']) # alphabetical, row by row; '.buy & sell' sends both rating reports

def command_keyboard(per_row=3):
	"""Persistent reply keyboard of the common commands (Telegram DMs); a press sends the command text as a message."""
	rows = [[{'text': c} for c in COMMAND_BUTTONS[i:i + per_row]] for i in range(0, len(COMMAND_BUTTONS), per_row)]
	return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}

KEYBOARD_FILE = 'finbot_keyboards.json' # chat id -> version of the command keyboard that chat last received

def keyboard_version():
	"""A short hash of the command keyboard, which changes whenever its buttons do."""
	return hashlib.sha1(json.dumps(command_keyboard(), sort_keys=True).encode()).hexdigest()[:8]

def mark_keyboard(chat_id):
	"""Record that this chat now has the current command keyboard."""
	with state.edit(KEYBOARD_FILE, {}) as versions:
		versions[str(chat_id)] = keyboard_version()

def push_keyboard(chat_id):
	"""Telegram can only change a reply keyboard by sending a message, so send a short one carrying it."""
	result = transports.TelegramBot(chat_id).post_text('⌨️ Keyboard updated', command_keyboard())
	if result is not None:
		mark_keyboard(chat_id)
	return result

def ensure_keyboard(chat_id):
	"""DMs only (positive chat ids): bring a chat's keyboard up to date if its buttons have changed or it never had them."""
	if int(chat_id) <= 0:
		return
	if state.load(KEYBOARD_FILE, {}).get(str(chat_id)) != keyboard_version():
		push_keyboard(chat_id)

def refresh_keyboards():
	"""At startup: update every chat we know of whose keyboard is out of date."""
	for chat_id, version in state.load(KEYBOARD_FILE, {}).items():
		if version != keyboard_version():
			try:
				push_keyboard(chat_id)
			except Exception as e:
				print("keyboard refresh failed for", chat_id, e, file=sys.stderr)

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
