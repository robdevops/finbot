#!/usr/bin/env python3
"""Split an old single .env into the two config files: finbot.env (the startup file) and preferences.conf.

  util/split_env.py [old file]      (default: the .env in the checkout, which finbot will not start with)

Reads the old file in either format: dotenv (key = 'value' # comment, export key=value) or plain KEY=value. Writes finbot.env.new
and preferences.conf.new next to it; it never overwrites anything. Review them, then move them into place: finbot.env wherever your
launcher loads it from, preferences.conf into DATA_DIR. Then delete the old file. Keys it cannot place (removed or unknown) are listed
and left out."""

import argparse
import os
import re
import sys
from pathlib import Path

if __name__ == '__main__':
	os.environ['FINBOT_CHECK_ONLY'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config

RENAMED = {'volatile_multiplier': 'volatility_multiplier'}
REMOVED = {'slackToken': 'nothing reads it any more'}


def parse_line(line):
	"""(key, value) of a line of an old env file, None for a blank or comment line, (line, None) for one that is not KEY=value.
	Takes the dotenv format too: an `export ` prefix, spaces around =, quotes, and a trailing # comment are dropped."""
	line = line.strip()
	if not line or line.startswith('#'):
		return None
	if line.startswith('export '):
		line = line[7:].lstrip()
	if '=' not in line:
		return line, None
	key, value = (part.strip() for part in line.split('=', 1))
	m = re.match(r"""^(['"])(.*?)\1(\s*#.*)?$""", value)
	if m:
		value = m.group(2)
	else:
		value = re.sub(r'\s+#.*$', '', value)
	return key, value


def split(text, path='.env'):
	"""(startup lines, preference lines, notes) for the lines of an old env file."""
	startup, preferences, notes = [], [], []
	for number, raw in enumerate(text.splitlines(), 1):
		parsed = parse_line(raw)
		if parsed is None:
			continue
		key, value = parsed
		key = RENAMED.get(key, key)
		if value is None:
			notes.append(f'{path} line {number}: not KEY=value, left out')
		elif key in REMOVED:
			notes.append(f'{path} line {number}: {key} dropped ({REMOVED[key]})')
		elif key == 'STATE_DIRECTORY':
			notes.append(f'{path} line {number}: {key} is set by systemd, left out')
		elif key in config.STARTUP_KEYS:
			startup.append(f'{key}={value}')
		elif key in config.PREFERENCE_KEYS:
			preferences.append(f'{key}={value}')
		else:
			notes.append(f'{path} line {number}: unknown key {key}, left out')
	return startup, preferences, notes


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('file', nargs='?', default=str(config.OLD_ENV), help=f'the old env file (default: {config.OLD_ENV})')
	args = ap.parse_args()
	src = Path(args.file)
	if not src.is_file():
		sys.exit(f'{src} does not exist: nothing to split')
	startup, preferences, notes = split(src.read_text(), src)
	outputs = {src.with_name('finbot.env.new'): ('# finbot.env: the startup file, loaded by your launcher; a change needs a restart.', startup, 0o600),
		src.with_name('preferences.conf.new'): ('# preferences.conf: read by the bot; reload with systemctl reload finbot.', preferences, 0o644)}
	if any(path.exists() for path in outputs):
		sys.exit('refusing to overwrite: ' + ', '.join(str(p) for p in outputs if p.exists()))
	for path, (header, lines, mode) in outputs.items():
		path.write_text(header + '\n' + ''.join(line + '\n' for line in lines))
		path.chmod(mode)
		print(f'wrote {path} ({len(lines)} keys)', file=sys.stderr)
	for note in notes:
		print(note, file=sys.stderr)
	print(f'next: put finbot.env where your launcher loads it and preferences.conf in the data directory (DATA_DIR), then delete {src}', file=sys.stderr)
