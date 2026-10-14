#!/usr/bin/env python3
"""Compare the shipped defaults/ with the data dir (DATA_DIR, default var/), or with the directory given by --dest.
Dry run by default. Every file is reported as copied, replaced or skipped. --apply copies files that are missing;
--force also replaces differing files (the old copy is kept as .bak)."""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config


def sync(apply=False, force=False, dest=None):
	"""One (file, outcome) per default: copied / would copy, replaced (old copy kept as .bak), or skipped."""
	apply = apply or force
	dest_dir = Path(dest or config.env.data_dir)
	results = []
	for src in sorted((config.REPO_DIR / 'defaults').iterdir()):
		if not src.is_file():
			continue
		if src.name == 'finbot.env':
			continue # the startup file is not data: it holds credentials, lives wherever the launcher loads it from, and the bot never reads it
		name = src.name
		target = dest_dir / name
		if not target.exists():
			if apply:
				dest_dir.mkdir(parents=True, exist_ok=True)
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
	args = ap.parse_args()
	print(f"{config.REPO_DIR / 'defaults'} -> {Path(args.dest or config.env.data_dir).resolve()}")
	for name, outcome in sync(args.apply or args.force, args.force, args.dest):
		label = {'copied': '', 'skipped - destination identical': '', 'skipped - destination differs': '[differs]'}.get(outcome, f'[{outcome}]')
		print(f"{name} {label}".rstrip())
