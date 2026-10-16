"""Analysts' consensus rating changes since the last scheduled run (rating); .buy and .sell are in rankings."""
from lib import reports
from lib import delivery
from lib import formats
from lib import state
from lib import links
from lib import watchlist
from lib import yahoo

STATE_FILE = 'finbot_rating.json' # each chat's {ticker: [action, index]} as its last scheduled run saw them

def run(dest=None):
	"""Post the analysts' consensus ratings of the stocks a chat follows that changed since its last scheduled run: to
	the chat that asked (dest), against its record; or, a scheduled run, to the job's chat (dest), recording the
	ratings it saw."""
	chat, interactive = delivery.target(dest), delivery.interactive(dest)
	market_data, seen = gather(watchlist.with_holdings(chat.key))
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
		payload.append(f"{emoji} {formats.short_name(data['profile_title'])} ({ticker_link}) changed from {message}")
	payload.sort()
	if payload:
		payload.insert(0, service.bold('Consensus rating changes:'))
	elif interactive:
		payload = ["No rating changes found"]
	return payload

ARGUMENTS = '' # what a scheduled run takes: none

job = reports.no_arguments('rating')
