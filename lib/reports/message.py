"""A text that a job posts as it is, a reminder say (scheduled: message "TEXT"), in the network's markup: [text](url) is
a link and a line wrapped in _underscores_ is in italics (formats.markup); {years since YYYY-MM-DD} becomes the years
since that date as an ordinal, for an anniversary ("It's my 4th birthday")."""
import datetime
import re

from lib import delivery
from lib import formats

ARGUMENTS = '"TEXT"' # what a scheduled run takes: its text, in double quotes, over several lines if need be
MAX_LINES = 40
MAX_CHARACTERS = 3000
YEARS = re.compile(r'\{years since (\d{4})-(\d{2})-(\d{2})\}')


def run(dest=None, *, lines):
	"""Post the lines to the chat whose job it is (dest), each placeholder filled, by an explicit replace: the text is
	data, never a format string."""
	filled = [YEARS.sub(lambda found: years_since(found, today()), line) for line in lines]
	for chat in delivery.targets(dest):
		delivery.deliver(chat, delivery.Report([formats.markup(line, chat.dialect) for line in filled]))


def today():
	"""Today's date, by the timezone preference's clock."""
	return datetime.datetime.now(formats.zone()).date()


def years_since(found, on):
	"""The years from a placeholder's date to the date on, as an ordinal ('4th'); for no date, the placeholder."""
	try:
		since = datetime.date(*map(int, found.groups()))
	except ValueError:
		return found.group(0)
	years = on.year - since.year - ((on.month, on.day) < (since.month, since.day))
	return f'{years}{formats.ordinal(years)}'


def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments), its text's lines; none or too many: ValueError."""
	lines = list(argv)
	if not lines or not all(isinstance(line, str) for line in lines) or not any(line.strip() for line in lines):
		raise ValueError(ARGUMENTS)
	if len(lines) > MAX_LINES or sum(map(len, lines)) > MAX_CHARACTERS:
		raise ValueError(f'a text of {MAX_LINES} lines and {MAX_CHARACTERS} characters at most')
	return 'message', {'lines': lines}
