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
* Interactive chat commands (Slack & Telegram):
  * All the above reports
  * Price history graph
  * Stock lookup with price/valuation related stats and warnings
  * Company profiles
  * Shared watch list
  * List stocks (holdings + watchlist) by P/E, Forward P/E, PEG, market cap, or Yahoo analyst consensus

### Chat networks
What finbot can do on each network. Telegram takes everything; the others take what their APIs allow.

| Feature | Telegram | Slack | Discord |
|---|---|---|---|
| Chat commands | ✓ | ✓ | ✗ (a webhook only posts) |
| "typing…" while a command works | ✓ | ✗ (Slack has no typing notice for bots) | ✗ |
| Charts in replies | ✓ | ✓ with `slackBotToken` | n/a |
| Charts in scheduled reports | ✓ | ✗ (the incoming webhook takes text only) | ✓ |
| Period and job buttons | ✓ | ✗ | ✗ |
| No link previews | ✓ | ✓ | ✓ |
| Linked tickers | ✓ | ✓ | ✓ |
| Charts updated in place by their buttons | ✓ | ✗ | ✗ |

**Setting up a network:** [Telegram](doc/telegram.md) · [Slack](doc/slack.md) · [Discord](doc/discord.md). Each guide
covers the whole setup of that network, and where there is a choice between reports only and the interactive bot, it
compares the two before the steps.

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

### Requirements
* Most features require a Sharesight paid plan, preferably with automatic trade imports, and an API key
* A Telegram bot, a Slack app or a Discord webhook (see the network's guide, above)
* Interactive commands require a public web server with domain name and matching certificate to proxy chat commands to the bot (see the [Telegram](doc/telegram.md#interactive-bot) and [Slack](doc/slack.md#interactive-bot) guides).
* Python 3.13.5 (the version in `.python-version`; 3.12 is the minimum)
* Python modules, pinned to versions with 3.13 support in `requirements.txt`:
```
croniter python-dateutil requests gevent pandas matplotlib numpy
```

### Supported commands

Where:
* _percent_ is a number, optionally followed by '%'
* _period_ is a number followed by 'd', 'w', 'm' or 'y', or 'ytd'
* _portfolio_ is a Sharesight portfolio name
* _symbol_ is a Yahoo Finance symbol
```
.symbol
.beta
.buy
.sell
.compare symbol symbol [symbol...] [period|max]
.dividend [period|symbol]
.earnings [period|symbol]
.forward pe [symbol|top|bottom|negative]
.history symbol
.holdings portfolio
.jobs [run number|command]
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

`!` or `/` work in place of the dot, and so does the bot's name: `@botname price 7d`, `@botname AAPL`. `.help` lists the commands in chat.

Trade notifications are peformed by polling the Sharesight trades API on a schedule (see [Scheduling](#scheduling)), and notifying your configured chat networks of any new trades. Thus, it works best if your trades are auto-imported into Sharesight through its broker integrations, and if your environment has persistent storage so that the bot can keep track of known trade IDs between runs.

The other various reports can also run on a schedule (e.g. daily or weekly), or on demand through the interactive bot. They query the Yahoo Finance API for stock data based on current holdings across your Sharesight portfolios, your friends' Sharesight portfolios, plus a custom watch list. Depending on how they're triggered, they will either report to all configured chat networks, or reply to the chat which triggered them.

The interactive bot component requires you to host a web service on a domain with a trusted certificate. It subscribes to push updates from native Slack apps / Telegram bots, and reacts to certain regex seen in chat. It provides:
* Stock lookup (financials, company profile, price charts)
* Group maintainable watch list, picked up by the various reports
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

This report can only be run through the interactive bot. Example usage:
```
.AAPL
```
```
@botname AAPL
```

### Trades
![trade update in Slack](img/trades.png?raw=true "Trade update in Slack")

`trades.py` sends recent Sharesight trades to your configured chat services.
By default, this report searches Sharesight for trades from the past 28 days (`past_days`). You can override this in `preferences.conf`, or by providing a number as argument when triggered through the chat bot.

Without persistent storage, set `past_days=0` to avoid duplicate trade notifications. In this case, the schedule must run the report exactly once per day, after market close.

With persistent storage, the default of `past_days=28` suits. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to schedule it every 20 minutes.

```
past_days=28
```

Cron trigger:
```
trades.py
```

Interactive trigger:
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

`price.py` sends premarket, midsession, and interday price movements if any holdings moved over a percentage threshold. This data is sourced from Yahoo! Finance and Sharesight. The default threshold is 5% but you can change it by setting `price_percent` in the `preferences.conf`, or by providing a number as argument when triggered through the chat bot. Decimal fractions are accepted.

If `demote_volatile` is `true`, stocks with a [market cap](https://www.investopedia.com/terms/m/marketcapitalization.asp) under US$150M, or a [beta](https://www.investopedia.com/terms/b/beta.asp) of > 1.5 and a market cap of under US$1B will have their alert threshold (`price_percent`) doubled. A market cap in another currency is converted at Yahoo's exchange rate.

Config example:
```
price_percent=5
demote_volatile=True
```

Cron trigger:
```
./price.py [premarket|midsession|interday|close|days (int)]
```
When scheduled (Cron), the mode must be passed as an execution argument:
* If `premarket` is passed, it only reports on pre/post market price movements.
* If `midsession` is passed, it only reports for markets currently in session. This is intended to run from Cron to provide mid-session alerts for big price movements of your holdings. For example, it could be run twice per day 12 hours apart, to capture markets in different timezones.
* If `interday` is passed, it reports current price against the previous market close.
* If `close` is passed, it reports daily change in stocks whose market closed in the past 3 hours.
* If an integer [i] is passed, it reports current price against [i] days ago.

Interactive trigger (pre-market):
```
.premarket [percent]
```
```
@botname premarket [percent]
```

Interactive trigger (mid-session):
```
.session [percent]
```
```
@botname session [percent]
```

Interactive trigger (interday).
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

`performance.py` reports on Sharesight portfolio performance over a given period. The default is set by `past_days` in the `preferences.conf`, which can be overridden at runtime by specifying an integer as the argument.

Config example:
```
past_days=28
```

Cron trigger:
```
./performance.py 7
```

Interactive trigger:
```
.performance [period]
```
```
@botname performance [period]
```

Interactively, you can also specify a portfolio:
```
.performance [period] [[portfolio]
```
```
@botname performance [period] [portfolio]
```

### Events calendar
![earnings message in Slack](img/earnings.png?raw=true "Earnings message in Slack")

`cal.py` sends upcoming earnings and ex-dividend date alerts. The data is sourced from Yahoo! Finance. It reports on events up to `future_days` into the future. This is set in the `preferences.conf` for triggering the report from Cron, or can be specified as an argument when triggered through the chat bot.

**Finance Explainer:** When a company releases its quarterly earnings report, the stock price may undergo a signficant positive or negative movement, depending on whether the company beat or missed market expectations. You may wish to hold off buying more of this stock until after its earnings report, unless you think the stock will beat market expectations.

**Finance Explainer:** When a stock goes ex-dividend, the share price [typically drops](https://www.investopedia.com/articles/stocks/07/ex_dividend.asp) by the amount of the dividend paid. If you buy right before the ex-dividend date, you can expect an unrealised capital loss, plus a tax obligation for the dividend. Thus, you may wish to wait for the ex-dividend date before buying more of this stock.
```
future_days=30
```

Cron execution:
```
./cal.py [earnings|ex-dividend]
```

Interactive trigger (earnings):
```
.earnings [period]
```
```
@botname earnings [period]
```

Interactive trigger (ex-dividend):
```
.dividend [period]
```
```
@botname dividend [period]
```

### Highly shorted stock warnings
![short warnings in Slack](img/shorts.png?raw=true "Short warnings in Slack")

`shorts.py` sends short interest warnings. The data is sourced from Yahoo Finance and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. This can be specified in the `preferences.conf` for running the report from Cron, or as an argument when triggered through the chat bot.

**Finance Explainer:** A high short ratio indicates a stock is exposed to high risks, such as potential banktrupcy. It may also incentivise negative news articles which harm the stock price. If the market is wrong, however, risk tolerant investors may receive windfall gains. This report is intended to alert you to an above-average risk, and prompt you to investigate this stock more closely.
```
shorts_percent=15
```

Interactive trigger:
```
.shorts [percent]
```
```
@botname shorts [percent]
```

### pe / forward pe / peg
![Forward PE report in Slack](img/finbot_fpe.png?raw=true "Forward PE report in Slack")

List securities by P/E ratio, forward P/E ratio, or PEG ratio. A forward P/E is an analysts' estimate, so its lists take only stocks covered by at least `min_analysts` analysts (7 by default; see `preferences.conf`).

Interactive trigger:
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

Interactive trigger:
```
.history <symbol>
```
```
@botname history <symbol>
```

### Buy
![Buy ratings in Slack](img/finbot_buy.png?raw=true "Buy ratings in Slack")

Show top recommended buys by Yahoo Finance analysts rating, among stocks rated by at least `min_analysts` analysts (7 by default; see `preferences.conf`)

Interactive trigger:
```
.buy
```
```
@botname buy
```

### Sell
![Rating report in Slack](img/finbot_sell.png?raw=true "Rating report in Slack")

Show top recommended sells by Yahoo Finance analysts rating, among stocks rated by at least `min_analysts` analysts

Interactive trigger:
```
.sell
```
```
@botname sell
```

### Marketcap
![Marketcap report in Slack](img/finbot_marketcap.png?raw=true "Marketcap report in Slack")

List the top (or bottom) stocks by market cap, in US dollars: market caps in other currencies are converted at Yahoo's exchange rates. With a symbol, its market cap in its own currency and in US dollars.

Interactive trigger:
```
.marketcap [top|bottom|SYMBOL]
```
```
@botname marketcap [top|bottom|SYMBOL]
```

### Consensus rating changes
![Rating change report in Slack](img/finbot_rating.png?raw=true "Rating change report in Slack")

Notifies when Yahoo Finance analyst rating consensus changes category (e.g. from hold to buy). Designed to run from Cron. Requires persistent storage.

```
./rating.py
```

### Watchlist
![Shared watchlist in Slack](img/watchlist.png?raw=true "Shared watchlist in Slack")

Tracks additional securities which are not in your Sharesight holdings. The various reports will include wishlist items as if they are holdings.

It is stored in `var/finbot_watchlist.json` by default. It is a JSON array literal containing Yahoo symbols. Example:
```
["2454.TW", "3217.TWO", "ASO.AX", "STEM"]
```

When the bot is run interactively, the watchlist is dynamic and can be edited by members of a chat group. In this case, there is no need to create/edit the file manually.

Interactive trigger:
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
| `scheduler` | `True` | Run the scheduled reports (`schedule.cron`) inside the bot |
| `scheduler_catchup` | `5` | Minutes: a run missed while the bot was down still fires if it was due this recently |
| `telegramChatID` | | Chat group or channel id that scheduled reports go to on Telegram |
| `sharesight_code` | | Sharesight API access |
| `sharesight_client_id` | | Sharesight API access |
| `sharesight_client_secret` | | Sharesight API access |
| `slack_webhook` | | Slack incoming webhook, for outbound reports |
| `discord_webhook` | | Discord webhook, for outbound reports |
| `telegramBotToken` | | Telegram bot token, for outbound reports |
| `slackBotToken` | | Slack bot token, for replies and chart uploads in Slack |
| `telegramOutgoingWebhook` | | Telegram webhook path the bot accepts (interactive mode) |
| `telegramOutgoingToken` | | Secret token Telegram must present (interactive mode) |
| `slackOutgoingWebhook` | | Slack webhook path the bot accepts (interactive mode) |
| `slackOutgoingToken` | | Token Slack must present (interactive mode): the older way, which Slack has deprecated; not needed with `slackSigningSecret` |
| `slackSigningSecret` | | Secret Slack signs each request with (interactive mode) |

### `preferences.conf` items

Copies preferences.conf and metadata files into the data directory (never overwrites)
```
util/sync_defaults.py [-d DEST] --apply
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
| `performance_use_sharesight` | `False` | Use Sharesight rather than Yahoo for performance over a period |
| `alliterate` | `False` | Greeting uses alliterating adjectives (easter egg) |
| `graph` | `True` | Send charts with reports |
| `hyperlink` | `True` | Hyperlink tickers in reports |
| `hyperlinkFooter` | `True` | Add a website link footer to stock lookups |
| `hyperlinkProvider` | `google` | Where ticker links go: `google` or `yahoo` |
| `chunk_maxlines` | `20` | Maximum lines per message before a report is split |
| `country_code` | `AU` | Country, used by the reminder report |
| `timezone` | `Australia/Melbourne` | Time zone, used by the reminder report |
| `cache` | `True` | Cache Yahoo and Sharesight responses |
| `cache_seconds` | `43200` | Cache lifetime in seconds (12 hours) |
| `performance_cache_seconds` | `1800` | Cache lifetime of Sharesight performance reports in seconds |
| `http_timeout` | `18` | Seconds to wait on outbound HTTP requests |
| `debug` | `False` | Extra diagnostics in the log |
| `print_headers` | `False` | Log inbound request headers |

A key in the wrong file, or one that is not listed, stops finbot starting; on a reload it is reported and nothing is applied.

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
[Discord](doc/discord.md). It covers the bot or webhook, its `finbot.env` keys, and for chat commands the HTTPS server in
front of finbot.

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
performance_cache_seconds=1800
```

`performance_cache_seconds` (default 30 minutes) is the cache lifetime of Sharesight performance reports.

To flush the cache, so that everything is fetched afresh, signal the running bot: it deletes its cache files (Yahoo and Sharesight
answers, charts, the Yahoo cookie) and keeps its state (watchlist, seen trades, ratings, schedule), then refills the Sharesight caches
at once. There is no `systemctl flush`, since systemctl takes no custom verbs; any of these does it:
```
sudo systemctl kill -s USR1 finbot          # systemd
sudo systemctl start finbot-flush           # the same, once finbot-flush.service is installed (see below)
docker kill -s USR1 <container>             # Docker
kill -USR1 <pid of bot.py>                  # anything else
```
The log says `cache: flushed N files`. To install the `finbot-flush` shortcut: `sudo cp -v finbot-flush.service /etc/systemd/system/ &&
sudo systemctl daemon-reload`. `finbot.service` itself needs no change. With the bot stopped, `cleanup.py 0` deletes the same files.

While `bot.py` is running with Sharesight configured and `cache=True` (a reload that switches `cache` pauses or resumes it), a background job keeps the Sharesight portfolio list (`cache_seconds`) and each portfolio's holdings report (1 day, `performance_cache_seconds` cache) refreshed at 90% of their cache lifetime, so chat requests do not wait on Sharesight. If a refresh fails, the previous cache keeps being served and the job retries after 5 minutes.

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
The scheduled reports are started by `bot.py`, each run in its own child process (`python -m lib.jobrun`), so they use the same user, sandbox, environment and data directory as the bot, while heavy work (charts, large reports) cannot hold up incoming chat webhooks. A run that exceeds 5 minutes is stopped. There is no cron to set up, which matters under systemd `DynamicUser=` where only the bot's own user can read the state directory. **This is on by default.** Remove the equivalent entries from any old crontab before the first start, otherwise every job runs twice; or set `scheduler=False` in the environment file to keep using cron.

The schedulable scripts are `trades.py`, `price.py`, `reminder.py`, `cal.py`, `shorts.py`, `performance.py`, `rating.py`, `milestone.py`, `podcasts.py "<feed url>"` and `cleanup.py [days]` (deletes cache files older than `days`, default 30). Other jobs, such as a DNS updater or backups, stay in cron or systemd timers.

The schedule is `defaults/schedule.cron`, written in **cron-compatible syntax**: five time fields (minute, hour, day of month, month, day of week; `*/20`, `Mon-Fri`, ranges and lists work) or an `@macro` such as `@daily`, then a finbot script and its arguments. Quote an argument that has spaces or special characters (a feed URL with `&`, say). Several commands separated by `;` run one after another. `MAILTO=`, `SHELL=`, `PATH=` and `HOME=` lines are ignored. Anything else a crontab allows (a user column, pipes, other programs) is not supported: such a line is reported at startup and skipped. A time that cannot be or never comes (minute 61, 30 February) is different: finbot refuses to start with it, and a reload with it is refused, leaving the running schedule as it was. Existing crontab lines can be pasted as they are: `> /dev/null` redirects, `{ a; b ;}` groups and a path before the script name are understood.
```
# Every 20 minutes on weekdays
*/20 * * * Mon-Fri trades.py

# Weekly, one after the other
28  21 * * Sat cal.py earnings; cal.py ex-dividend; price.py 7; performance.py 7; rating.py

# New episodes, hourly
01 0-10,23 * * Mon-Fri podcasts.py "https://example.com/podcast.rss"
```
The default times suit a server set to UTC. Like cron, they follow the server's own time zone; put `CRON_TZ=Australia/Melbourne` on a line of its own above a job to pin another zone.

**To change a job**, copy the schedule to the data directory, edit the copy, and reload (no restart, so the bot stays up):
```
util/sync_defaults.py --apply       # copies schedule.cron to the data directory if it is not there yet
sudoedit /var/lib/finbot/schedule.cron
sudo systemctl reload finbot        # the bot re-reads the file and logs how many jobs it loaded
```
The bot logs the number of jobs when it starts or reloads, and each job as it runs (`journalctl -u finbot`); a line it cannot use is reported by name. If the edited file has no usable line the previous schedule keeps running.

**To run a job from chat**, send `.jobs` (also `.cron`, `.crons` or `.schedule`): it lists the scheduled commands, each once and without times, comments or `.py` (`cleanup` and `podcasts` are scheduled but not listed), and on Telegram adds a button per command. `.jobs run 2` (or tapping the button) runs that command now, and `.jobs run price.py close` runs it by name; anything not in the schedule is refused, and so is a chain such as `a; b` (run them one at a time). A manual run is exactly a cron run: it reports to all configured chat networks, updates the same state (seen trades, ratings and so on), and does not change the schedule. Anyone who can message the bot can do this; a command that is already running is not started twice.

Behaviour worth knowing:
* A run that was due while the bot was down (a restart, a deploy) still fires once if it was due within the last `scheduler_catchup` minutes (default 5). A restart right after a run does not repeat it.
* A job still running when it is next due is skipped, and a job that takes more than 5 minutes is abandoned and reported.
* Failures are reported to your chat channels, as before.
* With `scheduler=False` nothing is scheduled by the bot, so you can keep using cron or systemd timers and run the scripts yourself.

**Running a report by hand.** Under `DynamicUser=yes` you cannot simply log in as the bot's user, so run the script as a transient unit with a dynamic user and the same state directory:
```
sudo systemd-run --pty --wait --collect -p DynamicUser=yes -p StateDirectory=finbot -p EnvironmentFile=/opt/finbot.env /opt/finbot/price.py 7
```
The script prints its output on your terminal and sends its report to your chat channels as usual. The transient unit gets its own dynamic user, and systemd may re-own the state directory to it for the run: check `ls -ln /var/lib/private/finbot` afterwards and `systemctl restart finbot` if the bot can no longer write there. The chat commands (`.price 7d`, `.performance 7d`, ...) run the same reports inside the bot, without any of this. Outside systemd, run a script from the checkout as your own user with the settings loaded into the shell: `set -a; . /opt/finbot.env; set +a; ./price.py 7` (this works while no value in the file contains spaces).

## Daemonize (systemd)
`finbot.service` can take care of keeping `bot.py` running in the background and starting it on boot. Copy `finbot.service` to `/etc/systemd/system/`, edit it to set the `User`, `ExecStart` and the path of [`finbot.env`](#setup) (`EnvironmentFile=`, and the `ExecStartPre=` check), then enable and start it. `systemctl reload finbot` re-reads `preferences.conf` and the [schedule](#scheduling) without a restart; a change to `finbot.env` needs `systemctl restart finbot`:

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
