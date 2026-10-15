"""What is held and followed: .holdings, .who, .pie and .watchlist."""
from lib import watchlist
from lib import sharesight
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import yahoo

def holding_line(holding, service, text=None):
	"""'🇦🇺 Title (CODE)' for a Sharesight holding, CODE (or `text`) linking to the holding on Sharesight."""
	link = service.link(f"https://portfolio.sharesight.com/holdings/{holding['holding_id']}/dashboard",
		holding['code'] if text is None else text)
	return f"{markets.flag_from_market(holding['market_code'])} {formats.transform_title(holding['name'])} ({link})"

def prepare_holdings_payload(portfolio_name, service):
	"""The holdings of the portfolio called `portfolio_name`. Raises sharesight.PortfolioNotFound."""
	portfolio, = sharesight.portfolios(portfolio_name)
	holdings = portfolio.holdings()
	payload = sorted(holding_line(holding, service) for holding in holdings.values())
	if payload:
		payload.insert(0, service.bold(f"Holdings for {portfolio.name} ({len(holdings)})"))
	return payload

def prepare_who(service, code):
	"""Which portfolios hold `code` (a ticker without its exchange), each holding linked to Sharesight."""
	blocks = []
	for portfolio in sharesight.portfolios():
		found = [holding_line(holding, service, code)
			for holding in portfolio.holdings().values() if holding['code'].upper() == code]
		blocks.append(found and [service.bold(f"{portfolio.name}:")] + found)
	return formats.sections(*blocks) or [f'{code} not found in any portfolio']

def prepare_pie(portfolio_name, by, service, max_slices=8):
	"""Portfolio value by industry (or by='sector'): (payload, chart or None). Raises sharesight.PortfolioNotFound."""
	portfolio, = sharesight.portfolios(portfolio_name)
	name = portfolio.name
	key = 'sector_classification_name' if by == 'sector' else 'industry_classification_name'
	totals = {}
	for holding in portfolio.holdings().values():
		try:
			value = float(holding.get('value'))
		except (TypeError, ValueError):
			continue
		if value > 0:
			label = holding.get(key) or 'Unclassified'
			totals[label] = totals.get(label, 0.0) + value
	if not totals:
		return [f"{name} has no holdings with a value"], None
	rows = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
	if len(rows) > max_slices:
		rest = sum(v for _, v in rows[max_slices - 1:])
		rows = rows[:max_slices - 1]
		rows.append(('Other', rest))
	total = sum(v for _, v in rows)
	title = f"{name} by {by}"
	payload = [service.bold(title)]
	payload += [f"{label}: {value / total * 100:.1f}%" for label, value in rows]
	noun = {'sector': ('sector', 'sectors'), 'industry': ('industry', 'industries')}[by]
	subtitle = f"{len(totals)} {noun[0] if len(totals) == 1 else noun[1]}"
	return payload, render.Chart('pie', title, subtitle, tuple(rows))

def prepare_watchlist(service, chat, user, action=None, ticker=None):
	"""The .watchlist reply in a chat (by its key): the companies it watches, or one line on adding ('add') or removing
	('delete') a ticker (Yahoo's symbol, as yahoo.symbol gives it)."""
	if action:
		return [watchlist_change(service, chat, user, action, ticker)]
	watched = watchlist.tickers(chat)
	market_data = yahoo.fetch(watched) if watched else {}
	lines = [links.stock_line(ticker, quote, service)
		for ticker, quote in sorted(market_data.items(), key=lambda item: item[1]['profile_title'].lower())]
	if not lines:
		return ['Watchlist is empty. Try ".watchlist add SYMBOL" to create it']
	return [f"Hi {user}, I'm currently tracking:"] + lines

def watchlist_change(service, chat, user, action, ticker):
	"""The reply to adding `ticker` (Yahoo's symbol) to a chat's watchlist, or removing it."""
	quote = yahoo.fetch([ticker]).get(ticker) or {}
	link = links.finance_link(ticker, quote.get('profile_exchange') or ticker, service)
	described = service.bold(f"{quote['profile_title']} ({link})" if quote.get('profile_title') else link)
	if action == 'delete':
		if not watchlist.remove(chat, ticker):
			return f"Beep Boop. I could not find {service.bold(ticker)} to remove it"
		return f"Ok {user}, I deleted {described}"
	if not quote:
		return f"Beep Boop. I could not find {service.bold(ticker)} to add it"
	if not watchlist.add(chat, ticker):
		return f"{user}, I'm already tracking {described}"
	return f"Ok {user}, I added {described}"
