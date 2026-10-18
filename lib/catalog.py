"""The default jobs: every chat has them, each switched on until the chat switches it off (.jobs). An item's name says
what it reports on, never when: its schedule (lib/when.py) says that. For performance and movers the period follows how
often the item runs (period_args): quarterly, 90 days. The market reports run in their market's zone, so that they keep
to its session through its daylight saving: pre-market at 7:15am New York, mid-session about halfway through, the close
30 minutes after it. The reminders come from a data file (REMINDERS), each at 8:30am Sydney on its date."""
import dataclasses
import datetime
import re

from lib import config
from lib import formats
from lib import markets
from lib import when
from lib.reports import message

SYDNEY, NEW_YORK, HONG_KONG, LONDON = 'Australia/Sydney', 'America/New_York', 'Asia/Hong_Kong', 'Europe/London'
MORNING = '08:30' # by Sydney's clock: the weekly and longer reports, and the reminders
TUE_SAT = ['tue', 'wed', 'thu', 'fri', 'sat'] # the mornings after a US session
REMINDERS = 'finbot_reminders.json' # the reminders: DATA_DIR's copy, else the one shipped in defaults/ (data_file)
SHARESIGHT = ('trades', 'performance', 'holdings', 'treemap', 'who') # the actions that report on Sharesight
PERIODIC = ('performance', 'movers') # the reports whose period follows how often they run
PERIOD_DAYS = {'daily': 1, 'weekdays': 1, 'weekly': 7, 'monthly': 30, 'quarterly': 90, 'bi-annual': 180, 'annual': 365}
MONEY_CAFE = ('https://www.omnycontent.com/d/playlist/b034de0e-930d-434b-9822-a7140060b2c0/'
	'95d715e5-10a7-4e54-b114-a9b4001be172/c47481a8-e548-4c2b-8592-ad48003dc9c2/podcast.rss')
STOCKTAKE = ('https://www.omnycontent.com/d/playlist/b034de0e-930d-434b-9822-a7140060b2c0/'
	'087f773e-34f7-45fb-a4f2-a78b000c6495/b9e412ea-f1ee-40db-a0f8-aaf5005d790d/podcast.rss')


@dataclasses.dataclass(frozen=True)
class Item:
	"""A default job: its key (in a chat's record of the ones it switched off), the name .jobs shows, the action it runs
	(a name in jobs.ACTIONS) with its arguments, its schedule, and the country it is for (None: every chat's)."""
	key: str
	name: str
	action: str
	args: tuple
	schedule: when.Schedule
	country: str = None


def period_args(action, schedule):
	"""The arguments of performance or movers that make its period follow how often the schedule runs: over the days
	between runs (weekly, 7); for movers daily, on weekdays or on other days, the day's moves (interday), and for
	performance on other days its usual period; [] for any other action."""
	days = PERIOD_DAYS.get(schedule.frequency)
	if action == 'movers':
		return ['interday'] if days in (None, 1) else [str(days)]
	if action == 'performance':
		return [] if days is None else [str(days)]
	return []


def at(days, time=MORNING, zone=SYDNEY):
	"""A schedule at a time of day on some days: at('weekdays', '16:30', NEW_YORK)."""
	return when.Schedule.from_json({'days': days, 'at': time, 'zone': zone})


OLD_NAMES = {'movers': 'price'} # an action renamed keeps its default jobs' keys, which chats' records name

def periodic(frequency, days):
	"""The performance and movers items that run at a frequency, each over the days between its runs, keyed by the
	action's old name where it had one (price-weekly)."""
	schedule = at(days)
	return tuple(Item(f'{OLD_NAMES.get(action, action)}-{frequency}', action, action,
		tuple(period_args(action, schedule)), schedule) for action in PERIODIC)


def reminder(entry):
	"""A reminder's item (a message job), from an entry of REMINDERS: its key, its date ('MM-DD' each year, 'YYYY-MM-DD'
	once; at 8:30am Sydney) and its lines (as a message job takes them); where it is for one country, that country,
	whose flag {flag} becomes (markets.flag); and the name .jobs shows, where it is not its first line. Raises
	ValueError, saying why, for an entry that cannot be one."""
	fields = ('key', 'date', 'lines', 'country', 'name')
	if not isinstance(entry, dict) or set(entry) - set(fields):
		raise ValueError(f'a reminder holds {", ".join(fields)}, and nothing else')
	key, date, lines, country, name = (entry.get(field) for field in fields)
	if not (isinstance(key, str) and key and all(isinstance(value, (str, type(None))) for value in (country, name))):
		raise ValueError('its key, and any country or name, are text')
	if not (isinstance(date, str) and re.fullmatch(r'(\d{4}-)?\d\d-\d\d', date)):
		raise ValueError(f'{key}: its date is MM-DD (each year) or YYYY-MM-DD (once), not {date!r}')
	try:
		message.job(lines if isinstance(lines, list) else [])
		schedule = at({'date': date} if len(date) == 10 else {'day': int(date[3:]), 'months': [int(date[:2])]})
	except ValueError as e:
		raise ValueError(f'{key}: {e}') from None
	if schedule.next_after(datetime.datetime(2000, 1, 1, tzinfo=when.UTC)) is None:
		raise ValueError(f'{key}: there is no {date}')
	return Item(key, name or message_name(lines, country), 'message',
		tuple(line.replace('{flag}', markets.flag(country or '')) for line in lines), schedule, country)


_reminders = None # the reminders' items, as last read well (read_reminders)

def read_reminders():
	"""Read the reminders afresh (REMINDERS: DATA_DIR's copy, else the shipped one), each entry a reminder(), for
	items(): at start, and on a reload (SIGHUP). Raises config.ConfigError naming the file and the entry for one that
	does not read, and then the reminders read before stay."""
	global _reminders
	path = config.data_file(REMINDERS)
	try:
		entries = config.data_json(REMINDERS, [])
		if not isinstance(entries, list):
			raise ValueError('it is a list of reminders')
		found = []
		for number, entry in enumerate(entries, 1):
			try:
				found.append(reminder(entry))
			except ValueError as e:
				raise ValueError(f'reminder {number}: {e}') from None
		if len({item.key for item in found} | {item.key for item in ITEMS}) < len(found) + len(ITEMS):
			raise ValueError("a key that is another reminder's, or another default job's")
	except (OSError, ValueError) as e: # one that does not parse: a JSONDecodeError
		raise config.ConfigError(f'{path}: {e}')
	_reminders = tuple(found)
	return _reminders


def reminders():
	"""The reminders' items, as last read (read_reminders), and read now where they have not been."""
	return read_reminders() if _reminders is None else _reminders


def message_name(lines, country=None, size=56):
	"""What .jobs calls a reminder: its first line's words cut to fit, and the country it is for."""
	first = next((formats.plain(line).replace('{flag}', '').strip() for line in lines if line.strip()), '')
	if len(first) > size:
		first = first[:size].rsplit(' ', 1)[0] + ' …'
	return first + (f' ({country})' if country else '')


ITEMS = (
	Item('trades', 'trades', 'trades', (),
		when.Schedule.from_json({'span': ['mon 09:00', 'sat 15:00'], 'every': 20, 'zone': SYDNEY})),
	Item('price-midsession-au', 'movers midsession AU', 'movers', ('midsession',), at('weekdays', '13:00')),
	Item('price-midsession-us', 'movers midsession US', 'movers', ('midsession',), at('weekdays', '12:45', NEW_YORK)),
	Item('price-premarket-us', 'movers premarket US', 'movers', ('premarket',), at('weekdays', '07:15', NEW_YORK)),
	Item('price-close-au', 'movers close AU', 'movers', ('close',), at('weekdays', '16:30')),
	Item('price-close-hk', 'movers close HK', 'movers', ('close',), at('weekdays', '16:30', HONG_KONG)),
	Item('price-close-uk', 'movers close UK', 'movers', ('close',), at('weekdays', '17:00', LONDON)),
	Item('price-close-us', 'movers close US', 'movers', ('close',), at('weekdays', '16:30', NEW_YORK)),
	Item('rating', 'rating', 'rating', (), at(TUE_SAT)),
	Item('milestone', 'milestone', 'milestone', (), at(TUE_SAT)),
	*(Item(f"podcasts-{name.lower().replace(' ', '-')}", f'podcasts {name}', 'podcasts', (feed,),
		when.Schedule.from_json({'days': 'weekdays', 'every': 60, 'from': '10:01', 'to': '21:01', 'zone': SYDNEY}))
		for name, feed in (('Money Cafe', MONEY_CAFE), ('Stocktake', STOCKTAKE))),
	Item('earnings', 'earnings', 'earnings', (), at(['sun'])),
	Item('shorts', 'shorts', 'shorts', (), at(['sun'])),
	*periodic('weekly', ['sun']),
	*periodic('monthly', {'day': 2}),
	*periodic('quarterly', {'day': 2, 'months': [1, 4, 7, 10]}),
	*periodic('bi-annual', {'day': 2, 'months': [1, 7]}),
	*periodic('annual', {'day': 2, 'months': [1]}),
)


def items(country, sharesight=True):
	"""The default jobs where the country_code setting is country, the reports' (ITEMS), then the reminders: every item
	but those for another country, and where Sharesight is not set up (sharesight false), those that report on it."""
	return [item for item in (*ITEMS, *reminders()) if item.country in (None, country) and (sharesight or
		item.action not in SHARESIGHT)]


def matching(action, args, schedule, country):
	"""The default job that a job is, or None: the same action and arguments, on the same days at the same times, in a
	zone that keeps the same clock as the item's (a chat in Melbourne typing a Sydney item's schedule)."""
	for item in items(country):
		if ((item.action, item.args) == (action, tuple(args)) and
				dataclasses.replace(item.schedule, zone=schedule.zone) == schedule and
				when.same_clock(item.schedule.zone, schedule.zone)):
			return item
	return None
