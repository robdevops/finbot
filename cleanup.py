#!/usr/bin/env python3

import os, sys, time
from lib.config import *
from lib import webhook

def lambda_handler(days=30):
	"""Delete the cache files (finbot_*) that were last written more than `days` days ago."""
	cutoff = time.time() - days * 86400
	removed = 0
	try:
		entries = list(os.scandir(config_cache_dir))
	except FileNotFoundError:
		return 0
	for entry in entries:
		if entry.is_file(follow_symlinks=False) and entry.name.startswith('finbot_') and entry.stat().st_mtime < cutoff:
			try:
				os.unlink(entry.path)
				removed += 1
			except OSError as e:
				print("cleanup: can't remove", entry.path, e, file=sys.stderr)
	print(f"cleanup: removed {removed} cache files older than {days} days from {config_cache_dir}")
	return removed

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case []:
			return 'cleanup.py', {}
		case [days] if days.isdigit():
			return f'cleanup.py {days}', {'days': int(days)}
		case _:
			raise ValueError('[days]')

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
