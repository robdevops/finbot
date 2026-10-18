"""Deletes old cache files (scheduled: cleanup [days]); with days=0 it is the cache flush. util/flush.py deletes
them by age too (remove)."""
import os, time
from lib import log
from lib import config
from lib import reports

def run(dest=None, *, days=30):
	"""Delete the cache files (finbot_*) that were last written more than `days` days ago (days=0: all of them, a
	flush); see remove. A system job: it posts nothing (dest)."""
	return remove(before=time.time() - days * 86400)

def remove(before=None, after=None, directory=None):
	"""Delete the cache files (finbot_*) in directory (the cache dir) last written before the time `before`, or after
	the time `after` (epoch seconds; neither: all of them), but not a temp file written in the last minute: that is an
	atomic write in flight (cache.write_file). Nothing else in it, and nothing in the data dir. Returns how many."""
	now = time.time()
	removed = 0
	try:
		entries = list(os.scandir(directory or config.env.cache_dir))
	except FileNotFoundError:
		return 0
	for entry in entries:
		if not (entry.is_file(follow_symlinks=False) and entry.name.startswith('finbot_')):
			continue
		written = entry.stat().st_mtime
		if (before is not None and written >= before) or (after is not None and written <= after):
			continue
		if entry.name.endswith('.tmp') and written > now - 60:
			continue
		try:
			os.unlink(entry.path)
			removed += 1
		except OSError as e:
			log.warn("cleanup: can't remove", entry.path, e)
	return removed

ARGUMENTS = '[DAYS]' # what a scheduled run takes
job = reports.optional_days('cleanup', 'days')
