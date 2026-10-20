"""The scheduler (lib/jobs.py): each chat's jobs (the default ones and those it added) and the system jobs running on a
fake clock, across the clocks' changes; .jobs in a chat, its menu of buttons and the steps of Add; each job run in the
bot's process, past its deadline too."""
import contextlib, datetime, io, os, re, subprocess, sys, tempfile, threading, time, unittest
import zoneinfo
from pathlib import Path
from unittest import mock
from tests.common import *
from lib import catalog, jobs, when
from lib.reports import cleanup, sharesight_warm, yahoo_warm
from tests import test_sending

PREFETCH_HISTORY = yahoo.prefetch_history # FinbotCase replaces it; the warm job's test puts it back
SYSTEM = jobs.SYSTEM # SchedulerBase takes the system jobs out; their own tests put them back


def at(day, hour, minute, second=0):
	"""A UTC time in October 2026 (the 13th is a Tuesday)."""
	return datetime.datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


class Clock:
	def __init__(self, now):
		"""now: the time the clock shows until a test moves it."""
		self.now = now

	def __call__(self):
		"""The time the clock shows."""
		return self.now


class CleanupJob(FinbotCase):
	def test_removes_only_old_finbot_cache_files(self):
		"""cleanup deletes finbot's cache files older than the days given, not newer ones, other files or dirs."""
		folder = temp_dir(self)
		self.env(cache_dir=folder)

		old, new = time.time() - 40 * 86400, time.time() - 5 * 86400
		for name, stamp in (('finbot_old.json', old), ('finbot_new.json', new), ('other_old.json', old),
				('finbot_old.png', old)):
			path = os.path.join(folder, name)
			Path(path).write_text('x')
			os.utime(path, (stamp, stamp))
		os.mkdir(os.path.join(folder, 'finbot_dir'))
		os.utime(os.path.join(folder, 'finbot_dir'), (old, old))
		self.assertEqual(cleanup.run(days=30), 2)
		self.assertEqual(sorted(os.listdir(folder)), ['finbot_dir', 'finbot_new.json', 'other_old.json'])

	def test_a_temp_file_being_written_is_left_alone(self):
		"""A flush (0 days) spares a temp file from the last minute (a write in flight) and deletes a stale one."""
		folder = temp_dir(self)
		self.env(cache_dir=folder)

		for name, stamp in (('finbot_a.json.x1.tmp', time.time() - 5),
				('finbot_b.json.x2.tmp', time.time() - 40 * 86400)):
			Path(folder, name).write_text('x')
			os.utime(Path(folder, name), (stamp, stamp))
		self.assertEqual(cleanup.run(days=0), 1) # a flush: the stale one goes, the write in flight stays
		self.assertEqual(os.listdir(folder), ['finbot_a.json.x1.tmp'])

	def test_missing_cache_dir_is_fine(self):
		"""No cache dir: nothing to delete, no error."""
		self.env(cache_dir='/nonexistent/finbot-cache')

		self.assertEqual(cleanup.run(days=30), 0)


class YahooWarmJob(FinbotCase):
	def setUp(self):
		"""The real prefetch, Yahoo answering each history with the ticker's name, except T2's, which fails; Sharesight
		configured."""
		super().setUp()
		self.patch(yahoo, 'prefetch_history', PREFETCH_HISTORY)
		self.env(sharesight_client_id='id')
		def answer(ticker, full):
			"""A history that names its ticker; none for T2."""
			if ticker == 'T2':
				raise RuntimeError('Yahoo unreachable')
			return {'history of': ticker}
		self.patch(yahoo, '_chart_answer', answer)

	def test_every_followed_stocks_history_is_fetched_afresh(self):
		"""yahoo_warm fetches the price history of every stock followed even while its cache is fresh, so that none
		runs out between runs: it counts the ones fetched, and a failure is only logged."""
		cache.write('finbot_yahoo_history_T1.json', {'history of': 'an hour ago'})
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertEqual(yahoo_warm.run(), len(TICKERS) - 1)
		self.assertEqual(cache.read('finbot_yahoo_history_T1.json'), {'history of': 'T1'})
		self.assertIn(f'yahoo_warm: {len(TICKERS) - 1} of {len(TICKERS)} price histories fetched', log.getvalue())

	def test_without_sharesight_the_watchlists_are_fetched(self):
		"""While Sharesight cannot be asked for the holdings, every chat's watchlist's histories are fetched; without
		Sharesight configured, it is not asked."""
		asked = []
		def unreachable():
			"""Sharesight failing, as watchlist.all_followed meets it."""
			asked.append(1)
			raise RuntimeError('Sharesight auth: down')
		self.patch(watchlist, 'all_followed', unreachable)
		self.patch(watchlist, 'all_watched', lambda: ['W1'])
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertEqual(yahoo_warm.run(), 1)
		self.assertEqual(cache.read('finbot_yahoo_history_W1.json'), {'history of': 'W1'})
		self.assertIn('no holdings from Sharesight', log.getvalue())
		self.env(sharesight_client_id='')
		self.assertEqual((yahoo_warm.run(), len(asked)), (1, 1))

	def test_with_the_cache_off_nothing_is_fetched(self):
		"""With the cache setting off nothing would be kept, so nothing is fetched."""
		self.settings(cache=False)
		self.patch(yahoo, '_chart_answer', None)
		self.assertEqual(yahoo_warm.run(), 0)


class SharesightWarmJob(FinbotCase):
	def test_the_portfolios_are_refreshed_where_sharesight_is_configured(self):
		"""sharesight_warm refreshes the portfolio list and the holdings (sharesight.warm) and counts the portfolios;
		without Sharesight configured, or with the cache setting off (nothing would be kept), it fetches nothing."""
		self.patch(sharesight, 'warm', lambda: ['Rob', 'RobSMSF'])
		self.env(sharesight_client_id='id')
		self.assertEqual(sharesight_warm.run(), 2)
		self.settings(cache=False)
		self.assertEqual(sharesight_warm.run(), 0)
		self.settings(cache=True)
		self.env(sharesight_client_id='')
		self.assertEqual(sharesight_warm.run(), 0)

	def test_a_failure_is_logged_not_reported(self):
		"""A refresh that fails is only logged, not reported in the chat: the next run tries again."""
		def down():
			"""Sharesight unreachable, as warm meets it."""
			raise RuntimeError('Sharesight portfolios: unreachable')
		self.patch(sharesight, 'warm', down)
		self.env(sharesight_client_id='id')
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertEqual(sharesight_warm.run(), 0)
		self.assertIn('sharesight_warm: refresh failed: Sharesight portfolios: unreachable', log.getvalue())
		self.assertEqual(self.errors, [])


CHAT, OTHER = 'telegram:55', 'slack:C1' # two chats, by their keys
ITEMS = catalog.ITEMS # the default jobs: SchedulerBase takes them out, DefaultJobs puts them back
FEW = (catalog.Item('rating', 'rating', 'rating', (), catalog.at(catalog.TUE_SAT)), # two default jobs, for the menu
	catalog.Item('price-close-us', 'movers close US', 'movers', ('close',), catalog.at('weekdays', '16:30',
		catalog.NEW_YORK)))


def newest(lines):
	"""The job just added, pointed to (👉) and in bold in the list that shows it: its line, without the markup."""
	return next(line for line in lines if re.match(r'👉 <b>\d+\. ', line))[5:-4]


def entry(text, on=True, zone='UTC'):
	"""A job as JOBS_FILE stores one a chat added, from what .jobs add takes ('trades every 20 mins weekdays'), in UTC
	unless it names a zone (or another is given)."""
	action, args, schedule = jobs.parse_add(text, zone)
	return jobs.make_job(action, args, schedule, 'telegram:1', on).stored()


class SchedulerBase(FinbotCase):
	def setUp(self):
		"""Chat telegram:55 with one job it added, trades every 20 minutes on weekdays in UTC, and no default jobs (they
		have tests of their own); a fake clock; no system jobs (nor those); the reports noted with the chat each posts
		to, not run."""
		super().setUp()
		self.patch(jobs, 'SYSTEM', ())
		self.patch(catalog, 'ITEMS', ())
		self.store(CHAT, 'trades every 20 mins weekdays')
		self.clock = Clock(at(13, 21, 3))
		self.ran, self.dests = [], []
		for name in ('earnings', 'message', 'performance', 'movers', 'rating', 'shorts', 'trades'):
			self.patch(jobs.ACTIONS[name], 'run', self.recorder(name))

	def recorder(self, name):
		"""A report's run() that notes the run, and the chat it would post to (its key; None for a system job)."""
		def run(dest=None, **kwargs):
			"""Note the run and where it posts."""
			self.ran.append((name, kwargs))
			self.dests.append(dest.key if dest else None)
		return run

	def store(self, chat, *texts, on=True, off=()):
		"""Set a chat's jobs as .jobs would have stored them: those it added (each as .jobs add takes it, in UTC), and
		the default ones it switched off (their keys)."""
		with state.edit(jobs.JOBS_FILE, {}) as chats:
			chats[chat] = {'jobs': [entry(text, on) for text in texts], **({'off': list(off)} if off else {})}

	def scheduler(self, catchup=5):
		"""A loaded scheduler on the fake clock that runs jobs in this process, at once."""
		s = jobs.Scheduler(catchup=catchup, clock=self.clock, sleep=lambda seconds: None, spawn=lambda f, *a: f(*a))
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		return s


class LoadsTakeTurns(SchedulerBase):
	"""Two changes at once: the list read last is the one left live."""

	def test_a_change_during_a_load_is_live_after_both(self):
		"""A job switched off while another load is reading the jobs (an older list) is off once both are done: the
		second load waits for the first, so the first cannot swap its older list in after it."""
		self.patch(catalog, 'ITEMS', FEW)
		s = self.scheduler()
		read = s.stored_chats
		reading, release = threading.Event(), threading.Event()
		def slow():
			"""The first read of the jobs file waits until the other change is stored."""
			chats = read()
			if not reading.is_set():
				reading.set()
				release.wait(5)
			return chats
		self.patch(s, 'stored_chats', slow)
		jobs.know([CHAT])
		first = threading.Thread(target=s.load)
		first.start()
		reading.wait(5)
		job = next(job for job in s.chat_jobs(CHAT) if job.item == 'rating')
		second = threading.Thread(target=s.toggle, args=(job, False))
		second.start()
		for _ in range(200): # until the switch is stored
			if 'rating' in (state.load(jobs.JOBS_FILE, {}).get(CHAT) or {}).get('off', []):
				break
			time.sleep(0.01)
		release.set()
		first.join(5)
		second.join(5)
		self.assertFalse(next(job for job in s.chat_jobs(CHAT) if job.item == 'rating').on)


class WarmNow(FinbotCase):
	def test_the_warm_jobs_run_through_the_scheduler(self):
		"""warm_now runs both warm jobs through the scheduler, which does not start one that is running already."""
		warmed = []
		self.patch(sharesight_warm, 'run', lambda dest: warmed.append('sharesight'))
		self.patch(yahoo_warm, 'run', lambda dest: warmed.append('yahoo'))
		s = jobs.Scheduler(clock=Clock(at(13, 21, 3)))
		with contextlib.redirect_stderr(io.StringIO()) as log:
			s.load()
			jobs.warm_now(s)
			s.busy.add(next(job.key for job in s.system_jobs() if job.action == 'yahoo_warm')) # on its schedule
			jobs.warm_now(s)
		self.assertEqual(warmed, ['sharesight', 'yahoo', 'sharesight'])
		self.assertIn('cache: filling it again: sharesight_warm, yahoo_warm', log.getvalue())


class SystemJobs(FinbotCase):
	def test_the_system_jobs_are_fixed_and_no_chats(self):
		"""The system jobs run on a schedule of their own, in UTC, the same for every install: each warm job within its
		cache's lifetime (Sharesight's every 30 minutes, cached 40; Yahoo's every 4 hours, cached 6), and cleanup
		weekly. A chat can neither add one nor see it among its own jobs; .jobs system lists them."""
		s = jobs.Scheduler()
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		self.assertEqual({job.label: job.schedule.describe('Australia/Melbourne') for job in s.system_jobs()},
			{'sharesight_warm': 'every 30 mins from :14 UTC', 'yahoo_warm': 'every 4 hours at :07 UTC',
				'cleanup 30': 'weekly, Saturdays at 18:51 UTC'})
		self.assertLess(30 * 60, config.settings.performance_cache_seconds)
		self.assertLess(4 * 3600, config.settings.cache_seconds)
		self.assertCountEqual(s.chat_jobs(''), s.system_jobs())
		for name in jobs.SYSTEM_ACTIONS:
			with self.subTest(name=name):
				with self.assertRaisesRegex(jobs.ScheduleError, f"no report '{name}'"):
					jobs.parse_add(f'{name} daily', 'UTC')
				with self.assertRaisesRegex(jobs.ScheduleError, f"no report '{name}'"):
					s.add(CHAT, name, [], when.parse('daily', 'UTC'))
		self.patch(jobs, 'current', s)
		self.assertEqual(about.prepare_system(TELEGRAM), ['<b>System jobs:</b>',
			'sharesight_warm · every 30 mins from :14 UTC', 'yahoo_warm · every 4 hours at :07 UTC',
			'cleanup 30 · weekly, Saturdays at 18:51 UTC'])


class SchedulerTests(SchedulerBase):
	def test_fires_on_the_minute_on_weekdays_only(self):
		"""A job fires on its minute, once, on weekdays only; runs missed over days coalesce into one."""
		s = self.scheduler()
		self.clock.now = at(13, 21, 19, 59)
		self.assertEqual(s.due(self.clock.now), [])
		self.clock.now = at(13, 21, 20)
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 20)])
		self.assertEqual(s.due(self.clock.now), []) # not twice
		self.clock.now = at(13, 21, 40, 30)
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)])
		self.clock.now = at(16, 23, 50) # the rest of the week, seen at once: the many missed runs coalesce into one
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(16, 23, 40)])
		self.clock.now = at(17, 21, 20) # a Saturday
		self.assertEqual(s.due(self.clock.now), [])

	def test_tick_runs_the_job_for_its_chat_and_returns_the_wait(self):
		"""tick() runs what is due, posting to the job's chat as a scheduled run, and returns how long to sleep: up to
		30 seconds, less when the next run is nearer."""
		dests = []
		self.patch(jobs.ACTIONS['trades'], 'run', lambda dest=None, **k: dests.append(dest))
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		self.assertEqual(s.tick(), 30) # the next run is 20 minutes away: wake at most every 30 seconds
		self.assertEqual([(dest.key, dest.scheduled) for dest in dests], [(CHAT, True)])
		self.clock.now = at(13, 21, 39, 50)
		self.assertEqual(s.tick(), 10)

	def test_each_chats_jobs_post_to_that_chat(self):
		"""Two chats' jobs at the same time each run, each posting to its own chat."""
		self.store(OTHER, 'trades every 20 mins weekdays', 'shorts daily at 22:00')
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		s.tick()
		self.assertEqual(set(zip(self.dests, [name for name, _ in self.ran])), {(CHAT, 'trades'), (OTHER, 'trades')})
		self.ran.clear()
		self.dests.clear()
		self.clock.now = at(13, 22, 0)
		s.tick()
		self.assertEqual(set(zip(self.dests, [name for name, _ in self.ran])), {(CHAT, 'trades'), (OTHER, 'trades'),
			(OTHER, 'shorts')})

	def test_a_job_that_is_off_never_fires_nor_catches_up_once_on(self):
		"""A job that is off does not fire; switched on, it fires at its next time, not for the runs it missed."""
		self.store(CHAT, 'trades every 20 mins weekdays', on=False)
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		self.assertEqual(s.due(self.clock.now), [])
		self.clock.now = at(13, 21, 30)
		s.toggle(s.chat_jobs(CHAT)[0])
		self.assertTrue(s.chat_jobs(CHAT)[0].on)
		self.assertEqual(s.due(self.clock.now), []) # 21:20 is not caught up
		self.clock.now = at(13, 21, 40)
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)])

	def test_a_run_missed_within_the_catch_up_window_fires_once(self):
		"""After a restart, a run missed within the catch-up window fires once; an older one is skipped."""
		first = self.scheduler()
		state.save(jobs.STATE_FILE, {first.chat_jobs(CHAT)[0].key: at(13, 21, 0).isoformat()})
		self.clock.now = at(13, 21, 43)
		s = self.scheduler()
		# 21:20 is older than 5 minutes: skipped
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)])

	def test_a_corrupt_state_file_is_reported_and_the_schedule_starts_afresh(self):
		"""A state file cut off mid-write is reported once, and the schedule runs as usual and writes it afresh."""
		Path(config.env.data_dir, jobs.STATE_FILE).write_text('{"telegram:55|trades|[]|{}": "2026-1')
		s = self.scheduler()
		self.assertEqual((s.last, len(self.errors)), ({}, 1))
		self.assertIn('cannot read finbot_jobs.json', self.errors[0])
		self.clock.now = at(13, 21, 20)
		self.assertEqual(len(s.due(self.clock.now)), 1) # runs as usual, and the record is written afresh
		self.assertEqual(state.load(jobs.STATE_FILE), {s.chat_jobs(CHAT)[0].key: at(13, 21, 20).isoformat()})

	def test_no_record_means_nothing_is_missed(self):
		"""With no record of past runs, nothing counts as missed."""
		self.clock.now = at(13, 21, 43)
		s = self.scheduler()
		self.assertEqual(s.due(self.clock.now), [])

	def test_a_restart_just_after_a_run_does_not_repeat_it(self):
		"""A restart just after a run does not run it again."""
		s = self.scheduler()
		self.clock.now = at(13, 21, 20, 5)
		self.assertEqual(len(s.due(self.clock.now)), 1)
		self.clock.now = at(13, 21, 21)
		again = self.scheduler()
		self.assertEqual(again.due(self.clock.now), [])

	def test_a_failing_job_is_reported_to_its_chat_and_the_others_still_run(self):
		"""A job that fails is reported to the chat whose job it is; another due at the same time still runs."""
		self.store(CHAT, 'trades every 20 mins', 'shorts every 20 mins')
		def boom(dest=None, **k):
			"""Fail."""
			raise RuntimeError('boom')
		self.patch(jobs.ACTIONS['trades'], 'run', boom)
		reported = []
		self.patch(delivery, 'report_error', lambda e, dest=None, context=None: reported.append((context, dest.key)))
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		s.tick()
		self.assertEqual(reported, [('trades', CHAT)])
		self.assertEqual(self.ran, [('shorts', {})])
		self.assertEqual(s.execute(next(job for job in s.chat_jobs(CHAT) if job.action == 'trades')), 'failed')

	def test_system_exit_inside_a_job_is_reported_not_raised(self):
		"""A report calling sys.exit is reported like any failure and does not stop the scheduler."""
		def quit_(dest=None, **k):
			"""Exit, as a report may."""
			raise SystemExit(1)
		self.patch(jobs.ACTIONS['trades'], 'run', quit_)
		s = self.scheduler()
		s.run(s.chat_jobs(CHAT)[0])
		self.assertEqual(len(self.errors), 1)

	def test_a_job_past_its_deadline_is_reported_once_and_left_to_finish(self):
		"""A job still running at its deadline is reported as late, once, and runs on to its end (a thread cannot be
		stopped); meanwhile it stays marked running, so a second run of it is turned away."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.1)
		s = self.scheduler()
		second = []
		def slow(dest=None, **k):
			"""Take three deadlines, and try a second run of this job meanwhile."""
			time.sleep(0.3)
			second.append(s.execute(s.chat_jobs(CHAT)[0]))
			self.ran.append(('trades', k))
		self.patch(jobs.ACTIONS['trades'], 'run', slow)
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(s.run(s.chat_jobs(CHAT)[0]), 'done')
		self.assertEqual(self.errors, ['⚠️ trades: TimeoutError: still running after 0.00166667 minutes, and left to'
			' finish'])
		self.assertEqual(second, ['already running'])
		self.assertEqual(self.ran, [('trades', {})])
		self.assertEqual(s.busy, set())

	def test_the_record_of_runs_is_saved_outside_the_schedulers_lock(self):
		"""Saving the record of runs (flushed to disk, which takes a while) holds no lock a chat's command waits on: the
		scheduler's lock is free while it writes."""
		s = self.scheduler()
		held = []
		self.patch(state, 'save', lambda name, data: held.append((name, s.lock.locked())))
		s.run(s.chat_jobs(CHAT)[0])
		self.assertEqual(held, [(jobs.STATE_FILE, False)])

	def test_an_older_finbots_names_are_rewritten_in_the_file_once(self):
		"""A job JOBS_FILE keeps as an older finbot named it (cal earnings: earnings now) is rewritten there as the
		scheduler loads, once: the next load finds nothing to change, and writes nothing."""
		with state.edit(jobs.JOBS_FILE, {}) as chats:
			chats[CHAT]['jobs'][0].update(action='cal', args=['earnings'])
		s = self.scheduler()
		self.assertEqual([(job.action, job.args) for job in s.chat_jobs(CHAT)], [('earnings', ())])
		self.assertEqual({key: state.load(jobs.JOBS_FILE)[CHAT]['jobs'][0][key] for key in ('action', 'args')},
			{'action': 'earnings', 'args': []})
		saved = []
		self.patch(state, 'save', lambda name, data: saved.append(name))
		s.load()
		self.assertNotIn(jobs.JOBS_FILE, saved)

	def test_a_stored_job_that_cannot_be_is_logged_left_out_and_never_run(self):
		"""A job is only ever an action of the fixed table with arguments its parser takes: a stored one that is
		anything else (a command, a module's path, a system job, arguments its action refuses, a schedule that is
		none, junk) is logged and left out, never run, and the chat's other jobs load."""
		once = {'at': '01:00', 'zone': 'UTC'}
		bad = [{'action': 'os.system', 'args': ['rm -rf /'], 'schedule': once},
			{'action': 'price; rm -rf /', 'args': [], 'schedule': once},
			{'action': 'lib.reports.price', 'args': ['close'], 'schedule': once},
			{'action': '__import__', 'args': ['os'], 'schedule': once},
			{'action': 'eval', 'args': ['1'], 'schedule': once}, {'action': 'yahoo_warm', 'args': [], 'schedule': once},
			{'action': 'price', 'args': ['bogus'], 'schedule': once},
			{'action': 'trades', 'args': [], 'schedule': {'at': '25:00'}},
			{'action': 'trades', 'args': [7], 'schedule': once}, {'action': ['trades'], 'args': [], 'schedule': once},
			'trades', {'action': 'trades', 'schedule': once, 'on': 'yes'},
			{'action': 'trades', 'args': [], 'schedule': {'at': '01:00', 'zone': '../../etc/passwd'}}]
		with state.edit(jobs.JOBS_FILE, {}) as chats:
			chats[CHAT]['jobs'] += bad
		with contextlib.redirect_stderr(io.StringIO()) as log:
			s = jobs.Scheduler(clock=self.clock, spawn=lambda f, *a: f(*a))
			s.load()
		self.assertEqual([job.name for job in s.chat_jobs(CHAT)], ['trades'])
		self.assertEqual(log.getvalue().count('schedule: a job of telegram:55 left out'), len(bad))
		self.assertEqual(self.errors, [])
		for day in range(14, 21):
			self.clock.now = at(day, 1, 30)
			s.tick()
		self.assertEqual({name for name, _ in self.ran}, {'trades'})

	def test_a_job_added_as_price_before_runs_as_movers(self):
		"""The movers list was price: a job a chat added under that name loads as movers, its arguments and schedule
		kept, and runs as movers; one added as price now is .compare's, stored as compare."""
		with state.edit(jobs.JOBS_FILE, {}) as chats:
			chats[CHAT]['jobs'] = [{'action': 'price', 'args': ['close'], 'schedule': {'at': '01:00', 'zone': 'UTC'}}]
		s = self.scheduler()
		self.assertEqual([(job.action, job.args, job.name) for job in s.chat_jobs(CHAT)],
			[('movers', ('close',), 'movers close')])
		self.clock.now = at(14, 1, 30)
		s.tick()
		self.assertEqual(self.ran, [('movers', {'mode': 'close'})])
		self.assertEqual(entry('price AAPL weekly')['action'], 'compare')

	def test_run_forever_survives_an_error(self):
		"""run_forever reports a failed tick and carries on."""
		s = self.scheduler()
		calls = []
		def sleep(seconds):
			"""Note the sleep, and stop the loop on the third."""
			calls.append(seconds)
			if len(calls) == 3:
				raise KeyboardInterrupt
		s.sleep = sleep
		with mock.patch.object(s, 'tick', side_effect=[RuntimeError('tick failed'), 30, 30]):
			with self.assertRaises(KeyboardInterrupt):
				s.run_forever()
		self.assertEqual(calls, [30, 30, 30])
		self.assertTrue(any('tick failed' in e for e in self.errors))


class DaylightSaving(SchedulerBase):
	"""A job runs by its zone's clock through its changes: Melbourne's clocks go forward at 02:00 on 4 October 2026,
	New York's at 02:00 on 8 March 2026 and back at 02:00 on 1 November 2026."""

	def runs(self, text, zone, start, end):
		"""When the scheduler runs CHAT's one job (as .jobs add takes it, in zone) between start and end, its clock
		moving ten minutes at a time: each run as UTC's clock and the zone's read it ('Fri 21:30 16:30')."""
		with state.edit(jobs.JOBS_FILE, {}) as chats:
			chats[CHAT] = {'jobs': [entry(text, zone=zone)]}
		self.clock.now = start
		s, fired = self.scheduler(), []
		while self.clock.now < end:
			fired += [f"{t.astimezone(UTC):%a %H:%M} {t.astimezone(zoneinfo.ZoneInfo(zone)):%H:%M}"
				for _, t in s.due(self.clock.now)]
			self.clock.now += datetime.timedelta(minutes=10)
		return fired

	def test_a_daily_job_runs_once_a_day_at_its_time_across_the_change(self):
		"""A Melbourne job at 9am runs once a day at 9am Melbourne, before and after its clocks go forward."""
		mel = zoneinfo.ZoneInfo('Australia/Melbourne')
		self.assertEqual(self.runs('trades daily at 9am', 'Australia/Melbourne', datetime.datetime(2026, 10, 2, 12,
			tzinfo=mel), datetime.datetime(2026, 10, 5, 12, tzinfo=mel)), ['Fri 23:00 09:00', 'Sat 22:00 09:00',
			'Sun 22:00 09:00'])

	def test_a_new_york_job_keeps_new_yorks_clock_in_march_and_november(self):
		"""A job stored in New York's zone runs at 4:30pm there on both sides of each change: 21:30 UTC, then 20:30."""
		ny = zoneinfo.ZoneInfo('America/New_York')
		self.assertEqual(self.runs('movers close weekdays at 4:30pm New York', 'America/New_York',
			datetime.datetime(2026, 3, 5, 12, tzinfo=ny), datetime.datetime(2026, 3, 11, tzinfo=ny)),
			['Thu 21:30 16:30', 'Fri 21:30 16:30', 'Mon 20:30 16:30', 'Tue 20:30 16:30'])
		self.assertEqual(self.runs('movers close weekdays at 4:30pm New York', 'America/New_York',
			datetime.datetime(2026, 10, 29, 12, tzinfo=ny), datetime.datetime(2026, 11, 4, tzinfo=ny)),
			['Thu 20:30 16:30', 'Fri 20:30 16:30', 'Mon 21:30 16:30', 'Tue 21:30 16:30'])


class ChatBase(SchedulerBase):
	"""A chat's .jobs: the scheduler running, two default jobs (FEW), Telegram's toasts and edits noted, and the
	replies with their buttons."""

	def setUp(self):
		"""Chat telegram:55 with the trades job it added, the scheduler running, and what is posted noted."""
		super().setUp()
		self.patch(catalog, 'ITEMS', FEW)
		self.s = self.scheduler()
		self.patch(jobs, 'current', self.s)
		self.toasts, self.edits = [], []
		self.patch(telegram_common, 'answerCallbackQuery', lambda cid, text=None, alert=False: self.toasts.append(text))
		self.patch(telegram_common.TelegramBot, 'edit_text', lambda dest, mid, text, buttons=None:
			self.edits.append((dest.where, mid, text, buttons)))
		self.replies = []
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None:
			self.replies.append((dest.key, list(lines), buttons)) or [])

	def say(self, text, chat='55'):
		"""Send text in a Telegram chat: the lines of the reply."""
		self.replies.clear()
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('telegram', chat, '@u', text, BOT))
		self.assertEqual(self.errors, [], text)
		return self.replies[-1][1] if self.replies else None

	def press(self, data):
		"""Press a button under the bot's message 9 in chat 55: (the edited text's lines, the buttons' labels by row,
		and their data by label)."""
		self.edits.clear()
		with contextlib.redirect_stderr(io.StringIO()):
			self.press_button(data)
		self.assertEqual(self.errors, [], data)
		if not self.edits:
			return None, None, None
		_, _, text, markup = self.edits[-1]
		return text.split('\n'), [[button.label for button in row] for row in markup], {button.label: button.data
			for row in markup for button in row}

	def crc(self, chat=CHAT):
		"""The checksum of a chat's list, as its menu's buttons carry it."""
		return jobs.list_checksum(self.s.chat_jobs(chat))


class JobsInChat(ChatBase):
	"""What a chat types: .jobs lists its jobs; run, toggle, add and del; next and system."""

	def test_add_list_and_remove(self):
		"""A job is added; the list shows each job with its number, its switch, * till it runs, its name and its
		schedule in words, then how Add is typed, in italics, over the buttons; a job is removed, a default one too,
		which stays out of the list."""
		self.assertEqual(newest(self.say('.jobs add shorts daily at 10pm')), '3. * shorts · daily at 10:00pm')
		self.assertEqual(self.say('.jobs'), ['<b>Jobs here</b>', '', '<b>Rating</b>',
			'1. * rating · Tue–Sat at 8:30am', '', '<b>Movers</b>',
			'2. * movers close US · weekdays at 4:30pm New York (7:30am local, Tue–Sat)', '', '<b>Shorts</b>',
			'3. * shorts · daily at 10:00pm', '', '<b>Trades</b>', '4. * trades · every 20 mins, weekdays UTC', '',
			'* not run yet', '',
			'<i>/jobs add REPORT SCHEDULE</i>', '<i>/jobs add reminder SCHEDULE "TEXT"</i>'])
		self.assertEqual([[button.label for button in row] for row in self.replies[-1][2]],
			[['+', 'Edit', 'Run', 'Upcoming']])
		self.assertEqual(self.say('.jobs del 4'), ['Deleted 4. trades · every 20 mins, weekdays UTC'])
		shorts = entry('shorts daily at 10pm', zone='Australia/Melbourne')
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [shorts]})
		self.assertEqual(self.say('.jobs delete 1'), ['Deleted 1. rating · Tue–Sat at 8:30am'])
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [shorts], 'deleted': ['rating']})
		self.assertEqual([job.name for job in self.s.chat_jobs(CHAT)], ['movers close US', 'shorts'])
		self.assertEqual(self.say('.job remove 2'), ['Deleted 2. shorts · daily at 10:00pm'])
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [], 'deleted': ['rating']})

	def test_the_list_has_a_heading_per_report_and_reminders_last(self):
		"""The jobs of a report are listed together under a heading of its name, in the default jobs' order, and the
		reminders last under theirs, whenever they were added; the numbers follow."""
		self.say('.jobs add reminder daily at 9am "first"')
		self.say('.jobs add shorts daily at 10pm')
		lines = self.say('.jobs')
		self.assertEqual([line for line in lines if line.startswith('<b>')], ['<b>Jobs here</b>', '<b>Rating</b>',
			'<b>Movers</b>', '<b>Shorts</b>', '<b>Trades</b>', '<b>Reminders</b>'])
		at = lines.index('<b>Reminders</b>')
		self.assertEqual(lines[at - 2:at + 2], ['4. * trades · every 20 mins, weekdays UTC', '', '<b>Reminders</b>',
			'5. * first · daily at 9:00am'])

	def test_a_command_of_help_as_a_job(self):
		""".jobs add takes a command of .help, with its words; the job is listed by its name and words, and runs as the
		command does, posting what it posts; a command that changes something is no job."""
		self.assertEqual(newest(self.say('.jobs add peg top weekly')), '3. * peg top · weekly, Saturdays at 9:00am')
		self.sent.clear()
		self.assertIsNone(self.say('.jobs run 3')) # what it posts shows it ran
		self.assertTrue(self.sent or self.replies[:-1]) # what .peg top posts
		self.assertIn("no report 'plan'", self.say('.jobs add plan buy low weekly')[0])

	def test_without_sharesight_no_job_reports_on_it(self):
		"""Without Sharesight's keys, a chat cannot add a job that reports on it, and Add does not offer one."""
		self.env(sharesight_client_id='')
		self.assertEqual(self.say('.jobs add trades every 20 mins weekdays from 10am to 4pm'), ['trades reports on'
			' Sharesight, which is not set up'])
		labels = [button.label for row in about.add_screen(TELEGRAM, CHAT, [])[1] for button in row]
		self.assertNotIn('trades', labels)
		self.assertNotIn('performance', labels)
		self.assertIn('movers', labels)

	def test_add_reads_english_and_the_period_follows_how_often(self):
		"""A job is a report, what it takes, and a schedule in English, by the timezone setting's clock unless it
		names a zone; performance and movers cover the days between runs where they name no period."""
		for text, line, args in (('movers weekly', 'movers · weekly, Saturdays at 9:00am', ['7']),
				('performance first day of each month at 9am', 'performance · monthly, the 1st at 9:00am', ['30']),
				('movers daily at 5pm', 'movers · daily at 5:00pm', ['interday']),
				('movers 30 weekly', 'movers 30 · weekly, Saturdays at 9:00am', ['30']),
				('movers midsession weekdays at 12:45pm New York',
					'movers midsession · weekdays at 12:45pm New York (3:45am local, Tue–Sat)', ['midsession']),
				('earnings every sunday at 8:30am', 'earnings · weekly, Sundays at 8:30am', []),
				('trades every 20 mins weekdays from 10am to 4pm', 'trades · every 20 mins, weekdays 10am–4pm', [])):
			with self.subTest(text=text):
				added = self.say(f'.jobs add {text}')
				self.assertEqual(newest(added).split('. ', 1)[1], f'* {line}')
				self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT]['jobs'][-1]['args'], args)
				self.say('.jobs del 4')

	def test_a_message_takes_its_text_in_quotes(self):
		"""A message is a schedule, then its text in double quotes (curly ones too), from the first to the last, so
		that quotes inside it stay; over several lines if need be; at 8:30am where it says no time. A job runs the
		message action with its lines."""
		added = self.say('.jobs add message every 31 mar "🥳 Happy "EOFY" everyone"')
		self.assertEqual(newest(added), '4. * 🥳 Happy "EOFY" everyone · annual, 31 Mar at 8:30am')
		self.say('.jobs add message on 28 oct 2026 at 9am “line one\nline [two](https://x.example)”')
		stored = state.load(jobs.JOBS_FILE)[CHAT]['jobs']
		self.assertEqual([job['args'] for job in stored[1:]], [['🥳 Happy "EOFY" everyone'],
			['line one', 'line [two](https://x.example)']])
		self.assertIsNone(self.say('.jobs run 5'))
		self.assertEqual(self.ran, [('message', {'lines': ['line one', 'line [two](https://x.example)']})])
		self.assertIn('a reminder is a schedule, then its text in double quotes',
			self.say('.jobs add message daily "no end')[0])

	def test_add_alone_lists_the_reports_a_job_can_run(self):
		""".jobs add alone lists the reports and the commands with what each takes, message among them, no system job,
		and examples."""
		lines = self.say('.jobs add')
		self.assertEqual(lines[0], '<b>What a job can run:</b>')
		for line in ('reminder "TEXT"', 'performance [DAYS]', 'podcasts FEED_URL',
				'movers midsession|interday|premarket|close|DAYS', 'trades', '.jobs add movers weekly', 'beta',
				'ratio [SYMBOL] [forward|current|peg] [top|bottom|negative|reverse]',
				'price [SYMBOL ... up to 8] [period]', '.jobs add ratio peg bottom weekly'):
			self.assertIn(line, lines)
		self.assertFalse(any(name in line for line in lines for name in jobs.SYSTEM_ACTIONS))

	def test_a_job_that_cannot_be_is_refused_saying_why(self):
		"""A report that is none (or a script's file name, a system job, a command), arguments it does not take, words
		that are no schedule, a zone that is none, a one-off gone by, a job here already: refused, saying why."""
		for text, why in (('nothere daily', "no report 'nothere'"), ('trades.py daily', "no report 'trades.py'"),
				('yahoo_warm daily', "no report 'yahoo_warm'"), ('os.system daily', "no report 'os.system'"),
				('movers bogus weekly', 'movers takes midsession|interday|premarket|close|DAYS'),
				('trades 7 daily', 'trades takes no arguments'), ('trades fortnightly', "can't read 'fortnightly'"),
				('shorts daily at 9am Atlantis', "can't read 'atlantis'"), ('trades', 'no days or times'),
				('message on 1 jan 2020 "late"', 'once, 1 Jan 2020 has gone by'),
				('trades every 20 mins weekdays UTC', 'that job is here already')):
			with self.subTest(text=text):
				self.assertIn(why, self.say(f'.jobs add {text}')[0])
		self.assertEqual(len(state.load(jobs.JOBS_FILE)[CHAT]['jobs']), 1)

	def test_what_is_said_back_is_escaped(self):
		"""A job's name and what was typed are text, not markup, wherever they are said back: a message job's run,
		its deletion, and a report or number that is none."""
		self.say('.jobs add message daily at 9am "R&D <b>soon</b>"')
		name = 'R&amp;D &lt;b&gt;soon&lt;/b&gt;'
		self.s.claim(self.s.chat_jobs(CHAT)[3].key) # as if it were running: its run says so
		self.assertEqual(self.say('.jobs run 4'), [f'4. {name}: already running'])
		self.assertEqual(self.say('.jobs del 4'), [f'Deleted 4. {name} · daily at 9:00am'])
		self.assertEqual(self.say('.jobs add <x> daily'), ["no report '&lt;x&gt;': send .jobs add for the reports"])
		self.assertEqual(self.say('.jobs run <b>'), ['no job &lt;b&gt;: send .jobs for the list'])

	def test_a_chat_adds_thirty_jobs_at_most(self):
		"""A chat may add 30 jobs; the 31st is refused."""
		for minute in range(1, 30):
			self.s.add(CHAT, 'shorts', [], when.parse(f'daily at 1:{minute:02d}', 'UTC'))
		self.assertIn('30 jobs is the most a chat may add', self.say('.jobs add shorts daily at 2:00')[0])
		self.assertEqual(len(self.s.chat_jobs(CHAT)), 32)

	def test_a_job_the_defaults_have_switches_that_one_on(self):
		"""A job typed as a default one is (in a zone that keeps its clock: Melbourne for Sydney) switches that one on,
		and brings it back where it was removed; nothing more is stored."""
		self.say('.jobs toggle 1')
		added = self.say('.jobs add rating tue-sat at 8:30am')
		self.assertEqual(newest(added), '1. * rating · Tue–Sat at 8:30am')
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [entry('trades every 20 mins weekdays')]})
		self.say('.jobs remove 1')
		self.assertEqual([job.name for job in self.s.chat_jobs(CHAT)], ['movers close US', 'trades'])
		added = self.say('.jobs add rating tue-sat at 8:30am')
		self.assertEqual(newest(added), '1. * rating · Tue–Sat at 8:30am')
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [entry('trades every 20 mins weekdays')]})

	def test_run_a_job_now(self):
		""".jobs run N runs job N now, posting to this chat, what it posts showing that it ran (no line says it is
		done); a number that is none says so; another chat's numbers are its own."""
		self.assertIsNone(self.say('.jobs run 3'))
		self.assertEqual((self.ran, self.dests), ([('trades', {})], [CHAT]))
		self.assertEqual(self.say('.jobs run 9'), ['no job 9: send .jobs for the list'])
		self.assertIsNone(self.say('.jobs run 1', chat='56')) # a chat seen first has the defaults
		self.assertEqual(self.dests, [CHAT, 'telegram:56'])

	def test_a_job_run_now_posts_nothing_where_it_has_nothing_to_show(self):
		"""Run now and .jobs run run a job as its schedule does: nothing to show (answer.Nothing) posts nothing either
		way (Run now said so), and an answer of another kind is the reply."""
		job = self.s.chat_jobs(CHAT)[2]
		for raised, posted in ((answer.Nothing('No new trades'), []),
				(answer.Answer('Rob portfolio not found'), [(CHAT, ['Rob portfolio not found'], None)] * 2)):
			def run(dest=None, **kwargs):
				"""Come to this round's answer."""
				raise raised
			self.patch(jobs.ACTIONS['trades'], 'run', run)
			with self.subTest(raised=raised):
				self.replies.clear()
				self.assertEqual((self.s.execute(job), self.s.run(job)), ('done', 'done'))
				self.assertEqual(self.replies, posted)

	def test_enable_and_disable_a_job(self):
		""".jobs disable N switches job N off and .jobs enable N on, whichever way it was; .jobs enable, disable or
		delete alone opens Edit."""
		off, on = '3. ❌* <s>trades · every 20 mins, weekdays UTC</s>', '3. * trades · every 20 mins, weekdays UTC'
		for typed, line in (('.jobs disable 3', off), ('.jobs disable 3', off), ('.jobs enable 3', on)):
			with self.subTest(typed=typed):
				self.assertEqual(self.say(typed), [line])
		self.say('.jobs disable 1')
		for typed in ('.jobs enable', '.jobs disable', '.jobs delete'):
			with self.subTest(typed=typed):
				self.assertEqual(self.say(typed)[0], '<b>Tap a job to enable or disable it</b>')
				self.assertEqual([[button.label for button in row] for row in self.replies[-1][2]],
					[['1 rating', '2 movers close US', '3 trades'],
					['OK', 'Cancel', 'Disable all', 'Delete disabled jobs']])

	def test_toggle_a_job_off_and_on(self):
		""".jobs toggle N switches job N off (it no longer fires) and on again."""
		self.assertEqual(self.say('.jobs toggle 3'), ['3. ❌* <s>trades · every 20 mins, weekdays UTC</s>'])
		self.clock.now = at(13, 21, 20)
		self.assertEqual(self.s.due(self.clock.now), [])
		self.assertEqual(self.say('.jobs toggle 3'), ['3. * trades · every 20 mins, weekdays UTC'])
		self.clock.now = at(13, 21, 40)
		self.assertEqual([job.name for job, _ in self.s.due(self.clock.now)], ['rating', 'trades'])

	def test_a_job_is_marked_till_it_first_runs(self):
		"""* marks a job that has never run, on its schedule or by hand; the list says what it means while it shows
		it."""
		self.say('.jobs run 3')
		lines = self.say('.jobs')
		self.assertIn('3. trades · every 20 mins, weekdays UTC', lines)
		self.assertIn('1. * rating · Tue–Sat at 8:30am', lines)
		self.clock.now = at(13, 21, 31) # Wednesday 8:31am in Sydney: rating has run, New York's close not yet
		self.s.tick()
		lines = self.say('.jobs')
		self.assertIn('1. rating · Tue–Sat at 8:30am', lines)
		self.assertIn('2. * movers close US · weekdays at 4:30pm New York (7:30am local, Tue–Sat)', lines)
		self.assertIn('* not run yet', lines)
		self.say('.jobs run 2')
		self.assertNotIn('* not run yet', self.say('.jobs'))

	def test_a_one_off_gone_by_is_deleted_as_the_list_is_shown(self):
		"""A one-off job whose time has gone by (run or off) is deleted as the list is next shown, never on a tick."""
		self.say('.jobs add message on 15 oct 2026 at 9am "soon"')
		self.assertEqual(len(state.load(jobs.JOBS_FILE)[CHAT]['jobs']), 2)
		self.clock.now = at(16, 0, 0)
		self.s.tick()
		self.assertEqual(len(state.load(jobs.JOBS_FILE)[CHAT]['jobs']), 2)
		self.assertNotIn('soon', '\n'.join(self.say('.jobs')))
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT], {'jobs': [entry('trades every 20 mins weekdays')]})

	def test_upcoming_and_system(self):
		""".jobs upcoming (or next, as it was called) lists the next runs in order, a repeat's runs on a day as one;
		.jobs system the system's."""
		lines = self.say('.jobs upcoming')
		self.assertEqual(self.say('.jobs next'), lines)
		self.assertEqual(lines[:4], ['<b>Upcoming runs:</b>',
			'Wed 14 Oct 8:20am (21:20 UTC) – 10:40am, every 20 mins · 3. trades',
			'Wed 14 Oct 8:30am · 1. rating',
			'Wed 14 Oct 11:00am (00:00 UTC) – Thu 15 Oct 10:40am, every 20 mins · 3. trades'])
		self.assertEqual(self.say('.jobs system'), ['<b>System jobs:</b>'])

	def test_no_schedule_running(self):
		"""Without a schedule running, .jobs says so."""
		self.patch(jobs, 'current', None)
		self.assertEqual(self.say('.jobs'), ['No schedule is running'])

	def test_a_job_is_its_chats_whichever_way_its_updates_arrive(self):
		"""A chat's jobs are kept under its network and its id, which a network gives the same in both modes: a job
		added in http mode is that chat's in pull mode, listed and fired there, and the other way round."""
		updates = test_sending.EveryNetworkAndMode()
		updates.updates = 0
		self.patch(discord_common.READER, 'bot_id', '99')
		self.env(slackBotToken='xoxb-1', discordBotToken='x')
		for network, chat in (('telegram', '-1001'), ('slack', 'C1'), ('discord', '77')):
			for first, then in (('http', 'pull'), ('pull', 'http')):
				with self.subTest(network=network, added=first):
					self.env(**test_sending.EveryNetworkAndMode.MODES[(network, first)])
					reader = READERS[network]
					with contextlib.redirect_stderr(io.StringIO()):
						added = updates.update(network, first, chat, '.jobs add shorts daily at 23:00')
						answer = bot.take(reader, added)
						if answer.then:
							answer.then()
						self.join_workers()
						key = f'{network}:{chat}'
						self.assertEqual([job.name for job in self.s.chat_jobs(key)], ['rating', 'movers close US',
							'shorts'])
						self.env(**test_sending.EveryNetworkAndMode.MODES[(network, then)])
						self.replies.clear()
						answer = bot.take(reader, updates.update(network, then, chat, '.jobs'))
						if answer.then:
							answer.then()
						self.join_workers()
					self.assertTrue(any(line.endswith('3. * shorts · daily at 11:00pm') for line in
						self.replies[-1][1]), self.replies[-1][1])
					self.assertEqual(self.replies[-1][0], key)
					self.dests.clear()
					self.s.run(self.s.chat_jobs(key)[2])
					self.assertEqual(self.dests, [key]) # posted to the same chat
					self.s.delete(self.s.chat_jobs(key)[2])


class JobsMenu(ChatBase):
	"""The .jobs menu's buttons: each screen drawn in place of the pressed one, with a page of the list and a button
	per job; Add's steps; a stale or forged press acting on nothing."""

	def test_a_job_that_is_off_has_a_red_button(self):
		"""Edit draws a job's button red when the job is off and plain when it is on; the run list, not a toggle, is
		plain."""
		off, on = buttons.OFF, ''
		def tones():
			"""The tones of the buttons of the last screen, by row."""
			return [[button.tone for button in row] for row in self.edits[-1][3]]
		self.press(f'm|edit|0|{self.crc()}')
		self.assertEqual(tones(), [[on, on, on], ['', '', '']])
		lines, rows, data = self.press(f'm|edit|0|1|{self.crc()}')
		self.assertEqual(tones(), [[off, on, on], ['', '', '', '']])
		self.press(f'm|run|0|{self.crc()}')
		self.assertEqual({tone for row in tones() for tone in row}, {''})

	def test_edit_switches_jobs_and_deletes_the_disabled_after_asking(self):
		"""Edit lists the jobs with a button for each, red where it is off: a press switches that job, OK
		goes back, and Delete disabled jobs, shown while one is off, asks before it deletes them; buttons drawn for
		another list switch and delete nothing."""
		lines, rows, data = self.press(f'm|edit|0|{self.crc()}')
		self.assertEqual((lines[0], rows), ('<b>Tap a job to enable or disable it</b>', [['1 rating',
			'2 movers close US', '3 trades'], ['OK', 'Cancel', 'Disable all']]))
		lines, rows, data = self.press(data['1 rating'])
		self.assertEqual((lines[0], rows), ('Disabled 1. rating', [['1 rating', '2 movers close US', '3 trades'],
			['OK', 'Cancel', 'Disable all', 'Delete disabled jobs']]))
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT]['off'], ['rating'])
		lines, rows, data = self.press(data['Delete disabled jobs'])
		self.assertEqual((lines[0], rows), ('<b>Delete the 1 disabled job?</b>', [['Yes, delete them', 'Cancel']]))
		self.assertEqual(lines[2], '1. ❌ <s>rating</s>')
		lines, rows, data = self.press(data['Cancel'])
		self.assertEqual(lines[0], '<b>Tap a job to enable or disable it</b>')
		lines, rows, data = self.press(data['OK'])
		self.assertEqual((lines[0], rows[0]), ('<b>Jobs here</b>', ['+', 'Edit', 'Run', 'Upcoming']))
		self.press(f'm|edit|0|{self.crc()}')
		self.assertEqual(self.press('m|edit|0|ask|0000')[0][0], 'The jobs have changed: here they are now')
		lines, rows, data = self.press(f'm|edit|0|{self.crc()}')
		lines, rows, data = self.press(data['Delete disabled jobs'])
		lines, rows, data = self.press(data['Yes, delete them'])
		self.assertEqual((lines[0], [job.name for job in self.s.chat_jobs(CHAT)]), ('Deleted 1 disabled job',
			['movers close US', 'trades']))

	def test_the_top_level_offers_only_what_can_be_done(self):
		"""Edit, Run and Upcoming show only where a job is there to act on: with every job off no Upcoming; with none,
		only +."""
		def top():
			"""The top screen's button labels, by row."""
			return [[button.label for button in row] for row in about.jobs_screen(TELEGRAM, CHAT)[1]]
		self.assertEqual(top(), [['+', 'Edit', 'Run', 'Upcoming']])
		for job in self.s.chat_jobs(CHAT):
			self.s.toggle(job, False)
		self.assertEqual(top(), [['+', 'Edit', 'Run']])
		for job in self.s.chat_jobs(CHAT):
			self.s.delete(job)
		self.assertEqual(top(), [['+']])

	def test_run_now_runs_the_job_and_says_only_what_went_wrong(self):
		"""Run now lists the jobs with a button each; a press runs the job, what it posts showing that it ran: no
		message says it is done, but one says so when it did not run (running already)."""
		_, _, data = self.press(f'm|run|0|{self.crc()}')
		self.replies.clear()
		self.press(data['3 trades'])
		self.assertEqual((self.ran, self.replies), ([('trades', {})], []))
		self.assertTrue(self.s.claim(self.s.chat_jobs(CHAT)[2].key)) # as if it were running
		self.press(data['3 trades'])
		self.assertEqual((len(self.ran), self.replies), (1, [(CHAT, ['3. trades: already running'], None)]))

	def test_upcoming_lists_the_next_runs_with_cancel(self):
		"""Upcoming lists the next runs, with Cancel back to the list."""
		lines, rows, data = self.press(f'm|next|{self.crc()}')
		self.assertEqual((lines[:2], rows), (['<b>Upcoming runs:</b>', 'Wed 14 Oct 8:20am (21:20 UTC) – 10:40am,'
			' every 20 mins · 3. trades'], [['Back']]))
		self.assertEqual(self.press(data['Back'])[0][0], '<b>Jobs here</b>')

	def test_a_stale_or_forged_press_acts_on_nothing(self):
		"""A press drawn for another list (its checksum), for a number that is none, or of no screen at all (a job
		button of the older lists, j| and e|, and of the retired Enable, Disable and Delete screens among them)
		switches, deletes and runs nothing: the screen is drawn as the list is now, or the press is ignored."""
		good = self.crc()
		for data in (f'm|edit|0|1|0000', f'm|run|0|3|0000', f'm|run|0|9|{good}', f'm|run|0|0|{good}',
				f'm|run|0|x|{good}', f'm|run|0|all|{good}'):
			with self.subTest(data=data):
				lines, _, _ = self.press(data)
				self.assertEqual(lines[0], 'The jobs have changed: here they are now')
		for data in (f'm|zz|0|{good}', f'm|run|0|1|{good}|' + 'x' * 60, 'm|run|٨|1|' + good, 'm|run|0|1|a b',
				f'j|3|{good}', f'e|3|{good}', f'm|on|0|1|{good}', f'm|off|0|1|{good}', f'm|del|0|3|{good}'):
			with self.subTest(data=data):
				self.assertEqual(self.press(data), (None, None, None))
		self.assertEqual((self.ran, len(self.s.chat_jobs(CHAT))), ([], 3))
		self.assertTrue(all(job.on for job in self.s.chat_jobs(CHAT)))

	def test_add_by_buttons_back_and_cancel(self):
		"""Add takes the report (by its name alone), how often, then the day, the hour and the minute from buttons, by
		the timezone setting's clock, each choice's default marked † and the key under it in italics; Cancel goes
		back to the list, and after the report Back a step back; its last step adds the job and says so, the same job
		as typed."""
		lines, rows, data = self.press(f'm|add|{self.crc()}')
		self.assertEqual(lines[:3], ['<b>Add a job: which report?</b>', '', '<b>Jobs</b>']) # the list stays in view
		self.assertEqual(rows, [['trades', 'movers midsession', 'movers premarket'], ['movers close', 'movers',
			'performance'], ['earnings', 'shorts', 'rating'], ['milestone', 'reminder', 'holdings'],
			['treemap', 'who', 'marketcap'], ['beta', 'price', 'buysell'], ['ratio', 'stock'], ['Cancel']])
		self.assertEqual((data['movers'], data['Cancel']), (f'm|add|5|{self.crc()}', f'm|top|0|{self.crc()}'))
		lines, rows, data = self.press(data['movers'])
		self.assertEqual((lines[:3], rows), (['<b>Add movers: how often?</b>', '', '<i>† indicates default</i>'],
			[['one-off', 'hourly', 'daily†'], ['weekly', 'monthly', 'quarterly'], ['bi-annual', 'annual', 'every...'],
			['Back', 'Cancel']]))
		lines, rows, data = self.press(data['weekly'])
		self.assertEqual(rows[:2], [['Mon', 'Tue', 'Wed', 'Thu'], ['Fri', 'Sat†', 'Sun']])
		self.assertEqual(data['Cancel'], f'm|top|0|{self.crc()}')
		lines, rows, data = self.press(data['Fri'])
		self.assertEqual(lines[:2], ['<b>Add movers, weekly, Fridays: at what hour?</b>', "By Melbourne's clock"])
		self.assertEqual((len(rows), [len(row) for row in rows], rows[1][4], rows[-1]), (5, [5] * 5, '09†',
			['20', '21', '22', '23', 'Back']))
		self.assertEqual(data['Back'], f'm|add|5|w|{self.crc()}')
		lines, rows, data = self.press(data['14'])
		self.assertEqual((rows[0], rows[-1]), (['14:00†', '14:05', '14:10', '14:15'], ['Back', 'Cancel']))
		lines, rows, data = self.press(data['14:30'])
		self.assertEqual(newest(lines), '3. * movers · weekly, Fridays at 2:30pm')
		self.assertEqual((lines[0], rows, data['+']), ('Added', [['+', 'Edit', 'Run', 'Upcoming']],
			f'm|add|{self.crc()}')) # the whole list, the job added in bold, with the list's buttons
		self.assertEqual(state.load(jobs.JOBS_FILE)[CHAT]['jobs'][-1], entry('movers every friday at 2:30pm',
			zone='Australia/Melbourne'))
		self.assertIn('that job is here already', self.say('.jobs add movers weekly on friday at 14:30')[0])

	def test_the_month_steps_start_a_cycle(self):
		"""Monthly asks for the day of the month; quarterly, bi-annual and annual first for the start month, the cycle
		following from it, then the day, hour and minute; annual offers only the days its month has. On Discord the
		days of a month come on two pages."""
		lines, rows, data = self.press(f'm|add|6|m|{self.crc()}')
		self.assertEqual((lines[:2], rows[0], rows[-2], rows[-1]), (['<b>Add performance, monthly: on which day of the'
			' month?</b>', 'A month without that day has no run'], ['1†', '2', '3', '4', '5'], ['31'],
			['Back', 'Cancel']))
		lines, rows, data = self.press(data['15'])
		self.assertEqual(lines[0], '<b>Add performance, monthly, the 15th: at what hour?</b>')
		lines, rows, data = self.press(data['09†'])
		lines, rows, data = self.press(data['09:00†'])
		self.assertEqual(newest(lines), '3. * performance · monthly, the 15th at 9:00am')
		for frequency, start, said, added in (('quarterly', 'Feb', 'quarterly, Feb/May/Aug/Nov',
				'quarterly, 15 Feb/May/Aug/Nov at 9:00am'), ('bi-annual', 'Mar', 'bi-annual, Mar and Sep',
				'bi-annual, 15 Mar and 15 Sep at 9:00am'), ('annual', 'Apr', 'annual, in Apr',
				'annual, 15 Apr at 9:00am')):
			with self.subTest(frequency=frequency):
				lines, rows, data = self.press(f'm|add|{self.crc()}')
				lines, rows, data = self.press(data['movers'])
				lines, rows, data = self.press(data[frequency])
				self.assertEqual((lines[0], rows[0]), (f'<b>Add movers, {frequency}: start month?</b>', ['Jan†', 'Feb',
					'Mar', 'Apr']))
				lines, rows, data = self.press(data[start])
				self.assertEqual(lines[0], f'<b>Add movers, {said}: on which day of the month?</b>')
				for pressed in ('15', '09†', '09:00†'):
					lines, rows, data = self.press(data[pressed])
				self.assertTrue(newest(lines).endswith(f'* movers · {added}'), lines)
		lines, rows, data = self.press(f'm|add|5|a|2|{self.crc()}')
		self.assertEqual((lines[0], rows[-2]), ('<b>Add movers, annual, in Feb: on which day of the month?</b>',
			['26', '27', '28', '29']))
		self.assertEqual(about.add_screen(DISCORD, CHAT, ['5', 'm'])[1][-1][0].label, '▶')
		self.assertEqual(about.add_screen(DISCORD, CHAT, ['5', 'm', 'p1'])[1][0][0].label, '21')

	def test_repeats_by_buttons(self):
		"""hourly and every... take which days, the start hour and minute and the end time (or the end of the day);
		every... offers a weekday too, which takes an hour and a minute; every default gives the all-day repeat."""
		lines, rows, data = self.press(f'm|add|5|r|{self.crc()}')
		self.assertEqual((lines[0], rows), ('<b>Add movers: every...</b>', [['5 mins', '10 mins', '15 mins', '20 mins'],
			['30 mins', '2 hours', '3 hours', '4 hours'], ['6 hours', '12 hours', 'weekday†'], ['Back', 'Cancel']]))
		lines, rows, data = self.press(data['weekday†'])
		self.assertEqual(lines[0], '<b>Add movers, weekdays: at what hour?</b>')
		lines, rows, data = self.press(data['09†'])
		self.assertEqual(newest(self.press(data['09:00†'])[0]), '3. * movers · weekdays at 9:00am')
		lines, rows, data = self.press(f'm|add|8|h|{self.crc()}')
		self.assertEqual((lines[0], rows[0]), ('<b>Add shorts, hourly: on which days?</b>', ['every day†', 'weekdays']))
		lines, rows, data = self.press(data['weekdays'])
		self.assertEqual(lines[:2], ['<b>Add shorts, hourly, weekdays: start hour?</b>', "By Melbourne's clock"])
		lines, rows, data = self.press(data['10'])
		self.assertEqual((lines[0], rows[0]), ('<b>Add shorts, hourly, weekdays from 10am: start minute?</b>',
			[':00†', ':05', ':10', ':15']))
		lines, rows, data = self.press(data[':05'])
		self.assertEqual((lines[0], rows[0], rows[-2:]), ('<b>Add shorts, hourly at :05, weekdays from 10am: end'
			' time?</b>', ['11:05', '12:05', '13:05', '14:05'], [['23:05', 'end of day†'], ['Back', 'Cancel']]))
		self.assertEqual(newest(self.press(data['16:05'])[0]), '4. * shorts · hourly at :05, weekdays 10am–4pm')
		self.assertEqual(newest(self.press(f'm|add|9|h|d|0|0|e|{self.crc()}')[0]), '2. * rating · hourly')
		self.assertEqual(newest(self.press(f'm|add|10|r|20|k|10|5|965|{self.crc()}')[0]),
			'5. * milestone · every 20 mins, weekdays 10:05am–4:05pm')
		self.assertEqual(newest(self.press(f'm|add|7|r|20|k|0|0|e|{self.crc()}')[0]),
			'5. * earnings · every 20 mins, weekdays')
		screen = about.add_screen(DISCORD, CHAT, ['5', 'h', 'd', '0', '0'])
		rows = [[button.label for button in row] for row in screen[1]]
		self.assertEqual((len(rows), rows[-1]), (5, ['21:00', '22:00', '23:00', 'end of day†', 'Back'])) # 25 buttons

	def test_a_one_off_by_year_month_day_hour_and_minute(self):
		"""A one-off takes its year (this one and the nine after it), month, day, hour and minute, never one gone by,
		tomorrow its default day; a reminder's text cannot come from a button, so its screen says how to type one."""
		lines, rows, data = self.press(f'm|add|8|o|{self.crc()}')
		self.assertEqual((lines[0], rows[:2]), ('<b>Add shorts, once: in which year?</b>', [['2026†', '2027', '2028',
			'2029', '2030'], ['2031', '2032', '2033', '2034', '2035']]))
		lines, rows, data = self.press(data['2026†'])
		self.assertEqual((lines[0], rows[0]), ('<b>Add shorts, once, 2026: in which month?</b>',
			['Oct†', 'Nov', 'Dec']))
		lines, rows, data = self.press(data['Oct†'])
		self.assertEqual((lines[0], rows[0], rows[-2]), ('<b>Add shorts, once, Oct 2026: on which day?</b>', ['14',
			'15†', '16', '17', '18'], ['29', '30', '31']))
		lines, rows, data = self.press(f'm|add|8|o|2027|{self.crc()}')
		self.assertEqual(rows[0], ['Jan†', 'Feb', 'Mar', 'Apr'])
		lines, rows, data = self.press(data['Feb'])
		self.assertEqual((rows[0][0], rows[-2]), ('1†', ['26', '27', '28']))
		lines, rows, data = self.press(data['20'])
		self.assertEqual(lines[0], '<b>Add shorts, once, 20 Feb 2027: at what hour?</b>')
		lines, rows, data = self.press(data['08'])
		self.assertEqual(newest(self.press(data['08:00†'])[0]), '3. * shorts · once, 20 Feb 2027 at 8:00am')
		lines, rows, _ = self.press(f'm|add|11|{self.crc()}')
		self.assertEqual(lines[:3], ['<b>Add a reminder</b>', "A reminder's text is what you type:",
			'.jobs add reminder SCHEDULE "TEXT"'])
		self.assertEqual(rows, [['Back', 'Cancel']])

	def test_the_commands_of_help_by_buttons(self):
		"""Add offers the commands of .help after the reports: one that takes no stock adds as a report does, as does
		one whose usage brackets its stock or portfolio (a picker's, run bare as typed: the first one's answer); one
		that needs a stock says how to type it. On Discord the list comes on two pages."""
		lines, rows, data = self.press(f'm|add|{self.crc()}')
		for pressed in ('ratio', 'weekly', 'Fri', '09†', '09:00†'):
			lines, rows, data = self.press(data[pressed])
		self.assertEqual(newest(lines), '3. * ratio · weekly, Fridays at 9:00am')
		self.assertIn('ratio', [job.action for job in self.s.chat_jobs(CHAT)])
		lines, rows, data = self.press(f'm|add|{self.crc()}')
		for pressed in ('treemap', 'weekly', 'Fri', '09†', '09:00†'):
			lines, rows, data = self.press(data[pressed])
		self.assertEqual(newest(lines), '5. * treemap · weekly, Fridays at 9:00am')
		made = next(job for job in self.s.chat_jobs(CHAT) if job.action == 'treemap')
		self.assertEqual((made.action, made.kwargs), ('treemap', {'words': []}))
		lines, rows, data = self.press(f'm|add|{self.crc()}')
		lines, rows, _ = self.press(data['who'])
		self.assertEqual((lines[:6], rows), (['<b>Add who</b>', 'What who is about is typed:',
			'.jobs add who SYMBOL SCHEDULE', '', '<b>For example:</b>', '.jobs add who AAPL weekly'],
			[['Back', 'Cancel']]))
		first, second = (about.add_screen(DISCORD, CHAT, steps)[1] for steps in ([], ['p1']))
		self.assertEqual(([len(row) for row in first], [button.label for button in first[-1]]), ([4, 4, 4, 4, 2],
			['▶', 'Cancel']))
		self.assertEqual([button.label for row in second for button in row], ['price',
			'buysell', 'ratio', 'stock', '◀', 'Cancel'])

	def test_a_step_that_is_none_adds_nothing(self):
		"""Data that is no step of Add (forged, or an older finbot's: the weekdays frequency, the next 14 days, every...
		hourly) adds nothing and says so: a report, frequency, year, month or day not offered, a day gone by, 30 Feb, an
		end not among the runs, a page where there is none."""
		crc = self.crc()
		for data in ('26', '5|x', '5|k', '5|o|261020', '5|r|60', '5|w|7|9', '5|d|24', '5|d|9|9', '5|d|9|0|0',
				'1|r|7', '5|o|2025', '5|o|2036', '5|o|2026|9', '5|o|2026|10|13', '5|o|2027|2|30', '5|a|2|30', '5|q|13',
				'5|w|p1', '5|m|def', '5|h|d|10|5|600', '5|h|d|10|5|1000', '5|h|d|10|5|e|0'):
			with self.subTest(data=data):
				self.assertEqual(self.press(f'm|add|{data}|{crc}')[0][0], 'That is no step of Add')
		self.assertEqual(len(self.s.chat_jobs(CHAT)), 3)

	def test_every_screen_fits_each_network(self):
		"""With every default job and 30 jobs added, each page of each screen fits a message of each network (Discord
		2000 characters, Telegram 4096), with at most 25 buttons in five rows of five, each button's data within
		Telegram's 64 bytes and its own in the message (Slack and Discord take it as the button's id)."""
		def fits(service, lines, markup):
			"""Check one screen against a network's limits."""
			self.assertLessEqual(len('\n'.join(lines)), service.text_limit)
			if service == DISCORD:
				self.assertLessEqual(len(markup), 5)
				self.assertTrue(all(len(row) <= 5 for row in markup))
			data = [button.data for row in markup for button in row]
			self.assertEqual(len(data), len(set(data)), data)
			self.assertTrue(all(len(each.encode()) <= buttons.MAX_CALLBACK_BYTES for each in data))
		self.patch(catalog, 'ITEMS', ITEMS)
		for minute in range(29):
			self.s.add(CHAT, 'message', [f'reminder number {minute} ' * 4], when.parse(f'daily at 1:{minute:02d}',
				'UTC'))
		for service in (TELEGRAM, SLACK, DISCORD):
			for screen in ('top', 'edit', 'run'):
				for page in range(6):
					with self.subTest(service=service, screen=screen, page=page):
						fits(service, *about.jobs_screen(service, CHAT, screen, page))
			for steps in ([], ['p1'], ['19'], ['5'], ['5', 'w'], ['5', 'w', '5'], ['5', 'w', '5', '14'], ['5', 'm'],
					['5', 'm', 'p1'], ['5', 'q'], ['5', 'q', '2'], ['5', 'b', '3'], ['5', 'a'], ['5', 'a', '2'],
					['5', 'a', '2', '29'], ['5', 'o'], ['5', 'o', '2026'], ['5', 'o', '2026', '10'],
					['5', 'o', '2027', '1'],
					['5', 'o', '2027', '1', 'p1'], ['5', 'o', '2027', '1', '31'], ['5', 'h'], ['5', 'h', 'd'],
					['5', 'h', 'd', '0'], ['5', 'h', 'd', '0', '0'], ['5', 'r'], ['5', 'r', 'k'], ['5', 'r', 'k', '9'],
					['5', 'r', '20'], ['5', 'r', '20', 'k', '10'], ['5', 'r', '20', 'k', '10', '5'], ['12']):
				if steps[-1:] == ['p1'] and service != DISCORD: # Telegram and Slack take every day on one page
					continue
				with self.subTest(service=service, steps=steps):
					lines, markup = about.add_screen(service, CHAT, steps)
					fits(service, about.listed_with(service, CHAT, lines), markup)
			fits(service, *about.next_screen(service, CHAT))
			fits(service, *about.delete_disabled_screen(service, CHAT))
			fits(service, *about.added_screen(service, CHAT, 1))
			fits(service, *about.add_failed(service, CHAT, ['5', 'd', '9'], 'that job is here already'))
		pages = len({about.jobs_screen(DISCORD, CHAT, 'edit', page)[0][0] for page in range(6)})
		self.assertEqual(pages, 4) # 64 jobs, 16 to a page on Discord
		lines, markup = about.jobs_screen(DISCORD, CHAT, 'top', 3) # no pages: what fits, and how many more
		self.assertEqual((lines[0], '▶' in str(markup), '…and ' in str(lines)), ('**Jobs here**', False, True))

class ReportImports(FinbotCase):
	"""What importing the reports brings in."""

	def test_a_report_loads_neither_pillow_nor_the_scheduler(self):
		"""A report imports only its own module: movers once pulled in every report, through charts and jobs, and the
		chart code until a chart is drawn."""
		code = ('import sys; from lib.reports import movers, performance, trades, shorts, earnings; '
			'print(sorted(m for m in ("lib.jobs", "PIL") if m in sys.modules))')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data})
		self.assertEqual(out.stdout.strip().splitlines()[-1:], ['[]'], out.stderr)


if __name__ == '__main__':
	unittest.main()
