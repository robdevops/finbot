""".price, .session, .premarket, .postmarket: price moves past a threshold (scheduled: price.py midsession | interday |
premarket | close | <days>)."""
import sys
import datetime

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

def gather(specific_stock=None, days=None):
	"""(tickers, market data) for a price report: Yahoo's quotes; over `days` each holding's Sharesight figure, and for the tickers
	Sharesight has none for (the watchlist) their Yahoo history, fetched together up front."""
	tickers = [markets.transform_to_yahoo(specific_stock)] if specific_stock else watchlist.with_holdings()
	market_data = yahoo.fetch(tickers)
	if config.prefs.demote_volatile: # trigger_bar compares market caps, in US dollars
		yahoo.add_usd_market_caps(market_data)
	# Sharesight reports a holding's performance only for the time it was held: held for 1Y and asked for 5Y, it gives 1Y
	if days and (not specific_stock or config.prefs.performance_use_sharesight):
		for portfolio in sharesight.portfolios():
			for holding in portfolio.performance(days)['report']['holdings']:
				ticker = markets.transform_to_yahoo(holding['instrument']['code'], holding['instrument']['market_code'])
				if ticker in market_data:
					market_data[ticker]['percent_change_period'] = float(holding['capital_gain_percent'])
				elif ticker in tickers:
					print("Notice: price.py:", ticker, "has no data", file=sys.stderr)
		if not specific_stock and not config.prefs.performance_use_sharesight:
			yahoo.prefetch_history([t for t in market_data if 'percent_change_period' not in market_data[t]])
	return tickers, market_data

def needs_beta(quote):
	"""Whether trigger_bar must know this ticker's beta: a small cap between US$150M and US$1B, which counts as volatile when its
	beta is over 1.5. The beta is only in Yahoo's details."""
	return config.prefs.demote_volatile and 1.5e8 <= quote.get('market_cap_usd', float('inf')) < 1e9

def trigger_bar(ticker, quote, threshold, details=None):
	"""The move this ticker needs before it alone sends a scheduled report: more for leveraged ETFs (demote_leveraged) and volatile
	small caps (demote_volatile; their market caps in US dollars), else the threshold itself. details: Yahoo's details of the
	tickers that need_beta, fetched together; without it this ticker's are fetched here."""
	title = quote['profile_title'].lower()
	if config.prefs.demote_leveraged and ('2x' in title or '3x' in title):
		return threshold * 1.3
	cap = quote.get('market_cap_usd')
	if config.prefs.demote_volatile and cap is not None and cap < 1e9:
		if cap < 1e7:
			return threshold * config.prefs.volatility_multiplier * 1.3
		if cap < 1.5e8:
			return threshold * config.prefs.volatility_multiplier
		beta = (yahoo.fetch_detail(ticker) if details is None else details).get(ticker, {}).get('beta')
		if beta is None or beta > 1.5:
			return threshold * config.prefs.volatility_multiplier
	return threshold

def report(service, threshold=None, user='', specific_stock=None, interactive=False, midsession=False, premarket=False, interday=False,
		days=None, close=False, top=None, market=None):
	"""(payload, chart) of the price report for one service: the moves of `threshold` percent or more (or the top and bottom `top`),
	today's, over `days`, at the close, mid-session or pre-market. A scheduled report goes out only when one ticker passes its
	trigger_bar; it then lists every ticker past the threshold. market: gather()'s (tickers, market data), fetched when not given."""
	if threshold is None:
		threshold = config.prefs.price_percent
	tickers, market_data = market or gather(specific_stock, days)
	now = datetime.datetime.now()
	rows = [] # (ticker, percent, report line without its percent)
	exchanges = set()
	states = []
	latest = None # date of the freshest price, for the heading
	graph = None
	triggered = interactive
	for ticker, quote in market_data.items():
		state = quote['marketState']
		states.append(state)
		quoted = datetime.datetime.fromtimestamp(quote['regularMarketTime'])
		latest = max(latest or quoted.date(), quoted.date())
		if midsession and state != 'REGULAR':
			continue # not in session (states: PREPRE PRE REGULAR POST POSTPOST CLOSED)
		if interday and not interactive and now - quoted > datetime.timedelta(days=1):
			continue # a market holiday: no repeat of the last session's moves
		if close and not interactive and (now - quoted > datetime.timedelta(hours=1.5) or state in ('PREPRE', 'PRE', 'REGULAR')):
			continue # its market did not just close
		if premarket:
			percent = quote.get('percent_change_premarket', quote.get('percent_change_postmarket'))
			if percent is None:
				continue
		elif days:
			percent = quote.get('percent_change_period') # Sharesight's figure, for a holding
			if percent is None:
				if config.prefs.performance_use_sharesight:
					continue
				if specific_stock: # the one ticker asked for: no history is reported in one line
					drawn = config.prefs.graph and delivery.takes_charts(service, interactive)
					history, graph = yahoo.price_history(ticker, days, graph=drawn, graphCache=False)
				else:
					try:
						history, _ = yahoo.price_history(ticker, days, graph=False)
					except RuntimeError as e: # no history for this ticker: leave it out of the list
						print(ticker, e, file=sys.stderr)
						continue
				percent = history[days]
		else:
			percent = quote['percent_change']
		percent = float(percent)
		if abs(percent) >= threshold or (specific_stock and interactive):
			exchange = quote['profile_exchange']
			exchanges.add(markets.exchange_human(exchange))
			rows.append((ticker, percent, f"{formats.get_emoji(percent)} {quote['profile_title']} ({links.quote_link(ticker, exchange, service, days=days)})"))
	if not triggered: # a scheduled report: is there a move big enough for its ticker? Small caps' betas are fetched together
		details = yahoo.fetch_details([ticker for ticker, _, _ in rows if needs_beta(market_data[ticker])])
		if not any(abs(percent) >= trigger_bar(ticker, market_data[ticker], threshold, details) for ticker, percent, _ in rows):
			rows = []
	rows.sort(key=lambda row: row[1], reverse=True)
	payload = [f"{line} {formats.signed_percent(round(percent))}" for _, percent, line in rows]
	chart_rows = [(ticker, percent) for ticker, percent, _ in rows]
	label = lambda chart_rows: [(ticker.split('.')[0].removesuffix('-USD'), percent) for ticker, percent in chart_rows]
	if payload and not specific_stock:
		as_of = latest or datetime.date.today()
		on = formats.date_short(as_of, True)
		where = ", ".join(exchanges)
		if midsession:
			heading = f'≥ {threshold:g}% mid-session, {on} ({where})'
		elif premarket:
			heading = f'≥ {threshold:g}% pre-market, {on} ({where})'
		elif close:
			heading = f'≥ {threshold:g}% at close, {on} ({where})'
		elif top:
			heading = f'Top {top} performers {formats.date_range_english(days, as_of) if days else on}'
		elif days:
			heading = f'Price movement {threshold:g}%, {formats.date_range_english(days, as_of)}'
		else:
			heading = f'{threshold:g}% at close, {on}'
		if top:
			bottom = [service.bold(f'Bottom {top}')] + list(reversed(payload[-top:]))
			payload = [service.bold(heading)] + payload[:top] + [''] + bottom
			chart_top = chart_rows[:top]
			chart_bottom = [row for row in reversed(chart_rows[-top:]) if row not in chart_top] # worst first
			if chart_top: # the best, then after a gap the worst, as the caption's two lists
				span = formats.days_english(days, 'in ', 'the past ')
				graph = render.Chart('bars', f"Top & bottom {top}", f"% change {span}",
					(*label(chart_top), ('', None), *label(chart_bottom)))
		else:
			payload.insert(0, service.bold(heading))
			session = 'midsession' if midsession else 'premarket' if premarket else None
			graph = render.Chart('bars', heading, rows=tuple(label(chart_rows)), session=session)
	elif not payload and interactive:
		if specific_stock:
			if midsession:
				payload = [f"{tickers[0]} not found or not in session"]
			elif premarket:
				payload = [f"No premarket price found for {tickers[0]}"]
			else:
				payload = [f"No interday price found for {tickers[0]}"]
		elif premarket:
			payload = [f"No pre-market price movements meet threshold {threshold:g}%"]
		elif midsession:
			if 'REGULAR' not in states:
				payload = [f"{user}, no tracked stocks are currently in session."]
			else:
				payload = [f"{user}, no in-session securities meet threshold {threshold:g}%"]
		else:
			payload = [f"{user}, no price movements meet threshold {threshold:g}%"]
	return payload, graph

def run(dest=None, *, threshold=None, user='', specific_stock=None, midsession=False, premarket=False, interday=False,
		days=None, close=False, top=None):
	"""Post the price report (report() has the modes): to the chat that asked (dest), else to the default chats, with
	its chart and period buttons where they can go."""
	interactive = dest is not None
	if threshold is None:
		threshold = config.prefs.price_percent
	market = gather(specific_stock, days)
	def markup(chat):
		"""A chart's period buttons, where the chat takes buttons: one ticker's chart, and the daily and N-day lists,
		but not the intraday ones."""
		if not chat.takes_buttons:
			return None
		if specific_stock:
			return buttons.keyboard('p', market[0], buttons.period_for_days(days))
		if not (midsession or premarket or close):
			return buttons.keyboard('l', [f"{threshold:g}", str(top or 0)], buttons.period_for_days(days, 'd' if not days else None))
		return None
	for chat in delivery.targets(dest):
		payload, graph = report(chat.dialect, threshold, user, specific_stock, interactive, midsession, premarket,
			interday, days, close, top, market)
		delivery.deliver(chat, delivery.Report(payload, graph, markup(chat) if graph else None))

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case ['midsession' | 'interday' | 'premarket' | 'close' as arg]:
			return f'price.py {arg}', {arg: True}
		case [days] if days.isdigit():
			return f'price.py {days}', {'threshold': 0, 'days': int(days), 'top': 10}
		case _:
			raise ValueError('[midsession|interday|premarket|close|days (int)]')
