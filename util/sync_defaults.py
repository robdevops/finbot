#!/usr/bin/env python3
"""Compare the shipped defaults/ with the data dir (DATA_DIR, default var/), or with the directory given by --dest.
Dry run by default. Every file is reported as copied, replaced or skipped. --apply copies files that are missing;
--force also replaces differing files (the old copy is kept as .bak). A destination that does not exist is an error,
unless --create makes it (mode 750). It needs only the standard library, so any python3 runs it."""

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

if __name__ == '__main__':
	os.environ['FINBOT_CHECK_ONLY'] = '1' # importing lib.config must not create the data dirs: --dest names another
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config


def sync(apply=False, force=False, dest=None, create=False):
	"""One (file, outcome) per default: copied / would copy, replaced (old copy kept as .bak), or skipped. A destination
	that does not exist is made (mode 750) with create, when copying; without it, FileNotFoundError."""
	apply = apply or force
	dest_dir = Path(dest or config.env.data_dir)
	if not dest_dir.is_dir():
		if not create:
			raise FileNotFoundError(f'{dest_dir} does not exist: --create makes it')
		if apply:
			dest_dir.mkdir(mode=0o750, parents=True)
	results = []
	for src in sorted((config.REPO_DIR / 'defaults').iterdir()):
		if not src.is_file():
			continue
		if src.name in ('finbot.env', 'schedule.cron'):
			# the startup file is not data: it holds credentials, lives wherever the launcher loads it from, and the bot
			# never reads it; the old schedule is read only to give an upgrade's home chats their jobs (lib/migrate.py)
			continue
		name = src.name
		target = dest_dir / name
		if not target.exists():
			if apply:
				shutil.copy2(src, target)
			results.append((name, 'copied' if apply else 'would copy'))
		elif filecmp.cmp(src, target, shallow=False):
			results.append((name, 'skipped - destination identical'))
		elif name == 'preferences.conf':
			results.append((name, 'skipped - destination differs')) # configured preferences are never replaced
		elif force:
			shutil.copy2(target, str(target) + '.bak')
			shutil.copy2(src, target)
			results.append((name, 'replaced'))
		else:
			results.append((name, 'skipped - destination differs'))
	return results


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument('--apply', action='store_true', help='copy missing files')
	ap.add_argument('--force', action='store_true', help='also replace differing files (keeps .bak); implies --apply')
	ap.add_argument('--dest', metavar='DIR', help='destination directory (default: the data dir, DATA_DIR or var/)')
	ap.add_argument('--create', action='store_true', help='make the destination directory (mode 750) if it is missing')
	args = ap.parse_args()
	print(f"{config.REPO_DIR / 'defaults'} -> {Path(args.dest or config.env.data_dir).resolve()}")
	try:
		results = sync(args.apply or args.force, args.force, args.dest, args.create)
	except FileNotFoundError as e:
		print('sync_defaults:', e, file=sys.stderr)
		sys.exit(2)
	for name, outcome in results:
		label = {'copied': '', 'skipped - destination identical': '',
			'skipped - destination differs': '[differs]'}.get(outcome, f'[{outcome}]')
		print(f"{name} {label}".rstrip())
