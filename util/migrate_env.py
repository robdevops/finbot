#!/usr/bin/env python3
"""Convert an old dotenv-style .env (key = 'value' # comment) to the strict KEY=value format
that systemd EnvironmentFile, docker --env-file and bin/run all read the same way.
Prints the result; --write replaces the file and keeps the original as .bak."""

import argparse
import re
import shutil
import sys
from pathlib import Path


def convert_line(line):
	line = line.strip()
	if not line or line.startswith('#'):
		return line
	if line.startswith('export '):
		line = line[7:].lstrip()
	if '=' not in line:
		return '# ' + line + ' # no value, not a setting'
	key, value = (part.strip() for part in line.split('=', 1))
	m = re.match(r"""^(['"])(.*?)\1(\s*#.*)?$""", value)
	if m:
		value = m.group(2)
	else:
		value = re.sub(r'\s+#.*$', '', value)
	return key + '=' + value


def convert(text):
	return ''.join(convert_line(line) + '\n' for line in text.splitlines())


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument('file', nargs='?', default=str(Path(__file__).resolve().parent.parent / '.env'))
	ap.add_argument('--write', action='store_true', help='replace the file (original kept as .bak)')
	args = ap.parse_args()
	path = Path(args.file)
	out = convert(path.read_text())
	if args.write:
		shutil.copy2(path, str(path) + '.bak')
		path.write_text(out)
		print('wrote', path, '(original kept as ' + str(path) + '.bak)', file=sys.stderr)
	else:
		sys.stdout.write(out)
