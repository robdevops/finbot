"""The pickers: what a chat gets when it types .treemap, .holdings or .price (.compare) with nothing to say
what it is about, or a job runs one so: the answer for the first portfolio or ticker, with buttons for the portfolios
or tickers under it, one message edited as each is pressed (buttons.PickPress). Each answer takes the message over and
leaves the buttons under it, the item shown marked, so another can be picked. The ticker picker is .price's: its
period row ends in +, which opens the tickers to tick."""
from lib import answer
from lib import buttons
from lib import config
from lib import delivery
from lib import log
from lib import render
from lib import sharesight
from lib import watchlist
from lib.reports import holdings

MOST_ITEMS = 100 # items offered, paged: what the mask of ticks in a button's data has room for
CHARTS = 'tc' # the pickers whose answer is a chart

def as_photo(chat, cmd):
	"""Whether a picker's message is a picture with the answer as its caption (the answer's chart, or render.blank where
	there is none to draw): when its answer is a chart, and this chat takes charts (the graph setting on); else text."""
	return cmd in CHARTS and chat.takes_charts and config.settings.graph

def noun(cmd):
	"""What a picker picks: 'portfolio' or 'ticker' (compare's)."""
	return 'ticker' if cmd == 'c' else 'portfolio'

def layout(service, cmd):
	"""(items to a page, items to a row) that a picker's screen has room for: 32 in rows of 4; Discord holds five rows
	of five buttons, so a page leaves a row for the group and page buttons (12 portfolios, 20 tickers)."""
	if service == 'discord':
		return (20, 5) if noun(cmd) == 'ticker' else (12, 4)
	return 32, 4

def items(cmd, chat):
	"""What a picker offers, sorted: portfolio names (a portfolio command), or tickers (compare): the ones
	held, or the chat's (by its key) watchlist where it holds none. Raises answer.Answer where there are none."""
	if noun(cmd) == 'portfolio':
		found = sorted(portfolio.name for portfolio in sharesight.portfolios())
	else:
		found = sorted(sharesight.tickers() or watchlist.tickers(chat))
	if not found:
		raise answer.Answer("No tickers to pick from: .watchlist add SYMBOL adds one")
	return found[:MOST_ITEMS]

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
	"""What a picker answers at first, as (shown, mask): the first portfolio (treemap, holdings), or the first
	ticker (compare), ticked, alphabetically."""
	if cmd == 'c':
		return pack([0]), 0b1
	return 1, 0

def shown_names(cmd, found, shown):
	"""The items a picker's message shows now (shown, as a PickPress has it): none when it shows nothing yet."""
	if cmd == 'c':
		return [found[number] for number in unpack(shown) if 0 <= number < len(found)] if shown else []
	return [found[shown - 1]] if 0 < shown <= len(found) else []

def prime(service, cmd, group, found, index):
	"""Draw, to fill the cache, the charts a button of a treemap picker would ask for: the other groupings of the
	portfolio shown (found[index]) first, then every other portfolio in all, each uploaded ahead to the network's
	preload chat where a setting names one (delivery.preload; one failing stops those uploads). A failure is logged,
	never raised."""
	by = holdings.GROUPS.get(group, 'industry')
	wanted = [(found[index], each) for each in holdings.GROUPS.values() if each != by] + [(name, each)
		for name in found if name != found[index] for each in holdings.GROUPS.values()]
	preloading = True
	for name, by in wanted:
		try:
			_, chart = holdings.prepare_treemap(name, by, service)
			if chart and chart.rows:
				image = render.draw(chart)
				preloading = preloading and delivery.preload(service, image)
		except Exception as e:
			log.warn("priming", cmd, name, by, "failed:", e)

def screen(service, cmd, found, group, period, shown, mask, view, page=0, note=None):
	"""A picker's screen, as (lines, rows): `view` 'p', the first (the portfolios; for tickers the period and the way
	to the tickers), 'm', the tickers', or 'g', a treemap's menu of what to group by; `page` of the items; `shown`
	what the message answers now (an item's number plus one, or compare's tickers, see pack; 0 for nothing yet, as an
	older finbot's holdings began); `mask` has a bit for each ticked ticker. The lines, what to pick, show only where
	there is no answer yet: an answer's caption shows instead. Where the message shows a note, the tickers' screen's
	presses are n, not m: the next one draws the message whole again, which takes the note away (an m press changes
	only the buttons)."""
	per_page, per_row = layout(service, cmd)
	pages = -(-len(found) // per_page)
	page = min(max(page, 0), pages - 1)
	ticked = [i for i in range(len(found)) if mask >> i & 1]
	to_compare = cmd == 'c' and bool(ticked) and pack(ticked) != shown # ticks to show in place of what is shown
	crc = buttons.checksum(found)
	step = 'n' if note else 'm' # the tickers' screen, at a page
	def button(label, act, active=False, **changes):
		"""A button of this screen, whatever it changes (group, period, shown or mask) in its data."""
		now = {'group': group, 'period': period, 'shown': shown, 'mask': mask} | changes
		return buttons.pick_button(label, buttons.PickPress(cmd, now['group'], now['period'], now['shown'],
			now['mask'], act, crc), active)
	rows = []
	if view == 'g': # the treemap's menu: a choice redoes the chart and stays; Back
		chosen = group if group in holdings.GROUPS else 'i'
		menu = {name: button(name.capitalize(), f"q{page}", key == chosen, group=key)
			for key, name in sorted(holdings.GROUPS.items(), key=lambda item: item[1])}
		back = button('◀ Back', f"p{page}")
		return ['Grouped by'], [[menu['country'], menu['currency'], menu['industry']],
			[back, menu['market'], menu['sector']]]
	if cmd == 'c' and view == 'p': # the periods, and + to the tickers
		rows.append([button(buttons.PERIODS[key][0], 'p0', key == period, period=key) for key in buttons.BUTTONS['c']] +
			[button('+', f"{step}0")])
		if to_compare:
			rows.append([button('OK', 'h0')])
	on_page = items_on(found, page, per_page)
	if noun(cmd) == 'portfolio':
		rows += chunks([button(name, f"r{i}", shown == i + 1, shown=i + 1) for i, name in on_page], per_row)
		if cmd == 't':
			rows.append([button(f"Grouped by: {holdings.GROUPS.get(group, 'industry').capitalize()} ▾", f"g{page}")])
	elif view == 'm':
		rows += chunks(ticker_buttons(found, page, per_page, mask, button, lambda ticker: f"✅ {ticker}", step,
			full=len(ticked) >= buttons.MAX_PICKED), per_row)
	nav = [button('◀ Back', 'p0')] if cmd == 'c' and view == 'm' else []
	if pages > 1 and (view == 'm' or noun(cmd) == 'portfolio'): # the page buttons: under the tickers, not above them
		nav += page_buttons(page, pages, step if view == 'm' else 'p', button)
	if view == 'm' and to_compare:
		nav.append(button('OK', 'h0'))
	if nav:
		rows.append(nav)
	if noun(cmd) == 'portfolio':
		heading = f"{service.bold(buttons.PICKERS[cmd].capitalize())}: pick a portfolio"
	else:
		heading = f"Pick up to {buttons.MAX_PICKED} tickers"
	return ([note] if note else []) + [heading + (f" (page {page + 1} of {pages})" if pages > 1 else '')], rows

def items_on(found, page, per_page):
	"""(number, item) of the items on a page."""
	return list(enumerate(found))[page * per_page:(page + 1) * per_page]

def chunks(row, size):
	"""A list of buttons as rows of at most `size`."""
	return [row[i:i + size] for i in range(0, len(row), size)]

def ticker_buttons(found, page, per_page, mask, button, mark, step, full=False):
	"""The buttons of a page of tickers to tick (the .price picker's, the watchlist's Edit): a ticked one (a bit of
	`mask`) is labelled by mark(ticker) and unticks itself; any other ticks itself, or with `full` (no more may be
	ticked) is refused (act f). `button(label, act, **changes)` makes the screen's own button, `changes` the mask it
	asks for; `step` is the act that redraws the screen at `page`."""
	tickers = []
	for i, ticker in items_on(found, page, per_page):
		if mask >> i & 1:
			tickers.append(button(mark(ticker), f"{step}{page}", mask=mask ^ 1 << i))
		elif full:
			tickers.append(button(ticker, f"f{page}"))
		else:
			tickers.append(button(ticker, f"{step}{page}", mask=mask | 1 << i))
	return tickers

def page_buttons(page, pages, act, button):
	"""The < and > buttons of a screen at `page` of `pages`, each pressing `act` at the page it goes to; none for a
	page there is no other side of."""
	return ([button('<', f"{act}{page - 1}")] if page else []) + (
		[button('>', f"{act}{page + 1}")] if page < pages - 1 else [])
