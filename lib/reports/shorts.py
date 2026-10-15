""".shorts: the most shorted stocks followed, from Short Man (ASX) and Yahoo (scheduled: shorts.py)."""
from lib import config
from lib import webhook
from lib import markets
from lib import render
from lib import watchlist
from lib import yahoo
from lib import shortman

def lambda_handler(chat_id=None, threshold=None, specific_stock=None, service=None, interactive=False):
	"""Post the stocks followed whose short interest is over `threshold` percent (the shorts_percent preference when
	None), or one stock's: to the chat that asked (interactive), else to the default chats. Short Man has the ASX's
	figures, Yahoo the US's."""
	if threshold is None:
		threshold = config.prefs.shorts_percent
	def prepare_shorts_payload(service, market_data):
		"""(the report in one network's markup, its chart or None), the most shorted first."""
		found = [] # (percent, line, chart label)
		for ticker in tickers:
			try:
				short_percent = float(market_data[ticker]['short_percent'])
			except (KeyError, ValueError):
				continue
			if short_percent > threshold or specific_stock:
				code = ticker.split('.')[0]
				url = 'https://www.shortman.com.au/stock?q=' + code if ticker.endswith('.AX') else 'https://finance.yahoo.com/quote/' + ticker + '/key-statistics?p=' + ticker
				found.append((short_percent, f"🩳 {market_data[ticker]['profile_title']} ({service.link(url, code)}) {round(short_percent)}%", code))
		found.sort(key=lambda row: row[0], reverse=True) # largest first, as the chart has them
		payload, graph = [line for _, line, _ in found], None
		if payload and not specific_stock:
			payload.insert(0, service.bold(f'Tracked stocks shorted over {threshold:g}%'))
			if webhook.takes_charts(service, interactive):
				graph = render.shorts_chart([(code, percent) for percent, _, code in found], threshold)
		elif not payload and interactive:
			payload = [f"🩳 No short interest found for {tickers[0]}" if specific_stock else f"🩳 No stocks shorted over {threshold:g}%. Try specifying a number."]
		return payload, graph

	# MAIN #

	if specific_stock:
		ticker = markets.transform_to_yahoo(specific_stock)
		tickers = [ticker]
	else:
		tickers = watchlist.with_holdings()

	market_data = yahoo.fetch(tickers)
	market_data |= yahoo.fetch_details((ticker for ticker in tickers if '.' not in ticker), strict=bool(specific_stock)) # US short interest; Short Man has the ASX's
	market_data = shortman.fetch(market_data)

	for service, url, chat in webhook.destinations(interactive, service, chat_id):
		payload, graph = prepare_shorts_payload(service, market_data)
		webhook.send(service, url, chat, payload, graph)

def job(argv):
	"""Arguments of a scheduled run: shorts.py takes none."""
	return 'shorts.py', {}
