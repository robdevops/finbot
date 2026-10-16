"""Keeps the price history of every stock followed fresh in the cache (scheduled: yahoo_warm), so that a period list
or a chart never waits on Yahoo. Sharesight's caches have their own, sharesight_warm."""
from lib import reports
from lib import log
from lib import config, sharesight, watchlist, yahoo

def run():
	"""Fetch afresh the price history of every stock followed (every chat's watchlist, and the holdings where
	Sharesight is configured), so each is cached for cache_seconds (6 hours by default) from now: the system job runs
	this every 4 hours, before any runs out, and a flush at once. With the cache setting off nothing would be kept,
	so nothing is fetched. Returns how many it fetched."""
	if not config.settings.cache:
		return 0
	tickers = watchlist.all_watched()
	if sharesight.configured():
		try:
			tickers = watchlist.all_followed()
		except Exception as e: # Sharesight unreachable, say: the watchlists' at least
			log.warn("yahoo_warm: no holdings from Sharesight:", e)
	failed = yahoo.prefetch_history(tickers, seconds=0)
	log.info(f"yahoo_warm: {len(tickers) - len(failed)} of {len(tickers)} price histories fetched")
	return len(tickers) - len(failed)

ARGUMENTS = '' # what a scheduled run takes: none

job = reports.no_arguments('yahoo_warm')
