"""Keeps Sharesight's portfolio list and holdings reports fresh in the cache (scheduled: sharesight_warm.py), so that a
request never waits on Sharesight. The price histories have their own, yahoo_warm.py."""
import sys
from lib import config, sharesight

def run():
	"""Fetch afresh the portfolio list and each portfolio's holdings report, which every report starts from: the
	holdings report is cached for performance_cache_seconds (40 minutes by default), and the default schedule runs
	this every 30 minutes. Nothing without Sharesight configured, or with the cache preference off (nothing would be
	kept). A failure is only logged: the caches it would have replaced are served while fresh, and the next run tries
	again. Returns how many portfolios it refreshed."""
	if not (config.prefs.cache and config.env.sharesight_auth.get('client_id')):
		return 0
	try:
		return len(sharesight.warm())
	except Exception as e:
		print("sharesight_warm: refresh failed:", e, file=sys.stderr)
		return 0

def job(argv):
	"""Arguments of a scheduled run: sharesight_warm.py takes none."""
	return 'sharesight_warm.py', {}
