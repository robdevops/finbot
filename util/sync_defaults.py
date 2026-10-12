#!/usr/bin/env python3
"""Compare the shipped defaults/ with the data dir (DATA_DIR, default var/).
Dry run by default. --apply copies files that are missing; --force also overwrites
differing files (the old copy is kept as .bak). Existing files are never touched otherwise."""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config
from lib.config import REPO_DIR


def sync(apply=False, force=False):
	apply = apply or force
	dest_dir = Path(config.config_var_dir)
	changes = []
	for src in sorted((REPO_DIR / 'defaults').iterdir()):
		if not src.is_file():
			continue
		name = '.env' if src.name == 'env.example' else src.name
		dest = dest_dir / name
		if not dest.exists():
			status = 'missing'
		elif filecmp.cmp(src, dest, shallow=False):
			continue
		else:
			status = 'differs'
		if name == '.env' and status == 'differs':
			continue # a configured .env is never replaced
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
	args = ap.parse_args()
	for name, status in sync(args.apply or args.force, args.force):
		done = args.force or (args.apply and status == 'missing')
		print(('updated ' if done else 'would update ') + name + ' (' + status + ')')
