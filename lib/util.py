import os
import io
import datetime
import json
from pathlib import Path
import re
import sys
import tempfile
import time
from lib.config import * # first: sets MPLCONFIGDIR before matplotlib is imported (lazily, by the chart functions)
from lib import sharesight


TITLE_TRIMS = [ # transform_title: (text, replacement), in order, as each sees what the ones before it made
	(' - ', ' '), ('Roundhill ETF Trust ', ''), ('Class A Common Stock', ''),
	('BlackRock Institutional Trust Company N.A.', ''), ('Listed Funds Trust', ''), ('GraniteShares ETF Trust', ''),
	('ProShares Trust', ''), ('VanEck ETF Trust', ''), ('Direxion Shares ETF Trust', ''), (' of California', ''),
	('Magnificent', 'Mag'), ('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'First Trust Clean Energy'),
	('First Trust Exchange-Traded Fund III First Trust Nasdaq Clean Edge Clean Energy Index Fund', 'First Trust Green Energy'),
	('Mirae Asset Global Investments (Hong Kong) Limited', ''), ('Space Exploration Technologies', 'SpaceX'),
	('Exchange Traded Funds Series OFC', ''), ('Global X Global X', 'Global X'), ('Tema ETF Trust', ''), (' AUD', ' '),
	(' USD', ' '), ('New York Shares', ''), ('China Electric Vehicle and Battery ETF', 'China EV ETF'),
	('China Electric Vehicle ETF', 'China EV ETF'), ('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable'),
	('Advanced Micro Devices', 'AMD'), ('Taiwan Semiconductor Manufacturing', 'TSM'),
	('Flight Centre Travel', 'Flight Centre'), ('Global X Funds ', ''), (' of Australia', ''),
	('National Australia Bank', 'NAB'), (' PLC', ''), (' p.l.c.', ''), (' P.l.c.', ''), (' P.L.C.', ''), (' Units', '')
]

TITLE_SHORTENINGS = [ # and these after the suffixes come off
	('Microbalifesciences', 'Microba Life Sciences'), ('Walt Disney Co (The)', 'Disney'), ('Lisenergylimited', 'LI-S Energy'),
	('Invesco Capital Management LLC ', ''), ('QUALCOMM', 'Qualcomm'), ('Ordinary Shares Class A', ''),
	('Ordinary Shares Class C', ''), ('Lbt Innovations', 'LBT Innovations'),
	('Vanguard Information Technology', 'Vanguard Infotech'), ('The ', ''), (' Shares', ''), ('Rea ', 'REA '),
	('Csl ', 'CSL '), ('Battery ', 'Batt '), ('.com', ''), ('Etf', 'ETF'), ('N.V.', ''), (' NV ', ' '), ('New York Re', ''),
	(' Australian', ' Aus'), (' Australia', ' Aus'), (' Infrastructure', ' Infra'), (' Manufacturing Company', ' '),
	(' Limited', ' '), (' Ltd', ' '), (' Holdings', ' '), (' Holding', ' '), (' (Holdings)', ''), (' Corporation', ' '),
	(' Incorporated', ' '), (' incorporated', ' '), (' Technologies', ' '), (' Technology', ' '), (' Enterprises', ' '),
	(' Enterprise', ' '), (' Enterpr', ' '), (' Ventures', ' '), (' Resources', ' '), (' (Intrada', ''), (' Structured', ''),
	(' Co.', ' '), (' Corp.', ' '), (' Corp', ' '), (' Tech ', ' '), (' Company', ' '), (' Group', ' '), (', Inc', ' '),
	(' Inc', ' '), (' Plc', ' '), (' plc', ' '), (' Index', ' '), (' ADR', ' '), (' Daily', ' '), (' Long', ' '),
	(' Bull', ' '), (' .', ' '), (' ,', ' ')
]

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
	return ' '.join(title.replace(' Usd', ' USD').replace('Ishares', 'iShares').split())

MARKETS = { # Sharesight market code -> (flag, currency); no currency where a market quotes in several (LSE and HKEX allow non-home currencies)
	'ASX': ('🇦🇺', 'AUD'),
	'BOM': ('🇮🇳', 'INR'), 'NSE': ('🇮🇳', 'INR'),
	'BMV': ('🇲🇽', 'MXN'),
	'BKK': ('🇹🇭', 'THB'),
	'BVMF': ('🇧🇷', 'BRL'),
	'SHE': ('🇨🇳', 'CNY'), 'SHA': ('🇨🇳', 'CNY'),
	'CPSE': ('🇩🇰', 'DKK'),
	**dict.fromkeys(('EURONEXT', 'AMS', 'ATH', 'BIT', 'BME', 'DUB', 'EBR', 'EPA', 'ETR', 'FWB', 'FRA', 'VIE'), ('🇪🇺', 'EUR')),
	'HKG': ('🇭🇰', None),
	'ICSE': ('🇮🇸', 'ISK'),
	'JSE': ('🇿🇦', 'ZAR'),
	'KRX': ('🇰🇷', 'KRW'), 'KOSDAQ': ('🇰🇷', 'KRW'),
	'LSE': ('🇬🇧', 'GBP'), # better than trades.py using brokerage_currency_code, which is AUD on CMC
	'MISX': ('🇷🇺', 'RUB'),
	'OM': ('🇸🇪', 'SEK'), 'STO': ('🇸🇪', 'SEK'),
	'SWX': ('🇨🇭', 'CHF'), 'VTX': ('🇨🇭', 'CHF'),
	'TAI': ('🇹🇼', 'TWD'), 'TPE': ('🇹🇼', 'TWD'),
	'TASE': ('🇮🇱', 'ILS'),
	'NZX': ('🇳🇿', 'NZD'),
	'OB': ('🇳🇴', 'NOK'),
	'SGX': ('🇸🇬', 'SGD'),
	'TSE': ('🇯🇵', 'JPY'),
	'TSX': ('🇨🇦', 'CAD'),
	'NASDAQ': ('🇺🇸', 'USD'), 'NYSE': ('🇺🇸', 'USD'), 'BATS': ('🇺🇸', 'USD'), 'AMEX': ('🇺🇸', None),
	'WAR': ('🇵🇱', 'PLN'),
}

def flag_from_market(market):
	if market in MARKETS:
		return MARKETS[market][0]
	return '🇺🇸' if market.lower().startswith(('nasdaq', 'nyse')) else ''

TICKER_FLAGS = {'AS': '🇳🇱', 'AX': '🇦🇺', 'HK': '🇭🇰', 'KS': '🇰🇷', 'KQ': '🇰🇷', 'L': '🇬🇧', 'NS': '🇮🇳', 'NZ': '🇳🇿', 'SI': '🇸🇬', 'T': '🇯🇵', 'TA': '🇮🇱',
	'TW': '🇹🇼', 'TWO': '🇹🇼', 'TO': '🇨🇦'} # Yahoo suffix -> flag

def flag_from_ticker(ticker):
	return TICKER_FLAGS.get(ticker.split('.')[1], '') if '.' in ticker else '🇺🇸'

def currency_from_market(market):
	return MARKETS.get(market, (None, None))[1]

def cache_path(name, persist=False):
	"""Where a cache file lives, or with persist=True a state file (in the data directory)."""
	return (config_var_dir if persist else config_cache_dir) + "/" + name

def _fresh_cache(cacheFile, maxSeconds):
	"""The cache file's path if it was written less than maxSeconds ago (config_cache_seconds when UNSET), else None."""
	if maxSeconds is UNSET:
		maxSeconds = config_cache_seconds
	path, age = cache_path(cacheFile), cache_age(cacheFile)
	if age is None:
		print("cache miss:", path, file=sys.stderr) if debug else None
		return None
	if age >= maxSeconds:
		print("cache expired:", path, file=sys.stderr) if debug else None
		return None
	print("cache hit:", path, "TTL:", td_to_human(datetime.timedelta(seconds=maxSeconds - age)), file=sys.stderr) if debug else None
	return path

def read_cache(cacheFile, maxSeconds=UNSET):
	"""A cache file's JSON, or None when it is missing or older than maxSeconds."""
	path = _fresh_cache(cacheFile, maxSeconds)
	return json.loads(Path(path).read_text(encoding="utf-8")) if path else None

def cache_age(cacheFile):
	"""Seconds since the cache file was written, or None when it does not exist."""
	try:
		return time.time() - os.path.getmtime(cache_path(cacheFile))
	except OSError:
		return None

def write_file(path, data, sync=False):
	"""Write `data` (bytes) to `path` whole or not at all, mode 0640: it goes to a temp file beside it, which then replaces the file,
	so a failure part way (a full disk, a kill) leaves the old file as it was. sync=True also flushes it to disk, for state that
	must survive a power cut. The process umask is left alone."""
	path = os.path.realpath(path) # through a symlink, as an in-place write would
	fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=os.path.basename(path) + '.', suffix='.tmp')
	try:
		with os.fdopen(fd, 'wb') as f:
			f.write(data)
			if sync:
				f.flush()
				os.fsync(f.fileno())
		os.chmod(tmp, 0o640)
		os.replace(tmp, path)
	except BaseException:
		try:
			os.unlink(tmp)
		except OSError:
			pass
		raise

def json_write(filename, data, persist=False):
	"""A cache file, or with persist=True a state file in the data directory (also flushed to disk). See write_file."""
	path = cache_path(filename, persist)
	if debug:
		print("cache write:", path, file=sys.stderr)
	write_file(path, json.dumps(data, indent=4).encode('utf-8'), sync=persist)

def json_load(filename, persist=False):
	path = Path(cache_path(filename, persist))
	return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

def read_binary_cache(cacheFile, maxSeconds=UNSET):
	"""A cache file's bytes (as a file object), or None when it is missing or older than maxSeconds."""
	path = _fresh_cache(cacheFile, maxSeconds)
	return io.BytesIO(Path(path).read_bytes()) if path else None

def write_binary_cache(cacheFile, data):
	data.seek(0)
	write_file(cache_path(cacheFile), data.getvalue())

def humanUnits(value, decimal_places=2):
	"""1234567 -> '1.23 M'."""
	for unit in ['', 'K', 'M', 'B', 'T', 'Q']:
		if value < 1000.0 or unit == 'Q':
			break
		value /= 1000.0
	return f"{value:.{decimal_places}f} {unit}".rstrip()

def yahoo_link(ticker, service='telegram', brief=True, text=None):
	if not text:
		text = ticker.split('.')[0] if brief else ticker
	return link("https://au.finance.yahoo.com/quote/" + ticker, text, service)

def security_line(flag, title, link):
	"""'🇦🇺 Title (link)': how a report line names a security (without a leading space where its market has no flag)."""
	return f"{flag} {title} ({link})" if flag else f"{title} ({link})"

def link(url, text, service='telegram'):
	if service == 'telegram' and config_hyperlink:
		hyperlink = '<a href="' + url + '">' + text + '</a>'
	elif service in {'discord', 'slack'} and config_hyperlink:
		hyperlink = '<' + url + '|' + text + '>'
	else:
		hyperlink = text
	return hyperlink

def finance_link(symbol, exchange, service='telegram', days=1, brief=True, text=None):
	if config_hyperlinkProvider == 'google':
		return gfinance_link(symbol, exchange, service, days, brief, text)
	return yahoo_link(symbol, service, brief, text)

def quote_link(ticker, exchange, service='telegram', days=1):
	"""finance_link, but to Yahoo for what Google Finance has no page for: Taipei Exchange, crypto (CCC) and indices (^)."""
	if exchange in ('Taipei Exchange', 'CCC') or ticker.startswith('^'):
		return yahoo_link(ticker, service)
	return finance_link(ticker, exchange, service, days=days)

def gfinance_link(symbol, exchange, service='telegram', days=1, brief=True, text=None):
	window = '1D'
	if not days:
		days = 1
	if days > 1:
		window = '5D'
	if days > 7:
		window = '1M'
	if days > 31:
		window = '6M'
	if days > 183:
		window = '1Y'
	if days > 365:
		window = '5Y'
	if days > 1825:
		window = 'Max'
	url = "https://www.google.com/finance/quote/"
	if '.' in exchange:
		exchange = exchange.split('.')[1]
	exchange = transform_to_google(exchange)
	symbol_short = symbol.replace(':', '.').split('.')[0]
	symbol_short = symbol_short.replace('-', '.') # class shares e.g. BRK.A
	ticker = symbol_short + ':' + exchange
	if brief and not text:
		text = symbol_short
	elif not text:
		if '.' in symbol:
			text = ticker
		else:
			text = symbol # US
	if service in {'telegram', 'discord', 'slack'} and config_hyperlink:
		return link(url + ticker + '?window=' + window, text, service)
	return symbol

VENUES = { # the names Yahoo, Sharesight and Google give an exchange -> (Google Finance code, country)
	**dict.fromkeys(('OTC', 'PNK', 'Other OTC', 'OTCPK'), ('OTCMKTS', None)),
	**dict.fromkeys(('TO', 'TOR', 'Toronto'), ('TSE', 'CA')),
	**dict.fromkeys(('TW', 'TWO', 'TAI', 'Taiwan', 'Taipei Exchange', 'Taipei'), ('TPE', 'TW')),
	**dict.fromkeys(('HK', 'HKG', 'HKSE'), ('HKG', 'HK')),
	**dict.fromkeys(('KQ', 'KOE', 'KOSDAQ'), ('KOSDAQ', 'KR')),
	**dict.fromkeys(('KS', 'KRX', 'KSE', 'KSC'), ('KRX', 'KR')),
	**dict.fromkeys(('L', 'LSE', 'London'), ('LON', 'UK')),
	**dict.fromkeys(('T', 'TYO', 'JPX', 'Tokyo'), ('TYO', 'JP')),
	**dict.fromkeys(('TA', 'TLV', 'Tel Aviv'), ('TLV', 'IL')),
	**dict.fromkeys(('NZSE', 'NZE', 'New Zealand', 'Auckland'), (None, 'NZ')),
}

def transform_to_google(exchange):
	if 'Nasdaq' in exchange:
		return 'NASDAQ'
	if exchange == 'Cboe US':
		return 'BATS'
	return VENUES.get(exchange, (None, None))[0] or exchange

def exchange_human(exchange):
	if 'Nasdaq' in exchange or 'NYSE' in exchange or 'Other OTC' in exchange:
		return 'US'
	return VENUES.get(exchange, (None, None))[1] or exchange

YAHOO_SUFFIX = { # exchange code (Sharesight, Google) -> Yahoo's ticker suffix
	'ASX': 'AX', 'HKG': 'HK', 'KRX': 'KS', 'KOSDAQ': 'KQ', 'LSE': 'L', 'NZX': 'NZ', 'SGX': 'SI',
	'TAI': 'TW', # Taiwan in YF and Sharesight; TPE in GF
	'TPE': 'TWO', # Taipei in YF, Taiwan in GF (GF format will not work as input); missing from GF
	'TSE': 'T', 'TYO': 'T', # Tokyo: TSE in Sharesight (Google's TSE is Toronto, which Sharesight calls TSX), TYO in GF
	'TSX': 'TO', 'TLV': 'TA',
}

def transform_to_yahoo(ticker, market=None):
	split = ticker.replace(':', '.').split('.')
	if len(split) > 1:
		ticker = split[0]
		market = split[1]
	if not market:
		return ticker
	market = YAHOO_SUFFIX.get(market, market)
	if market in {'NASDAQ', 'NYSE', 'BATS', 'OTCMKTS', 'AMEX', 'NYSEARCA'}: # US venues: Yahoo symbols carry no suffix
		return ticker
	if market in {'A', 'B', 'C'}: # class shares
		return ticker + '-' + market
	return ticker + '.' + market

def strip_url(url):
	url = url.removeprefix('https://www.')
	url = url.removeprefix('http://www.')
	url = url.removeprefix('https://')
	url = url.removeprefix('http://')
	return url

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
	"""'28 Sep - 5 Oct 2026' for the `days` ending on `end`; both ends carry their year when the range crosses a year boundary."""
	start = end - datetime.timedelta(days=days)
	return f"{date_short(start, start.year != end.year)} - {date_short(end, True)}"

def days_english(days, prefix='the past ', article=''):
	if days is None or days == 0:
		return 'today'
	elif days == 1:
		return prefix + article + 'day'
	elif days == 7:
		return prefix + article + 'week'
	elif days == 30:
		return prefix + article + 'month'
	elif days == 365:
		return prefix + article + 'year'
	elif days % 7 == 0:
		return prefix + str(int(days/7)) + ' weeks'
	elif days % 30 == 0:
		return prefix + str(int(days/30)) + ' months'
	elif days % 365 == 0:
		return prefix + str(int(days/365)) + ' years'
	else:
		return prefix + str(days) + ' days'

def fit_left_margin(fig, ax, pad_px=18):
	"""Widen the left margin so the longest Y tick label is never clipped; the right edge stays put."""
	renderer = fig.canvas.get_renderer()
	fig.canvas.draw()
	widest = max((t.get_window_extent(renderer).width for t in ax.get_yticklabels() if t.get_text()), default=0)
	need = (widest + ax.yaxis.get_tick_padding() * fig.dpi / 72 + pad_px) / fig.bbox.width
	x0, y0, w, h = ax.get_position().bounds
	if need > x0:
		ax.set_position([need, y0, w - (need - x0), h])

def style_date_axis(ax, start, end, ink):
	"""Larger, explicit date ticks: format follows the span, few enough ticks that they never collide."""
	import matplotlib.dates as mdates
	days = (end - start).days
	fmt = '%Y' if days > 1460 else '%b %Y' if days > 150 else '%d %b'
	ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=2, maxticks=5)) # minticks=3 warns on a 2-day span
	ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
	ax.tick_params(axis='x', colors=ink, labelsize=10, length=3, width=0.8, pad=6)

PALETTE = ('#14181f', '#eef1f5', '#9aa4b2', '#2a313c') # charts: dark surface, ink, muted ink, grid lines

def _figure(facecolor):
	"""A 1280x800 figure (Telegram's photo size, so it is never resampled) and its Agg canvas."""
	from matplotlib.figure import Figure
	from matplotlib.backends.backend_agg import FigureCanvasAgg
	fig = Figure(figsize=(6.4, 4.0), dpi=200, facecolor=facecolor)
	return fig, FigureCanvasAgg(fig)

def _style_time_axes(fig, ax, start, end):
	"""What the line charts share: a horizontal grid, no frame, muted ticks, and the date axis from start to end."""
	_, ink, ink2, grid = PALETTE
	ax.grid(axis='y', color=grid, linewidth=0.6)
	ax.set_axisbelow(True)
	for side in ax.spines.values():
		side.set_visible(False)
	ax.tick_params(colors=ink2, labelsize=8, length=0, pad=4)
	style_date_axis(ax, start, end, ink)
	fit_left_margin(fig, ax)

def _heading(fig, title, subtitle='', subtitle_color=None):
	"""A chart's title at the top left, and its subtitle (if any) beneath."""
	_, ink, ink2, _ = PALETTE
	fig.text(0.03, 0.957, title, color=ink, fontsize=13, fontweight='bold', ha='left', va='center')
	if subtitle:
		fig.text(0.03, 0.910, subtitle, color=subtitle_color or ink2, fontsize=8.5, ha='left', va='center')

def _png(fig, facecolor):
	"""The figure as PNG bytes, rewound, or an upload sends an empty file. No bbox_inches='tight': it would change the 1280x800 size."""
	buf = io.BytesIO()
	fig.savefig(buf, format='png', facecolor=facecolor)
	buf.seek(0)
	return buf

def graph(df, title, ylabel):
	"""Render a price chart as PNG bytes, sized for Telegram (1280px wide, no server-side resampling)."""
	from matplotlib.ticker import MaxNLocator, FuncFormatter
	import matplotlib.dates as mdates
	import numpy as np
	import pandas as pd
	# palette: dark surface, muted ink, green/red for up/down (red/green separated in lightness as well as hue)
	bg, ink, ink2, grid = PALETTE
	up, down, flat = '#34d399', '#fb7185', '#9aa4b2'
	x = pd.to_datetime(df['Date'].astype(str))
	y = df['Close'].astype(float)
	first, last = y.iloc[0], y.iloc[-1]
	color = up if last > first else down if last < first else flat
	pct = (last - first) / first * 100 if first else 0
	arrow = '▲' if last > first else '▼' if last < first else '■'

	fig, _ = _figure(bg)
	ax = fig.add_axes([0.075, 0.105, 0.885, 0.755], facecolor=bg)
	ax.fill_between(x, y, y.min() - (y.max() - y.min()) * 0.15, color=color, alpha=0.14, linewidth=0)
	ax.plot(x, y, color=color, linewidth=1.6, solid_capstyle='round')
	ax.plot([x.iloc[-1]], [last], marker='o', markersize=5, color=color, markeredgecolor=bg, markeredgewidth=1.5, clip_on=False)

	# headroom above/below so annotations never leave the plot
	span = (y.max() - y.min()) or max(abs(y.max()) * 0.02, 1e-9)
	ax.set_ylim(y.min() - span * 0.22, y.max() + span * 0.17)
	ax.margins(x=0.02)
	ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.2f}".rstrip('0').rstrip('.'))) # 66,000 / 1.5
	_style_time_axes(fig, ax, x.iloc[0], x.iloc[-1])

	def annotate(i, name, above):
		xd, yv = x.iloc[i], y.iloc[i]
		frac = (mdates.date2num(xd) - mdates.date2num(x.iloc[0])) / max(mdates.date2num(x.iloc[-1]) - mdates.date2num(x.iloc[0]), 1)
		# anchor text toward the inside of the plot so it cannot run off either edge
		ha = 'left' if frac < 0.25 else 'right' if frac > 0.75 else 'center'
		dx = {'left': 4, 'right': -4, 'center': 0}[ha]
		ax.annotate(f"{name} {yv:,.2f}\n{xd:%d %b %Y}", xy=(xd, yv), xytext=(dx, 9 if above else -9),
			textcoords='offset points', ha=ha, va='bottom' if above else 'top',
			fontsize=7, color=ink, linespacing=1.3, annotation_clip=False)
		ax.plot([xd], [yv], marker='o', markersize=4, color=ink, markeredgecolor=bg, markeredgewidth=1, zorder=5)
	imax, imin = int(np.argmax(y.values)), int(np.argmin(y.values))
	if imax != len(y) - 1:
		annotate(imax, 'High', True)
	if imin != len(y) - 1 and imin != imax:
		annotate(imin, 'Low', False)

	_heading(fig, title, f"{last:,.2f} {ylabel or ''}   {arrow} {abs(pct):.2f}%  over period", color)

	return _png(fig, bg)

def compare_graph(series, title, subtitle=''):
	"""Rebased % change lines for 2-6 tickers. series: list of (label, pandas Series of closes), already cropped to the period.
	Returns PNG bytes (1280x800, Telegram's photo size)."""
	from matplotlib.ticker import MaxNLocator, FuncFormatter
	bg, ink, ink2, grid = PALETTE
	# categorical slots 1-5 and 7 of the validated dark palette; red/green are skipped because they mean down/up
	colors = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']
	fig, _ = _figure(bg)
	ax = fig.add_axes([0.075, 0.105, 0.72, 0.755], facecolor=bg)
	rebased = []
	for label, y in series:
		rebased.append((label, (y / y.iloc[0] - 1) * 100))
	ax.axhline(0, color=ink2, linewidth=0.8, alpha=0.6, zorder=1)
	for (label, y), color in zip(rebased, colors):
		ax.plot(y.index, y.values, color=color, linewidth=1.5, solid_capstyle='round', zorder=3)
	lo = min(y.min() for _, y in rebased)
	hi = max(y.max() for _, y in rebased)
	span = (hi - lo) or 1.0
	ax.set_ylim(min(lo, 0) - span * 0.06, max(hi, 0) + span * 0.06)
	ax.margins(x=0.01)
	ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+,.0f}%" if v else "0%"))
	_style_time_axes(fig, ax, min(y.index[0] for _, y in rebased), max(y.index[-1] for _, y in rebased))

	# direct end-labels in the right margin, spread so they never overlap
	ymin, ymax = ax.get_ylim()
	ends = sorted(((y.iloc[-1], i) for i, (_, y) in enumerate(rebased)))
	pos = [(v - ymin) / (ymax - ymin) for v, _ in ends]
	gap = 0.065
	for i in range(1, len(pos)):
		pos[i] = max(pos[i], pos[i - 1] + gap)
	overflow = pos[-1] - 0.97
	if overflow > 0: # too high: shift the stack down, then re-enforce the floor
		pos = [p - overflow for p in pos]
		for i in range(len(pos) - 2, -1, -1):
			pos[i] = min(pos[i], pos[i + 1] - gap)
	for (value, i), p in zip(ends, pos):
		label, y = rebased[i]
		color = colors[i]
		ax.plot([1.015], [p], marker='s', markersize=4, color=color, transform=ax.transAxes, clip_on=False, zorder=4)
		ax.annotate(f"{label}  {value:+,.1f}%", xy=(y.index[-1], value), xycoords='data', xytext=(1.03, p), textcoords='axes fraction',
			ha='left', va='center', fontsize=7.5, color=ink, annotation_clip=False,
			arrowprops=dict(arrowstyle='-', color=color, linewidth=0.7, alpha=0.7, shrinkA=0, shrinkB=2, relpos=(0, 0.5)))
	_heading(fig, title, subtitle)
	return _png(fig, bg)

SESSION_TINTS = {'midsession': '#34d399', 'premarket': '#facc15'} # subtle green / yellow wash; at close stays plain

def tinted(bg, color, amount=0.07):
	"""bg blended a little way towards color, as a hex string."""
	mix = lambda i: round(int(bg[i:i + 2], 16) * (1 - amount) + int(color[i:i + 2], 16) * amount)
	return '#{:02x}{:02x}{:02x}'.format(mix(1), mix(3), mix(5))

def hbar_chart(rows, title, subtitle='', value_fmt=None, xlim=None, session=None):
	"""Horizontal bars that mirror the caption list, first row on top, filling the whole 1280x800 canvas.
	Blue for >= 0, red below. Each row's label sits at the bar's base and its value at the tip.
	rows: [(label, value)]; a (label, None) row is a blank spacer. xlim zooms the value axis (bars then start at its left edge).
	session: 'midsession' or 'premarket' washes the background green or yellow."""
	value_fmt = value_fmt or (lambda v: signed_percent(round(v)))
	bg, ink, ink2, _ = PALETTE
	up, down = '#3987e5', '#fb7185'
	if session in SESSION_TINTS:
		bg = tinted(bg, SESSION_TINTS[session])
	fig, canvas = _figure(bg)
	top_edge = 0.85 if subtitle else 0.89
	left = 0.14 if xlim else 0.04 # zoomed charts keep their labels outside the plot
	ax = fig.add_axes([left, 0.02, 0.96 - left, top_edge - 0.02], facecolor=bg)
	real = [(y, label, v) for y, (label, v) in enumerate(rows) if v is not None]
	values = [v for _, _, v in real]
	n = len(rows)
	ax.barh([y for y, _, _ in real], values, height=0.72, color=[up if v >= 0 else down for v in values], zorder=3)
	base = max(xlim[0], 0) if xlim else 0
	if not xlim:
		ax.axvline(0, color=ink2, linewidth=1.0, zorder=4)
	top, bottom = max(max(values), 0), min(min(values), 0)
	lo0 = xlim[0] if xlim else bottom
	hi0 = xlim[1] if xlim else top
	if hi0 <= lo0: # every value zero: give the axis a width, or the scale below divides by zero
		hi0 = lo0 + 1
	ax.set_xlim(lo0, hi0)
	ax.set_ylim(n - 0.4, -0.6) # first row on top
	ax.set_yticks([])
	ax.xaxis.set_visible(False) # no x axis labels or grid lines: every bar carries its own value
	for side in ax.spines.values():
		side.set_visible(False)
	dpi = fig.dpi
	axes_px = (top_edge - 0.02) * fig.get_figheight() * dpi
	bar_px = 0.72 * axes_px / n
	longest = max([len(str(label)) for _, label, _ in real] + [3])
	em_px = min(bar_px * 1.3, 0.28 * (0.96 - left) * fig.get_figwidth() * dpi / (0.62 * longest)) # text height follows the bar thickness
	size = max(5, min(30, em_px * 72 / dpi))
	# each row's label sits beside the bar's base (left of the zero line for rising bars, right of it for falling ones)
	base_labels = []
	value_labels = []
	drop = -0.365 * size # baseline sits half a cap height below the bar's centre, so the capitals are centred on the bar
	for y, label, v in real:
		base_labels.append(ax.annotate(label, xy=(base, y), xytext=(-4, drop), textcoords='offset points', ha='right', va='baseline',
			fontsize=size, color=ink, annotation_clip=False, zorder=5))
		value_labels.append(ax.annotate(value_fmt(v), xy=(v, y), xytext=(4 if v >= 0 else -4, drop), textcoords='offset points',
			ha='left' if v >= 0 else 'right', va='baseline', fontsize=size, color=ink, annotation_clip=False))
	renderer = canvas.get_renderer()
	canvas.draw()
	label_width = [t.get_window_extent(renderer).width for t in base_labels]
	value_width = [t.get_window_extent(renderer).width for t in value_labels]
	if xlim: # zoomed charts put the labels in the left margin: shrink the text until the widest label fits inside the image
		room = left * fig.get_figwidth() * dpi - 30 # also leaves the 4pt gap before the bar base
		if max(label_width) > room:
			for t in base_labels + value_labels:
				t.set_fontsize(t.get_fontsize() * room / max(label_width))
			canvas.draw()
			label_width = [t.get_window_extent(renderer).width for t in base_labels]
			value_width = [t.get_window_extent(renderer).width for t in value_labels]
	width = ax.get_window_extent(renderer).width
	lo, hi = lo0, hi0
	for _ in range(12): # the pixels-per-unit scale depends on the limits, which depend on the text beside the bars: settle it iteratively
		per_unit = width / (hi - lo)
		# room for the text outside the bars: each tip's value, and each base's label (zoomed charts keep those in the left margin)
		new_lo, new_hi = lo0, hi0
		for (_, _, v), w, vw in zip(real, label_width, value_width):
			if v >= 0:
				new_hi = max(new_hi, v + (vw + 12) / per_unit)
				if not xlim:
					new_lo = min(new_lo, base - (w + 12) / per_unit)
			else:
				new_lo = min(new_lo, v - (vw + 12) / per_unit)
				if not xlim:
					new_hi = max(new_hi, base + (w + 12) / per_unit)
		if abs(new_lo - lo) < 1e-6 * (hi - lo) and abs(new_hi - hi) < 1e-6 * (hi - lo):
			break
		lo, hi = new_lo, new_hi
	ax.set_xlim(lo, hi)
	for t, (_, _, v) in zip(base_labels, real):
		t.xyann = (-4 if v >= 0 else 4, drop)
		t.set_ha('right' if v >= 0 else 'left')
	fig.text(0.03, 0.945 if not subtitle else 0.935, title, color=ink, fontsize=13, fontweight='bold', ha='left', va='center')
	if subtitle:
		fig.text(0.03, 0.885, subtitle, color=ink2, fontsize=8.5, ha='left', va='center')
	return _png(fig, bg)

SHORTS_VERDICTS = ((5, 'board shorts'), (10, 'cargo shorts'), (15, 'boxers'), (20, 'gym shorts'), # five points each at the bottom
	(30, 'cutoffs'), (40, 'short shorts'), (50, 'daisy dukes'), (60, 'hot pants'), (70, 'speedos'), (80, 'budgie smugglers'), (90, 'just a belt'),
	(float('inf'), 'never nudes')) # the extreme ones step in every 10 points

def shorts_verdict(percent):
	"""The more shorted, the shorter the shorts."""
	return next(name for limit, name in SHORTS_VERDICTS if percent < limit)

def shorts_chart(rows, threshold, step=5):
	"""Short interest as a pictogram: each row is a run of cartoon shorts, one pair per `step` percent (the last pair cropped).
	rows: [(label, percent)], largest first. Loud on purpose and drawn from patches, since matplotlib cannot render colour emoji.
	Returns PNG bytes (1280x800)."""
	import math
	import numpy as np
	from matplotlib.patches import Polygon, Rectangle, Circle, Ellipse, PathPatch
	from matplotlib.path import Path
	sky, ink, sea, foam, ray = '#ffe66d', '#1b1f3b', '#1ea7e1', '#b5e8ff', '#ffd23f'
	colors = ['#ff3d81', '#00b8a0', '#ff8a00', '#7a5cff', '#5bc215']
	W, H = 1280, 800
	if len(rows) > 24: # pairs of shorts need height: keep the most and the least shorted
		rows = rows[:12] + rows[-12:]
	rows = [(label if len(label) <= 10 else label[:9] + '…', value) for label, value in rows]
	fig, canvas = _figure(sky)
	ax = fig.add_axes([0, 0, 1, 1], facecolor=sky)
	ax.set_xlim(0, W)
	ax.set_ylim(H, 0) # pixels, y down
	ax.axis('off')

	def shorts(x, y, w, h, color, frac=1.0, lw=1.6):
		"""One pair, top-left at (x, y); frac < 1 crops it from the right."""
		def P(px, py):
			return (x + px * w, y + py * h)
		belt = '#' + ''.join(f"{int(int(color[i:i + 2], 16) * 0.7):02x}" for i in (1, 3, 5))
		legs = Polygon([P(0.04, 0.2), P(0.96, 0.2), P(1.0, 0.97), P(0.56, 0.97), P(0.5, 0.58), P(0.44, 0.97), P(0.0, 0.97)],
			closed=True, facecolor=color, edgecolor=ink, linewidth=lw, joinstyle='round')
		waist = Rectangle(P(0.04, 0.0), 0.92 * w, 0.22 * h, facecolor=belt, edgecolor=ink, linewidth=lw)
		parts = [legs, waist]
		for dx, dy in ((0.2, 0.5), (0.3, 0.78), (0.72, 0.5), (0.8, 0.78), (0.14, 0.8)): # polka dots
			parts.append(Circle(P(dx, dy), 0.045 * w, facecolor='white', edgecolor='none'))
		parts.append(Rectangle(P(0.47, 0.0), 0.06 * w, 0.22 * h, facecolor='#ffd23f', edgecolor=ink, linewidth=lw * 0.6)) # belt buckle
		clip = Rectangle((x - 2, y - 2), w * frac + 2, h + 4, transform=ax.transData) if frac < 1 else None
		for part in parts:
			ax.add_patch(part)
			if clip is not None:
				part.set_clip_path(clip)

	# decor: a big sun in sunglasses whose rays run under everything to the edges, and the sea
	R = 100 # the sun's radius; it sits in the top right corner
	margin = 5 # gap between the sun and the top and right edges
	sx, sy, rays = W - R - margin, R + margin, 16
	tilt = math.radians(-1) # beams turned 1 degree counter-clockwise (angles run clockwise here, as y points down)
	for k in range(0, rays, 2): # every other wedge, so the rays alternate with the sky
		a0, a1 = k * 2 * math.pi / rays + tilt, (k + 1) * 2 * math.pi / rays + tilt
		ax.add_patch(Polygon([(sx, sy), (sx + 2000 * math.cos(a0), sy + 2000 * math.sin(a0)), (sx + 2000 * math.cos(a1), sy + 2000 * math.sin(a1))],
			closed=True, facecolor=ray, edgecolor='none', zorder=-1))
	def at(u, v): # face coordinates in sun radii, y down
		return (sx + u * R, sy + v * R)
	ax.add_patch(Circle((sx, sy), R, facecolor='#ffb000', edgecolor='none'))
	for dx, dy, r, c in ((-0.05, -0.06, 0.93, '#ffb90a'), (-0.1, -0.12, 0.78, '#ffc21f'), (-0.16, -0.2, 0.55, '#ffcb35')): # fake gradient
		ax.add_patch(Circle(at(dx, dy), r * R, facecolor=c, edgecolor='none'))
	brown = '#5a3d37'
	for (u, v), w, h in (((-0.46, -0.07), 0.21, 0.25), ((0.31, -0.37), 0.20, 0.24)): # lopsided eyes
		ax.add_patch(Ellipse(at(u, v), w * R, h * R, facecolor=brown, edgecolor='none'))
	nose = np.array([(-0.07, -0.35), (0.05, -0.26), (0.15, -0.13), (0.18, 0.0), (0.10, 0.10), (-0.03, 0.16)])
	nose = nose.mean(axis=0) + 0.62 * (nose - nose.mean(axis=0)) # dainty: a smaller squiggle
	pts = np.vstack([nose[0], nose, nose[-1]]) # Catmull-Rom through the points, so the squiggle is smooth
	curve = [0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
		for p0, p1, p2, p3 in zip(pts, pts[1:], pts[2:], pts[3:]) for t in np.linspace(0, 1, 12)]
	ax.plot([sx + u * R for u, _ in curve], [sy + v * R for _, v in curve], color='#e07b1a', linewidth=2.6, solid_capstyle='round')
	mouth_pts = [(-0.47, 0.47), (0.73, 0.0), (0.75, 0.35), (0.45, 0.74), (0.1, 0.74), (-0.15, 0.74), (-0.42, 0.62), (-0.47, 0.47), (-0.47, 0.47)]
	mc = (0.13, 0.37) # the mouth shrinks towards its middle
	mouth = Path([at(mc[0] + 0.65 * (u - mc[0]), mc[1] + 0.65 * (v - mc[1])) for u, v in mouth_pts],
		[Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CLOSEPOLY])
	ax.add_patch(PathPatch(mouth, facecolor='#2b2118', edgecolor='none'))
	ax.add_patch(Rectangle((0, 748), W, H - 748, facecolor=sea, edgecolor='none'))
	for cx in range(0, W + 36, 36):
		ax.add_patch(Circle((cx, 748), 19, facecolor=foam, edgecolor='none'))

	ax.text(40, 52, 'Shorts', color=ink, fontsize=21, fontweight='bold', ha='left', va='center')
	ax.text(40, 104, f"each pair of shorts = {step}% of shares shorted", color=ink, fontsize=9.5, ha='left', va='center')

	top, bottom = 205, 726 # below the sun
	n = len(rows)
	row_h = min((bottom - top) / n, 110)
	top += ((bottom - top) - row_h * n) / 2 # few rows sit in the middle of the beach, not the top
	bottom = top + row_h * n
	size = max(6, min(18, row_h * 0.5 * 72 / 200 * 2))
	label_w = max(len(str(label)) for label, _ in rows) * size * 200 / 72 * 0.62
	x0 = 40 + label_w + 16
	room = 40 + 400 # right-hand text: percent and verdict
	max_icons = max(math.ceil(max(v for _, v in rows) / step), 1)
	icon_w = min((W - room - x0) / max_icons, row_h * 1.1 * 0.9, 120)
	icon_h = icon_w / 1.1
	lw = max(0.6, min(1.6, icon_w / 45))
	pct_texts = []
	for i, (label, value) in enumerate(rows):
		cy = top + (i + 0.5) * row_h
		ax.text(x0 - 14, cy, label, color=ink, fontsize=size, fontweight='bold', ha='right', va='center')
		whole, frac = divmod(value / step, 1)
		color = colors[i % len(colors)]
		for k in range(int(whole) + (1 if frac > 0.02 else 0)):
			shorts(x0 + k * icon_w, cy - icon_h / 2, icon_w * 0.92, icon_h, color, frac if k == int(whole) and frac > 0.02 else 1.0, lw)
		end = x0 + (value / step) * icon_w
		pct_texts.append((ax.text(end + 14, cy, f"{round(value)}%", color=ink, fontsize=size, fontweight='bold', ha='left', va='center'), cy, value))
	canvas.draw() # measure the percentages, then put each verdict right after its own
	for text, cy, value in pct_texts:
		verdict = ax.text(text.get_window_extent(canvas.get_renderer()).x1 + 10, cy, shorts_verdict(round(value)), color=ink, fontsize=size * 0.62, fontstyle='italic', ha='left', va='center')
		extent = verdict.get_window_extent(canvas.get_renderer())
		if extent.x1 > W - 16: # never run off the image: shrink to fit
			verdict.set_fontsize(verdict.get_fontsize() * (W - 16 - extent.x0) / extent.width)
	ax.text(W / 2, 784, 'past fashion not indicative of future fashion', color='white', fontsize=8, fontstyle='italic', ha='center', va='center')
	line_x = x0 + threshold / step * icon_w
	ax.plot([line_x, line_x], [top - 12, bottom], color=ink, linewidth=1.8, linestyle=(0, (5, 4)), zorder=0)
	ax.text(line_x, top - 18, f"{threshold:g}% outrageous line", color=ink, fontsize=7.5, fontweight='bold', ha='center', va='bottom')

	return _png(fig, sky)

def rows_chart(rows, title, subtitle='', **kw):
	"""Horizontal bars for a list of (label, value). Over 40 rows keeps the first and last 20."""
	if len(rows) > 40:
		rows = rows[:20] + rows[-20:]
	return hbar_chart(rows, title, subtitle, **kw)

def pie_chart(rows, title, subtitle=''):
	"""Pie of (label, value) rows, largest first, with a legend of name and share. At most 8 named slices
	(the dark categorical slots, in fixed order); a slice labelled 'Other' is gray. Returns PNG bytes (1280x800)."""
	from matplotlib.patches import Rectangle
	bg, ink, ink2, _ = PALETTE
	slots = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']
	other = '#6b7280'
	total = sum(v for _, v in rows) or 1.0
	colors, n = [], 0
	for label, _ in rows:
		if label == 'Other':
			colors.append(other)
		else:
			colors.append(slots[n % len(slots)])
			n += 1
	fig, _ = _figure(bg)
	ax = fig.add_axes([0.02, 0.02, 0.525, 0.84], facecolor=bg) # square: 0.84 * 4in = 0.525 * 6.4in
	ax.pie([v for _, v in rows], colors=colors, startangle=90, counterclock=False,
		wedgeprops={'edgecolor': bg, 'linewidth': 2}) # 2px surface gap between slices
	ax.set_xlim(-1.03, 1.03) # matplotlib's default 1.25 leaves a wide margin around the pie
	ax.set_ylim(-1.03, 1.03)
	ax.set_aspect('equal')
	step = min(0.075, 0.74 / max(len(rows), 1))
	y = 0.5 + step * (len(rows) - 1) / 2 - 0.03 # legend block centred on the pie
	for (label, value), color in zip(rows, colors):
		fig.add_artist(Rectangle((0.57, y - 0.014), 0.018, 0.028, transform=fig.transFigure, facecolor=color, edgecolor='none'))
		fig.text(0.60, y, label if len(label) <= 28 else label[:27] + '…', color=ink, fontsize=8.5, ha='left', va='center')
		fig.text(0.97, y, f"{value / total * 100:.1f}%", color=ink2, fontsize=8.5, ha='right', va='center')
		y -= step
	_heading(fig, title, subtitle)
	return _png(fig, bg)

def bar_graph(top_rows, bottom_rows, title, subtitle=''):
	"""Top performers then, after a gap, the worst performers: the same order as the caption's two lists."""
	return hbar_chart(list(top_rows) + [('', None)] + list(bottom_rows), title, subtitle)

def signed_percent(value, decimals=None):
	"""12 -> '+12%', -3.5 -> '-3.5%', 0 -> '0%'; thousands separated. decimals=None keeps the value's own digits."""
	if value == 0:
		return '0%'
	return f"{value:+,}%" if decimals is None else f"{value:+,.{decimals}f}%"

def get_emoji(number):
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

def get_holdings_and_watchlist():
	tickers = set(sharesight.get_holdings_wrapper())
	tickers.update(json_load('finbot_watchlist.json', persist=True) or []) # absent until the first add
	if 'GOOG' in tickers and 'GOOGL' in tickers:
		tickers.remove("GOOGL")
	return sorted(tickers)

def ordinal(num):
	value = str(num)
	if len(value) > 1:
		secondToLastDigit = value[-2]
		if secondToLastDigit == '1':
			return 'th'
	lastDigit = value[-1]
	if (lastDigit == '1'):
		return 'st'
	elif (lastDigit == '2'):
		return 'nd'
	elif (lastDigit == '3'):
		return 'rd'
	else:
		return 'th'

def td_to_human(timedelta):
	days, remainder = divmod(timedelta.total_seconds(), 86400)
	hours, remainder = divmod(remainder, 3600)
	minutes, seconds = divmod(remainder, 60)
	parts = []
	if days:
		parts.append(f"{int(days)} day{'s' if days != 1 else ''}")
	if hours:
		parts.append(f"{int(hours)} hour{'s' if hours != 1 else ''}")
	if minutes:
		parts.append(f"{int(minutes)} minute{'s' if minutes != 1 else ''}")
	if seconds:
		parts.append(f"{int(seconds)} second{'s' if seconds != 1 else ''}")
	if not parts:
		return "0 seconds"
	return ", ".join(parts)
