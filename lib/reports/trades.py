""".trades: Sharesight buys and sells; a scheduled run reports only new ones (scheduled: trades.py)."""
import random, sys
import datetime

from lib import config
from lib import state
from lib import words
from lib import sharesight
from lib import delivery
from lib import formats
from lib import links
from lib import markets
from lib import yahoo

def lambda_handler(chat_id=None, days=None, service=None, user='', portfolio_select=None, interactive=False):
	"""The buys and sells of the past `days`, in every portfolio or the one named: on a scheduled run only those not reported
	before. Raises sharesight.PortfolioNotFound for a name that is none of them."""
	if days is None:
		days = config.prefs.past_days
	state_file = "finbot_sharesight_trades.json"

	def prepare_trade_payload(service, trades):
		"""The report in one network's markup: the buys and sells (on a scheduled run only new ones), grouped by date,
		each linked to Sharesight and to the stock's page."""
		payload_staging = []
		dates = set()
		wanted = [] # the trades to report: buys and sells that are new (or all of them, when interactive)
		for trade in trades:
			if trade['transaction_type'] not in {'BUY', 'SELL'}:
				continue
			if not interactive and int(trade['id']) in known_trades:
				continue
			wanted.append(trade)
		if not wanted: # the usual case on a scheduled run
			return []
		market_data = {}
		if config.prefs.trades_use_yahoo:
			tickers = {markets.transform_to_yahoo(trade['symbol'], trade['market']) for trade in wanted} # one yahoo.fetch for all
			try:
				print("Fetching tickers from Yahoo: ", tickers, file=sys.stderr)
				market_data = yahoo.fetch(tickers)
			except Exception as e:
				print("Warning: could not fetch Yahoo:", e, file=sys.stderr)

		for trade in wanted:
			portfolio_name = trade['portfolio'] # custom field
			trade_id = int(trade['id'])
			date = trade['transaction_date'] # 2023-12-30
			symbol = trade['symbol']
			market = trade['market']
			action, emoji = ('bought', '💸') if trade['transaction_type'] == 'BUY' else ('sold', '🤑')
			units = float(trade['quantity'])
			price = float(trade['price'])
			currency = trade['brokerage_currency_code']
			if config.prefs.trades_use_yahoo:
				ticker = markets.transform_to_yahoo(symbol, market)
				try:
					market = market_data[ticker]['profile_exchange']
				except Exception as e:
					print("Warning: could not get market for", ticker, "from Yahoo:", e, file=sys.stderr)
			value = round(price * units) # not Sharesight's trade value, which it converts to the portfolio's currency
			holding_id = str(trade['holding_id'])
			dt_date = datetime.datetime.strptime(date, '%Y-%m-%d').date() # (2023, 12, 30)

			newtrades.add(trade_id) # recorded by the main body once the report is out
			dates.add(dt_date)

			flag = markets.flag_from_market(market)
			# lookup currency or fall back to less reliable sharesight currency
			currency_temp = markets.currency_from_market(market)
			if currency_temp:
				currency = currency_temp
			sharesight_url = "https://portfolio.sharesight.com/holdings/"
			trade_url = sharesight_url + holding_id + '/dashboard/transactions'
			trade_link = service.link(trade_url, action)
			holding_link = links.finance_link(symbol, market, service)
			payload_staging.append([dt_date, trade_id, emoji, portfolio_name, trade_link, currency, f'{value}', holding_link, flag])

		payload = []
		payload_staging.sort()
		for date in sorted(dates):
			if len(dates) > 1 or (interactive and days > 1):
				human_date = date.strftime('%b %d') # Dec 30
				payload.append("")
				payload.append(service.bold(human_date))
			for trade in payload_staging:
				if date == trade[0]:
					payload.append(' '.join(trade[2:]))

		return payload

	# MAIN #
	newtrades = set()
	known_trades = set(state.load(state_file, []))
	trades = [trade for portfolio in sharesight.portfolios(portfolio_select) for trade in portfolio.trades(days)]

	for dest in delivery.destinations(interactive, service, chat_id):
		service = dest.dialect
		payload = prepare_trade_payload(service, trades)
		if interactive and not payload: # no trades, or none of them a buy or a sell
			payload = [f"{user} No trades {formats.days_english(days, 'in the past ')}. {random.choice(words.noTradesVerb)}"]
		delivery.deliver(dest, delivery.Report(payload))

	if newtrades and not interactive:
		with state.edit(state_file, []) as known:
			known.extend(sorted(newtrades.difference(known)))

def job(argv):
	"""Arguments of a scheduled run: trades.py takes none."""
	return 'trades.py', {}
