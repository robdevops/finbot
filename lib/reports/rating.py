"""Analysts' consensus rating changes since the last scheduled run (rating); .buy and .sell are in rankings."""
from lib import delivery
from lib import state
from lib import links
from lib import watchlist
from lib import yahoo

STATE_FILE = 'finbot_rating.json' # each chat's {ticker: [action, index]} as its last scheduled run saw them

def run(dest=None):
	"""Post the analysts' consensus ratings that changed since a chat's last scheduled run: to the chat that asked
	(dest), against its record; or, a scheduled run, to each of its chats (dest, a chat's job; else the home chats),
	recording for each the ratings it saw."""
	interactive = delivery.interactive(dest)
	market_data, seen = gather(watchlist.with_holdings())
	for chat in delivery.targets(dest):
		changes = changed(market_data, seen, state.load_for(chat.key, STATE_FILE, {}))
		delivery.deliver(chat, delivery.Report(report(chat.dialect, changes, interactive)))
		if seen and not interactive: # added to its record: a ticker missing from this run keeps its last rating
			with state.edit_for(chat.key, STATE_FILE, {}) as ratings:
				ratings.update(seen)

def gather(tickers):
	"""(the stocks' details; {ticker: [action, index]} of every rating seen, which counts only with its analysts)."""
	market_data = yahoo.fetch_details(tickers)
	seen = {}
	for ticker in tickers:
		details = market_data.get(ticker, {})
		try:
			action, index = details['recommend'], round(float(details['recommend_index']), 1)
		except (KeyError, ValueError):
			continue
		if 'recommend_analysts' in details:
			seen[ticker] = [action, index]
	return market_data, seen

def changed(market_data, seen, old):
	"""The ratings seen that changed from a chat's record (old, {ticker: [action, index]}): [(ticker, its details, old
	(action, index), new (action, index), analysts)]."""
	changes = []
	for ticker, (action, index) in seen.items():
		try:
			old_action, old_index = old[ticker]
		except (KeyError, TypeError, ValueError):
			continue
		if old_action and action != old_action:
			changes.append((ticker, market_data[ticker], (old_action, old_index), (action, index),
				market_data[ticker]['recommend_analysts']))
	return changes

def report(service, changes, interactive):
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
		payload.insert(0, service.bold('Consensus rating changes:'))
	elif interactive:
		payload = ["No rating changes found"]
	return payload

ARGUMENTS = '' # what a scheduled run takes: none

def job(argv):
	"""A scheduled run's arguments: (label, run's keyword arguments); rating takes none, and an argument raises
	ValueError."""
	if argv:
		raise ValueError('no arguments')
	return 'rating', {}
