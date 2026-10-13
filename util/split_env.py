#!/usr/bin/env python3
"""Split an old single .env into the two config files: finbot.env (the startup file) and preferences.conf.

  util/split_env.py /opt/finbot.env

Reads KEY=value lines (run util/migrate_env.py first if the file is in the old dotenv format) and writes finbot.env.new and
preferences.conf.new next to it; it never overwrites anything. Review them, then move them into place: finbot.env wherever your launcher
loads it from, preferences.conf into DATA_DIR. Keys it cannot place (removed or unknown) are listed and left out."""

import argparse
import os
import sys
from pathlib import Path

if __name__ == '__main__':
	os.environ['FINBOT_CHECK_ONLY'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config

RENAMED = {'volatile_multiplier': 'volatility_multiplier'}
REMOVED = {'slackToken': 'nothing reads it any more'}


def split(text, path='.env'):
	"""(startup lines, preference lines, notes) for the KEY=value lines of an old env file."""
	startup, preferences, notes = [], [], []
	for number, raw in enumerate(text.splitlines(), 1):
		line = raw.strip()
		if not line or line.startswith('#'):
			continue
		key, sep, value = line.partition('=')
		key = RENAMED.get(key.strip(), key.strip())
		if not sep:
			notes.append(f'{path} line {number}: not KEY=value, left out')
		elif key in REMOVED:
			notes.append(f'{path} line {number}: {key} dropped ({REMOVED[key]})')
		elif key == 'STATE_DIRECTORY':
			notes.append(f'{path} line {number}: {key} is set by systemd, left out')
		elif key in config.STARTUP_KEYS:
			startup.append(f'{key}={value.strip()}')
		elif key in config.PREFERENCE_KEYS:
			preferences.append(f'{key}={value.strip()}')
		else:
			notes.append(f'{path} line {number}: unknown key {key}, left out')
	return startup, preferences, notes


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('file', help='the old env file')
	args = ap.parse_args()
	src = Path(args.file)
	startup, preferences, notes = split(src.read_text(), src)
	outputs = {src.with_name('finbot.env.new'): ('# finbot.env: the startup file, loaded by your launcher; a change needs a restart.', startup, 0o600),
		src.with_name('preferences.conf.new'): ('# preferences.conf: read by the bot; reload with SIGHUP.', preferences, 0o644)}
	if any(path.exists() for path in outputs):
		sys.exit('refusing to overwrite: ' + ', '.join(str(p) for p in outputs if p.exists()))
	for path, (header, lines, mode) in outputs.items():
		path.write_text(header + '\n' + ''.join(line + '\n' for line in lines))
		path.chmod(mode)
		print(f'wrote {path} ({len(lines)} keys)', file=sys.stderr)
	for note in notes:
		print(note, file=sys.stderr)
