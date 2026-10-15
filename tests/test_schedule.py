"""The schedule file (lib/jobs.py): its lines parsed, each script's job(argv), and a schedule the bot refuses."""
import hashlib, io, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from tests.common import *
from lib import jobs
from lib.reports import cal, cleanup, performance, podcasts, price


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
		line = f'01 0-10,23 * * Mon-Fri podcasts.py "{url}" > ~/out 2>&1 # hourly (UTC)\n'
		parsed, errors = jobs.parse_schedule(line, UTC)
		self.assertEqual(errors, [])
		self.assertEqual(parsed[0].commands[0][2], {'feed_url': url})
		parsed, errors = jobs.parse_schedule(f"5 4 * * * podcasts.py '{url}'; shorts.py\n", UTC)
		self.assertEqual([(label[:9], kw) for label, _, kw in parsed[0].commands],
			[('podcasts.', {'feed_url': url}), ('shorts.py', {})])

	def test_unquoted_shell_syntax_is_still_refused(self):
		"""Pipes, &&, a trailing &, $(), backticks, input redirects, subshells and an unterminated quote are refused."""
		for line in ('0 1 * * * trades.py | tee x', '0 1 * * * trades.py && shorts.py & ',
			'0 1 * * * trades.py $(date)', '0 1 * * * trades.py `x`',
					 '0 1 * * * trades.py < in', '0 1 * * * (trades.py)', '0 1 * * * trades.py "unterminated'):
			parsed, errors = jobs.parse_schedule(line + '\n', UTC)
			self.assertEqual((parsed, len(errors)), ([], 1), line)

	def test_redirects_and_braces_are_dropped(self):
		"""Output redirects, braces, paths and trailing comments are dropped from a command."""
		for command in ('trades.py > /dev/null', 'trades.py >/dev/null 2>&1', 'trades.py &> /dev/null',
			'trades.py >> ~/x 2>&1',
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
		text = ('0 1 * * * ls | wc -l\n0 1 * * * price.py bogus\n0 1 * * * nothere.py\n61 1 * * * trades.py\n0 1 * *\n'
			'FOO=bar\n5 4 * * * shorts.py\n')
		parsed, errors = jobs.parse_schedule(text, UTC)
		self.assertEqual([j.expr for j in parsed], ['5 4 * * *'])
		self.assertEqual([number for number, _, _ in errors], [1, 2, 3, 4, 5, 6])

	def test_impossible_times_are_marked_and_reboot_is_just_unsupported(self):
		"""Times that never come (30 February, minute 61, month 13, @bogus) are ImpossibleTime; @reboot is only
		unsupported, and 29 February does come."""
		for line in ('0 0 30 2 * trades.py', '0 9 31 4,6,9,11 * trades.py', '61 1 * * * trades.py',
				'0 0 * 13 * trades.py', '@bogus trades.py'):
			parsed, errors = jobs.parse_schedule(line + '\n', UTC)
			self.assertEqual(parsed, [], line)
			self.assertIsInstance(errors[0][2], jobs.ImpossibleTime, line)
		parsed, errors = jobs.parse_schedule('@reboot trades.py\n0 0 29 2 * trades.py\n', UTC)
		self.assertEqual([j.expr for j in parsed], ['0 0 29 2 *']) # a leap day does come
		self.assertNotIsInstance(errors[0][2], jobs.ImpossibleTime)

	def test_cron_tz_applies_to_the_lines_below(self):
		"""CRON_TZ sets the zone of the lines below it; an unknown zone is skipped."""
		text = '1 1 * * * trades.py\nCRON_TZ=Australia/Melbourne\n2 2 * * * trades.py\nCRON_TZ=Nowhere/Land\n'
		parsed, _ = jobs.parse_schedule(text, UTC)
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
		# the label is the start of the state file's hash
		self.assertIn('finbot_podcast_seen_' + label.split()[1], podcasts.get_seen_filename(url))
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
		self.assertEqual(sorted(path.stem for path in Path(ROOT).glob('*.py') if path.stem not in ('bot',
			'bot_send_stdin')),
						 sorted(jobs.SCRIPTS))
		with tempfile.TemporaryDirectory() as data:
			run = lambda *args: subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
				timeout=60, env={**os.environ, 'DATA_DIR': data})
			self.assertEqual(run('cleanup.py', '0').returncode, 0)
			bad = run('price.py', 'bogus')
			self.assertEqual(bad.returncode, 1)
			self.assertIn('Usage: price.py [midsession', bad.stderr)


class StartupRefusal(unittest.TestCase):
	def test_the_bot_will_not_start_with_an_impossible_time(self):
		"""bot.py will not start while the schedule holds a time that never comes, and says which."""
		skip_if_old_env(self)
		with tempfile.TemporaryDirectory() as data:
			Path(data, 'schedule.cron').write_text('*/20 * * * Mon-Fri trades.py\n0 9 31 6 * price.py close\n')
			env = bare_environment()
			env.update(DATA_DIR=data, port='0')
			out = subprocess.run([sys.executable, 'bot.py'], cwd=ROOT, env=env, capture_output=True, text=True,
				timeout=120)
		self.assertEqual(out.returncode, 1, out.stderr)
		self.assertIn(f"ERROR schedule: {data}/schedule.cron line 2: '0 9 31 6 *' never comes", out.stderr)


if __name__ == '__main__':
	unittest.main()
