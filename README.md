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

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

### Requirements
* Most features require a Sharesight paid plan, preferably with automatic trade imports, and an API key
* Discord/Slack webhooks / Telegram bot user
* Interactive commands require a public web server with domain name and matching certificate to proxy chat commands to the bot.
* Python 3.13.5 (the version in `.python-version`; 3.12 is the minimum)
* Python modules, pinned to versions with 3.13 support in `requirements.txt`:
```
croniter python-dateutil requests gevent pandas matplotlib numpy
```

### Supported commands

Where:
* _percent_ is a number followed by '%'
* _period_ is a number followed by 'd' 'w' 'm' or 'y'
* _portfolio_ is a Sharesight portfolio name
* _symbol_ is a Yahoo Finance symbol
```
.symbol
.dividend [period|symbol]
.earnings [period|symbol]
.history symbol
.holdings portfolio
.jobs [run number|command]
.marketcap [symbol|top|bottom]
.performance [period] [portfolio]
.pie portfolio [sector]
.premarket [percent|symbol]
.price [percent|symbol] [period]
.rating [strong buy|buy|hold|underperform|sell]
.session [percent|symbol]
.shorts [percent|symbol]
.trades [period] [portfolio]
.value [pe|forward pe|peg|bottom pe|bottom forward pe|bottom peg|negative forward pe|negative peg]
.watchlist [add|del symbol]
.who symbol
```

Alternative syntax:

```
@botname <symbol>
@botname dividend [period|symbol]
@botname earnings [period|symbol]
@botname history symbol
@botname holdings [portfolio]
@botname jobs [run number|command]
@botname marketcap [symbol|top|bottom]
@botname performance [period] [portfolio]
@botname pie portfolio [sector]
@botname premarket [percent|symbol]
@botname price [percent|symbol] [period]
@botname rating [buy|hold|underperform|sell]
@botname session [percent|symbol]
@botname shorts [percent|symbol]
@botname trades [period] [portfolio]
@botname value [pe|forward pe|peg]
@botname watchlist [add|del symbol]
@botname who symbol
```

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
By default, this report searches Sharesight for trades from the current day only. You can override this with `past_days` in the `preferences.conf`, or by providing a number as argument when triggered through the chat bot.

Without persistent storage, it is recommended to leave `past_days=0` to avoid duplicate trade notifications. In this case, the schedule must run the report exactly once per day, after market close.

With persistent storage, it is recommended to set `past_days=30`. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to schedule it every 20 minutes.

```
past_days=30
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

`prices.py` sends premarket, midsession, and interday price movements if any holdings moved over a percentage threshold. This data is sourced from Yahoo! Finance and Sharesight. The default threshold is 10% but you can change it by setting `price_percent` in the `preferences.conf`, or by providing a number as argument when triggered through the chat bot. Decimal fractions are accepted.

If `demote_volatile` is `true`, stocks with a [market cap](https://www.investopedia.com/terms/m/marketcapitalization.asp) under 150M, or a [beta](https://www.investopedia.com/terms/b/beta.asp) of > 1.5 and a market cap of under 1B will have their alert threshold (`price_percent`) doubled.

Config example:
```
price_percent=9.4
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
.midsession [percent]
```
```
@botname midsession [percent]
```

Interactive trigger (interday).
```
.price [percent]
```
```
@botname [percent]
```

For interday, can also specify the time period.
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
future_days=7
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

List securities by P/E ratio, forward P/E ratio, or PEG ratio

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

Show top recommended buys by Yahoo Finance analysts rating

Interactive trigger:
```
.buy
```
```
@botname buy
```

### Sell
![Rating report in Slack](img/finbot_sell.png?raw=true "Rating report in Slack")

Show top recommended sells by Yahoo Finance analysts rating

Interactive trigger:
```
.sell
```
```
@botname sell
```

### Marketcap
![Marketcap report in Slack](img/finbot_marketcap.png?raw=true "Marketcap report in Slack")

List the top (or bottom) stocks by market cap

Interactive trigger:
```
.marketcap [top|bottom]
```
```
@botname marketcap [top|bottom]
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
Configuration is split into two files by **when a change can take effect**. Start by creating both from the shipped templates:
```
sudo cp ~/finbot/defaults/finbot.env /opt/finbot.env && sudo chmod 600 /opt/finbot.env && sudo vi /opt/finbot.env
util/sync_defaults.py --apply     # copies preferences.conf into the data directory (never overwrites)
vi <data directory>/preferences.conf
```

| | **`finbot.env`: the startup file** | `preferences.conf` |
|---|---|---|
| Holds | where finbot runs, who it talks to, where it reports: `DATA_DIR`, `ip`, `port`, `telegramChatID`, `scheduler`, `scheduler_catchup` and the 11 credentials and endpoints (17 keys) | how it behaves: every other setting (25 keys) |
| Read by | **your launcher, never by the bot**. The bot only inherits the values in its environment (see below). | **the bot itself**, from `<data directory>/preferences.conf`, at start and on every reload |
| A change takes effect | after a **restart** | on a **reload**: `sudo systemctl kill -s HUP finbot` (or `systemctl reload finbot` if your unit has `ExecReload=`, as the shipped one does), `docker kill -s HUP <container>`, or `kill -HUP <pid>` |
| Protection | root-owned, `chmod 600`. It holds the credentials, and the bot cannot read or change it. | lives in the data directory, so it holds nothing sensitive |
| Format | flat `KEY=value` lines | flat `KEY=value` lines: **not** an INI file, no `[sections]` |

Both files are plain `KEY=value`: no spaces around `=`, no quotes, no trailing comments (comments go on their own line). The two files never overlap, and **finbot refuses to start if a key is in the wrong one** or is not a known key at all (a typo such as `futur_days`). The error names the file, the line and where the key belongs. A preference key (such as `future_days`) arriving through the environment is refused the same way.

**Load `finbot.env` with your launcher:**
* **systemd:** `EnvironmentFile=/opt/finbot.env` in `finbot.service`, plus `ExecStartPre=+.../util/check_config.py /opt/finbot.env` so a typo stops the start (the shipped unit has both).
* **Docker:** `--env-file /opt/finbot.env`. Docker keeps quotes literally, so use none. Run `util/check_config.py /opt/finbot.env` first if you want the same check.
* **init.d / shell:** `util/check_config.py /opt/finbot.env && set -a && . /opt/finbot.env && set +a && ./bot.py` (`set -a` is what exports the values to the bot).
* **Scheduled jobs:** they are started by `bot.py` (see [Scheduling](#scheduling)), so they run on the same settings. For a one-off run, see [Running a report by hand](#scheduling).
* **AWS Lambda:** set them as function environment variables.

**Changing settings:** edit `preferences.conf`, then reload. The log shows what changed (`config: future_days 7 -> 30`). If the file has a mistake, the reload reports it (`ERROR config: ...`), applies nothing and leaves finbot running on its previous settings. Check an edit before reloading with `util/check_config.py /opt/finbot.env`. Edit `finbot.env`, then restart: a running bot cannot see it change.

### finbot.env: why these keys need a restart
`finbot.env` is the startup file. These are the keys in it, and why none of them can be changed by a reload:

| Key | Why a reload cannot apply it | Kind |
|---|---|---|
| `ip`, `port` | `bot.py` binds the socket once. A new address means closing and reopening it, dropping in-flight requests, and usually changing the reverse proxy. | technical |
| `DATA_DIR` (and systemd's `STATE_DIRECTORY`) | It locates everything else: `preferences.conf`, `schedule.cron`, the state files and the cache, and `MPLCONFIGDIR`, which matplotlib reads once. Moving it would orphan the seen-trades, ratings and milestone state. | technical |
| `telegramBotToken` | At start finbot registers its inbound URL with Telegram and learns the bot's `@username`, which it uses as the command prefix. A new token is a different bot. | technical |
| `telegramOutgoingWebhook`, `telegramOutgoingToken` | These are what was registered with Telegram at start, and the bot matches every request against them. Changing only the local side makes Telegram keep sending the old URL and secret, and every inbound message is rejected. | technical |
| `slackOutgoingWebhook`, `slackOutgoingToken` | The same for Slack: they must match what your Slack app sends. | technical |
| `sharesight_code`, `sharesight_client_id`, `sharesight_client_secret` | They mint the Sharesight token, which is cached on disk for about 30 minutes. After a change the cached token still belongs to the old account until it expires. `code` is also a one-time OAuth value. | technical |
| `telegramChatID` | Could be reloaded, but it decides where scheduled reports go (trades, performance, ratings), and `preferences.conf` sits in the writable data directory. A report destination should not be editable by anything with write access there, and a typo would silently send reports to the wrong chat. | deliberate |
| `scheduler`, `scheduler_catchup` | Whether the scheduler runs is decided at start. A live toggle would need machinery to stop a thread and handle jobs in flight, for something that rarely changes. | deliberate |
| `slackBotToken` | The outbound Slack credential. A typo would silently stop Slack replies. | deliberate |
| `slack_webhook`, `discord_webhook` | They define which services every report goes to. A typo would silently redirect or drop all reports. | deliberate |

"Technical" means a reload cannot do it without more machinery than it is worth. "Deliberate" means it could be done and is held back on purpose.

### If a file is missing or wrong
| Situation | At start | On reload |
|---|---|---|
| No `preferences.conf` | Fine: built-in defaults (and a log line saying reload has nothing to re-read) | `ERROR`, nothing reloaded, finbot keeps running |
| `preferences.conf` unreadable, malformed, unknown or misplaced key, bad value | **Refuses to start** (exit 1), naming file and line | `ERROR`, nothing applied, finbot keeps running on its previous settings |
| A preference key in the environment (`finbot.env`) | **Refuses to start** | not applicable |
| `finbot.env` missing or unreadable | Your launcher fails before finbot starts | not applicable |
| `finbot.env` edited while running | not applicable | not noticed: restart |
| `preferences.conf` edited, no reload sent | not applicable | nothing changes, scheduled jobs included, until you reload |

**Upgrading from one `.env`?** Run `util/migrate_env.py --write` first if it is in the old dotenv format (`key = 'value' # comment`), then `util/split_env.py /opt/finbot.env`. It writes `finbot.env.new` and `preferences.conf.new` next to it, never overwriting, and lists any key it dropped or did not recognise. Until you split, finbot refuses to start because the one file mixes both kinds of key.

### Data directory
All state and cache lives under `var/` in the checkout by default. Set `DATA_DIR` to relocate it (cache moves to `$DATA_DIR/cache`), e.g. for a Docker bind mount that survives rebuilds:
```
docker run -v /srv/finbot:/data -e DATA_DIR=/data --env-file /opt/finbot.env ...
```
Reference data (`finbot_adr.json`, `finbot_sws_*.json`, `reminder.json`) ships in `defaults/`. A file of the same name in the data directory takes precedence. Defaults are never copied or overwritten automatically; to see or pull in updates run:
```
util/sync_defaults.py          # dry run
util/sync_defaults.py --apply  # copy missing files (including a starter preferences.conf)
util/sync_defaults.py --force  # also overwrite changed files, keeping .bak copies
```
With systemd `DynamicUser=yes` and `StateDirectory=finbot`, `DATA_DIR` defaults to systemd's `$STATE_DIRECTORY` (`/var/lib/finbot`), so no setting is needed; move existing data once with `cp -a /opt/finbot/var/. /var/lib/finbot/`. An explicit `DATA_DIR` always wins.

In Docker, one container is enough: `bot.py` runs the schedule too, so there is no cron or scheduler sidecar to set up.

On AWS Lambda only `/tmp` is writable and ephemeral, so mount EFS and point `DATA_DIR` at it. S3 is not supported yet.

### Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to `finbot.env`. Example:
```
sharesight_code=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_id=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_secret=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
```

### Discord
Discord support is currently only for trade notifications and scheduled reports.
The Discord webhook can be provisioned in Discord under _Server Settings > Integrations > Webhooks_.
Example:
```
discord_webhook=https://discord.com/api/webhooks/1009998000000000000/aaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbb
```

### Slack
A Slack webhook can be provisioned by creating a new app from scratch at https://api.slack.com/apps/ then navigating to _Incoming Webhooks_. Once the link is generated, add it to `finbot.env`. Example:
```
slack_webhook=https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA
```
The webhook is only used for the trade notifications and scheduled reports. The interactive bot requires further configuration of this Slack app (see below).

### Telegram
* Set up the bot by messaging [BotFather](https://telegram.me/BotFather).
* Add your bot to a group or channel.
* For security, run `/setjoingroups` and set to `Disabled`
* Optionally, make the bot a group admin (for interactive features).
* In `finbot.env`, set `telegramBotToken` to the token BotFather gave you.
* In `finbot.env`, set `telegramChatID` to the chat group or channel id.
   * For channels and supergroups, `telegramChatID` should be negative and 13 characters. Prepend `-100` if necessary.
   * Be aware a group id can change if you edit group settings and it becomes a "supergroup". Currently, the bot does not automatically handle this.
* Example `finbot.env` entry:
```
telegramBotToken=0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA
telegramChatID=-1001000000000
```

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
Many objects are cached for just under one day by default. Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache=True
cache_seconds=82800
performance_cache_seconds=1800
```

`performance_cache_seconds` (default 30 minutes) is the cache lifetime of Sharesight performance reports.

While `bot.py` is running (with `cache=True` and Sharesight configured), a background job keeps the Sharesight portfolio list (`cache_seconds`) and each portfolio's holdings report (1 day, `performance_cache_seconds` cache) refreshed at 90% of their cache lifetime, so chat requests do not wait on Sharesight. If a refresh fails, the previous cache keeps being served and the job retries after 5 minutes.

### Hyperlinks
These `preferences.conf` options relate to hyperlinks:

* `hyperlink`, if set to `False`, disables all hyperlinks. Note: it can not disable syntax highlighting and false positives by chat clients that try to detect domains. Setting it to `False` can be useful for chat networks like Discord that can't easily disable link previews. Defaults to `True`.
```
hyperlink=True
```

* `hyperlinkFooter` appends hyperlinks to the company website and to a Google search for the ticker on simplywall.st  for the symbol lookup report. Possible values are `True` or `False`. Defaults to `False`.

```
hyperlinkFooter=True
```

* `hyperlinkProvider` configures where to send ticker hyperlinks. Available values are `google` and `yahoo`. If set to `google`, it is only used where practical, as Google does not publish earnings date, ex-dividend date, premarket price, or short interest figures. Defaults to `yahoo`.
```
hyperlinkProvider=google
```
```
hyperlinkProvider=yahoo
```

## Scheduling
The scheduled reports are started by `bot.py`, each run in its own child process (`python -m lib.jobrun`), so they use the same user, sandbox, environment and data directory as the bot, while heavy work (charts, large reports) cannot hold up incoming chat webhooks. A run that exceeds 15 minutes is stopped. There is no cron to set up, which matters under systemd `DynamicUser=` where only the bot's own user can read the state directory. **This is on by default.** Remove the equivalent entries from any old crontab before the first start, otherwise every job runs twice; or set `scheduler=False` in the environment file to keep using cron.

The schedulable scripts are `trades.py`, `price.py`, `reminder.py`, `cal.py`, `shorts.py`, `performance.py`, `rating.py`, `milestone.py`, `podcasts.py "<feed url>"` and `cleanup.py [days]` (deletes cache files older than `days`, default 30). Other jobs, such as a DNS updater or backups, stay in cron or systemd timers.

The schedule is `defaults/schedule.cron`, written in **cron-compatible syntax**: five time fields (minute, hour, day of month, month, day of week; `*/20`, `Mon-Fri`, ranges and lists work) or an `@macro` such as `@daily`, then a finbot script and its arguments. Quote an argument that has spaces or special characters (a feed URL with `&`, say). Several commands separated by `;` run one after another. `MAILTO=`, `SHELL=`, `PATH=` and `HOME=` lines are ignored. Anything else a crontab allows (a user column, pipes, other programs) is not supported: such a line is reported at startup and skipped. Existing crontab lines can be pasted as they are: `> /dev/null` redirects, `{ a; b ;}` groups and a path before the script name are understood.
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
* A job still running when it is next due is skipped, and a job that takes more than 15 minutes is abandoned and reported.
* Failures are reported to your chat channels, as before.
* With `scheduler=False` nothing is scheduled by the bot, so you can keep using cron or systemd timers and run the scripts yourself.

**Running a report by hand.** Under `DynamicUser=yes` you cannot simply log in as the bot's user, so run the script as a transient unit with a dynamic user and the same state directory:
```
sudo systemd-run --pty --wait --collect -p DynamicUser=yes -p StateDirectory=finbot -p EnvironmentFile=/opt/finbot.env /opt/finbot/price.py 7
```
The script prints its output on your terminal and sends its report to your chat channels as usual. The transient unit gets its own dynamic user, and systemd may re-own the state directory to it for the run: check `ls -ln /var/lib/private/finbot` afterwards and `systemctl restart finbot` if the bot can no longer write there. The chat commands (`.price 7d`, `.performance 7d`, ...) run the same reports inside the bot, without any of this. Outside systemd, run a script from the checkout as your own user with the settings loaded into the shell: `set -a; . ./.env; set +a; ./price.py 7` (this works while no value in the file contains spaces).

## Interactive bot setup
The backend `bot.py` needs a frontend https server on a valid domain name with a valid x509 certifcate.
It defaults to listening on http://127.0.0.1:5000/, which can be changed with `ip` and `port` in `finbot.env`.

Example frontend https server config (nginx):
```
server {
	listen 8443 ssl;
	deny all;

	server_name         www.example.com;
	ssl_certificate     /etc/letsencrypt/live/www.example.com/fullchain.pem;
	ssl_certificate_key /etc/letsencrypt/live/www.example.com/privkey.pem;
	ssl_protocols       TLSv1 TLSv1.1 TLSv1.2;
	ssl_ciphers         HIGH:!aNULL:!MD5;

	location /slack {
		proxy_pass http://127.0.0.1:5000/slack;
                include /etc/nginx/aws_subnets;
                deny all;
	}
	location /telegram {
		proxy_pass http://127.0.0.1:5000/telegram;
		include /etc/nginx/telegram_subnets;
		deny all;
	}
}
```
Note: The utils folder contains scripts to generate `/etc/nginx/aws_subnets` and `/etc/nginx/telegram_subnets`. They can be run once, or placed in `/etc/cron.daily/`.

### Integrating the interactive bot with chat networks

#### Telegram
* Message BotFather to create a bot user.
  * Set `telegramBotToken` in `finbot.env` to the token given by BotFather.
  * Add your Telegram bot user to a group
    * Give the bot group admin access so it can read the group chat.
    * For security, message BotFather and disable `/setjoingroups`.
* Set `telegramOutgoingWebhook` in `finbot.env` to your web server (e.g. https://www.example.com:8443/telegram).
* Set `telegramOutgoingToken` to a password of your choosing. Telegram will use this to authenticate with finbot.
With these options set, your bot will auto-subscribe your URL to events the bot sees, when you run `bot.py`.

#### Slack
Visit https://api.slack.com/apps/ to create a new Slack app from scratch (if you already created one for a finbot webhook, you can reuse that app).
* From _Basic Information > Verification Token_, copy _Verification token_ into `finbot.env` as `slackOutgoingToken`. This allows Slack to authenticate with finbot.
* In `finbot.env`, put your web server URL (e.g. https://www.example.com:8443/slack) into `slackOutgoingWebhook`
* Save `finbot.env` and restart `bot.py`
* Under _Event Subscriptions_:
  * Go to _Enable Events > On > Request URL_ and enter your web server URL (e.g. https://www.example.com:8443/slack). At this time, if the bot is reachable, it will auto respond to Slack's verification request.
  * Go down to _Subscribe to bot events_ and add event `app_mention` for the bot to see _@botname_ mentions.
    * Alternatively, you can subscribe to `message.channels` if you want your bot to see everything and respond to `.` commands. To avoid duplicate responses, don't subscribe to `app_mention` and `message.channels` at the same time.
    * If you want to DM the bot:
      * Subscribe to `message.im`
      * Check the box _App Home > Allow users to send Slash commands and messages from the messages tab_
  * Save Changes
* Under _OAuth & Permissions_:
  * Scroll down to _Scopes > Bot Token Scopes_, and add: `chat:write` and `files:write`.
  * Scroll up to _OAuth Tokens for Your Workspace_:
    * If _Bot User OAuth Token_ is not visible, hit _Install to Workspace > Allow_
    * Copy _Bot User OAuth Token_ into `finbot.env` as `slackBotToken`. This allows finbot to authenticate with Slack so it can send replies.
    * Restart `bot.py`

### Daemonize (systemd)
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

## Limitations
* Discord shows garbage link previews from Sharesight. Set `hyperlink=False`, or disable this for each Discord client under _Settings > Text & Images > Embeds and link previews_ (must be repeated for each participating Discord client).

## Suggestions
* Is my code is doing something the hard way?
* Something important is missing from this README?

Log an [issue](https://github.com/robdevops/finbot/issues)!
