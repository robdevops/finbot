""".trades: Sharesight buys and sells; a scheduled run reports only new ones (scheduled: trades)."""
import dataclasses
import datetime

from lib import answer
from lib import buttons
from lib import log
from lib import config
from lib import state
from lib import sharesight
from lib import delivery
from lib import formats
from lib import links
from lib import markets
from lib import yahoo

STATE_FILE = "finbot_sharesight_trades.json" # each chat's ids of the trades reported to it


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


def run(chat, *, days=None, user='', portfolio_select=None):
	"""Post the buys and sells of the past `days`, in every portfolio or the one named, to the chat: a command's, with
	period buttons, which show the trades of another span in place, and a line where there are none; or a job's, those
	it has not told the chat of before, raising answer.Nothing where there are none. Raises
	sharesight.PortfolioNotFound for a name that is none of them."""
	interactive = delivery.interactive(chat)
	if days is None:
		days = config.settings.past_days
	told = set() if interactive else set(state.load_for(chat.key, STATE_FILE, []))
	new = gather(days, portfolio_select, told) # those the chat was told of before are left out
	payload, when = report(chat.dialect, new, days, interactive), formats.days_english(days, 'in the past ')
	if not interactive and not payload:
		raise answer.Nothing(f"No new trades {when}.")
	markup = None
	if interactive:
		payload = payload or [f"{user} No trades {when}."]
		markup = buttons.keyboard('r', [portfolio_select or ''], buttons.period_for_days(days))
	delivery.deliver(chat, delivery.Report(payload, None, markup))
	if new and not interactive: # recorded once the report is out
		with state.edit_for(chat.key, STATE_FILE, []) as known:
			known.extend(sorted({trade.id for trade in new}.difference(known)))


def listing(service, days, portfolio_select=None):
	"""The lines a chat asking for the trades of the past `days` gets, as run() posts them, for a period button's press:
	the buys and sells, or a line saying there are none."""
	payload = report(service, gather(days, portfolio_select, set()), days, True)
	return payload or [f"No trades {formats.days_english(days, 'in the past ')}."]


def gather(days, portfolio_select, known):
	"""The buys and sells of the past `days` in every portfolio or the one named, but those whose id is `known`, by
	date: each with its market and currency, from Yahoo with trades_use_yahoo (one fetch for all)."""
	raw = [trade for portfolio in sharesight.portfolios(portfolio_select) for trade in portfolio.trades(days)
		if trade['transaction_type'] in {'BUY', 'SELL'} and int(trade['id']) not in known]
	quotes = {}
	if raw and config.settings.trades_use_yahoo:
		tickers = {markets.transform_to_yahoo(trade['symbol'], trade['market']) for trade in raw}
		try:
			quotes = yahoo.fetch(tickers)
		except Exception as e:
			log.warn("Warning: could not fetch Yahoo:", e)
	trades = []
	for trade in raw:
		market = trade['market']
		ticker = markets.transform_to_yahoo(trade['symbol'], market)
		# the currency by Sharesight's market code, which the table knows, not Yahoo's name for the exchange (NasdaqGS)
		currency = markets.currency_from_market(market) or quotes.get(ticker, {}).get('currency') or \
			trade['brokerage_currency_code']
		if config.settings.trades_use_yahoo:
			try:
				market = quotes[ticker]['profile_exchange']
			except Exception as e:
				log.warn("Warning: could not get market for", ticker, "from Yahoo:", e)
		trades.append(Trade(date=datetime.datetime.strptime(trade['transaction_date'], '%Y-%m-%d').date(),
			id=int(trade['id']), portfolio=trade['portfolio'], bought=trade['transaction_type'] == 'BUY',
			value=round(float(trade['price']) * float(trade['quantity'])),
			currency=currency, symbol=trade['symbol'],
			market=market, holding_id=str(trade['holding_id'])))
	return sorted(trades, key=lambda trade: (trade.date, trade.id))


def report(service, trades, days, interactive):
	"""The trades in one network's markup, each linked to Sharesight and to the stock's page: under a heading per date
	when there are several dates, or when a chat asked for more than a day."""
	def line(trade):
		"""One trade: who, bought or sold (linked to Sharesight), how much, and the stock."""
		action, emoji = ('bought', '💸') if trade.bought else ('sold', '🤑')
		url = f"https://portfolio.sharesight.com/holdings/{trade.holding_id}/dashboard/transactions"
		return ' '.join([emoji, trade.portfolio, service.link(url, action), trade.currency, f'{trade.value}',
			links.finance_link(trade.symbol, trade.market, service), markets.flag_from_market(trade.market)])
	dates = sorted({trade.date for trade in trades})
	headed = len(dates) > 1 or (interactive and days > 1)
	return formats.sections(*([service.bold(f"{date:%b %d}")] * headed + [line(trade) for trade in trades
		if trade.date == date] for date in dates))
