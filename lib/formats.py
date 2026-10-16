"""Text for people: company names trimmed, numbers in units, dates and spans in words, signed percents, ordinals."""
import datetime
import re
import zoneinfo

from lib import config

TITLE_TRIMS = [ # transform_title: (text, replacement), in order, as each sees what the ones before it made
	(' - ', ' '), ('Roundhill ETF Trust ', ''), ('Class A Common Stock', ''),
	('BlackRock Institutional Trust Company N.A.', ''), ('Listed Funds Trust', ''), ('GraniteShares ETF Trust', ''),
	('ProShares Trust', ''), ('VanEck ETF Trust', ''), ('Direxion Shares ETF Trust', ''), (' of California', ''),
	('Magnificent', 'Mag'), ('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'First Trust Clean Energy'),
	('First Trust Exchange-Traded Fund III First Trust Nasdaq Clean Edge Clean Energy Index Fund',
		'First Trust Green Energy'),
	('Mirae Asset Global Investments (Hong Kong) Limited', ''), ('Space Exploration Technologies', 'SpaceX'),
	('Exchange Traded Funds Series OFC', ''), ('Global X Global X', 'Global X'), ('Tema ETF Trust', ''), (' AUD', ' '),
	(' USD', ' '), ('New York Shares', ''), ('China Electric Vehicle and Battery ETF', 'China EV ETF'),
	('China Electric Vehicle ETF', 'China EV ETF'), ('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable'),
	('Advanced Micro Devices', 'AMD'), ('Taiwan Semiconductor Manufacturing', 'TSM'),
	('Flight Centre Travel', 'Flight Centre'), ('Global X Funds ', ''), (' of Australia', ''),
	('National Australia Bank', 'NAB'), (' PLC', ''), (' p.l.c.', ''), (' P.l.c.', ''), (' P.L.C.', ''), (' Units', '')
]

TITLE_SHORTENINGS = [ # and these after the suffixes come off
	('Microbalifesciences', 'Microba Life Sciences'), ('Walt Disney Co (The)', 'Disney'),
	('Lisenergylimited', 'LI-S Energy'),
	('Invesco Capital Management LLC ', ''), ('QUALCOMM', 'Qualcomm'), ('Ordinary Shares Class A', ''),
	('Ordinary Shares Class C', ''), ('Lbt Innovations', 'LBT Innovations'),
	('Vanguard Information Technology', 'Vanguard Infotech'), ('The ', ''), (' Shares', ''), ('Rea ', 'REA '),
	('Csl ', 'CSL '), ('Battery ', 'Batt '), ('.com', ''), ('Etf', 'ETF'), ('N.V.', ''), (' NV ', ' '),
	('New York Re', ''),
	(' Australian', ' Aus'), (' Australia', ' Aus'), (' Infrastructure', ' Infra'), (' Manufacturing Company', ' '),
	(' Limited', ' '), (' Ltd', ' '), (' Holdings', ' '), (' Holding', ' '), (' (Holdings)', ''), (' Corporation', ' '),
	(' Incorporated', ' '), (' incorporated', ' '), (' Technologies', ' '), (' Technology', ' '), (' Enterprises', ' '),
	(' Enterprise', ' '), (' Enterpr', ' '), (' Ventures', ' '), (' Resources', ' '), (' (Intrada', ''),
	(' Structured', ''),
	(' Co.', ' '), (' Corp.', ' '), (' Corp', ' '), (' Tech ', ' '), (' Company', ' '), (' Group', ' '), (', Inc', ' '),
	(' Inc', ' '), (' Plc', ' '), (' plc', ' '), (' Index', ' '), (' ADR', ' '), (' Daily', ' '), (' Long', ' '),
	(' Bull', ' '), (' .', ' '), (' ,', ' ')
]

TRUST_WORDS = ('ETF', 'ETFs', 'Series', 'Trust', 'Fund', 'Funds', 'OFC', 'Exchange-Traded', 'Portfolios') # a trust's

def fund_name(title):
	"""A fund's own name, without its trust's before it: up to its brand again, where the trust's words come first
	('Global X ETF Series OFC Global X China EV ETF': 'Global X China EV ETF'); an earlier ETF, with the trust's words
	after it ('Betashares ETF Trust Global Cybersecurity ETF': 'Betashares Global Cybersecurity ETF'); OFC (a fund
	company) anywhere. A company's name ('Johnson & Johnson') stays as it is."""
	words = title.split()
	again = next((i for i in range(1, len(words) - 1)
		if words[i] == words[0] and any(word in TRUST_WORDS for word in words[1:i])), 0)
	title = ' '.join(word for word in words[again:] if word != 'OFC')
	trust = '|'.join(re.escape(word) for word in TRUST_WORDS)
	return re.sub(rf'\bETFs? (?:(?:{trust}) )*(?=.*\bETF\b)', '', title)

def transform_title(title):
	"""A company or fund name as the reports show it: shorter, without fund-trust boilerplate and legal suffixes."""
	title = title.replace(' FPO', '')
	if title.isupper() or title.islower():
		title = title.title()
	for text, replacement in TITLE_TRIMS:
		title = title.replace(text, replacement)
	for suffix in (' AG', ' SE', ' Se'):
		title = title.removesuffix(suffix)
	title = re.sub(r'\[\w+\]$', '', title)
	for text, replacement in TITLE_SHORTENINGS:
		title = title.replace(text, replacement)
	if title.islower():
		title = title.title()
	for suffix in (' &', ' and'):
		title = title.strip().removesuffix(suffix)
	return fund_name(' '.join(title.replace(' Usd', ' USD').replace('Ishares', 'iShares').split()))

def human_units(value, decimal_places=2):
	"""1234567 -> '1.23 M'."""
	for unit in ['', 'K', 'M', 'B', 'T', 'Q']:
		if value < 1000.0 or unit == 'Q':
			break
		value /= 1000.0
	return f"{value:.{decimal_places}f} {unit}".rstrip()

def sections(*blocks):
	"""Blocks of lines one after another, a blank line between each two; an empty block is left out."""
	lines = []
	for block in blocks:
		if block and lines:
			lines.append('')
		lines += block or []
	return lines

NAME_LIMIT = 30 # characters of a name in a report's list: a longer line wraps on a phone

def short_name(name):
	"""A name for a report's list, cut at a word to at most NAME_LIMIT characters, an ellipsis last: 'Global X Asia
	Semiconductor ETF' -> 'Global X Asia Semiconductor…'. The name stays whole everywhere else."""
	if len(name) <= NAME_LIMIT:
		return name
	cut = name[:NAME_LIMIT - 1]
	if ' ' in cut[NAME_LIMIT // 2:]: # a word break past halfway: cut there rather than mid-word
		cut = cut[:cut.rindex(' ')]
	return cut.rstrip(' ,&-') + '…'

def security_line(flag, title, link):
	"""'🇦🇺 Title (link)': how a report line names a security (without a leading space where its market has no flag),
	the name cut to fit a phone (short_name)."""
	title = short_name(title)
	return f"{flag} {title} ({link})" if flag else f"{title} ({link})"

def strip_url(url):
	"""url without its scheme and www., to show as a link's text."""
	return url.split('://', 1)[-1].removeprefix('www.')

def make_paragraphs(walloftext):
	"""The text in paragraphs, each ending with the first sentence that takes it past 22 words."""
	paragraphs, buffer = [], []
	for word in walloftext.split():
		buffer.append(word)
		if word.endswith(('!', '.')) and len(buffer) > 22:
			paragraphs.append(' '.join(buffer))
			buffer = []
	if buffer: # the rest: it used to be dropped, and a short text with it
		paragraphs.append(' '.join(buffer))
	return '\n\n'.join(paragraphs)

def date_short(d, year=False):
	"""5 Oct (or 5 Oct 2026)."""
	return f"{d.day} {d:%b}" + (f" {d.year}" if year else "")

def date_range_english(days, end):
	"""'28 Sep - 5 Oct 2026' for the `days` ending on `end`; both ends carry their year when the range crosses one."""
	start = end - datetime.timedelta(days=days)
	return f"{date_short(start, start.year != end.year)} - {date_short(end, True)}"

def days_english(days, prefix='the past ', article=''):
	"""A span of days in words: 'today' for 0 or None; prefix + article + 'day', 'week', 'month' or 'year'; else prefix
	and a count of weeks, months, years or days ('the past 3 weeks')."""
	if not days:
		return 'today'
	for size, unit in ((1, 'day'), (7, 'week'), (30, 'month'), (365, 'year')):
		if days == size:
			return prefix + article + unit
	for size, units in ((7, 'weeks'), (30, 'months'), (365, 'years')): # weeks first: 210 days are 30 weeks
		if days % size == 0:
			return f"{prefix}{int(days // size)} {units}"
	return f"{prefix}{days} days"

def price(value):
	"""A price to show: two decimals, thousands separated (1,234.50); under 1, three significant digits (0.0123)."""
	return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.3g}"

def short_ticker(ticker):
	"""A ticker as a chart labels it: without its exchange (BHP.AX: BHP) or a crypto's dollar (BTC-USD: BTC)."""
	return ticker.split('.')[0].removesuffix('-USD')

def signed_percent(value, decimals=None):
	"""12 -> '+12%', -3.5 -> '-3.5%', 0 -> '0%'; thousands separated. decimals=None keeps the value's own digits."""
	if value == 0:
		return '0%'
	return f"{value:+,}%" if decimals is None else f"{value:+,.{decimals}f}%"

def get_emoji(number):
	"""🔼 for a rise, 🔻 for a fall, ▪️ for no change."""
	if number > 0:
		return '🔼'
	elif number < 0:
		return '🔻'
	else:
		return '▪️'

def days_from_human_days(arg):
	"""7, 7d, 2w, 3m, 1y or ytd -> days. Raises ValueError for anything else."""
	arg = arg.upper()
	if arg == 'YTD':
		today = datetime.datetime.now().date()
		return (today - today.replace(day=1, month=1)).days
	for suffix, days in (('D', 1), ('W', 7), ('M', 30)):
		try:
			return int(arg.removesuffix(suffix)) * days
		except ValueError:
			pass
	return int(arg.removesuffix('Y')) * 365

def seconds_from_human(arg):
	"""180s, 24h, or any period that days_from_human_days takes (7d, 2w, 3m, 1y, ytd, 7) -> seconds. Raises ValueError
	for anything else."""
	for suffix, seconds in (('s', 1), ('h', 3600)):
		if arg.lower().endswith(suffix) and arg[:-1].isdigit():
			return int(arg[:-1]) * seconds
	return days_from_human_days(arg) * 86400

def ordinal(num):
	"""The ordinal suffix of a whole number: 'st' for 1, 'nd' for 22, 'th' for 11 and 13."""
	return 'th' if num % 100 in (11, 12, 13) else {1: 'st', 2: 'nd', 3: 'rd'}.get(num % 10, 'th')


def zone():
	"""The timezone preference as a zone: UTC where it names none."""
	try:
		return zoneinfo.ZoneInfo(config.prefs.timezone)
	except (ValueError, zoneinfo.ZoneInfoNotFoundError):
		return zoneinfo.ZoneInfo('UTC')
