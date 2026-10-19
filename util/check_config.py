#!/usr/bin/env python3
"""Lint finbot's two config files with the rules the bot applies, without starting it.

  util/check_config.py /opt/finbot.env [/var/lib/finbot/settings.conf]

finbot.env (the startup file) is never read by the bot, so this is the only place its
typos are caught: an unknown key, a setting key in it, a malformed line or a bad value.
settings.conf defaults to <DATA_DIR>/settings.conf and is checked as the bot checks it
at start and on reload. It also warns when finbot.env is not 600 root:root, as it holds
the credentials. Exits 1 and prints every problem if either file is wrong, so a launcher
can refuse to start (see doc/install.md and doc/docker.md)."""

import argparse
import grp
import os
import pwd
import stat
import sys
from pathlib import Path

if __name__ == '__main__':
	# importing lib.config must not create the data directories (may run as root, from systemd)
	os.environ['FINBOT_CHECK_ONLY'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config


def _startup_values(path):
	"""The startup settings that a finbot.env gives. Raises config.ConfigError."""
	values = config.read_startup_file(path)
	return config.startup_values(lambda name, default=None: values.get(name, default))


def check(startup_path, settings_path):
	"""Every problem in the two files, as a list of lines (a key that does nothing any more is a note, not
	a problem: notes() has those)."""
	problems = []
	if startup_path:
		try:
			_startup_values(startup_path)
		except config.ConfigError as e:
			problems += e.errors
	try:
		settings = config.read_settings(settings_path)
		if settings is not None:
			config.setting_values(settings)
	except config.ConfigError as e:
		problems += e.errors
	return problems


def warnings(startup_path):
	"""What a valid finbot.env sets that keeps part of the bot from working or does nothing, a line each:
	what bot.py logs at start."""
	try:
		return config.startup_warnings(_startup_values(startup_path))
	except config.ConfigError:
		return []


def notes(settings_path, startup_path=None):
	"""The keys of the two files, where valid, that do nothing any more, a line each with what to do
	instead."""
	lines = []
	if startup_path:
		try:
			lines += config.retired_notes(config.read_startup_file(startup_path), 'finbot.env')
		except config.ConfigError:
			pass
	try:
		return lines + config.retired_notes(config.read_settings(settings_path) or {})
	except config.ConfigError:
		return lines


def _name(lookup, number):
	"""The name of a user or group by its number, or the number when it has none."""
	try:
		return lookup(number)[0]
	except KeyError:
		return str(number)


def permission_warnings(path):
	"""A line saying so if the file is not 600 root:root, as finbot.env should be (it holds the credentials,
	and systemd loads it as root); nothing if it is, or cannot be read."""
	try:
		info = os.stat(path)
	except OSError:
		return []
	mode = stat.S_IMODE(info.st_mode)
	if mode == 0o600 and (info.st_uid, info.st_gid) == (0, 0):
		return []
	owner = f'{_name(pwd.getpwuid, info.st_uid)}:{_name(grp.getgrgid, info.st_gid)}'
	return [f'{path} is {mode:o} {owner}, not 600 root:root: it holds credentials; '
		f'chmod 600 {path} && chown root:root {path}']


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('startup', help='the finbot.env to check (the startup file)')
	ap.add_argument('settings', nargs='?', default=config.settings_path,
		help='default: <DATA_DIR>/settings.conf')
	args = ap.parse_args()
	problems = check(args.startup, args.settings)
	for line in problems:
		print('ERROR config:', line, file=sys.stderr)
	for line in permission_warnings(args.startup):
		print('WARN config:', line, file=sys.stderr)
	if not problems:
		has_settings = Path(args.settings).is_file()
		print('config: ok', args.startup, args.settings if has_settings else '(no settings.conf, defaults)')
		for line in warnings(args.startup):
			print('config: warning:', line)
		for line in notes(args.settings, args.startup):
			print('config:', line)
	sys.exit(1 if problems else 0)
