"""Analysts' consensus rating changes since the last scheduled run (scheduled: rating.py). .buy and .sell are in rankings."""
from lib import delivery
from lib import state
from lib import links
from lib import markets
from lib import watchlist
from lib import yahoo

STATE_FILE = 'finbot_rating.json' # {ticker: [action, index]} as last seen

def run(dest=None, *, specific_stock=None):
	"""Post the analysts' consensus ratings that changed since the last scheduled run, which records the ratings it saw:
	to the chat that asked (dest), else to the default chats."""
	interactive = dest is not None
	tickers = [markets.transform_to_yahoo(specific_stock)] if specific_stock else watchlist.with_holdings()
	changes, seen = gather(tickers, specific_stock)
	for chat in delivery.targets(dest):
		delivery.deliver(chat, delivery.Report(report(chat.dialect, changes, tickers, specific_stock, interactive)))
	if seen and not interactive: # added to what is recorded: a ticker missing from this run keeps its last rating
		with state.edit(STATE_FILE, {}) as ratings:
			ratings.update(seen)

def gather(tickers, specific_stock):
	"""(the ratings that changed since the last scheduled run, [(ticker, its details, old [action, index], new [action,
	index], analysts)]; {ticker: [action, index]} of every rating seen)."""
	old = state.load(STATE_FILE, {})
	market_data = yahoo.fetch_details(tickers, strict=bool(specific_stock))
	changes, seen = [], {}
	for ticker in tickers:
		try:
			action = market_data[ticker]['recommend'].replace('_', ' ')
			index = round(float(market_data[ticker]['recommend_index']), 1)
			analysts = market_data[ticker]['recommend_analysts']
		except (KeyError, ValueError):
			continue
		seen[ticker] = [action, index]
		try:
			old_action, old_index = old[ticker]
		except (KeyError, TypeError, ValueError):
			continue
		if old_action and action != old_action:
			changes.append((ticker, market_data[ticker], (old_action, old_index), (action, index), analysts))
	return changes, seen

def report(service, changes, tickers, specific_stock, interactive):
	"""The rating changes in one network's markup, sorted: 📈 when the consensus improved (its index fell: 1 is a strong
	buy), 📉 when it worsened."""
	payload = []
	for ticker, data, (old_action, old_index), (action, index), analysts in changes:
		emoji = '📈' if old_index > index else '📉' if old_index < index else '▪️'
		ticker_link = links.finance_link(ticker, data['profile_exchange'], service, brief=False)
		before, after = service.bold(f'{old_index} {old_action}'), service.bold(f'{index} {action}')
		message = f"{before} to {after} ({analysts} analysts)"
		payload.append(f"{emoji} {data['profile_title']} ({ticker_link}) changed from {message}")
	payload.sort()
	if payload:
		if not specific_stock:
			payload.insert(0, service.bold('Consensus rating changes:'))
	elif interactive:
		payload = [f"No rating changes found for {tickers[0]}" if specific_stock else "No rating changes found"]
	return payload

def job(argv):
	"""Arguments of a scheduled run: rating.py takes none."""
	return 'rating.py', {}
