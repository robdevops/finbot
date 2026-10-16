"""Ranked lists of the stocks followed (.marketcap, .pe, .forward pe and .peg, .beta, .buy and .sell), and one stock's
market cap or ratio."""
from lib import log
from lib import answer
from lib import config
from lib import watchlist
from lib import formats
from lib import links
from lib import render
from lib import yahoo

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

def marketcap_list(service, chat, bottom=False, length=15):
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
		return ['No market cap data found']
	caps.sort(key=lambda cap: cap[0], reverse=not bottom)
	heading = f"{'Bottom' if bottom else 'Top'} {length} tracked stocks by market cap (USD)"
	return [service.bold(heading)] + [line for _, line in caps[:length]]

def prepare_rating_payload(service, chat, action, length=15):
	"""(payload, chart) of the `length` stocks a chat follows (by its key) rated `action` ('buy' or 'sell') by
	min_analysts or more analysts (fewer, and the consensus says little: ASX small caps covered by two to six brokers
	are nearly all a perfect 1.0 buy), the strongest rating first (1 is a strong buy, 5 a strong sell); on equal
	ratings, the one more analysts give first."""
	found = [] # (rating, analysts, line, ticker)
	for ticker, data in yahoo.fetch_details(watchlist.with_holdings(chat)).items():
		if 'recommend' not in data or data['recommend_analysts'] < config.settings.min_analysts:
			continue
		recommend = data['recommend']
		if (action == 'buy' and 'buy' in recommend) or (action == 'sell' and recommend in ('sell', 'underperform')):
			rating, analysts = round(data['recommend_index'], 2), data['recommend_analysts']
			line = f"{links.stock_line(ticker, data, service)} {rating} ({analysts} analysts)"
			found.append((rating, analysts, line, ticker))
	found = sorted(found, key=lambda row: (row[0] if action == 'buy' else -row[0], -row[1]))[:length]
	payload = [line for _, _, line, _ in found]
	if not payload:
		return [f"No tracked stocks rated {action} by {config.settings.min_analysts}+ analysts"], None
	message = f"Top {length} analyst {action} ratings for tracked stocks ({config.settings.min_analysts}+ analysts)"
	shown = [(formats.short_ticker(ticker), rating) for rating, _, _, ticker in found]
	low, high = min(r for _, r in shown), max(r for _, r in shown)
	spread = (high - low) or 0.2
	# zoom the axis onto the ratings so the bars fill the panel (ratings only run 1-5)
	chart = render.Chart('bars', message, 'Mean analyst rating: 1 = strong buy, 5 = strong sell (axis zoomed)',
		tuple(shown), value_format='number', xlim=(max(0.9, low - spread * 0.9), min(5.1, high + spread * 0.25)))
	return [service.bold(message)] + payload, chart

RATIOS = {'pe': 'price_to_earnings_trailing', 'forward pe': 'price_to_earnings_forward', 'peg': 'price_to_earnings_peg'}

def ratio_line(service, ticker, kind):
	"""One stock's line for .pe, .forward pe or .peg SYMBOL (kind: pe, forward pe or peg): its P/E, trailing and
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

def ratio_list(service, chat, kind, mode='top', length=15):
	"""(payload, chart): the `length` stocks a chat follows (by its key) by a ratio (kind: pe, forward pe or peg),
	lowest first (mode top), highest first (bottom), or the negative ones only, lowest first (negative). A forward P/E
	is analysts' estimate, so its list takes only stocks that min_analysts or more analysts cover, as .buy does."""
	field = RATIOS[kind]
	market_data = yahoo.fetch(watchlist.with_holdings(chat))
	if kind == 'peg': # the PEG is in Yahoo's details
		market_data |= yahoo.fetch_details(market_data)
	covered = None # for a forward P/E list: the tickers enough analysts cover
	if kind == 'forward pe':
		covered = {ticker for ticker, detail in yahoo.fetch_details(market_data).items()
			if detail.get('recommend_analysts', 0) >= config.settings.min_analysts}
	rows = [] # (ratio, chart label, line), one sorted list for the caption and the chart
	for ticker, data in market_data.items():
		ratio = data.get(field)
		if ratio is None or (covered is not None and ticker not in covered) or (ratio < 0) != (mode == 'negative'):
			continue # the negative ones, or none of them
		rows.append((ratio, formats.short_ticker(ticker), f"{links.stock_line(ticker, data, service)} {ratio}"))
	rows.sort(key=lambda row: row[0])
	if mode == 'bottom':
		rows.reverse()
	rows = rows[:length]
	trail = f'negative {kind}' if mode == 'negative' else kind # what the heading calls the ratio
	if not rows:
		if covered is not None:
			return [f"No tracked stocks with {config.settings.min_analysts}+ analysts have a {trail} ratio"], None
		return [f"{kind if mode == 'top' else f'{mode} {kind}'}: no data found"], None
	coverage = f" ({config.settings.min_analysts}+ analysts)" if covered is not None else ''
	heading = f"{'Bottom' if mode == 'bottom' else 'Top'} {length} tracked stocks by {trail} ratio{coverage}"
	bars = tuple((label, float(ratio)) for ratio, label, _ in rows)
	chart = render.Chart('bars', heading, rows=bars, value_format='number')
	return [service.bold(heading)] + [line for _, _, line in rows], chart

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
		return ['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'], None
	found.sort(key=lambda row: row[0], reverse=True)
	heading = 'Beta over 1.5 and mkt cap under US$2B'
	chart = render.Chart('bars', heading, rows=tuple(row for _, _, row in found), value_format='number')
	return [service.bold(heading)] + [line for _, line, _ in found], chart
