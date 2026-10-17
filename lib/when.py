"""Schedules of finbot's own, in place of cron: which days a job runs, which times on those days, and the time zone
they are in. A schedule is kept as JSON in its job (to_json, from_json); parse() reads what a chat types ("weekly at
9am", "every 20 mins weekdays from 10am to 9pm New York"), describe() says it back in words, and next_after() gives
the next run. Unlike cron, one schedule holds a span across days ("every 20 mins, Mon 9am – Sat 3pm")."""
import dataclasses
import datetime
import functools
import json
import re
import zoneinfo

UTC = zoneinfo.ZoneInfo('UTC')
MINUTE = datetime.timedelta(minutes=1)
DAY_MINUTES = 1440
WEEK = 7 * DAY_MINUTES
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
DEFAULT_AT = 9 * 60 # a schedule's time of day where none is typed: 9am
ZONE_WORDS = { # what people call a zone -> the zone, with its daylight saving: EST is New York's clock all year
	'utc': 'UTC', 'gmt': 'Europe/London', 'bst': 'Europe/London', 'uk': 'Europe/London',
	'et': 'America/New_York', 'est': 'America/New_York', 'edt': 'America/New_York',
	'ct': 'America/Chicago', 'cst': 'America/Chicago', 'cdt': 'America/Chicago',
	'pt': 'America/Los_Angeles', 'pst': 'America/Los_Angeles', 'pdt': 'America/Los_Angeles',
	'cet': 'Europe/Paris', 'cest': 'Europe/Paris', 'hkt': 'Asia/Hong_Kong', 'jst': 'Asia/Tokyo',
	'aet': 'Australia/Sydney', 'aest': 'Australia/Sydney', 'aedt': 'Australia/Sydney'}
AREAS = ('Africa', 'America', 'Antarctica', 'Asia', 'Atlantic', 'Australia', 'Europe', 'Indian', 'Pacific')
EXAMPLES = ('daily at 9am', 'weekdays at 4:30pm', 'every saturday at 9am', 'first day of each month at 9am',
	'quarterly', 'quarterly from feb on the 15th', 'every 20 mins weekdays from 10am to 9pm', 'every 31 mar',
	'on 28 oct 2026', 'weekdays at 4:30pm New York')
TIME = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?'
DAY = r'(mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday|r|s)?s?'
MONTH = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(?:uary|ruary|ch|il|e|y|ust|tember|t|ober|ember)?'
OF_MONTH = r'(?: of (?:each|the|every) month)?'


class ScheduleError(ValueError):
	"""A schedule, or a job, that cannot be: its text is said to the chat that asked for it."""


@dataclasses.dataclass(frozen=True)
class Schedule:
	"""When a job runs: on which days (days: 'daily', 'weekdays', a tuple of DAYS, {'day': n, 'months': (...)}, monthly
	where months is empty, or {'date': 'YYYY-MM-DD'}, once); at which times on them (at, a minute of the day; or every
	so many minutes, counted from midnight, from start to end where given, both included); or in place of both a span
	from a minute of the week to another (span, with every); and the zone those are in."""
	days: object = 'daily'
	at: int = None
	every: int = None
	start: int = None
	end: int = None
	span: tuple = None
	zone: str = 'UTC'

	@property
	def tz(self):
		"""The schedule's zone, as zoneinfo has it."""
		return zoneinfo.ZoneInfo(self.zone)

	@property
	def key(self):
		"""The schedule as one string, the same for equal schedules: part of its job's key."""
		return json.dumps(self.to_json(), sort_keys=True, ensure_ascii=False)

	def to_json(self):
		"""The schedule as its job keeps it: plain JSON, its times as 'HH:MM'."""
		days, data = self.days, {}
		if self.span:
			data['span'] = [f'{DAYS[m // DAY_MINUTES]} {clock24(m % DAY_MINUTES)}' for m in self.span]
		elif isinstance(days, tuple):
			data['days'] = list(days)
		elif isinstance(days, dict) and 'day' in days:
			data['days'] = {'day': days['day'], **({'months': list(days['months'])} if days['months'] else {})}
		else:
			data['days'] = dict(days) if isinstance(days, dict) else days
		for name, value in (('at', self.at), ('from', self.start), ('to', self.end)):
			if value is not None:
				data[name] = clock24(value)
		if self.every is not None:
			data['every'] = self.every
		data['zone'] = self.zone
		return data

	@classmethod
	def from_json(cls, data):
		"""The schedule a job keeps (to_json). Raises ScheduleError for anything that is not one."""
		try:
			days = data.get('days', 'daily')
			if isinstance(days, list):
				days = tuple(sorted(set(days), key=DAYS.index))
			elif isinstance(days, dict):
				days = {'date': days['date']} if 'date' in days else {'day': days['day'],
					'months': tuple(sorted(set(days.get('months', ()))))}
			span = tuple(week_minute(part) for part in data['span']) if 'span' in data else None
			times = {name: None if data.get(name) is None else minutes(data[name]) for name in ('at', 'from', 'to')}
			schedule = cls(days, times['at'], data.get('every'), times['from'], times['to'], span,
				data.get('zone', 'UTC'))
		except (AttributeError, KeyError, TypeError, ValueError) as e:
			raise ScheduleError(f'not a schedule: {data!r} ({e})') from None
		schedule.check()
		return schedule

	def check(self):
		"""Raise ScheduleError unless the schedule can be: a zone zoneinfo knows, days and times that are some."""
		try:
			problem = self.problem()
		except (AttributeError, KeyError, TypeError, ValueError) as e:
			problem = f'not a schedule ({e})'
		if problem:
			raise ScheduleError(problem)

	def problem(self):
		"""What makes the schedule one that cannot be, or None."""
		try:
			zoneinfo.ZoneInfo(self.zone)
		except (TypeError, ValueError, KeyError):
			return f'no time zone {self.zone!r}'
		if (self.at is None) == (self.every is None):
			return 'a schedule runs at a time of day, or every so many minutes'
		if any(value is not None and not (whole(value) and 0 <= value < DAY_MINUTES)
				for value in (self.at, self.start, self.end)):
			return 'no such time of day'
		if self.every is not None and not (whole(self.every) and 1 <= self.every <= DAY_MINUTES):
			return 'every 1 minute to every 24 hours'
		if self.span is not None:
			if self.every is None or self.days != 'daily' or self.start is not None or self.end is not None:
				return 'a span of days runs every so many minutes, and says its days itself'
			if len(self.span) != 2 or self.span[0] == self.span[1] or not all(whole(m) and 0 <= m < WEEK
					for m in self.span):
				return 'no such span of days'
			return None
		days = self.days
		if days in ('daily', 'weekdays'):
			return None
		if isinstance(days, tuple):
			return None if days and len(set(days)) == len(days) and set(days) <= set(DAYS) else f'no days {days!r}'
		if isinstance(days, dict) and set(days) == {'date'}:
			datetime.date.fromisoformat(days['date'])
			return None
		if (isinstance(days, dict) and set(days) == {'day', 'months'} and whole(days['day']) and 1 <= days['day'] <= 31
				and isinstance(days['months'], tuple) and all(whole(m) and 1 <= m <= 12 for m in days['months'])):
			return None
		return f'no days {days!r}'

	def day_ok(self, day):
		"""Whether the schedule runs on this date at all (a span on every date, at the minutes times() gives)."""
		days = self.days
		if self.span or days == 'daily':
			return True
		if days == 'weekdays':
			return day.weekday() < 5
		if isinstance(days, tuple):
			return DAYS[day.weekday()] in days
		if 'date' in days:
			return day.isoformat() == days['date']
		return day.day == days['day'] and (not days['months'] or day.month in days['months'])

	def times(self, day):
		"""The minutes of this date at which the schedule runs, earliest first."""
		if not self.day_ok(day):
			return []
		if self.at is not None:
			return [self.at]
		if self.span:
			start, end = self.span
			base = day.weekday() * DAY_MINUTES
			return [m for m in range(0, DAY_MINUTES, self.every) if within(base + m, start, end)]
		start = self.start or 0
		end = DAY_MINUTES - 1 if self.end is None else self.end
		return [m for m in range(start % self.every, DAY_MINUTES, self.every) if within(m, start, end)]

	def dates(self, first):
		"""The dates from first on that the schedule may run on, in order, as far ahead as its next run can be: a week
		for days of the week, nine years for a day of some months (29 February), the date itself for a one-off."""
		days = self.days
		if isinstance(days, dict) and not self.span:
			if 'date' in days:
				date = datetime.date.fromisoformat(days['date'])
				return [date] if date >= first else []
			return month_days(first, days['day'], days['months'] or range(1, 13))
		return (first + datetime.timedelta(days=n) for n in range(8))

	def next_after(self, moment):
		"""The schedule's first run after moment (an aware datetime), in UTC (a time its zone repeats compares equal to
		no other zone's); None when it has none (a one-off gone by). A time the clocks skip runs as they reach the first
		minute after the gap; a time they repeat runs once, the first time."""
		zone, after = self.tz, moment.astimezone(UTC)
		local = moment.astimezone(zone)
		earliest = local.hour * 60 + local.minute - 120 # today's minutes before that have gone, daylight saving or not
		for day in self.dates(local.date()):
			for minute in self.times(day):
				if day == local.date() and minute < earliest:
					continue
				run = arrival(day, minute, zone)
				if run > after:
					return run
		return None

	@property
	def frequency(self):
		"""How often its days come round, in a word: daily, weekdays, weekly, monthly, quarterly, bi-annual, annual or
		once; None for other days (several weekdays, other months) and for a span."""
		days = self.days
		if self.span or isinstance(days, str):
			return None if self.span else days
		if isinstance(days, tuple):
			return 'weekly' if len(days) == 1 else None
		if 'date' in days:
			return 'once'
		return month_kind(days['months'])

	def describe(self, local, now=None):
		"""The schedule in words, by its own zone's clock: plain where that is local (the zone's name), in 24 hours with
		"UTC" after it where it is UTC, else with the zone's place after it and, where the local clock differs at the
		next run after now, its times in parentheses: "weekdays at 12:45pm New York (3:45am local, Tue–Sat)"."""
		if self.zone == local:
			return self.words(False)
		if self.zone == 'UTC':
			return self.words(True) + ' UTC'
		return f"{self.words(False)} {place(self.zone)}{self.aside(local, now)}"

	def words(self, utc):
		"""The schedule in words, its times as its zone's clock has them (in 24 hours where utc)."""
		if self.at is not None:
			return f"{days_words(self.days)} at {clock(self.at, utc)}"
		if self.span:
			return f"{repeat_words(self.every, 0, utc)}, {span_words(self.span, utc)}"
		head, window = self.repeat(utc)
		tail = ' '.join(part for part in ('' if self.days == 'daily' else repeat_days(self.days), window) if part)
		return f"{head}, {tail}" if tail else head

	def repeat(self, utc, gap=0):
		"""A repeat's words, (how often, its window of hours or ''), the window moved by gap minutes."""
		start, end = self.start or 0, self.end
		if end is None and start < self.every: # where in each step it runs, not a window
			return repeat_words(self.every, start, utc), ''
		offset = start % 60 if self.every % 60 == 0 else 0
		low = bound(start - offset + gap, utc)
		window = f"from {low}" if end is None else f"{low}–{bound(end - offset + gap, utc)}"
		return repeat_words(self.every, offset, utc), window

	def aside(self, local, now):
		"""' (3:45am local, Tue–Sat)': the times as the local clock reads them at the next run, where it differs from
		the zone's; '' where they agree, and for a repeat with no window."""
		run = self.next_after(now or datetime.datetime.now(UTC))
		if run is None:
			return ''
		here, there = run.astimezone(self.tz), run.astimezone(zoneinfo.ZoneInfo(local))
		gap = int((there.utcoffset() - here.utcoffset()).total_seconds()) // 60
		utc, days = local == 'UTC', ''
		if not gap:
			return ''
		if self.at is not None:
			text = clock(there.hour * 60 + there.minute, utc)
			days = shifted(self.days, (there.date() - here.date()).days)
		elif self.span:
			text = span_words(tuple((m + gap) % WEEK for m in self.span), utc)
		else:
			text = self.repeat(utc, gap)[1]
		if not text:
			return ''
		return f" ({text} {'UTC' if utc else 'local'}{', ' + days if days else ''})"


def whole(value):
	"""Whether value is a whole number (True and False are not)."""
	return isinstance(value, int) and not isinstance(value, bool)


def within(value, low, high):
	"""Whether value is from low to high, both included, where high may come round again before low (a night)."""
	return low <= value <= high if low <= high else value >= low or value <= high


def month_days(first, day, months):
	"""The dates on that day of those months, from first on, for nine years."""
	for index in range(first.year * 12 + first.month - 1, (first.year + 9) * 12):
		year, month = divmod(index, 12)
		if month + 1 in months:
			try:
				date = datetime.date(year, month + 1, day)
			except ValueError: # no such day that month (the 31st, 29 February)
				continue
			if date >= first:
				yield date


def arrival(day, minute, zone):
	"""When a date's minute comes in a zone, in UTC: one the clocks skip comes as they reach the first minute after the
	gap; one they repeat, the first time."""
	wall = datetime.datetime.combine(day, datetime.time(minute // 60, minute % 60))
	moment = wall.replace(tzinfo=zone).astimezone(UTC)
	if moment.astimezone(zone).replace(tzinfo=None) == wall:
		return moment
	moment = wall.replace(tzinfo=zone, fold=1).astimezone(UTC) # before the gap, by its length
	offset = moment.astimezone(zone).utcoffset()
	for _ in range(DAY_MINUTES):
		moment += MINUTE
		if moment.astimezone(zone).utcoffset() != offset:
			break
	return moment


def minutes(text):
	"""'08:30' -> 510. Raises ValueError for no time of day."""
	hours, _, mins = text.partition(':')
	value = int(hours) * 60 + int(mins)
	if not (len(mins) == 2 and 0 <= int(mins) < 60 and 0 <= value < DAY_MINUTES):
		raise ValueError(f'no time {text!r}')
	return value


def week_minute(text):
	"""'mon 09:00' -> the minute of the week, from Monday midnight."""
	day, time = text.split()
	return DAYS.index(day) * DAY_MINUTES + minutes(time)


def clock24(minute):
	"""510 -> '08:30'."""
	return f'{minute // 60:02d}:{minute % 60:02d}'


def clock(minute, utc):
	"""A time of day as shown: '8:30am', '12:45pm'; '21:30' in 24 hours, for UTC."""
	if utc:
		return clock24(minute)
	hour, mins = divmod(minute, 60)
	return f"{hour % 12 or 12}:{mins:02d}{'am' if hour < 12 else 'pm'}"


def bound(minute, utc):
	"""The end of a window or span as shown: '10am', '9:30pm' ('10:00' for UTC); any minute, as the clock reads it."""
	minute %= DAY_MINUTES
	if utc:
		return clock24(minute)
	hour, mins = divmod(minute, 60)
	return f"{hour % 12 or 12}{f':{mins:02d}' if mins else ''}{'am' if hour < 12 else 'pm'}"


def repeat_words(every, offset, utc):
	"""How often a repeat runs, and where its steps fall (offset, minutes after midnight): 'every 20 mins', 'every 30
	mins from :14', 'hourly at :01', 'every 8 hours at :07', 'every 2 hours from 1am'."""
	hours = every % 60 == 0
	text = ('every minute' if every == 1 else f'every {every} mins' if not hours else 'hourly' if every == 60
		else f'every {every // 60} hours')
	if not offset:
		return text
	if offset < 60:
		return f"{text} {'at' if hours else 'from'} :{offset:02d}"
	return f"{text} from {bound(offset, utc)}"


def span_words(span, utc):
	"""'Mon 9am – Sat 3pm': a span from a minute of the week to another."""
	return ' – '.join(f"{DAYS[m // DAY_MINUTES].title()} {bound(m % DAY_MINUTES, utc)}" for m in span)


def ordinal(n):
	"""2 -> '2nd'."""
	return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def plural(day):
	"""'sun' -> 'Sundays'."""
	return DAY_NAMES[DAYS.index(day)] + 's'


def date_words(date):
	"""A date as shown: '28 Oct 2026'."""
	return f"{date.day} {MONTHS[date.month - 1].title()} {date.year}"


def day_list(days):
	"""Some days of the week as shown: ('tue', 'wed', 'thu', 'fri', 'sat') -> 'Tue–Sat', a run of three or more even
	across Sunday ('Sun–Thu'); ('mon', 'thu') -> 'Mon, Thu'; ('sat', 'sun') -> 'weekends'."""
	found = sorted({DAYS.index(day) for day in days})
	if len(found) == 7:
		return 'daily'
	if found == [5, 6]:
		return 'weekends'
	for first in range(len(found) if len(found) >= 3 else 0):
		run = found[first:] + found[:first]
		if all((b - a) % 7 == 1 for a, b in zip(run, run[1:])):
			return f'{DAYS[run[0]].title()}–{DAYS[run[-1]].title()}'
	return ', '.join(DAYS[i].title() for i in found)


def days_words(days):
	"""Which days, in words: 'daily', 'weekdays', 'weekly, Sundays', 'Tue–Sat', 'monthly, the 2nd', 'quarterly, 2
	Jan/Apr/Jul/Oct', 'bi-annual, 2 Jan and 2 Jul', 'annual, 2 Jan', 'once, 28 Oct 2026'."""
	if isinstance(days, str):
		return days
	if isinstance(days, tuple):
		return f'weekly, {plural(days[0])}' if len(days) == 1 else day_list(days)
	if 'date' in days:
		return 'once, ' + date_words(datetime.date.fromisoformat(days['date']))
	day, months = days['day'], days['months']
	names = [MONTHS[m - 1].title() for m in months]
	kind = month_kind(months)
	if kind == 'monthly':
		return f'monthly, the {ordinal(day)}'
	if kind == 'bi-annual':
		return f'bi-annual, {day} {names[0]} and {day} {names[1]}'
	return f"{kind or 'yearly'}, {day} {'/'.join(names)}"


def cycle(start, count):
	"""The months of a cycle that comes count times a year, from its start month (1–12), in order: quarterly from Feb
	is (2, 5, 8, 11), bi-annual from Mar (3, 9)."""
	return tuple(sorted((start - 1 + i * 12 // count) % 12 + 1 for i in range(count)))


def month_kind(months):
	"""How often some months of the year come round, in a word: monthly for none (every month), quarterly for four 3
	apart, bi-annual for two 6 apart, from any month, annual for one; None for others."""
	if not months:
		return 'monthly'
	if len(months) == 1:
		return 'annual'
	if len(months) in (2, 4) and tuple(months) == cycle(months[0], len(months)):
		return 'bi-annual' if len(months) == 2 else 'quarterly'
	return None


def repeat_days(days):
	"""The days a repeat runs on, in words: 'weekdays', 'Saturdays', 'Tue–Sat', 'on the 2nd', 'on 31 Mar'."""
	if isinstance(days, str):
		return days
	if isinstance(days, tuple):
		return plural(days[0]) if len(days) == 1 else day_list(days)
	if 'date' in days:
		return 'on ' + date_words(datetime.date.fromisoformat(days['date']))
	names = '/'.join(MONTHS[m - 1].title() for m in days['months'])
	return f"on {days['day']} {names}" if names else f"on the {ordinal(days['day'])}"


def shifted(days, shift):
	"""The days as a clock `shift` days ahead has them ('weekdays' a day on is 'Tue–Sat'); '' for daily or no shift."""
	if not shift or days == 'daily':
		return ''
	if isinstance(days, dict):
		return 'the day after' if shift > 0 else 'the day before'
	moved = tuple(DAYS[(DAYS.index(day) + shift) % 7] for day in (DAYS[:5] if days == 'weekdays' else days))
	return plural(moved[0]) if len(moved) == 1 else day_list(moved)


def place(zone):
	"""A zone's place, as shown: 'America/New_York' -> 'New York'."""
	return zone.rsplit('/', 1)[-1].replace('_', ' ')


@functools.cache
def zone_names():
	"""(every zone's name in lower case -> the name, every place of the world's areas in lower case -> its zone)."""
	names = sorted(zoneinfo.available_timezones())
	places = {}
	for name in names:
		if name.split('/')[0] in AREAS:
			places.setdefault(place(name).lower(), name)
	return {name.lower(): name for name in names}, places


def zone_named(words):
	"""The zone that words name (a zone's name, a place, or what people call it: EST, AEST; any case), or None."""
	text = ' '.join(words).lower()
	if text in ZONE_WORDS:
		return ZONE_WORDS[text]
	exact, places = zone_names()
	return exact.get(text.replace(' ', '_')) if '/' in text else places.get(text)


def time_of(hours, mins, half):
	"""The minute of the day of a typed time: ('9', None, 'am') -> 540, ('21', '30', None) -> 1290. Raises
	ScheduleError for no time of day."""
	hour, minute = int(hours), int(mins or 0)
	if half:
		if not 1 <= hour <= 12:
			raise ScheduleError(f'no time {hours}{half}')
		hour = hour % 12 + (12 if half == 'pm' else 0)
	if not (0 <= hour < 24 and 0 <= minute < 60):
		raise ScheduleError(f"no time {hours}:{mins or '00'}")
	return hour * 60 + minute


def parse(text, zone, default_at=DEFAULT_AT):
	"""The Schedule that a chat typed ("weekly at 9am", "every 20 mins weekdays from 10am to 9pm New York"), in the
	zone it names last, else in zone (the timezone setting's); at default_at where it says no time. Raises
	ScheduleError, with examples, for what it cannot read."""
	words = text.lower().replace('–', '-').replace('—', '-').replace(',', ' ').split()
	named = None
	for size in (3, 2, 1):
		if len(words) > size and (found := zone_named(words[-size:])):
			named, words = found, words[:-size]
			break
	s = f" {' '.join(words)} "

	def take(pattern):
		"""The match of pattern in what is left of the text, which it then leaves out; None where there is none."""
		nonlocal s
		found = re.search(pattern, s)
		if found:
			s = s[:found.start()] + ' ' + s[found.end():]
		return found

	try:
		days = read_date(take)
		span = window = offset = at = None
		if m := take(rf' (?:from|between) {DAY} {TIME} (?:to|and|-) {DAY} {TIME} '):
			span = (DAYS.index(m[1]) * DAY_MINUTES + time_of(*m.group(2, 3, 4)),
				DAYS.index(m[5]) * DAY_MINUTES + time_of(*m.group(6, 7, 8)))
		elif m := take(rf' (?:from|between) {TIME} (?:to|and|-) {TIME} '):
			window = (time_of(*m.group(1, 2, 3)), time_of(*m.group(4, 5, 6)))
		every = read_every(take)
		if m := take(r' at :(\d{2}) '):
			offset = int(m[1])
		elif m := take(rf' at {TIME} '):
			at = time_of(*m.group(1, 2, 3))
		if days is None:
			days = read_days(take)
		if s.split():
			raise ScheduleError(f"can't read {' '.join(s.split())!r}")
		if days is None and at is None and every is None and span is None:
			raise ScheduleError('no days or times')
		if every is None:
			if span or window or offset is not None:
				raise ScheduleError('a window of hours, a span of days or a minute past the hour goes with a repeat'
					' ("every 20 mins")')
			at = default_at if at is None else at
		elif at is not None:
			raise ScheduleError('a schedule runs at a time, or every so many minutes: not both')
		if span and days is not None:
			raise ScheduleError('a span of days says its days itself')
		start, end = window or (None, None)
		if offset is not None:
			if offset >= 60:
				raise ScheduleError(f'no minute :{offset}')
			start, end = (start or 0) + offset, None if end is None else end + offset
		schedule = Schedule(days or 'daily', at, every, start, end, span, named or zone)
		schedule.check()
	except ValueError as e: # ScheduleError, or a date that is none (31 February)
		raise ScheduleError(f"{e}. For example: {'; '.join(EXAMPLES)}") from None
	return schedule


def read_date(take):
	"""The days of a date that the text says (take() finds and leaves out each phrase): a one-off ('on 28 oct 2026') or
	a date each year ('every 31 mar'); None for neither."""
	if m := take(rf' on (\d{{1,2}}) {MONTH} (\d{{4}}) '):
		return {'date': datetime.date(int(m[3]), MONTHS.index(m[2]) + 1, int(m[1])).isoformat()}
	if m := take(r' on (\d{4})-(\d{2})-(\d{2}) '):
		return {'date': datetime.date(int(m[1]), int(m[2]), int(m[3])).isoformat()}
	if m := take(rf' (?:every|on) (\d{{1,2}}) {MONTH} '):
		day, month = int(m[1]), MONTHS.index(m[2]) + 1
		datetime.date(2024, month, day) # a day that month has, in a leap year
		take(r' (?:annual|annually|yearly|every year) ')
		return {'day': day, 'months': (month,)}
	return None


def read_every(take):
	"""The minutes between the runs of a repeat that the text says ('every 20 mins', 'hourly'), or None."""
	if m := take(r' every (\d+) ?(?:m|min|mins|minute|minutes) '):
		return int(m[1])
	if m := take(r' every (\d+) ?(?:h|hr|hrs|hour|hours) '):
		return int(m[1]) * 60
	if take(r' (?:hourly|every hour) '):
		return 60
	return None


def read_days(take):
	"""The days that the text says (take() finds and leaves out each phrase), or None where it says none."""
	if take(r' (?:daily|every day) '):
		return 'daily'
	if take(r' (?:on )?(?:weekdays|every weekday) '):
		return 'weekdays'
	if take(r' (?:on )?(?:weekends|every weekend) '):
		return ('sat', 'sun')
	if m := take(rf' (?:on )?{DAY}(?: ?- ?| to ){DAY} '):
		first, last = DAYS.index(m[1]), DAYS.index(m[2])
		return tuple(sorted((DAYS[(first + i) % 7] for i in range((last - first) % 7 + 1)), key=DAYS.index))
	if m := take(rf' weekly(?: on {DAY})? '):
		return (m[1] or 'sat',)
	if m := take(rf' (?:every |on )?{DAY} '):
		return (m[1],)
	day = None
	if m := take(rf' (?:on )?the (\d{{1,2}})(?:st|nd|rd|th)?{OF_MONTH} ') or take(
			rf' (?:on )?(\d{{1,2}})(?:st|nd|rd|th){OF_MONTH} '):
		day = int(m[1])
	elif take(r' (?:on )?(?:the )?first (?:day )?of (?:each|the|every) month '):
		day = 1
	if day is not None and not 1 <= day <= 31:
		raise ScheduleError(f'no day {day} of the month')
	start = rf'(?: (?:from|starting(?: in)?) {MONTH})?' # the month a cycle starts in: quarterly from feb
	for pattern, count in ((r' monthly ', 0), (rf' quarterly{start} ', 4), (r' (?:bi-annual|biannual|bi-annually|'
			rf'biannually|half-yearly|semi-annual|semi-annually|twice a year){start} ', 2),
			(rf' (?:annual|annually|yearly|every year){start} ', 1)):
		if m := take(pattern):
			first = MONTHS.index(m[1]) + 1 if count and m[1] else 1
			return {'day': day or 1, 'months': cycle(first, count) if count else ()}
	return None if day is None else {'day': day, 'months': ()}
