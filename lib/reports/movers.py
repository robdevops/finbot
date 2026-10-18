""".movers, .session, .premarket, .postmarket: price moves past a threshold (scheduled: movers midsession | interday |
premarket | close | <days>)."""
import dataclasses
import datetime

from lib import answer
from lib import log
from lib import config
from lib import delivery
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import watchlist
from lib import yahoo
from lib import buttons
from lib.reports import history

def gather(tickers, days=None):
	"""The market data of a movers report on tickers (the stocks a chat follows, or the one asked about, Yahoo's
	symbol): Yahoo's quotes, and over `days` each one's change as percent_change_period, from its Yahoo history (the
	change its chart shows), the histories fetched together up front."""
	market_data = yahoo.fetch(tickers)
	if config.settings.demote_volatile: # trigger_bar compares market caps, in US dollars
		yahoo.add_usd_market_caps(market_data)
	if not days:
		return market_data
	yahoo.prefetch_history(list(market_data))
	for ticker in list(market_data):
		try:
			changes, _ = history.price_line(ticker, days, market_data[ticker])
		except RuntimeError as e: # no history: left out of the list
			log.warn(ticker, e)
			continue
		market_data[ticker]['percent_change_period'] = changes[days]
	return market_data

def needs_beta(quote):
	"""Whether trigger_bar must know this ticker's beta: a small cap between US$150M and US$1B, which counts as volatile
	when its beta is over 1.5. The beta is only in Yahoo's details."""
	return config.settings.demote_volatile and 1.5e8 <= quote.get('market_cap_usd', float('inf')) < 1e9

def trigger_bar(ticker, quote, threshold, details):
	"""The move this ticker needs before it alone sends a scheduled report: more for leveraged ETFs (demote_leveraged)
	and volatile small caps (demote_volatile; their market caps in US dollars), else the threshold itself. details:
	Yahoo's details of the tickers that need_beta, fetched together."""
	title = quote['profile_title'].lower()
	if config.settings.demote_leveraged and ('2x' in title or '3x' in title):
		return threshold * 1.3
	cap = quote.get('market_cap_usd')
	if config.settings.demote_volatile and cap is not None and cap < 1e9:
		if cap < 1e7:
			return threshold * config.settings.volatility_multiplier * 1.3
		if cap < 1.5e8:
			return threshold * config.settings.volatility_multiplier
		beta = details.get(ticker, {}).get('beta')
		if beta is None or beta > 1.5:
			return threshold * config.settings.volatility_multiplier
	return threshold

# today's moves, in session, out of it (pre- or post-market), at the close, over `days`
MODES = ('interday', 'midsession', 'premarket', 'close', 'period')
HEADINGS = { # the report's heading, by mode
	'interday': '≥ {threshold:g}% at close, {on}',
	'midsession': '≥ {threshold:g}% mid-session, {on} ({where})',
	'premarket': '≥ {threshold:g}% pre-market, {on} ({where})',
	'close': '≥ {threshold:g}% at close, {on} ({where})',
	'period': 'Price movement ≥ {threshold:g}%, {span}',
}

@dataclasses.dataclass
class Moves:
	"""What a movers report shows, the same for every chat (moves() works it out once): the moves that pass, (ticker,
	percent, quote) best first, the countries of their exchanges, whether a market of the stocks is in session, the date
	of the freshest price."""
	rows: list
	exchanges: set
	in_session: bool
	as_of: datetime.date

def change(mode, quote, now, interactive):
	"""A stock's move in a mode of MODES, or None when it has none to report: not in session (midsession), quoted more
	than a day ago (a market holiday: no repeat of the last session's moves), its market not just closed (close), no
	price out of session (premarket), no change over the period (period)."""
	state = quote['marketState'] # PREPRE PRE REGULAR POST POSTPOST CLOSED
	age = now - datetime.datetime.fromtimestamp(quote['regularMarketTime'])
	if mode == 'midsession':
		return quote['percent_change'] if state == 'REGULAR' else None
	if mode == 'interday':
		return quote['percent_change'] if interactive or age <= datetime.timedelta(days=1) else None
	if mode == 'close':
		just_closed = age <= datetime.timedelta(hours=1.5) and state not in ('PREPRE', 'PRE', 'REGULAR')
		return quote['percent_change'] if interactive or just_closed else None
	if mode == 'premarket':
		return quote.get('percent_change_premarket', quote.get('percent_change_postmarket'))
	return quote.get('percent_change_period')

def moves(tickers, mode='interday', threshold=None, days=None, specific_stock=None, interactive=False):
	"""The Moves of a movers report on tickers (watchlist.covered: the stocks a chat follows, or the one asked about) in
	a mode of MODES ('period': over `days`): each whose move is `threshold` percent or more, or the one stock asked
	about, whatever its move. A scheduled report keeps them only when one passes its trigger_bar."""
	if threshold is None:
		threshold = config.settings.price_percent
	market_data = gather(tickers, days)
	now = datetime.datetime.now()
	rows, exchanges = [], set()
	for ticker, quote in market_data.items():
		percent = change(mode, quote, now, interactive)
		if percent is not None and (abs(float(percent)) >= threshold or (specific_stock and interactive)):
			exchanges.add(markets.exchange_human(quote['profile_exchange']))
			rows.append((ticker, float(percent), quote))
	if not interactive: # scheduled: is a move big enough for its ticker? Small caps' betas are fetched together
		details = yahoo.fetch_details([ticker for ticker, _, quote in rows if needs_beta(quote)])
		if not any(abs(percent) >= trigger_bar(ticker, quote, threshold, details) for ticker, percent, quote in rows):
			rows = []
	rows.sort(key=lambda row: row[1], reverse=True)
	stamps = [quote['regularMarketTime'] for quote in market_data.values()]
	as_of = datetime.datetime.fromtimestamp(max(stamps), formats.zone()).date() if stamps else formats.today()
	in_session = any(quote['marketState'] == 'REGULAR' for quote in market_data.values())
	return Moves(rows, exchanges, in_session, as_of)

def report(service, found, mode='interday', threshold=None, days=None, top=None, user='', specific_stock=None):
	"""(payload, chart) of a movers report in one network's markup, from moves()' Moves: the moves of `threshold`
	percent or more in a mode of MODES ('period': over `days`), or the top and bottom `top`. Raises answer.Nothing where
	none is."""
	if threshold is None:
		threshold = config.settings.price_percent
	lines = [f"{formats.get_emoji(percent)} {formats.short_name(quote['profile_title'])} "
		f"({links.finance_link(ticker, quote['profile_exchange'], service, days=days)}) "
		f"{formats.signed_percent(round(percent))}" for ticker, percent, quote in found.rows]
	if not lines:
		raise answer.Nothing(nothing(mode, threshold, user, specific_stock, found.in_session))
	if specific_stock:
		return lines, None
	label = lambda rows: [(formats.short_ticker(ticker), percent) for ticker, percent, _ in rows]
	on = formats.date_short(found.as_of, True)
	span = formats.date_range_english(days, found.as_of) if days else on
	if not top:
		heading = HEADINGS[mode].format(threshold=threshold, on=on, where=", ".join(found.exchanges), span=span)
		session = mode if mode in ('midsession', 'premarket') else None
		chart = render.Chart('bars', heading, rows=tuple(label(found.rows)), session=session)
		return [service.bold(heading)] + lines, chart
	worst = [i for i in reversed(range(len(found.rows))) if i >= top][:top] # the worst, worst first, none of the best
	payload = [service.bold(f'Top {top} performers {span}')] + lines[:top]
	if worst:
		payload += ['', service.bold(f'Bottom {top}')] + [lines[i] for i in worst]
	period = formats.days_english(days)
	subtitle = f"% change {'' if period == 'today' else 'over '}{period}"
	bars = label(found.rows[:top]) # the best, then after a gap the worst, as the caption's two lists
	if worst:
		bars += [('', None)] + label(found.rows[i] for i in worst)
	return payload, render.Chart('bars', f"Top & bottom {top}", subtitle, tuple(bars))

def nothing(mode, threshold, user, ticker, in_session):
	"""What a chat is told when nothing meets the threshold, or the one ticker asked for (.session, .premarket) has no
	price in this mode."""
	if ticker:
		if mode == 'midsession':
			return f"{ticker} not found or not in session"
		kind = 'premarket' if mode == 'premarket' else 'interday'
		return f"No {kind} price found for {ticker}"
	if mode == 'premarket':
		return f"No pre-market price movements meet threshold {threshold:g}%"
	if mode == 'midsession' and not in_session:
		said = "no tracked stocks are currently in session."
	elif mode == 'midsession':
		said = f"no in-session securities meet threshold {threshold:g}%"
	else:
		said = f"no price movements meet threshold {threshold:g}%"
	return f"{user}, {said}" if user else said[0].upper() + said[1:] # a job run now has no one to name

def run(chat, *, mode='interday', threshold=None, days=None, top=None, user='', specific_stock=None):
	"""Post the movers report (report() has the modes) on the stocks a chat follows, to the chat (a command's or a
	job's), with its chart, and the period buttons of the daily and N-day lists (not the intraday ones) where they can
	go: those buttons' (kind, arguments, the period marked), as charts.prime takes them, or None. Raises answer.Nothing
	where nothing moved."""
	if threshold is None:
		threshold = config.settings.price_percent
	found = moves(watchlist.covered(chat.key, specific_stock), mode, threshold, days, specific_stock,
		delivery.interactive(chat))
	payload, graph = report(chat.dialect, found, mode, threshold, days, top, user, specific_stock)
	attached = ('l', *list_buttons(threshold, top, days)) if graph and mode in ('interday', 'period') else None
	delivery.deliver(chat, delivery.Report(payload, graph, attached and buttons.keyboard(*attached)))
	return attached

def list_buttons(threshold=None, top=None, days=None):
	"""What the movers list's period buttons carry, and the one marked: ([threshold, top], period), as charts.build
	takes them for 'l'. The threshold is the price_percent setting where None, top '0' for no top list, and the period
	1D (today's moves) where no days are given."""
	if threshold is None:
		threshold = config.settings.price_percent
	period = buttons.period_for_days(days, None if days else buttons.DEFAULT_PERIOD['l'])
	return [f"{threshold:g}", str(top or 0)], period

ARGUMENTS = 'midsession|interday|premarket|close|DAYS' # what a scheduled run takes

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case ['midsession' | 'interday' | 'premarket' | 'close' as mode]:
			return f'movers {mode}', {'mode': mode}
		case [days] if days.isdigit():
			return f'movers {days}', {'mode': 'period', 'threshold': 0, 'days': int(days), 'top': 10}
		case _:
			raise ValueError(ARGUMENTS)
