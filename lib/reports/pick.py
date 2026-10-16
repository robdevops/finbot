"""The pickers: what a chat gets when it types .pie, .treemap, .holdings, .history or .compare with nothing to say what
it is about: buttons for the portfolios or tickers, one message edited as each is pressed (buttons.PickPress), the
last press turning it into the answer."""
import hashlib

from lib import answer
from lib import buttons
from lib import config
from lib import sharesight
from lib import watchlist

PER_ROW = {'portfolio': 3, 'ticker': 4} # buttons to a row of items
MOST_ITEMS = 32 # items offered; Discord has room for fewer (DISCORD_ITEMS)
DISCORD_ITEMS = 16 # four rows of four: a fifth row of its 5 holds the way back and the compare button
CHARTS = 'ptyc' # the pickers whose answer is a chart

def as_photo(chat, cmd):
	"""Whether a picker's message is a picture (a 1x1 image whose caption is the picker): when its answer is a chart,
	and this chat takes charts (the graph preference on); else it is text."""
	return cmd in CHARTS and chat.takes_charts and config.prefs.graph

def noun(cmd):
	"""What a picker picks: 'portfolio' or 'ticker'."""
	return 'ticker' if cmd in 'yc' else 'portfolio'

def items(service, cmd, chat):
	"""What a picker offers, sorted: portfolio names (a portfolio command), or tickers (history, compare): the ones
	held, or the chat's watchlist where it holds none. Raises answer.Answer where there are none."""
	if noun(cmd) == 'portfolio':
		found = sorted(portfolio.name for portfolio in sharesight.portfolios())
	else:
		found = sharesight.tickers() or watchlist.tickers(chat)
		found = sorted(found)
	if not found:
		raise answer.Answer("No tickers to pick from: .watchlist add SYMBOL adds one")
	return found[:DISCORD_ITEMS if service == 'discord' else MOST_ITEMS]

def checksum(found):
	"""A short stand-in for a list of items, which tells any change of it."""
	return hashlib.sha1('\n'.join(found).encode()).hexdigest()[:4]

def press(cmd, group, period, mask, act, found):
	"""The PickPress a button of this picker sends, for the list `found` of items."""
	return buttons.PickPress(cmd, group, period, mask, act, checksum(found))

def start(service, cmd, chat, group='0', period='0'):
	"""A picker's first screen: (lines, rows)."""
	return screen(service, cmd, items(service, cmd, chat), group, period, 0, 'p')

def screen(service, cmd, found, group, period, mask, view, note=None):
	"""A picker's screen, as (lines, rows): view 'p', its first (the portfolios, or for tickers the period and a
	button for the tickers' screen), or 'm', the tickers'. `mask` has a bit for each ticked ticker."""
	ticked = [name for i, name in enumerate(found) if mask >> i & 1]
	name = buttons.PICKERS[cmd]
	rows = []
	if period != '0' and view == 'p':
		rows.append([buttons.pick_button(buttons.PERIODS[key][0], press(cmd, group, key, mask, 'p', found),
			key == period) for key in buttons.BUTTONS['c']])
	if cmd == 't' and view == 'p':
		other = 's' if group != 's' else 'i'
		rows.append([buttons.pick_button(f"Group by: {'Sector' if group == 's' else 'Industry'}",
			press(cmd, other, period, mask, 'p', found))])
	if noun(cmd) == 'portfolio':
		heading = f"{service.bold(name.capitalize())}: pick a portfolio"
		rows += chunks([buttons.pick_button(name, press(cmd, group, period, mask, f'r{i}', found))
			for i, name in enumerate(found)], PER_ROW['portfolio'])
	elif view == 'p':
		heading = f"{service.bold(name.capitalize())}: pick " + ('up to 6 tickers' if cmd == 'c' else 'a ticker')
		label = f"Tickers ({len(ticked)}) ▶" if ticked else "Tickers ▶"
		rows.append([buttons.pick_button(label, press(cmd, group, period, mask, 'm', found))])
	else:
		heading = f"{service.bold(name.capitalize())}: pick " + ('up to 6 tickers' if cmd == 'c' else 'a ticker')
		full = len(ticked) >= buttons.MAX_PICKED
		tickers = []
		for i, ticker in enumerate(found):
			if cmd == 'y':
				tickers.append(buttons.pick_button(ticker, press(cmd, group, period, mask, f'r{i}', found)))
			elif mask >> i & 1:
				tickers.append(buttons.pick_button(f"✅ {ticker}", press(cmd, group, period, mask ^ 1 << i, 'm', found)))
			else:
				tickers.append(buttons.pick_button(ticker, press(cmd, group, period, mask, 'f', found) if full else
					press(cmd, group, period, mask | 1 << i, 'm', found)))
		rows += chunks(tickers, PER_ROW['ticker'])
	if cmd == 'c' and len(ticked) >= 2:
		last = [buttons.pick_button('Compare', press(cmd, group, period, mask, 'g', found))]
	else:
		last = []
	if cmd in 'yc' and view == 'm':
		last.insert(0, buttons.pick_button('◀ Back', press(cmd, group, period, mask, 'p', found)))
	elif last:
		rows.append(last)
		last = []
	if last:
		rows.append(last)
	lines = ([note] if note else []) + [heading]
	if ticked:
		lines.append(f"Ticked: {', '.join(ticked)}")
	return lines, rows

def chunks(row, size):
	"""A list of buttons as rows of at most `size`."""
	return [row[i:i + size] for i in range(0, len(row), size)]
