"""The scheduled jobs. Each chat's, which its people manage with .jobs (lib/worker.py), each posting to that chat: the
default jobs (lib/catalog.py), which every chat has, switched on until it switches them off, and those it added; both
kept in JOBS_FILE by chat key, whose chats are those finbot knows (see). And the system jobs (SYSTEM), fixed here, which
fill the cache and clear it out.

A job runs one action of ACTIONS, a fixed table of finbot's own report modules (message among them, which posts a
text), with the arguments that action's parser (its job()) takes: never a command, a script or code. A stored job names
its action and holds its arguments as words, and both are checked again as it loads. Its schedule (lib/when.py) says
which days and times, in its zone. The bot runs each job itself, in a thread of its own, sharing its user,
environment, caches and connections."""
import dataclasses
import datetime
import heapq
import hmac
import json
import math
import os
import threading
import time
import zlib

from lib import catalog
from lib import config
from lib import delivery
from lib import log
from lib import sharesight
from lib import state
from lib import when
from lib.reports import cal, cleanup, message, milestone, performance, podcasts, price, rating, shorts, trades
from lib.reports import sharesight_warm, yahoo_warm

# what a job may run, by name: a report module of finbot's own, whose run() is called with what its job() made of the
# job's arguments; nothing else is ever called, imported or evaluated
ACTIONS = {'cal': cal, 'message': message, 'milestone': milestone, 'performance': performance, 'podcasts': podcasts,
	'price': price, 'rating': rating, 'shorts': shorts, 'trades': trades,
	'cleanup': cleanup, 'sharesight_warm': sharesight_warm, 'yahoo_warm': yahoo_warm}
SYSTEM_ACTIONS = ('cleanup', 'sharesight_warm', 'yahoo_warm') # the system's alone: a chat cannot schedule these
# the system jobs, in UTC: the Sharesight portfolios and holdings fetched afresh every 30 minutes (cached 40), the price
# histories of the stocks followed every 4 hours (cached 6), so that no request waits on either; and cache files
# older than 30 days deleted weekly
SYSTEM = (('sharesight_warm', (), {'every': 30, 'from': '00:14'}), ('yahoo_warm', (), {'every': 240, 'from': '00:07'}),
	('cleanup', ('30',), {'days': ['sat'], 'at': '18:51'}))
WARM = ('sharesight_warm', 'yahoo_warm') # the jobs that fill the cache, run at once after a flush too
# {chat key: {'jobs': [{action, args, schedule, on}], 'off': [catalog keys], 'deleted': [catalog keys]}}: the jobs it
# added, the default jobs it switched off and those it removed; a chat whose default jobs start off holds 'defaults':
# 'off' and 'on' instead of 'off', the catalog keys switched on; a direct message holds 'dm': True
JOBS_FILE = 'finbot_chat_jobs.json'
OLD_FILE = 'finbot_schedule.json' # each chat's cron jobs, from before the catalog: read for its chats alone
STATE_FILE = 'finbot_jobs.json' # each job's last run, by key: a restart neither repeats a run nor loses one
MESSAGE_AT = 8 * 60 + 30 # a message's time of day where none is typed: 8:30am
MAX_JOBS = 30 # the jobs a chat may add, at most
JOB_TIMEOUT = 5 * 60 # seconds a job may run before it is reported as late, once (it runs on, see execute)
MINUTE = datetime.timedelta(minutes=1)
QUOTES = '"“”' # what opens and closes a message's text: phones type curly quotes
UTC = when.UTC
ScheduleError = when.ScheduleError
current = None # the running Scheduler, set by bot.py; the chat commands use it


@dataclasses.dataclass
class Job:
	"""A job: the action it runs (a name in ACTIONS), the arguments its parser took and what it made of them (a label,
	run's keyword arguments); its schedule; the chat it posts to (its key, as delivery.chat takes it; '' for a system
	job); whether it is on; its catalog item (its key; None for one its chat added); and the name .jobs shows."""
	action: str
	args: tuple
	label: str
	kwargs: dict
	schedule: when.Schedule
	chat: str = ''
	on: bool = True
	item: str = None
	name: str = ''

	@property
	def key(self):
		"""What the job is, for its record of runs and the checksum of its buttons: its chat and catalog item, or its
		chat, action, arguments and schedule."""
		if self.item:
			return f'{self.chat}|{self.item}'
		return f'{self.chat}|{self.action}|{json.dumps(list(self.args), ensure_ascii=False)}|{self.schedule.key}'

	@property
	def module(self):
		"""What runs it: a report module, or a command of .help (worker.CommandJob)."""
		return actions()[self.action]

	def stored(self):
		"""The job as JOBS_FILE keeps one a chat added."""
		return {'action': self.action, 'args': list(self.args), 'schedule': self.schedule.to_json(), 'on': self.on}


def checksum(text):
	"""A job's short stand-in in a button (Telegram allows 64 bytes of data): it tells a changed list."""
	return format(zlib.crc32(text.encode()) & 0xffff, '04x')


def list_checksum(jobs):
	"""A chat's list's short stand-in in the .jobs menu's buttons: it tells any change of the list, so that a button
	drawn for another list acts on nothing."""
	return checksum('\n'.join(job.key for job in jobs))


def run_in_process(label, module, kwargs, dest=None):
	"""Run a job here, in the calling thread: its report's run(**kwargs), posting to dest (a chat's job; None for a
	system job, which posts nothing)."""
	if dest is None:
		module.run(**kwargs)
	else:
		module.run(dest, **kwargs)


def start_thread(target, *args):
	"""Run target(*args) in a daemon thread of its own."""
	threading.Thread(target=target, args=args, daemon=True).start()


def system_jobs():
	"""The system jobs (SYSTEM), as Jobs."""
	return [make_job(action, args, when.Schedule.from_json({**times, 'zone': 'UTC'})) for action, args, times in SYSTEM]


def warm_now(scheduler=None):
	"""Run the warm jobs (WARM) now, one after the other: through the scheduler, so that one running on its schedule
	is not started twice; without one (a test, a tool), here, a failure reported as the scheduler reports it."""
	warm = [job for job in system_jobs() if job.action in WARM]
	log.info('cache: filling it again:', ', '.join(job.label for job in warm))
	for job in warm:
		if scheduler:
			scheduler.execute(job)
			continue
		try:
			run_in_process(job.label, job.module, job.kwargs)
		except Exception as e:
			delivery.report_error(e, context=job.label)
	log.info('cache: warm jobs done')


def actions():
	"""Every action a job may name: the report modules (ACTIONS), and the commands of .help that a job may run
	(command_actions), each standing in for a report module."""
	return {**command_actions(), **ACTIONS}


def command_actions():
	"""The commands of .help that a job may run, by each name a job may call one by (worker.job_commands)."""
	from lib import worker # here, not at the top: worker imports this module
	return worker.job_commands()


def chat_actions():
	"""The actions a chat may schedule, by name: the reports, then the commands of .help a job may run, as .help names
	them."""
	return sorted(name for name in ACTIONS if name not in SYSTEM_ACTIONS) + [name for name, command in
		command_actions().items() if command.listed]


def make_job(action, args, schedule, chat='', on=True, item=None, name=None):
	"""A Job of an action (actions()) with the arguments its parser takes (words), on a when.Schedule: the system's
	actions only for a system job (no chat); a command by the name a job calls it (its name in .help). Raises
	ScheduleError, saying what is wrong."""
	known = actions()
	if not isinstance(action, str) or action not in known or (chat and action in SYSTEM_ACTIONS):
		raise ScheduleError(f"no report {action!r}: send .jobs add for the reports")
	if not isinstance(args, (list, tuple)) or not all(isinstance(arg, str) for arg in args):
		raise ScheduleError(f'{action} takes words, not {args!r}')
	action = getattr(known[action], 'name', action) # a command's other name (a typo too) stands for its first
	try:
		label, kwargs = known[action].job(list(args))
	except ValueError as e:
		raise ScheduleError(f'{action} takes {e}')
	if not isinstance(schedule, when.Schedule):
		raise ScheduleError(f'no schedule: {schedule!r}')
	return Job(action, tuple(args), label, kwargs, schedule, chat, on, item,
		name or display_name(action, args, schedule, label))


def display_name(action, args, schedule, label):
	"""What .jobs calls a job a chat added: performance or price alone where the period follows how often it runs
	(catalog.period_args), 'message: ' and its first line, else its parser's label ('cal earnings', 'price 30')."""
	if action == 'message':
		return catalog.message_name(args)
	if action in catalog.PERIODIC and list(args) == catalog.period_args(action, schedule):
		return action
	return label


def stored_job(chat, entry):
	"""A job a chat added, as JOBS_FILE keeps it (Job.stored). Raises ScheduleError for one that cannot be: an action
	that is none, arguments its parser refuses, a schedule that is none (an edited file, or an older one)."""
	if not isinstance(entry, dict):
		raise ScheduleError(f'no job: {entry!r}')
	on = entry.get('on', True)
	if not isinstance(on, bool):
		raise ScheduleError(f'no switch: {on!r}')
	schedule = when.Schedule.from_json(entry.get('schedule'))
	return make_job(entry.get('action'), entry.get('args', []), schedule, chat, on)


def entry_key(chat, entry):
	"""The key of a job a chat added, as JOBS_FILE keeps it; None for one that cannot be."""
	try:
		return stored_job(chat, entry).key
	except ScheduleError:
		return None


def item_on(record, key):
	"""Whether a default job (by its catalog key) is on in a chat's record: unless it is switched off, or, where the
	default jobs start off (a direct message), where it is switched on."""
	if record.get('defaults') == 'off':
		listed = record.get('on', [])
		return isinstance(listed, list) and key in listed
	listed = record.get('off', [])
	return not (isinstance(listed, list) and key in listed)


def switch_item(record, key, on):
	"""Switch a default job on or off in a chat's record: whether it is on now."""
	starts_on = record.get('defaults') != 'off'
	name = 'off' if starts_on else 'on' # the list of those switched from how they start
	keep(record, name, [each for each in record.get(name, []) if each != key] + ([key] if on != starts_on else []))
	return on


def removed(record):
	"""The default jobs (by catalog key) that a chat's record says it removed."""
	listed = record.get('deleted', [])
	return [key for key in listed if isinstance(key, str)] if isinstance(listed, list) else []


def keep(record, name, listed):
	"""Set a list of a chat's record, or leave it out where it is empty."""
	if listed:
		record[name] = listed
	else:
		record.pop(name, None)


def switch_record(record, on):
	"""Switch every job of a chat's record on, or off: those it added, and the default ones, which then start so."""
	record.pop('off', None)
	record.pop('on', None)
	if on:
		record.pop('defaults', None)
	else:
		record['defaults'] = 'off'
	for entry in record.get('jobs', []):
		if isinstance(entry, dict):
			entry['on'] = on


def is_dm(key):
	"""Whether a chat (by key) is a direct message with the bot, as its key tells: a person's positive id on Telegram,
	an id starting D on Slack; None on Discord, whose key does not say."""
	network, _, chat = key.partition(':')
	if network == 'telegram':
		return not chat.startswith('-')
	if network == 'slack':
		return chat.startswith('D')
	return None


def know(keys, dm=None):
	"""Make chats known (by key), each new one with none added and the default jobs switched on, or off in a direct
	message (marked 'dm'): where dm is True (else as its key tells, is_dm). How many were new."""
	with state.edit(JOBS_FILE, {}) as chats:
		new = [key for key in dict.fromkeys(keys) if key not in chats]
		for key in new:
			chats[key] = {'defaults': 'off', 'dm': True} if (is_dm(key) if dm is None else dm) else {}
	return len(new)


def parse_add(text, zone):
	"""What .jobs add was given (its text after add) as (action, arguments, when.Schedule): a report, the arguments it
	takes and a schedule in English, in zone unless it names one (the arguments end wherever both read), the period of
	performance and price following how often it runs where none is given; or message, a schedule, then the text in
	double quotes (curly ones too), from the first quote to the last, so that quotes inside it stay, over several lines
	if need be, at 8:30am where it says no time. Raises ScheduleError."""
	name, rest = (text.strip().split(None, 1) + [''])[:2]
	name = name.lower()
	if name == 'message':
		start = min((rest.find(quote) for quote in QUOTES if quote in rest), default=-1)
		end = max(rest.rfind(quote) for quote in QUOTES)
		if start < 0 or end <= start:
			raise ScheduleError('a message is a schedule, then its text in double quotes: .jobs add message every 31'
				' mar "🥳 Happy EOFY"')
		return 'message', rest[start + 1:end].replace('\r', '').split('\n'), when.parse(rest[:start], zone, MESSAGE_AT)
	known, words = actions(), text.split()
	name = next((' '.join(words[:size]).lower() for size in (2, 1) if ' '.join(words[:size]).lower() in known), name)
	if name not in known or name in SYSTEM_ACTIONS:
		raise ScheduleError(f"no report {name!r}: send .jobs add for the reports")
	words, wrong, unread = words[len(name.split()):], None, None
	for cut in range(len(words) + 1):
		try:
			schedule = when.parse(' '.join(words[cut:]), zone)
		except ScheduleError as e:
			unread = unread or e
			continue
		args = words[:cut] or catalog.period_args(name, schedule)
		try:
			known[name].job(args)
		except ValueError as e:
			wrong = ScheduleError(f'{name} takes {e}')
			continue
		return name, args, schedule
	raise wrong or unread


class Scheduler:
	"""Runs the jobs: each chat's, from JOBS_FILE and the catalog, and the system jobs. clock, sleep, spawn and runner
	can be replaced, which the tests do. Its lock covers what the loop, a change from chat and the runs share: the
	jobs, their bases and next runs, the record of runs and what is running."""

	def __init__(self, catchup=None, clock=None, sleep=None, spawn=None, runner=None):
		"""catchup is how late, in minutes, a missed run may still start (the scheduler_catchup setting when None);
		clock, sleep, spawn and runner stand in for the real ones in tests."""
		self.catchup = datetime.timedelta(minutes=config.env.scheduler_catchup if catchup is None else catchup)
		self.clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
		self.sleep = sleep or time.sleep
		self.spawn = spawn or start_thread
		self.runner = runner or run_in_process # (label, module, kwargs, dest): runs the job
		self.jobs = []
		self.chats = set() # the chats JOBS_FILE knows
		self.base = {} # key -> the time after which the next run is due
		self.next_at = {} # key -> the next run after its base, once worked out (None: none, or off)
		self.last = {}
		self.busy = set() # the keys of the jobs running now, scheduled or by hand
		self.adopted = False # whether the old OLD_FILE's chats were looked at, at the first load
		self.lock = threading.Lock()

	def load(self):
		"""Read every job: the system jobs; for each chat JOBS_FILE knows, the catalog's (switched off where its record
		says so) and those it added. A stored job that cannot be (an action that is none, arguments its parser refuses:
		an edited or older file) is logged and left out, never run. A job kept from before keeps its timing; a new one
		counts from now, as one does that was off."""
		jobs = system_jobs()
		chats = self.stored_chats()
		items = catalog.items(config.prefs.country_code, sharesight.configured())
		for chat, record in chats.items():
			gone = set(removed(record))
			jobs += [make_job(item.action, item.args, item.schedule, chat, item_on(record, item.key), item.key,
				item.name) for item in items if item.key not in gone]
			added = record.get('jobs', [])
			keys = set()
			for entry in added if isinstance(added, list) else []:
				try:
					job = stored_job(chat, entry)
				except ScheduleError as e:
					log.warn(f'schedule: a job of {chat} left out: {e}')
					continue
				if job.key not in keys:
					keys.add(job.key)
					jobs.append(job)
		with self.lock: # no run is recorded between reading the record and swapping it in
			try:
				last, problem = state.load(STATE_FILE), None
			except (OSError, ValueError) as e: # unreadable or not JSON: start without one; the next run rewrites it
				last, problem = None, f'cannot read {STATE_FILE}, starting without a record of past runs: {e}'
			keys = {job.key for job in jobs}
			self.last = {key: value for key, value in last.items() if key in keys} if isinstance(last, dict) else {}
			if isinstance(last, dict) and self.last != last: # a job gone: one added again later has not run
				self.save_runs()
			now = self.clock()
			old = {job.key: self.base[job.key] for job in self.jobs if job.key in self.base}
			self.base = {job.key: old.get(job.key) or self.start_base(job, now) for job in jobs}
			self.next_at = {}
			self.jobs, self.chats = jobs, set(chats)
		if problem:
			delivery.report_error(ScheduleError(problem), context='schedule')
		dms = sum(1 for key, record in chats.items() if isinstance(record, dict) and record.get('dm') is True or
			is_dm(key))
		log.info(f"schedule: {len(jobs) - len(SYSTEM)} jobs of {len(chats) - dms} group"
			f" chat{'' if len(chats) - dms == 1 else 's'} and {dms} DM{'' if dms == 1 else 's'}, and {len(SYSTEM)}"
			" system jobs")

	def stored_chats(self):
		"""The chats JOBS_FILE knows, each with its record. At the first load, those the old OLD_FILE knew join them
		first, with the default jobs; the file is read for their keys alone, their cron jobs not carried over."""
		if not self.adopted:
			self.adopted = True
			if os.path.exists(state.path(OLD_FILE)):
				try:
					old = state.load(OLD_FILE, {})
					know(key for key in old if isinstance(key, str) and ':' in key)
				except (OSError, ValueError, TypeError) as e:
					log.warn(f'schedule: {OLD_FILE} left as it is, unreadable: {e}')
				log.info(f"schedule: {OLD_FILE} is read no more: each chat's jobs are in {JOBS_FILE}, its chats with"
					" the default jobs; it can be deleted")
		try:
			chats = state.load(JOBS_FILE, {})
		except (OSError, ValueError) as e:
			log.error(f'schedule: cannot read {JOBS_FILE}, so no chat has jobs: {e}')
			return {}
		if not isinstance(chats, dict):
			log.error(f'schedule: {JOBS_FILE} is no list of chats, so no chat has jobs')
			return {}
		return {chat: record for chat, record in chats.items() if isinstance(record, dict)}

	def start_base(self, job, now):
		"""Where to count from at start: a run missed in the catch-up window fires once; with no record, none is."""
		last = self.last.get(job.key)
		if not last or not job.on:
			return now
		try:
			return max(datetime.datetime.fromisoformat(last), now - self.catchup)
		except (TypeError, ValueError):
			return now

	def due(self, now):
		"""The jobs to run now, as (job, run time). Several missed runs of one job run it once. A job that is off never
		runs, and counts from now: switched on, it does not catch up. Each job's next run is worked out once, and again
		only after it runs, so that a tick costs little."""
		fired = []
		with self.lock:
			for job in self.jobs:
				key = job.key
				if not job.on:
					self.base[key], self.next_at[key] = now, None
					continue
				upcoming = self.next_at[key] if key in self.next_at else job.schedule.next_after(self.base[key])
				if upcoming is None or upcoming > now:
					self.next_at[key] = upcoming
					continue
				latest = upcoming
				while (upcoming := job.schedule.next_after(latest)) is not None and upcoming <= now:
					latest = upcoming
				self.base[key], self.next_at[key] = latest, upcoming
				self.last[key] = latest.isoformat()
				fired.append((job, latest))
			if fired:
				self.save_runs()
		return fired

	def save_runs(self):
		"""Write the record of runs (the lock held)."""
		try:
			state.save(STATE_FILE, self.last)
		except OSError as e:
			log.error('schedule: cannot save', STATE_FILE, e)

	def claim(self, key):
		"""Mark a job running, unless it already is (scheduled or by hand): whether it was claimed."""
		with self.lock:
			if key in self.busy:
				return False
			self.busy.add(key)
			return True

	def execute(self, job):
		"""Run a job now, in this thread, posting to its chat (a system job posts nothing, and its failure goes to the
		log); a failure is reported. A job already running is skipped. One still running after JOB_TIMEOUT is reported
		as late, once, and runs on: a thread cannot be stopped, but every request it makes has a timeout, so it ends;
		until then it stays marked running, and no second copy starts. Returns 'done', 'failed' or 'already running'."""
		dest = delivery.chat(job.chat, scheduled=True) if job.chat else None
		if not self.claim(job.key):
			log.warn(f'schedule: {job.label} is already running for {job.chat or "the system"}, skipping it')
			return 'already running'
		log.info(f'schedule: running {job.label}' + (f' for {job.chat}' if job.chat else ''))
		late = threading.Timer(JOB_TIMEOUT, delivery.report_error, args=(TimeoutError(f'still running after'
			f' {JOB_TIMEOUT / 60:g} minutes, and left to finish'), dest), kwargs={'context': job.label})
		late.daemon = True
		late.start()
		try:
			self.runner(job.label, job.module, job.kwargs, dest)
			return 'done'
		except (Exception, SystemExit) as e:
			delivery.report_error(e, dest, context=job.label)
			return 'failed'
		finally:
			late.cancel()
			with self.lock:
				self.busy.discard(job.key)

	def running(self, chat):
		"""The keys of the jobs running now for a chat (by its key), and for the system."""
		with self.lock:
			return {key for key in self.busy if key.partition('|')[0] in (chat, '')}

	def chat_jobs(self, chat):
		"""A chat's jobs, as .jobs numbers them from 1: the default ones, then those it added, but a one-off gone by."""
		now = self.clock()
		with self.lock:
			jobs = [job for job in self.jobs if job.chat == chat]
		return [job for job in jobs if not self.expired(job, now)]

	def system_jobs(self):
		"""The system jobs."""
		with self.lock:
			return [job for job in self.jobs if not job.chat]

	def expired(self, job, now):
		"""Whether a one-off job's time has gone by, longer ago than a missed run may still start: run or not."""
		return job.schedule.frequency == 'once' and job.schedule.next_after(now - self.catchup - MINUTE) is None

	def has_run(self, job):
		"""Whether a job has ever run, on its schedule or by hand."""
		with self.lock:
			return job.key in self.last

	def job(self, chat, number):
		"""A chat's job by its number in .jobs (a string, from a chat). Raises ScheduleError."""
		jobs = self.chat_jobs(chat)
		if not (number.isascii() and number.isdigit() and 1 <= int(number) <= len(jobs)):
			raise ScheduleError(f'no job {number}: send .jobs for the list')
		return jobs[int(number) - 1]

	def number(self, chat, key):
		"""A chat's job's number in .jobs, by its key."""
		return next(number for number, job in enumerate(self.chat_jobs(chat), 1) if job.key == key)

	def pick(self, chat, number, crc):
		"""The job a button stands for. Button data is untrusted input: the number must be plain digits within this
		chat's list, and the checksum must match that very job, else ScheduleError."""
		job = self.job(chat, number)
		if not hmac.compare_digest(checksum(job.key), crc):
			raise ScheduleError('the jobs have changed')
		return job

	def run(self, job):
		"""Run a job now, as its schedule would, and note the run: its outcome (see execute)."""
		with self.lock:
			self.last[job.key] = self.clock().isoformat()
			self.save_runs()
		return self.execute(job)

	def see(self, chat, dm=None):
		"""A chat seen, at a command of its: one finbot does not know yet starts with the default jobs, switched on,
		or off in a direct message (dm, from the network, else as the chat's key tells: is_dm)."""
		with self.lock:
			known = chat in self.chats
		if not known:
			know([chat], dm)
			self.load()

	def change(self, chat, edit):
		"""Change a chat's jobs as stored, and return what edit(record) returned: it changes the chat's record ({'off':
		[catalog keys], 'jobs': [...]}), or raises ScheduleError; then every job is read again, to count at once."""
		with state.edit(JOBS_FILE, {}) as chats:
			record = chats.setdefault(chat, {})
			if not isinstance(record.get('jobs', []), list):
				record['jobs'] = []
			result = edit(record)
		self.load()
		return result

	def add(self, chat, action, args, schedule):
		"""Add a job to a chat, switched on: an action of ACTIONS, its arguments, a when.Schedule. One the catalog has
		(catalog.matching) is that default job, switched on, and back in the list where the chat removed it. Returns its
		number in .jobs. Raises ScheduleError for a job that cannot be, a one-off gone by, one the chat has already, or
		one more than MAX_JOBS."""
		job = make_job(action, args, schedule, chat)
		if job.action in catalog.SHARESIGHT and not sharesight.configured():
			raise ScheduleError(f'{job.action} reports on Sharesight, which is not set up')
		if schedule.frequency == 'once' and schedule.next_after(self.clock()) is None:
			raise ScheduleError(f"{when.days_words(schedule.days)} has gone by: a one-off is for a time ahead")
		if item := catalog.matching(job.action, job.args, schedule, config.prefs.country_code):
			def restore(record):
				"""Bring the default job back where the chat removed it, and switch it on."""
				keep(record, 'deleted', [key for key in removed(record) if key != item.key])
				switch_item(record, item.key, True)
			self.change(chat, restore)
			return self.number(chat, f'{chat}|{item.key}')
		def append(record):
			"""Append the job, unless the chat has it already, within MAX_JOBS."""
			entries = record.setdefault('jobs', [])
			if any(entry_key(chat, entry) == job.key for entry in entries):
				raise ScheduleError('that job is here already: send .jobs for the list')
			if len(entries) >= MAX_JOBS:
				raise ScheduleError(f'{MAX_JOBS} jobs is the most a chat may add: delete one first')
			entries.append(job.stored())
		self.change(chat, append)
		return self.number(chat, job.key)

	def switch_all(self, chat, on):
		"""Switch every job of a chat on, or off: the default ones and those it added."""
		self.change(chat, lambda record: switch_record(record, on))

	def delete(self, job):
		"""Remove a chat's job (from job() or pick()): one it added, or a default one, which stays out of its list
		until the same job is added again."""
		def remove(record):
			"""Remove the job, as stored."""
			if not job.item:
				return record['jobs'].pop(self.index(record, job))
			for name in ('off', 'on'):
				keep(record, name, [key for key in record.get(name, []) if key != job.item])
			record['deleted'] = list(dict.fromkeys([*removed(record), job.item]))
		self.change(job.chat, remove)

	def delete_all(self, chat):
		"""Remove every job of a chat: those it added, and the default ones, which stay out of its list until the same
		job is added again."""
		def clear(record):
			"""Remove every job, as stored."""
			record['jobs'] = []
			record.pop('off', None)
			record.pop('on', None)
			record['deleted'] = list(dict.fromkeys([*removed(record), *(item.key for item in catalog.ITEMS)]))
		self.change(chat, clear)

	def switch(self, job, on):
		"""Switch a chat's job on, or off, whichever way it is now: whether it is on."""
		def turn(record):
			"""Set the job's switch, as stored."""
			if job.item:
				return switch_item(record, job.item, on)
			record['jobs'][self.index(record, job)]['on'] = on
			return on
		return self.change(job.chat, turn)

	def toggle(self, job):
		"""Switch a chat's job on or off: whether it is on now."""
		def flip(record):
			"""Flip the job's switch, as stored."""
			if job.item:
				return switch_item(record, job.item, not item_on(record, job.item))
			entry = record['jobs'][self.index(record, job)]
			entry['on'] = not entry.get('on', True)
			return entry['on']
		return self.change(job.chat, flip)

	@staticmethod
	def index(record, job):
		"""Where a job its chat added is among those stored. Raises ScheduleError when it is gone meanwhile."""
		for i, entry in enumerate(record['jobs']):
			if entry_key(job.chat, entry) == job.key:
				return i
		raise ScheduleError('that job is gone: send .jobs for the list')

	def prune(self, chat):
		"""Delete a chat's one-off jobs whose time has gone by (run, or missed while off or down): as its list is
		shown, never on a tick."""
		now = self.clock()
		with self.lock:
			gone = {job.key for job in self.jobs if job.chat == chat and not job.item and self.expired(job, now)}
		if gone:
			self.change(chat, lambda record: record.update(jobs=[entry for entry in record['jobs']
				if entry_key(chat, entry) not in gone]))

	def next_run(self, job):
		"""When a job runs next, or None when it is off (or a one-off gone by)."""
		if not job.on:
			return None
		with self.lock:
			base = self.base.get(job.key) or self.clock()
		return job.schedule.next_after(max(base, self.clock()))

	def upcoming(self, chat, count=20):
		"""A chat's next runs, in time order, at most count: (first, last, job, number), first and last the same but for
		a repeat, whose runs on a day of its zone are one entry, from its first run that day to its last. Each job's
		runs come from a heap, so that it takes about count + jobs schedule lookups."""
		now, heap, found = self.clock(), [], []
		for number, job in enumerate(self.chat_jobs(chat), 1):
			if job.on and (run := job.schedule.next_after(now)) is not None:
				heap.append((run, number, job))
		heapq.heapify(heap)
		while heap and len(found) < count:
			run, number, job = heapq.heappop(heap)
			last, schedule = run, job.schedule
			if schedule.every:
				day = run.astimezone(schedule.tz).date()
				if minutes := schedule.times(day):
					last = max(run, when.arrival(day, minutes[-1], schedule.tz))
			found.append((run, last, job, number))
			if (following := schedule.next_after(last)) is not None:
				heapq.heappush(heap, (following, number, job))
		return found

	def tick(self):
		"""Start what is due; returns the seconds until the next run, from 1 to 30."""
		now = self.clock()
		for job, _ in self.due(now):
			self.spawn(self.execute, job)
		with self.lock:
			waits = [(upcoming - now).total_seconds() for upcoming in self.next_at.values() if upcoming]
		return min(30, max(1, math.ceil(min(waits)))) if waits else 30

	def run_forever(self):
		"""Never returns, never raises: a failure is reported and the loop carries on."""
		while True:
			try:
				self.sleep(self.tick())
			except Exception as e:
				delivery.report_error(e, context='schedule')
				self.sleep(30)
