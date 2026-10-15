# finbot

## Description

### Features
* Discord, Slack and Telegram support
* [Sharesight](https://www.sharesight.com/au/) API features:
  * Trade notifications
  * Portfolio performance
  * Holdings list
* Yahoo Finance data for Sharesight holdings:
  * Analyst consensus changes
  * Earnings date reminders
  * Ex-dividend date warnings
  * Highly shorted stock warnings (AU, US)
  * Interday and premarket price movements over a defined threshold
* Chat commands (Telegram, Slack & Discord), with no server to host:
  * All the above reports
  * Price history graph
  * Stock lookup with price/valuation related stats and warnings
  * Company profiles
  * A watch list per chat
  * List stocks (holdings + watchlist) by P/E, Forward P/E, PEG, market cap, or Yahoo analyst consensus

### Chat networks
What finbot can do on each network. Telegram takes everything; the others take what their APIs allow.

| Feature | Telegram | Slack | Discord |
|---|---|---|---|
| Chat commands | ✓ | ✓ | ✓: slash commands (`/price`), and messages (`.price`) over the gateway |
| "typing…" while a command works | ✓ | ⏳ on the command's message (Slack has no typing notice for bots) | ✓ for a message; "thinking…" for a slash command |
| Charts in replies | ✓ | ✓ | ✓ |
| Charts in scheduled reports | ✓ | ✓ | ✓ |
| Period and job buttons | ✓ | ✓ | ✓ |
| No link previews | ✓ | ✓ | ✓ |
| Linked tickers | ✓ | ✓ | ✓ |
| Charts updated in place by their buttons | ✓ | ✓ | ✓ |

**Setting up a network:** [Telegram](doc/telegram.md) · [Slack](doc/slack.md) · [Discord](doc/discord.md). Each guide
covers the whole setup of that network's bot, and compares its two modes (finbot fetching its updates, or the network
posting them to your HTTPS server) before the steps.

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

### Requirements
* Most features require a Sharesight paid plan, preferably with automatic trade imports, and an API key
* A Telegram bot, a Slack app or a Discord bot (see the network's guide, above)
* No server: finbot fetches its updates from each network itself (pull mode: Telegram's long polling, Slack's Socket Mode, Discord's gateway). In HTTP mode instead, a network posts them to a public web server with a domain name and a matching certificate, which proxies them to the bot (see the [Telegram](doc/telegram.md#http-mode), [Slack](doc/slack.md#http-mode) and [Discord](doc/discord.md#http-mode) guides).
* Python 3.13.5 (the version in `.python-version`; 3.12 is the minimum)
* Python modules, pinned to versions with 3.13 support in `requirements.txt`:
```
croniter python-dateutil requests matplotlib numpy
```
* For a network in http mode (its webhook URL set), also `waitress` (Debian: `python3-waitress`); for Slack in Socket
  Mode, `websocket-client` (`python3-websocket`); for Discord's gateway, `discord.py` (`python3-discord`), and for its
  http mode, `PyNaCl` (`python3-nacl`). The optional modules are in `requirements-optional.txt`, each imported only by
  the mode that needs it.

### Supported commands

Where:
* _percent_ is a number, optionally followed by '%'
* _period_ is a number followed by 'd', 'w', 'm' or 'y', or 'ytd'
* _portfolio_ is a Sharesight portfolio name
* _symbol_ is a Yahoo Finance symbol; a bare one Yahoo does not know is tried again on your exchange (`exchange_suffix`: `BHP` may be `BHP.AX`)
```
.symbol
.stock symbol
.beta
.buy
.sell
.compare symbol symbol [symbol...] [period]
.dividend [period|symbol]
.earnings [period|symbol]
.forward pe [symbol|top|bottom|negative]
.history symbol
.holdings portfolio
.jobs [run|toggle] [number]
.jobs add [CRON_TZ=zone] time report
.jobs del number
.marketcap [symbol|top|bottom]
.pe [symbol|top|bottom]
.peg [symbol|top|bottom|negative]
.performance [period] [portfolio]
.pie portfolio [sector]
.plan [your plan]
.premarket [percent|symbol]
.price [percent|symbol|top|bottom] [period]
.session [percent|symbol]
.shorts [percent|symbol]
.trades [period] [portfolio]
.watchlist [add|del symbol]
.who symbol
```

`!` or `/` work in place of the dot, and so does the bot's name: `@botname price 7d`, `@botname AAPL`. Each command is also a slash command, as Discord registers them: `/stock symbol` (or `/profile symbol`) for `.symbol`, `/forwardpe` for `.forward pe`. A command is its whole name, in any case, and so are its keywords (`.price TOP`); any other first word is a symbol. `.help` lists the commands in chat.

Trade notifications are peformed by polling the Sharesight trades API on a schedule (see [Scheduling](#scheduling)), and notifying each chat that schedules them of any new trades. Thus, it works best if your trades are auto-imported into Sharesight through its broker integrations, and if your environment has persistent storage so that the bot can keep track of known trade IDs between runs.

The other various reports can also run on a schedule (e.g. daily or weekly), or on demand with a command. They query the Yahoo Finance API for stock data based on current holdings across your Sharesight portfolios, your friends' Sharesight portfolios, plus a custom watch list. A scheduled report posts to the chat whose job it is, and a command's reply to the chat that sent it.

The bot answers commands in every chat it is in. It fetches its updates from each network itself, with no server to host (pull mode); in HTTP mode instead, a network posts them to a web service you host on a domain with a trusted certificate. It provides:
* Stock lookup (financials, company profile, price charts)
* A watch list per chat, which anyone in it can change, picked up by the reports there
* Listing of portfolios and portfolio performance
* Listing of holdings sorted by various attributes 
* Running the other stock reports on demand

## Reports

### Stock lookup
![Screenshot showing stock info on Slack](img/stockinfo.png?raw=true "Screenshot showing stock info on Slack")

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
.AAPL
```
```
@botname AAPL
```

### Trades
![trade update in Slack](img/trades.png?raw=true "Trade update in Slack")

The `trades` report sends recent Sharesight trades to each chat that schedules it.
By default, this report searches Sharesight for trades from the past 28 days (`past_days`). You can override this in `preferences.conf`, or by providing a number as argument when triggered through the chat bot.

Without persistent storage, set `past_days=0` to avoid duplicate trade notifications. In this case, the schedule must run the report exactly once per day, after market close.

With persistent storage, the default of `past_days=28` suits. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to schedule it every 20 minutes.

```
past_days=28
```

Job (see [Scheduling](#scheduling)), such as `.jobs add */20 * * * Mon-Fri trades`:
```
trades
```

Command:
```
.trades [period]
```
```
@botname trades [period]
```

You can also specify a portfolio name to get trades for just that portfolio:
```
.trades [period] [portfolio]
```
```
@botname trades [period] [portfolio]
```

### Price alerts
![Price chart triggered from Slack](img/finbot_price.png?raw=true "Price chart triggered from Slack")
![Price alert triggered by Cron](img/price.png?raw=true "Price alert triggered by Cron")

The `price` report sends premarket, midsession, and interday price movements if any holdings moved over a percentage threshold. This data is sourced from Yahoo! Finance and Sharesight. The default threshold is 5% but you can change it by setting `price_percent` in the `preferences.conf`, or by providing a number as argument when triggered through the chat bot. Decimal fractions are accepted.

If `demote_volatile` is `true`, stocks with a [market cap](https://www.investopedia.com/terms/m/marketcapitalization.asp) under US$150M, or a [beta](https://www.investopedia.com/terms/b/beta.asp) of > 1.5 and a market cap of under US$1B will have their alert threshold (`price_percent`) doubled. A market cap in another currency is converted at Yahoo's exchange rate.

Config example:
```
price_percent=5
demote_volatile=True
```

Job (see [Scheduling](#scheduling)), such as `.jobs add 29 21 * * Mon-Fri price interday`:
```
price premarket|midsession|interday|close|DAYS
```
When scheduled, the mode is its argument:
* If `premarket` is passed, it only reports on pre/post market price movements.
* If `midsession` is passed, it only reports for markets currently in session. This is intended to run on a schedule to provide mid-session alerts for big price movements of your holdings. For example, it could be run twice per day 12 hours apart, to capture markets in different timezones.
* If `interday` is passed, it reports current price against the previous market close.
* If `close` is passed, it reports daily change in stocks whose market closed in the past 3 hours.
* If an integer [i] is passed, it reports current price against [i] days ago.

Command (pre-market):
```
.premarket [percent]
```
```
@botname premarket [percent]
```

Command (mid-session):
```
.session [percent]
```
```
@botname session [percent]
```

Command (interday).
```
.price [percent]
```
```
@botname price [percent]
```

For interday, can also specify the time period. A bare number is the percent; a period carries its unit: `7d`, `2w`, `3m`, `1y` or `ytd`. For example, `.price 3 7d` lists the moves of 3% or more over the past week.
```
.price [percent] [period]
```

Or a specific stock. In this case, the output includes a graph.
```
.price [symbol] [period]
```

### Portfolio performance
![Screenshot of Portfolio performance notification on Slack](img/performance.png?raw=true "Screenshot performance notification on Slack")

The `performance` report covers Sharesight portfolio performance over a given period. The default is set by `past_days` in the `preferences.conf`, which can be overridden at runtime by specifying an integer as the argument.

Config example:
```
past_days=28
```

Job (see [Scheduling](#scheduling)), such as `.jobs add 28 21 * * Sat performance 7`:
```
performance [DAYS]
```

Command:
```
.performance [period]
```
```
@botname performance [period]
```

As a command, it also takes a portfolio:
```
.performance [period] [[portfolio]
```
```
@botname performance [period] [portfolio]
```

### Events calendar
![earnings message in Slack](img/earnings.png?raw=true "Earnings message in Slack")

The `cal` report sends upcoming earnings and ex-dividend date alerts. The data is sourced from Yahoo! Finance. It reports on events up to `future_days` into the future. This is set in the `preferences.conf` for a scheduled run, or can be specified as an argument when triggered through the chat bot.

**Finance Explainer:** When a company releases its quarterly earnings report, the stock price may undergo a signficant positive or negative movement, depending on whether the company beat or missed market expectations. You may wish to hold off buying more of this stock until after its earnings report, unless you think the stock will beat market expectations.

**Finance Explainer:** When a stock goes ex-dividend, the share price [typically drops](https://www.investopedia.com/articles/stocks/07/ex_dividend.asp) by the amount of the dividend paid. If you buy right before the ex-dividend date, you can expect an unrealised capital loss, plus a tax obligation for the dividend. Thus, you may wish to wait for the ex-dividend date before buying more of this stock.
```
future_days=30
```

Job (see [Scheduling](#scheduling)), such as `.jobs add 28 21 * * Sat cal earnings`:
```
cal earnings|ex-dividend
```

Command (earnings):
```
.earnings [period]
```
```
@botname earnings [period]
```

Command (ex-dividend):
```
.dividend [period]
```
```
@botname dividend [period]
```

### Highly shorted stock warnings
![short warnings in Slack](img/shorts.png?raw=true "Short warnings in Slack")

The `shorts` report sends short interest warnings. The data is sourced from Yahoo Finance and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. This can be specified in the `preferences.conf` for a scheduled run, or as an argument when triggered through the chat bot.

**Finance Explainer:** A high short ratio indicates a stock is exposed to high risks, such as potential banktrupcy. It may also incentivise negative news articles which harm the stock price. If the market is wrong, however, risk tolerant investors may receive windfall gains. This report is intended to alert you to an above-average risk, and prompt you to investigate this stock more closely.
```
shorts_percent=15
```

Command:
```
.shorts [percent]
```
```
@botname shorts [percent]
```

### pe / forward pe / peg
![Forward PE report in Slack](img/finbot_fpe.png?raw=true "Forward PE report in Slack")

List securities by P/E ratio, forward P/E ratio, or PEG ratio. A forward P/E is an analysts' estimate, so its lists take only stocks covered by at least `min_analysts` analysts (7 by default; see `preferences.conf`).

Command:
```
.pe [SYMBOL]
.fpe [SYMBOL|bottom|negative]
.peg [SYMBOL|bottom|negative]
```
```
@botname pe [SYMBOL|top|bottom]
@botname fpe [SYMBOL|top|bottom|negative]
@botname peg [SYMBOL|top|bottom|negative]
```

### History
![Price history report in Slack](img/finbot_history.png?raw=true "Price history report in Slack")

Shows the long term performance of a security.
It creates a 5Y chart, and then lists performance for several periods (5Y 3Y 1Y 6M 3M 1M 1W 1D)

Command:
```
.history <symbol>
```
```
@botname history <symbol>
```

### Buy
![Buy ratings in Slack](img/finbot_buy.png?raw=true "Buy ratings in Slack")

Show top recommended buys by Yahoo Finance analysts rating, among stocks rated by at least `min_analysts` analysts (7 by default; see `preferences.conf`)

Command:
```
.buy
```
```
@botname buy
```

### Sell
![Rating report in Slack](img/finbot_sell.png?raw=true "Rating report in Slack")

Show top recommended sells by Yahoo Finance analysts rating, among stocks rated by at least `min_analysts` analysts

Command:
```
.sell
```
```
@botname sell
```

### Marketcap
![Marketcap report in Slack](img/finbot_marketcap.png?raw=true "Marketcap report in Slack")

List the top (or bottom) stocks by market cap, in US dollars: market caps in other currencies are converted at Yahoo's exchange rates. With a symbol, its market cap in its own currency and in US dollars.

Command:
```
.marketcap [top|bottom|SYMBOL]
```
```
@botname marketcap [top|bottom|SYMBOL]
```

### Consensus rating changes
![Rating change report in Slack](img/finbot_rating.png?raw=true "Rating change report in Slack")

Notifies when Yahoo Finance analyst rating consensus changes category (e.g. from hold to buy). Designed to run on a schedule, such as `.jobs add 28 21 * * Sat rating` (see [Scheduling](#scheduling)). Requires persistent storage.

```
rating
```

### Watchlist
![Shared watchlist in Slack](img/watchlist.png?raw=true "Shared watchlist in Slack")

Tracks additional securities which are not in your Sharesight holdings. Each chat has its own watchlist, which anyone in the chat can change: the reports in that chat, asked for or scheduled, include its watchlist's stocks as if they were holdings, and no other chat's. The Sharesight holdings are the same in every chat. `yahoo_warm` keeps every chat's watchlist warm in the cache.

The watchlists are kept in `finbot_watchlist.json` in the data directory, by chat (`{"chats": {"telegram:-1001234": ["2454.TW", "ASO.AX", "STEM"]}}`), so there is no need to edit the file. The first start with watchlists per chat gives each home chat the watchlist kept before, and the same goes for the plans that `.plan` records: each chat's `.plan` lists only the plans recorded in it.

Command:
```
.watchlist
```
```
.watchlist [add|del] [symbol]
```
```
@botname watchlist
```
```
@botname watchlist [add|del] [symbol]
```

## Installation (Linux)
```
sudo $(which apt dnf yum) install git python3-pip
```
```
git clone https://github.com/robdevops/finbot.git ~/finbot
```
```
cd ~/finbot
```
```
pip3 install -r requirements.txt
```
Or, with [uv](https://docs.astral.sh/uv/), which also fetches the exact Python from `.python-version`:
```
uv venv && uv pip install -r requirements.txt
```

## Setup
Configuration is split into two files -- finbot.env for startup environment variables, and preferences.conf for values that can be changed at runtime.

Copy the shipped template:
```
sudo cp ~/finbot/defaults/finbot.env /opt/finbot.env && sudo chmod 600 /opt/finbot.env
```

### `finbot.env`
**Load `finbot.env` with your launcher:**
* **systemd:** `EnvironmentFile=/opt/finbot.env` in `finbot.service`, plus `ExecStartPre=+.../util/check_config.py /opt/finbot.env` for pre-flight lint.
* **Docker:** `--env-file /opt/finbot.env`. Docker keeps quotes literally, so use none. Run `util/check_config.py /opt/finbot.env` first if you want the lint check.
* **init.d / shell:** `util/check_config.py /opt/finbot.env && set -a && . /opt/finbot.env && set +a && ./bot.py` (`set -a` is what exports the values to the bot).
* **Scheduled jobs:** they are started by `bot.py` (see [Scheduling](#scheduling)), so they run on the same settings. For a one-off run, see [Running a report by hand](#scheduling).

The startup keys, read by your launcher. A change needs a restart. Blank means unset. Each network's guide says which
of the chat network keys it needs.

| Key | Default | Description |
|---|---|---|
| `DATA_DIR` | `var/` in the checkout (`$STATE_DIRECTORY` under systemd `StateDirectory=`) | Where state and cache live |
| `ip` | `127.0.0.1` | Address the bot listens on |
| `port` | `5000` | Port the bot listens on |
| `scheduler_catchup` | `5` | Minutes: a run missed while the bot was down still fires if it was due this recently |
| `telegramChatID` | | Telegram's home chat, a group or channel id: finbot's first start gives it the default jobs, and error reports go there (see [Scheduling](#scheduling)) |
| `sharesight_code` | | Sharesight API access |
| `sharesight_client_id` | | Sharesight API access |
| `sharesight_client_secret` | | Sharesight API access |
| `telegramBotToken` | | Telegram bot token: reports, and commands (finbot fetches its updates unless `telegramOutgoingWebhook` is set) |
| `slackBotToken` | | Slack bot token, for replies and chart uploads in Slack |
| `slackAppToken` | | Slack app-level token (`xapp-`): commands over a socket finbot opens to Slack (Socket Mode), when `slackOutgoingWebhook` is empty |
| `slackChannelID` | | Slack's home channel id, as `telegramChatID` (with `slackBotToken`) |
| `telegramOutgoingWebhook` | | The URL Telegram posts its updates to (HTTP mode); empty, finbot fetches them (pull mode) |
| `telegramOutgoingToken` | | Secret token Telegram must present (HTTP mode) |
| `slackOutgoingWebhook` | | The URL Slack posts its events and button presses to (HTTP mode); empty, Socket Mode with `slackAppToken` |
| `slackOutgoingToken` | | Token Slack must present (HTTP mode): the older way, which Slack has deprecated; not needed with `slackSigningSecret` |
| `slackSigningSecret` | | Secret Slack signs each request with (HTTP mode) |
| `discordBotToken` | | Discord bot token: replies, and commands over the gateway unless `discordOutgoingWebhook` is set |
| `discordChannelID` | | Discord's home channel id, as `telegramChatID` (with `discordBotToken`) |
| `discordOutgoingWebhook` | | The Interactions Endpoint URL Discord posts slash commands and button presses to (HTTP mode); empty, the gateway (pull mode) |
| `discordPublicKey` | | The app's public key, which checks the signature of each interaction (HTTP mode) |

### `preferences.conf` items

Copies preferences.conf and metadata files into the data directory (never overwrites)
```
util/sync_defaults.py [--dest DIR] --apply
```

The preferences, read by the bot itself. A change takes effect on a reload. A true/false preference takes `true`/`false`, `yes`/`no`, `on`/`off` or `1`/`0`; anything else is a mistake, reported like any other. A blank value means the default.

| Key | Default | Description |
|---|---|---|
| `past_days` | `28` | How many days back reports look |
| `future_days` | `30` | How many days ahead the events calendar looks |
| `price_percent` | `5` | Price alert threshold, percent |
| `shorts_percent` | `15` | Short interest alert threshold, percent |
| `min_analysts` | `7` | `.buy`, `.sell` and `.forward pe` list only stocks covered by at least this many analysts; with fewer, a consensus says little (thinly covered small caps are nearly all a perfect buy) |
| `demote_volatile` | `True` | Volatile (small cap, high beta) stocks need a bigger move to alert |
| `demote_leveraged` | `True` | Leveraged (2x, 3x) funds need a bigger move to alert |
| `volatility_multiplier` | `2` | How much bigger a move volatile stocks need |
| `exclude_portfolios` | | Sharesight portfolio IDs to leave out, space separated |
| `include_portfolios` | | Sharesight portfolio IDs to report on, space separated (empty: all that are not excluded) |
| `trades_use_yahoo` | `True` | Use Yahoo for trades; set `False` if Yahoo breaks |
| `graph` | `True` | Send charts with reports |
| `hyperlink` | `True` | Hyperlink tickers in reports |
| `hyperlinkFooter` | `True` | Add a website link footer to stock lookups |
| `hyperlinkProvider` | `google` | Where ticker links go: `google` or `yahoo` |
| `exchange_suffix` | `AX` | Regional: Yahoo's suffix for your exchange (`AX` for the ASX, `NZ`, `L`, `TO` and so on). A bare symbol Yahoo does not know is tried again with it, in every command that takes a symbol (`BHP` becomes `BHP.AX`); empty, a symbol is taken as written |
| `country_code` | `AU` | Regional: your country, for the reminder report |
| `timezone` | `Australia/Melbourne` | Regional: your time zone, for the reminder report, and for each job's next run in `.jobs` (besides UTC) |
| `cache` | `True` | Cache Yahoo and Sharesight responses |
| `cache_seconds` | `43200` | Cache lifetime in seconds (12 hours) |
| `performance_cache_seconds` | `2400` | Cache lifetime of Sharesight performance reports in seconds: longer than the 30 minutes between `sharesight_warm` runs, so the holdings never run out |
| `http_timeout` | `18` | Seconds to wait on outbound HTTP requests |
| `debug` | `False` | Extra diagnostics in the log |
| `print_headers` | `False` | Log inbound request headers |

A key in the wrong file, or one that is not listed, stops finbot starting; on a reload it is reported and nothing is applied. A key finbot no longer reads (`alliterate`, `chunk_maxlines`) is ignored, and the log at start says to delete it.

edit `preferences.conf`, then reload if running. The service log shows what changed (`config: future_days 30 -> 45`). If the file has a mistake, the reload reports it (`ERROR config: ...`), applies nothing and leaves finbot running on its previous settings. Check an edit before reloading with `util/check_config.py /opt/finbot.env`. Edit `finbot.env`, then restart: a running bot cannot see it change.

**Upgrading from one `.env`?** finbot no longer reads it, and refuses to start while a `.env` is in the checkout, so its settings cannot be silently ignored. Run `util/split_env.py` (or `util/split_env.py /path/to/old.env` for one elsewhere). It reads either format, the old dotenv one (`key = 'value' # comment`) or plain `KEY=value`, writes `finbot.env.new` and `preferences.conf.new` next to the old file, never overwriting, and lists any key it dropped or did not recognise. Put `finbot.env` where your launcher loads it and `preferences.conf` in the data directory, then delete the old file.

### Data directory
All state and cache lives under `var/` in the checkout by default. Set `DATA_DIR` to relocate it (cache moves to `$DATA_DIR/cache`), e.g. for a Docker bind mount that survives rebuilds:
```
docker run -v /srv/finbot:/data -e DATA_DIR=/data --env-file /opt/finbot.env ...
```
Reference data (`finbot_adr.json`, `finbot_sws_*.json`, `reminder.json`) ships in `defaults/`. A file of the same name in the data directory takes precedence. Defaults are never copied or overwritten automatically; to see or pull in updates run:
```
util/sync_defaults.py          # dry run
util/sync_defaults.py --apply  # copy missing files (including a starter preferences.conf)
util/sync_defaults.py --force  # also replace changed files, keeping .bak copies
util/sync_defaults.py --dest /srv/finbot --apply  # target another directory instead of the data directory
```
`reminder.json` holds the reminders that the `reminder` report posts on their day. Each entry has a `month_day` (`06-30`) and a `message`, which is one line or a list of lines, and may name a `year` (`2026`) and a `gate_country` (posted only when `country_code` in `preferences.conf` matches; `{flag}` in its message becomes that country's flag). A message is text, with two kinds of markup that each network gets in its own form: `[text](https://example.com)` is a link, and a line wrapped in underscores, `_like this_`, is in italics. The Australian end of financial year checklist (23 June) is such an entry: if you keep your own `reminder.json` in the data directory, `util/sync_defaults.py` shows what it lacks.

With systemd `DynamicUser=yes` and `StateDirectory=finbot`, `DATA_DIR` defaults to systemd's `$STATE_DIRECTORY` (`/var/lib/finbot`), so no setting is needed; move existing data once with `cp -a /opt/finbot/var/. /var/lib/finbot/`. An explicit `DATA_DIR` always wins.

In Docker, one container is enough: `bot.py` runs the schedule too, so there is no cron or scheduler sidecar to set up.

### Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to `finbot.env`. Example:
```
sharesight_code=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_id=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_secret=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
```

### Chat networks setup
Follow the guide for each network you use: [Telegram](doc/telegram.md), [Slack](doc/slack.md) or
[Discord](doc/discord.md). It covers the bot, its `finbot.env` keys, and for HTTP mode the HTTPS server in front of
finbot.

### Portfolios
Portfolios are auto-discovered, including other people's portfolios which are shared to you. To exclude specific portfolios, add their IDs to `exclude_portfolios` in the `preferences.conf`:
```
exclude_portfolios=100003 100004
```

Alternatively, you can include only specific portfolios:
```
include_portfolios=100001 100002
```

### Caching
Many objects are cached for 12 hours by default (`cache_seconds`). Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache=True
cache_seconds=43200
performance_cache_seconds=2400
```

`performance_cache_seconds` (default 40 minutes) is the cache lifetime of Sharesight performance reports.

Charts are cached by what they show (with `cache=True`): the same chart, for another chat, a later run or a period button, is drawn once, and a chart of new figures is a new chart, so a cached one is never stale. The weekly system job `cleanup` removes cache files after 30 days.

To flush the cache, so that everything is fetched afresh, signal the running bot: it deletes its cache files (Yahoo and Sharesight
answers, charts, the Yahoo cookie) and keeps its state (watchlist, jobs, seen trades, ratings), then runs both warm jobs
(`sharesight_warm`, `yahoo_warm`) straight away to fill the cache again. There is no `systemctl flush`, since systemctl takes no custom verbs; any of these does it:
```
sudo systemctl kill -s USR1 finbot          # systemd
sudo systemctl start finbot-flush           # the same, once finbot-flush.service is installed (see below)
docker kill -s USR1 <container>             # Docker
kill -USR1 <pid of bot.py>                  # anything else
```
The log says `cache: flushed N files`, then `cache: warm jobs done` once the cache is full again. To install the `finbot-flush` shortcut: `sudo cp -v finbot-flush.service /etc/systemd/system/ &&
sudo systemctl daemon-reload`. `finbot.service` itself needs no change. With the bot stopped, deleting the files in `DATA_DIR/cache` does the same.

Two system jobs keep the caches full, each on a fixed interval shorter than the cache lifetime, so that chat requests do not wait on Sharesight or Yahoo (see [Scheduling](#scheduling)): `sharesight_warm` fetches the Sharesight portfolio list and each portfolio's holdings report afresh every 30 minutes (`performance_cache_seconds`: 40 minutes), and `yahoo_warm` the price history of every stock followed every 8 hours (`cache_seconds`: 12 hours). Neither fetches anything with `cache=False`, and `sharesight_warm` nothing without Sharesight configured. A refresh that fails is logged, the previous cache keeps being served while fresh, and the next run tries again. A flush runs both at once (see above).

### Hyperlinks
These `preferences.conf` options relate to hyperlinks:

* `hyperlink`, if set to `False`, disables all hyperlinks. Note: it can not disable syntax highlighting and false positives by chat clients that try to detect domains. Defaults to `True`.
```
hyperlink=True
```

* `hyperlinkFooter` appends hyperlinks to the company website and to a Google search for the ticker on simplywall.st  for the symbol lookup report. Possible values are `True` or `False`. Defaults to `True`.

```
hyperlinkFooter=True
```

* `hyperlinkProvider` configures where to send ticker hyperlinks. Available values are `google` and `yahoo`. If set to `google`, it is only used where practical, as Google does not publish earnings date, ex-dividend date, premarket price, or short interest figures. Defaults to `google`.
```
hyperlinkProvider=google
```
```
hyperlinkProvider=yahoo
```

## Scheduling
Each chat has its own jobs: reports that run on a schedule and post to that chat. Anyone in the chat manages them there,
with `.jobs` (also `.job`, `.cron`, `.crons` or `.schedule`):
```
.jobs                      this chat's jobs, numbered, each with its next run; then the system jobs
.jobs add                  the reports a job can run, and what each takes
.jobs add 29 21 * * Mon-Fri price interday
.jobs run                  the list, with a button per job that runs it now; .jobs run 2 runs job 2
.jobs toggle               the list, with a button per job that switches it on or off; .jobs toggle 2
.jobs del 2                deletes job 2
```

A job is a time in crontab's syntax, then one or more reports with their arguments:
* **The time** is five fields (minute, hour, day of month, month, day of week; `*/20`, `Mon-Fri`, ranges and lists
  work) or an `@macro` such as `@daily`. A time that cannot be or never comes (minute 61, 30 February) is refused,
  saying why.
* **Times are in UTC**, which keeps the ASX's jobs and NYSE's each within an hour of their local times all year. To
  follow one market's clocks exactly, a job names its zone first, as crontab writes it:
  `.jobs add CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession`. `.jobs` shows each next run in UTC and in
  the `timezone` preference.
* **The reports** are `trades`, `price midsession|interday|premarket|close|DAYS`, `cal earnings|ex-dividend`,
  `performance [DAYS]`, `rating`, `milestone`, `shorts`, `reminder` and `podcasts FEED_URL`. Several, separated by `;`,
  run one after another: `.jobs add 28 21 * * Sat cal earnings; cal ex-dividend; price 7; performance 7; rating`.
  Quote an argument that holds spaces or a `;` (a feed URL, say).
* A chat has 30 jobs at most.

A job posts to its own chat, whichever way that chat's updates reach finbot: the jobs are kept by network and chat id
(`finbot_schedule.json` in the data directory), so switching a network between pull and HTTP mode keeps them. Each chat
also keeps its own record of what a report has told it (trades, rating changes, record highs, podcast episodes), so the
same report scheduled in two chats tells each of them once. A run from `.jobs run` is a scheduled run: it posts to the
chat and updates the same record. A change counts at once, with no reload.

**The system jobs**, fixed in `lib/jobs.py` and listed by `.jobs` under _System_, keep the cache full and tidy:
`sharesight_warm` every 30 minutes, `yahoo_warm` every 8 hours (see [Caching](#caching)), and `cleanup 30` weekly,
which deletes cache files older than 30 days. A chat cannot add, switch or run them.

**From `schedule.cron`**, where the schedule used to be: the first time finbot starts without `finbot_schedule.json`,
it gives each home chat (`telegramChatID`, `slackChannelID`, `discordChannelID`) the jobs of the data directory's
`schedule.cron`, else of the shipped `defaults/schedule.cron`, each in the zone it ran in (the server's), without the
system jobs. It copies the reports' records to each home chat too, so that nothing old is told again. It logs what it
did, and any line it left out, and reads the file no more: delete the data directory's copy afterwards.

Behaviour worth knowing:
* The reports run in `bot.py` itself, each in a thread of its own, sharing the bot's user, sandbox, environment, data
  directory, caches and connections; charts are drawn one at a time, and a slow report holds up no chat command. There
  is no cron to set up: remove any old crontab entries that ran finbot's scripts, or their reports come twice.
* A run that was due while the bot was down (a restart, a deploy) still fires once if it was due within the last
  `scheduler_catchup` minutes (default 5). A restart right after a run does not repeat it. A job that is switched off
  does not fire, and does not catch up once it is switched on again.
* A job still running when it is next due is skipped. A command still running after 5 minutes is reported once, and
  left to finish (a thread cannot be stopped, but every request it makes has a timeout); until it does, it is not
  started again. Each command of a job has 5 minutes of its own.
* A failure is reported to the job's chat. The bot logs each job as it runs (`journalctl -u finbot`).

## Daemonize (systemd)
`finbot.service` can take care of keeping `bot.py` running in the background and starting it on boot. Copy `finbot.service` to `/etc/systemd/system/`, edit it to set the `User`, `ExecStart` and the path of [`finbot.env`](#setup) (`EnvironmentFile=`, and the `ExecStartPre=` check), then enable and start it. `systemctl reload finbot` re-reads `preferences.conf` without a restart; a change to `finbot.env` needs `systemctl restart finbot`:

```
sudo cp -v finbot.service /etc/systemd/system/
```
```
sudo sed -i 's/CHANGEME/YOUR LINUX USERNAME/' /etc/systemd/system/finbot.service
```
```
sudo systemctl daemon-reload
```
```
sudo systemctl enable finbot --now
```
You can now monitor the bot's stderr with :
```
journalctl -fu finbot
```

## Suggestions
* Is my code is doing something the hard way?
* Something important is missing from this README?

Log an [issue](https://github.com/robdevops/finbot/issues)!
