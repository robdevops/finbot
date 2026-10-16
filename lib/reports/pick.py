"""The pickers: what a chat gets when it types .pie, .treemap, .holdings, .history or .compare with nothing to say what
it is about: buttons for the portfolios or tickers, one message edited as each is pressed (buttons.PickPress). An
answer takes the message over and leaves the buttons under it, the item shown marked, so another can be picked."""
import hashlib

from lib import answer
from lib import buttons
from lib import config
from lib import log
from lib import render
from lib import sharesight
from lib import watchlist
from lib.reports import holdings

MOST_ITEMS = 100 # items offered, paged: what the mask of ticks in a button's data has room for
CHARTS = 'ptyc' # the pickers whose answer is a chart

def as_photo(chat, cmd):
	"""Whether a picker's message is a picture (a 1x1 image whose caption is the picker): when its answer is a chart,
	and this chat takes charts (the graph preference on); else it is text."""
	return cmd in CHARTS and chat.takes_charts and config.prefs.graph

def noun(cmd):
	"""What a picker picks: 'portfolio' or 'ticker'."""
	return 'ticker' if cmd in 'yc' else 'portfolio'

def layout(service, cmd):
	"""(items to a page, items to a row) that a picker's screen has room for: 32 in rows of 4; Discord holds five rows
	of five buttons, so a page leaves a row for the group and page buttons (12 portfolios, 20 tickers)."""
	if service == 'discord':
		return (20, 5) if noun(cmd) == 'ticker' else (12, 4)
	return 32, 4

def items(service, cmd, chat):
	"""What a picker offers, sorted: portfolio names (a portfolio command), or tickers (history, compare): the ones
	held, or the chat's watchlist where it holds none. Raises answer.Answer where there are none."""
	if noun(cmd) == 'portfolio':
		found = sorted(portfolio.name for portfolio in sharesight.portfolios())
	else:
		found = sorted(sharesight.tickers() or watchlist.tickers(chat))
	if not found:
		raise answer.Answer("No tickers to pick from: .watchlist add SYMBOL adds one")
	return found[:MOST_ITEMS]

def checksum(found):
	"""A short stand-in for a list of items, which tells any change of it."""
	return hashlib.sha1('\n'.join(found).encode()).hexdigest()[:4]

def pack(numbers):
	"""The numbers of the tickers on show (compare's), as one number for a button's data: two hex digits to each, its
	number plus one; 0 for none."""
	return int(''.join(f'{number + 1:02x}' for number in numbers), 16) if numbers else 0

def unpack(shown):
	"""The numbers of the tickers that pack made `shown` of."""
	text = format(shown, 'x')
	text = text.rjust(len(text) + len(text) % 2, '0')
	return [int(text[i:i + 2], 16) - 1 for i in range(0, len(text), 2)]

def default(cmd, found):
	"""What a picker answers at first, as (shown, mask): the first portfolio (pie, treemap) or ticker (history), or the
	first two tickers (compare), alphabetically; (0, 0) for nothing yet (holdings). Raises answer.Answer where compare
	has fewer than two tickers."""
	if cmd == 'c':
		if len(found) < 2:
			raise answer.Answer("Compare needs two tickers: .watchlist add SYMBOL adds one")
		return pack([0, 1]), 0b11
	return (0, 0) if cmd == 'h' else (1, 0)

def shown_names(cmd, found, shown):
	"""The items a picker's message shows now (shown, as a PickPress has it): none when it shows nothing yet."""
	if cmd == 'c':
		return [found[number] for number in unpack(shown) if 0 <= number < len(found)] if shown else []
	return [found[shown - 1]] if 0 < shown <= len(found) else []

def prime(service, cmd, group, found, index):
	"""Draw, to fill the cache, the charts a button of a pie or treemap picker would ask for: first the other grouping
	of the portfolio shown (found[index]), then every other portfolio in both. A failure is logged, never raised."""
	prepare = holdings.prepare_pie if cmd == 'p' else holdings.prepare_treemap
	other = 'industry' if group == 's' else 'sector'
	wanted = [(found[index], other)] + [(name, by) for name in found if name != found[index]
		for by in ('industry', 'sector')]
	for name, by in wanted:
		try:
			_, chart = prepare(name, by, service)
			if chart and chart.rows:
				render.draw(chart)
		except Exception as e:
			log.warn("priming", cmd, name, by, "failed:", e)

def screen(service, cmd, found, group, period, shown, mask, view, page=0, note=None):
	"""A picker's screen, as (lines, rows): `view` 'p', the first (the portfolios; for tickers the period and the way
	to the tickers), or 'm', the tickers'; `page` of the items; `shown` what the message answers now (an item's number
	plus one, or compare's tickers, see pack; 0 for nothing yet); `mask` has a bit for each ticked ticker."""
	per_page, per_row = layout(service, cmd)
	pages = -(-len(found) // per_page)
	page = min(max(page, 0), pages - 1)
	ticked = [name for i, name in enumerate(found) if mask >> i & 1]
	to_compare = cmd == 'c' and len(ticked) >= 2 and pack([i for i in range(len(found)) if mask >> i & 1]) != shown
	name = buttons.PICKERS[cmd]
	def button(label, act, active=False, **changes):
		"""A button of this screen, whatever it changes (group, period, shown or mask) in its data."""
		state = {'group': group, 'period': period, 'shown': shown, 'mask': mask} | changes
		return buttons.pick_button(label, buttons.PickPress(cmd, state['group'], state['period'], state['shown'],
			state['mask'], act, checksum(found)), active)
	rows = []
	if cmd in 'yc' and view == 'p': # the period, and the way to the tickers
		rows.append([button(buttons.PERIODS[key][0], 'p0', key == period, period=key) for key in buttons.BUTTONS['c']])
		more = ("Select..." + (f" ({len(ticked)})" if ticked else "")) if cmd == 'c' else "Tickers ▶"
		rows.append([button(more, 'm0')] + ([button('Compare', 'h0')] if to_compare else []))
	on_page = items_on(found, page, per_page)
	if noun(cmd) == 'portfolio':
		rows += chunks([button(name, f"r{i}", shown == i + 1, shown=i + 1) for i, name in on_page], per_row)
		if cmd == 't':
			rows.append([button(f"Group by: {'Sector' if group == 's' else 'Industry'}", f"p{page}",
				group='i' if group == 's' else 's')])
	elif view == 'm':
		full = len(ticked) >= buttons.MAX_PICKED
		tickers = []
		for i, ticker in on_page:
			if cmd == 'y':
				tickers.append(button(ticker, f"r{i}", shown == i + 1, shown=i + 1))
			elif mask >> i & 1:
				tickers.append(button(f"✅ {ticker}", f"m{page}", mask=mask ^ 1 << i))
			else:
				tickers.append(button(ticker, f"f{page}") if full else button(ticker, f"m{page}", mask=mask | 1 << i))
		rows += chunks(tickers, per_row)
	nav = [button('◀ Back', 'p0')] if cmd in 'yc' and view == 'm' else []
	if pages > 1 and (view == 'm' or noun(cmd) == 'portfolio'): # the page buttons: under the tickers, not above them
		act = 'm' if view == 'm' else 'p'
		nav += ([button('<', f"{act}{page - 1}")] if page else []) + (
			[button('>', f"{act}{page + 1}")] if page < pages - 1 else [])
	if view == 'm' and to_compare:
		nav.append(button('Compare', f"g{page}"))
	if nav:
		rows.append(nav)
	picks = f'up to {buttons.MAX_PICKED} tickers' if cmd == 'c' else 'a ticker'
	heading = f"{service.bold(name.capitalize())}: pick " + ('a portfolio' if noun(cmd) == 'portfolio' else picks)
	lines = ([note] if note else []) + [heading + (f" (page {page + 1} of {pages})" if pages > 1 else '')]
	if ticked:
		lines.append(f"Ticked: {', '.join(ticked)}")
	return lines, rows

def items_on(found, page, per_page):
	"""(number, item) of the items on a page."""
	return list(enumerate(found))[page * per_page:(page + 1) * per_page]

def chunks(row, size):
	"""A list of buttons as rows of at most `size`."""
	return [row[i:i + size] for i in range(0, len(row), size)]
