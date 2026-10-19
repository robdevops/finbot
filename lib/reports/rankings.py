"""Ranked lists of the stocks followed (.marketcap, .ratio, .beta, .buy and .sell), and one stock's
market cap or ratio."""
from lib import log
from lib import answer
from lib import config
from lib import watchlist
from lib import formats
from lib import links
from lib import render
from lib import yahoo

LENGTH = 15 # the stocks a ranking lists
PAIRED = 10 # the stocks in each of two lists in one message (.buy & sell)

def marketcap_line(service, ticker):
	"""One stock's market cap, in its own currency, and in US dollars too where that is another. Raises answer.Answer
	when Yahoo has none."""
	data = yahoo.add_usd_market_caps(yahoo.fetch_detail(ticker, 600)).get(ticker, {})
	if 'market_cap' not in data:
		raise answer.Answer(f"Mkt cap not found for {ticker}")
	currency = yahoo.market_cap_currency(data) or ''
	cap = f"{currency} {formats.human_units(data['market_cap'])}".strip()
	if currency != 'USD' and 'market_cap_usd' in data:
		cap += f" (USD {formats.human_units(data['market_cap_usd'])})"
	return f"{links.stock_line(ticker, data, service)} mkt cap: {cap}"

def marketcap_list(service, chat, bottom=False, length=LENGTH):
	"""The `length` stocks a chat follows (by its key) of largest (or, `bottom`, smallest) market cap, compared in US
	dollars at Yahoo's exchange rates: a market cap in won or yen is a far bigger number."""
	caps = [] # (market cap in US dollars, line)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch(watchlist.with_holdings(chat))).items():
		if 'market_cap_usd' not in data:
			why = "no market cap" if 'market_cap' not in data else f"no exchange rate for {data.get('currency')}"
			log.debug(ticker, why)
			continue
		cap = formats.human_units(data['market_cap_usd'])
		caps.append((data['market_cap_usd'], f"{links.stock_line(ticker, data, service)} mkt cap: {cap}"))
	if not caps:
		raise answer.Nothing('No market cap data found')
	caps.sort(key=lambda cap: cap[0], reverse=not bottom)
	heading = f"{'Bottom' if bottom else 'Top'} {length} tracked stocks by market cap (USD)"
	return [service.bold(heading)] + [line for _, line in caps[:length]]

def rated(details, action, length):
	"""[(rating, analysts, line, ticker)] of the `length` stocks (Yahoo's details by ticker) rated `action` ('buy' or
	'sell') by min_analysts or more analysts (fewer, and the consensus says little: ASX small caps covered by two to six
	brokers are nearly all a perfect 1.0 buy), the strongest rating first (1 is a strong buy, 5 a strong sell); on
	equal ratings, the one more analysts give first."""
	found = [] # (rating, analysts, line, ticker)
	for ticker, data in details.items():
		if 'recommend' not in data or data['recommend_analysts'] < config.settings.min_analysts:
			continue
		recommend = data['recommend']
		if (action == 'buy' and 'buy' in recommend) or (action == 'sell' and recommend in ('sell', 'underperform')):
			rating, analysts = round(data['recommend_index'], 2), data['recommend_analysts']
			found.append((rating, analysts, (ticker, data, rating, analysts), ticker))
	return sorted(found, key=lambda row: (row[0] if action == 'buy' else -row[0], -row[1]))[:length]

def prepare_rating_payload(service, chat, actions, length=None, asked=True):
	"""(payload, chart) of the `length` stocks a chat follows (by its key) rated each of `actions` ('buy' and 'sell',
	in the order asked; LENGTH for one list, PAIRED for each of two where None): one list each, and one bar chart with
	the sells in red. A list with no stocks says so, where someone asked; none at all raises answer.Nothing."""
	length = length or (LENGTH if len(actions) == 1 else PAIRED)
	details = yahoo.fetch_details(watchlist.with_holdings(chat))
	analysts = f"{config.settings.min_analysts}+ analysts" # in each list's heading, and in the chart's subtitle
	blocks, notes, rows, red, shown = [], [], [], [], []
	for action in actions:
		found = rated(details, action, length)
		if not found:
			notes.append(f"No tracked stocks rated {action} by {analysts}")
			continue
		title = f"Top {length} analyst {action} ratings for tracked stocks"
		blocks.append([service.bold(f"{title} ({analysts})")] + [
			f"{links.stock_line(ticker, data, service)} {rating} ({count} analysts)"
			for _, _, (ticker, data, rating, count), _ in found])
		if rows:
			rows.append(('', None)) # a gap between the lists
		if action == 'sell':
			red += range(len(rows), len(rows) + len(found))
		rows += [(formats.short_ticker(ticker), rating) for rating, _, _, ticker in found]
		shown += [rating for rating, *_ in found]
	if not blocks:
		raise answer.Nothing(*notes)
	if len(blocks) > 1:
		title = f"Top {length} analyst buy and sell ratings for tracked stocks"
	payload = formats.sections(*blocks, notes if asked else [])
	low, high = min(shown), max(shown)
	spread = (high - low) or 0.2
	# zoom the axis onto the ratings so the bars fill the panel (ratings only run 1-5)
	chart = render.Chart('bars', title, f"Mean rating of {analysts}: 1 = strong buy, 5 = strong sell (axis zoomed), "
		+ formats.date_short(formats.today(), True), tuple(rows), value_format='number',
		xlim=(max(0.9, low - spread * 0.9), min(5.1, high + spread * 0.25)), red_rows=tuple(red))
	return payload, chart

RATIOS = {'forward pe': 'price_to_earnings_forward', 'trailing pe': 'price_to_earnings_trailing',
	'peg': 'price_to_earnings_peg'}
ESTIMATES = ('forward pe', 'peg') # the ratios that are analysts' estimates: their lists need min_analysts of them

def ratio_line(service, ticker, kind):
	"""One stock's line for .pe (the forward P/E) or .peg SYMBOL (kind: forward pe or peg): its P/E, trailing and
	forward where Yahoo has them, or its PEG. Raises answer.Answer when Yahoo knows neither the stock nor the ratio (a
	loss-maker has no trailing P/E)."""
	data = yahoo.fetch([ticker]).get(ticker)
	if data is None:
		raise answer.Answer(f"{ticker}: no data found")
	if kind == 'peg': # the PEG is in Yahoo's details
		data |= yahoo.fetch_details([ticker], strict=True).get(ticker, {})
		figures = f"PEG: {data['price_to_earnings_peg']}" if data.get('price_to_earnings_peg') is not None else ''
	else:
		both = (('trailing', 'price_to_earnings_trailing'), ('forward', 'price_to_earnings_forward'))
		figures = ', '.join(f'{name} {data[key]}' for name, key in both if data.get(key) is not None)
		figures = f"PE: {figures}" if figures else ''
	if not figures:
		raise answer.Answer(f"{ticker}: no {kind} ratio found")
	return f"{links.stock_line(ticker, data, service)} {figures}"

def ratio_list(service, chat, kind, mode='top', length=LENGTH):
	"""(payload, chart): the `length` stocks a chat follows (by its key) by a ratio (kind: forward pe, trailing pe or
	peg), lowest first (mode top), highest first (bottom), or the negative ones only, lowest first (negative). A
	forward P/E and a PEG are analysts' estimates (of earnings, of their growth), so their lists take only stocks that
	min_analysts or more analysts cover, as .buy does; a trailing P/E is of earnings reported, and takes all."""
	field = RATIOS[kind]
	market_data = yahoo.fetch(watchlist.with_holdings(chat))
	covered = None # the tickers enough analysts cover, for the estimates
	if kind in ESTIMATES:
		details = yahoo.fetch_details(market_data) # how many analysts cover each, and its PEG
		if kind == 'peg':
			market_data |= details
		covered = {ticker for ticker, detail in details.items()
			if detail.get('recommend_analysts', 0) >= config.settings.min_analysts}
	rows = [] # (ratio, chart label, line), one sorted list for the caption and the chart
	for ticker, data in market_data.items():
		ratio = data.get(field)
		if ratio is None or (covered is not None and ticker not in covered) or (ratio < 0) != (mode == 'negative'):
			continue # too few analysts; the negative ones, or none of them
		rows.append((ratio, formats.short_ticker(ticker), f"{links.stock_line(ticker, data, service)} {ratio}"))
	rows.sort(key=lambda row: row[0])
	if mode == 'bottom':
		rows.reverse()
	rows = rows[:length]
	trail = f'negative {kind}' if mode == 'negative' else kind # what the heading calls the ratio
	analysts = f"{config.settings.min_analysts}+ analysts" if covered is not None else '' # in the heading and subtitle
	if not rows:
		raise answer.Nothing(f"No tracked stocks with {analysts} have a {trail} ratio" if analysts else
			f"No tracked stocks have a {trail} ratio")
	heading = f"{'Bottom' if mode == 'bottom' else 'Top'} {length} tracked stocks by {trail} ratio"
	subtitle = ', '.join(filter(None, (analysts, formats.date_short(formats.today(), True))))
	chart = render.Chart('bars', heading, subtitle, tuple((label, float(ratio)) for ratio, label, _ in rows),
		value_format='number')
	return [service.bold(heading + (f" ({analysts})" if analysts else ''))] + [line for _, _, line in rows], chart

def prepare_beta_payload(service, chat):
	"""(payload, chart) of the stocks a chat follows (by its key) with a beta over 1.5 and a market cap under US$2B,
	highest beta first."""
	found = [] # (beta, line, chart row)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch_details(watchlist.with_holdings(chat))).items():
		if 'beta' not in data:
			continue
		beta = round(data['beta'], 1)
		if beta > 1.5 and data.get('market_cap_usd', float('inf')) < 2e9:
			line = f"{links.stock_line(ticker, data, service)} {beta} β"
			found.append((beta, line, (formats.short_ticker(ticker), float(beta))))
	if not found:
		raise answer.Nothing('No tracked stocks have a beta over 1.5 and mkt cap under US$2B')
	found.sort(key=lambda row: row[0], reverse=True)
	heading = 'Beta over 1.5 and mkt cap under US$2B'
	chart = render.Chart('bars', heading, formats.date_short(formats.today(), True), tuple(row for _, _, row in found),
		value_format='number')
	return [service.bold(heading)] + [line for _, line, _ in found], chart
