"""The in-process scheduler (lib/jobs.py): firing on a fake clock, across the clocks' changes, runs from chat,
and each command in a child process."""
import contextlib, datetime, io, json, os, signal, subprocess, sys, tempfile, threading, time, unittest
import zoneinfo
from pathlib import Path
from unittest import mock
import gevent
from tests.common import *
from lib import jobs
from lib.reports import cleanup, podcasts, price, sharesight_warm, yahoo_warm

PREFETCH_HISTORY = yahoo.prefetch_history # FinbotCase replaces it; the warm job's test puts it back


def run_in_process(label, module, kwargs):
	"""The scheduler's runner in these tests: the command's handler, called here (no child process, no deadline)."""
	module.run(**kwargs)
	return 0


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
		"""The real prefetch, Yahoo answering each history with the ticker's name, except T2's, which fails."""
		super().setUp()
		self.patch(yahoo, 'prefetch_history', PREFETCH_HISTORY)
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

	def test_without_sharesight_the_watchlist_is_fetched(self):
		"""While Sharesight cannot be asked for the holdings, the watchlist's histories are fetched."""
		def unreachable():
			"""Sharesight failing, as watchlist.with_holdings meets it."""
			raise RuntimeError('Sharesight auth: down')
		self.patch(watchlist, 'with_holdings', unreachable)
		self.patch(watchlist, 'tickers', lambda: ['W1'])
		with contextlib.redirect_stderr(io.StringIO()) as log:
			self.assertEqual(yahoo_warm.run(), 1)
		self.assertEqual(cache.read('finbot_yahoo_history_W1.json'), {'history of': 'W1'})
		self.assertIn('no holdings from Sharesight', log.getvalue())

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


class SchedulerFlag(unittest.TestCase):
	def flag(self, **env):
		"""config.env.scheduler in a fresh interpreter, given `env`."""
		code = 'from lib import config; print(config.env.scheduler)'
		e = {k: v for k, v in os.environ.items() if k != 'scheduler'}
		e.update(env)
		repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		return subprocess.run([sys.executable, '-c', code], cwd=repo, env=e, capture_output=True, text=True,
			check=True).stdout.split()[-1]

	def test_on_by_default_and_off_for_false(self):
		"""The scheduler is on by default and with any true word, off with any false one."""
		self.assertEqual(self.flag(), 'True')
		for value in ('True', 'true', '1', 't'):
			self.assertEqual(self.flag(scheduler=value), 'True', value)
		for value in ('False', 'false', '0', 'no'):
			self.assertEqual(self.flag(scheduler=value), 'False', value)


class SchedulerBase(FinbotCase):
	def setUp(self):
		"""A schedule of trades.py every 20 minutes on weekdays, a fake clock; trades and shorts recorded, not run."""
		super().setUp()
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.file = Path(tmp.name, 'schedule.cron')
		self.file.write_text('*/20 * * * Mon-Fri trades.py\n')
		self.clock = Clock(at(13, 21, 3))
		self.ran = []
		self.patch(jobs.SCRIPTS['trades'], 'run', lambda **k: self.ran.append(('trades', k)))
		self.patch(jobs.SCRIPTS['shorts'], 'run', lambda **k: self.ran.append(('shorts', k)))

	def scheduler(self, catchup=5):
		"""A loaded scheduler on the fake clock that runs commands in this process, at once."""
		s = jobs.Scheduler(lambda: self.file, catchup=catchup, clock=self.clock, sleep=lambda seconds: None,
						   spawn=lambda f, *a: f(*a), zone=UTC, runner=run_in_process)
		self.assertTrue(s.load())
		return s


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

	def test_tick_runs_the_job_and_returns_the_wait(self):
		"""tick() runs what is due and returns how long to sleep: up to 30 seconds, less when the next run is nearer."""
		s = self.scheduler()
		self.clock.now = at(13, 21, 20)
		wait = s.tick()
		self.assertEqual(self.ran, [('trades', {})])
		self.assertEqual(wait, 30) # the next run is 20 minutes away: wake at most every 30 seconds
		self.clock.now = at(13, 21, 39, 50)
		self.assertEqual(s.tick(), 10)

	def test_a_run_missed_within_the_catch_up_window_fires_once(self):
		"""After a restart, a run missed within the catch-up window fires once; an older one is skipped."""
		first = self.scheduler()
		first.last = {first.jobs[0].key: at(13, 21, 0).isoformat()}
		state.save(jobs.STATE_FILE, first.last)
		self.clock.now = at(13, 21, 43)
		s = self.scheduler()
		# 21:20 is older than 5 minutes: skipped
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)])

	def test_a_corrupt_state_file_is_reported_and_the_schedule_starts_afresh(self):
		"""A state file cut off mid-write is reported once, and the schedule runs as usual and writes it afresh."""
		# cut off mid-write
		Path(config.env.data_dir, jobs.STATE_FILE).write_text('{"*/20 * * * Mon-Fri|UTC|trades.py": "2026-10-13T21:')
		s = self.scheduler()
		self.assertEqual((s.last, len(self.errors)), ({}, 1))
		self.assertIn('cannot read finbot_jobs.json', self.errors[0])
		self.clock.now = at(13, 21, 20)
		self.assertEqual(len(s.due(self.clock.now)), 1) # runs as usual, and the record is written afresh
		self.assertEqual(state.load(jobs.STATE_FILE), {s.jobs[0].key: at(13, 21, 20).isoformat()})
		s.reload() # and a reload is no trouble either
		self.assertEqual(len(self.errors), 1)

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

	def test_a_failing_job_is_reported_and_the_next_command_still_runs(self):
		"""A command that fails is reported, and the next command on its line still runs."""
		self.file.write_text('*/20 * * * * trades.py; shorts.py\n')
		def boom(**k):
			"""Fail."""
			raise RuntimeError('boom')
		self.patch(jobs.SCRIPTS['trades'], 'run', boom)
		s = self.scheduler()
		s.execute(s.jobs[0].commands)
		self.assertEqual(self.ran, [('shorts', {})])
		self.assertTrue(any('boom' in e for e in self.errors))

	def test_system_exit_inside_a_job_is_reported_not_raised(self):
		"""A SystemExit inside a job is reported, not raised, and the job is marked done."""
		def quit_(**k):
			"""Exit, as a script calling sys.exit would."""
			raise SystemExit(3)
		self.patch(jobs.SCRIPTS['trades'], 'run', quit_)
		s = self.scheduler()
		s.execute(s.jobs[0].commands)
		self.assertEqual(len(self.errors), 1)

	def test_a_command_stopped_at_its_deadline_is_reported_and_the_next_still_runs(self):
		"""A command still running at its deadline (run_child stops it) is reported, and the rest of its line runs."""
		self.file.write_text('*/20 * * * * trades.py; shorts.py\n')
		def runner(label, module, kwargs):
			"""trades.py hangs until run_child stops it; the rest run here."""
			if label == 'trades.py':
				raise TimeoutError('still running after 5 minutes')
			return run_in_process(label, module, kwargs)
		s = self.scheduler()
		s.runner = runner
		self.assertEqual(s.execute(s.jobs[0].commands), 'timed out')
		self.assertEqual(self.errors, ['⚠️ trades.py: TimeoutError: still running after 5 minutes'])
		self.assertEqual(self.ran, [('shorts', {})])
		self.assertEqual(s.busy, set())

	def test_reload_applies_edits_keeps_state_and_survives_a_bad_file(self):
		"""A reload applies edits and keeps unchanged jobs' timing; an unusable file keeps the running schedule."""
		s = self.scheduler()
		old_key = s.jobs[0].key
		base = s.base[old_key]
		self.file.write_text('*/20 * * * Mon-Fri trades.py\n5 4 * * * shorts.py\n')
		self.assertTrue(s.load())
		self.assertEqual(len(s.jobs), 2)
		self.assertEqual(s.base[old_key], base)
		self.file.write_text('# nothing usable\nnot a job\n')
		self.assertFalse(s.load())
		self.assertEqual(len(s.jobs), 2)

	def test_an_impossible_time_refuses_the_whole_file(self):
		"""A time that never comes refuses the whole file: a reload says why and the running schedule carries on."""
		s = self.scheduler()
		self.file.write_text('*/20 * * * Mon-Fri trades.py\n0 9 30 2 * shorts.py\n5 4 * * * nothere.py\n')
		with self.assertRaises(jobs.ImpossibleTime) as caught:
			s.load()
		self.assertEqual(len(caught.exception.lines), 1)
		self.assertIn("line 2: '0 9 30 2 *' never comes", caught.exception.lines[0])
		self.assertEqual(self.errors, []) # load reports nothing for a refused file...
		s.reload() # ...a reload says why it was refused, and the running schedule carries on
		self.assertEqual(len(self.errors), 1)
		self.assertIn('not reloaded, the running schedule is unchanged', self.errors[0])
		self.assertEqual([j.text for j in s.jobs], ['*/20 * * * Mon-Fri trades.py'])
		self.clock.now = at(13, 21, 20)
		self.assertEqual(len(s.due(self.clock.now)), 1)

	def test_load_reports_bad_lines_once_and_runs_the_rest(self):
		"""A bad line is reported once and the rest of the schedule runs."""
		self.file.write_text('0 1 * * * nothere.py\n*/20 * * * * trades.py\n')
		s = self.scheduler()
		self.assertEqual(len(s.jobs), 1)
		self.assertEqual(len(self.errors), 1)

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


class DaylightSaving(unittest.TestCase):
	"""Melbourne's clocks go back an hour at 03:00 on 5 April 2026 and forward at 02:00 on 4 October 2026. The fire
	times must be right on any croniter: the distro packages (up to 6.0) got zoneinfo's changes wrong."""
	MEL = zoneinfo.ZoneInfo('Australia/Melbourne')

	def fires(self, expr, start, end):
		"""When a job fires between start and end, as Melbourne times ('04 09:00 AEDT')."""
		job = jobs.parse_schedule(f'{expr} trades.py\n', self.MEL)[0][0]
		s = jobs.Scheduler(lambda: None, zone=self.MEL)
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
		"""The scheduler runs a daily Melbourne job once a day across the change to daylight time."""
		file = Path(temp_dir(self), 'schedule.cron')
		file.write_text('CRON_TZ=Australia/Melbourne\n0 9 * * * trades.py\n')
		clock = Clock(self.mel(2026, 10, 3, 12).astimezone(UTC))
		s = jobs.Scheduler(lambda: file, clock=clock, zone=UTC, runner=lambda *a: 0)
		elsewhere = dataclasses.replace(config.env, data_dir=temp_dir(self))
		with mock.patch.object(config, 'env', elsewhere), contextlib.redirect_stderr(io.StringIO()):
			self.assertTrue(s.load())
			fired = []
			while clock.now < self.mel(2026, 10, 5, 12):
				fired += [t.astimezone(UTC).astimezone(self.MEL).strftime('%d %H:%M') for _, t in s.due(clock.now)]
				clock.now += datetime.timedelta(minutes=10)
		self.assertEqual(fired, ['04 09:00', '05 09:00'])


class ManualRuns(SchedulerBase):
	def setUp(self):
		"""A schedule with repeats, comments, braces and the commands that cannot be picked (cleanup, podcasts)."""
		super().setUp()
		self.file.write_text('# a comment\n*/20 * * * Mon-Fri trades.py > /dev/null\n'
			'28 21 * * Sat price.py close; trades.py # weekly\n5 4 * * * { price.py close ;}\n6 4 * * * price.py 7\n'
			'0 3 * * * performance.py 365; performance.py 7; performance.py 90; performance.py 30; performance.py 180\n'
			'0 2 * * * cleanup.py\n1 * * * * podcasts.py "https://example.com/feed"\n')
		self.s = self.scheduler()
		self.patch(jobs, 'current', self.s)
		self.patch(jobs.SCRIPTS['price'], 'run', lambda **k: self.ran.append(('price', k)))

	def test_commands_are_unique_clean_and_in_order(self):
		"""The commands offered are each once, without redirects, sorted by name with numbers in numeric order."""
		self.assertEqual([label for label, _, _ in self.s.commands()],
			['performance.py 7', 'performance.py 30', 'performance.py 90', 'performance.py 180',
																	   'performance.py 365', 'price.py 7',
																	   'price.py close', 'trades.py'])

	def test_select_by_number_or_command_text(self):
		"""A command is picked by its number or its text, quotes, paths and redirects aside."""
		self.assertEqual(self.s.select('7')[0], 'price.py close')
		self.assertEqual(self.s.select('8')[0], 'trades.py')
		self.assertEqual(self.s.select('  "price.py" close > /dev/null')[0], 'price.py close')
		self.assertEqual(self.s.select('~/finbot/price.py 7')[0], 'price.py 7')

	def test_select_refuses_what_is_not_offered(self):
		"""Numbers out of range, cleanup, podcasts, unscheduled commands, shell syntax and two commands are refused."""
		for text in ('0', '9', 'cleanup.py', 'podcasts.py "https://example.com/feed"', 'price.py 99', 'cal.py earnings',
				'nonsense', 'ls | wc', '', 'price.py close; trades.py'):
			with self.assertRaises(jobs.ScheduleError, msg=text):
				self.s.select(text)
		with self.assertRaisesRegex(jobs.ScheduleError, '^cleanup is a system job: it runs on its schedule only$'):
			self.s.select('cleanup.py')

	def test_run_now_runs_one_command_and_leaves_the_schedule_alone(self):
		"""run_now runs one command and leaves the schedule's timing alone."""
		base, last = dict(self.s.base), dict(self.s.last)
		self.assertEqual(self.s.run_now('7'), ('price.py close', 'done'))
		self.assertEqual(self.ran, [('price', {'mode': 'close'})])
		self.assertEqual((self.s.base, self.s.last), (base, last))
		self.assertEqual(self.s.busy, set())

	def test_run_now_refuses_while_the_command_is_running_and_reports_failures(self):
		"""run_now refuses a command that is running, and reports one that fails."""
		self.s.busy.add('trades.py')
		self.assertEqual(self.s.run_now('8'), ('trades.py', 'already running'))
		self.assertEqual(self.ran, [])
		self.s.busy.clear()
		def boom(**k):
			"""Fail."""
			raise RuntimeError('boom')
		self.patch(jobs.SCRIPTS['trades'], 'run', boom)
		self.assertEqual(self.s.run_now('8'), ('trades.py', 'failed'))
		self.assertTrue(any('boom' in e for e in self.errors))
		self.assertEqual(self.s.busy, set())

	def test_a_scheduled_run_skips_a_command_that_a_manual_run_is_in_the_middle_of(self):
		"""A scheduled run skips a command still running (from chat, or the line's last run), and runs the rest of its
		line."""
		self.s.busy.add('trades.py')
		self.assertEqual(self.s.execute(self.s.jobs[1].commands), 'already running')
		self.assertEqual(self.ran, [('price', {'mode': 'close'})]) # price.py close ran, trades.py was skipped

	def test_run_now_times_out(self):
		"""A manual run stopped at its deadline says so."""
		def hang(label, module, kwargs):
			"""Hang until run_child stops it."""
			raise TimeoutError('still running after 5 minutes')
		self.s.runner = hang
		self.assertEqual(self.s.run_now('8'), ('trades.py', 'timed out'))
		self.assertEqual(self.s.busy, set())

	def test_two_runs_of_one_command_at_once_run_it_once(self):
		"""Of two runs of the same command started together, one runs it and the other is told it is running."""
		def slow(**k):
			"""Take a while, letting the other run start."""
			time.sleep(0.2)
			self.ran.append(('trades', k))
		self.patch(jobs.SCRIPTS['trades'], 'run', slow)
		outcomes = []
		threads = [threading.Thread(target=lambda: outcomes.append(self.s.run_now('8'))) for _ in range(2)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(sorted(outcomes), [('trades.py', 'already running'), ('trades.py', 'done')])
		self.assertEqual(self.ran, [('trades', {})])
		self.assertEqual(self.s.busy, set())

	def list_in_chat(self, text='.jobs'):
		"""The lines .jobs (or `text`) answers with."""
		return self.command(text)[0][1]

	def test_list_in_chat_is_just_the_commands(self):
		""".jobs and aliases number the commands, without times, comments or redirects, and mark one that is running;
		the system jobs follow under their own heading, without a number."""
		feed = jobs.display(podcasts.job(['https://example.com/feed'])[0]) # podcasts and the feed's hash
		for alias in ('.jobs', '.cron', '.crons', '.schedule', '@' + BOT.lstrip('@') + ' jobs'):
			text = '\n'.join(map(str, self.list_in_chat(alias)))
			for line in ('1. performance 7', '2. performance 30', '5. performance 365', '6. price 7', '7. price close',
					'8. trades\n\n<b>System:</b>\ncleanup\n' + feed + '\n'):
				self.assertIn(line, text, alias)
			for noise in ('*/20', '#', 'Mon-Fri', 'next', 'last', '/dev/null', 'weekly', '.py'):
				self.assertNotIn(noise, text, alias)
		self.s.busy.add('price.py 7')
		self.assertIn('6. price 7 (running)', '\n'.join(map(str, self.list_in_chat())))

	def test_a_schedule_of_system_jobs_alone_lists_them(self):
		"""A schedule of system jobs alone lists them, with nothing to run or tap."""
		self.file.write_text('0 2 * * * cleanup.py\n')
		self.patch(jobs, 'current', self.scheduler())
		self.assertEqual(about.prepare_jobs_payload(TELEGRAM, '', tappable=True), (['<b>System:</b>', 'cleanup'], None))

	def test_a_chat_that_takes_buttons_gets_one_per_command(self):
		"""Where buttons work each command gets one, whose data fits in Telegram's 64 bytes, and the list says to tap
		it; elsewhere there are none, and it does not."""
		payload, markup = about.prepare_jobs_payload(TELEGRAM, '', tappable=True)
		pressable = [b for row in markup for b in row]
		self.assertEqual([b.label for b in pressable], ['1. performance 7', '2. performance 30', '3. performance 90',
			'4. performance 180', '5. performance 365', '6. price 7', '7. price close', '8. trades'])
		for b in pressable:
			self.assertLessEqual(len(b.data.encode()), 64)
		self.assertTrue(payload[-1].endswith('or tap it'))
		payload, markup = about.prepare_jobs_payload(SLACK, '')
		self.assertIsNone(markup)
		self.assertTrue(payload[-1].endswith('.jobs run NUMBER'))

	def test_slack_gets_the_buttons_in_block_kit_and_a_stale_list_is_replaced(self):
		"""With the bot token and slackOutgoingWebhook, Slack's .jobs list carries a button per command, two to a row
		of Block Kit, and a stale button's press puts the current list in its place."""
		self.env(slackBotToken='xoxb-test', slackOutgoingWebhook='https://example.com/slack')
		self.patch(transports.Transport, 'text', REAL_TEXT)
		posts = []
		self.patch(transports.net, 'post', lambda url, **kwargs: posts.append((url, kwargs)) or
			mock.Mock(status_code=200, json=lambda: {'ok': True, 'ts': '1.5'}))
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_request(inbound.Message('slack', 'C1', '<@U1>', '.jobs', BOT, 'U'))
		url, kwargs = posts[-1]
		blocks = json.loads(kwargs['data']['blocks'])
		self.assertTrue(url.endswith('/chat.postMessage'))
		self.assertEqual([block['type'] for block in blocks], ['section'] + ['actions'] * 4)
		self.assertEqual([button['text']['text'] for button in blocks[4]['elements']], ['7. price close', '8. trades'])
		with contextlib.redirect_stderr(io.StringIO()):
			worker.process_callback(inbound.Press('slack', 't1', 'C1', '1.5', 'j|7|0000'))
		url, kwargs = posts[-1]
		self.assertTrue(url.endswith('/chat.update'))
		self.assertEqual((kwargs['data']['channel'], kwargs['data']['ts']), ('C1', '1.5'))
		self.assertEqual(len(json.loads(kwargs['data']['blocks'])), 5)
		self.assertEqual(self.ran, [])

	def test_the_chat_command_passes_the_keyboard_on(self):
		""".jobs sends its buttons with the list."""
		seen = []
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None: seen.append(buttons) or [])
		worker.process_request(inbound.Message('telegram', '55', '@u', '.jobs', BOT, 'U'))
		self.assertEqual(len(seen[0][0]), 2) # two to a row

	def test_button_press_runs_that_command(self):
		"""Pressing a command's button runs it, says so in a toast, and reports how it went."""
		sent = []
		self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: sent.append(text))
		markup = about.prepare_jobs_payload(TELEGRAM, '', tappable=True)[1]
		data = next(b.data for row in markup for b in row if b.label.startswith('7.'))
		self.sent.clear()
		worker.process_callback(inbound.Press('telegram', 'cb1', '55', '9', data))
		self.assertEqual(self.ran, [('price', {'mode': 'close'})])
		self.assertEqual(self.sent, [('text', ['7. price close: done'])])
		self.assertEqual(sent, ['Running price close…'])

	def stale_buttons(self):
		"""Capture the toast and the in-place edit that a refused button press produces."""
		self.toasts, self.edits = [], []
		self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: self.toasts.append(text))
		self.patch(transports.TelegramBot, 'edit_text', lambda dest, mid, text, buttons=None:
			self.edits.append((dest.where, mid, text, buttons)))

	def test_forged_button_data_never_runs_anything_else(self):
		"""Bad or forged button data runs nothing, refreshes buttons in place; no number picks cleanup or podcasts."""
		self.stale_buttons()
		good = jobs.checksum('trades.py')
		for data in ('j|-1|' + good, 'j|0|' + good, 'j|9|' + good, 'j|8|0000', 'j|8|', 'j|8', 'j|8|' + good + '|x',
			'j||' + good,
					 'j|٨|' + good, 'j| 8|' + good, 'j|8.0|' + good, 'j|trades.py|' + good, 'j|1|' + good,
					 'j|8|price.py close',
					 'j|8|' + good.upper() + 'x', 'j|99999999999999999999|' + good):
			self.sent.clear()
			self.toasts.clear(); self.edits.clear()
			worker.process_callback(inbound.Press('telegram', 'cb', '55', '9', data))
			self.assertEqual(self.ran, [], data)
			self.assertEqual(self.toasts, ['Buttons updated, try again'], data)
			self.assertEqual(len(self.edits), 1, data)
			self.assertEqual(self.sent, [], data) # no new message, the old one is edited
		# cleanup and podcasts are scheduled but cannot be picked, by number or by their checksum
		for label in ('cleanup.py', 'podcasts.py'):
			for n in range(1, 12):
				with self.assertRaises(jobs.ScheduleError):
					self.s.pick(str(n), jobs.checksum(label))
		worker.process_callback(inbound.Press('telegram', 'cb', '55', '9', 'j|8|' + good)) # the genuine one still works
		self.assertEqual(self.ran, [('trades', {})])

	def test_button_from_an_old_schedule_updates_the_message(self):
		"""A stale button runs nothing; the message gets the current list and buttons (scheduler off: a notice)."""
		self.stale_buttons()
		worker.process_callback(inbound.Press('telegram', 'cb1', '55', '9', 'j|7|0000'))
		worker.process_callback(inbound.Press('telegram', 'cb1', '55', '9', 'j|9|0000'))
		self.assertEqual(self.ran, [])
		self.assertEqual(self.sent, [])
		self.assertEqual(self.toasts, ['Buttons updated, try again'] * 2)
		chat, mid, text, markup = self.edits[0]
		self.assertEqual((chat, mid), ('55', '9')) # the message with the old buttons is edited in place
		self.assertIn('7. price close', text)
		self.assertEqual(markup, about.prepare_jobs_payload(TELEGRAM, '', tappable=True)[1]) # the current buttons
		self.patch(jobs, 'current', None) # scheduler off: the list is replaced by the notice and the buttons removed
		worker.process_callback(inbound.Press('telegram', 'cb1', '55', '9', 'j|7|0000'))
		self.assertEqual(self.edits[-1][2:], ('Scheduled jobs are off (scheduler=False)', [])) # no buttons left

	def test_run_in_chat(self):
		""".jobs run takes a number or a command's text."""
		self.assertEqual(self.command('.jobs run 8'), [('text', ['8. trades: done'])])
		self.assertEqual(self.ran, [('trades', {})])
		self.ran.clear()
		self.assertEqual(self.command('.cron run price close')[0][1], ['7. price close: done'])
		self.assertEqual(self.ran, [('price', {'mode': 'close'})])

	def test_run_in_chat_refusals(self):
		""".jobs run refuses an unscheduled command, an unknown number and two commands, else gives its usage."""
		self.assertIn('not in the schedule', self.list_in_chat('.jobs run cal.py earnings')[0])
		self.assertIn('no command 99', self.list_in_chat('.jobs run 99')[0])
		self.assertIn('one command at a time', self.list_in_chat('.jobs run price.py close; trades.py')[0])
		self.assertIn('Usage', self.list_in_chat('.jobs run')[0])
		self.assertIn('Usage', self.list_in_chat('.jobs bogus')[0])
		self.assertEqual(self.ran, [])

	def test_scheduler_off(self):
		"""With the scheduler off, .jobs says so."""
		self.patch(jobs, 'current', None)
		self.assertIn('off', self.list_in_chat('.jobs')[0])
		self.assertIn('off', self.list_in_chat('.jobs run 8')[0])

	def test_job_is_still_a_ticker(self):
		""".job is a ticker, not .jobs."""
		self.assertNotIn('Scheduled', str(self.command('.job')))


class ChildProcess(FinbotCase):
	"""Jobs run in their own process, so heavy work cannot hold up the bot's web server."""

	def sleeper(self, seconds):
		"""Have run_child start a process that sleeps for `seconds`, kept in self.children."""
		real = jobs.subprocess.Popen
		self.children = []
		def popen(args, **kw):
			"""Start the sleeper instead of the job."""
			self.children.append(real([sys.executable, '-c', f'import time; time.sleep({seconds})']))
			return self.children[-1]
		self.patch(jobs.subprocess, 'Popen', popen)

	def test_every_command_can_be_handed_to_a_child(self):
		"""Every shipped command's arguments survive JSON, the way they reach the child."""
		parsed, _ = jobs.parse_schedule(DEFAULT_SCHEDULE.read_text(), UTC)
		for job in parsed:
			for label, module, kwargs in job.commands:
				self.assertEqual(json.loads(json.dumps(kwargs)), kwargs, label)

	def test_a_real_child_runs_the_handler_and_reports_its_exit_status(self):
		"""A real child runs the report and exits 0, or REPORTED when it failed and said so."""
		real = jobs.subprocess.Popen
		self.patch(jobs.subprocess, 'Popen',
			lambda args, **kw: real(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw))
		with tempfile.TemporaryDirectory() as data:
			env = {'DATA_DIR': data, 'telegramBotToken': '', 'slack_webhook': '', 'discord_webhook': ''}
			with mock.patch.dict(os.environ, env):
				self.assertEqual(jobs.run_child('cleanup.py', cleanup, {}), 0)
				self.assertEqual(jobs.run_child('cleanup.py 0', cleanup, {'days': 'not a number'}),
					jobs.jobrun.REPORTED)

	def test_a_job_process_survives_a_reload_signal(self):
		"""A job process ignores SIGHUP, which systemctl kill -s HUP sends to every process of the unit."""
		with tempfile.TemporaryDirectory() as scripts, tempfile.TemporaryDirectory() as data:
			Path(scripts, 'sleeper.py').write_text(
				'import time\ndef run():\n    print("started", flush=True)\n    time.sleep(1)\n')
			env = {**os.environ, 'PYTHONPATH': scripts, 'DATA_DIR': data, 'telegramBotToken': '', 'slack_webhook': '',
				'discord_webhook': ''}
			proc = subprocess.Popen([sys.executable, '-m', 'lib.jobrun', 'sleeper', '{}'], cwd=ROOT, env=env,
				stdout=subprocess.PIPE, text=True)
			self.addCleanup(proc.kill)
			for line in proc.stdout:
				if line.strip() == 'started':
					break
			proc.send_signal(signal.SIGHUP) # what `systemctl kill -s HUP finbot` does to every process of the unit
			self.assertEqual(proc.wait(timeout=30), 0)

	def test_a_script_that_cannot_be_imported_is_reported(self):
		"""A report that cannot be imported is reported like any other failure."""
		with tempfile.TemporaryDirectory() as data:
			env = {**os.environ, 'DATA_DIR': data, 'telegramBotToken': '', 'slack_webhook': '', 'discord_webhook': ''}
			out = subprocess.run([sys.executable, '-m', 'lib.jobrun', 'nosuchscript', '{}'], cwd=ROOT, env=env,
				capture_output=True, text=True)
		self.assertEqual(out.returncode, jobs.jobrun.REPORTED, out.stderr)
		self.assertIn('⚠️ nosuchscript.py: ModuleNotFoundError', out.stderr)

	def test_scheduler_reports_a_child_that_ended_without_saying_why(self):
		"""A child killed by a signal or exiting non-zero without a report is reported by the scheduler; one that
		reported itself is not reported twice."""
		file = Path(temp_dir(self), 'schedule.cron')
		file.write_text('* * * * * trades.py\n')
		for status, reason in ((-signal.SIGHUP, 'killed by SIGHUP'), (-signal.SIGKILL, 'killed by SIGKILL'),
			(1, 'exited with status 1 without saying why'),
							   (jobs.jobrun.REPORTED, None)): # the child reported this one itself
			with self.subTest(status=status):
				self.errors.clear()
				s = jobs.Scheduler(lambda: file, zone=UTC, runner=lambda label, module, kwargs: status)
				self.assertTrue(s.load())
				self.assertEqual(s.run_now('1'), ('trades.py', 'failed'))
				self.assertEqual(self.errors, [f'⚠️ trades.py: RuntimeError: {reason}'] if reason else [])
				self.assertEqual(s.busy, set())

	def test_a_report_script_loads_neither_pandas_nor_the_scheduler(self):
		"""A job imports only its script; price once pulled in pandas and every script (via charts, reports, jobs)."""
		code = ('import sys; from lib.reports import price, performance, trades, shorts, cal; '
			'print(sorted(m for m in ("pandas", "lib.jobs", "matplotlib") if m in sys.modules))')
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
				env={**os.environ, 'DATA_DIR': data})
		self.assertEqual(out.stdout.strip().splitlines()[-1:], ['[]'], out.stderr)

	def test_the_event_loop_keeps_running_while_a_child_works(self):
		"""Waiting for a child does not stop the event loop."""
		self.sleeper(1)
		ticks = []
		def ticker():
			"""Tick five times, 0.1 seconds apart."""
			for _ in range(5):
				gevent.sleep(0.1)
				ticks.append(time.monotonic())
		greenlet = gevent.spawn(ticker)
		started = time.monotonic()
		self.assertEqual(jobs.run_child('cleanup.py', cleanup, {}), 0)
		greenlet.join()
		self.assertGreater(time.monotonic() - started, 0.9)
		self.assertEqual(len(ticks), 5) # the loop was not blocked by the child
		self.assertLess(ticks[-1] - started, 0.8)

	def test_a_child_still_running_at_its_deadline_is_stopped(self):
		"""A child still running after JOB_TIMEOUT is stopped, rather than left running, and TimeoutError raised."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.3)
		self.sleeper(30)
		started = time.monotonic()
		with self.assertRaises(TimeoutError):
			jobs.run_child('cleanup.py', cleanup, {})
		self.assertLess(time.monotonic() - started, 5)
		self.assertIsNotNone(self.children[0].poll()) # the child was stopped, not left running

	def test_another_interruption_stops_the_child_too(self):
		"""An interruption while a child runs (a greenlet killed, say) stops the child as well."""
		self.sleeper(30)
		with self.assertRaises(gevent.Timeout):
			with gevent.Timeout(0.3):
				jobs.run_child('cleanup.py', cleanup, {})
		self.assertIsNotNone(self.children[0].poll())

	def test_each_command_of_a_line_has_a_deadline_of_its_own(self):
		"""The deadline is per command (it once covered the whole line): two that each take most of it both finish."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.8)
		self.sleeper(0.5)
		file = Path(temp_dir(self), 'schedule.cron')
		file.write_text('* * * * * trades.py; shorts.py\n')
		s = jobs.Scheduler(lambda: file, zone=UTC)
		with contextlib.redirect_stderr(io.StringIO()):
			self.assertTrue(s.load())
			self.assertEqual(s.execute(s.jobs[0].commands), 'done')
		self.assertEqual(len(self.children), 2)
		self.assertEqual(self.errors, [])


if __name__ == '__main__':
	unittest.main()
