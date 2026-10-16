"""Keeps Sharesight's portfolio list and holdings reports fresh in the cache (scheduled: sharesight_warm), so that a
request never waits on Sharesight. The price histories have their own, yahoo_warm."""
from lib import reports
from lib import log
from lib import config, sharesight

def run():
	"""Fetch afresh the portfolio list and each portfolio's holdings report, which every report starts from: the
	holdings report is cached for performance_cache_seconds (40 minutes by default); the default schedule runs this
	every 30 minutes, and a flush at once. Nothing without Sharesight configured, or with the cache setting off
	(nothing would be kept). A failure is only logged: the caches it would have replaced are served while fresh, and
	the next run tries again. Returns how many portfolios it refreshed."""
	if not (config.settings.cache and sharesight.configured()):
		return 0
	try:
		return len(sharesight.warm())
	except Exception as e:
		log.warn("sharesight_warm: refresh failed:", e)
		return 0

ARGUMENTS = '' # what a scheduled run takes: none

job = reports.no_arguments('sharesight_warm')
