"""What finbot can do: the .help text, and the .jobs menu: a chat's jobs a page at a time, with buttons that enable,
disable, delete or run one; the steps of Add; the upcoming runs; the system jobs; and the reports a job can run."""
import calendar
import datetime
import re

from lib import buttons
from lib import catalog
from lib import config
from lib import formats
from lib import jobs
from lib import sharesight
from lib import when

HEADINGS = {'top': 'Jobs here', 'edit': 'Tap a job to enable or disable it', 'run': 'Tap a job to run it now'}
ADD_TYPED = ['/jobs add REPORT SCHEDULE', '/jobs add reminder SCHEDULE "TEXT"'] # how Add is typed: under the list
NOT_RUN = '* not run yet' # the key to a list's mark
PAGE_ROOM = 500 # characters of a screen besides its jobs' lines: its headings, a note, the key to *
JOB_ROW = 4 # job buttons in a row
MOST_JOBS = {'discord': 16} # job buttons on a page: Discord takes five rows of five, one kept for the others; else 40
# Add's reports: (label, action, arguments; None where the period follows how often it runs, or a reminder's text)
REPORTS = (('trades', 'trades', ()), ('movers midsession', 'movers', ('midsession',)),
	('movers premarket', 'movers', ('premarket',)), ('movers close', 'movers', ('close',)), ('movers', 'movers', None),
	('performance', 'performance', None), ('earnings', 'earnings', ()),
	('shorts', 'shorts', ()), ('rating', 'rating', ()),
	('milestone', 'milestone', ()), ('reminder', 'message', None))
FREQUENCIES = (('o', 'one-off'), ('h', 'hourly'), ('d', 'daily'), ('w', 'weekly'), ('m', 'monthly'),
	('q', 'quarterly'), ('b', 'bi-annual'), ('a', 'annual'), ('r', 'every...'))
WEEKDAY = 'k' # every...'s weekday, among its intervals: a time each weekday
REPEAT = ('repeat', 'start hour', 'start minute', 'end') # a repeat's choices after its interval
# Add's choices after how often, in turn; every... takes a weekday's hour and minute instead, once it is a weekday
LEVELS = {'o': ('year', 'month', 'day', 'hour', 'minute'), 'h': REPEAT, 'd': ('hour', 'minute'),
	'w': ('weekday', 'hour', 'minute'), 'm': ('day', 'hour', 'minute'), 'q': ('month', 'day', 'hour', 'minute'),
	'b': ('month', 'day', 'hour', 'minute'), 'a': ('month', 'day', 'hour', 'minute'), 'r': ('interval', *REPEAT)}
CYCLES = {'q': 4, 'b': 2, 'a': 1} # months a year of quarterly, bi-annual and annual, from the start month chosen
CYCLE_NOTES = {'q': ['Then every 3 months'], 'b': ['And 6 months later']} # under the start month's question
END = 'e' # a repeat's end where it runs to the end of the day
# the default of each choice, marked † on its button; a one-off's are today's year and month, and tomorrow
USUAL = {'frequency': 'd', 'weekday': '5', 'day': '1', 'month': '1', 'hour': '9', 'minute': '0', 'interval': WEEKDAY,
	'repeat': 'd', 'start hour': '0', 'start minute': '0', 'end': END}
MORE = 'p1' # Add's data for the second page of the days of a month
INTERVALS = (5, 10, 15, 20, 30, 120, 180, 240, 360, 720) # minutes between a repeat's runs, as every... offers them
MINUTES = tuple(range(0, 60, 5)) # the minutes Add offers
MOST_DAYS = {'discord': 20} # days of the month on a page: Discord takes 25 buttons, elsewhere all 31
MOST_REPORTS = {'discord': 16} # Add's reports on a page, four to a row: Discord takes five rows, elsewhere all
YEARS = 10 # the years a one-off may be in, this one first
CROWDED = 20 # a screen of more choices takes them in rows of five, Back last: Discord takes 25 buttons

def jobs_screen(service, chat, screen='top', page=0, note=None, highlight=None):
	"""A screen of the .jobs menu that lists a chat's jobs (by its key), numbered, each struck through and marked ❌
	when it is off, * where it has never run, its name and its schedule in words, by the timezone setting's clock
	(lib/when.py), then the key to the marks shown. top has what can be done in one row (+ to add, and where there is
	a job to act on, Edit, Run, Upcoming) and how + is typed, in italics; edit and run a button for each job, which
	switches it on or off, or runs it now. A page at a time, as many jobs as a message of the network takes (◀ and ▶
	for the others), after a note of what the last press did. A one-off gone by is deleted first. Returns (lines,
	buttons). The job numbered `highlight` is in bold with a 👉 before it, on its page."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running'], None
	scheduler.prune(chat)
	own = scheduler.chat_jobs(chat)
	running, local, now = scheduler.running(chat), formats.zone().key, scheduler.clock()
	entries = [(number, job, job_entry(service, scheduler, number, job, running, local, now))
		for number, job in enumerate(own, 1)]
	if highlight:
		entries = [(number, job, f'👉 {service.bold(line)}' if number == highlight else line)
			for number, job, line in entries]
	parts = paged(entries, service)
	if highlight:
		page = next((i for i, part in enumerate(parts) if any(number == highlight for number, _, _ in part)), page)
	page = min(max(page, 0), len(parts) - 1)
	shown = parts[page]
	span = f' ({shown[0][0]}–{shown[-1][0]} of {len(own)})' if len(parts) > 1 else ''
	lines = ([note, ''] if note else []) + [service.bold(HEADINGS[screen] + span)]
	if not own:
		lines.append('No jobs here: + adds one')
	if shown:
		lines += grouped(service, shown)
	if not all(scheduler.has_run(job) for _, job, _ in shown):
		lines += ['', NOT_RUN]
	if screen == 'top':
		lines += ['', *(service.italic(service.escape(line)) for line in ADD_TYPED)]
	return lines, screen_buttons(screen, page, len(parts), shown, jobs.list_checksum(own), own)

def grouped(service, shown):
	"""The entries (number, job, line) as lines: the jobs of each report, or the reminders, under a heading of their
	own, a blank line before each heading."""
	lines, section = [], None
	for _, job, line in shown:
		kind = 'Reminders' if job.action == 'message' else job.action.capitalize()
		if kind != section:
			lines += ['', service.bold(kind)]
			section = kind
		lines.append(line)
	return lines

def listed_with(service, chat, lines):
	"""A screen's lines (an Add step's) with the chat's job list under them, to show it while a job is added: as many
	jobs as fit a message of the network with the screen, then how many more there are."""
	scheduler = jobs.current
	if scheduler is None:
		return lines
	own = scheduler.chat_jobs(chat)
	running, local, now = scheduler.running(chat), formats.zone().key, scheduler.clock()
	room = service.text_limit - len('\n'.join(lines)) - PAGE_ROOM // 2
	shown, size = [], 0
	for number, job in enumerate(own, 1):
		line = job_entry(service, scheduler, number, job, running, local, now)
		size += len(line) + 1
		if size > room or len(shown) == MOST_JOBS.get(service, 40):
			break
		shown.append((number, job, line))
	if not shown:
		return lines
	more = [f'…and {len(own) - len(shown)} more'] if len(shown) < len(own) else []
	return [*lines, '', service.bold('Jobs'), *grouped(service, shown)[1:], *more]

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

def screen_buttons(screen, page, pages, shown, crc, own):
	"""A list screen's buttons: top's, what can be done (+; Edit and Run with any job, Upcoming with one on), in one
	row; edit's and run's, a button for each job shown, '<number> <name>', JOB_ROW to a row, edit's red for a job that
	is off, then OK and, while any job is off, Delete disabled jobs (edit), or Cancel (run); ◀ and ▶ to the other
	pages."""
	if screen == 'top':
		possible = [('+', 'add', [])] + [(label, kind, args) for label, kind, args, there in (
			('Edit', 'edit', [0], bool(own)), ('Run', 'run', [0], bool(own)),
			('Upcoming', 'next', [], any(job.on for job in own))) if there]
		rows = [[buttons.menu_button(label, kind, args, crc) for label, kind, args in possible]]
		nav = []
	else: # edit or run: a button per job
		rows = buttons.chunks([buttons.menu_button(f'{number} {job.name}', screen, [page, number], crc,
			buttons.tone(job.on) if screen == 'edit' else '') for number, job, _ in shown], JOB_ROW)
		nav = [buttons.menu_button('OK' if screen == 'edit' else 'Cancel', 'top', [0], crc)]
		if screen == 'edit' and not all(job.on for job in own):
			nav.append(buttons.menu_button('Delete disabled jobs', screen, [page, 'ask'], crc))
	nav += buttons.page_buttons(page, pages, lambda label, to: buttons.menu_button(label, screen, [to], crc))
	return rows + ([nav] if nav else [])

def delete_disabled_screen(service, chat, page=0):
	"""Delete disabled jobs' question, for a chat (by its key): whether to delete the jobs that are off, listed, with
	Yes, delete them and Cancel, back to the editing."""
	own = jobs.current.chat_jobs(chat)
	off = [(number, job) for number, job in enumerate(own, 1) if not job.on]
	crc = jobs.list_checksum(own)
	return [service.bold(f"Delete the {len(off)} disabled job{'' if len(off) == 1 else 's'}?"), '',
		*(f"{number}. ❌ {service.strike(service.escape(job.name))}" for number, job in off)], [[
		buttons.menu_button('Yes, delete them', 'edit', [page, 'yes'], crc),
		buttons.menu_button('Cancel', 'edit', [page], crc)]]

def job_entry(service, scheduler, number, job, running=(), local=None, now=None):
	"""'5. movers close AU · weekdays at 4:30pm Sydney': a job in .jobs, with its number, * where it has never run, its
	name and its schedule in words, and whether it is running; one that is off has a ❌ before them and is struck
	through."""
	never = '' if scheduler.has_run(job) else '*'
	schedule = job.schedule.describe(local or formats.zone().key, now or scheduler.clock())
	body = f"{service.escape(job.name)} · {schedule}"
	shown = f"{never} {body}" if job.on else f"❌{never} {service.strike(body)}"
	shown = shown.lstrip()
	return f"{number}. {shown}" + (' (running)' if job.key in running else '')

def job_line(service, number, job, outcome):
	"""'3. trades: done': a job's number in the .jobs list, its name, and how its run went."""
	return f"{number}. {service.escape(job.name)}: {outcome}"

def next_screen(service, chat, count=20):
	"""`.jobs upcoming`: a chat's next runs, in time order, at most count, each by the timezone setting's clock
	(and its own zone's beside it, where that differs), with its number and name in .jobs; a repeat's runs on a day
	are one entry, from its first to its last. Returns (lines, buttons): Back, to the list."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running'], None
	local = formats.zone()
	lines = [service.bold('Upcoming runs:')]
	for first, last, job, number in scheduler.upcoming(chat, count):
		said = moment_words(first, local, job.schedule.tz)
		if job.schedule.every:
			end = last.astimezone(local)
			said += (f" – {clock_words(end, local)}" if end.date() == first.astimezone(local).date() else
				f" – {moment_words(last, local)}") + f", {when.repeat_words(job.schedule.every, 0, local.key == 'UTC')}"
		lines.append(f"{said} · {number}. {service.escape(job.name)}")
	if len(lines) == 1:
		lines.append('None: every job here is off')
	return lines, [[buttons.menu_button('Back', 'top', [0], jobs.list_checksum(scheduler.chat_jobs(chat)))]]

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
	"""A step of Add, from the choices made so far (steps, from the button pressed: the report's number, how often,
	then the LEVELS of that frequency in turn): (lines, buttons) of the next choice, its default marked †, or (None,
	(action, arguments, schedule)) once every choice is made, by the timezone setting's clock. Cancel goes back to
	the list, and Back, after the report, a step back. Raises ValueError for choices that are none (forged data, or an
	older finbot's)."""
	scheduler = jobs.current
	crc, local = jobs.list_checksum(scheduler.chat_jobs(chat)), formats.zone()
	today = scheduler.clock().astimezone(local).date()
	steps, page = list(steps), 0
	if steps and steps[-1] == MORE:
		steps, page = steps[:-1], 1
	back = buttons.menu_button('Back', 'add', steps[:-1], crc)
	cancel = buttons.menu_button('Cancel', 'top', [0], crc)
	def choices(heading, offer, row, lines=(), usual=None, nav=None):
		"""A choice's screen: its heading and lines, and '† indicates default' in italics where one is (usual: its
		data); its buttons (label, data), `row` to a row, the default's label marked †; then Back and Cancel (or nav).
		More than CROWDED choices, with no nav of their own, go in rows of five with Back last."""
		tapped = [buttons.menu_button(label + ('†' if data == usual else ''), 'add', [*steps, data], crc)
			for label, data in offer]
		key = [] if usual is None else ['', service.italic('† indicates default')]
		text = [service.bold(heading), *lines, *key]
		if nav is None and len(tapped) > CROWDED:
			return text, buttons.chunks([*tapped, back], 5)
		return text, buttons.chunks(tapped, row) + [nav or [back, cancel]]
	def turn(more):
		"""The ◀ or ▶ of a choice that may take two pages (more: whether it does); MORE ending the steps asks for the
		second."""
		return buttons.page_buttons(page, 2 if more else 1, lambda label, to: buttons.menu_button(label, 'add',
			[*steps, MORE] if to else steps, crc))
	reports = add_reports()
	if not steps: # a button per report, by its name alone (none that reports on Sharesight without it), and Cancel
		offer = [(label, number) for number, (label, action, _) in enumerate(reports, 1)
			if sharesight.configured() or action not in catalog.SHARESIGHT]
		most = MOST_REPORTS.get(service, len(offer))
		if page * most >= len(offer):
			raise ValueError('no such page')
		nav = turn(len(offer) > most) + [cancel]
		return choices('Add a job: which report?', offer[page * most:(page + 1) * most], 4 if service in
			MOST_REPORTS else 3, nav=nav)
	label, action, args = reports[choice(steps[0], 1, len(reports)) - 1]
	if action == 'message':
		return [service.bold('Add a reminder'), "A reminder's text is what you type:",
			'.jobs add reminder SCHEDULE "TEXT"', '', service.bold('For example:'),
			'.jobs add reminder every 31 mar at 8:30am "🥳 Happy EOFY"',
			'.jobs add reminder on 28 oct 2026 "ubank draw 6/6"'], [[back, cancel]]
	command = jobs.command_actions().get(action)
	if command and command.needs: # what it is about, a stock or a portfolio, comes from typing, not a button
		return [service.bold(f'Add {label}'), f'What {label} is about is typed:',
			f'.jobs add {action} {command.ARGUMENTS} SCHEDULE', '', service.bold('For example:'),
			f'.jobs add {action} {example(command.ARGUMENTS)} weekly'], [[back, cancel]]
	if len(steps) == 1:
		return choices(f'Add {label}: how often?', [(name, code) for code, name in FREQUENCIES], 3,
			usual=USUAL['frequency'])
	frequency, made = steps[1], steps[2:]
	levels = levels_of(frequency, made)
	if len(made) > len(levels) or (page and levels[len(made):len(made) + 1] != ('day',)):
		raise ValueError('no such choices')
	values = {'interval': 60} if frequency == 'h' else {}
	for level, data in zip(levels, made):
		values[level] = chosen(level, data, frequency, values, today)
	if len(made) == len(levels):
		schedule = built(frequency, values, local.key)
		return None, (action, list(args) if args is not None else catalog.period_args(action, schedule), schedule)
	level, said = levels[len(made)], so_far(frequency, values)
	found, usual = offered(level, frequency, values, today)
	offer = [(text, data) for text, data, _ in found]
	if level == 'day':
		most = MOST_DAYS.get(service, 31)
		if page * most >= len(offer):
			raise ValueError('no such page')
		nav = turn(len(offer) > most) + [back, cancel]
		question = 'on which day?' if frequency == 'o' else 'on which day of the month?'
		return choices(f'Add {label}, {said}: {question}', offer[page * most:(page + 1) * most], 5,
			['A month without that day has no run'] if frequency in 'mqb' else [], usual, nav)
	if level == 'interval':
		return choices(f'Add {label}: every...', offer, 4, ['A span across days is typed: .jobs add REPORT every 20'
			' mins from mon 9am to sat 3pm'], usual)
	clock = [f"By {when.place(local.key)}'s clock"]
	month = ('in which month?', 4, []) if frequency == 'o' else ('start month?', 4, CYCLE_NOTES.get(frequency, []))
	question, row, lines = {'year': ('in which year?', 5, []), 'month': month,
		'weekday': ('on which day?', 4, []), 'hour': ('at what hour?', 5, clock), 'minute': ('at what time?', 4, []),
		'repeat': ('on which days?', 2, []), 'start hour': ('start hour?', 5, clock),
		'start minute': ('start minute?', 4, []), 'end': ('end time?', 4, [])}[level]
	return choices(f'Add {label}, {said}: {question}', offer, row, lines, usual)

def add_reports():
	"""What Add offers a job to run: the reports (REPORTS), then the commands of .help a job may run, in its order (buy
	and sell as one), each (label, action, arguments; None where the period follows how often it runs). Each one's
	place in this list is its button's data, whichever are offered."""
	commands = []
	for name, command in jobs.command_actions().items():
		if command.listed and name != 'sell':
			name = 'buy&sell' if name == 'buy' else name
			commands.append((name.replace('&', ' & '), name, ()))
	return REPORTS + tuple(commands)

def example(arguments):
	"""What a command's arguments may be, for an example: its words outside brackets, each SYMBOL a ticker in turn and
	PORTFOLIO a portfolio's name (the first that Sharesight's cache has, else Growth)."""
	tickers, names = iter(('AAPL', 'MSFT', 'GOOG')), sharesight.cached()[0] + ['Growth']
	return ' '.join(next(tickers) if word == 'SYMBOL' else names[0] if word == 'PORTFOLIO' else word
		for word in re.sub(r'\[[^\]]*\]', '', arguments).split())

def levels_of(frequency, made):
	"""The choices Add asks for after how often (LEVELS), as far as those made say: every... asks a weekday's hour and
	minute once its interval is a weekday. Raises ValueError for a frequency that is none."""
	if frequency not in LEVELS:
		raise ValueError(f'no frequency {frequency!r}')
	return ('interval', 'hour', 'minute') if frequency == 'r' and made[:1] == [WEEKDAY] else LEVELS[frequency]

def offered(level, frequency, values, today):
	"""What a level of Add offers, from the choices before it (values) and today's date (a one-off's): its choices,
	[(label, data, value)] (what each button shows, the data it carries, and what it means), and the default's data."""
	if level == 'year':
		return [(str(year), str(year), year) for year in range(today.year, today.year + YEARS)], str(today.year)
	if level == 'month':
		first = today.month if frequency == 'o' and values['year'] == today.year else 1
		months = [(when.MONTHS[month - 1].title(), str(month), month) for month in range(first, 13)]
		return months, str(first) if frequency == 'o' else USUAL[level]
	if level == 'day':
		if frequency == 'o': # the days the month has, from today on
			year, month = values['year'], values['month']
			first = today.day if (year, month) == (today.year, today.month) else 1
			days = range(first, calendar.monthrange(year, month)[1] + 1)
			tomorrow = today + datetime.timedelta(days=1)
			usual = tomorrow.day if (tomorrow.year, tomorrow.month) == (year, month) else first
		else: # annual: the days its month has, in a leap year; else every day a month may have
			last = {2: 29, 4: 30, 6: 30, 9: 30, 11: 30}.get(values['month'], 31) if frequency == 'a' else 31
			days, usual = range(1, last + 1), USUAL[level]
		return [(str(day), str(day), day) for day in days], str(usual)
	if level in ('hour', 'start hour'):
		return [(f'{hour:02d}', str(hour), hour) for hour in range(24)], USUAL[level]
	if level in ('minute', 'start minute'):
		hour = f"{values['hour']:02d}" if level == 'minute' else ''
		return [(f'{hour}:{minute:02d}', str(minute), minute) for minute in MINUTES], USUAL[level]
	if level == 'weekday':
		return [(day.title(), str(number), number) for number, day in enumerate(when.DAYS)], USUAL[level]
	if level == 'interval':
		return [(when.repeat_words(minutes, 0, False).removeprefix('every '), str(minutes), minutes)
			for minutes in INTERVALS] + [('weekday', WEEKDAY, WEEKDAY)], USUAL[level]
	if level == 'repeat':
		return [('every day', 'd', 'daily'), ('weekdays', 'k', 'weekdays')], USUAL[level]
	# the end: each run after the start, a step apart (an hour, where it repeats more often), or the end of the day
	start, step = values['start hour'] * 60 + values['start minute'], max(values['interval'], 60)
	return [(when.clock24(end), str(end), end) for end in range(start + step, when.DAY_MINUTES, step)] + [
		('end of day', END, None)], USUAL[level]

def chosen(level, data, frequency, values, today):
	"""What a choice at a level of Add means, from its button's data, among what that level offers (offered). Raises
	ValueError for one it does not offer."""
	for _, offer, value in offered(level, frequency, values, today)[0]:
		if data == offer:
			return value
	raise ValueError(f'no {level} {data!r}')

def so_far(frequency, values):
	"""How often a job being added runs, as far as it is chosen: 'once, Oct 2026', 'weekly, Fridays', 'quarterly,
	Feb/May/Aug/Nov', 'hourly at :05, weekdays from 10am'."""
	if values.get('interval') not in (None, WEEKDAY):
		start = values.get('start hour', 0) * 60 + values.get('start minute', 0)
		return when.Schedule(values.get('repeat', 'daily'), every=values['interval'], start=start or None).words(False)
	if frequency == 'r':
		return 'weekdays' if values.get('interval') == WEEKDAY else 'every...'
	if frequency == 'o':
		if 'day' in values:
			return 'once, ' + when.date_words(datetime.date(values['year'], values['month'], values['day']))
		if 'month' in values:
			return f"once, {when.MONTHS[values['month'] - 1].title()} {values['year']}"
		return f"once, {values['year']}" if 'year' in values else 'once'
	if 'weekday' in values:
		return f"weekly, {when.plural(when.DAYS[values['weekday']])}"
	if frequency in CYCLES and 'month' in values:
		months = when.cycle(values['month'], CYCLES[frequency])
		if 'day' in values:
			return when.days_words({'day': values['day'], 'months': months})
		names = [when.MONTHS[month - 1].title() for month in months]
		return dict(FREQUENCIES)[frequency] + ', ' + {'b': ' and '.join(names), 'a': f'in {names[0]}'}.get(frequency,
			'/'.join(names))
	if 'day' in values:
		return when.days_words({'day': values['day'], 'months': ()})
	return dict(FREQUENCIES)[frequency]

def built(frequency, values, zone):
	"""The when.Schedule that Add's choices make (values), in zone. Raises ScheduleError for one that cannot be."""
	if values.get('interval') not in (None, WEEKDAY): # hourly, or every so many minutes or hours
		start = values['start hour'] * 60 + values['start minute']
		schedule = when.Schedule(values['repeat'], every=values['interval'], start=start or None, end=values['end'],
			zone=zone)
	else:
		if frequency == 'o':
			days = {'date': datetime.date(values['year'], values['month'], values['day']).isoformat()}
		elif frequency == 'w':
			days = (when.DAYS[values['weekday']],)
		elif frequency in CYCLES:
			days = {'day': values['day'], 'months': when.cycle(values['month'], CYCLES[frequency])}
		elif frequency == 'm':
			days = {'day': values['day'], 'months': ()}
		else:
			days = 'weekdays' if frequency == 'r' else 'daily'
		schedule = when.Schedule(days, at=values['hour'] * 60 + values['minute'], zone=zone)
	schedule.check()
	return schedule

def choice(text, low, high):
	"""A choice's number from a button's data, from low to high. Raises ValueError for one that is none."""
	if not (text.isascii() and text.isdigit() and low <= int(text) <= high):
		raise ValueError(f'no choice {text!r}')
	return int(text)

def added_screen(service, chat, number):
	"""What the last step of Add shows: the whole list, the job added pointed to (👉) and in bold, with the buttons of
	the list (+ adds another)."""
	return jobs_screen(service, chat, 'top', 0, 'Added', number)

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
	"""`.jobs add` alone: what a job can run (the reports, then the commands of .help), each with what it takes, and
	examples."""
	known = jobs.actions()
	return [service.bold('What a job can run:')] + [f"{'reminder' if name == 'message' else name} "
		f"{known[name].ARGUMENTS}".strip() for name in jobs.chat_actions()] + ['', service.bold('For example:'),
		'.jobs add movers weekly',
		'.jobs add movers close weekdays at 4:30pm New York', '.jobs add performance first day of each month at 9am',
		'.jobs add trades every 20 mins weekdays from 10am to 4pm', '.jobs add peg top weekly',
		'.jobs add price AAPL MSFT 1y monthly', '.jobs add reminder every 31 mar at 8:30am "🥳 Happy EOFY"', '',
		f"Times are by {when.place(formats.zone().key)}'s clock unless one names a zone (UTC, New York, EST);"
		" performance and movers cover the days between runs"]

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
