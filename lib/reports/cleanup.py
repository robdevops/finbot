"""Deletes old cache files (scheduled: cleanup.py [days]); with days=0 it is the cache flush."""
import os, sys, time
from lib import config

def run(*, days=30):
	"""Delete the cache files (finbot_*) that were last written more than `days` days ago (days=0: all of them, a flush), but not
	a temp file written in the last minute: that is an atomic write in flight (cache.write_file)."""
	now = time.time()
	cutoff = now - days * 86400
	removed = 0
	try:
		entries = list(os.scandir(config.env.cache_dir))
	except FileNotFoundError:
		return 0
	for entry in entries:
		if entry.is_file(follow_symlinks=False) and entry.name.startswith('finbot_') and entry.stat().st_mtime < cutoff:
			if entry.name.endswith('.tmp') and entry.stat().st_mtime > now - 60:
				continue
			try:
				os.unlink(entry.path)
				removed += 1
			except OSError as e:
				print("cleanup: can't remove", entry.path, e, file=sys.stderr)
	return removed

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
	match argv:
		case []:
			return 'cleanup.py', {}
		case [days] if days.isdigit():
			return f'cleanup.py {days}', {'days': int(days)}
		case _:
			raise ValueError('[days]')
