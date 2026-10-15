"""Ranked lists of the stocks followed: .marketcap, .pe, .fpe and .peg (top, bottom, negative), .beta, .buy and .sell."""
import sys
from lib import answer
from lib import config
from lib import watchlist
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import yahoo

def prepare_marketcap_payload(service, action='top', length=15):
	"""The `length` tracked stocks of largest (action 'top') or smallest ('bottom') market cap, compared in US dollars at Yahoo's
	exchange rates: a market cap in won or yen is a far bigger number. Any other action is one ticker's, in its own currency too."""
	if action not in ('top', 'bottom'):
		ticker = markets.transform_to_yahoo(action.upper())
		data = yahoo.add_usd_market_caps(yahoo.fetch_detail(ticker, 600)).get(ticker, {})
		if 'market_cap' not in data:
			return [f"Mkt cap not found for {ticker}"]
		currency = yahoo.market_cap_currency(data) or ''
		cap = f"{currency} {formats.human_units(data['market_cap'])}".strip()
		if currency != 'USD' and 'market_cap_usd' in data:
			cap += f" (USD {formats.human_units(data['market_cap_usd'])})"
		link = links.finance_link(ticker, data.get('profile_exchange', ''), service)
		return [formats.security_line(markets.flag_from_ticker(ticker), data.get('profile_title', ticker), link) + f" mkt cap: {cap}"]
	caps = [] # (market cap in US dollars, line)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch(watchlist.with_holdings())).items():
		if 'market_cap_usd' not in data:
			print(ticker, "no market cap" if 'market_cap' not in data else f"no exchange rate for {data.get('currency')}", file=sys.stderr)
			continue
		link = links.finance_link(ticker, data['profile_exchange'], service)
		line = formats.security_line(markets.flag_from_ticker(ticker), data['profile_title'], link)
		caps.append((data['market_cap_usd'], line + f" mkt cap: {formats.human_units(data['market_cap_usd'])}"))
	if not caps:
		return ['No market cap data found']
	caps.sort(key=lambda cap: cap[0], reverse=action == 'top')
	return [service.bold(f'{action.title()} {length} tracked stocks by market cap (USD)')] + [line for _, line in caps[:length]]

def prepare_rating_payload(service, action, length=15):
	"""(payload, chart) of the `length` tracked stocks rated `action` ('buy' or 'sell') by min_analysts or more analysts (fewer,
	and the consensus says little: ASX small caps covered by two to six brokers are nearly all a perfect 1.0 buy), the strongest
	rating first (1 is a strong buy, 5 a strong sell); on equal ratings, the one more analysts give first."""
	found = [] # (rating, analysts, line, ticker)
	for ticker, data in yahoo.fetch_details(watchlist.with_holdings()).items():
		if 'recommend' not in data or data['recommend_analysts'] < config.prefs.min_analysts:
			continue
		recommend = data['recommend'].replace('_', ' ')
		if (action == 'buy' and 'buy' in recommend) or (action == 'sell' and recommend in ('sell', 'underperform')):
			rating, analysts = round(data['recommend_index'], 2), data['recommend_analysts']
			link = links.finance_link(ticker, data['profile_exchange'], service)
			found.append((rating, analysts, f"{markets.flag_from_ticker(ticker)} {data['profile_title']} ({link}) {rating} ({analysts} analysts)", ticker))
	found = sorted(found, key=lambda row: (row[0] if action == 'buy' else -row[0], -row[1]))[:length]
	payload = [line for _, _, line, _ in found]
	if not payload:
		return [f"No tracked stocks rated {action} by {config.prefs.min_analysts}+ analysts"], None
	message = f"Top {length} analyst {action} ratings for tracked stocks ({config.prefs.min_analysts}+ analysts)"
	shown = [(ticker.split('.')[0], rating) for rating, _, _, ticker in found]
	low, high = min(r for _, r in shown), max(r for _, r in shown)
	spread = (high - low) or 0.2
	# zoom the axis onto the ratings so the bars fill the panel (ratings only run 1-5)
	chart = render.Chart('bars', message, 'Mean analyst rating: 1 = strong buy, 5 = strong sell (axis zoomed)',
		tuple(shown), value_format='number', xlim=(max(0.9, low - spread * 0.9), min(5.1, high + spread * 0.25)))
	return [service.bold(message)] + payload, chart

RATIOS = {'pe': 'price_to_earnings_trailing', 'forward pe': 'price_to_earnings_forward', 'peg': 'price_to_earnings_peg'}

def prepare_value_payload(service, action='pe', ticker_select=None, length=15):
	"""(payload, chart): the tracked stocks by a ratio of RATIOS, or one ticker's. action is the ratio, or 'bottom' or
	'negative' and the ratio: lowest first, highest first ('bottom'), or the negative ones only, lowest first. A forward
	P/E is analysts' estimate, so its lists take only stocks that min_analysts or more analysts cover, as .buy does."""
	mode, kind = action.split(' ', 1) if action.split()[0] in ('bottom', 'negative') else ('top', action)
	field = RATIOS[kind]
	tickers = [ticker_select] if ticker_select else watchlist.with_holdings()
	market_data = yahoo.fetch(tickers)
	if kind == 'peg': # the PEG is in Yahoo's details
		market_data |= yahoo.fetch_details(market_data, strict=bool(ticker_select))
	covered = None # for a forward P/E list: the tickers enough analysts cover
	if kind == 'forward pe' and not ticker_select:
		covered = {ticker for ticker, detail in yahoo.fetch_details(market_data).items()
			if detail.get('recommend_analysts', 0) >= config.prefs.min_analysts}
	rows = [] # (ratio, chart label, line), one sorted list for the caption and the chart
	for ticker, data in market_data.items():
		ratio = data.get(field)
		if ratio is None or (covered is not None and ticker not in covered):
			continue
		if not ticker_select and (ratio < 0) != (mode == 'negative'): # a list: the negative ones, or none of them
			continue
		link = links.finance_link(ticker, data.get('profile_exchange'), service)
		start = f"{markets.flag_from_ticker(ticker)} {data.get('profile_title')} ({link})"
		if ticker_select and mode == 'top' and kind in ('pe', 'forward pe'): # one stock's P/E: trailing and forward
			both = (('trailing', 'price_to_earnings_trailing'), ('forward', 'price_to_earnings_forward'))
			parts = ', '.join(f'{name} {data[key]}' for name, key in both if data.get(key) is not None)
			rows.append((ratio, None, f"{start} PE: {parts}"))
		else:
			rows.append((ratio, ticker.split('.')[0], f"{start} {ratio}"))
	rows.sort(key=lambda row: row[0])
	if mode == 'bottom':
		rows.reverse()
	if ticker_select:
		if not rows: # Yahoo does not know it, or sends no such ratio for it (a loss-maker has no trailing P/E)
			raise answer.Answer(f"{ticker_select}: no {kind.upper()} found" if ticker_select in market_data
				else f"{ticker_select}: no data found")
		return [line for _, _, line in rows], None
	rows = rows[:length]
	trail = kind if mode != 'negative' else action # what the heading calls the ratio
	if not rows:
		if covered is not None:
			return [f"No tracked stocks with {config.prefs.min_analysts}+ analysts have a {trail} ratio"], None
		return [f"{action}: no data found"], None
	coverage = f" ({config.prefs.min_analysts}+ analysts)" if covered is not None else ''
	heading = f"{'Bottom' if mode == 'bottom' else 'Top'} {length} tracked stocks by {trail} ratio{coverage}"
	bars = tuple((label, float(ratio)) for ratio, label, _ in rows)
	chart = render.Chart('bars', heading, rows=bars, value_format='number')
	return [service.bold(heading)] + [line for _, _, line in rows], chart

def prepare_beta_payload(service):
	"""(payload, chart) of the tracked stocks with a beta over 1.5 and a market cap under US$2B, the highest beta first."""
	found = [] # (beta, line, chart row)
	for ticker, data in yahoo.add_usd_market_caps(yahoo.fetch_details(watchlist.with_holdings())).items():
		if 'beta' not in data:
			continue
		beta = round(data['beta'], 1)
		if beta > 1.5 and data.get('market_cap_usd', float('inf')) < 2e9:
			link = links.finance_link(ticker, data['profile_exchange'], service)
			found.append((beta, formats.security_line(markets.flag_from_ticker(ticker), data['profile_title'], link) + f" {beta} β", (ticker.split('.')[0], float(beta))))
	if not found:
		return ['No tracked stocks have a beta over 1.5 and mkt cap under US$2B'], None
	found.sort(key=lambda row: row[0], reverse=True)
	heading = 'Beta over 1.5 and mkt cap under US$2B'
	chart = render.Chart('bars', heading, rows=tuple(row for _, _, row in found), value_format='number')
	return [service.bold(heading)] + [line for _, line, _ in found], chart
