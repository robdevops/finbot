"""Keeps the price history of every stock followed fresh in the cache (scheduled: yahoo_warm.py), so that a period list
or a chart never waits on Yahoo. Sharesight's caches have their own, sharesight_warm.py."""
import sys
from lib import config, watchlist, yahoo

def run():
	"""Fetch afresh the price history of every stock followed (the watchlist, and the holdings where Sharesight is
	configured), so each is cached for cache_seconds (12 hours by default) from now: the default schedule runs this
	every 8 hours, before any runs out, and a flush at once. With the cache preference off nothing would be kept, so
	nothing is fetched. Returns how many it fetched."""
	if not config.prefs.cache:
		return 0
	tickers = watchlist.tickers()
	if config.env.sharesight_auth.get('client_id'):
		try:
			tickers = watchlist.with_holdings()
		except Exception as e: # Sharesight unreachable, say: the watchlist's at least
			print("yahoo_warm: no holdings from Sharesight:", e, file=sys.stderr)
	failed = yahoo.prefetch_history(tickers, seconds=0)
	print(f"yahoo_warm: {len(tickers) - len(failed)} of {len(tickers)} price histories fetched", file=sys.stderr)
	return len(tickers) - len(failed)

def job(argv):
	"""Arguments of a scheduled run: yahoo_warm.py takes none."""
	return 'yahoo_warm.py', {}
