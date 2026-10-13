"""The scheduled reports (formerly cron jobs), run by the bot itself.

The schedule is a file in crontab syntax: five time fields (or an @macro) and then a finbot script with its arguments, e.g.
`*/20 * * * Mon-Fri trades.py` or `28 21 * * Sat cal.py earnings; price.py 7`. Pasted crontab lines (`./price.py > /dev/null`,
`{ a; b ;}`) are accepted too. Running in the bot means the jobs share its user, sandbox, environment and cache."""
import datetime
import hmac
import json
import math
import os
import re
import shlex
import sys
import zlib
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path

import gevent
from gevent import subprocess
from croniter import croniter

from lib.config import *
from lib import util
from lib import webhook
import cal, cleanup, milestone, performance, podcasts, price, rating, reminder, shorts, trades

SCRIPTS = {'cal': cal, 'cleanup': cleanup, 'milestone': milestone, 'performance': performance, 'podcasts': podcasts, 'price': price,
	'rating': rating, 'reminder': reminder, 'shorts': shorts, 'trades': trades}
current = None # the running Scheduler, set by bot.py; the chat commands use it
HIDDEN = ('cleanup', 'podcasts') # scheduled, but not offered in the chat list
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = 'finbot_jobs.json' # last fire time of every job, so a restart neither repeats a run nor loses one
JOB_TIMEOUT = 15 * 60 # seconds a job may run before it is abandoned and reported
IGNORED_VARIABLES = ('MAILTO', 'SHELL', 'PATH', 'HOME', 'LOGNAME')
OPERATOR = re.compile(r'\d*>>?&?\d*|&>>?|;|&&|\|\|?|&|[<`$(){}]') # what a shell reads as more than a word, outside quotes
REDIRECT = re.compile(r'\d*>>?&?\d*|&>>?') # > file, >> file, 2>&1, &> file


def checksum(label):
	"""Short stand-in for a command in a Telegram button, whose data is limited to 64 bytes: detects a changed schedule."""
	return format(zlib.crc32(label.encode()) & 0xffff, '04x')


def run_child(label, module, kwargs):
	"""Run a command in its own process (python -m lib.jobrun) and return its exit status. The child inherits the environment,
	user and output of the bot, so it behaves like the old cron job. A timeout or any other interruption stops the child."""
	proc = subprocess.Popen([sys.executable, '-m', 'lib.jobrun', module.__name__, json.dumps(kwargs)], cwd=ROOT)
	try:
		return proc.wait()
	except BaseException:
		proc.terminate()
		try:
			proc.wait(timeout=10)
		except subprocess.TimeoutExpired:
			proc.kill()
			proc.wait()
		raise


def run_in_process(label, module, kwargs):
	"""The runner for tests: call the handler here instead of in a child process."""
	module.lambda_handler(**kwargs)
	return 0


def display(label):
	"""A command as shown in chat: 'price.py close' -> 'price close'."""
	return re.sub(r'^(\w+)\.py', r'\1', label)


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


def tokenize(text):
	"""A command line as ('word', text) and ('op', text) tokens. Quoted text is always a word, whatever it contains."""
	tokens, word, started, i = [], '', False, 0
	def flush():
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
	"""Word lists, one per command: split on unquoted ; and &&, redirects and braces dropped, any other shell syntax refused."""
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

	def __init__(self, path, catchup=config_scheduler_catchup, clock=None, sleep=None, spawn=None, zone=None, runner=None):
		self.path = path
		self.catchup = datetime.timedelta(minutes=catchup)
		self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
		self.sleep = sleep or gevent.sleep
		self.spawn = spawn or gevent.spawn
		self.runner = runner or run_child # (label, module, kwargs) -> exit status
		self.zone = zone
		self.jobs = []
		self.base = {} # key -> the time after which the next run is due
		self.last = {}
		self.busy = set() # labels of the commands running now, scheduled or manual

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
		print(f"schedule: {len(jobs)} job{'' if len(jobs) == 1 else 's'} from {path}", file=sys.stderr)
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
			return 'already running'
		return self.execute(job, job.commands)

	def execute(self, job, commands):
		"""Run commands one after another. `job` (None for a manual run of one command) is marked running meanwhile. A command that
		is already running, scheduled or manual, is skipped. Returns 'done', 'timed out', 'failed' or 'already running'."""
		if job:
			job.running = True
		outcome, label = 'done', ''
		timeout = gevent.Timeout(JOB_TIMEOUT)
		timeout.start()
		try:
			for label, module, kwargs in commands:
				if label in self.busy:
					print(f'schedule: {label} is already running, skipping it', file=sys.stderr)
					outcome = 'already running'
					continue
				self.busy.add(label)
				print(f'schedule: running {label}', file=sys.stderr)
				try:
					if self.runner(label, module, kwargs):
						outcome = 'failed' # the child has already reported why
				except gevent.Timeout:
					raise
				except (Exception, SystemExit) as e:
					webhook.report_error(e, context=label)
					outcome = 'failed'
				finally:
					self.busy.discard(label)
		except gevent.Timeout as t:
			if t is not timeout:
				raise
			webhook.report_error(TimeoutError(f'still running after {JOB_TIMEOUT // 60} minutes'), context=label)
			outcome = 'timed out'
		finally:
			timeout.close()
			if job:
				job.running = False
		return outcome

	def commands(self):
		"""Every offered scheduled command once, sorted by name with numbers in numeric order: [(label, module, kwargs)]. The time,
		comments, redirects and the other commands of a line are not part of it; HIDDEN scripts are left out."""
		unique = {}
		for job in self.jobs:
			for command in job.commands:
				if command[1] not in [SCRIPTS[name] for name in HIDDEN]:
					unique.setdefault(command[0], command)
		natural = lambda label: [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', label.lower())]
		return [unique[label] for label in sorted(unique, key=natural)]

	def select(self, text):
		"""The scheduled command for `.jobs run <text>`: a number from the list, or the command itself. Raises ScheduleError."""
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
		raise ScheduleError(f"'{text}' is not in the schedule; send .jobs to list the commands")

	def pick(self, number, crc):
		"""The offered command a button stands for. Button data is untrusted input: the number must be plain digits within the
		list and the checksum must match that very command, else ScheduleError."""
		commands = self.commands()
		if not (number.isascii() and number.isdigit() and 1 <= int(number) <= len(commands)):
			raise ScheduleError('no such command')
		command = commands[int(number) - 1]
		if not hmac.compare_digest(checksum(command[0]), crc):
			raise ScheduleError('the schedule changed')
		return command

	def run_command(self, command):
		"""Run one command returned by select() or pick(). Returns (label, outcome)."""
		return command[0], self.execute(None, [command])

	def run_now(self, text):
		"""`.jobs run`: one scheduled command, now, as cron would run it; the schedule is unchanged. Returns (label, outcome)."""
		return self.run_command(self.select(text))

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
