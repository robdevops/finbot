"""The scheduled reports (formerly cron jobs), run by the bot itself.

The schedule is a file in crontab syntax: five time fields (or an @macro) and then a finbot script with its arguments, e.g.
`*/20 * * * Mon-Fri trades.py` or `28 21 * * Sat cal.py earnings; price.py 7`. Pasted crontab lines (`bin/run price.py > /dev/null`,
`{ a; b ;}`) are accepted too. Running in the bot means the jobs share its user, sandbox, environment and cache."""
import datetime
import json
import math
import os
import re
import shlex
import sys
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path

import gevent
from croniter import croniter

from lib.config import *
from lib import util
from lib import webhook
import cal, milestone, performance, price, rating, reminder, shorts, trades

SCRIPTS = {'cal': cal, 'milestone': milestone, 'performance': performance, 'price': price, 'rating': rating, 'reminder': reminder,
	'shorts': shorts, 'trades': trades}
STATE_FILE = 'finbot_jobs.json' # last fire time of every job, so a restart neither repeats a run nor loses one
JOB_TIMEOUT = 15 * 60 # seconds a job may run before it is abandoned and reported
IGNORED_VARIABLES = ('MAILTO', 'SHELL', 'PATH', 'HOME', 'LOGNAME')
REDIRECT = re.compile(r'(?<!\S)(?:&|\d*)>>?&?\s*\S+') # > /dev/null, 2>&1, >> file, &> file


class ScheduleError(ValueError):
	pass


@dataclass
class Job:
	expr: str
	commands: list # [(label, module, kwargs)], run one after another
	zone: zoneinfo.ZoneInfo
	text: str
	key: str
	running: bool = field(default=False, compare=False)


def local_zone():
	"""The server's own time zone, which is what cron uses. Containers without one are UTC, as under cron."""
	try:
		if os.environ.get('TZ'):
			return zoneinfo.ZoneInfo(os.environ['TZ'].lstrip(':'))
		link = os.path.realpath('/etc/localtime')
		if '/zoneinfo/' in link:
			return zoneinfo.ZoneInfo(link.split('/zoneinfo/', 1)[1])
		return zoneinfo.ZoneInfo(Path('/etc/timezone').read_text().strip())
	except (OSError, ValueError, zoneinfo.ZoneInfoNotFoundError):
		return zoneinfo.ZoneInfo('UTC')


def parse_command(text):
	"""'~/finbot/bin/run price.py midsession > /dev/null' -> [('price.py midsession', price, {...})]. Raises ScheduleError."""
	text = re.sub(r'(?<!\S)#.*$', '', text) # a trailing comment
	text = REDIRECT.sub(' ', text.replace('{', ' ').replace('}', ' '))
	if re.search(r'[|`$<()]|&(?!&)', text):
		raise ScheduleError('only finbot scripts can be scheduled, not shell commands')
	commands = []
	for segment in re.split(r'\s*(?:;|&&)\s*', text):
		try:
			words = shlex.split(segment, comments=True)
		except ValueError as e:
			raise ScheduleError(str(e))
		while words and re.fullmatch(r'\w+=\S*', words[0]):
			words.pop(0) # FOO=bar prefix
		if not words or words[0] == 'cd':
			continue # empty, or a `cd ~/finbot` from an old crontab line
		if os.path.basename(words[0]) == 'run': # the bin/run wrapper
			words.pop(0)
		if not words:
			continue
		name = os.path.basename(words[0]).removesuffix('.py')
		if name not in SCRIPTS:
			raise ScheduleError(f"unknown script '{words[0]}' (known: {', '.join(sorted(SCRIPTS))})")
		try:
			label, kwargs = SCRIPTS[name].job(words[1:])
		except ValueError as e:
			raise ScheduleError(f'{name}.py {e}')
		commands.append((label, SCRIPTS[name], kwargs))
	if not commands:
		raise ScheduleError('no command')
	return commands


def parse_schedule(text, default_zone=None):
	"""(jobs, errors): errors are (line number, line, message) for the lines that were skipped."""
	zone = default_zone or local_zone()
	jobs, errors = [], []
	for number, raw in enumerate(text.splitlines(), 1):
		line = raw.strip()
		if not line or line.startswith('#'):
			continue
		try:
			if m := re.fullmatch(r'CRON_TZ=(\S+)', line):
				try:
					zone = zoneinfo.ZoneInfo(m.group(1))
				except (ValueError, zoneinfo.ZoneInfoNotFoundError):
					raise ScheduleError(f'unknown time zone {m.group(1)}')
				continue
			if m := re.fullmatch(r'(\w+)=.*', line):
				if m.group(1) in IGNORED_VARIABLES:
					continue
				raise ScheduleError(f'{m.group(1)}= is not supported')
			if line.startswith('@'):
				expr, _, rest = line.partition(' ')
			else:
				fields = line.split(None, 5)
				if len(fields) < 6:
					raise ScheduleError('expected five time fields and a command')
				expr, rest = ' '.join(fields[:5]), fields[5]
			if not croniter.is_valid(expr):
				raise ScheduleError(f"bad time '{expr}'")
			commands = parse_command(rest)
			key = f"{expr}|{zone.key}|{';'.join(label for label, _, _ in commands)}"
			jobs.append(Job(expr, commands, zone, line, key))
		except ScheduleError as e:
			errors.append((number, line, str(e)))
	return jobs, errors


class Scheduler:
	"""Fires the jobs of a schedule file. `path` is a callable returning the file (the data dir copy wins over the default, so a
	new copy is found on reload). `clock`, `sleep` and `spawn` can be replaced, which the tests do."""

	def __init__(self, path, catchup=config_scheduler_catchup, clock=None, sleep=None, spawn=None, zone=None):
		self.path = path
		self.catchup = datetime.timedelta(minutes=catchup)
		self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
		self.sleep = sleep or gevent.sleep
		self.spawn = spawn or gevent.spawn
		self.zone = zone
		self.jobs = []
		self.base = {} # key -> the time after which the next run is due
		self.last = {}

	def load(self):
		"""Read the schedule file. A file with no usable line keeps the schedule that is running."""
		path = self.path()
		try:
			jobs, errors = parse_schedule(Path(path).read_text(encoding='utf-8'), self.zone)
		except OSError as e:
			webhook.report_error(e, context='schedule')
			return False
		for number, line, message in errors:
			webhook.report_error(ScheduleError(f'{path} line {number}: {message}: {line}'), context='schedule')
		if not jobs and self.jobs:
			print('schedule: no usable line in', path, '- keeping the current schedule', file=sys.stderr)
			return False
		self.last = util.json_load(STATE_FILE, persist=True) or {}
		now = self.clock()
		old = {job.key: self.base[job.key] for job in self.jobs if job.key in self.base}
		self.base = {}
		for job in jobs:
			self.base[job.key] = old.get(job.key) or self.start_base(job, now)
		self.jobs = jobs
		print(f'schedule: {len(jobs)} jobs from {path}', file=sys.stderr)
		for job in jobs:
			print(f'schedule:   {job.text}  (next {self.next_fire(job, now):%a %d %b %H:%M %Z})', file=sys.stderr)
		return True

	def reload(self, *args):
		self.load()

	def start_base(self, job, now):
		"""Where to count from at start: a run missed within the catch-up window fires once; with no record, nothing is missed."""
		last = self.last.get(job.key)
		if not last:
			return now
		try:
			return max(datetime.datetime.fromisoformat(last), now - self.catchup)
		except ValueError:
			return now

	def next_fire(self, job, after):
		return croniter(job.expr, after.astimezone(job.zone)).get_next(datetime.datetime)

	def due(self, now):
		"""The jobs to run now, as (job, fire time). Several missed fire times of one job run it once."""
		fired = []
		for job in self.jobs:
			base, latest = self.base[job.key], None
			while (t := self.next_fire(job, base)) <= now:
				latest, base = t, t
			if latest:
				self.base[job.key] = latest
				self.last[job.key] = latest.isoformat()
				fired.append((job, latest))
		if fired:
			try:
				util.json_write(STATE_FILE, self.last, persist=True)
			except OSError as e:
				print('schedule: cannot save', STATE_FILE, e, file=sys.stderr)
		return fired

	def run_job(self, job, fire_time):
		"""One job: its commands in order. Skipped if the previous run is still going; abandoned after JOB_TIMEOUT."""
		if job.running:
			print(f'schedule: {job.text} is still running, skipping {fire_time:%H:%M}', file=sys.stderr)
			return
		job.running = True
		timeout = gevent.Timeout(JOB_TIMEOUT)
		timeout.start()
		try:
			for label, module, kwargs in job.commands:
				print(f'schedule: running {label}', file=sys.stderr)
				webhook.guarded(label, module.lambda_handler, exit=False, **kwargs)
		except gevent.Timeout as t:
			if t is not timeout:
				raise
			webhook.report_error(TimeoutError(f'still running after {JOB_TIMEOUT // 60} minutes'), context=job.text)
		finally:
			timeout.close()
			job.running = False

	def tick(self):
		"""Start what is due; returns the seconds until the next fire time."""
		now = self.clock()
		for job, fire_time in self.due(now):
			self.spawn(self.run_job, job, fire_time)
		waits = [(self.next_fire(job, self.base[job.key]) - now).total_seconds() for job in self.jobs]
		return min(30, max(1, math.ceil(min(waits)))) if waits else 30

	def run_forever(self):
		"""Never returns, never raises: a failure is reported and the loop carries on."""
		while True:
			try:
				self.sleep(self.tick())
			except Exception as e:
				webhook.report_error(e, context='schedule')
				self.sleep(30)
