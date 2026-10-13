#!/usr/bin/env python3
"""Compare the shipped defaults/ with the data dir (DATA_DIR, default var/), or with the directory given by --dest.
Dry run by default. Existing files are skipped and not listed. --apply copies files that are missing;
--force also lists and overwrites differing files (the old copy is kept as .bak)."""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config
from lib.config import REPO_DIR


def sync(apply=False, force=False, dest=None):
	apply = apply or force
	dest_dir = Path(dest or config.config_var_dir)
	changes = []
	for src in sorted((REPO_DIR / 'defaults').iterdir()):
		if not src.is_file():
			continue
		if src.name == 'finbot.env':
			continue # the startup file is not data: it holds credentials, lives wherever the launcher loads it from, and the bot never reads it
		name = src.name
		dest = dest_dir / name
		if not dest.exists():
			status = 'missing'
		elif filecmp.cmp(src, dest, shallow=False):
			continue
		elif not force:
			continue # existing files are skipped unless --force
		else:
			status = 'differs'
		if name == 'preferences.conf' and status == 'differs':
			continue # configured preferences are never replaced
		changes.append((name, status))
		if apply and (status == 'missing' or force):
			dest_dir.mkdir(parents=True, exist_ok=True)
			if status == 'differs':
				shutil.copy2(dest, str(dest) + '.bak')
			shutil.copy2(src, dest)
	return changes


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument('--apply', action='store_true', help='copy missing files')
	ap.add_argument('--force', action='store_true', help='also overwrite differing files (keeps .bak); implies --apply')
	ap.add_argument('--dest', metavar='DIR', help='destination directory (default: the data dir, DATA_DIR or var/)')
	args = ap.parse_args()
	print(f"{REPO_DIR / 'defaults'} -> {Path(args.dest or config.config_var_dir).resolve()}")
	changes = sync(args.apply or args.force, args.force, args.dest)
	for name, status in changes:
		done = args.force or (args.apply and status == 'missing')
		print(('updated ' if done else 'would update ') + name + ' (' + status + ')')
	if not changes:
		print('nothing to copy: every default already exists there' + ('' if args.force else ' (existing files are skipped; --force overwrites those that differ)'))
