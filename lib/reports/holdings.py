"""What is held and followed: .holdings, .who, .treemap and .watchlist."""
from lib import answer
from lib import buttons
from lib import watchlist
from lib import sharesight
from lib import formats
from lib import links
from lib import markets
from lib import render
from lib import yahoo

def holding_line(holding, service, text=None):
	"""'🇦🇺 Title (CODE)' for a Sharesight holding, CODE (or `text`) linking to the holding on Sharesight."""
	link = service.link(links.holding_url(holding['holding_id']), holding['code'] if text is None else text)
	name = formats.short_name(formats.transform_title(holding['name']))
	return f"{markets.flag_from_market(holding['market_code'])} {name} ({link})"

def prepare_holdings_payload(portfolio_name, service):
	"""The holdings of the portfolio called `portfolio_name`. Raises sharesight.PortfolioNotFound, and answer.Nothing
	for one that holds nothing."""
	portfolio, = sharesight.portfolios(portfolio_name)
	holdings = portfolio.holdings()
	if not holdings:
		raise answer.Nothing(f"{portfolio.name} holds nothing")
	return [service.bold(f"Holdings for {portfolio.name} ({len(holdings)})")] + sorted(holding_line(holding, service)
		for holding in holdings.values())

def prepare_who(service, code):
	"""Which portfolios hold `code` (a ticker without its exchange), each holding linked to Sharesight. Raises
	answer.Nothing for none."""
	blocks = []
	for portfolio in sharesight.portfolios():
		found = [holding_line(holding, service, code)
			for holding in portfolio.holdings().values() if holding['code'].upper() == code]
		blocks.append(found and [service.bold(f"{portfolio.name}:")] + found)
	found = formats.sections(*blocks)
	if not found:
		raise answer.Nothing(f'{code} not found in any portfolio')
	return found

GROUPS = buttons.GROUPS
GROUPED = 'industry' # what a treemap is grouped by unless told
NOUNS = {'sector': ('sector', 'sectors'), 'industry': ('industry', 'industries'),
	'country': ('country', 'countries'), 'currency': ('currency', 'currencies'), 'market': ('market', 'markets')}

def grouping(key):
	"""What a picker's group key (a key of GROUPS, or 0 for none chosen) groups a treemap by: a value of GROUPS."""
	return GROUPS.get(key, GROUPED)

def group_of(holding, by):
	"""The group a Sharesight holding is in by `by` (a value of GROUPS): its sector or industry, its market's country
	(its letters: the charts' font draws no flags), its currency or its market; 'Unclassified' where it has none."""
	market = holding.get('market_code') or ''
	country = markets.exchange_human(market) if market else ''
	label = {'sector': holding.get('sector_classification_name'),
		'industry': holding.get('industry_classification_name'), 'country': country,
		'currency': holding.get('currency_code'), 'market': market}[by]
	return label or 'Unclassified'

def _groups(portfolio, by):
	"""The holdings of a portfolio with a value, by `by` (a value of GROUPS): {group: [(code, value), ...]}."""
	groups = {}
	for holding in portfolio.holdings().values():
		try:
			value = float(holding.get('value'))
		except (TypeError, ValueError):
			continue
		if value > 0:
			groups.setdefault(group_of(holding, by), []).append((holding['code'], value))
	return groups

def _noun(by, count):
	"""'3 industries', '1 sector'."""
	singular, plural = NOUNS[by]
	return f"{count} {singular if count == 1 else plural}"

def prepare_treemap(portfolio_name, by, service, max_groups=8):
	"""The holdings as tiles grouped by `by` (a value of GROUPS): (payload, chart or None). Beyond `max_groups`
	the smallest groups are one 'Other'. Raises sharesight.PortfolioNotFound."""
	portfolio, = sharesight.portfolios(portfolio_name)
	name = portfolio.name
	groups = _groups(portfolio, by)
	if not groups:
		return [f"{name} has no holdings with a value"], None
	rows = sorted(((label, sorted(held, key=lambda item: item[1], reverse=True)) for label, held in groups.items()),
		key=lambda row: sum(value for _, value in row[1]), reverse=True)
	if len(rows) > max_groups:
		rest = sorted((item for _, held in rows[max_groups - 1:] for item in held), key=lambda item: item[1],
			reverse=True)
		rows = rows[:max_groups - 1] + [('Other', rest)]
	total = sum(value for _, held in rows for _, value in held)
	title = f"{name} treemap by {by}"
	payload = [service.bold(title)]
	shown = lambda label: f"{markets.flag(label)} {label}".lstrip() if by == 'country' else label # a country's flag
	payload += [f"{shown(label)}: {sum(value for _, value in held) / total * 100:.1f}%" for label, held in rows]
	count = sum(len(held) for held in groups.values())
	subtitle = f"{_noun(by, len(groups))}, {count} {'holding' if count == 1 else 'holdings'}"
	return payload, render.Chart('treemap', title, subtitle, tuple((label, tuple(held)) for label, held in rows))

def prepare_watchlist(service, chat, user, action=None, ticker=None, removing=()):
	"""The .watchlist reply in a chat (by its key): the companies it watches, those of `removing` struck through, or one
	line on adding ('add') or removing ('delete') a ticker (Yahoo's symbol, as yahoo.symbol gives it)."""
	if action:
		return [watchlist_change(service, chat, user, action, ticker)]
	watched = watchlist.tickers(chat)
	market_data = yahoo.fetch(watched) if watched else {}
	lines = [service.strike(links.stock_line(ticker, quote, service)) if ticker in removing else
		links.stock_line(ticker, quote, service)
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
