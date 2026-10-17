# Commands and reports

What finbot does in a chat: its commands, and the reports that they and each chat's [scheduled jobs](scheduling.md) post.

## On each network
What finbot can do on each network. Telegram takes everything; the others take what their APIs allow.

| Feature | Telegram | Slack | Discord |
|---|---|---|---|
| Chat commands | ✓: slash commands (`/price`) from the command menu, and messages (`.price`) | ✓: slash commands (`/price`) from the app's manifest, and messages | ✓: slash commands (`/price`), and messages over the gateway API |
| "typing…" while a command works | ✓ | ⏳ on the command's message (Slack has no typing notice for bots); none for a slash command, which has no message | ✓ for a message; "thinking…" for a slash command |
| Charts in replies | ✓ | ✓ | ✓ |
| Charts in scheduled reports | ✓ | ✓ | ✓ |
| Slash commands completed as they are typed | names, from the command menu | names, with their usage | names, and the arguments: keywords, periods, portfolios, tickers, jobs |
| Period and job buttons | ✓ | ✓ | ✓ |
| No link previews | ✓ | ✓ | ✓ |
| Linked tickers | ✓ | ✓ | ✓ |
| Charts updated in place by their buttons | ✓ | ✓ | ✓ |
| A button pressed twice in a minute taken once | ✓ | ✓ | ✓ |

Each network's guide sets up its bot and compares its two modes: [Telegram](telegram.md), [Slack](slack.md), [Discord](discord.md).

![Screenshot of showing trade notifications on Slack](../img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

## Supported commands

Where:
* _percent_ is a number, optionally followed by '%'
* _period_ is a number followed by 'd', 'w', 'm' or 'y', or 'ytd'
* _portfolio_ is a Sharesight portfolio name
* _symbol_ is a Yahoo Finance symbol; a bare one Yahoo does not know is tried again on your exchange (`exchange_suffix`: `BHP` may be `BHP.AX`)
```
/stock symbol
/beta
/buysell
/earningsdividend [period|symbol]
/help
/holdings [portfolio]
/jobs [upcoming|system]
/jobs enable|disable|delete|run [number]
/jobs add report schedule
/jobs add message schedule "text"
/marketcap [symbol|top|bottom]
/movers [percent|top|bottom|session|premarket] [period]
/pe [symbol|top|bottom|negative]
/peg [symbol|top|bottom|negative]
/performance [period] [portfolio]
/price [symbol...] [period]
/shorts [percent|symbol]
/trades [period] [portfolio]
/treemap [portfolio] [sector|industry|country|currency|market]
/watchlist [add|del symbol]
/who symbol
```

Each command is a slash command on every network, which completes its name as it is typed: Telegram's command menu, set as finbot starts; Slack's, from the app's manifest (`util/slack_manifest.py`, see the [Slack guide](slack.md#slash-commands)); Discord's, registered as finbot starts. `/profile` is a second name of `/stock`, and `/job` of `/jobs`: no slash command of their own, they work when typed. `/help` lists the commands in chat.

Every command also works as a plain message, which is quicker to type on a phone: a dot in place of the slash (`.movers 7d`), or `!`, or the bot's name (`@botname movers 7d`). As a message, `.forward pe` is `/forwardpe`, and a symbol alone is `/stock` (`.AAPL`, `@botname AAPL`). A message reaches the bot wherever it reads the chat: on Telegram, a direct chat, or a group where it is an administrator; on Slack, a direct message, a mention, or every message with `--every-message`; on Discord, in gateway API mode. A command is its whole name, in any case, and so are its keywords (`.movers TOP`); any other first word is a symbol.

Trade notifications are peformed by polling the Sharesight trades API on a schedule (see [Scheduling](scheduling.md)), and notifying each chat that schedules them of any new trades. Thus, it works best if your trades are auto-imported into Sharesight through its broker integrations, and if your environment has persistent storage so that the bot can keep track of known trade IDs between runs.

The other various reports can also run on a schedule (e.g. daily or weekly), or on demand with a command. They query the Yahoo Finance API for stock data based on current holdings across your Sharesight portfolios, your friends' Sharesight portfolios, plus a custom watch list. A scheduled report posts to the chat whose job it is, and a command's reply to the chat that sent it.

The bot answers commands in every chat it is in. By default, it fetches its updates from each network itself (pull mode); alternatively, in push mode, each network pushes them to your HTTPS gateway, which passes them to the bot. It provides:
* Stock lookup (financials, company profile, price charts)
* A watch list per chat, which anyone in it can change, picked up by the reports there
* Listing of portfolios and portfolio performance
* A treemap of a portfolio (`/treemap portfolio [sector|industry|country|currency|market]`): the treemap tiles each holding by value, grouped and coloured by industry (the default), sector, country (its market's, as two letters, with a flag in the caption), currency or market
* Buttons to pick from where a command takes a portfolio or tickers and is typed without them: `/treemap`, `/holdings` (the first portfolio alphabetically; a treemap by industry, or by the grouping typed) and `/price` (the first ticker, over 7D unless a period or `max` is typed) answer at once, with the buttons under the chart: portfolios four to a row and `/treemap`'s Grouped by button after them, which opens a menu of Country, Currency, Industry, Market and Sector with Back (the one shown marked; a choice redoes the chart in place and keeps the menu open, Back returns to the portfolios); for tickers the period row, ending in `+` to the tickers (those held, else the chat's watchlist) with `<` `>` pages: up to 8 ticked, which OK draws. With one ticker ticked, `+` clears it, so that the first tick picks afresh. Another portfolio or ticker, a grouping or a period redoes the chart in place (a tick or a page of tickers changes only the buttons, on Telegram and Discord), and a `/treemap` draws its other charts in the background so the next press is quick. `/price T1 T2 [period]` typed with tickers gets the same period row and `+` when the tickers are among those held (else watched) and the period is a button one. Every chart with a period row, from any command, draws its other periods in the background once it is sent, so a period press is quick. Thirty-two items make a page (fewer on Discord, which holds five rows of five buttons). A job of one posts the same, buttons and all (but draws no charts ahead), and a chat with no buttons gets the usage instead
* Listing of holdings sorted by various attributes 
* Running the other stock reports on demand

## Reports

### Stock lookup
![Screenshot showing stock info on Slack](../img/stockinfo.png?raw=true "Screenshot showing stock info on Slack")

The stock lookup returns various stats relevant to a stock's valuation, growth and risk factors.

#### Emoji legend
* The colored circle next to the symbol at the top indicates the current market state:
    * 🔴 market closed
    * 🟠 pre/post-market
    * 🟢 normal trading
* The warning symbol ⚠️ indicates possible risk factors. This is not intended to replace due diligence, but to non-exhaustively highlight where additional diligence is due. Some risk factors include:
    * Negative earnings ⚠️
    * Earnings in decline ⚠️
    * Negative cashflow ⚠️
    * High short interest ⚠️
    * High forward P/E ratio ⚠️
    * Net insider selling ⚠️
    * High debt-to-equity ratio ⚠️
* The arrow grid indicates the directional change in the company earnings and revenue for each reporting period. A red arrow indicates the absolute earnings was negative:
    * 🔼 earnings/revenue increased from the previous period
    * 🔽 earnings/revenue decreased from the previous period
    * 🔺 earnings increased from the previous period but remained negative
    * 🔻 earnings decreased from the previous period and was negative
    * ▪️  earnings/revenue matched the previous period
    * ❌ data is missing for this period
* Using the example screenshot above, Crowdstrike reported:
    * 🔼🔼🔼 revenue increased in all of the past three quarters
    * 🔺🔻🔻 In the past three quarters, earnings initially increased, then decreased for two quarters, and was negative in every quarter
    * 🔼🔼🔼 revenue increased in all of the past three years
    * 🔻🔺🔻 In the past three years, earnings decreased, increased, then decreased, and was negative for all three years

This report is a command only. Example usage:
```
/stock AAPL
```
As a message: `.AAPL`, or `@botname AAPL`.

### Trades
![trade update in Slack](../img/trades.png?raw=true "Trade update in Slack")

The `trades` report sends recent Sharesight trades to each chat that schedules it.
By default, this report searches Sharesight for trades from the past 28 days (`past_days`). You can override this in `settings.conf`, or by providing a number as argument when triggered through the chat bot.

Without persistent storage, set `past_days=0` to avoid duplicate trade notifications. In this case, the schedule must run the report exactly once per day, after market close.

With persistent storage, the default of `past_days=28` suits. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to schedule it every 20 minutes.

```
past_days=28
```

Job (see [Scheduling](scheduling.md)), such as `/jobs add trades every 20 mins weekdays`:
```
trades
```

Command:
```
/trades [period]
```

You can also specify a portfolio name to get trades for just that portfolio:
```
/trades [period] [portfolio]
```

The reply has period buttons (1D, 7D, 1M) that show the trades of that span in place, for the portfolio named if one was. A scheduled report has none.

### Movers
![Movers chart triggered from Slack](../img/finbot_price.png?raw=true "Movers chart triggered from Slack")
![Movers alert posted by a job](../img/price.png?raw=true "Movers alert posted by a job")

The `movers` report sends premarket, midsession, and interday price movements if any holdings moved over a percentage threshold, as a bar chart: one bar per stock, its change over the period. This data is sourced from Yahoo! Finance and Sharesight. The default threshold is 5% but you can change it by setting `price_percent` in the `settings.conf`, or by providing a number as argument when triggered through the chat bot. Decimal fractions are accepted.

If `demote_volatile` is `true`, stocks with a [market cap](https://www.investopedia.com/terms/m/marketcapitalization.asp) under US$150M, or a [beta](https://www.investopedia.com/terms/b/beta.asp) of > 1.5 and a market cap of under US$1B will have their alert threshold (`price_percent`) doubled. A market cap in another currency is converted at Yahoo's exchange rate.

Config example:
```
price_percent=5
demote_volatile=True
```

Job (see [Scheduling](scheduling.md)), such as `/jobs add movers close weekdays at 4:30pm New York`:
```
movers premarket|midsession|interday|close|DAYS
```
When scheduled, the mode is its argument:
* If `premarket` is passed, it only reports on pre/post market price movements.
* If `midsession` is passed, it only reports for markets currently in session. This is intended to run on a schedule to provide mid-session alerts for big price movements of your holdings. For example, it could be run twice per day 12 hours apart, to capture markets in different timezones.
* If `interday` is passed, it reports current price against the previous market close.
* If `close` is passed, it reports daily change in stocks whose market closed in the past 3 hours.
* If an integer [i] is passed, it reports current price against [i] days ago.

Command (pre-market, with a symbol for one stock's):
```
/movers premarket [percent|symbol]
```

Command (mid-session, with a symbol for one stock's):
```
/movers session [percent|symbol]
```

Command (interday).
```
/movers [percent]
```

For interday, can also specify the time period. A bare number is the percent; a period carries its unit: `7d`, `2w`, `3m`, `1y` or `ytd`. For example, `/movers 3 7d` lists the moves of 3% or more over the past week.
```
/movers [percent] [period]
```

Or the ten best and the ten worst over the period, whatever their moves:
```
/movers top|bottom [period]
```

`/movers` was `/price` until `/price` became the price line chart (see [Price](#price)); `/price` with a percent, `top` or `bottom` and no symbol says so. `/session` and `/premarket` were commands of their own: they are `/movers session` and `/movers premarket` now, and still answer when typed.

### Portfolio performance
![Screenshot of Portfolio performance notification on Slack](../img/performance.png?raw=true "Screenshot performance notification on Slack")

The `performance` report covers Sharesight portfolio performance over a given period. The default is set by `past_days` in the `settings.conf`, which can be overridden at runtime by specifying an integer as the argument. The portfolios are listed by name, then the S&P 500 and NASDAQ 100 benchmarks, in the list and the chart alike.

Config example:
```
past_days=28
```

Job (see [Scheduling](scheduling.md)), such as `/jobs add performance weekly`:
```
performance [DAYS]
```

Command:
```
/performance [period]
```

As a command, it also takes a portfolio:
```
/performance [period] [portfolio]
```

### Events calendar
![earnings message in Slack](../img/earnings.png?raw=true "Earnings message in Slack")

The `cal` report sends upcoming earnings and ex-dividend date alerts. The data is sourced from Yahoo! Finance. It reports on events up to `future_days` into the future. This is set in the `settings.conf` for a scheduled run, or can be specified as an argument when triggered through the chat bot.

**Finance Explainer:** When a company releases its quarterly earnings report, the stock price may undergo a signficant positive or negative movement, depending on whether the company beat or missed market expectations. You may wish to hold off buying more of this stock until after its earnings report, unless you think the stock will beat market expectations.

**Finance Explainer:** When a stock goes ex-dividend, the share price [typically drops](https://www.investopedia.com/articles/stocks/07/ex_dividend.asp) by the amount of the dividend paid. If you buy right before the ex-dividend date, you can expect an unrealised capital loss, plus a tax obligation for the dividend. Thus, you may wish to wait for the ex-dividend date before buying more of this stock.
```
future_days=30
```

Job (see [Scheduling](scheduling.md)), such as `/jobs add cal earnings every sunday at 8:30am`:
```
cal earnings|ex-dividend
```

Command (the coming earnings, then the ex-dividend dates; for a period, or one symbol):
```
/earningsdividend [period|symbol]
```

Typed, `.earnings` gives the earnings alone and `.dividend` the ex-dividend dates alone.

### Highly shorted stock warnings
![short warnings in Slack](../img/shorts.png?raw=true "Short warnings in Slack")

The `shorts` report sends short interest warnings. The data is sourced from Yahoo Finance and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. This can be specified in the `settings.conf` for a scheduled run, or as an argument when triggered through the chat bot.

**Finance Explainer:** A high short ratio indicates a stock is exposed to high risks, such as potential banktrupcy. It may also incentivise negative news articles which harm the stock price. If the market is wrong, however, risk tolerant investors may receive windfall gains. This report is intended to alert you to an above-average risk, and prompt you to investigate this stock more closely.
```
shorts_percent=15
```

Command:
```
/shorts [percent]
```

### pe / peg
![Forward PE report in Slack](../img/finbot_fpe.png?raw=true "Forward PE report in Slack")

List securities by forward P/E ratio (`/pe`), or PEG ratio. A forward P/E is an analysts' estimate, so its lists take only stocks covered by at least `min_analysts` analysts (7 by default; see `settings.conf`).

Command:
```
/pe [SYMBOL|top|bottom|negative]
/peg [SYMBOL|top|bottom|negative]
```

### Price
![One stock's price line in Slack](../img/finbot_history.png?raw=true "One stock's price line in Slack")

One stock's price line over a period, green or red with its change and filled below, its high and low marked; or two
to eight stocks' changes over the period, rebased on one chart. Max is a stock's whole history, and ten years for
several. Typed, `.compare` and `.history` are other names for it.

Command:
```
/price [symbol...] [period]
```

### Buy and sell
![Buy ratings in Slack](../img/finbot_buy.png?raw=true "Buy ratings in Slack")
![Rating report in Slack](../img/finbot_sell.png?raw=true "Rating report in Slack")

Show the top recommended buys, then the top recommended sells, by Yahoo Finance analysts rating, among stocks rated by at least `min_analysts` analysts (7 by default; see `settings.conf`). Typed, `.buy` gives the buys alone and `.sell` the sells alone.

Command:
```
/buysell
```

### Marketcap
![Marketcap report in Slack](../img/finbot_marketcap.png?raw=true "Marketcap report in Slack")

List the top (or bottom) stocks by market cap, in US dollars: market caps in other currencies are converted at Yahoo's exchange rates. With a symbol, its market cap in its own currency and in US dollars.

Command:
```
/marketcap [top|bottom|SYMBOL]
```

### Consensus rating changes
![Rating change report in Slack](../img/finbot_rating.png?raw=true "Rating change report in Slack")

Notifies when Yahoo Finance analyst rating consensus changes category (e.g. from hold to buy). Designed to run on a schedule, such as `/jobs add rating tue-sat at 8:30am` (see [Scheduling](scheduling.md)). Requires persistent storage.

```
rating
```

### Watchlist
![Shared watchlist in Slack](../img/watchlist.png?raw=true "Shared watchlist in Slack")

Tracks additional securities which are not in your Sharesight holdings. Each chat has its own watchlist, which anyone in the chat can change: the reports in that chat, asked for or scheduled, include its watchlist's stocks as if they were holdings, and no other chat's. The Sharesight holdings are the same in every chat. `yahoo_warm` keeps every chat's watchlist warm in the cache.

The watchlists are kept in `finbot_watchlist.json` in the data directory, by chat (`{"chats": {"telegram:-1001234": ["2454.TW", "ASO.AX", "STEM"]}}`), so there is no need to edit the file.

Command (with an Edit button, where the chat has buttons: it offers each ticker, which a press strikes through, and Delete deletes the struck ones; none under an empty watchlist):
```
/watchlist
```
```
/watchlist [add|del] [symbol]
```
