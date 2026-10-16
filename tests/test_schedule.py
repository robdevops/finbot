"""Jobs as .jobs add takes them (lib/jobs.py): their lines, and each report's job(argv); and the one-time migration
(lib/migrate.py) of the old schedule.cron, and of the reports' records, to the home chats."""
import contextlib, hashlib, io, os, unittest
from pathlib import Path
from unittest import mock
from tests.common import *
from lib import jobs, migrate, state, watchlist, worker
from lib.reports import cal, cleanup, milestone, performance, podcasts, price, rating, trades

LOCAL_ZONE = migrate.local_zone # the real one: the migration tests put UTC in its place


class JobLines(unittest.TestCase):
	def test_a_job_is_a_time_then_its_reports(self):
		"""A job is five time fields, or an @macro, then one or more reports with their arguments, separated by ";";
		it is on, in UTC, and its reports are kept as written."""
		job = jobs.parse_job('28  21 * * Sat cal earnings; cal ex-dividend;price 7 ; performance 7; rating')
		self.assertEqual((job.when, job.zone.key, job.on, job.chat), ('28 21 * * Sat', 'UTC', True, ''))
		self.assertEqual([label for label, _, _ in job.commands],
			['cal earnings', 'cal ex-dividend', 'price 7', 'performance 7', 'rating'])
		self.assertEqual(job.text, 'cal earnings; cal ex-dividend;price 7 ; performance 7; rating')
		self.assertEqual(job.line, '28 21 * * Sat ' + job.text)
		self.assertEqual(jobs.parse_job('@daily reminder', 'telegram:1').when, '@daily')

	def test_a_job_may_name_its_zone_first(self):
		"""A job may name its zone, as crontab writes it, to follow that market's clocks; its line keeps it."""
		job = jobs.parse_job('CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession')
		self.assertEqual((job.zone.key, job.when, job.text),
			('America/New_York', '15 13 * * Mon-Fri', 'price midsession'))
		self.assertEqual(job.line, 'CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession')
		for zone in ('Nowhere/Land', '', '../etc/passwd'):
			with self.subTest(zone=zone), self.assertRaisesRegex(jobs.ScheduleError, 'no time zone'):
				jobs.parse_job(f'CRON_TZ={zone} 0 1 * * * trades')

	def test_quoted_arguments_may_hold_anything(self):
		"""An argument in quotes may hold anything, a ";" included; commands after a ";" outside quotes still split."""
		url = 'https://example.com/feed?a=1&b=2;c>d $x |y'
		for quoted in (f'"{url}"', f"'{url}'"):
			job = jobs.parse_job(f'5 4 * * * podcasts {quoted}; shorts')
			self.assertEqual([(label.split()[0], kwargs) for label, _, kwargs in job.commands],
				[('podcasts', {'feed_url': url}), ('shorts', {})])
		with self.assertRaisesRegex(jobs.ScheduleError, 'No closing quotation'):
			jobs.parse_job('5 4 * * * podcasts "https://example.com')

	def test_shell_syntax_is_only_words_that_no_report_takes(self):
		"""Nothing runs a shell: pipes, redirects, $() and comments are mere words, which no report takes."""
		for line in ('0 1 * * * trades | tee x', '0 1 * * * trades > /dev/null', '0 1 * * * trades $(date)',
				'0 1 * * * trades && shorts', '0 1 * * * trades # a note'):
			with self.subTest(line=line), self.assertRaisesRegex(jobs.ScheduleError, 'trades takes no arguments'):
				jobs.parse_job(line)

	def test_a_time_that_cannot_be_or_never_comes(self):
		"""A time that cannot be (minute 61, month 13, @bogus) or never comes (30 February) is ImpossibleTime, and so is
		@reboot; 29 February does come."""
		for when, why in (('0 0 30 2 *', 'never comes'), ('0 9 31 4,6,9,11 *', 'never comes'),
				('61 1 * * *', 'is no time'), ('0 0 * 13 *', 'is no time'), ('@bogus', 'is no time'),
				('@reboot', 'the jobs start with the bot')):
			with self.subTest(when=when), self.assertRaisesRegex(jobs.ImpossibleTime, why):
				jobs.parse_job(f'{when} trades')
		self.assertEqual(jobs.parse_job('0 0 29 2 * trades').when, '0 0 29 2 *')

	def test_what_is_no_report(self):
		"""A job runs reports by name: not a script's file, not a system job's (except as one), not a report that is
		not there; with arguments it takes, and with at least one report."""
		for line, why in (('0 1 * * * nothere', "no report 'nothere'"),
				('0 1 * * * trades.py', "no report 'trades.py'"),
				('0 1 * * * ./trades', "no report './trades'"), ('0 1 * * * yahoo_warm', "no report 'yahoo_warm'"),
				('0 1 * * * cleanup 30', "no report 'cleanup'"), ('0 1 * * * trades; nothere', "no report 'nothere'"),
				('0 1 * * * price soon', 'price takes midsession|interday|premarket|close|DAYS'),
				('0 1 * * * ;', 'no report: send .jobs add'), ('0 1 * * *', 'a job is five time fields'),
				('trades', 'a job is five time fields')):
			with self.subTest(line=line), self.assertRaisesRegex(jobs.ScheduleError, why):
				jobs.parse_job(line)
		self.assertEqual(jobs.parse_job('51 18 * * Sat cleanup 30', system=True).commands[0][2], {'days': 30})


class JobArguments(unittest.TestCase):
	def test_price(self):
		"""price takes one mode or a number of days (the top and bottom ten over it); anything else is its usage."""
		self.assertEqual(price.job(['midsession']), ('price midsession', {'mode': 'midsession'}))
		self.assertEqual(price.job(['premarket'])[1], {'mode': 'premarket'})
		self.assertEqual(price.job(['interday'])[1], {'mode': 'interday'})
		self.assertEqual(price.job(['close'])[1], {'mode': 'close'})
		self.assertEqual(price.job(['28']), ('price 28', {'mode': 'period', 'threshold': 0, 'days': 28, 'top': 10}))
		for bad in ([], ['soon'], ['7', '8']):
			with self.assertRaisesRegex(ValueError, price.ARGUMENTS.replace('|', r'\|')):
				price.job(bad)

	def test_cal_and_performance(self):
		"""cal takes earnings or ex-dividend; performance an optional number of days."""
		self.assertEqual(cal.job(['earnings']), ('cal earnings', {'event': 'earnings'}))
		self.assertEqual(cal.job(['ex-dividend']), ('cal ex-dividend', {'event': 'ex-dividend'}))
		self.assertEqual(performance.job([]), ('performance', {}))
		self.assertEqual(performance.job(['7']), ('performance 7', {'past_days': 7}))
		for bad, module in ((['x'], cal), ([], cal), (['x'], performance)):
			with self.assertRaises(ValueError):
				module.job(bad)

	def test_podcasts(self):
		"""podcasts takes one feed URL; its label carries the start of the hash that names its seen file."""
		url = 'https://example.com/podcast.rss'
		label, kwargs = podcasts.job([url])
		self.assertEqual(kwargs, {'feed_url': url})
		self.assertIn('finbot_podcast_seen_' + label.split()[1], podcasts.get_seen_filename(url))
		self.assertEqual(label, 'podcasts ' + hashlib.md5(url.encode()).hexdigest()[:8])
		for bad in ([], [url, url]):
			with self.assertRaises(ValueError):
				podcasts.job(bad)

	def test_cleanup_arguments(self):
		"""cleanup takes an optional number of days."""
		self.assertEqual(cleanup.job([]), ('cleanup', {}))
		self.assertEqual(cleanup.job(['7']), ('cleanup 7', {'days': 7}))
		for bad in (['x'], ['1', '2']):
			with self.assertRaises(ValueError):
				cleanup.job(bad)

	def test_plain_reports(self):
		"""The other reports take no arguments, and say so: their ARGUMENTS, which .jobs add lists, are empty."""
		for name, module in jobs.SCRIPTS.items():
			with self.subTest(name=name):
				self.assertIsInstance(module.ARGUMENTS, str)
				if name not in ('cal', 'cleanup', 'performance', 'podcasts', 'price'):
					self.assertEqual((module.job([]), module.ARGUMENTS), ((name, {}), ''))
					with self.assertRaisesRegex(ValueError, 'no arguments'):
						module.job(['7'])

	def test_the_checkout_holds_only_the_bot_at_its_top(self):
		"""The scheduled reports run in the bot (and `.jobs run`), so the checkout's top holds bot.py alone: the scripts
		that ran each report from cron are gone."""
		self.assertEqual(sorted(path.name for path in Path(ROOT).glob('*.py')), ['bot.py'])


class Migration(FinbotCase):
	"""As finbot first starts with jobs per chat, the home chats get what was kept for all chats, once."""

	def setUp(self):
		"""Two home chats, Telegram's and Slack's; the old schedule ran in UTC."""
		super().setUp()
		self.env(slackBotToken='xoxb-1', slackChannelID='C1')
		self.patch(migrate, 'local_zone', lambda: jobs.UTC)

	def migrate(self):
		"""Run the migration, as finbot does as it starts: what it logs."""
		with contextlib.redirect_stderr(io.StringIO()) as log:
			migrate.run()
		return log.getvalue()

	def test_the_old_schedule_becomes_each_home_chats_jobs_once(self):
		"""Each home chat gets the old schedule's jobs (the data dir's copy), pasted crontab syntax read as cron read
		it, each in the zone it ran in, without the system jobs; a line that cannot be a job is logged and left out.
		Then the old file is read no more."""
		url = 'https://example.com/feed?a=1&b=2'
		Path(config.env.data_dir, 'schedule.cron').write_text('MAILTO=me\n'
			'*/20 * * * Mon-Fri ~/finbot/trades.py > ~/finbot.trades 2>&1\n'
			'28  21 * * Sat { ./cal.py earnings; ./price.py 7 ;} &> /dev/null # weekly\n'
			'@daily /opt/finbot/reminder.py\n'
			'CRON_TZ=Australia/Melbourne\n'
			'14,44 * * * * sharesight_warm.py\n'
			f'01 * * * * podcasts.py "{url}"; cleanup.py 30\n'
			'0 1 * * * ls | wc -l\n'
			'0 9 31 6 * price.py close\n'
			'0 2 * * * bin/run trades.py\n')
		log = self.migrate()
		jobs_each = [{'when': '*/20 * * * Mon-Fri', 'reports': 'trades', 'zone': 'UTC', 'on': True},
			{'when': '28 21 * * Sat', 'reports': 'cal earnings; price 7', 'zone': 'UTC', 'on': True},
			{'when': '@daily', 'reports': 'reminder', 'zone': 'UTC', 'on': True},
			{'when': '01 * * * *', 'reports': f"podcasts '{url}'", 'zone': 'Australia/Melbourne', 'on': True}]
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {'telegram:1': jobs_each, 'slack:C1': jobs_each})
		path = config.env.data_dir + '/schedule.cron'
		self.assertEqual([line for line in log.splitlines() if 'left out' in line], [
			f'schedule: {path} line 8 left out: only finbot scripts can be scheduled, not shell commands',
			f"schedule: {path} line 9 left out: '0 9 31 6 *' never comes: no date matches it",
			f"schedule: {path} line 10 left out: no report 'run': send .jobs add for the reports and what each takes"])
		self.assertIn(f"schedule: the 4 jobs of {path} are now each home chat's (telegram:1, slack:C1)", log)
		s = jobs.Scheduler()
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
		self.assertEqual([job.line for job in s.chat_jobs('slack:C1')][-1], f"CRON_TZ=Australia/Melbourne 01 * * * *"
			f" podcasts '{url}'")
		Path(config.env.data_dir, 'schedule.cron').write_text('0 3 * * * shorts.py\n') # read no more
		self.assertEqual(self.migrate(), '')
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {'telegram:1': jobs_each, 'slack:C1': jobs_each})

	def test_the_shipped_schedule_migrates_whole(self):
		"""Without a copy in the data dir, the home chats get the shipped schedule's jobs, every line of it but the
		system jobs', the weekly line's five reports among them."""
		self.assertNotIn('left out', self.migrate())
		entries = state.load(jobs.SCHEDULE_FILE)['telegram:1']
		self.assertEqual(len(entries), 8)
		self.assertIn({'when': '28 21 * * Sat', 'reports': 'cal earnings; cal ex-dividend; price 7; performance 7;'
			' rating', 'zone': 'UTC', 'on': True}, entries)
		self.assertFalse(any(name in entry['reports'] for entry in entries for name in jobs.SYSTEM_SCRIPTS))

	def test_an_empty_schedule_migrates_to_no_jobs_and_is_done(self):
		"""A schedule with no jobs gives the home chats none, and the migration is still done: it is not tried again."""
		Path(config.env.data_dir, 'schedule.cron').write_text('# nothing\n14,44 * * * * sharesight_warm.py\n')
		self.migrate()
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {})
		Path(config.env.data_dir, 'schedule.cron').write_text('0 3 * * * shorts.py\n')
		self.assertEqual(self.migrate(), '')
		self.assertEqual(state.load(jobs.SCHEDULE_FILE), {})

	def test_with_no_home_chat_it_waits(self):
		"""With no home chat set there is nowhere to put the jobs and records, so the migration waits for one."""
		self.env(telegramChatID='', slackChannelID='')
		state.save(trades.STATE_FILE, ['t1'])
		self.assertEqual(self.migrate(), '')
		self.assertFalse(os.path.exists(state.path(jobs.SCHEDULE_FILE)))
		self.assertEqual(state.load(trades.STATE_FILE), ['t1'])

	def test_the_watchlist_plans_and_records_become_each_home_chats_once(self):
		"""The watchlist and the plans become each home chat's, and so does what a report has told the chats (trades,
		ratings, record highs, each feed's episodes), so that nothing old is told again; a file kept per chat already is
		left as it is, and so is one that cannot be read (said in the log)."""
		feed = podcasts.get_seen_filename('https://example.com/podcast.rss')
		old = {watchlist.FILE: ['MSFT', 'BHP.AX'], worker.PLANS: {'@rob': 'buy low'}, trades.STATE_FILE: ['t1', 't2'],
			rating.STATE_FILE: {'NVDA': ['upgrade', 3]}, milestone.STATE_FILE: {'NVDA': {'all_time_high': 200}},
			feed: ['guid-1']}
		for name, record in old.items():
			state.save(name, record)
		log = self.migrate()
		for name, record in old.items():
			with self.subTest(name=name):
				self.assertEqual(state.load(name), {'chats': {'telegram:1': record, 'slack:C1': record}})
		self.assertIn(f'state: {feed} is kept per chat now, its record copied to telegram:1, slack:C1', log)
		state.save(trades.STATE_FILE, {'chats': {'telegram:1': ['t3']}})
		Path(state.path(rating.STATE_FILE)).write_text('{"NVDA": ["upgr')
		log = self.migrate()
		self.assertEqual(state.load(trades.STATE_FILE), {'chats': {'telegram:1': ['t3']}})
		self.assertEqual(Path(state.path(rating.STATE_FILE)).read_text(), '{"NVDA": ["upgr')
		self.assertIn(f'state: {rating.STATE_FILE} left as it is, unreadable', log)

	def test_pasted_redirects_braces_and_paths_are_dropped(self):
		"""Output redirects, braces, paths, a .py and trailing comments are dropped from an old line's command."""
		for command in ('trades.py > /dev/null', 'trades.py >/dev/null 2>&1', 'trades.py &> /dev/null',
				'trades.py >> ~/x 2>&1', '{ trades.py ;} > ~/x', '/opt/finbot/trades.py # note (x)', 'FOO=1 trades'):
			with self.subTest(command=command):
				lines = migrate.legacy_lines(f'0 1 * * * {command}\n', 'schedule.cron')
				self.assertEqual([commands for _, _, _, commands in lines], [[('trades', [])]])

	def test_the_local_zone_follows_tz(self):
		"""The old schedule ran in the server's zone, which TZ sets: UTC by that name when it is UTC by another."""
		for tz, zone in (('Australia/Melbourne', 'Australia/Melbourne'), ('Etc/UTC', 'UTC'), (':UTC', 'UTC')):
			with self.subTest(tz=tz), mock.patch.dict(os.environ, {'TZ': tz}):
				self.assertEqual(LOCAL_ZONE().key, zone)
