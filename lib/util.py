import os
import io
import datetime
import json
import re
import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from lib import sharesight
from lib.config import *


def chunker(seq, size):
	return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def transform_title(title):
	title = title.replace(' FPO', '')
	if title.isupper() or title.islower():
		title = title.title()
	title = title.replace(' - ', ' ')
	title = title.replace('Roundhill ETF Trust ', '')
	title = title.replace('Class A Common Stock', '')
	title = title.replace('BlackRock Institutional Trust Company N.A.', '')
	title = title.replace('Listed Funds Trust', '')
	title = title.replace('GraniteShares ETF Trust', '')
	title = title.replace('ProShares Trust', '')
	title = title.replace('VanEck ETF Trust', '')
	title = title.replace('Direxion Shares ETF Trust', '')
	title = title.replace(' of California', '')
	title = title.replace('Magnificent', 'Mag')
	title = title.replace('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'First Trust Clean Energy')
	title = title.replace('First Trust Exchange-Traded Fund III First Trust Nasdaq Clean Edge Clean Energy Index Fund', 'First Trust Green Energy')
	title = title.replace('Mirae Asset Global Investments (Hong Kong) Limited', '')
	title = title.replace('Space Exploration Technologies', 'SpaceX')
	title = title.replace('Exchange Traded Funds Series OFC', '')
	title = title.replace('Global X Global X', 'Global X')
	title = title.replace('Tema ETF Trust', '')
	title = title.replace(' AUD', ' ')
	title = title.replace(' USD', ' ')
	title = title.replace('New York Shares', '')
	title = title.replace('China Electric Vehicle and Battery ETF', 'China EV ETF')
	title = title.replace('China Electric Vehicle ETF', 'China EV ETF')
	title = title.replace('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable')
	title = title.replace('Advanced Micro Devices', 'AMD')
	title = title.replace('Taiwan Semiconductor Manufacturing', 'TSM')
	title = title.replace('Flight Centre Travel', 'Flight Centre')
	title = title.replace('Global X Funds ', '')
	title = title.replace(' of Australia', '')
	title = title.replace('National Australia Bank', 'NAB')
	title = title.replace(' PLC', '')
	title = title.replace(' p.l.c.', '')
	title = title.replace(' P.l.c.', '')
	title = title.replace(' P.L.C.', '')
	title = title.replace(' Units', '')
	if title.endswith(' AG'):
		title = title.replace(' AG', '')
	if title.endswith(' SE'):
		title = title.replace(' SE', '')
	if title.endswith(' Se'):
		title = title.replace(' SE', '')
	title = re.sub(r'\[\w+\]$', '', title)
	title = title.replace('Microbalifesciences', 'Microba Life Sciences')
	title = title.replace('Walt Disney Co (The)', 'Disney')
	title = title.replace('Lisenergylimited', 'LI-S Energy')
	title = title.replace('Invesco Capital Management LLC ', '')
	title = title.replace('QUALCOMM', 'Qualcomm')
	title = title.replace('Ordinary Shares Class A', '')
	title = title.replace('Ordinary Shares Class C', '')
	title = title.replace('Lbt Innovations', 'LBT Innovations')
	title = title.replace('Vanguard Information Technology', 'Vanguard Infotech')
	title = title.replace('The ', '')
	title = title.replace(' Shares', '')
	title = title.replace('Rea ', 'REA ')
	title = title.replace('Csl ', 'CSL ')
	title = title.replace('Battery ', 'Batt ')
	title = title.replace('.com', '')
	title = title.replace('Etf', 'ETF')
	title = title.replace('N.V.', '')
	title = title.replace(' NV ', ' ')
	title = title.replace('New York Re', '')
	title = title.replace(' Australian', ' Aus')
	title = title.replace(' Australia', ' Aus')
	title = title.replace(' Infrastructure', ' Infra')
	title = title.replace(' Manufacturing Company', ' ')
	title = title.replace(' Limited', ' ')
	title = title.replace(' Ltd', ' ')
	title = title.replace(' Holdings', ' ')
	title = title.replace(' Holding', ' ')
	title = title.replace(' (Holdings)', '')
	title = title.replace(' Corporation', ' ')
	title = title.replace(' Incorporated', ' ')
	title = title.replace(' incorporated', ' ')
	title = title.replace(' Technologies', ' ')
	title = title.replace(' Technology', ' ')
	title = title.replace(' Enterprises', ' ')
	title = title.replace(' Enterprise', ' ')
	title = title.replace(' Enterpr', ' ')
	title = title.replace(' Ventures', ' ')
	title = title.replace(' Resources', ' ')
	title = title.replace(' (Intrada', '')
	title = title.replace(' Structured', '')
	title = title.replace(' Co.', ' ')
	title = title.replace(' Corp.', ' ')
	title = title.replace(' Corp', ' ')
	title = title.replace(' Tech ', ' ')
	title = title.replace(' Company', ' ')
	title = title.replace(' Group', ' ')
	title = title.replace(', Inc', ' ')
	title = title.replace(' Inc', ' ')
	title = title.replace(' Plc', ' ')
	title = title.replace(' plc', ' ')
	title = title.replace(' Index', ' ')
	title = title.replace(' ADR', ' ')
	title = title.replace(' Daily', ' ')
	title = title.replace(' Long', ' ')
	title = title.replace(' Bull', ' ')
	title = title.replace(' .', ' ')
	title = title.replace(' ,', ' ')
	if title.islower():
		title = title.title()
	title = title.strip()
	if title.endswith(' &'):
		title = title.replace(' &', '')
	if title.endswith(' and'):
		title = title.replace(' and', '')
	title = title.replace(' Usd', ' USD')
	title = title.replace('  ', ' ')
	title = title.replace('Ishares', 'iShares')
	return title

def categorise_tickers(tickers):
	tickers_us = [] # used by fetch_finviz()
	tickers_au = [] # used by fetch_shortman()
	tickers_world = [] # used by fetch_yahoo()
	for ticker in tickers:
		if '.AX' in ticker:
			tickers_au.append(ticker)
		if '.' in ticker:
			tickers_world.append(ticker)
		else:
			tickers_us.append(ticker)
	return tickers_au, tickers_world, tickers_us

def flag_from_market(market):
	flag=''
	if market == 'ASX':
		flag = '🇦🇺'
	elif market in {'BOM', 'NSE'}:
		flag = '🇮🇳'
	elif market in {'BMV'}:
		flag = '🇲🇽'
	elif market in {'BKK'}:
		flag = '🇹🇭'
	elif market in {'BVMF'}:
		flag = '🇧🇷'
	elif market in {'SHE', 'SGX', 'SHA'}:
		flag = '🇨🇳'
	elif market == 'CPSE':
		flag = '🇩🇰'
	elif market in {'EURONEXT','AMS','ATH','BIT','BME','DUB','EBR','EPA','ETR','FWB','FRA','VIE'}:
		flag = '🇪🇺'
	elif market == 'HKG':
		flag = '🇭🇰'
	elif market == 'ICSE':
		flag = '🇮🇸'
	elif market in {'JSE'}:
		flag = '🇿🇦'
	elif market in {'KRX', 'KOSDAQ'}:
		flag = '🇰🇷'
	elif market == 'LSE':
		flag = '🇬🇧'
	elif market == 'MISX':
		flag = '🇷🇺'
	elif market in {'OM', 'STO'}:
		flag = '🇸🇪'
	elif market == 'SGX':
		flag = '🇸🇬'
	elif market in {'SWX', 'VTX'}:
		flag = '🇨🇭'
	elif market in {'TAI', 'TPE'}:
		flag = '🇹🇼'
	elif market == 'TASE':
		flag = '🇮🇱'
	elif market == 'OB':
		flag = '🇳🇴'
	elif market == 'TSE':
		flag = '🇯🇵'
	elif market == 'TSX':
		flag = '🇨🇦'
	elif market in {'BATS', 'AMEX'} or market.lower().startswith('nasdaq') or market.lower().startswith('nyse'):
		flag = '🇺🇸'
	elif market in {'WAR'}:
		flag = '🇵🇱'
	return flag

def flag_from_ticker(ticker):
	flag = ''
	if '.' in ticker:
		suffix = ticker.split('.')[1]
		if suffix == 'AS':
			flag = '🇳🇱'
		elif suffix == 'AX':
			flag = '🇦🇺'
		elif suffix == 'HK':
			flag = '🇭🇰'
		elif suffix in ('KS', 'KQ'):
			flag = '🇰🇷'
		elif suffix == 'L':
			flag = '🇬🇧'
		elif suffix == 'NS':
			flag = '🇮🇳'
		elif suffix == 'NZ':
			flag = '🇳🇿'
		elif suffix in ('TW', 'TWO'):
			flag = '🇹🇼'
		elif suffix == 'TO':
			flag = '🇨🇦'
	else:
		flag = '🇺🇸'
	return flag

def currency_from_market(market):
	if market == 'ASX':
		currency = 'AUD'
	elif market in {'BOM', 'NSE'}:
		currency = 'INR'
	elif market in {'BMV'}:
		currency = 'MXN'
	elif market in {'BKK'}:
		currency = 'THB'
	elif market in {'BVMF'}:
		currency = 'BRL'
	elif market in {'SHE', 'SGX', 'SHA'}:
		currency = 'CNY'
	elif market == 'CPSE':
		currency = 'DEK'
	elif market in {'EURONEXT','AMS','ATH','BIT','BME','DUB','EBR','EPA','ETR','FWB','FRA','VIE'}:
		currency = 'EUR'
	elif market == 'ICSE':
		currency = 'ISK'
	elif market in {'JSE'}:
		currency = 'ZAR'
	elif market in {'KRX', 'KOSDAQ'}:
		currency = 'KRW'
	elif market == 'MISX':
		currency = 'RUB'
	elif market in {'OM', 'STO'}:
		currency = 'SEK'
	elif market == 'SGX':
		currency = 'SGD'
	elif market in {'SWX', 'VTX'}:
		currency = 'CHF'
	elif market in {'TAI', 'TPE'}:
		currency = 'TWD'
	elif market == 'TASE':
		currency = 'ILS'
	elif market == 'OB':
		currency = 'NOK'
	elif market == 'TSE':
		currency = 'JPY'
	elif market == 'TSX':
		currency = 'CAD'
	elif market in {'NASDAQ', 'NYSE', 'BATS'}:
		currency = 'USD'
	elif market in {'WAR'}:
		currency = 'PLN'
	elif market == 'LSE':
		currency = 'GBP' # LSE allows non-home currencies, but this is better than trades.py using brokerage_currency_code which is AUD on CMC
	else:
		# note: LSE and HKE allow non-home currencies
		return None
	return currency

def get_currency_symbol(currency):
	currency_symbol=''
	if currency in {'AUD', 'CAD', 'HKD', 'NZD', 'SGD', 'TWD', 'USD'}:
		currency_symbol = '$'
	elif currency_symbol in {'CNY', 'JPY'}:
		currency_symbol = '¥'
	elif currency == 'EUR':
		currency_symbol = '€'
	elif currency == 'GBP':
		currency_symbol = '£'
	elif currency_symbol == 'KRW':
		currency_symbol = '₩'
	elif currency == 'RUB':
		currency_symbol = '₽'
	elif currency == 'THB':
		currency_symbol = '฿'
	return currency_symbol

def read_cache(cacheFile, maxSeconds=config_cache_seconds):
	cacheFile = config_cache_dir + "/" + cacheFile
	if os.path.isfile(cacheFile):
		maxSeconds = datetime.timedelta(seconds=maxSeconds)
		cacheFileMtime = datetime.datetime.fromtimestamp(os.path.getmtime(cacheFile))
		cacheFileAge = datetime.datetime.now() - cacheFileMtime
		if cacheFileAge < maxSeconds:
			if debug:
				ttl = maxSeconds - cacheFileAge
				print("cache hit:", cacheFile, "TTL:", td_to_human(ttl), file=sys.stderr)
			with open(cacheFile, "r", encoding="utf-8") as f:
				cacheDict = json.load(f)
			return cacheDict
		print("cache expired:", cacheFile, file=sys.stderr) if debug else None
		return None
	print("cache miss:", cacheFile, file=sys.stderr) if debug else None
	return None

def json_write(filename, data, persist=False):
	if persist:
		filename = config_var_dir + "/" + filename
	else:
		filename = config_cache_dir + "/" + filename
	os.umask(0)
	def opener(filename, flags):
		return os.open(filename, flags, 0o640)
	with open(filename, "w", opener=opener, encoding="utf-8") as f:
		if debug:
			print("cache write:", filename, file=sys.stderr)
		json.dump(data, f, indent=4)
	os.umask(0o022)

def json_load(filename, persist=False):
	if persist:
		filename = config_var_dir + "/" + filename
	else:
		filename = config_cache_dir + "/" + filename
	if os.path.isfile(filename):
		with open(filename, "r", encoding="utf-8") as f:
			data = json.load(f)
	else:
		data = None
	return data

def read_binary_cache(cacheFile, maxSeconds=config_cache_seconds):
	cacheFile = config_cache_dir + "/" + cacheFile
	if os.path.isfile(cacheFile):
		maxSeconds = datetime.timedelta(seconds=maxSeconds)
		cacheFileMtime = datetime.datetime.fromtimestamp(os.path.getmtime(cacheFile))
		cacheFileAge = datetime.datetime.now() - cacheFileMtime
		if cacheFileAge < maxSeconds:
			if debug:
				ttl = maxSeconds - cacheFileAge
				print("cache hit", cacheFile, "TTL:", td_to_human(ttl), file=sys.stderr)
			with open(cacheFile, "rb") as f:
				data = io.BytesIO(f.read())
			return data
		print("cache expired:", cacheFile, file=sys.stderr) if debug else None
		return None
	print("cache miss:", cacheFile, file=sys.stderr)
	return None

def write_binary_cache(cacheFile, data):
	cacheFile = config_cache_dir + "/" + cacheFile
	os.umask(0)
	def opener(path, flags):
		return os.open(path, flags, 0o640)
	with open(cacheFile, "wb", opener=opener) as f:
		data.seek(0)
		f.write(data.getbuffer())
	os.umask(0o022)

def humanUnits(value, decimal_places=2):
	for unit in ['', 'K', 'M', 'B', 'T', 'Q']:
		if value < 1000.0 or unit == 'Q':
			break
		value /= 1000.0
	return f"{value:.{decimal_places}f} {unit}"

def yahoo_link(ticker, service='telegram', brief=True, text=None):
	yahoo_url = "https://au.finance.yahoo.com/quote/"
	if brief and not text:
		text = ticker.split('.')[0]
	elif not text:
		text = ticker
	if service == 'telegram' and config_hyperlink:
		ticker_link = '<a href="' + yahoo_url + ticker + '">' + text + '</a>'
	elif service in {'discord', 'slack'} and config_hyperlink:
		ticker_link = '<' + yahoo_url + ticker + '|' + text + '>'
	else:
		ticker_link = text
	return ticker_link

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
		link = gfinance_link(symbol, exchange, service, days, brief, text)
	else:
		link = yahoo_link(ticker, service, brief, text)
	return link

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
	if service == 'telegram' and config_hyperlink:
		ticker_link = '<a href="' + url + ticker + '?window=' + window + '">' + text + '</a>'
	elif service in {'discord', 'slack'} and config_hyperlink:
		ticker_link = '<' + url + ticker + '?window=' + window + '|' + text + '>'
	else:
		ticker_link = symbol
	return ticker_link

def transform_to_google(exchange):
	if 'Nasdaq' in exchange:
		exchange = 'NASDAQ'
	elif exchange == 'Cboe US':
		exchange = 'BATS'
	elif exchange in {'OTC', 'PNK', 'Other OTC', 'OTCPK'}:
		exchange = 'OTCMKTS'
	elif exchange in {'TO', 'TOR', 'Toronto'}:
		exchange = 'TSE'
	elif exchange in {'TW', 'TWO', 'TAI', 'Taiwan', 'Taipei Exchange', 'Taipei'}:
		exchange = 'TPE'
	elif exchange in {'HK', 'HKG', 'HKSE'}:
		exchange = 'HKG'
	elif exchange in {'KQ', 'KOE', 'KOSDAQ'}:
		exchange = 'KOSDAQ'
	elif exchange in {'KS', 'KRX', 'KSE', 'KSC'}:
		exchange = 'KRX'
	elif exchange in {'L', 'LSE', 'London'}:
		exchange = 'LON'
	elif exchange in {'T', 'TYO', 'JPX', 'Tokyo'}:
		exchange = 'TYO'
	elif exchange in {'TA', 'TLV', 'Tel Aviv'}:
		exchange = 'TLV'
	return exchange

def exchange_human(exchange):
	if 'Nasdaq' in exchange or 'NYSE' in exchange or 'Other OTC' in exchange:
		return 'US'
	elif exchange in {'TO', 'TOR', 'Toronto'}:
		return 'CA'
	elif exchange in {'TW', 'TWO', 'TAI', 'Taiwan', 'Taipei Exchange', 'Taipei'}:
		return 'TW'
	elif exchange in {'HK', 'HKG', 'HKSE'}:
		return 'HK'
	elif exchange in {'KQ', 'KOE', 'KOSDAQ', 'KS', 'KRX', 'KSE', 'KSC'}:
		return 'KR'
	elif exchange in {'L', 'LSE', 'London'}:
		return 'UK'
	elif exchange in {'T', 'TYO', 'JPX', 'Tokyo'}:
		return 'JP'
	elif exchange in {'TA', 'TLV', 'Tel Aviv'}:
		return 'IL'
	elif exchange in {'NZSE', 'NZE', 'New Zealand', 'Auckland'}:
		return 'NZ'
	return exchange

def transform_to_yahoo(ticker, market=None):
	split = ticker.replace(':', '.').split('.')
	if len(split) > 1:
		ticker = split[0]
		market = split[1]
	if not market:
		return ticker
	if market == 'ASX':
		market = 'AX'
	if market == 'HKG':
		market = 'HK'
	if market == 'KRX':
		market = 'KS'
	if market == 'KOSDAQ':
		market = 'KQ'
	if market == 'LSE':
		market = 'L'
	if market == 'TAI': # Taiwan in YF, Sharesight
		market = 'TW' # TPE in GF
	if market == 'TPE': # Taipei in YF, Taiwan in GF. GF format will not work as input
		market = 'TWO' # missing from GF
	if market == 'TSE':
		market = 'TO'
	if market == 'TYO':
		market = 'T'
	if market == 'TLV':
		market = 'TA'
	if market in {'NASDAQ', 'NYSE', 'BATS', 'OTCMKTS'}:
		return ticker
	if market in {'A', 'B', 'C'}: # class shares
		return ticker + '-' + market
	ticker = ticker + '.' + market
	return ticker

def strip_url(url):
	url = url.removeprefix('https://www.')
	url = url.removeprefix('http://www.')
	url = url.removeprefix('https://')
	url = url.removeprefix('http://')
	return url

def make_paragraphs(walloftext):
	buffer = []
	output = []
	for word in walloftext.split():
		buffer.append(word)
		if word.endswith(('!', '.')) and len(buffer) > 22:
			output.append(' '.join(buffer))
			buffer = []
	output = '\n\n'.join(output)
	return output

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
	days = (end - start).days
	fmt = '%Y' if days > 1460 else '%b %Y' if days > 150 else '%d %b'
	ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=5))
	ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
	ax.tick_params(axis='x', colors=ink, labelsize=10, length=3, width=0.8, pad=6)
	for label in ax.get_xticklabels():
		label.set_fontweight('medium')

def graph(df, title, ylabel):
	"""Render a price chart as PNG bytes, sized for Telegram (1280px wide, no server-side resampling)."""
	from matplotlib.figure import Figure
	from matplotlib.backends.backend_agg import FigureCanvasAgg
	from matplotlib.ticker import MaxNLocator
	import pandas as pd
	# palette: dark surface, muted ink, green/red for up/down (red/green separated in lightness as well as hue)
	bg, ink, ink2, grid = '#14181f', '#eef1f5', '#9aa4b2', '#2a313c'
	up, down, flat = '#34d399', '#fb7185', '#9aa4b2'
	x = pd.to_datetime(df['Date'].astype(str))
	y = df['Close'].astype(float)
	first, last = y.iloc[0], y.iloc[-1]
	color = up if last > first else down if last < first else flat
	pct = (last - first) / first * 100 if first else 0
	arrow = '▲' if last > first else '▼' if last < first else '■'

	fig = Figure(figsize=(6.4, 4.0), dpi=200, facecolor=bg) # 1280x800
	FigureCanvasAgg(fig)
	ax = fig.add_axes([0.075, 0.105, 0.885, 0.755], facecolor=bg)
	ax.fill_between(x, y, y.min() - (y.max() - y.min()) * 0.15, color=color, alpha=0.14, linewidth=0)
	ax.plot(x, y, color=color, linewidth=1.6, solid_capstyle='round')
	ax.plot([x.iloc[-1]], [last], marker='o', markersize=5, color=color, markeredgecolor=bg, markeredgewidth=1.5, clip_on=False)

	# headroom above/below so annotations never leave the plot
	span = (y.max() - y.min()) or max(abs(y.max()) * 0.02, 1e-9)
	ax.set_ylim(y.min() - span * 0.22, y.max() + span * 0.17)
	ax.margins(x=0.02)
	ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
	ax.grid(axis='y', color=grid, linewidth=0.6)
	ax.set_axisbelow(True)
	for side in ax.spines.values():
		side.set_visible(False)
	ax.tick_params(colors=ink2, labelsize=8, length=0, pad=4)
	style_date_axis(ax, x.iloc[0], x.iloc[-1], ink)
	fit_left_margin(fig, ax)

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

	fig.text(0.03, 0.957, title, color=ink, fontsize=13, fontweight='bold', ha='left', va='center')
	fig.text(0.03, 0.910, f"{last:,.2f} {ylabel or ''}   {arrow} {abs(pct):.2f}%  over period", color=color, fontsize=8.5, ha='left', va='center')

	buf = io.BytesIO()
	fig.savefig(buf, format='png', facecolor=bg) # no bbox_inches='tight': keep exact 1280x800
	return buf

def compare_graph(series, title, subtitle=''):
	"""Rebased % change lines for 2-6 tickers. series: list of (label, pandas Series of closes), already cropped to the period.
	Returns PNG bytes (1280x800, Telegram's photo size)."""
	from matplotlib.figure import Figure
	from matplotlib.backends.backend_agg import FigureCanvasAgg
	from matplotlib.ticker import MaxNLocator, FuncFormatter
	bg, ink, ink2, grid = '#14181f', '#eef1f5', '#9aa4b2', '#2a313c'
	# categorical slots 1-5 and 7 of the validated dark palette; red/green are skipped because they mean down/up
	colors = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#9085e9']
	fig = Figure(figsize=(6.4, 4.0), dpi=200, facecolor=bg)
	FigureCanvasAgg(fig)
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
	ax.grid(axis='y', color=grid, linewidth=0.6)
	ax.set_axisbelow(True)
	for side in ax.spines.values():
		side.set_visible(False)
	ax.tick_params(colors=ink2, labelsize=8, length=0, pad=4)
	style_date_axis(ax, min(y.index[0] for _, y in rebased), max(y.index[-1] for _, y in rebased), ink)

	fit_left_margin(fig, ax)

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
		ax.annotate(f"{label}  {value:+.1f}%", xy=(y.index[-1], value), xycoords='data', xytext=(1.03, p), textcoords='axes fraction',
			ha='left', va='center', fontsize=7.5, color=ink, annotation_clip=False,
			arrowprops=dict(arrowstyle='-', color=color, linewidth=0.7, alpha=0.7, shrinkA=0, shrinkB=2, relpos=(0, 0.5)))
	fig.text(0.03, 0.957, title, color=ink, fontsize=13, fontweight='bold', ha='left', va='center')
	if subtitle:
		fig.text(0.03, 0.910, subtitle, color=ink2, fontsize=8.5, ha='left', va='center')
	buf = io.BytesIO()
	fig.savefig(buf, format='png', facecolor=bg)
	return buf

def get_emoji(number):
	if number > 0:
		#return '🔺'
		return '🔼'
	elif number < 0:
		return '🔻'
	else:
		return '▪️'

def days_from_human_days(arg):
	arg = arg.upper()
	today = datetime.datetime.now().date()
	if arg == 'YTD':
		target = today.replace(day=1, month=1)
		return (today - target).days
	try:
		days = int(arg.removesuffix('D'))
	except ValueError:
		try:
			days = int(arg.removesuffix('W')) * 7
		except ValueError:
			try:
				days = int(arg.removesuffix('M')) * 30
			except ValueError:
				days = int(arg.removesuffix('Y')) * 365
	return days

def get_holdings_and_watchlist():
	tickers = set(sharesight.get_holdings_wrapper())
	tickers.update(json_load('finbot_watchlist.json', persist=True))
	if 'GOOG' in tickers and 'GOOGL' in tickers:
		tickers.remove("GOOGL")
	tickers = sorted(set(tickers))
	return tickers

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
