"""The log, syslog style: each line has a level, ERROR, WARN, INFO or DEBUG, and goes to stderr (which systemd and
Docker take to the journal) when the log_level setting lets it in: that level and those above it, so ERROR always
does. Each takes print()'s arguments. Under journald (JOURNAL_STREAM is set) a line starts with its syslog priority,
<3> to <7>, which journald takes off and files the line under, so journalctl colours and filters (-p) by it; anywhere
else a line has no prefix. A line that can run long (a request's URL, a chat message) goes through cut(),
which puts it on one line within the log_width setting."""
import os
import sys

from lib import config

LEVELS = config.LOG_LEVELS # ERROR WARN INFO DEBUG, the most severe first
PRIORITIES = {'ERROR': 3, 'WARN': 4, 'INFO': 6, 'DEBUG': 7} # syslog's err, warning, info and debug


def enabled(level):
	"""Whether log_level lets lines of this level into the log."""
	return LEVELS.index(level) <= LEVELS.index(config.settings.log_level)


def prefix(level):
	"""What starts a line of this level: its syslog priority, as journald reads it, under journald, else nothing."""
	return f'<{PRIORITIES[level]}>' if os.environ.get('JOURNAL_STREAM') else ''


def write(level, parts, options):
	"""A line of these parts (and print()'s options) at this level, if log_level lets it in."""
	if enabled(level):
		sep = str(options.pop('sep', None) or ' ')
		print(prefix(level) + sep.join(str(part) for part in parts), file=sys.stderr, **options)


def cut(text):
	"""A log line that can run long (text) on one line, each run of line breaks and spaces one space, and cut to
	log_width characters, its last an ellipsis (…); whole where log_width is 0."""
	text, width = ' '.join(str(text).split()), config.settings.log_width
	return text if width <= 0 or len(text) <= width else text[:width - 1] + '…'


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
