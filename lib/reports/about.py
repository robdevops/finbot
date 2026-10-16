"""What finbot can do: the .help text, and the .jobs menu: a chat's jobs a page at a time, with buttons that switch,
delete or run one; the steps of Add; the next runs; the system jobs; and the reports a job can run."""
import datetime

from lib import buttons
from lib import catalog
from lib import config
from lib import formats
from lib import jobs
from lib import when

HEADINGS = {'top': 'Jobs here', 'on': 'Tap a job to switch it on or off', 'run': 'Tap a job to run it now',
	'del': 'Tap a job added here to delete it (a default job is switched off instead)'}
TYPED = ['.jobs run|toggle|del NUMBER: run one now, switch it on or off, delete one added here',
	'.jobs add REPORT SCHEDULE: add one (.jobs add lists the reports)', '.jobs next: the next runs',
	'.jobs system: the system jobs'] # what a chat without buttons types instead
TYPED_ACTIONS = {'on': 'toggle', 'del': 'del', 'run': 'run'}
NOT_RUN, DEFAULT = '* not run yet', '† default (no delete, only disable)' # the key to a list's marks
PAGE_ROOM = 500 # characters of a screen besides its jobs' lines: its headings, a note, the key to *
JOB_ROW = 4 # job buttons in a row
MOST_JOBS = {'discord': 16} # job buttons on a page: Discord takes five rows of five, one kept for the others; else 40
# Add's reports: (label, action, arguments; None where the period follows how often it runs, or a message's text)
REPORTS = (('trades', 'trades', ()), ('price midsession', 'price', ('midsession',)),
	('price premarket', 'price', ('premarket',)), ('price close', 'price', ('close',)), ('price', 'price', None),
	('performance', 'performance', None), ('cal earnings', 'cal', ('earnings',)),
	('cal ex-dividend', 'cal', ('ex-dividend',)), ('shorts', 'shorts', ()), ('rating', 'rating', ()),
	('milestone', 'milestone', ()), ('message', 'message', None))
FREQUENCIES = (('o', 'one-off'), ('d', 'daily'), ('k', 'weekdays'), ('w', 'weekly'), ('m', 'monthly'),
	('q', 'quarterly'), ('b', 'bi-annual'), ('a', 'annual'), ('r', 'repeating'))
# Add's choices after how often, in turn; and the default of each, marked † on its button
LEVELS = {'o': ('date', 'hour', 'minute'), 'd': ('hour', 'minute'), 'k': ('hour', 'minute'),
	'w': ('weekday', 'hour', 'minute'), 'm': ('day', 'hour', 'minute'), 'q': ('day', 'hour', 'minute'),
	'b': ('day', 'hour', 'minute'), 'a': ('month', 'day', 'hour', 'minute'), 'r': ('interval', 'repeat')}
USUAL = {'frequency': 'd', 'weekday': 5, 'day': 1, 'month': 1, 'hour': 9, 'minute': 0, 'interval': 60, 'repeat': 'd'}
MORE = 'p1' # Add's data for the second page of the days of a month
INTERVALS = (5, 10, 15, 20, 30, 60, 120, 180, 240, 360, 720) # minutes between a repeat's runs, as Add offers them
MINUTES = tuple(range(0, 60, 5)) # the minutes Add offers
MOST_DAYS = {'discord': 20} # days of the month on a page: Discord takes 25 buttons, elsewhere all 31

def jobs_screen(service, chat, screen='top', page=0, note=None, tappable=True):
	"""A screen of the .jobs menu that lists a chat's jobs (by its key), numbered: the default ones (†), then those
	added here, each ✅ (on) or ❌ (off), * where it has never run, its name and its schedule in words, by the timezone
	preference's clock (lib/when.py), then the key to the marks shown. top has what can be done (Enable/disable,
	Delete, Add, Run now, Next); on, del and run a button per job, which switches it (and All, every job), deletes it
	(one added here: a default one has none) or runs it now. A page at a time, as many jobs as a message of the
	network takes (◀ and More ▶ for the others), after a note of what the last press did. A one-off gone by is deleted
	first. Returns (lines, buttons); where the chat takes no buttons (tappable false), the whole list and what to type
	instead."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running'], None
	scheduler.prune(chat)
	own = scheduler.chat_jobs(chat)
	running, local, now = scheduler.running(chat), formats.zone().key, scheduler.clock()
	entries = [(number, job, job_entry(service, scheduler, number, job, running, local, now))
		for number, job in enumerate(own, 1)]
	parts = paged(entries, service) if tappable else [entries]
	page = min(max(page, 0), len(parts) - 1)
	shown = parts[page]
	span = f' ({shown[0][0]}–{shown[-1][0]} of {len(own)})' if len(parts) > 1 else ''
	lines = ([note, ''] if note else []) + [service.bold(HEADINGS[screen] + span)]
	if screen == 'del' and all(job.item for job in own):
		lines.append('None added here yet: Add makes one')
	kind = None
	for number, job, line in shown:
		if kind != (job.item is not None): # a heading where the default jobs start, and those added here
			kind = job.item is not None
			lines += ['', service.bold('Default jobs:' if kind else 'Added here:')]
		lines.append(line)
	key = [text for text, marked in ((NOT_RUN, not all(scheduler.has_run(job) for _, job, _ in shown)),
		(DEFAULT, any(job.item for _, job, _ in shown))) if marked]
	if key:
		lines += ['', ', '.join(key)]
	if not tappable:
		return lines + [''] + (TYPED if screen == 'top' else [f'Send .jobs {TYPED_ACTIONS[screen]} NUMBER']), None
	return lines, screen_buttons(screen, page, len(parts), shown, jobs.list_checksum(own), all(job.on for job in own))

def paged(entries, service):
	"""The jobs' entries (number, job, line) a page at a time: as many as fit a message of the network with room to
	spare, and as many buttons as it takes in a message besides the others."""
	most, room = MOST_JOBS.get(service, 40), service.text_limit - PAGE_ROOM
	parts, size = [[]], 0
	for entry in entries:
		if parts[-1] and (len(parts[-1]) == most or size + len(entry[2]) + 1 > room):
			parts.append([])
			size = 0
		parts[-1].append(entry)
		size += len(entry[2]) + 1
	return parts

def screen_buttons(screen, page, pages, shown, crc, every_on=False):
	"""A list screen's buttons: top's, what can be done; on, del and run's, one for each job shown that the screen
	acts on, '<number> <name>' (with its ✅ or ❌ to switch it), JOB_ROW to a row, then on's All, which switches every
	job of the chat on (All off where every_on: off), and Cancel, back to the list; ◀ and More ▶ to the other pages."""
	if screen == 'top':
		rows = [[buttons.menu_button('Enable/disable', 'on', [0], crc), buttons.menu_button('Delete', 'del', [0], crc)],
			[buttons.menu_button('Add', 'add', [], crc), buttons.menu_button('Run now', 'run', [0], crc),
				buttons.menu_button('Next', 'next', [], crc)]]
		nav = []
	else:
		tapped = [buttons.menu_button(f"{number} {('✅ ' if job.on else '❌ ') if screen == 'on' else ''}{job.name}",
			screen, [page, number], crc) for number, job, _ in shown if screen != 'del' or not job.item]
		rows = [tapped[i:i + JOB_ROW] for i in range(0, len(tapped), JOB_ROW)]
		nav = [buttons.menu_button('Cancel', 'top', [0], crc)]
		if screen == 'on':
			nav.insert(0, buttons.menu_button('All off' if every_on else 'All on', 'on', [page, 'alloff' if every_on
				else 'allon'], crc))
	if page > 0:
		nav.append(buttons.menu_button('◀', screen, [page - 1], crc))
	if page < pages - 1:
		nav.append(buttons.menu_button('More ▶', screen, [page + 1], crc))
	return rows + ([nav] if nav else [])

def job_entry(service, scheduler, number, job, running=(), local=None, now=None):
	"""'5. ✅ price close AU† · weekdays at 4:30pm Sydney': a job in .jobs, with its number, whether it is on (and *
	where it has never run), its name (and † for a default job), its schedule in words, and whether it is running."""
	mark = ('✅' if job.on else '❌') + ('' if scheduler.has_run(job) else '*')
	name = service.escape(job.name) + ('†' if job.item else '')
	schedule = job.schedule.describe(local or formats.zone().key, now or scheduler.clock())
	return f"{number}. {mark} {name} · {schedule}" + (' (running)' if job.key in running else '')

def job_line(number, job, outcome):
	"""'3. trades: done': a job's number in the .jobs list, its name, and how its run went."""
	return f"{number}. {job.name}: {outcome}"

def next_screen(service, chat, count=20):
	"""`.jobs next`: a chat's next runs, in time order, at most count, each by the timezone preference's clock (and its
	own zone's beside it, where that differs), with its number and name in .jobs; a repeat's runs on a day are one
	entry, from its first to its last. Returns (lines, buttons): Cancel, back to the list."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running'], None
	local = formats.zone()
	lines = [service.bold('Next runs:')]
	for first, last, job, number in scheduler.upcoming(chat, count):
		said = moment_words(first, local, job.schedule.tz)
		if job.schedule.every:
			end = last.astimezone(local)
			said += (f" – {clock_words(end, local)}" if end.date() == first.astimezone(local).date() else
				f" – {moment_words(last, local)}") + f", {when.repeat_words(job.schedule.every, 0, local.key == 'UTC')}"
		lines.append(f"{said} · {number}. {service.escape(job.name)}")
	if len(lines) == 1:
		lines.append('None: every job here is off')
	return lines, [[buttons.menu_button('Cancel', 'top', [0], jobs.list_checksum(scheduler.chat_jobs(chat)))]]

def clock_words(moment, zone):
	"""A moment's time of day by a zone's clock: '8:30am', in 24 hours for UTC ('21:30')."""
	here = moment.astimezone(zone)
	return when.clock(here.hour * 60 + here.minute, zone.key == 'UTC')

def moment_words(moment, local, zone=None):
	"""'Sun 18 Oct 8:30am': a moment by the local clock, with a zone's beside it where that differs ('Tue 20 Oct 3:45am
	(12:45pm New York)')."""
	here = moment.astimezone(local)
	said = f"{here:%a} {here.day} {here:%b} {clock_words(moment, local)}"
	if zone is not None and moment.astimezone(zone).utcoffset() != here.utcoffset():
		said += f" ({clock_words(moment, zone)} {when.place(zone.key)})"
	return said

def add_screen(service, chat, steps):
	"""A step of Add, from the choices made so far (steps, from the button pressed: the report's number, how often, then
	the LEVELS of that frequency in turn: a date, a day of the week or of the month, a month, the hour and the minute,
	or a repeat's interval and its days): (lines, buttons) of the next choice, its default (USUAL) marked †, or (None,
	(action, arguments, schedule)) once every choice is made, at a time by the timezone preference's clock. Cancel goes
	back to the list, and Back, after the report, a step back. Raises ValueError for choices that are none (forged)."""
	scheduler = jobs.current
	crc, local = jobs.list_checksum(scheduler.chat_jobs(chat)), formats.zone()
	tomorrow = scheduler.clock().astimezone(local).date() + datetime.timedelta(days=1)
	steps, page = list(steps), 0
	if steps and steps[-1] == MORE:
		steps, page = steps[:-1], 1
	back = buttons.menu_button('Back', 'add', steps[:-1], crc)
	cancel = buttons.menu_button('Cancel', 'top', [0], crc)
	def choices(heading, offered, row, lines=(), usual=None, nav=None):
		"""A choice's screen: its heading and lines, and '† indicates default' where one is (usual: its data); its
		buttons (label, data), `row` to a row, the default's label marked †; then Back and Cancel (or nav)."""
		tapped = [buttons.menu_button(label + ('†' if data == usual else ''), 'add', [*steps, data], crc)
			for label, data in offered]
		key = [] if usual is None else ['', '† indicates default']
		return [service.bold(heading), *lines, *key], [tapped[i:i + row] for i in range(0, len(tapped), row)] + [
			nav or [back, cancel]]
	if not steps: # a button per report, by its name alone, and Cancel
		return choices('Add a job: which report?', [(label, number) for number, (label, _, _) in enumerate(REPORTS, 1)],
			3, nav=[cancel])
	label, action, args = REPORTS[choice(steps[0], 1, len(REPORTS)) - 1]
	if action == 'message':
		return [service.bold('Add a message'), "A message's text is what you type:",
			'.jobs add message SCHEDULE "TEXT"', '', service.bold('For example:'),
			'.jobs add message every 31 mar at 8:30am "🥳 Happy EOFY"',
			'.jobs add message on 28 oct 2026 "ubank draw 6/6"'], [[back, cancel]]
	if len(steps) == 1:
		return choices(f'Add {label}: how often?', [(name, code) for code, name in FREQUENCIES], 3,
			usual=USUAL['frequency'])
	frequency, levels = steps[1], LEVELS.get(steps[1])
	if levels is None:
		raise ValueError(f'no frequency {frequency!r}')
	made = steps[2:]
	if len(made) > len(levels) or (page and levels[len(made):len(made) + 1] != ('day',)):
		raise ValueError('no such choices')
	values = {}
	for level, data in zip(levels, made):
		values[level] = chosen(level, data, values)
	if len(made) == len(levels):
		if frequency == 'r':
			schedule = when.Schedule('daily' if values['repeat'] == 'd' else 'weekdays', every=values['interval'],
				zone=local.key)
		else:
			if frequency == 'o':
				days = {'date': values['date'].isoformat()}
			elif frequency == 'w':
				days = (when.DAYS[values['weekday']],)
			elif 'day' in values:
				days = {'day': values['day'], 'months': {'m': (), 'q': when.QUARTERS, 'b': when.HALVES}.get(frequency,
					(values.get('month'),))}
			else:
				days = 'daily' if frequency == 'd' else 'weekdays'
			schedule = when.Schedule(days, at=values['hour'] * 60 + values['minute'], zone=local.key)
		schedule.check()
		return None, (action, list(args) if args is not None else catalog.period_args(action, schedule), schedule)
	level, said = levels[len(made)], so_far(frequency, values)
	if level == 'date':
		dates = [tomorrow + datetime.timedelta(days=n) for n in range(-1, 13)]
		return choices(f'Add {label}, once: on which day?', [(f'{date:%a} {date.day} {date:%b}', f'{date:%y%m%d}')
			for date in dates], 4, ['A later one is typed: .jobs add REPORT on 28 oct 2026 at 9am'],
			f'{tomorrow:%y%m%d}')
	if level == 'weekday':
		return choices(f'Add {label}, weekly: on which day?', [(day.title(), number) for number, day in
			enumerate(when.DAYS)], 4, usual=USUAL['weekday'])
	if level == 'month':
		return choices(f'Add {label}, annual: in which month?', [(month.title(), number) for number, month in
			enumerate(when.MONTHS, 1)], 4, usual=USUAL['month'])
	if level == 'day':
		last = {2: 29, 4: 30, 6: 30, 9: 30, 11: 30}.get(values.get('month'), 31)
		most = MOST_DAYS.get(service, 31)
		if page * most >= last:
			raise ValueError('no such page')
		nav = [back, cancel]
		if page:
			nav.insert(0, buttons.menu_button('◀', 'add', steps, crc))
		elif last > most:
			nav.insert(0, buttons.menu_button('More ▶', 'add', [*steps, MORE], crc))
		return choices(f'Add {label}, {said}: on which day of the month?', [(str(day), day) for day in
			range(1, last + 1)][page * most:(page + 1) * most], 5, ['A month without that day has no run'],
			USUAL['day'], nav)
	if level == 'hour':
		lines, rows = choices(f'Add {label}, {said}: at what hour?', [(f'{hour:02d}', hour) for hour in range(24)], 5,
			[f"By {when.place(local.key)}'s clock"], USUAL['hour'])
		hours = [button for row in rows[:-1] for button in row] + [back] # 24 and Back: Discord takes 25 buttons
		return lines, [hours[i:i + 5] for i in range(0, 25, 5)]
	if level == 'minute':
		hour = values['hour']
		return choices(f'Add {label}, {said}: at what time?', [(f'{hour:02d}:{minute:02d}', minute) for minute in
			MINUTES], 4, usual=USUAL['minute'])
	if level == 'interval':
		return choices(f'Add {label}, repeating: how often?', [(when.repeat_words(minutes, 0, False).removeprefix(
			'every '), minutes) for minutes in INTERVALS], 4, ['A window of hours is typed: .jobs add REPORT every 20'
			' mins weekdays from 10am to 4pm'], USUAL['interval'])
	return choices(f'Add {label}, {said}: on which days?', [('every day', 'd'), ('weekdays', 'k')], 2,
		usual=USUAL['repeat'])

def chosen(level, data, values):
	"""A choice's value at a level of Add, from a button's data (values: the choices before it). Raises ValueError for
	one that is none."""
	if level == 'date':
		if not (len(data) == 6 and data.isascii() and data.isdigit()):
			raise ValueError(f'no date {data!r}')
		return datetime.date(2000 + int(data[:2]), int(data[2:4]), int(data[4:]))
	if level == 'day':
		day = choice(data, 1, 31)
		if 'month' in values:
			datetime.date(2024, values['month'], day) # a day that month has, in a leap year
		return day
	if level in ('weekday', 'month', 'hour', 'minute', 'interval'):
		return choice(data, *{'weekday': (0, 6), 'month': (1, 12), 'hour': (0, 23), 'minute': (0, 55, MINUTES),
			'interval': (1, 1440, INTERVALS)}[level])
	if data not in ('d', 'k'):
		raise ValueError(f'no days {data!r}')
	return data

def so_far(frequency, values):
	"""How often a job being added runs, as far as it is chosen: 'weekly, Fridays', 'annual, in Mar', 'monthly'."""
	if frequency == 'r':
		return when.repeat_words(values['interval'], 0, False) if 'interval' in values else 'repeating'
	if 'date' in values:
		return f"once, {when.date_words(values['date'])}"
	if 'weekday' in values:
		return f"weekly, {when.plural(when.DAYS[values['weekday']])}"
	if 'day' in values:
		months = {'m': (), 'q': when.QUARTERS, 'b': when.HALVES}.get(frequency, (values.get('month'),))
		return when.days_words({'day': values['day'], 'months': months})
	if 'month' in values:
		return f"annual, in {when.MONTHS[values['month'] - 1].title()}"
	return dict(FREQUENCIES)[frequency].replace('one-off', 'once')

def choice(text, low, high, among=None):
	"""A choice's number from a button's data, from low to high (and among those offered, where given). Raises
	ValueError for one that is none."""
	if not (text.isascii() and text.isdigit() and low <= int(text) <= high and (among is None or int(text) in among)):
		raise ValueError(f'no choice {text!r}')
	return int(text)

def added_screen(service, chat, number):
	"""What the last step of Add shows: the job added, with its number in the list, and buttons to it and to Add."""
	own = jobs.current.chat_jobs(chat)
	crc = jobs.list_checksum(own)
	return [f"Added: {job_entry(service, jobs.current, number, own[number - 1])}"], [[buttons.menu_button('Jobs',
		'top', [0], crc), buttons.menu_button('Add another', 'add', [], crc)]]

def add_failed(service, chat, steps, why):
	"""What the last step of Add shows when the job cannot be added: why, with Back to the last choice and Cancel."""
	crc = jobs.list_checksum(jobs.current.chat_jobs(chat))
	return [service.escape(why)], [[buttons.menu_button('Back', 'add', list(steps)[:-1], crc),
		buttons.menu_button('Cancel', 'top', [0], crc)]]

def prepare_system(service):
	"""`.jobs system`: the system jobs, which fill the cache and clear it out, each with its schedule in words."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running']
	running, local, now = scheduler.running(''), formats.zone().key, scheduler.clock()
	return [service.bold('System jobs:')] + [f"{job.name} · {job.schedule.describe(local, now)}" +
		(' (running)' if job.key in running else '') for job in scheduler.system_jobs()]

def prepare_reports(service):
	"""`.jobs add` alone: the reports a job can run, each with what it takes, and examples."""
	return [service.bold('Reports a job can run:')] + [f"{name} {jobs.ACTIONS[name].ARGUMENTS}".strip()
		for name in jobs.chat_actions()] + ['', service.bold('For example:'), '.jobs add price weekly',
		'.jobs add price close weekdays at 4:30pm New York', '.jobs add performance first day of each month at 9am',
		'.jobs add trades every 20 mins weekdays from 10am to 4pm',
		'.jobs add message every 31 mar at 8:30am "🥳 Happy EOFY"', '',
		f"Times are by {when.place(formats.zone().key)}'s clock unless one names a zone (UTC, New York, EST);"
		" performance and price cover the days between runs"]

def prepare_help(service, botName, sections):
	"""The .help text: each section's command lines under its heading (worker.help_sections() has them), then the bot's
	@name as another way to start a command. botName is the bot's @name. On Discord the lines are slash commands, and
	the other ways, which are messages, work only over the gateway."""
	if service == 'discord':
		example = None if config.env.discordOutgoingWebhook else f'.price, or <{botName}> price'
	else:
		example = '<' + botName + '> trades' if service == 'slack' else botName + ' price'
	return formats.sections(*([service.bold(heading + ":")] + lines for heading, lines in sections),
		[service.bold("Alternative syntax:"), example] if example else [],
		[f"Full help on {service.link('https://github.com/robdevops/finbot', 'GitHub')}"])
