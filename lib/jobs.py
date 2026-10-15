"""The scheduled reports (formerly cron jobs), run by the bot itself.

The schedule is a file in crontab syntax: five time fields (or an @macro) and then a finbot script with its
arguments, e.g. `*/20 * * * Mon-Fri trades.py` or `28 21 * * Sat cal.py earnings; price.py 7`. Pasted crontab lines
(`./price.py > /dev/null`, `{ a; b ;}`) are accepted too. Running in the bot means the jobs share its user, sandbox,
environment and cache."""
import datetime
import hmac
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import zlib
import zoneinfo
from dataclasses import dataclass
from pathlib import Path

from croniter import croniter, CroniterBadDateError

from lib import config
from lib import state
from lib import jobrun
from lib import delivery
from lib.reports import cal, cleanup, milestone, performance, podcasts, price, rating, reminder, shorts, trades
from lib.reports import yahoo_warm

SCRIPTS = {'cal': cal, 'cleanup': cleanup, 'milestone': milestone, 'performance': performance, 'podcasts': podcasts,
	'price': price, 'rating': rating, 'reminder': reminder, 'shorts': shorts, 'trades': trades,
	'yahoo_warm': yahoo_warm}
current = None # the running Scheduler, set by bot.py; the chat commands use it
HIDDEN = ('cleanup', 'podcasts', 'yahoo_warm') # scheduled, but not run from chat: .jobs lists them under System
STATE_FILE = 'finbot_jobs.json' # last fire time of every job, so a restart neither repeats a run nor loses one
JOB_TIMEOUT = 5 * 60 # seconds each command may run before it is stopped and reported
IGNORED_VARIABLES = ('MAILTO', 'SHELL', 'PATH', 'HOME', 'LOGNAME')
# what a shell reads as more than a word, outside quotes
OPERATOR = re.compile(r'\d*>>?&?\d*|&>>?|;|&&|\|\|?|&|[<`$(){}]')
REDIRECT = re.compile(r'\d*>>?&?\d*|&>>?') # > file, >> file, 2>&1, &> file


def checksum(label):
	"""A command's short stand-in in a button (Telegram allows 64 bytes of data): it detects a changed schedule."""
	return format(zlib.crc32(label.encode()) & 0xffff, '04x')


def run_child(label, module, kwargs):
	"""Run a command in its own process (python -m lib.jobrun) and return its exit status. The child inherits the
	environment, user and output of the bot, so it behaves like the old cron job. One still running after JOB_TIMEOUT
	is stopped and TimeoutError raised; any other interruption stops it too."""
	# the preferences this process runs on, not whatever the file says now
	env = dict(os.environ, **config.child_environment())
	args = [sys.executable, '-m', 'lib.jobrun', module.__name__, json.dumps(kwargs)]
	proc = subprocess.Popen(args, cwd=config.REPO_DIR, env=env)
	try:
		return proc.wait(timeout=JOB_TIMEOUT)
	except subprocess.TimeoutExpired:
		stop(proc)
		raise TimeoutError(f'still running after {JOB_TIMEOUT // 60} minutes') from None
	except BaseException:
		stop(proc)
		raise


def stop(proc):
	"""End a child process: asked to stop, then killed if it is still there 10 seconds later."""
	proc.terminate()
	try:
		proc.wait(timeout=10)
	except subprocess.TimeoutExpired:
		proc.kill()
		proc.wait()


def start_thread(target, *args):
	"""Run target(*args) in a daemon thread of its own (a greenlet, under gevent's monkey patching)."""
	threading.Thread(target=target, args=args, daemon=True).start()


def exit_reason(status):
	"""Why a job process ended, when it did not report it itself: killed by a signal, or failed before it could say."""
	if status < 0:
		try:
			return f'killed by {signal.Signals(-status).name}'
		except ValueError:
			return f'killed by signal {-status}'
	return f'exited with status {status} without saying why'


def display(label):
	"""A command as shown in chat: 'price.py close' -> 'price close'."""
	return re.sub(r'^(\w+)\.py', r'\1', label)


class ScheduleError(ValueError):
	pass


class ImpossibleTime(ScheduleError):
	"""A time that cannot be (minute 61) or never comes (30 February). Other bad lines are reported and skipped, but
	this refuses the whole file: finbot does not start with it, and a reload keeps the schedule that is running. `lines`
	says where, one per line."""
	def __init__(self, lines):
		"""lines: where, one message or a list of them."""
		self.lines = [lines] if isinstance(lines, str) else list(lines)
		super().__init__('; '.join(self.lines))


@dataclass
class Job:
	expr: str
	commands: list # [(label, module, kwargs)], run one after another
	zone: zoneinfo.ZoneInfo
	text: str
	key: str


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
				raise ScheduleError('No closing quotation')
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
	"""Word lists, one per command: split on unquoted ; and &&, redirects and braces dropped, other syntax refused."""
	commands, current, target = [], [], False
	for kind, value in tokens:
		if target: # the file of a redirect
			target = False
			if kind == 'word':
				continue
		if kind == 'word':
			current.append(value)
		elif value in (';', '&&'):
			commands.append(current)
			current = []
		elif value in ('{', '}'):
			continue
		elif REDIRECT.fullmatch(value):
			target = not re.search(r'&\d+$', value) # 2>&1 has no file after it, > /dev/null does
		else:
			raise ScheduleError('only finbot scripts can be scheduled, not shell commands')
	commands.append(current)
	return [words for words in commands if words]


def parse_command(text):
	"""'~/finbot/price.py midsession > /dev/null' -> [('price.py midsession', price, {...})]. Raises ScheduleError."""
	commands = []
	for words in split_commands(tokenize(text)):
		while words and re.fullmatch(r'\w+=\S*', words[0]):
			words.pop(0) # FOO=bar prefix
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
	"""(jobs, errors): errors are (line number, line, ScheduleError) for the lines that were skipped."""
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
			if expr == '@reboot':
				raise ScheduleError('@reboot is not supported: the schedule starts with the bot')
			if not croniter.is_valid(expr):
				raise ImpossibleTime(f"bad time '{expr}'")
			try:
				croniter(expr, datetime.datetime(2000, 1, 1)).get_next(datetime.datetime)
			except CroniterBadDateError:
				raise ImpossibleTime(f"'{expr}' never comes: no date matches it")
			commands = parse_command(rest)
			key = f"{expr}|{zone.key}|{';'.join(label for label, _, _ in commands)}"
			jobs.append(Job(expr, commands, zone, line, key))
		except ScheduleError as e:
			errors.append((number, line, e))
	return jobs, errors


class Scheduler:
	"""Fires the jobs of a schedule file. `path` is a callable returning the file (the data dir copy wins over the
	default, so a new copy is found on reload). `clock`, `sleep` and `spawn` can be replaced, which the tests do. Its
	lock covers what the loop, a reload and runs from chat share: the jobs, their bases, the record of runs and what is
	running."""

	def __init__(self, path, catchup=None, clock=None, sleep=None, spawn=None, zone=None, runner=None):
		"""path() gives the schedule file's path. catchup is how late, in minutes, a missed run may still start (the
		scheduler_catchup setting when None); clock, sleep, spawn, zone and runner stand in for the real ones in
		tests."""
		self.path = path
		self.catchup = datetime.timedelta(minutes=config.env.scheduler_catchup if catchup is None else catchup)
		self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
		self.sleep = sleep or time.sleep
		self.spawn = spawn or start_thread
		self.runner = runner or run_child # (label, module, kwargs) -> exit status
		self.zone = zone
		self.jobs = []
		self.base = {} # key -> the time after which the next run is due
		self.last = {}
		self.busy = set() # labels of the commands running now, scheduled or manual
		self.lock = threading.Lock()

	def load(self):
		"""Read the schedule file. A line with an impossible time refuses the whole file: ImpossibleTime is raised,
		naming every such line, and nothing changes. Other bad lines are reported and skipped; a file with no usable
		line keeps the schedule that is running."""
		path = self.path()
		try:
			jobs, errors = parse_schedule(Path(path).read_text(encoding='utf-8'), self.zone)
		except OSError as e:
			delivery.report_error(e, context='schedule')
			return False
		impossible = [f'{path} line {number}: {error}: {line}' for number, line, error in errors
			if isinstance(error, ImpossibleTime)]
		if impossible:
			raise ImpossibleTime(impossible)
		for number, line, error in errors:
			delivery.report_error(ScheduleError(f'{path} line {number}: {error}: {line}'), context='schedule')
		if not jobs and self.jobs:
			print('schedule: no usable line in', path, '- keeping the current schedule', file=sys.stderr)
			return False
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
		print(f"schedule: {len(jobs)} job{'' if len(jobs) == 1 else 's'} from {path}", file=sys.stderr)
		return True

	def reload(self, *args):
		"""SIGHUP: read the edited file. One with an impossible time is refused and reported; the schedule stays."""
		try:
			self.load()
		except ImpossibleTime as e:
			problem = f'not reloaded, the running schedule is unchanged: {e}'
			delivery.report_error(ScheduleError(problem), context='schedule')

	def start_base(self, job, now):
		"""Where to count from at start: a run missed in the catch-up window fires once; with no record, none is."""
		last = self.last.get(job.key)
		if not last:
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
		times = croniter(job.expr, after.astimezone(job.zone).replace(tzinfo=None))
		while True:
			# fold 0: the first of a repeated time
			t = times.get_next(datetime.datetime).replace(tzinfo=job.zone).timestamp()
			# by the instant: comparing two times of one zone ignores which of a repeated hour they are in
			if t > after.timestamp():
				return datetime.datetime.fromtimestamp(t, job.zone)

	def due(self, now):
		"""The jobs to run now, as (job, fire time). Several missed fire times of one job run it once."""
		fired = []
		with self.lock:
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
					state.save(STATE_FILE, self.last)
				except OSError as e:
					print('schedule: cannot save', STATE_FILE, e, file=sys.stderr)
		return fired

	def claim(self, label):
		"""Mark a command running, unless it already is (scheduled or manual): whether it was claimed."""
		with self.lock:
			if label in self.busy:
				return False
			self.busy.add(label)
			return True

	def execute(self, commands):
		"""Run commands one after another (a job's), each stopped and reported if still running after JOB_TIMEOUT.
		One already running (from the line's last run, another line or chat) is skipped. Returns 'done', 'timed out',
		'failed' or 'already running'."""
		outcome = 'done'
		for label, module, kwargs in commands:
			if not self.claim(label):
				print(f'schedule: {label} is already running, skipping it', file=sys.stderr)
				outcome = 'already running'
				continue
			print(f'schedule: running {label}', file=sys.stderr)
			try:
				status = self.runner(label, module, kwargs)
				if status:
					outcome = 'failed'
					if status != jobrun.REPORTED: # it ended without saying why
						delivery.report_error(RuntimeError(exit_reason(status)), context=label)
			except TimeoutError as e: # run_child stopped it: the rest of the line still runs
				delivery.report_error(e, context=label)
				outcome = 'timed out'
			except (Exception, SystemExit) as e:
				delivery.report_error(e, context=label)
				outcome = 'failed'
			finally:
				with self.lock:
					self.busy.discard(label)
		return outcome

	def commands(self, hidden=False):
		"""Every scheduled command offered in chat once, or with hidden=True each of the HIDDEN scripts' (System),
		sorted by name with numbers in numeric order: [(label, module, kwargs)]. The time, comments, redirects and the
		other commands of a line are not part of it."""
		unique = {}
		system = {SCRIPTS[name] for name in HIDDEN}
		for job in self.jobs:
			for command in job.commands:
				if (command[1] in system) == hidden:
					unique.setdefault(command[0], command)
		natural = lambda label: [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', label.lower())]
		return [unique[label] for label in sorted(unique, key=natural)]

	def select(self, text):
		"""The scheduled command for `.jobs run <text>`: a number in the list, or the command. Raises ScheduleError."""
		text = text.strip()
		commands = self.commands()
		if text.isdigit():
			if not 1 <= int(text) <= len(commands):
				raise ScheduleError(f'no command {text}; send .jobs to list them')
			return commands[int(text) - 1]
		try:
			wanted = parse_command(text)
		except ScheduleError as e:
			raise ScheduleError(f'{e}; send .jobs to list the commands')
		if len(wanted) != 1:
			raise ScheduleError('run one command at a time; send .jobs to list them')
		for command in commands:
			if command[0] == wanted[0][0]:
				return command
		if any(command[0] == wanted[0][0] for command in self.commands(hidden=True)):
			raise ScheduleError(f'{display(wanted[0][0])} is a system job: it runs on its schedule only')
		raise ScheduleError(f"'{text}' is not in the schedule; send .jobs to list the commands")

	def pick(self, number, crc):
		"""The offered command a button stands for. Button data is untrusted input: the number must be plain digits
		within the list and the checksum must match that very command, else ScheduleError."""
		commands = self.commands()
		if not (number.isascii() and number.isdigit() and 1 <= int(number) <= len(commands)):
			raise ScheduleError('no such command')
		command = commands[int(number) - 1]
		if not hmac.compare_digest(checksum(command[0]), crc):
			raise ScheduleError('the schedule changed')
		return command

	def run_command(self, command):
		"""Run one command returned by select() or pick(). Returns (label, outcome)."""
		return command[0], self.execute([command])

	def run_now(self, text):
		"""`.jobs run`: one scheduled command now, as cron runs it; the schedule stays. Returns (label, outcome)."""
		return self.run_command(self.select(text))

	def tick(self):
		"""Start what is due; returns the seconds until the next fire time."""
		now = self.clock()
		for job, fire_time in self.due(now):
			self.spawn(self.execute, job.commands)
		with self.lock:
			waits = [(self.next_fire(job, self.base[job.key]) - now).total_seconds() for job in self.jobs]
		return min(30, max(1, math.ceil(min(waits)))) if waits else 30

	def run_forever(self):
		"""Never returns, never raises: a failure is reported and the loop carries on."""
		while True:
			try:
				self.sleep(self.tick())
			except Exception as e:
				delivery.report_error(e, context='schedule')
				self.sleep(30)
