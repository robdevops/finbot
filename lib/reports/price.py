""".price, .session, .premarket, .postmarket: price moves past a threshold (scheduled: price.py midsession | interday |
premarket | close | <days>)."""
import dataclasses
import datetime
import sys

from lib import config
from lib import sharesight
from lib import delivery
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import watchlist
from lib import yahoo
from lib import buttons
from lib.reports import history

def gather(specific_stock=None, days=None):
	"""(tickers, market data, the line chart or None) for a price report on the stocks followed or one (Yahoo's
	symbol): Yahoo's quotes, and over `days` each one's change as percent_change_period: a holding's from Sharesight,
	the others' from Yahoo's history, fetched together up front, with the line chart of the one stock asked about
	(performance_use_sharesight: Sharesight's figures only, and the one stock's even when the others take Yahoo's)."""
	tickers = watchlist.covered(specific_stock)
	market_data = yahoo.fetch(tickers)
	if config.prefs.demote_volatile: # trigger_bar compares market caps, in US dollars
		yahoo.add_usd_market_caps(market_data)
	chart = None
	if not days:
		return tickers, market_data, chart
	# Sharesight reports a holding's performance only for the time it was held: held for 1Y and asked for 5Y, it gives 1Y
	if not specific_stock or config.prefs.performance_use_sharesight:
		for portfolio in sharesight.portfolios():
			for holding in portfolio.performance(days)['report']['holdings']:
				ticker = markets.transform_to_yahoo(holding['instrument']['code'], holding['instrument']['market_code'])
				if ticker in market_data:
					market_data[ticker]['percent_change_period'] = float(holding['capital_gain_percent'])
				elif ticker in tickers:
					print("Notice: price.py:", ticker, "has no data", file=sys.stderr)
	if config.prefs.performance_use_sharesight:
		return tickers, market_data, chart
	missing = [ticker for ticker in market_data if 'percent_change_period' not in market_data[ticker]]
	if not specific_stock:
		yahoo.prefetch_history(missing)
	for ticker in missing:
		try:
			changes, chart = history.price_line(ticker, days, market_data[ticker])
		except RuntimeError as e: # no history: the one stock asked about says so, a list leaves it out
			if specific_stock:
				raise
			print(ticker, e, file=sys.stderr)
			continue
		market_data[ticker]['percent_change_period'] = changes[days]
	if not specific_stock:
		chart = None # the line of one stock only
	return tickers, market_data, chart

def needs_beta(quote):
	"""Whether trigger_bar must know this ticker's beta: a small cap between US$150M and US$1B, which counts as volatile when its
	beta is over 1.5. The beta is only in Yahoo's details."""
	return config.prefs.demote_volatile and 1.5e8 <= quote.get('market_cap_usd', float('inf')) < 1e9

def trigger_bar(ticker, quote, threshold, details):
	"""The move this ticker needs before it alone sends a scheduled report: more for leveraged ETFs (demote_leveraged) and volatile
	small caps (demote_volatile; their market caps in US dollars), else the threshold itself. details: Yahoo's details of the
	tickers that need_beta, fetched together."""
	title = quote['profile_title'].lower()
	if config.prefs.demote_leveraged and ('2x' in title or '3x' in title):
		return threshold * 1.3
	cap = quote.get('market_cap_usd')
	if config.prefs.demote_volatile and cap is not None and cap < 1e9:
		if cap < 1e7:
			return threshold * config.prefs.volatility_multiplier * 1.3
		if cap < 1.5e8:
			return threshold * config.prefs.volatility_multiplier
		beta = details.get(ticker, {}).get('beta')
		if beta is None or beta > 1.5:
			return threshold * config.prefs.volatility_multiplier
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
	"""What a price report shows, the same for every chat (moves() works it out once): the moves that pass, (ticker,
	percent, quote) best first, the countries of their exchanges, whether a market of the stocks is in session, the date
	of the freshest price, and the one stock's line chart, if any."""
	rows: list
	exchanges: set
	in_session: bool
	as_of: datetime.date
	chart: object = None

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

def moves(mode='interday', threshold=None, days=None, specific_stock=None, interactive=False):
	"""The Moves of a price report in a mode of MODES ('period': over `days`): each stock followed whose move is
	`threshold` percent or more, or the one stock asked about, whatever its move. A scheduled report keeps them only
	when one passes its trigger_bar."""
	if threshold is None:
		threshold = config.prefs.price_percent
	_, market_data, chart = gather(specific_stock, days)
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
	as_of = datetime.datetime.fromtimestamp(max(stamps)).date() if stamps else datetime.date.today()
	in_session = any(quote['marketState'] == 'REGULAR' for quote in market_data.values())
	return Moves(rows, exchanges, in_session, as_of, chart)

def report(service, found, mode='interday', threshold=None, days=None, top=None, user='', specific_stock=None,
		interactive=False):
	"""(payload, chart) of a price report in one network's markup, from moves()' Moves: the moves of `threshold` percent
	or more in a mode of MODES ('period': over `days`), or the top and bottom `top`."""
	if threshold is None:
		threshold = config.prefs.price_percent
	lines = [f"{formats.get_emoji(percent)} {quote['profile_title']} "
		f"({links.finance_link(ticker, quote['profile_exchange'], service, days=days)}) "
		f"{formats.signed_percent(round(percent))}" for ticker, percent, quote in found.rows]
	if not lines:
		return [nothing(mode, threshold, user, specific_stock, found.in_session, days)] if interactive else [], None
	if specific_stock:
		return lines, found.chart
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

def nothing(mode, threshold, user, ticker, in_session, days=None):
	"""What a chat is told when nothing meets the threshold, or the one ticker asked for has no price in this mode."""
	if ticker:
		if mode == 'midsession':
			return f"{ticker} not found or not in session"
		if mode == 'period':
			return f"No price change found for {ticker} over {formats.days_english(days)}"
		kind = 'premarket' if mode == 'premarket' else 'interday'
		return f"No {kind} price found for {ticker}"
	if mode == 'premarket':
		return f"No pre-market price movements meet threshold {threshold:g}%"
	if mode == 'midsession' and not in_session:
		return f"{user}, no tracked stocks are currently in session."
	if mode == 'midsession':
		return f"{user}, no in-session securities meet threshold {threshold:g}%"
	return f"{user}, no price movements meet threshold {threshold:g}%"

def run(dest=None, *, mode='interday', threshold=None, days=None, top=None, user='', specific_stock=None):
	"""Post the price report (report() has the modes): to the chat that asked (dest), else to the default chats, with
	its chart and period buttons where they can go."""
	interactive = dest is not None
	if threshold is None:
		threshold = config.prefs.price_percent
	found = moves(mode, threshold, days, specific_stock, interactive)
	def markup(chat):
		"""A chart's period buttons, where the chat takes buttons: one ticker's chart, and the daily and N-day lists,
		but not the intraday ones."""
		if not chat.takes_buttons:
			return None
		if specific_stock:
			return buttons.keyboard('p', [specific_stock], buttons.period_for_days(days))
		if mode in ('interday', 'period'):
			return buttons.keyboard('l', [f"{threshold:g}", str(top or 0)], buttons.period_for_days(days, 'd' if not days else None))
		return None
	for chat in delivery.targets(dest):
		payload, graph = report(chat.dialect, found, mode, threshold, days, top, user, specific_stock, interactive)
		delivery.deliver(chat, delivery.Report(payload, graph, markup(chat) if graph else None))

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case ['midsession' | 'interday' | 'premarket' | 'close' as mode]:
			return f'price.py {mode}', {'mode': mode}
		case [days] if days.isdigit():
			return f'price.py {days}', {'mode': 'period', 'threshold': 0, 'days': int(days), 'top': 10}
		case _:
			raise ValueError('[midsession|interday|premarket|close|days (int)]')
