"""The scheduled reports: each chat's jobs, which its people manage with .jobs (lib/worker.py), kept in SCHEDULE_FILE
and each posting to its own chat; and the system jobs (SYSTEM), fixed here, which fill the cache and clear it out.

A job is a time in crontab's syntax (five fields, or an @macro such as @daily), in UTC unless it names its own zone
first (CRON_TZ=America/New_York), then one or more reports with their arguments, separated by ";":
`*/20 * * * Mon-Fri trades`, `28 21 * * Sat cal earnings; price 7`. The bot runs each command itself, in a thread of
its own, sharing its user, sandbox, environment, caches and connections."""
import datetime
import hmac
import math
import re
import shlex
import sys
import threading
import time
import zlib
import zoneinfo
from dataclasses import dataclass

from croniter import croniter, CroniterBadDateError

from lib import config
from lib import state
from lib import delivery
from lib.reports import cal, cleanup, milestone, performance, podcasts, price, rating, reminder, shorts, trades
from lib.reports import sharesight_warm, yahoo_warm

SCRIPTS = {'cal': cal, 'cleanup': cleanup, 'milestone': milestone, 'performance': performance, 'podcasts': podcasts,
	'price': price, 'rating': rating, 'reminder': reminder, 'shorts': shorts, 'trades': trades,
	'sharesight_warm': sharesight_warm, 'yahoo_warm': yahoo_warm}
# the system jobs, in UTC: the Sharesight portfolios and holdings fetched afresh every 30 minutes (cached 40), the price
# histories of the stocks followed every 8 hours (cached 12), so that no request waits on either; and cache files
# older than 30 days deleted weekly
SYSTEM = (('14,44 * * * *', 'sharesight_warm'), ('7 */8 * * *', 'yahoo_warm'), ('51 18 * * Sat', 'cleanup 30'))
SYSTEM_SCRIPTS = ('sharesight_warm', 'yahoo_warm', 'cleanup') # a chat cannot schedule these
WARM = 'sharesight_warm; yahoo_warm' # the jobs that fill the cache, run at once after a flush too
SCHEDULE_FILE = 'finbot_schedule.json' # {chat key: [{'when', 'reports', 'zone', 'on'}]}: each chat's jobs, in order
STATE_FILE = 'finbot_jobs.json' # last fire time of every job, so a restart neither repeats a run nor loses one
MAX_JOBS = 30 # a chat's jobs, at most
JOB_TIMEOUT = 5 * 60 # seconds a command may run before it is reported as late, once (it runs on, see execute)
UTC = zoneinfo.ZoneInfo('UTC')
current = None # the running Scheduler, set by bot.py; the chat commands use it


class ScheduleError(ValueError):
	"""A job that cannot be: said to the chat that asked for it."""


class ImpossibleTime(ScheduleError):
	"""A time that cannot be (minute 61) or never comes (30 February)."""


@dataclass
class Job:
	"""A job: its time, in its zone; the commands it runs in turn, [(label, report module, run's keyword arguments)];
	the chat it posts to (its key, as delivery.chat takes it; '' for a system job); whether it is on; and its reports
	as written."""
	when: str
	commands: list
	zone: zoneinfo.ZoneInfo
	chat: str
	on: bool
	text: str

	@property
	def key(self):
		"""What the job is, for its record of runs and the checksum of its buttons: its chat, time, zone and reports."""
		return f'{self.chat}|{self.when}|{self.zone.key}|{self.text}'

	@property
	def line(self):
		"""The job as .jobs add takes it: its zone if not UTC, its time, its reports."""
		zone = '' if self.zone.key == 'UTC' else f'CRON_TZ={self.zone.key} '
		return f'{zone}{self.when} {self.text}'


def checksum(text):
	"""A job's short stand-in in a button (Telegram allows 64 bytes of data): it tells a changed list."""
	return format(zlib.crc32(text.encode()) & 0xffff, '04x')


def run_in_process(label, module, kwargs, dest=None):
	"""Run a command here, in the calling thread: its report's run(**kwargs), posting to dest (a chat's job) or else to
	the home chats."""
	if dest is None:
		module.run(**kwargs)
	else:
		module.run(dest, **kwargs)


def start_thread(target, *args):
	"""Run target(*args) in a daemon thread of its own."""
	threading.Thread(target=target, args=args, daemon=True).start()


def warm_now(scheduler=None):
	"""Run the warm jobs (WARM) now, one after the other: through the scheduler, so that one already running on its
	schedule is not started twice; without one (a test, a tool), here, a failure reported in the chat as the scheduler
	reports one."""
	commands = parse_reports(WARM, system=True)
	print('cache: filling it again:', ', '.join(label for label, _, _ in commands), file=sys.stderr)
	if scheduler:
		scheduler.execute(commands)
	else:
		for label, module, kwargs in commands:
			try:
				run_in_process(label, module, kwargs)
			except Exception as e:
				delivery.report_error(e, context=label)
	print('cache: warm jobs done', file=sys.stderr)


def parse_reports(text, system=False):
	"""'cal earnings; price 7' -> [(label, report module, run's keyword arguments)]: report names (lib/reports) and
	their arguments, quoted where they hold spaces, separated by ";". The system jobs' reports only with system. Raises
	ScheduleError, saying what is wrong."""
	lexer = shlex.shlex(text, posix=True, punctuation_chars=';')
	lexer.whitespace_split, lexer.commenters = True, ''
	try:
		tokens = list(lexer)
	except ValueError as e: # an unclosed quote
		raise ScheduleError(str(e))
	commands, words = [], []
	for token in tokens + [';']:
		if token.strip(';'):
			words.append(token)
			continue
		if not words:
			continue
		name, arguments, words = words[0], words[1:], []
		if name not in SCRIPTS or (name in SYSTEM_SCRIPTS and not system):
			raise ScheduleError(f"no report {name!r}: send .jobs add for the reports and what each takes")
		try:
			label, kwargs = SCRIPTS[name].job(arguments)
		except ValueError as e:
			raise ScheduleError(f'{name} takes {e}')
		commands.append((label, SCRIPTS[name], kwargs))
	if not commands:
		raise ScheduleError('no report: send .jobs add for the reports')
	return commands


def check_time(when):
	"""Raise ImpossibleTime for a time that cannot be (minute 61) or never comes (30 February)."""
	if when == '@reboot':
		raise ImpossibleTime('@reboot is no time: the jobs start with the bot')
	if not croniter.is_valid(when):
		raise ImpossibleTime(f"'{when}' is no time: five fields (minute hour day month weekday) or an @macro")
	try:
		croniter(when, datetime.datetime(2000, 1, 1)).get_next(datetime.datetime)
	except CroniterBadDateError:
		raise ImpossibleTime(f"'{when}' never comes: no date matches it")


def parse_job(line, chat='', on=True, system=False):
	"""A Job from its line, as .jobs add takes it: [CRON_TZ=Zone] five time fields (or an @macro), then its reports.
	Raises ScheduleError (ImpossibleTime for the time), saying what is wrong."""
	line = line.strip()
	zone = UTC
	if m := re.match(r'CRON_TZ=(\S*)\s*', line):
		try:
			zone = zoneinfo.ZoneInfo(m.group(1))
		except (ValueError, zoneinfo.ZoneInfoNotFoundError):
			raise ScheduleError(f'no time zone {m.group(1)!r} (such as America/New_York)')
		line = line[m.end():]
	if line.startswith('@'):
		when, _, reports = line.partition(' ')
	else:
		fields = line.split(None, 5)
		if len(fields) < 6:
			raise ScheduleError('a job is five time fields (minute hour day month weekday), then its reports')
		when, reports = ' '.join(fields[:5]), fields[5]
	check_time(when)
	return Job(when, parse_reports(reports, system), zone, chat, on, reports.strip())


class Scheduler:
	"""Fires the jobs: each chat's, from SCHEDULE_FILE, and the system jobs. clock, sleep, spawn and runner can be
	replaced, which the tests do. Its lock covers what the loop, a change from chat and the runs share: the jobs, their
	bases, the record of runs and what is running."""

	def __init__(self, catchup=None, clock=None, sleep=None, spawn=None, runner=None):
		"""catchup is how late, in minutes, a missed run may still start (the scheduler_catchup setting when None);
		clock, sleep, spawn and runner stand in for the real ones in tests."""
		self.catchup = datetime.timedelta(minutes=config.env.scheduler_catchup if catchup is None else catchup)
		self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
		self.sleep = sleep or time.sleep
		self.spawn = spawn or start_thread
		self.runner = runner or run_in_process # (label, module, kwargs, dest): runs the command
		self.jobs = []
		self.base = {} # key -> the time after which the next run is due
		self.last = {}
		self.busy = set() # (chat, label) of the commands running now, scheduled or manual
		self.lock = threading.Lock()

	def load(self):
		"""Read every chat's jobs from SCHEDULE_FILE, besides the system jobs: at start, and after every change from a
		chat. A job the file holds that cannot be any more (a report since retired) is reported and left out. A job
		kept from before keeps its timing; a new one counts from now, as one does that was off."""
		jobs = [parse_job(f'{when} {reports}', system=True) for when, reports in SYSTEM]
		for chat, entries in state.load(SCHEDULE_FILE, {}).items():
			for entry in entries:
				try:
					zone = '' if entry.get('zone', 'UTC') == 'UTC' else f"CRON_TZ={entry['zone']} "
					jobs.append(parse_job(f"{zone}{entry['when']} {entry['reports']}", chat, entry.get('on', True)))
				except (ScheduleError, KeyError, TypeError) as e:
					delivery.report_error(ScheduleError(f'a job of {chat} left out: {e}: {entry}'), context='schedule')
		with self.lock: # no run is recorded between reading the record and swapping it in
			try:
				last, problem = state.load(STATE_FILE), None
			except (OSError, ValueError) as e: # unreadable or not JSON: start without one; the next run rewrites it
				last, problem = None, f'cannot read {STATE_FILE}, starting without a record of past runs: {e}'
			self.last = last if isinstance(last, dict) else {}
			now = self.clock()
			old = {job.key: self.base[job.key] for job in self.jobs if job.key in self.base}
			self.base = {job.key: old.get(job.key) or self.start_base(job, now) for job in jobs}
			self.jobs = jobs
		if problem:
			delivery.report_error(ScheduleError(problem), context='schedule')
		chats = len({job.chat for job in jobs if job.chat})
		print(f"schedule: {len(jobs) - len(SYSTEM)} jobs of {chats} chat{'' if chats == 1 else 's'}, and"
			f" {len(SYSTEM)} system jobs", file=sys.stderr)

	def start_base(self, job, now):
		"""Where to count from at start: a run missed in the catch-up window fires once; with no record, none is."""
		last = self.last.get(job.key)
		if not last or not job.on:
			return now
		try:
			return max(datetime.datetime.fromisoformat(last), now - self.catchup)
		except ValueError:
			return now

	def next_fire(self, job, after):
		"""The first fire time after `after`, in the job's zone. croniter is given the naive local time and the zone is
		put back after: croniter up to 6.0 (the distro packages) mishandles zoneinfo across DST changes, firing daily
		jobs twice or an hour late. A time the clocks repeat fires once, the first time; one they skip (02:30 as they go
		forward) fires an hour later by the clock."""
		times = croniter(job.when, after.astimezone(job.zone).replace(tzinfo=None))
		while True:
			# fold 0: the first of a repeated time
			t = times.get_next(datetime.datetime).replace(tzinfo=job.zone).timestamp()
			# by the instant: comparing two times of one zone ignores which of a repeated hour they are in
			if t > after.timestamp():
				return datetime.datetime.fromtimestamp(t, job.zone)

	def due(self, now):
		"""The jobs to run now, as (job, fire time). Several missed fire times of one job run it once. A job that is off
		never fires, and counts from now: switched on, it does not catch up."""
		fired = []
		with self.lock:
			for job in self.jobs:
				if not job.on:
					self.base[job.key] = now
					continue
				base, latest = self.base[job.key], None
				while (t := self.next_fire(job, base)) <= now:
					latest, base = t, t
				if latest:
					self.base[job.key] = latest
					self.last[job.key] = latest.isoformat()
					fired.append((job, latest))
			if fired:
				try:
					state.save(STATE_FILE, self.last)
				except OSError as e:
					print('schedule: cannot save', STATE_FILE, e, file=sys.stderr)
		return fired

	def claim(self, chat, label):
		"""Mark a chat's command running, unless it already is (scheduled or manual): whether it was claimed."""
		with self.lock:
			if (chat, label) in self.busy:
				return False
			self.busy.add((chat, label))
			return True

	def execute(self, commands, chat=''):
		"""Run commands one after another (a job's), in this thread, posting to the chat whose job it is (its key; ''
		for a system job, whose failure goes to the home chats); a failure is reported. One already running for that
		chat is skipped. One still running after JOB_TIMEOUT is reported as late, once, and runs on: a thread cannot be
		stopped, but every request it makes has a timeout, so it ends; until then it stays marked running, and no
		second copy starts. Returns 'done', 'failed' or 'already running'."""
		dest = delivery.chat(chat, scheduled=True) if chat else None
		outcome = 'done'
		for label, module, kwargs in commands:
			if not self.claim(chat, label):
				print(f'schedule: {label} is already running for {chat or "the system"}, skipping it', file=sys.stderr)
				outcome = 'already running'
				continue
			print(f'schedule: running {label}' + (f' for {chat}' if chat else ''), file=sys.stderr)
			late = threading.Timer(JOB_TIMEOUT, delivery.report_error, args=(TimeoutError(f'still running after'
				f' {JOB_TIMEOUT / 60:g} minutes, and left to finish'), dest), kwargs={'context': label})
			late.daemon = True
			late.start()
			try:
				self.runner(label, module, kwargs, dest)
			except (Exception, SystemExit) as e:
				delivery.report_error(e, dest, context=label)
				outcome = 'failed'
			finally:
				late.cancel()
				with self.lock:
					self.busy.discard((chat, label))
		return outcome

	def running(self, chat):
		"""The labels of the commands running now for a chat (by its key), and for the system."""
		with self.lock:
			return {label for where, label in self.busy if where in (chat, '')}

	def chat_jobs(self, chat):
		"""A chat's jobs, in their order: .jobs numbers them from 1."""
		with self.lock:
			return [job for job in self.jobs if job.chat == chat]

	def system_jobs(self):
		"""The system jobs."""
		with self.lock:
			return [job for job in self.jobs if not job.chat]

	def job(self, chat, number):
		"""A chat's job by its number in .jobs (a string, from a chat). Raises ScheduleError."""
		jobs = self.chat_jobs(chat)
		if not (number.isascii() and number.isdigit() and 1 <= int(number) <= len(jobs)):
			raise ScheduleError(f'no job {number}: send .jobs for the list' if jobs else 'no jobs here yet: .jobs add')
		return jobs[int(number) - 1]

	def pick(self, chat, number, crc):
		"""The job a button stands for. Button data is untrusted input: the number must be plain digits within this
		chat's list, and the checksum must match that very job, else ScheduleError."""
		job = self.job(chat, number)
		if not hmac.compare_digest(checksum(job.key), crc):
			raise ScheduleError('the jobs have changed')
		return job

	def run(self, job):
		"""Run a job now, as its schedule would: its outcome (see execute)."""
		return self.execute(job.commands, job.chat)

	def change(self, chat, edit):
		"""Change a chat's jobs, as stored: edit(entries) does it to the list (and may raise ScheduleError); then they
		are read again, so that the change counts at once. Returns what edit returned."""
		with state.edit(SCHEDULE_FILE, {}) as chats:
			entries = chats.setdefault(chat, [])
			result = edit(entries)
			if not entries:
				del chats[chat]
		self.load()
		return result

	def add(self, chat, line):
		"""Add a job to a chat's list (a line as parse_job takes it), on: its number. Raises ScheduleError."""
		job = parse_job(line, chat)
		def append(entries):
			"""Append the job, within MAX_JOBS."""
			if len(entries) >= MAX_JOBS:
				raise ScheduleError(f'{MAX_JOBS} jobs is the most a chat may have: delete one first')
			entries.append({'when': job.when, 'reports': job.text, 'zone': job.zone.key, 'on': True})
			return len(entries)
		return self.change(chat, append)

	def delete(self, job):
		"""Delete a chat's job (from job() or pick())."""
		self.change(job.chat, lambda entries: entries.pop(self.index(entries, job)))

	def toggle(self, job):
		"""Switch a chat's job on or off: whether it is on now."""
		def flip(entries):
			"""Flip the job's switch."""
			entry = entries[self.index(entries, job)]
			entry['on'] = not entry.get('on', True)
			return entry['on']
		return self.change(job.chat, flip)

	@staticmethod
	def index(entries, job):
		"""Where a job is among its chat's stored entries. Raises ScheduleError when it is gone meanwhile."""
		for i, entry in enumerate(entries):
			zone = entry.get('zone', 'UTC')
			if (entry.get('when'), entry.get('reports'), zone) == (job.when, job.text, job.zone.key):
				return i
		raise ScheduleError('that job is gone: send .jobs for the list')

	def next_run(self, job):
		"""When a job fires next, or None when it is off."""
		if not job.on:
			return None
		with self.lock:
			base = self.base.get(job.key) or self.clock()
		return self.next_fire(job, max(base, self.clock()))

	def tick(self):
		"""Start what is due; returns the seconds until the next fire time."""
		now = self.clock()
		for job, fire_time in self.due(now):
			self.spawn(self.execute, job.commands, job.chat)
		with self.lock:
			waits = [(self.next_fire(job, self.base[job.key]) - now).total_seconds() for job in self.jobs if job.on]
		return min(30, max(1, math.ceil(min(waits)))) if waits else 30

	def run_forever(self):
		"""Never returns, never raises: a failure is reported and the loop carries on."""
		while True:
			try:
				self.sleep(self.tick())
			except Exception as e:
				delivery.report_error(e, context='schedule')
				self.sleep(30)
