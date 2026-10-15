"""What is held and followed: .holdings, .who, .pie and .watchlist."""
import re
from lib import watchlist
from lib import sharesight
from lib import formats
from lib import links
from lib import markets
from lib import yahoo

def holding_line(holding, service, text=None):
	"""'🇦🇺 Title (CODE)' for a Sharesight holding, CODE (or `text`) linking to the holding on Sharesight."""
	link = service.link(f"https://portfolio.sharesight.com/holdings/{holding['holding_id']}/dashboard", holding['code'] if text is None else text)
	return f"{markets.flag_from_market(holding['market_code'])} {formats.transform_title(holding['name'])} ({link})"

def prepare_holdings_payload(portfolio_name, service):
	"""The holdings of the portfolio called `portfolio_name`. Raises sharesight.PortfolioNotFound."""
	if not portfolio_name:
		names = [portfolio.name for portfolio in sharesight.portfolios()]
		return [".holdings: please try again specifying a portfolio:"] + names
	portfolio, = sharesight.portfolios(portfolio_name)
	holdings = portfolio.holdings()
	payload = sorted(holding_line(holding, service) for holding in holdings.values())
	if payload:
		payload.insert(0, service.bold(f"Holdings for {portfolio.name} ({len(holdings)})"))
	return payload

def prepare_who(service, code):
	"""Which portfolios hold `code` (a ticker without its exchange), each holding linked to Sharesight."""
	payload = []
	for portfolio in sharesight.portfolios():
		found = [holding_line(holding, service, code)
			for holding in portfolio.holdings().values() if holding['code'].upper() == code]
		if found:
			payload += [service.bold(f"{portfolio.name}:"), "\n".join(found), ""]
	return payload or [f'{code} not found in any portfolio']

def prepare_pie(portfolio_name, by, service, max_slices=8):
	"""Portfolio value by industry (or by='sector'): (payload, chart or None). Raises sharesight.PortfolioNotFound."""
	if not portfolio_name:
		names = [portfolio.name for portfolio in sharesight.portfolios()]
		return [".pie: please try again specifying a portfolio:"] + names, None
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
	return payload, {'pie': True, 'rows': rows, 'title': title, 'subtitle': subtitle}

def prepare_watchlist(service, user, action=None, ticker=None):
	"""The .watchlist reply: the companies watched, or one line on adding ('add') or removing ('delete') a ticker."""
	if action:
		return [watchlist_change(service, user, action, markets.transform_to_yahoo(ticker))]
	watched = watchlist.tickers()
	market_data = yahoo.fetch(watched) if watched else {}
	lines = sorted((f"{markets.flag_from_ticker(t)} {quote['profile_title']} ({links.finance_link(t, quote.get('profile_exchange'), service)})"
		for t, quote in market_data.items()), key=lambda line: re.findall('[A-Z].*', line)) # by name, the flag aside
	if not lines:
		return ['Watchlist is empty. Try ".watchlist add SYMBOL" to create it']
	return [f"Hi {user}, I'm currently tracking:"] + lines

def watchlist_change(service, user, action, asked):
	"""The reply to adding or removing `asked` (a Yahoo ticker)."""
	def described(ticker, quote):
		"""'Full Name (TICKER)' in bold, linked to the stock's page."""
		quote = quote or {}
		link = links.finance_link(ticker, quote.get('profile_exchange') or ticker, service)
		return service.bold(f"{quote['profile_title']} ({link})" if quote.get('profile_title') else link)
	if action == 'delete':
		if asked not in watchlist.tickers():
			return f"Beep Boop. I could not find {service.bold(asked)} to remove it"
		quote = yahoo.fetch([asked]).get(asked)
		watchlist.remove(asked)
		return f"Ok {user}, I deleted {described(asked, quote)}"
	found, quote = watchlist.find(asked)
	if not quote:
		return f"Beep Boop. I could not find {service.bold(asked)} to add it"
	added = watchlist.add(found)
	if found != asked:
		done = "so I added" if added else "and I'm already tracking"
		return f"Beep Boop. I could not find {service.bold(asked)} {done} {described(found, quote)}"
	return f"Ok {user}, I added {described(found, quote)}" if added else f"{user}, I'm already tracking {described(found, quote)}"
