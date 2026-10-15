"""What finbot says. A module per scheduled report: cal, cleanup (of the cache), milestone, performance, podcasts,
price, rating, reminder, shorts, trades, and sharesight_warm and yahoo_warm (which fill the cache), each with
job(argv), which parses its schedule line, and run(dest=None, **kwargs), which runs it, to the chat that asked (dest)
or else the default chats; the top-level script of the same name runs it from the command line. And the chat-only
reports: about (.help, .jobs), history (.history, .compare), holdings (.holdings, .who, .pie, .watchlist), profile
(.SYMBOL) and rankings (.marketcap, .pe and the rest)."""
import os
import sys


def cli(path):
	"""Run the report a top-level script is named for (price.py: lib/reports/price.py) with the script's arguments."""
	import importlib
	from lib import delivery
	report = importlib.import_module('lib.reports.' + os.path.basename(path).removesuffix('.py'))
	delivery.cli(sys.argv[0], report.job, report.run)
