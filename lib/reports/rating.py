"""Analysts' consensus rating changes since the last scheduled run (scheduled: rating.py). .buy and .sell are in rankings."""
from lib import webhook
from lib import state
from lib import links
from lib import markets
from lib import watchlist
from lib import yahoo

def lambda_handler(chat_id=None, specific_stock=None, service=None, interactive=False):
	"""Analysts' consensus ratings that changed since the last scheduled run, which records the ratings it saw."""
	def prepare_rating_payload(service, market_data):
		def get_emoji(old, new):
			if old > new:
				return '📈'
			if old < new:
				return '📉'
			else:
				return '▪️'
		payload = []
		new = {}
		for ticker in tickers:
			old_action=None
			old_index = float()
			try:
				action = market_data[ticker]['recommend'].replace('_', ' ')
				index = round(float(market_data[ticker]['recommend_index']), 1)
				analysts = market_data[ticker]['recommend_analysts']
			except (KeyError, ValueError):
				continue
			title = market_data[ticker]['profile_title']
			ticker_link = links.finance_link(ticker, market_data[ticker]['profile_exchange'], service, brief=False)
			new[ticker] = [action, index]
			try:
				old_action, old_index = old[ticker]
			except (KeyError, TypeError, ValueError):
				pass
			if old_action and action != old_action:
				emoji = get_emoji(old_index, index)
				message = f"{webhook.bold(f'{old_index} {old_action}', service)} to {webhook.bold(f'{index} {action}', service)} ({analysts} analysts)"
				payload.append(f"{emoji} {title} ({ticker_link}) changed from {message}")
		payload.sort()
		if payload:
			if not specific_stock:
				message = 'Consensus rating changes:'
				message = webhook.bold(message, service)
				payload.insert(0, message)
		else:
			if interactive:
				if specific_stock:
					payload = [f"No rating changes found for {tickers[0]}"]
				else:
					payload = ["No rating changes found"]
		return payload, new

	# MAIN #

	tickers = [markets.transform_to_yahoo(specific_stock)] if specific_stock else watchlist.with_holdings()
	old = state.load('finbot_rating.json', {})
	market_data = yahoo.fetch_details(tickers, strict=bool(specific_stock))

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, new = prepare_rating_payload(service, market_data)
		webhook.send(service, url, chat, payload)

	if new and not interactive: # added to what is recorded: a ticker missing from this run keeps its last rating
		with state.edit('finbot_rating.json', {}) as ratings:
			ratings.update(new)

def job(argv):
	return 'rating.py', {}
