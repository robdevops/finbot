"""A chart with period buttons, built by its kind's builder: the command's first view, and again for the period of a
button pressed, so that both look alike. Each builder takes the network's dialect, the chat's key (the movers list
covers the stocks that chat follows), the period, its days, then what the buttons carry."""
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
	caption = f"{formats.get_emoji(percent)} {title} ({link}) {formats.signed_percent(round(percent))}"
	return caption, chart

def compare_chart(service, chat, period, days, *tickers):
	""".price (and .compare, .history): the stocks' changes over the period, rebased on one chart; one stock's line as
	stock_chart draws it, as .history's was: green or red with the change, filled below."""
	if len(tickers) == 1:
		return stock_chart(service, chat, period, days, tickers[0])
	caption, chart = history.prepare_compare(service, list(tickers), days)
	return '\n'.join(caption), chart

def performance_chart(service, chat, period, days, portfolio):
	""".performance: each portfolio over the period, or the one named ('' for all)."""
	payload, chart = performance.report(service, days or buttons.MAX_DAYS, portfolio or None)
	return '\n'.join(payload), chart

def movers_list_chart(service, chat, period, days, threshold, top):
	""".movers: the moves past `threshold` among the stocks the chat follows, or the top and bottom `top` ('0': not a
	top list), over the period; period 'd' is today's moves, the command's default view, not a lookback of one day."""
	span = {'mode': 'interday'} if period == 'd' else {'mode': 'period', 'days': days or buttons.MAX_DAYS}
	threshold, top = float(threshold), int(top) or None
	found = movers.moves(watchlist.with_holdings(chat), threshold=threshold, interactive=True, **span)
	payload, chart = movers.report(service, found, threshold=threshold, asked=True, top=top, **span)
	if not chart:
		raise answer.Answer(*(payload or ['no price data']))
	return '\n'.join(payload), chart

def trades_list(service, chat, period, days, portfolio):
	""".trades: the buys and sells of the past `days`, in every portfolio or the one named ('' for all); text, with no
	chart."""
	return '\n'.join(trades.listing(service, days or buttons.MAX_DAYS, portfolio or None)), None

TEXT = 'r' # the kinds whose answer is text alone: the period buttons edit the message's text
BUILDERS = {'c': compare_chart, 'f': performance_chart, 'l': movers_list_chart, 'r': trades_list}

def build(kind, args, service, chat, period=None, days=None):
	"""(caption, chart spec or None) of a chart kind, in a chat (its key), from the arguments its buttons carry
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

def prime(kind, args, service, chat, shown):
	"""Draw, to fill the cache, the chart of each period button of a kind (but `shown`, the period already sent), as a
	press would ask for it, each uploaded ahead as it is drawn to the network's preload chat where a setting names one
	(delivery.Preloader). A period with nothing to draw is skipped, and a failure is logged, never raised. Each
	chart's times are logged (primed)."""
	preloader = delivery.Preloader(service)
	for period in buttons.BUTTONS[kind]:
		if period == shown:
			continue
		try:
			(_, chart), built = timed(build, kind, args, service, chat, period=period)
			if chart and chart.rows:
				image, drew = timed(render.draw, chart)
				preloader.add(image)
				primed(f"{kind} {period}", built, drew)
		except Exception as e:
			log.warn("priming", kind, args, period, "failed:", e)
	preloader.finish()

def prime_in_background(kind, args, service, chat, shown):
	"""Start drawing a chart's other periods, to fill the cache, in a thread of its own (see prime)."""
	threading.Thread(target=prime, args=(kind, args, service, chat, shown), daemon=True).start()
