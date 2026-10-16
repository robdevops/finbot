#!/usr/bin/env python3
"""Flush finbot's cache: delete the files in DATA_DIR/cache (Yahoo's and Sharesight's answers, the charts, the Yahoo
cookie) last written before or after a time ago, or all of them, so that what they held is fetched afresh. Never the
state in DATA_DIR itself: the watchlists, jobs, plans and records. The bot may keep running: it fetches a file that is
gone afresh."""

import argparse
import os
import sys
import time
from pathlib import Path

if __name__ == '__main__':
	os.environ['FINBOT_CHECK_ONLY'] = '1' # importing lib.config makes no data dir: --data-dir may name another
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config
from lib import formats
from lib.reports import cleanup

EXAMPLES = """examples:
  util/flush.py --before 180s    the files written more than 180 seconds ago
  util/flush.py --after 24h      the files written in the last 24 hours
  util/flush.py --after 7d       ... in the last 7 days
  util/flush.py --after 3m       ... in the last 3 months
  util/flush.py --after 1y       ... in the last year
  util/flush.py all              every file

A TIME is a number and s (seconds), h (hours), d (days), w (weeks), m (months: 30 days) or y (years).
DATA_DIR is finbot's, as finbot.env sets it, or var/ in the checkout; --data-dir names another. In Docker:
  sudo docker compose exec finbot util/flush.py all"""


def age(text):
	"""A TIME ago in seconds, for argparse: 180s, 24h, 7d, 2w, 3m or 1y."""
	try:
		seconds = formats.seconds_from_human(text)
	except ValueError:
		seconds = -1
	if seconds < 0:
		raise argparse.ArgumentTypeError(f'{text!r} is not a time: a number and s, h, d, w, m or y (180s, 24h, 7d)')
	return seconds


def parser():
	"""The arguments: --before TIME, --after TIME or all; and --data-dir."""
	ap = argparse.ArgumentParser(prog='util/flush.py', description=__doc__, epilog=EXAMPLES,
		formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('all', nargs='?', choices=['all'], metavar='all', help='every cache file')
	ap.add_argument('--before', metavar='TIME', type=age, help='the files written more than TIME ago')
	ap.add_argument('--after', metavar='TIME', type=age, help='the files written in the last TIME')
	ap.add_argument('--data-dir', metavar='DIR', help='the data dir whose cache to flush (default: DATA_DIR, or var/)')
	return ap


def main(argv=None):
	"""Flush what the arguments ask for and say how many files went; with none, the help. Returns the exit status."""
	argv = sys.argv[1:] if argv is None else argv
	ap = parser()
	if not argv:
		ap.print_help()
		return 2
	args = ap.parse_args(argv)
	if [args.all, args.before, args.after].count(None) != 2:
		ap.error('give one of --before TIME, --after TIME or all')
	cache = os.path.join(args.data_dir, 'cache') if args.data_dir else config.env.cache_dir # as config makes it
	now = time.time()
	removed = cleanup.remove(before=None if args.before is None else now - args.before,
		after=None if args.after is None else now - args.after, directory=cache)
	print(f"flushed {removed} file{'' if removed == 1 else 's'} from {cache}")
	return 0


if __name__ == '__main__':
	sys.exit(main())
