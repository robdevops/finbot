""".trades: Sharesight buys and sells; a scheduled run reports only new ones (scheduled: trades.py)."""
import dataclasses
import datetime
import random
import sys

from lib import config
from lib import state
from lib import words
from lib import sharesight
from lib import delivery
from lib import formats
from lib import links
from lib import markets
from lib import yahoo

STATE_FILE = "finbot_sharesight_trades.json" # the ids of the trades reported


@dataclasses.dataclass(frozen=True)
class Trade:
	"""A buy or a sell, as the report shows it."""
	date: datetime.date
	id: int
	portfolio: str
	bought: bool
	value: int # price times units, in the trade's own currency (not Sharesight's value, in the portfolio's)
	currency: str
	symbol: str
	market: str # Yahoo's name for the exchange, when trades_use_yahoo is on
	holding_id: str


def run(dest=None, *, days=None, user='', portfolio_select=None):
	"""Post the buys and sells of the past `days`, in every portfolio or the one named: to the chat that asked (dest),
	else, only those not reported before, to the default chats. Raises sharesight.PortfolioNotFound for a name that is
	none of them."""
	interactive = dest is not None
	if days is None:
		days = config.prefs.past_days
	trades = gather(days, portfolio_select, set() if interactive else set(state.load(STATE_FILE, [])))
	for chat in delivery.targets(dest):
		payload = report(chat.dialect, trades, days, interactive)
		if interactive and not payload: # no trades, or none of them a buy or a sell
			when = formats.days_english(days, 'in the past ')
			payload = [f"{user} No trades {when}. {random.choice(words.noTradesVerb)}"]
		delivery.deliver(chat, delivery.Report(payload))
	if trades and not interactive: # recorded once the report is out
		with state.edit(STATE_FILE, []) as known:
			known.extend(sorted({trade.id for trade in trades}.difference(known)))


def gather(days, portfolio_select, known):
	"""The buys and sells of the past `days` in every portfolio or the one named, but those whose id is `known`, by
	date: each with its market and currency, from Yahoo with trades_use_yahoo (one fetch for all)."""
	raw = [trade for portfolio in sharesight.portfolios(portfolio_select) for trade in portfolio.trades(days)
		if trade['transaction_type'] in {'BUY', 'SELL'} and int(trade['id']) not in known]
	quotes = {}
	if raw and config.prefs.trades_use_yahoo:
		tickers = {markets.transform_to_yahoo(trade['symbol'], trade['market']) for trade in raw}
		try:
			print("Fetching tickers from Yahoo: ", tickers, file=sys.stderr)
			quotes = yahoo.fetch(tickers)
		except Exception as e:
			print("Warning: could not fetch Yahoo:", e, file=sys.stderr)
	trades = []
	for trade in raw:
		market = trade['market']
		if config.prefs.trades_use_yahoo:
			ticker = markets.transform_to_yahoo(trade['symbol'], market)
			try:
				market = quotes[ticker]['profile_exchange']
			except Exception as e:
				print("Warning: could not get market for", ticker, "from Yahoo:", e, file=sys.stderr)
		trades.append(Trade(date=datetime.datetime.strptime(trade['transaction_date'], '%Y-%m-%d').date(),
			id=int(trade['id']), portfolio=trade['portfolio'], bought=trade['transaction_type'] == 'BUY',
			value=round(float(trade['price']) * float(trade['quantity'])),
			currency=markets.currency_from_market(market) or trade['brokerage_currency_code'], symbol=trade['symbol'],
			market=market, holding_id=str(trade['holding_id'])))
	return sorted(trades, key=lambda trade: (trade.date, trade.id))


def report(service, trades, days, interactive):
	"""The trades in one network's markup, each linked to Sharesight and to the stock's page: under a heading per date
	when there are several dates, or when a chat asked for more than a day."""
	dates = sorted({trade.date for trade in trades})
	payload = []
	for date in dates:
		if len(dates) > 1 or (interactive and days > 1):
			payload += ["", service.bold(f"{date:%b %d}")]
		for trade in trades:
			if trade.date == date:
				action, emoji = ('bought', '💸') if trade.bought else ('sold', '🤑')
				url = f"https://portfolio.sharesight.com/holdings/{trade.holding_id}/dashboard/transactions"
				payload.append(' '.join([emoji, trade.portfolio, service.link(url, action), trade.currency,
					f'{trade.value}', links.finance_link(trade.symbol, trade.market, service),
					markets.flag_from_market(trade.market)]))
	return payload


def job(argv):
	"""Arguments of a scheduled run: trades.py takes none."""
	return 'trades.py', {}
