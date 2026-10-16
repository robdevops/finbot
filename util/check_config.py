#!/usr/bin/env python3
"""Lint finbot's two config files with the rules the bot applies, without starting it.

  util/check_config.py /opt/finbot.env [/var/lib/finbot/preferences.conf]

finbot.env (the startup file) is never read by the bot, so this is the only place its typos are caught: an unknown key,
a preference key in it, a malformed line or a bad value. preferences.conf defaults to <DATA_DIR>/preferences.conf and is
checked the way the bot checks it at start and on reload. Exits 1 and prints every problem if either file is wrong, so a
launcher can refuse to start (see doc/install.md and doc/docker.md)."""

import argparse
import os
import sys
from pathlib import Path

if __name__ == '__main__':
	# importing lib.config must not create the data directories (this may run as root, from systemd)
	os.environ['FINBOT_CHECK_ONLY'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config


def check(startup_path, preferences_path):
	"""Every problem in the two files, as a list of lines (a key that does nothing any more is a note, not a problem:
	notes() has those)."""
	problems = []
	if startup_path:
		try:
			values = config.read_startup_file(startup_path)
			config.startup_values(lambda name, default=None: values.get(name, default))
		except config.ConfigError as e:
			problems += e.errors
	try:
		prefs = config.read_preferences(preferences_path)
		if prefs is not None:
			config.preference_values(config._getenv_for(prefs))
	except config.ConfigError as e:
		problems += e.errors
	return problems


def warnings(startup_path):
	"""What a valid finbot.env sets that keeps part of the bot from working or does nothing, a line each: what bot.py
	logs at start."""
	try:
		values = config.read_startup_file(startup_path)
		return config.startup_warnings(config.startup_values(lambda name, default=None: values.get(name, default)))
	except config.ConfigError:
		return []


def notes(preferences_path, startup_path=None):
	"""The keys of the two files, where valid, that do nothing any more, a line each with what to do instead."""
	lines = []
	if startup_path:
		try:
			lines += config.retired_notes(config.read_startup_file(startup_path), 'finbot.env')
		except config.ConfigError:
			pass
	try:
		return lines + config.retired_notes(config.read_preferences(preferences_path) or {})
	except config.ConfigError:
		return lines


if __name__ == '__main__':
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('startup', help='the finbot.env to check (the startup file)')
	ap.add_argument('preferences', nargs='?', default=config.preferences_path,
		help='default: <DATA_DIR>/preferences.conf')
	args = ap.parse_args()
	problems = check(args.startup, args.preferences)
	for line in problems:
		print('ERROR config:', line, file=sys.stderr)
	if not problems:
		print('config: ok', args.startup,
			args.preferences if Path(args.preferences).is_file() else '(no preferences.conf, defaults)')
		for line in warnings(args.startup):
			print('config: warning:', line)
		for line in notes(args.preferences, args.startup):
			print('config:', line)
	sys.exit(1 if problems else 0)
