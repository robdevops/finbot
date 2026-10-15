"""Once, as finbot starts: what the bot kept for all chats at once becomes each home chat's (telegramChatID,
slackChannelID, discordChannelID). The old schedule.cron (the data dir's copy, else the shipped one) is copied to every
home chat as its jobs, each in the zone it ran in, and is read no more; and the reports' records of what they told the
chats (trades, ratings, record highs, podcast episodes) are copied to each home chat, so that nothing old is told again.

This module, and defaults/schedule.cron, go once every install has started with it: they are its only users."""
import copy
import datetime
import glob
import os
import re
import shlex
import sys
import zoneinfo
from pathlib import Path

from lib import config
from lib import delivery
from lib import jobs
from lib import state
from lib.reports import milestone, podcasts, rating, trades

RECORDS = (trades.STATE_FILE, rating.STATE_FILE, milestone.STATE_FILE) # and each podcast feed's seen file
# what a shell reads as more than a word, outside quotes, in a pasted crontab line
OPERATOR = re.compile(r'\d*>>?&?\d*|&>>?|;|&&|\|\|?|&|[<`$(){}]')
REDIRECT = re.compile(r'\d*>>?&?\d*|&>>?') # > file, >> file, 2>&1, &> file


def run():
	"""Make the home chats' own what was kept for all chats, where that has not been done yet. With no home chat set,
	it all waits until there is one."""
	try:
		homes = [chat.key for chat in delivery.default_chats()]
	except RuntimeError:
		return
	schedule(homes)
	feeds = sorted(os.path.basename(path) for path in glob.glob(state.path(podcasts.SEEN_FILES)))
	for name in RECORDS + tuple(feeds):
		record(name, homes)


def schedule(homes):
	"""Give every home chat (keys) the jobs of the old schedule.cron, the system jobs aside (they run in code now),
	unless the chats' jobs are kept already (jobs.SCHEDULE_FILE). A line that cannot be a job any more is logged and
	left out."""
	if os.path.exists(state.path(jobs.SCHEDULE_FILE)):
		return
	path = config.data_file('schedule.cron')
	try:
		text = Path(path).read_text(encoding='utf-8')
	except OSError:
		text = ''
	entries = []
	for number, line, zone, words_list in legacy_lines(text, path):
		reports = '; '.join(shlex.join([name, *arguments]) for name, arguments in words_list
			if name not in jobs.SYSTEM_SCRIPTS)
		if not reports:
			continue
		try:
			job = jobs.parse_job(f"{'' if zone == 'UTC' else f'CRON_TZ={zone} '}{line} {reports}")
		except jobs.ScheduleError as e:
			print(f'schedule: {path} line {number} left out: {e}', file=sys.stderr)
			continue
		entries.append({'when': job.when, 'reports': job.text, 'zone': job.zone.key, 'on': True})
	# written even when empty: the file being there says the migration is done
	state.save(jobs.SCHEDULE_FILE, {key: copy.deepcopy(entries) for key in homes if entries})
	print(f"schedule: the {len(entries)} jobs of {path} are now each home chat's ({', '.join(homes)});"
		f" finbot reads that file no more: each chat's jobs are in {jobs.SCHEDULE_FILE}, changed with .jobs",
		file=sys.stderr)


def record(name, homes):
	"""A report's record kept for all chats at once (anything but {'chats': ...}) becomes each home chat's."""
	try:
		data = state.load(name)
	except (OSError, ValueError) as e:
		print(f'state: {name} left as it is, unreadable: {e}', file=sys.stderr)
		return
	if data is None or (isinstance(data, dict) and 'chats' in data):
		return
	state.save(name, {'chats': {key: copy.deepcopy(data) for key in homes}})
	print(f"state: {name} is kept per chat now, its record copied to {', '.join(homes)}", file=sys.stderr)


def local_zone():
	"""The server's own time zone, which the old schedule ran in, as cron does: UTC by that name when it is UTC by
	another (Etc/UTC), or when there is none."""
	try:
		if os.environ.get('TZ'):
			zone = zoneinfo.ZoneInfo(os.environ['TZ'].lstrip(':'))
		elif '/zoneinfo/' in (link := os.path.realpath('/etc/localtime')):
			zone = zoneinfo.ZoneInfo(link.split('/zoneinfo/', 1)[1])
		else:
			zone = zoneinfo.ZoneInfo(Path('/etc/timezone').read_text().strip())
	except (OSError, ValueError, zoneinfo.ZoneInfoNotFoundError):
		return jobs.UTC
	year = [datetime.datetime(2026, month, 1, tzinfo=zone).utcoffset() for month in (1, 7)]
	return jobs.UTC if year == [datetime.timedelta(0)] * 2 else zone


def legacy_lines(text, path):
	"""The jobs of an old schedule.cron (text, from path): (line number, time, zone name, [(report name, arguments)])
	for each line that parses, in the zone set above it (CRON_TZ=) or the server's own; pasted crontab syntax (paths,
	.py, redirects, braces, variables) read as cron read it. A line that does not parse is logged."""
	zone = local_zone().key
	for number, raw in enumerate(text.splitlines(), 1):
		line = raw.strip()
		if not line or line.startswith('#'):
			continue
		if m := re.fullmatch(r'CRON_TZ=(\S+)', line):
			zone = m.group(1)
			continue
		if re.fullmatch(r'\w+=.*', line): # MAILTO=, PATH= and the like
			continue
		if line.startswith('@'):
			when, _, rest = line.partition(' ')
		else:
			fields = line.split(None, 5)
			if len(fields) < 6:
				continue
			when, rest = ' '.join(fields[:5]), fields[5]
		try:
			commands = [(os.path.basename(words[0]).removesuffix('.py'), words[1:])
				for words in split_commands(tokenize(rest))]
		except ValueError as e:
			print(f'schedule: {path} line {number} left out: {e}', file=sys.stderr)
			continue
		yield number, when, zone, commands


def tokenize(text):
	"""A command line as ('word', text) and ('op', text) tokens. Quoted text is always a word, whatever it contains."""
	tokens, word, started, i = [], '', False, 0
	def flush():
		"""End the word being read, if there is one, and add it to the tokens."""
		nonlocal word, started
		if started:
			tokens.append(('word', word))
		word, started = '', False
	while i < len(text):
		c = text[i]
		if c.isspace():
			flush()
			i += 1
		elif c in '\'"':
			end = text.find(c, i + 1)
			if end < 0:
				raise ValueError('no closing quotation')
			word, started, i = word + text[i + 1:end], True, end + 1
		elif c == '\\' and i + 1 < len(text):
			word, started, i = word + text[i + 1], True, i + 2
		elif c == '#' and not started: # a trailing comment
			break
		elif m := OPERATOR.match(text, i):
			if word.isdigit() and m.group().startswith('>'): # the 2 of 2>&1 belongs to the redirect
				word, started = '', False
			flush()
			tokens.append(('op', m.group()))
			i = m.end()
		else:
			word, started, i = word + c, True, i + 1
	flush()
	return tokens


def split_commands(tokens):
	"""Word lists, one per command: split on unquoted ; and &&, redirects and braces dropped, variables before a command
	dropped, other shell syntax refused (ValueError)."""
	commands, current, target = [], [], False
	for kind, value in tokens:
		if target: # the file of a redirect
			target = False
			if kind == 'word':
				continue
		if kind == 'word':
			if current or not re.fullmatch(r'\w+=\S*', value): # FOO=bar before a command
				current.append(value)
		elif value in (';', '&&'):
			commands.append(current)
			current = []
		elif value in ('{', '}'):
			continue
		elif REDIRECT.fullmatch(value):
			target = not re.search(r'&\d+$', value) # 2>&1 has no file after it, > /dev/null does
		else:
			raise ValueError('only finbot scripts can be scheduled, not shell commands')
	commands.append(current)
	return [words for words in commands if words]
