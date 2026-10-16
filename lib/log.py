"""The log, syslog style: each line has a level, ERROR, WARN, INFO or DEBUG, and goes to stderr (which systemd and
Docker take to the journal) when the log_level preference lets it in: that level and those above it, so ERROR always
does. Each takes print()'s arguments."""
import sys

from lib import config

LEVELS = config.LOG_LEVELS # ERROR WARN INFO DEBUG, the most severe first


def enabled(level):
	"""Whether log_level lets lines of this level into the log."""
	return LEVELS.index(level) <= LEVELS.index(config.prefs.log_level)


def write(level, parts, options):
	"""A line of these parts (and print()'s options) at this level, if log_level lets it in."""
	if enabled(level):
		print(*parts, file=sys.stderr, **options)


def error(*parts, **options):
	"""Something failed and was lost: a message not sent, a request not answered, a start that cannot go on."""
	write('ERROR', parts, options)


def warn(*parts, **options):
	"""Something failed and finbot got over it: a notice not shown, a retry, a fallback, a request refused."""
	write('WARN', parts, options)


def info(*parts, **options):
	"""What finbot does: a message sent, a job run, each request it sends (a cache miss's) and each it answers."""
	write('INFO', parts, options)


def debug(*parts, **options):
	"""The detail of what it does, to find a fault: a cache miss, hit or write."""
	write('DEBUG', parts, options)
