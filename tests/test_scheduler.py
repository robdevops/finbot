"""The scheduler (lib/jobs.py): each chat's jobs and the system jobs firing on a fake clock, across the clocks' changes;
.jobs in a chat, and its buttons; each command run in the bot's process, past its deadline too."""
import contextlib, datetime, io, os, subprocess, sys, tempfile, time, unittest
import zoneinfo
from pathlib import Path
from unittest import mock
from tests.common import *
from lib import jobs
from lib.reports import cleanup, podcasts, price, sharesight_warm, yahoo_warm
from tests import test_sending

PREFETCH_HISTORY = yahoo.prefetch_history # FinbotCase replaces it; the warm job's test puts it back


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
		self.env(sharesight_auth={'client_id': 'id'})
		def answer(ticker, days, full):
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
		self.env(sharesight_auth={'client_id': None})
		self.assertEqual((yahoo_warm.run(), len(asked)), (1, 1))

	def test_with_the_cache_off_nothing_is_fetched(self):
		"""With the cache preference off nothing would be kept, so nothing is fetched."""
		self.prefs(cache=False)
		self.patch(yahoo, '_chart_answer', None)
		self.assertEqual(yahoo_warm.run(), 0)


class SharesightWarmJob(FinbotCase):
	def test_the_portfolios_are_refreshed_where_sharesight_is_configured(self):
		"""sharesight_warm refreshes the portfolio list and the holdings (sharesight.warm) and counts the portfolios;
		without Sharesight configured, or with the cache preference off (nothing would be kept), it fetches nothing."""
		self.patch(sharesight, 'warm', lambda: ['Rob', 'RobSMSF'])
		self.env(sharesight_auth={'client_id': 'id'})
		self.assertEqual(sharesight_warm.run(), 2)
		self.prefs(cache=False)
		self.assertEqual(sharesight_warm.run(), 0)
		self.prefs(cache=True)
		self.env(sharesight_auth={'client_id': None})
		self.assertEqual(sharesight_warm.run(), 0)

	def test_a_failure_is_logged_not_reported(self):
		"""A refresh that fails is only logged, not reported in the chat: the next run tries again."""
		def down():
			"""Sharesight unreachable, as warm meets it."""
			raise RuntimeError('Sharesight portfolios: unreachable')
		self.patch(sharesight, 'warm', down)
		self.env(sharesight_auth={'client_id': 'id'})
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertEqual(sharesight_warm.run(), 0)
		self.assertIn('sharesight_warm: refresh failed: Sharesight portfolios: unreachable', log.getvalue())
		self.assertEqual(self.errors, [])


CHAT, OTHER = 'telegram:55', 'slack:C1' # two chats, by their keys


def entry(line, on=True):
	"""A job as SCHEDULE_FILE stores it, from its line as .jobs add takes it."""
	job = jobs.parse_job(line)
	return {'when': job.when, 'reports': job.text, 'zone': job.zone.key, 'on': on}


class SchedulerBase(FinbotCase):
	def setUp(self):
		"""Chat telegram:55 runs trades every 20 minutes on weekdays; a fake clock; no system jobs (they have tests of
		their own); the reports noted with the chat each posts to, not run."""
		super().setUp()
		self.patch(jobs, 'SYSTEM', ())
		self.store(CHAT, '*/20 * * * Mon-Fri trades')
		self.clock = Clock(at(13, 21, 3))
		self.ran, self.dests = [], []
		for name in ('trades', 'shorts', 'price', 'rating', 'reminder'):
			self.patch(jobs.SCRIPTS[name], 'run', self.recorder(name))

	def recorder(self, name):
		"""A report's run() that notes the run, and the chat it would post to (its key; None for the home chats)."""
		def run(dest=None, **kwargs):
			"""Note the run and where it posts."""
			self.ran.append((name, kwargs))
			self.dests.append(dest.key if dest else None)
		return run

	def store(self, chat, *lines, on=True):
		"""Set a chat's jobs, as .jobs add would have stored them."""
		with state.edit(jobs.SCHEDULE_FILE, {}) as chats:
			chats[chat] = [entry(line, on) for line in lines]

	def scheduler(self, catchup=5):
		"""A loaded scheduler on the fake clock that runs commands in this process, at once."""
		s = jobs.Scheduler(catchup=catchup, clock=self.clock, sleep=lambda seconds: None, spawn=lambda f, *a: f(*a))
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		return s


class WarmNow(SchedulerBase):
	def test_the_warm_jobs_run_through_the_scheduler(self):
		"""warm_now runs both warm jobs through the scheduler, which does not start one that is running already."""
		warmed = []
		self.patch(jobs.SCRIPTS['sharesight_warm'], 'run', lambda: warmed.append('sharesight'))
		self.patch(jobs.SCRIPTS['yahoo_warm'], 'run', lambda: warmed.append('yahoo'))
		s = self.scheduler()
		with contextlib.redirect_stderr(io.StringIO()) as log:
			jobs.warm_now(s)
			s.busy.add(('', 'yahoo_warm')) # on its schedule
			jobs.warm_now(s)
		self.assertEqual(warmed, ['sharesight', 'yahoo', 'sharesight'])
		self.assertIn('cache: filling it again: sharesight_warm, yahoo_warm', log.getvalue())

	def test_without_a_scheduler_each_runs_here(self):
		"""Without a scheduler (a test, a tool), each warm job runs here, one after the other, a failure reported."""
		started = []
		def run(label, module, kwargs, dest=None):
			"""Note the run; the first one fails."""
			started.append(label)
			if label == 'sharesight_warm':
				raise RuntimeError('Sharesight unreachable')
		self.patch(jobs, 'run_in_process', run)
		with contextlib.redirect_stderr(io.StringIO()):
			jobs.warm_now()
		self.assertEqual(started, ['sharesight_warm', 'yahoo_warm'])
		self.assertEqual(self.errors, ['⚠️ sharesight_warm: RuntimeError: Sharesight unreachable'])


class SystemJobs(FinbotCase):
	def test_the_system_jobs_are_fixed_and_no_chats(self):
		"""The system jobs run on a schedule of their own, the same for every install: each warm job within its
		cache's lifetime (Sharesight's every 30 minutes, cached 40; Yahoo's every 8 hours, cached 12), and cleanup
		weekly. A chat can neither add one nor see it among its own jobs."""
		s = jobs.Scheduler()
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		system = {job.text: job.when for job in s.system_jobs()}
		self.assertEqual(system, {'sharesight_warm': '14,44 * * * *', 'yahoo_warm': '7 */8 * * *',
			'cleanup 30': '51 18 * * Sat'})
		self.assertLess(30 * 60, config.prefs.performance_cache_seconds)
		self.assertLess(8 * 3600, config.prefs.cache_seconds)
		self.assertEqual(s.chat_jobs(''), s.system_jobs())
		for name in jobs.SYSTEM_SCRIPTS:
			with self.subTest(name=name), self.assertRaisesRegex(jobs.ScheduleError, f"no report '{name}'"):
				s.add(CHAT, f'0 1 * * * {name}')


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
		self.patch(jobs.SCRIPTS['trades'], 'run', lambda dest=None, **k: dests.append(dest))
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		self.assertEqual(s.tick(), 30) # the next run is 20 minutes away: wake at most every 30 seconds
		self.assertEqual([(dest.key, dest.scheduled) for dest in dests], [(CHAT, True)])
		self.clock.now = at(13, 21, 39, 50)
		self.assertEqual(s.tick(), 10)

	def test_each_chats_jobs_post_to_that_chat(self):
		"""Two chats' jobs at the same time each run, each posting to its own chat."""
		self.store(OTHER, '*/20 * * * Mon-Fri trades', '0 22 * * * shorts')
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
		self.store(CHAT, '*/20 * * * Mon-Fri trades', on=False)
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
		first.last = {first.chat_jobs(CHAT)[0].key: at(13, 21, 0).isoformat()}
		state.save(jobs.STATE_FILE, first.last)
		self.clock.now = at(13, 21, 43)
		s = self.scheduler()
		# 21:20 is older than 5 minutes: skipped
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)])

	def test_a_corrupt_state_file_is_reported_and_the_schedule_starts_afresh(self):
		"""A state file cut off mid-write is reported once, and the schedule runs as usual and writes it afresh."""
		Path(config.env.data_dir, jobs.STATE_FILE).write_text('{"telegram:55|*/20 * * * Mon-Fri|UTC|trades": "2026-1')
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

	def test_a_failing_job_is_reported_to_its_chat_and_the_next_command_still_runs(self):
		"""A command that fails is reported to the chat whose job it is, and the next command of the job still runs."""
		self.store(CHAT, '*/20 * * * * trades; shorts')
		def boom(dest=None, **k):
			"""Fail."""
			raise RuntimeError('boom')
		self.patch(jobs.SCRIPTS['trades'], 'run', boom)
		reported = []
		self.patch(delivery, 'report_error', lambda e, dest=None, context=None: reported.append((context, dest.key)))
		s = self.scheduler()
		self.assertEqual(s.execute(s.chat_jobs(CHAT)[0].commands, CHAT), 'failed')
		self.assertEqual(reported, [('trades', CHAT)])
		self.assertEqual(self.ran, [('shorts', {})])

	def test_system_exit_inside_a_job_is_reported_not_raised(self):
		"""A report calling sys.exit is reported like any failure and does not stop the scheduler."""
		def quit_(dest=None, **k):
			"""Exit, as a report may."""
			raise SystemExit(1)
		self.patch(jobs.SCRIPTS['trades'], 'run', quit_)
		s = self.scheduler()
		s.run(s.chat_jobs(CHAT)[0])
		self.assertEqual(len(self.errors), 1)

	def test_a_command_past_its_deadline_is_reported_once_and_left_to_finish(self):
		"""A command still running at its deadline is reported as late, once, and runs on to its end (a thread cannot
		be stopped); meanwhile it stays marked running, so a second run of it is turned away; then the rest of its job
		runs."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.1)
		self.store(CHAT, '*/20 * * * * trades; shorts')
		s = self.scheduler()
		second = []
		def slow(dest=None, **k):
			"""Take three deadlines, and try a second run of this command meanwhile."""
			time.sleep(0.3)
			second.append(s.execute(s.chat_jobs(CHAT)[0].commands[:1], CHAT))
			self.ran.append(('trades', k))
		self.patch(jobs.SCRIPTS['trades'], 'run', slow)
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(s.run(s.chat_jobs(CHAT)[0]), 'done')
		self.assertEqual(self.errors, ['⚠️ trades: TimeoutError: still running after 0.00166667 minutes, and left to'
			' finish'])
		self.assertEqual(second, ['already running'])
		self.assertEqual(self.ran, [('trades', {}), ('shorts', {})])
		self.assertEqual(s.busy, set())

	def test_each_command_of_a_job_has_a_deadline_of_its_own(self):
		"""The deadline is per command (it once covered the whole line): two that each take most of it are not late."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.4)
		self.store(CHAT, '*/20 * * * * trades; shorts')
		self.patch(jobs.SCRIPTS['trades'], 'run', lambda dest=None, **k: time.sleep(0.25))
		self.patch(jobs.SCRIPTS['shorts'], 'run', lambda dest=None, **k: time.sleep(0.25))
		s = self.scheduler()
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertEqual(s.run(s.chat_jobs(CHAT)[0]), 'done')
		time.sleep(0.3) # past where a deadline of the whole job would have struck
		self.assertEqual(self.errors, [])

	def test_a_stored_job_that_cannot_be_is_reported_and_the_rest_run(self):
		"""A stored job that cannot be any more (a report since retired, say) is reported and left out; the chat's other
		jobs load."""
		with state.edit(jobs.SCHEDULE_FILE, {}) as chats:
			chats[CHAT].append({'when': '0 1 * * *', 'reports': 'nothere', 'zone': 'UTC', 'on': True})
		s = self.scheduler()
		self.assertEqual([job.text for job in s.chat_jobs(CHAT)], ['trades'])
		self.assertEqual(len(self.errors), 1)
		self.assertIn("a job of telegram:55 left out: no report 'nothere'", self.errors[0])

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


class DaylightSaving(FinbotCase):
	"""Melbourne's clocks go back an hour at 03:00 on 5 April 2026 and forward at 02:00 on 4 October 2026. The fire
	times must be right on any croniter: the distro packages (up to 6.0) got zoneinfo's changes wrong."""
	MEL = zoneinfo.ZoneInfo('Australia/Melbourne')

	def fires(self, expr, start, end):
		"""When a Melbourne job fires between start and end, as Melbourne times ('04 09:00 AEDT')."""
		job = jobs.parse_job(f'CRON_TZ=Australia/Melbourne {expr} trades')
		s = jobs.Scheduler()
		times, t = [], start
		while (t := s.next_fire(job, t)) <= end:
			# by way of UTC: the real local time
			times.append(t.astimezone(UTC).astimezone(self.MEL).strftime('%d %H:%M %Z'))
		return times

	def mel(self, *args, **kw):
		"""A Melbourne time."""
		return datetime.datetime(*args, tzinfo=self.MEL, **kw)

	def test_a_daily_job_fires_once_at_its_time(self):
		"""A daily job fires at its local time each day across both changes."""
		self.assertEqual(self.fires('0 9 * * *', self.mel(2026, 10, 2), self.mel(2026, 10, 6)),
			['02 09:00 AEST', '03 09:00 AEST', '04 09:00 AEDT', '05 09:00 AEDT'])
		self.assertEqual(self.fires('0 9 * * *', self.mel(2026, 4, 3), self.mel(2026, 4, 7)),
			['03 09:00 AEDT', '04 09:00 AEDT', '05 09:00 AEST', '06 09:00 AEST'])

	def test_a_skipped_or_repeated_time_fires_once(self):
		"""A time the clocks skip fires an hour later, and a repeated one fires once."""
		self.assertEqual(self.fires('30 2 * * *', self.mel(2026, 10, 3), self.mel(2026, 10, 6)),
			['03 02:30 AEST', '04 03:30 AEDT', '05 02:30 AEDT'])
		self.assertEqual(self.fires('30 2 * * *', self.mel(2026, 4, 4), self.mel(2026, 4, 7)),
			['04 02:30 AEDT', '05 02:30 AEDT', '06 02:30 AEST'])
		self.assertEqual(self.fires('*/20 * * * *', self.mel(2026, 10, 4, 1, 30), self.mel(2026, 10, 4, 3, 50)),
			['04 01:40 AEST', '04 03:00 AEDT', '04 03:20 AEDT', '04 03:40 AEDT'])
		self.assertEqual(self.fires('*/20 * * * *', self.mel(2026, 4, 5, 1, 30), self.mel(2026, 4, 5, 3, 30)),
						 ['05 01:40 AEDT', '05 02:00 AEDT', '05 02:20 AEDT', '05 02:40 AEDT', '05 03:00 AEST',
						 	'05 03:20 AEST'])

	def test_starting_in_the_repeated_hour_runs_nothing_twice(self):
		"""Starting during the repeated hour runs nothing twice."""
		second_time_round = self.mel(2026, 4, 5, 2, 10, fold=1).astimezone(UTC)
		self.assertEqual(self.fires('*/20 * * * *', second_time_round, self.mel(2026, 4, 5, 3, 0, 30)),
			['05 03:00 AEST'])
		self.assertEqual(self.fires('30 2 * * *', second_time_round, self.mel(2026, 4, 6, 12)), ['06 02:30 AEST'])

	def test_the_scheduler_runs_a_daily_job_once_across_the_change(self):
		"""The scheduler runs a chat's daily Melbourne job once a day across the change to daylight time."""
		self.patch(jobs, 'SYSTEM', ())
		with state.edit(jobs.SCHEDULE_FILE, {}) as chats:
			chats[CHAT] = [entry('CRON_TZ=Australia/Melbourne 0 9 * * * trades')]
		clock = Clock(self.mel(2026, 10, 3, 12).astimezone(UTC))
		s = jobs.Scheduler(clock=clock, runner=lambda *a: None)
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		fired = []
		while clock.now < self.mel(2026, 10, 5, 12):
			fired += [t.astimezone(UTC).astimezone(self.MEL).strftime('%d %H:%M') for _, t in s.due(clock.now)]
			clock.now += datetime.timedelta(minutes=10)
		self.assertEqual(fired, ['04 09:00', '05 09:00'])


class JobsInChat(SchedulerBase):
	"""What a chat does with its jobs: .jobs lists them; run, toggle, add and del; their buttons."""

	def setUp(self):
		"""Chat telegram:55 with its one job, the scheduler running, Telegram's toasts and edits noted."""
		super().setUp()
		self.s = self.scheduler()
		self.patch(jobs, 'current', self.s)
		self.toasts, self.edits = [], []
		self.patch(telegram_common, 'answerCallbackQuery', lambda cid, text=None: self.toasts.append(text))
		self.patch(telegram_common.TelegramBot, 'edit_text', lambda dest, mid, text, buttons=None:
			self.edits.append((dest.where, mid, text, buttons)))
		self.replies = []
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None:
			self.replies.append((dest.key, list(lines), buttons)) or [])

	def say(self, text, chat='55'):
		"""Send text in a Telegram chat: the lines of the reply."""
		self.replies.clear()
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('telegram', chat, '@u', text, BOT, 'U'))
		self.assertEqual(self.errors, [], text)
		return self.replies[-1][1] if self.replies else None

	def test_add_list_and_del(self):
		"""A job is added, listed with its number, line, state and next run (in UTC and Melbourne), and deleted."""
		added = self.say('.jobs add 29 21 * * Mon-Fri price interday')
		self.assertEqual(added, ['2. 29 21 * * Mon-Fri price interday: on, next Tue 21:29 UTC (Wed 08:29 AEDT)',
			'Added: .jobs lists them all'])
		listed = self.say('.jobs')
		self.assertEqual(listed[:3], ['<b>Jobs here:</b>', '1. */20 * * * Mon-Fri trades: on, next Tue 21:20 UTC (Wed'
			' 08:20 AEDT)', '2. 29 21 * * Mon-Fri price interday: on, next Tue 21:29 UTC (Wed 08:29 AEDT)'])
		self.assertEqual(listed[-4:], ['.jobs run [NUMBER]: run one now', '.jobs toggle [NUMBER]: switch one on or off',
			'.jobs add [CRON_TZ=ZONE] TIME REPORT: add one (.jobs add lists the reports)',
			'.jobs del NUMBER: delete one'])
		self.assertIsNone(self.replies[-1][2]) # .jobs alone has no buttons
		self.assertEqual(self.say('.jobs del 1'), ['Deleted 1. */20 * * * Mon-Fri trades'])
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {CHAT: [entry('29 21 * * Mon-Fri price interday')]})
		self.assertEqual([job.text for job in self.s.chat_jobs(CHAT)], ['price interday']) # at once, no reload
		self.assertEqual(self.say('.job del 1'), ['Deleted 1. 29 21 * * Mon-Fri price interday'])
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {})
		self.assertEqual(self.say('.jobs')[0], 'No jobs here yet: add one with .jobs add')

	def test_a_job_names_its_zone_runs_several_reports_and_quotes_its_arguments(self):
		"""A job is in UTC unless it names its zone; it may run several reports in turn, and an argument in quotes may
		hold anything."""
		url = 'https://example.com/feed?a=1&b=2;c'
		self.say(f'.jobs add CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession')
		self.say(f'.jobs add 5 4 * * * podcasts "{url}"; shorts')
		self.say('.jobs add @daily reminder')
		ny, feed, daily = self.s.chat_jobs(CHAT)[1:]
		self.assertEqual((ny.zone.key, ny.line), ('America/New_York', 'CRON_TZ=America/New_York 15 13 * * Mon-Fri'
			' price midsession'))
		self.assertEqual([(label.split()[0], kwargs) for label, _, kwargs in feed.commands],
			[('podcasts', {'feed_url': url}), ('shorts', {})])
		self.assertEqual((daily.when, daily.zone.key), ('@daily', 'UTC'))
		self.assertIn('2. CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession: on, next Wed 17:15 UTC',
			self.say('.jobs')[2])

	def test_add_alone_lists_the_reports_a_job_can_run(self):
		""".jobs add alone lists the reports with what each takes, the system jobs' aside, and examples."""
		lines = self.say('.jobs add')
		self.assertEqual(lines[0], '<b>Reports a job can run:</b>')
		for line in ('cal earnings|ex-dividend', 'performance [DAYS]', 'podcasts FEED_URL',
				'price midsession|interday|premarket|close|DAYS', 'trades'):
			self.assertIn(line, lines)
		self.assertFalse(any(name in line for line in lines for name in jobs.SYSTEM_SCRIPTS))

	def test_a_job_that_cannot_be_is_refused_saying_why(self):
		"""A time that cannot be or never comes, an unknown report, a script's file name, a system job, a bad argument,
		an unknown zone or too few fields: refused, saying why, and nothing stored."""
		for line, why in (('61 1 * * * trades', "'61 1 * * *' is no time"),
				('0 0 30 2 * trades', "'0 0 30 2 *' never comes"), ('@reboot trades', '@reboot is no time'),
				('0 1 * * * nothere', "no report 'nothere'"), ('0 1 * * * trades.py', "no report 'trades.py'"),
				('0 1 * * * yahoo_warm', "no report 'yahoo_warm'"),
				('0 1 * * * price bogus', 'price takes midsession|interday|premarket|close|DAYS'),
				('0 1 * * * trades 7', 'trades takes no arguments'),
				('CRON_TZ=Nowhere/Land 0 1 * * * trades', "no time zone 'Nowhere/Land'"),
				('0 1 * *', 'a job is five time fields')):
			with self.subTest(line=line):
				self.assertIn(why, self.say(f'.jobs add {line}')[0])
		self.assertEqual(len(self.s.chat_jobs(CHAT)), 1)

	def test_a_chat_has_thirty_jobs_at_most(self):
		"""A chat may have 30 jobs; the 31st is refused."""
		for minute in range(1, 30):
			self.s.add(CHAT, f'{minute} 1 * * * trades')
		self.assertIn('30 jobs is the most a chat may have', self.say('.jobs add 31 1 * * * trades')[0])
		self.assertEqual(len(self.s.chat_jobs(CHAT)), 30)

	def test_run_a_job_now(self):
		""".jobs run N runs job N now, posting to this chat, and says how it went; a number that is none says so."""
		self.assertEqual(self.say('.jobs run 1'), ['1. trades: done'])
		self.assertEqual((self.ran, self.dests), ([('trades', {})], [CHAT]))
		self.assertEqual(self.say('.jobs run 2'), ['no job 2: send .jobs for the list'])
		self.assertEqual(self.say('.jobs run 1', chat='56'), ['no jobs here yet: .jobs add']) # another chat's list
		self.assertEqual(self.ran, [('trades', {})])

	def test_toggle_a_job_off_and_on(self):
		""".jobs toggle N switches job N off (it no longer fires) and on again."""
		self.assertEqual(self.say('.jobs toggle 1'), ['1. */20 * * * Mon-Fri trades: off'])
		self.clock.now = at(13, 21, 20)
		self.assertEqual(self.s.due(self.clock.now), [])
		self.assertEqual(self.say('.jobs toggle 1')[0][:30], '1. */20 * * * Mon-Fri trades: ')
		self.clock.now = at(13, 21, 40)
		self.assertEqual(len(self.s.due(self.clock.now)), 1)

	def test_the_run_and_toggle_lists_have_a_button_per_job(self):
		""".jobs run and .jobs toggle list the jobs with a button each that runs it now or switches it."""
		self.s.add(CHAT, '0 22 * * * shorts')
		for action, kind in (('run', 'j'), ('toggle', 'e')):
			with self.subTest(action=action):
				self.say(f'.jobs {action}')
				lines, markup = self.replies[-1][1:]
				tap = 'Tap one to run it now' if action == 'run' else 'Tap one to switch it on or off'
				self.assertIn(tap, lines[-1])
				job = self.s.chat_jobs(CHAT)[1]
				self.assertEqual(markup[0][1], buttons.Button('2. shorts', f'{kind}|2|{jobs.checksum(job.key)}'))

	def test_a_run_button_runs_its_job_and_a_toggle_button_redraws_the_list(self):
		"""A run button runs its job and says how it went; a toggle button switches its job and redraws the list in
		place, with the buttons still there."""
		job = self.s.chat_jobs(CHAT)[0]
		self.press_button(f'j|1|{jobs.checksum(job.key)}')
		self.assertEqual((self.toasts, self.ran), (['Running…'], [('trades', {})]))
		self.assertEqual(self.replies[-1][1], ['1. trades: done'])
		self.press_button(f'e|1|{jobs.checksum(job.key)}')
		self.assertEqual(self.toasts[-1], 'Switching…')
		self.assertFalse(self.s.chat_jobs(CHAT)[0].on)
		chat, message, text, markup = self.edits[-1]
		self.assertEqual((chat, message), ('55', '9'))
		self.assertIn('1. */20 * * * Mon-Fri trades: off', text)
		self.assertEqual(markup[0][0].data, f'e|1|{jobs.checksum(job.key)}') # the key does not hold the switch

	def test_a_stale_or_forged_button_redraws_the_list_and_does_nothing(self):
		"""A button whose number or checksum is not this chat's job (an older list, another chat's, forged data) runs
		and switches nothing: the list is redrawn in its place, with that kind of buttons."""
		self.store(OTHER, '*/20 * * * Mon-Fri trades')
		self.s.load()
		good = jobs.checksum(self.s.chat_jobs(CHAT)[0].key)
		others = jobs.checksum(self.s.chat_jobs(OTHER)[0].key)
		for data in ('j|2|' + good, 'j|0|' + good, 'j|1|0000', 'j|1|' + others, 'e|1|0000', 'j|1', 'j|٨|' + good,
				'j| 1|' + good, 'e|99999999999999999999|' + good):
			with self.subTest(data=data):
				self.edits.clear()
				self.press_button(data)
				self.assertEqual(self.ran, [])
				self.assertTrue(self.s.chat_jobs(CHAT)[0].on)
				self.assertEqual(len(self.edits), 1)
				self.assertIn('1. */20 * * * Mon-Fri trades: on', self.edits[0][2])
				self.assertEqual(self.edits[0][3][0][0].data[0], data[0]) # the same kind of buttons
		self.press_button('j|1|' + good) # the genuine one still works
		self.assertEqual(self.ran, [('trades', {})])

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
						answer = bot.take(reader, updates.update(network, first, chat, '.jobs add 0 23 * * * shorts'))
						if answer.then:
							answer.then()
						self.join_workers()
						key = f'{network}:{chat}'
						self.assertEqual([job.text for job in self.s.chat_jobs(key)], ['shorts'])
						self.env(**test_sending.EveryNetworkAndMode.MODES[(network, then)])
						self.replies.clear()
						answer = bot.take(reader, updates.update(network, then, chat, '.jobs'))
						if answer.then:
							answer.then()
						self.join_workers()
					self.assertIn('1. 0 23 * * * shorts: on', self.replies[-1][1][1])
					self.assertEqual(self.replies[-1][0], key)
					self.dests.clear()
					self.s.run(self.s.chat_jobs(key)[0])
					self.assertEqual(self.dests, [key]) # posted to the same chat
					self.s.delete(self.s.chat_jobs(key)[0])


class ReportImports(FinbotCase):
	"""What importing the reports brings in."""

	def test_a_report_loads_neither_matplotlib_nor_the_scheduler(self):
		"""A report imports only its own module: price once pulled in every report, through charts and jobs, and the
		chart code until a chart is drawn."""
		code = ('import sys; from lib.reports import price, performance, trades, shorts, cal; '
			'print(sorted(m for m in ("lib.jobs", "matplotlib") if m in sys.modules))')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data})
		self.assertEqual(out.stdout.strip().splitlines()[-1:], ['[]'], out.stderr)


if __name__ == '__main__':
	unittest.main()
