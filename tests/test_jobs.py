"""The in-process scheduler (lib/jobs.py): schedule file parsing, each script's job(argv), and firing with a fake clock."""
import contextlib, datetime, hashlib, io, json, os, signal, subprocess, sys, tempfile, time, unittest, zoneinfo
from pathlib import Path
from unittest import mock
import gevent
from tests.common import *
from lib import jobs
from lib.reports import cal, cleanup, performance, podcasts, price

UTC = zoneinfo.ZoneInfo('UTC')
DEFAULT_SCHEDULE = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / 'defaults' / 'schedule.cron'


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


class ParseTests(unittest.TestCase):
	def test_shipped_schedule_has_no_errors(self):
		"""defaults/schedule.cron parses without errors, its Saturday line into its five commands."""
		parsed, errors = jobs.parse_schedule(DEFAULT_SCHEDULE.read_text(), UTC)
		self.assertEqual(errors, [])
		self.assertEqual(len(parsed), 9)
		weekly = next(j for j in parsed if j.expr == '28 21 * * Sat')
		self.assertEqual([label for label, _, _ in weekly.commands],
						 ['cal.py earnings', 'cal.py ex-dividend', 'price.py 7', 'performance.py 7', 'rating.py'])

	def test_pasted_crontab_lines(self):
		"""Lines pasted from a crontab work: variables, paths, redirects, braces, comments and @daily."""
		text = ('MAILTO=me\n'
				'*/20 * * * Mon-Fri ~/finbot/trades.py > ~/finbot.trades 2>&1\n'
				'28  21 * * Sat { ./cal.py earnings; ./price.py 7 ;} &> /dev/null # weekly (UTC)\n'
				'@daily /opt/finbot/reminder.py\n')
		parsed, errors = jobs.parse_schedule(text, UTC)
		self.assertEqual(errors, [])
		self.assertEqual([[label for label, _, _ in j.commands] for j in parsed],
						 [['trades.py'], ['cal.py earnings', 'price.py 7'], ['reminder.py']])

	def test_quoted_arguments_may_hold_anything(self):
		"""A quoted argument may hold shell characters; commands after a ; still split."""
		url = 'https://example.com/feed?a=1&b=2;c>d $x |y'
		parsed, errors = jobs.parse_schedule(f'01 0-10,23 * * Mon-Fri podcasts.py "{url}" > ~/out 2>&1 # hourly (UTC)\n', UTC)
		self.assertEqual(errors, [])
		self.assertEqual(parsed[0].commands[0][2], {'feed_url': url})
		parsed, errors = jobs.parse_schedule(f"5 4 * * * podcasts.py '{url}'; shorts.py\n", UTC)
		self.assertEqual([(label[:9], kw) for label, _, kw in parsed[0].commands], [('podcasts.', {'feed_url': url}), ('shorts.py', {})])

	def test_unquoted_shell_syntax_is_still_refused(self):
		"""Pipes, &&, a trailing &, $(), backticks, input redirects, subshells and an unterminated quote are refused."""
		for line in ('0 1 * * * trades.py | tee x', '0 1 * * * trades.py && shorts.py & ', '0 1 * * * trades.py $(date)', '0 1 * * * trades.py `x`',
					 '0 1 * * * trades.py < in', '0 1 * * * (trades.py)', '0 1 * * * trades.py "unterminated'):
			parsed, errors = jobs.parse_schedule(line + '\n', UTC)
			self.assertEqual((parsed, len(errors)), ([], 1), line)

	def test_redirects_and_braces_are_dropped(self):
		"""Output redirects, braces, paths and trailing comments are dropped from a command."""
		for command in ('trades.py > /dev/null', 'trades.py >/dev/null 2>&1', 'trades.py &> /dev/null', 'trades.py >> ~/x 2>&1',
						'{ trades.py ;} > ~/x', '/opt/finbot/trades.py # note (x)'):
			parsed, errors = jobs.parse_schedule(f'0 1 * * * {command}\n', UTC)
			self.assertEqual(errors, [], command)
			self.assertEqual([label for label, _, _ in parsed[0].commands], ['trades.py'], command)

	def test_bin_run_wrapper_is_no_longer_accepted(self):
		"""The old bin/run wrapper and a cd before the command are refused."""
		for command in ('bin/run trades.py', 'cd /opt/finbot; trades.py'):
			parsed, errors = jobs.parse_schedule(f'0 1 * * * {command}\n', UTC)
			self.assertEqual((parsed, len(errors)), ([], 1), command)

	def test_bad_lines_are_skipped_and_named(self):
		"""Bad lines are skipped and reported by line number; the good ones load."""
		text = '0 1 * * * ls | wc -l\n0 1 * * * price.py bogus\n0 1 * * * nothere.py\n61 1 * * * trades.py\n0 1 * *\nFOO=bar\n5 4 * * * shorts.py\n'
		parsed, errors = jobs.parse_schedule(text, UTC)
		self.assertEqual([j.expr for j in parsed], ['5 4 * * *'])
		self.assertEqual([number for number, _, _ in errors], [1, 2, 3, 4, 5, 6])

	def test_impossible_times_are_marked_and_reboot_is_just_unsupported(self):
		"""Times that never come (30 February, minute 61, month 13, @bogus) are ImpossibleTime; @reboot is only
		unsupported, and 29 February does come."""
		for line in ('0 0 30 2 * trades.py', '0 9 31 4,6,9,11 * trades.py', '61 1 * * * trades.py', '0 0 * 13 * trades.py', '@bogus trades.py'):
			parsed, errors = jobs.parse_schedule(line + '\n', UTC)
			self.assertEqual(parsed, [], line)
			self.assertIsInstance(errors[0][2], jobs.ImpossibleTime, line)
		parsed, errors = jobs.parse_schedule('@reboot trades.py\n0 0 29 2 * trades.py\n', UTC)
		self.assertEqual([j.expr for j in parsed], ['0 0 29 2 *']) # a leap day does come
		self.assertNotIsInstance(errors[0][2], jobs.ImpossibleTime)

	def test_cron_tz_applies_to_the_lines_below(self):
		"""CRON_TZ sets the zone of the lines below it; an unknown zone is skipped."""
		parsed, _ = jobs.parse_schedule('1 1 * * * trades.py\nCRON_TZ=Australia/Melbourne\n2 2 * * * trades.py\nCRON_TZ=Nowhere/Land\n', UTC)
		self.assertEqual([j.zone.key for j in parsed], ['UTC', 'Australia/Melbourne'])

	def test_local_zone_follows_tz(self):
		"""The local zone follows TZ."""
		with mock.patch.dict(os.environ, {'TZ': 'Australia/Melbourne'}):
			self.assertEqual(jobs.local_zone().key, 'Australia/Melbourne')


class JobArguments(unittest.TestCase):
	def test_price(self):
		"""price.py takes one mode or a number of days (the top and bottom ten over it); anything else is its usage."""
		self.assertEqual(price.job(['midsession']), ('price.py midsession', {'mode': 'midsession'}))
		self.assertEqual(price.job(['premarket'])[1], {'mode': 'premarket'})
		self.assertEqual(price.job(['interday'])[1], {'mode': 'interday'})
		self.assertEqual(price.job(['close'])[1], {'mode': 'close'})
		self.assertEqual(price.job(['28']), ('price.py 28', {'mode': 'period', 'threshold': 0, 'days': 28, 'top': 10}))
		for bad in ([], ['soon'], ['7', '8']):
			with self.assertRaises(ValueError):
				price.job(bad)

	def test_cal_and_performance(self):
		"""cal.py takes earnings or ex-dividend; performance.py an optional number of days."""
		self.assertEqual(cal.job(['earnings']), ('cal.py earnings', {'event': 'earnings'}))
		self.assertEqual(cal.job(['ex-dividend']), ('cal.py ex-dividend', {'event': 'ex-dividend'}))
		self.assertEqual(performance.job([]), ('performance.py', {}))
		self.assertEqual(performance.job(['7']), ('performance.py 7', {'past_days': 7}))
		for bad, module in ((['x'], cal), ([], cal), (['x'], performance)):
			with self.assertRaises(ValueError):
				module.job(bad)

	def test_podcasts(self):
		"""podcasts.py takes one feed URL; its label carries the start of the hash that names its state file."""
		url = 'https://example.com/podcast.rss'
		label, kwargs = podcasts.job([url])
		self.assertEqual(kwargs, {'feed_url': url})
		self.assertIn('finbot_podcast_seen_' + label.split()[1], podcasts.get_seen_filename(url)) # the label is the start of the state file's hash
		self.assertEqual(label, 'podcasts.py ' + hashlib.md5(url.encode()).hexdigest()[:8])
		for bad in ([], [url, url]):
			with self.assertRaises(ValueError):
				podcasts.job(bad)

	def test_cleanup_arguments(self):
		"""cleanup.py takes an optional number of days."""
		self.assertEqual(cleanup.job([]), ('cleanup.py', {}))
		self.assertEqual(cleanup.job(['7']), ('cleanup.py 7', {'days': 7}))
		for bad in (['x'], ['1', '2']):
			with self.assertRaises(ValueError):
				cleanup.job(bad)

	def test_plain_scripts(self):
		"""The other reports take no arguments."""
		for name, module in jobs.SCRIPTS.items():
			if name not in ('cal', 'cleanup', 'performance', 'podcasts', 'price'):
				self.assertEqual(module.job([]), (name + '.py', {}))

	def test_cli_prints_usage_and_exits(self):
		"""A bad argument on the command line prints the usage and exits 1."""
		with mock.patch('sys.stderr', new_callable=io.StringIO) as err, self.assertRaises(SystemExit) as exit_:
			delivery.cli('price.py', price.job, lambda **k: None, ['bogus'])
		self.assertEqual(exit_.exception.code, 1)
		self.assertIn('Usage: price.py [midsession', err.getvalue())

	def test_cli_runs_the_handler(self):
		"""Good arguments run the report with what job() made of them."""
		calls = []
		delivery.cli('price.py', price.job, lambda **k: calls.append(k), ['midsession'])
		self.assertEqual(calls, [{'mode': 'midsession'}])

	def test_each_scheduled_report_runs_from_its_top_level_script(self):
		"""./price.py and the rest run lib/reports/<name>.py, so cron lines and runs by hand keep working."""
		self.assertEqual(sorted(path.stem for path in Path(ROOT).glob('*.py') if path.stem not in ('bot', 'bot_send_stdin')),
						 sorted(jobs.SCRIPTS))
		with tempfile.TemporaryDirectory() as data:
			run = lambda *args: subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=60,
				env={**os.environ, 'DATA_DIR': data})
			self.assertEqual(run('cleanup.py', '0').returncode, 0)
			bad = run('price.py', 'bogus')
			self.assertEqual(bad.returncode, 1)
			self.assertIn('Usage: price.py [midsession', bad.stderr)


class CleanupJob(FinbotCase):
	def test_removes_only_old_finbot_cache_files(self):
		"""cleanup deletes finbot's cache files older than the days given, not newer ones, other files or dirs."""
		folder = tempfile.mkdtemp()
		self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
		self.env(cache_dir=folder)

		old, new = time.time() - 40 * 86400, time.time() - 5 * 86400
		for name, stamp in (('finbot_old.json', old), ('finbot_new.json', new), ('other_old.json', old), ('finbot_old.png', old)):
			path = os.path.join(folder, name)
			Path(path).write_text('x')
			os.utime(path, (stamp, stamp))
		os.mkdir(os.path.join(folder, 'finbot_dir'))
		os.utime(os.path.join(folder, 'finbot_dir'), (old, old))
		self.assertEqual(cleanup.run(days=30), 2)
		self.assertEqual(sorted(os.listdir(folder)), ['finbot_dir', 'finbot_new.json', 'other_old.json'])

	def test_a_temp_file_being_written_is_left_alone(self):
		"""A flush (0 days) spares a temp file from the last minute (a write in flight) and deletes a stale one."""
		folder = tempfile.mkdtemp()
		self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
		self.env(cache_dir=folder)

		for name, stamp in (('finbot_a.json.x1.tmp', time.time() - 5), ('finbot_b.json.x2.tmp', time.time() - 40 * 86400)):
			Path(folder, name).write_text('x')
			os.utime(Path(folder, name), (stamp, stamp))
		self.assertEqual(cleanup.run(days=0), 1) # a flush: the stale one goes, the write in flight stays
		self.assertEqual(os.listdir(folder), ['finbot_a.json.x1.tmp'])

	def test_missing_cache_dir_is_fine(self):
		"""No cache dir: nothing to delete, no error."""
		self.env(cache_dir='/nonexistent/finbot-cache')

		self.assertEqual(cleanup.run(days=30), 0)


class SchedulerFlag(unittest.TestCase):
	def flag(self, **env):
		"""config.env.scheduler in a fresh interpreter, given `env`."""
		code = 'from lib import config; print(config.env.scheduler)'
		e = {k: v for k, v in os.environ.items() if k != 'scheduler'}
		e.update(env)
		repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		return subprocess.run([sys.executable, '-c', code], cwd=repo, env=e, capture_output=True, text=True, check=True).stdout.split()[-1]

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
						   spawn=lambda f, *a: f(*a), zone=UTC, runner=jobs.run_in_process)
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
		self.assertEqual([t for _, t in s.due(self.clock.now)], [at(13, 21, 40)]) # 21:20 is older than 5 minutes: skipped

	def test_a_corrupt_state_file_is_reported_and_the_schedule_starts_afresh(self):
		"""A state file cut off mid-write is reported once, and the schedule runs as usual and writes it afresh."""
		Path(config.env.data_dir, jobs.STATE_FILE).write_text('{"*/20 * * * Mon-Fri|UTC|trades.py": "2026-10-13T21:') # cut off mid-write
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

	def test_an_overlapping_run_is_skipped(self):
		"""A run due while the last is still going is skipped."""
		s = self.scheduler()
		s.jobs[0].running = True
		s.run_job(s.jobs[0], at(13, 21, 20))
		self.assertEqual(self.ran, [])
		s.jobs[0].running = False
		s.run_job(s.jobs[0], at(13, 21, 20))
		self.assertEqual(self.ran, [('trades', {})])
		self.assertFalse(s.jobs[0].running)

	def test_a_failing_job_is_reported_and_the_next_command_still_runs(self):
		"""A command that fails is reported, and the next command on its line still runs."""
		self.file.write_text('*/20 * * * * trades.py; shorts.py\n')
		def boom(**k):
			"""Fail."""
			raise RuntimeError('boom')
		self.patch(jobs.SCRIPTS['trades'], 'run', boom)
		s = self.scheduler()
		s.run_job(s.jobs[0], at(13, 21, 20))
		self.assertEqual(self.ran, [('shorts', {})])
		self.assertTrue(any('boom' in e for e in self.errors))

	def test_system_exit_inside_a_job_is_reported_not_raised(self):
		"""A SystemExit inside a job is reported, not raised, and the job is marked done."""
		def quit_(**k):
			"""Exit, as a script calling sys.exit would."""
			raise SystemExit(3)
		self.patch(jobs.SCRIPTS['trades'], 'run', quit_)
		s = self.scheduler()
		s.run_job(s.jobs[0], at(13, 21, 20))
		self.assertEqual(len(self.errors), 1)
		self.assertFalse(s.jobs[0].running)

	def test_a_job_that_hangs_is_abandoned_and_reported(self):
		"""A job that runs past the timeout is abandoned and reported."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.05)
		self.patch(jobs.SCRIPTS['trades'], 'run', lambda **k: gevent.sleep(5))
		s = self.scheduler()
		s.run_job(s.jobs[0], at(13, 21, 20))
		self.assertTrue(any('still running' in e for e in self.errors))
		self.assertFalse(s.jobs[0].running)

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
	"""Melbourne's clocks go back an hour at 03:00 on 5 April 2026 and forward at 02:00 on 4 October 2026. The fire times must be
	right on any croniter: the distro packages (up to 6.0) got zoneinfo's changes wrong."""
	MEL = zoneinfo.ZoneInfo('Australia/Melbourne')

	def fires(self, expr, start, end):
		"""When a job fires between start and end, as Melbourne times ('04 09:00 AEDT')."""
		job = jobs.parse_schedule(f'{expr} trades.py\n', self.MEL)[0][0]
		s = jobs.Scheduler(lambda: None, zone=self.MEL)
		times, t = [], start
		while (t := s.next_fire(job, t)) <= end:
			times.append(t.astimezone(UTC).astimezone(self.MEL).strftime('%d %H:%M %Z')) # by way of UTC: the real local time
		return times

	def mel(self, *args, **kw):
		"""A Melbourne time."""
		return datetime.datetime(*args, tzinfo=self.MEL, **kw)

	def test_a_daily_job_fires_once_at_its_time(self):
		"""A daily job fires at its local time each day across both changes."""
		self.assertEqual(self.fires('0 9 * * *', self.mel(2026, 10, 2), self.mel(2026, 10, 6)), ['02 09:00 AEST', '03 09:00 AEST', '04 09:00 AEDT', '05 09:00 AEDT'])
		self.assertEqual(self.fires('0 9 * * *', self.mel(2026, 4, 3), self.mel(2026, 4, 7)), ['03 09:00 AEDT', '04 09:00 AEDT', '05 09:00 AEST', '06 09:00 AEST'])

	def test_a_skipped_or_repeated_time_fires_once(self):
		"""A time the clocks skip fires an hour later, and a repeated one fires once."""
		self.assertEqual(self.fires('30 2 * * *', self.mel(2026, 10, 3), self.mel(2026, 10, 6)), ['03 02:30 AEST', '04 03:30 AEDT', '05 02:30 AEDT'])
		self.assertEqual(self.fires('30 2 * * *', self.mel(2026, 4, 4), self.mel(2026, 4, 7)), ['04 02:30 AEDT', '05 02:30 AEDT', '06 02:30 AEST'])
		self.assertEqual(self.fires('*/20 * * * *', self.mel(2026, 10, 4, 1, 30), self.mel(2026, 10, 4, 3, 50)), ['04 01:40 AEST', '04 03:00 AEDT', '04 03:20 AEDT', '04 03:40 AEDT'])
		self.assertEqual(self.fires('*/20 * * * *', self.mel(2026, 4, 5, 1, 30), self.mel(2026, 4, 5, 3, 30)),
						 ['05 01:40 AEDT', '05 02:00 AEDT', '05 02:20 AEDT', '05 02:40 AEDT', '05 03:00 AEST', '05 03:20 AEST'])

	def test_starting_in_the_repeated_hour_runs_nothing_twice(self):
		"""Starting during the repeated hour runs nothing twice."""
		second_time_round = self.mel(2026, 4, 5, 2, 10, fold=1).astimezone(UTC)
		self.assertEqual(self.fires('*/20 * * * *', second_time_round, self.mel(2026, 4, 5, 3, 0, 30)), ['05 03:00 AEST'])
		self.assertEqual(self.fires('30 2 * * *', second_time_round, self.mel(2026, 4, 6, 12)), ['06 02:30 AEST'])

	def test_the_scheduler_runs_a_daily_job_once_across_the_change(self):
		"""The scheduler runs a daily Melbourne job once a day across the change to daylight time."""
		file = Path(tempfile.mkdtemp(), 'schedule.cron')
		file.write_text('CRON_TZ=Australia/Melbourne\n0 9 * * * trades.py\n')
		clock = Clock(self.mel(2026, 10, 3, 12).astimezone(UTC))
		s = jobs.Scheduler(lambda: file, clock=clock, zone=UTC, runner=lambda *a: 0)
		with mock.patch.object(config, 'env', dataclasses.replace(config.env, data_dir=tempfile.mkdtemp())), contextlib.redirect_stderr(io.StringIO()):
			self.assertTrue(s.load())
			fired = []
			while clock.now < self.mel(2026, 10, 5, 12):
				fired += [t.astimezone(UTC).astimezone(self.MEL).strftime('%d %H:%M') for _, t in s.due(clock.now)]
				clock.now += datetime.timedelta(minutes=10)
		self.assertEqual(fired, ['04 09:00', '05 09:00'])


class StartupRefusal(unittest.TestCase):
	def test_the_bot_will_not_start_with_an_impossible_time(self):
		"""bot.py will not start while the schedule holds a time that never comes, and says which."""
		skip_if_old_env(self)
		with tempfile.TemporaryDirectory() as data:
			Path(data, 'schedule.cron').write_text('*/20 * * * Mon-Fri trades.py\n0 9 31 6 * price.py close\n')
			env = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k not in config.STARTUP_KEYS}
			env.update(DATA_DIR=data, port='0')
			out = subprocess.run([sys.executable, 'bot.py'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
		self.assertEqual(out.returncode, 1, out.stderr)
		self.assertIn(f"ERROR schedule: {data}/schedule.cron line 2: '0 9 31 6 *' never comes", out.stderr)


class ManualRuns(SchedulerBase):
	def setUp(self):
		"""A schedule with repeats, comments, braces and the commands that cannot be picked (cleanup, podcasts)."""
		super().setUp()
		self.file.write_text('# a comment\n*/20 * * * Mon-Fri trades.py > /dev/null\n28 21 * * Sat price.py close; trades.py # weekly\n'
							 '5 4 * * * { price.py close ;}\n6 4 * * * price.py 7\n'
							 '0 3 * * * performance.py 365; performance.py 7; performance.py 90; performance.py 30; performance.py 180\n'
							 '0 2 * * * cleanup.py\n1 * * * * podcasts.py "https://example.com/feed"\n')
		self.s = self.scheduler()
		self.patch(jobs, 'current', self.s)
		self.patch(jobs.SCRIPTS['price'], 'run', lambda **k: self.ran.append(('price', k)))

	def test_commands_are_unique_clean_and_in_order(self):
		"""The commands offered are each once, without redirects, sorted by name with numbers in numeric order."""
		self.assertEqual([label for label, _, _ in self.s.commands()], ['performance.py 7', 'performance.py 30', 'performance.py 90', 'performance.py 180',
																	   'performance.py 365', 'price.py 7', 'price.py close', 'trades.py'])

	def test_select_by_number_or_command_text(self):
		"""A command is picked by its number or its text, quotes, paths and redirects aside."""
		self.assertEqual(self.s.select('7')[0], 'price.py close')
		self.assertEqual(self.s.select('8')[0], 'trades.py')
		self.assertEqual(self.s.select('  "price.py" close > /dev/null')[0], 'price.py close')
		self.assertEqual(self.s.select('~/finbot/price.py 7')[0], 'price.py 7')

	def test_select_refuses_what_is_not_offered(self):
		"""Numbers out of range, cleanup, podcasts, unscheduled commands, shell syntax and two commands are refused."""
		for text in ('0', '9', 'cleanup.py', 'podcasts.py "https://example.com/feed"', 'price.py 99', 'cal.py earnings', 'nonsense', 'ls | wc', '', 'price.py close; trades.py'):
			with self.assertRaises(jobs.ScheduleError, msg=text):
				self.s.select(text)

	def test_run_now_runs_one_command_and_leaves_the_schedule_alone(self):
		"""run_now runs one command and leaves the schedule's timing alone."""
		base, last = dict(self.s.base), dict(self.s.last)
		self.assertEqual(self.s.run_now('7'), ('price.py close', 'done'))
		self.assertEqual(self.ran, [('price', {'mode': 'close'})])
		self.assertEqual((self.s.base, self.s.last), (base, last))
		self.assertTrue(all(not job.running for job in self.s.jobs))
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
		"""A scheduled run skips a command a manual run is in the middle of, and runs the rest of its line."""
		self.s.busy.add('trades.py')
		self.assertEqual(self.s.run_job(self.s.jobs[1], at(13, 21, 28)), 'already running')
		self.assertEqual(self.ran, [('price', {'mode': 'close'})]) # price.py close ran, trades.py was skipped

	def test_run_now_times_out(self):
		"""A manual run past the timeout says so."""
		self.patch(jobs, 'JOB_TIMEOUT', 0.05)
		self.patch(jobs.SCRIPTS['trades'], 'run', lambda **k: gevent.sleep(5))
		self.assertEqual(self.s.run_now('8'), ('trades.py', 'timed out'))
		self.assertEqual(self.s.busy, set())

	def list_in_chat(self, text='.jobs'):
		"""The lines .jobs (or `text`) answers with."""
		return self.command(text)[0][1]

	def test_list_in_chat_is_just_the_commands(self):
		""".jobs and aliases number the commands, without times, comments or redirects, and mark one that is running."""
		for alias in ('.jobs', '.cron', '.crons', '.schedule', '@' + BOT.lstrip('@') + ' jobs'):
			text = '\n'.join(map(str, self.list_in_chat(alias)))
			for line in ('1. performance 7', '2. performance 30', '5. performance 365', '6. price 7', '7. price close', '8. trades'):
				self.assertIn(line, text, alias)
			for noise in ('*/20', '#', 'Mon-Fri', 'next', 'last', '/dev/null', 'weekly', '.py', 'cleanup', 'podcasts'):
				self.assertNotIn(noise, text, alias)
		self.s.busy.add('price.py 7')
		self.assertIn('6. price 7 (running)', '\n'.join(map(str, self.list_in_chat())))

	def test_telegram_gets_a_button_per_command_and_slack_does_not(self):
		"""On Telegram each command gets a button whose data fits in 64 bytes; Slack gets none."""
		payload, markup = about.prepare_jobs_payload(TELEGRAM, '')
		pressable = [b for row in markup for b in row]
		self.assertEqual([b.label for b in pressable], ['1. performance 7', '2. performance 30', '3. performance 90',
			'4. performance 180', '5. performance 365', '6. price 7', '7. price close', '8. trades'])
		for b in pressable:
			self.assertLessEqual(len(b.data.encode()), 64)
		payload, markup = about.prepare_jobs_payload(SLACK, '')
		self.assertIsNone(markup)

	def test_the_chat_command_passes_the_keyboard_on(self):
		""".jobs sends its buttons with the list."""
		seen = []
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None: seen.append(buttons) or [])
		worker.process_request('telegram', '55', '@u', '.jobs', BOT, 'U')
		self.assertEqual(len(seen[0][0]), 2) # two to a row

	def test_button_press_runs_that_command(self):
		"""Pressing a command's button runs it, says so in a toast, and reports how it went."""
		sent = []
		self.patch(telegram, 'answerCallbackQuery', lambda cid, text=None: sent.append(text))
		markup = about.prepare_jobs_payload(TELEGRAM, '')[1]
		data = next(b.data for row in markup for b in row if b.label.startswith('7.'))
		self.sent.clear()
		worker.process_callback('telegram', 'cb1', '55', '9', data)
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
		for data in ('j|-1|' + good, 'j|0|' + good, 'j|9|' + good, 'j|8|0000', 'j|8|', 'j|8', 'j|8|' + good + '|x', 'j||' + good,
					 'j|٨|' + good, 'j| 8|' + good, 'j|8.0|' + good, 'j|trades.py|' + good, 'j|1|' + good, 'j|8|price.py close',
					 'j|8|' + good.upper() + 'x', 'j|99999999999999999999|' + good):
			self.sent.clear()
			self.toasts.clear(); self.edits.clear()
			worker.process_callback('telegram', 'cb', '55', '9', data)
			self.assertEqual(self.ran, [], data)
			self.assertEqual(self.toasts, ['Buttons updated, try again'], data)
			self.assertEqual(len(self.edits), 1, data)
			self.assertEqual(self.sent, [], data) # no new message, the old one is edited
		# cleanup and podcasts are scheduled but cannot be picked, by number or by their checksum
		for label in ('cleanup.py', 'podcasts.py'):
			for n in range(1, 12):
				with self.assertRaises(jobs.ScheduleError):
					self.s.pick(str(n), jobs.checksum(label))
		worker.process_callback('telegram', 'cb', '55', '9', 'j|8|' + good) # the genuine button still works
		self.assertEqual(self.ran, [('trades', {})])

	def test_button_from_an_old_schedule_updates_the_message(self):
		"""A stale button runs nothing; the message gets the current list and buttons (scheduler off: a notice)."""
		self.stale_buttons()
		worker.process_callback('telegram', 'cb1', '55', '9', 'j|7|0000')
		worker.process_callback('telegram', 'cb1', '55', '9', 'j|9|0000')
		self.assertEqual(self.ran, [])
		self.assertEqual(self.sent, [])
		self.assertEqual(self.toasts, ['Buttons updated, try again'] * 2)
		chat, mid, text, markup = self.edits[0]
		self.assertEqual((chat, mid), ('55', '9')) # the message with the old buttons is edited in place
		self.assertIn('7. price close', text)
		self.assertEqual(markup, about.prepare_jobs_payload(TELEGRAM, '')[1]) # with the current buttons
		self.patch(jobs, 'current', None) # scheduler off: the list is replaced by the notice and the buttons removed
		worker.process_callback('telegram', 'cb1', '55', '9', 'j|7|0000')
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
		self.patch(jobs.subprocess, 'Popen', lambda args, **kw: real(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw))
		with tempfile.TemporaryDirectory() as data:
			env = {'DATA_DIR': data, 'telegramBotToken': '', 'slack_webhook': '', 'discord_webhook': ''}
			with mock.patch.dict(os.environ, env):
				self.assertEqual(jobs.run_child('cleanup.py', cleanup, {}), 0)
				self.assertEqual(jobs.run_child('cleanup.py 0', cleanup, {'days': 'not a number'}), jobs.jobrun.REPORTED)

	def test_a_job_process_survives_a_reload_signal(self):
		"""A job process ignores SIGHUP, which systemctl kill -s HUP sends to every process of the unit."""
		with tempfile.TemporaryDirectory() as scripts, tempfile.TemporaryDirectory() as data:
			Path(scripts, 'sleeper.py').write_text(
				'import time\ndef run():\n    print("started", flush=True)\n    time.sleep(1)\n')
			env = {**os.environ, 'PYTHONPATH': scripts, 'DATA_DIR': data, 'telegramBotToken': '', 'slack_webhook': '', 'discord_webhook': ''}
			proc = subprocess.Popen([sys.executable, '-m', 'lib.jobrun', 'sleeper', '{}'], cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)
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
			out = subprocess.run([sys.executable, '-m', 'lib.jobrun', 'nosuchscript', '{}'], cwd=ROOT, env=env, capture_output=True, text=True)
		self.assertEqual(out.returncode, jobs.jobrun.REPORTED, out.stderr)
		self.assertIn('⚠️ nosuchscript.py: ModuleNotFoundError', out.stderr)

	def test_scheduler_reports_a_child_that_ended_without_saying_why(self):
		"""A child killed by a signal or exiting non-zero without a report is reported by the scheduler; one that
		reported itself is not reported twice."""
		file = Path(tempfile.mkdtemp(), 'schedule.cron')
		file.write_text('* * * * * trades.py\n')
		for status, reason in ((-signal.SIGHUP, 'killed by SIGHUP'), (-signal.SIGKILL, 'killed by SIGKILL'), (1, 'exited with status 1 without saying why'),
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
		code = 'import sys; from lib.reports import price, performance, trades, shorts, cal; print(sorted(m for m in ("pandas", "lib.jobs", "matplotlib") if m in sys.modules))'
		with tempfile.TemporaryDirectory() as data:
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, env={**os.environ, 'DATA_DIR': data})
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

	def test_a_timeout_kills_the_child(self):
		"""A timeout stops the child, rather than leaving it running."""
		self.sleeper(30)
		started = time.monotonic()
		with self.assertRaises(gevent.Timeout):
			with gevent.Timeout(0.3):
				jobs.run_child('cleanup.py', cleanup, {})
		self.assertLess(time.monotonic() - started, 5)
		self.assertIsNotNone(self.children[0].poll()) # the child was stopped, not left running



if __name__ == '__main__':
	unittest.main()
