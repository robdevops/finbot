"""The default jobs: every chat has them, each switched on until the chat switches it off (.jobs). An item's name says
what it reports on, never when: its schedule (lib/when.py) says that. For performance and movers the period follows how
often the item runs (period_args): quarterly, 90 days. The market reports run in their market's zone, so that they keep
to its session through its daylight saving: pre-market at 7:15am New York, mid-session about halfway through, the close
30 minutes after it. The reminders (message jobs) run at 8:30am Sydney on their dates, some only where the country_code
setting is their country; a chat adds its own with .jobs add reminder."""
import dataclasses

from lib import formats
from lib import markets
from lib import when

SYDNEY, NEW_YORK, HONG_KONG, LONDON = 'Australia/Sydney', 'America/New_York', 'Asia/Hong_Kong', 'Europe/London'
MORNING = '09:00' # by Sydney's clock: the weekly and longer reports
REMINDERS = '08:30' # by Sydney's clock: the reminders
TUE_SAT = ['tue', 'wed', 'thu', 'fri', 'sat'] # the mornings after a US session
SHARESIGHT = ('trades', 'performance', 'holdings', 'treemap', 'who') # the actions that report on Sharesight
PERIODIC = ('performance', 'movers') # the reports whose period follows how often they run
PERIOD_DAYS = {'daily': 1, 'weekdays': 1, 'weekly': 7, 'monthly': 30, 'quarterly': 90, 'bi-annual': 180, 'annual': 365}
PERIOD_NAMES = {7: '1w', 30: '1m', 90: '3m', 180: '6m', 365: '1y'} # how performance's period is written


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
		return [] if days is None else [PERIOD_NAMES.get(days, str(days))]
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


def message(key, date, lines, country=None, name=None):
	"""A reminder (a message job) at 8:30am Sydney on its date ('MM-DD') each year; where it is for one country, with
	that country's flag for {flag} (markets.flag); named after its first line unless it has a name."""
	return Item(key, name or message_name(lines, country), 'message',
		tuple(line.replace('{flag}', markets.flag(country or '')) for line in lines),
		at({'day': int(date[3:]), 'months': [int(date[:2])]}, REMINDERS), country)


def message_name(lines, country=None, size=56):
	"""What .jobs calls a reminder: its first line's words cut to fit, and the country it is for."""
	first = next((formats.plain(line).replace('{flag}', '').strip() for line in lines if line.strip()), '')
	if len(first) > size:
		first = first[:size].rsplit(' ', 1)[0] + ' …'
	return first + (f' ({country})' if country else '')


EOFY_CHECKLIST = (
	"💸 Realise capital gains/losses by EOFY June 30{flag}",
	"",
	"💰 Finalise any deductables by EOF June 30: {flag}",
	"• donations*",
	"• Super contributions†",
	"• work expenses‡",
	"• investment subscriptions§",
	"",
	"_* Organisation must be [DGR-registered](https://abr.business.gov.au/Tools/DgrListing)_",
	"_† Allow transfer time for Super, as contributions can only be deducted for the year they're received. Stake"
	" users: see [note about XX PCC in transaction description](https://hellostake.com/au/support/stake-super/"
	"employer-and-personal-contributions/33442327233305#h_01JQAPN9A6ZM41NZKP6XZWN1KP)_",
	"_‡ See [eligible work expenses](https://www.ato.gov.au/individuals-and-families/"
	"income-deductions-offsets-and-records/deductions-you-can-claim)_",
	"_§ Must relate directly to specific trades and gains/income (e.g. not general finance news)_")

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
	Item('earnings', 'earnings', 'earnings', (), at({'day': 1})),
	Item('shorts', 'shorts', 'shorts', (), at(['sat'])),
	*periodic('weekly', ['sat']),
	*periodic('monthly', {'day': 1}),
	*periodic('quarterly', {'day': 1, 'months': [1, 4, 7, 10]}),
	message('message-eofy-world', '03-31', ['🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦']),
	message('message-eofy-checklist', '06-23', EOFY_CHECKLIST, 'AU'),
	message('message-eofy-au', '06-30', ['🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰']),
	message('message-intent-to-claim', '07-07', ["✍️ Submit 'Notice of Intent to Claim' for any post-tax Super"
		" contributions. The fund must acknowledge them before you lodge your tax return{flag}"], 'AU'),
	message('message-birthday', '08-18', ["It's my {years since 2022-08-18} birthday! 🥳"], name="finbot's birthday"),
	message('message-tax-due-soon', '10-25', ['😓 Self-service individual tax returns are due Oct 31{flag}'], 'AU'),
	message('message-tax-due-today', '10-31', ['😰 Self-service individual tax returns are due today{flag}'], 'AU'),
)


def items(country, sharesight=True):
	"""The default jobs where the country_code setting is country: every item but those for another country, and
	where Sharesight is not set up (sharesight false), those that report on it."""
	return [item for item in ITEMS if item.country in (None, country) and (sharesight or item.action not in
		SHARESIGHT)]


def matching(action, args, schedule, country):
	"""The default job that a job is, or None: the same action and arguments, on the same days at the same times, in a
	zone that keeps the same clock as the item's (a chat in Melbourne typing a Sydney item's schedule)."""
	for item in items(country):
		if ((item.action, item.args) == (action, tuple(args)) and
				dataclasses.replace(item.schedule, zone=schedule.zone) == schedule and
				when.same_clock(item.schedule.zone, schedule.zone)):
			return item
	return None
