"""Reminders for the day: the entries of reminder.json for today, and finbot's birthday (scheduled: reminder.py)."""
import datetime
import re
import zoneinfo
from dateutil.relativedelta import relativedelta
from lib import config
from lib import formats
from lib import delivery

BIRTHDAY = datetime.date(2022, 8, 18)
FLAGS = {'AU': '🇦🇺'} # what {flag} becomes in an entry gated to a country
LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)') # [text](url)


def lambda_handler():
	"""Post today's reminders to the default chats, if there are any."""
	today = datetime.datetime.now(zoneinfo.ZoneInfo(config.prefs.timezone)).date()
	entries = config.data_json("reminder.json", [])
	for dest in delivery.default_chats():
		delivery.deliver(dest, delivery.Report(report(dest.dialect, today, entries)))


def report(service, today, entries):
	"""Today's reminders in one network's markup, under a heading, or [] when there are none: the entries of
	reminder.json for this day (and year, and country, where an entry names one), and finbot's birthday."""
	payload = []
	for entry in entries:
		if entry.get("month_day") != today.strftime('%m-%d'):
			continue
		if entry.get("year") and str(entry["year"]) != today.strftime('%Y'):
			continue
		country = entry.get("gate_country")
		if country and config.prefs.country_code != country:
			continue
		message = entry["message"] # a line, or a list of them
		for line in [message] if isinstance(message, str) else message:
			payload.append(markup(line.replace("{flag}", FLAGS.get(country, '')), service))
	if today.strftime('%m-%d') == BIRTHDAY.strftime('%m-%d'):
		years = relativedelta(today, BIRTHDAY).years
		payload.append(f"It's my {years}{formats.ordinal(years)} birthday! 🥳")
	return [service.bold("Finance event reminders:")] + payload if payload else []


def markup(line, service):
	"""A line of reminder.json in the network's markup: [text](url) is a link, a line wrapped in _underscores_ is in
	italics, and the rest is text."""
	italic = len(line) > 1 and line.startswith('_') and line.endswith('_')
	if italic:
		line = line[1:-1]
	text, start = '', 0
	for link in LINK.finditer(line):
		text += service.escape(line[start:link.start()]) + service.link(link.group(2), service.escape(link.group(1)))
		start = link.end()
	text += service.escape(line[start:])
	return service.italic(text) if italic else text


def job(argv):
	"""Arguments of a scheduled run: reminder.py takes none."""
	return 'reminder.py', {}
