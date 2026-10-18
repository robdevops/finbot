"""What a job may be (lib/jobs.py): an action of the fixed table, never a command, with the arguments its report's job()
takes, as .jobs add reads them; the default jobs (lib/catalog.py) and the messages they post; and a direct message's
jobs."""
import contextlib, datetime, hashlib, io, re, unittest
from pathlib import Path
from tests.common import *
from lib import catalog, inbound, jobs, state, when, worker
from lib.reports import cleanup, earnings, message, movers, performance, podcasts

MELBOURNE = 'Australia/Melbourne'
OCTOBER = datetime.datetime(2026, 10, 15, tzinfo=when.UTC)


class Actions(unittest.TestCase):
	def test_a_job_runs_only_a_report_or_a_command_of_finbots_own(self):
		"""Each action a job may run is a report module of finbot's own, with its run and its parser, or a command of
		.help that changes nothing, by one of its names; a chat may schedule all but the system's, the commands listed
		by their names in .help."""
		for name, module in jobs.ACTIONS.items():
			with self.subTest(name=name):
				self.assertEqual(module.__name__, f'lib.reports.{name}')
				self.assertTrue(callable(module.run) and callable(module.job))
		commands = jobs.command_actions()
		for name, command in commands.items():
			with self.subTest(name=name):
				self.assertIn(command.command, worker.COMMANDS)
				self.assertTrue(command.command.job and name in command.command.names)
				self.assertNotIn(command.command.handler, worker.REPORTED)
		self.assertFalse({'help', 'start', 'watchlist', 'wishlist', 'plan', 'jobs', 'cron', 'schedule', 'movers',
			'session', 'earnings', 'trades'} & set(commands))
		self.assertEqual(jobs.chat_actions(), ['earnings', 'message', 'milestone', 'movers', 'performance', 'podcasts',
			'rating', 'shorts', 'trades', 'holdings', 'treemap', 'who', 'marketcap', 'beta', 'price',
			'buysell', 'pe', 'peg', 'stock'])

	def test_a_command_of_help_as_a_job(self):
		"""A job may run a command of .help by its name, the words it takes before the schedule; another of its names
		(a typo too) stands for it, but buy and sell's, which say which; one that takes no words refuses them, one
		that needs a stock refuses none, and one whose usage brackets its stock or portfolio (a picker's) runs bare."""
		weekly = when.parse('weekly', 'UTC')
		for text, action, args in (('pe top weekly', 'pe', ['top']), ('peg negative weekly', 'peg', ['negative']),
				('forward pe weekly', 'forward pe', []),
				('compare AAPL MSFT 1y weekly at 9am', 'compare', ['AAPL', 'MSFT', '1y']),
				('buy&sell weekly', 'buy&sell', []), ('holdings Rob weekly', 'holdings', ['Rob']),
				('holdings weekly', 'holdings', []), ('treemap sector weekly', 'treemap', ['sector']),
				('history weekly', 'history', []), ('compare weekly', 'compare', []), ('price weekly', 'price', []),
				('price AAPL weekly', 'price', ['AAPL'])):
			with self.subTest(text=text):
				self.assertEqual(jobs.parse_add(text, 'UTC')[:2], (action, args))
		for text in ('beta x weekly', 'who weekly', 'stock weekly'):
			with self.subTest(text=text), self.assertRaises(jobs.ScheduleError):
				jobs.parse_add(text, 'UTC')
		for action, args, made, name in (('hospital', ['AAPL'], 'compare', 'price AAPL'), ('fpe', [], 'pe',
				'pe'), ('buy&sell', [], 'buy&sell', 'buy & sell'), ('sell', [], 'sell', 'sell'),
				('price', ['AAPL'], 'compare', 'price AAPL')):
			with self.subTest(action=action):
				job = jobs.make_job(action, args, weekly, 'telegram:1')
				self.assertEqual((job.action, job.name, job.kwargs), (made, name, {'words': args}))

	def test_anything_else_is_refused(self):
		"""A name that is no action (a shell command, a module's path, a builtin), a system job for a chat, arguments
		that are not words or that its parser refuses: refused as a job is made and as .jobs add reads it."""
		daily = when.parse('daily', 'UTC')
		for action, args in (('os.system', ['ls']), ('price; rm -rf /', []), ('lib.reports.price', ['close']),
				('__import__', ['os']), ('eval', ['1']), ('yahoo_warm', []), ('movers', ['bogus']), ('trades', [7]),
				(['trades'], []), ('movers', 'close'), ('jobs', []), ('plan', ['x']),
				('watchlist', ['add', 'X']),
				('help', []), ('on_jobs', [])):
			with self.subTest(action=action, args=args), self.assertRaises(jobs.ScheduleError):
				jobs.make_job(action, args, daily, 'telegram:1')
		for text in ('os.system daily', 'price; rm -rf / daily', '../../etc/passwd daily', 'trades daily; rm -rf /',
				'message daily', 'trades.py daily', 'jobs add price daily daily', 'plan buy low daily',
				'watchlist add X daily'):
			with self.subTest(text=text), self.assertRaises(jobs.ScheduleError):
				jobs.parse_add(text, 'UTC')
		self.assertEqual(jobs.make_job('yahoo_warm', [], daily).label, 'yahoo_warm') # the system's own

	def test_what_jobs_add_reads(self):
		""".jobs add takes a report, what it takes and a schedule, wherever both read; performance and movers cover the
		days between runs where they name no period; a message takes its schedule, then its text in double quotes."""
		url = 'https://example.com/Feed.rss'
		for text, action, args, stored in (('movers weekly', 'movers', ['7'], {'days': ['sat'], 'at': '09:00'}),
				('movers close weekdays at 4:30pm New York', 'movers', ['close'],
					{'days': 'weekdays', 'at': '16:30', 'zone': 'America/New_York'}),
				('performance quarterly', 'performance', ['90'], {'days': {'day': 1, 'months': [1, 4, 7, 10]},
					'at': '09:00'}),
				('performance tue-sat at 8am', 'performance', [], {'days': ['tue', 'wed', 'thu', 'fri', 'sat'],
					'at': '08:00'}),
				('movers every 20 mins weekdays', 'movers', ['interday'], {'days': 'weekdays', 'every': 20}),
				('earnings every sunday', 'earnings', [], {'days': ['sun'], 'at': '09:00'}),
				(f'podcasts {url} hourly', 'podcasts', [url], {'days': 'daily', 'every': 60}),
				('message every 31 mar "🥳 Happy EOFY"', 'message', ['🥳 Happy EOFY'],
					{'days': {'day': 31, 'months': [3]}, 'at': '08:30'}),
				('message on 28 oct 2026 at 9am "a "quoted" word\nand a line"', 'message',
					['a "quoted" word', 'and a line'], {'days': {'date': '2026-10-28'}, 'at': '09:00'})):
			with self.subTest(text=text):
				got = jobs.parse_add(text, MELBOURNE)
				self.assertEqual((got[0], got[1], got[2].to_json()), (action, args, {'zone': MELBOURNE, **stored}))


class JobArguments(unittest.TestCase):
	def test_movers(self):
		"""movers takes one mode or a number of days (the top and bottom ten over it); anything else is its usage."""
		self.assertEqual(movers.job(['midsession']), ('movers midsession', {'mode': 'midsession'}))
		self.assertEqual(movers.job(['premarket'])[1], {'mode': 'premarket'})
		self.assertEqual(movers.job(['interday'])[1], {'mode': 'interday'})
		self.assertEqual(movers.job(['close'])[1], {'mode': 'close'})
		self.assertEqual(movers.job(['28']), ('movers 28', {'mode': 'period', 'threshold': 0, 'days': 28, 'top': 10}))
		for bad in ([], ['soon'], ['7', '8']):
			with self.assertRaisesRegex(ValueError, movers.ARGUMENTS.replace('|', r'\|')):
				movers.job(bad)

	def test_the_old_cal_jobs_are_the_earnings_job(self):
		"""A job stored as cal earnings or cal ex-dividend runs as earnings, and a default job's old keys in a chat's
		record stand for the one earnings."""
		schedule = {'days': ['sun'], 'at': '09:00', 'zone': 'UTC'}
		for args in (['earnings'], ['ex-dividend']):
			job = jobs.stored_job('telegram:5', {'action': 'cal', 'args': args, 'schedule': schedule})
			self.assertEqual((job.action, job.args, job.name), ('earnings', (), 'earnings'))
		self.assertFalse(jobs.item_on({'off': ['cal-ex-dividend']}, 'earnings'))
		self.assertTrue(jobs.item_on({'off': ['cal-ex-dividend']}, 'shorts'))
		self.assertEqual(jobs.removed({'deleted': ['cal-earnings', 'shorts']}), ['earnings', 'shorts'])

	def test_cal_and_performance(self):
		"""earnings takes none; performance an optional number of days."""
		self.assertEqual(performance.job([]), ('performance', {}))
		self.assertEqual(performance.job(['7']), ('performance 7', {'past_days': 7}))
		for bad, module in ((['x'], earnings), (['x'], performance)):
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

	def test_message(self):
		"""message takes its text's lines, which may hold anything but must say something, 40 lines and 3000 at most."""
		self.assertEqual(message.job(['a {0}', '', 'b']), ('message', {'lines': ['a {0}', '', 'b']}))
		for bad in ([], [''], [' ', ''], ['x'] * 41, ['x' * 3001], [5]):
			with self.subTest(bad=bad), self.assertRaises(ValueError):
				message.job(bad)

	def test_cleanup_arguments(self):
		"""cleanup takes an optional number of days."""
		self.assertEqual(cleanup.job([]), ('cleanup', {}))
		self.assertEqual(cleanup.job(['7']), ('cleanup 7', {'days': 7}))
		for bad in (['x'], ['1', '2']):
			with self.assertRaises(ValueError):
				cleanup.job(bad)

	def test_plain_reports(self):
		"""The other reports take no arguments, and say so: their ARGUMENTS, which .jobs add lists, are empty."""
		for name, module in jobs.ACTIONS.items():
			with self.subTest(name=name):
				self.assertIsInstance(module.ARGUMENTS, str)
				if name not in ('cleanup', 'message', 'performance', 'podcasts', 'movers'):
					self.assertEqual((module.job([]), module.ARGUMENTS), ((name, {}), ''))
					with self.assertRaisesRegex(ValueError, 'no arguments'):
						module.job(['7'])

	def test_the_checkout_holds_only_the_bot_at_its_top(self):
		"""The scheduled reports run in the bot (and `.jobs run`), so the checkout's top holds bot.py alone: the scripts
		that ran each report from cron are gone."""
		self.assertEqual(sorted(path.name for path in Path(ROOT).glob('*.py')), ['bot.py'])


class DefaultJobs(unittest.TestCase):
	def test_every_default_job_can_be(self):
		"""Each default job is an action a chat may schedule, with arguments its parser takes, on a schedule that runs;
		its key is its own; its name says what it reports on, never when; performance and movers over a period cover the
		days between their runs."""
		self.assertEqual(len(catalog.ITEMS), 34)
		self.assertEqual(len({item.key for item in catalog.ITEMS}), 34)
		start = datetime.datetime(2026, 1, 1, tzinfo=when.UTC)
		for item in catalog.ITEMS:
			with self.subTest(item=item.key):
				jobs.make_job(item.action, item.args, item.schedule, 'telegram:1', item=item.key, name=item.name)
				self.assertIn(item.action, jobs.chat_actions())
				self.assertIsNotNone(item.schedule.next_after(start))
				self.assertIsNone(re.search(r'\d(am|pm)|daily|weekly|monthly|quarterly|annual', item.name))
				if item.action in catalog.PERIODIC and all(arg.isdigit() for arg in item.args):
					self.assertEqual(list(item.args), catalog.period_args(item.action, item.schedule))

	def test_without_sharesight_no_default_job_reports_on_it(self):
		"""Without Sharesight, the default jobs leave out those that report on it: trades and performance."""
		names = {item.name for item in catalog.items('AU', sharesight=False)}
		self.assertFalse(names & {'trades', 'performance'})
		self.assertTrue({'trades', 'performance', 'movers'} <= {item.name for item in catalog.items('AU')})
		self.assertIn('movers', names)

	def test_the_default_jobs_as_a_melbourne_chat_sees_them(self):
		"""The default jobs by name, each with its schedule in words, as a chat in Melbourne sees them in mid-October:
		each in its market's zone, the local time beside it where the clocks differ."""
		described = [f'{item.name} · {item.schedule.describe(MELBOURNE, OCTOBER)}' for item in catalog.items('AU')]
		self.assertEqual(described, ['trades · every 20 mins, Mon 9am – Sat 3pm',
			'movers midsession AU · weekdays at 1:00pm',
			'movers midsession US · weekdays at 12:45pm New York (3:45am local, Tue–Sat)',
			'movers premarket US · weekdays at 7:15am New York (10:15pm local)',
			'movers close AU · weekdays at 4:30pm',
			'movers close HK · weekdays at 4:30pm Hong Kong (7:30pm local)',
			'movers close UK · weekdays at 5:00pm London (3:00am local, Tue–Sat)',
			'movers close US · weekdays at 4:30pm New York (7:30am local, Tue–Sat)',
			'rating · Tue–Sat at 8:30am', 'milestone · Tue–Sat at 8:30am',
			'podcasts Money Cafe · hourly at :01, weekdays 10am–9pm',
			'podcasts Stocktake · hourly at :01, weekdays 10am–9pm',
			'earnings · weekly, Sundays at 8:30am',
			'shorts · weekly, Sundays at 8:30am', 'performance · weekly, Sundays at 8:30am',
			'movers · weekly, Sundays at 8:30am', 'performance · monthly, the 2nd at 8:30am',
			'movers · monthly, the 2nd at 8:30am', 'performance · quarterly, 2 Jan/Apr/Jul/Oct at 8:30am',
			'movers · quarterly, 2 Jan/Apr/Jul/Oct at 8:30am',
			'performance · bi-annual, 2 Jan and 2 Jul at 8:30am',
			'movers · bi-annual, 2 Jan and 2 Jul at 8:30am', 'performance · annual, 2 Jan at 8:30am',
			'movers · annual, 2 Jan at 8:30am',
			'🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦 · annual, 31 Mar at 8:30am',
			'SPCX IPO anniversary · annual, 12 Jun at 8:30am',
			'💸 Realise capital gains/losses by EOFY June 30 (AU) · annual, 23 Jun at 8:30am',
			'🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰 · annual, 30 Jun at 8:30am',
			"✍️ Submit 'Notice of Intent to Claim' for any post-tax … (AU) · annual, 7 Jul at 8:30am",
			"finbot's birthday · annual, 18 Aug at 8:30am",
			'😓 Self-service individual tax returns are due Oct 31 (AU) · annual, 25 Oct at 8:30am',
			'ubank draw 6/6 … (AU) · once, 28 Oct 2026 at 8:30am',
			'😰 Self-service individual tax returns are due today (AU) · annual, 31 Oct at 8:30am',
			'SPCX 5th mensiversary. End of (statistically) most … · once, 12 Nov 2026 at 8:30am'])

	def test_a_message_for_one_country_only_there_with_its_flag(self):
		"""A message for one country is a default job only where it is the country_code setting, with its flag."""
		au, nz = ({item.key for item in catalog.items(country)} for country in ('AU', 'NZ'))
		self.assertEqual(sorted(au - nz), ['message-eofy-checklist', 'message-intent-to-claim', 'message-tax-due-soon',
			'message-tax-due-today', 'message-ubank-draw-6'])
		self.assertLess(nz, au)
		checklist = next(item for item in catalog.ITEMS if item.key == 'message-eofy-checklist')
		self.assertEqual(checklist.args[0], '💸 Realise capital gains/losses by EOFY June 30🇦🇺')
		self.assertFalse(any('{flag}' in line for item in catalog.ITEMS for line in item.args))

	def test_a_job_that_is_a_default_one(self):
		"""A job is a default one where its action, arguments, days and times are, in a zone that keeps the same clock
		(Melbourne's and's), and not in another (Brisbane's has no summer time)."""
		def matching(text):
			"""The default job that .jobs add's text is in Melbourne, or None."""
			item = catalog.matching(*jobs.parse_add(text, MELBOURNE), 'AU')
			return item and item.key
		self.assertEqual(matching('trades every 20 mins from mon 9am to sat 3pm'), 'trades')
		self.assertIsNone(matching('trades every 20 mins from mon 9am to sat 3pm Brisbane'))
		self.assertIsNone(matching('trades every 20 mins weekdays'))
		self.assertEqual(matching('movers close weekdays at 4:30pm New York'), 'price-close-us')
		self.assertEqual(matching('movers every sunday at 8:30am'), 'price-weekly')


class Messages(FinbotCase):
	def test_the_end_of_financial_year_checklist(self):
		"""On 23 June an Australian chat gets the EOFY checklist, its links and footnotes in its network's markup."""
		checklist = next(item for item in catalog.ITEMS if item.key == 'message-eofy-checklist')
		message.run(scheduled(), lines=list(checklist.args))
		lines = self.sent[0][1]
		self.assertEqual((len(lines), lines[0]), (12, '💸 Realise capital gains/losses by EOFY June 30🇦🇺'))
		self.assertEqual(lines[8], '<i>* Organisation must be <a href="https://abr.business.gov.au/Tools/DgrListing">'
			'DGR-registered</a></i>')

	def test_the_birthday_counts_the_years(self):
		"""finbot's birthday says how old it is that day, by the timezone setting's clock."""
		birthday = next(item for item in catalog.ITEMS if item.key == 'message-birthday')
		for today, said in ((datetime.date(2026, 8, 18), "It's my 4th birthday! 🥳"),
				(datetime.date(2026, 8, 17), "It's my 3rd birthday! 🥳")):
			with self.subTest(today=today):
				self.sent.clear()
				self.patch(message, 'today', lambda: today)
				message.run(scheduled('slack:C9'), lines=list(birthday.args))
				self.assertEqual(self.sent, [('text', [said])])

	def test_a_message_is_data(self):
		"""A message's text is posted as it is, made safe for its network, never formatted: braces stay braces."""
		message.run(scheduled(), lines=['<b>{0} {years since x}</b> & {__class__}'])
		self.assertEqual(self.sent, [('text', ['&lt;b&gt;{0} {years since x}&lt;/b&gt; &amp; {__class__}'])])


class DirectMessages(FinbotCase):
	"""A direct message with the bot starts with its default jobs off."""

	def test_a_direct_message_starts_with_its_default_jobs_off(self):
		"""A chat new to finbot starts with its default jobs on, a direct message with them off: Telegram's (a person's
		id) and Slack's (D…) as their keys tell, Discord's as its updates say. One switched on there is on."""
		jobs.know(['telegram:5', 'telegram:-100', 'slack:D1', 'slack:C1', 'discord:7'])
		jobs.know(['discord:8'], dm=True)
		dm = {'defaults': 'off', 'dm': True}
		self.assertEqual(state.load(jobs.JOBS_FILE), {'telegram:5': dm, 'telegram:-100': {}, 'slack:D1': dm,
			'slack:C1': {}, 'discord:7': {}, 'discord:8': dm})
		s = jobs.Scheduler(clock=lambda: OCTOBER)
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
			self.assertFalse(any(job.on for job in s.chat_jobs('telegram:5')))
			self.assertTrue(all(job.on for job in s.chat_jobs('telegram:-100')))
			s.toggle(s.chat_jobs('telegram:5')[0])
			self.assertEqual(state.load(jobs.JOBS_FILE)['telegram:5'], {**dm, 'on': ['trades']})
			self.assertEqual([job.on for job in s.chat_jobs('telegram:5')][:2], [True, False])

	def test_a_chat_seen_says_whether_it_is_a_direct_message(self):
		"""At a chat's first command it starts with its default jobs off where it is a direct Discord's update
		says so, Telegram's chat id does."""
		self.env(discordBotToken='x')
		s = jobs.Scheduler(clock=lambda: OCTOBER)
		with contextlib.redirect_stderr(io.StringIO()):
			s.load()
			self.patch(jobs, 'current', s)
			for chat, dm in (('88', True), ('77', False)):
				worker.process_request(inbound.Message('discord', chat, '<@5>', '.help', '@99', 'rob', dm=dm))
			worker.process_request(inbound.Message('telegram', '5', '@u', '.help', BOT, 'U'))
		self.assertEqual(state.load(jobs.JOBS_FILE), {'discord:88': {'defaults': 'off', 'dm': True}, 'discord:77': {},
			'telegram:5': {'defaults': 'off', 'dm': True}})

	def test_the_schedule_counts_group_chats_and_dms(self):
		"""The schedule's line in the log at each load counts the chats' jobs, the group chats and the DMs apart (a
		DM by its mark, or its key), and the system's jobs."""
		self.patch(catalog, 'ITEMS', ())
		self.patch(jobs, 'SYSTEM', ())
		state.save(jobs.JOBS_FILE, {'telegram:-100': {}, 'discord:8': {'dm': True}, 'slack:C1': {}})
		with contextlib.redirect_stderr(io.StringIO()) as log:
			jobs.Scheduler(clock=lambda: OCTOBER).load()
		self.assertIn('schedule: 0 jobs of 2 group chats and 1 DM, and 0 system jobs', log.getvalue())


if __name__ == '__main__':
	unittest.main()
