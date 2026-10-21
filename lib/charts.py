"""A chart with period buttons, built by its kind's builder: the command's first view, and again for the period of a
button pressed, so that both look alike. Each builder takes the network's dialect, the chat's key (the movers list
covers the stocks that chat follows), the period, its days, then what the buttons carry, and gives (lines, chart).
And priming: charts drawn ahead of the presses that may ask for them, to fill the cache."""
import functools
import threading
import time

from lib import answer
from lib import buttons
from lib import delivery
from lib import formats
from lib import links
from lib import log
from lib import render
from lib import watchlist
from lib import yahoo
from lib.reports import history, movers, performance, trades

def stock_chart(service, chat, period, days, ticker):
	"""One stock's change over the period (all its history for Max), from Yahoo, and its line: a .price of one."""
	market_data = yahoo.fetch([ticker])
	if ticker not in market_data:
		raise answer.Answer(f"no data found for {ticker}")
	changes, chart = history.price_line(ticker, days, market_data[ticker])
	percent = float(changes.get(days, changes.get('Max', next(iter(changes.values()), 0))))
	link = links.finance_link(ticker, market_data[ticker]['profile_exchange'], service, days=days)
	title = market_data[ticker]['profile_title']
	return [f"{formats.get_emoji(percent)} {title} ({link}) {formats.signed_percent(round(percent))}"], chart

def compare_chart(service, chat, period, days, *tickers):
	""".price (and .compare, .history): the stocks' changes over the period, rebased on one chart; one stock's line as
	stock_chart draws it, as .history's was: green or red with the change, filled below."""
	if len(tickers) == 1:
		return stock_chart(service, chat, period, days, tickers[0])
	return history.prepare_compare(service, list(tickers), days)

def performance_chart(service, chat, period, days, portfolio):
	""".performance: each portfolio over the period, or the one named ('' for all)."""
	return performance.report(service, days or buttons.MAX_DAYS, portfolio or None)

def movers_list_chart(service, chat, period, days, threshold, top):
	""".movers: the moves past `threshold` among the stocks the chat follows, or the top and bottom `top` ('0': not a
	top list), over the period; period 'd' is today's moves, the command's default view, not a lookback of one day."""
	span = {'mode': 'interday'} if period == 'd' else {'mode': 'period', 'days': days or buttons.MAX_DAYS}
	threshold, top = float(threshold), int(top) or None
	found = movers.moves(watchlist.with_holdings(chat), threshold=threshold, interactive=True, **span)
	return movers.report(service, found, threshold=threshold, top=top, **span)

def trades_list(service, chat, period, days, portfolio):
	""".trades: the buys and sells of the past `days`, in every portfolio or the one named ('' for all); text, with no
	chart."""
	return trades.listing(service, days or buttons.MAX_DAYS, portfolio or None), None

TEXT = 'r' # the kinds whose answer is text alone: the period buttons edit the message's text
BUILDERS = {'c': compare_chart, 'f': performance_chart, 'l': movers_list_chart, 'r': trades_list}

def build(kind, args, service, chat, period=None, days=None):
	"""(lines, chart spec or None) of a chart kind, in a chat (its key), from the arguments its buttons carry
	(buttons.keyboard): over a button period, or over `days` (a command's own span: .compare 3m), or the command's
	default view."""
	if kind not in BUILDERS:
		raise ValueError(f"unknown chart kind {kind}")
	return BUILDERS[kind](service, chat, period, buttons.PERIODS[period][1] if period else days, *args)

def timed(function, *args, **kwargs):
	"""(function(*args, **kwargs), the seconds it took)."""
	began = time.monotonic()
	result = function(*args, **kwargs)
	return result, time.monotonic() - began

def primed(what, built, drew):
	"""Log, at debug, how long one chart of a priming took: built (its data) and drew."""
	log.debug(f"priming {what}: built {built:.1f} s, drew {drew:.2f} s")

def periods(kind, args, service, chat, shown):
	"""What prime takes to draw the chart of each period button of a kind, but `shown`, the period already sent."""
	return [(f"{kind} {args} {period}", functools.partial(build, kind, args, service, chat, period=period))
		for period in buttons.BUTTONS[kind] if period != shown]

def prime(service, wanted):
	"""Draw, to fill the cache, the charts that a press may ask for: wanted, (label, build) pairs, build() giving
	(lines, chart) as a press would build it (periods; pick.treemaps). Each is uploaded ahead as it is drawn to the
	network's preload chat where a setting names one (delivery.Preloader). One with nothing to draw is skipped (an
	Answer, at debug), and a failure is logged, never raised. Each chart's times are logged (primed)."""
	preloader = delivery.Preloader(service)
	for label, make in wanted:
		try:
			(_, chart), built = timed(make)
			if chart and chart.drawable:
				image, drew = timed(render.draw, chart)
				preloader.add(image)
				primed(label, built, drew)
		except answer.Answer as e:
			log.debug(f"priming {label}: nothing to draw:", e)
		except Exception as e:
			log.warn(f"priming {label} failed:", e)
	preloader.finish()

def prime_in_background(service, wanted):
	"""Start drawing the charts wanted, to fill the cache, in a thread of its own (see prime)."""
	threading.Thread(target=prime, args=(service, wanted), daemon=True).start()
