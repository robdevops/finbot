# Configuration

Configuration is split into two files -- finbot.env for startup environment variables, and preferences.conf for values that can be changed at runtime.

Copy the shipped template:
```
sudo cp ~/finbot/defaults/finbot.env /opt/finbot.env && sudo chmod 600 /opt/finbot.env
```

## `finbot.env`
**Load `finbot.env` with your launcher:**
* **systemd:** `EnvironmentFile=/opt/finbot.env` in `finbot.service`, plus `ExecStartPre=+.../util/check_config.py /opt/finbot.env` for pre-flight lint.
* **Docker:** `compose.yaml` loads it, and checks it before the bot starts (see [docker.md](docker.md)). Write the values without quotes.
* **init.d / shell:** `util/check_config.py /opt/finbot.env && set -a && . /opt/finbot.env && set +a && ./bot.py` (`set -a` is what exports the values to the bot).
* **Scheduled jobs:** they are run by `bot.py` (see [Scheduling](scheduling.md)), so they run on the same settings. For a one-off run, send `.jobs run` in the chat.

The startup keys, read by your launcher. A change needs a restart. Blank means unset. Each network's guide says which
of the chat network keys it needs.

| Key | Default | Description |
|---|---|---|
| `DATA_DIR` | `var/` in the checkout (`$STATE_DIRECTORY` under systemd `StateDirectory=`) | Where state and cache live |
| `ip` | `127.0.0.1` | Address the bot listens on |
| `port` | `5000` | Port the bot listens on |
| `scheduler_catchup` | `5` | Minutes: a run missed while the bot was down still fires if it was due this recently |
| `telegramChatID` | | Telegram's home chat, a group or channel id: finbot's first start gives it the default jobs, and error reports go there (see [Scheduling](scheduling.md)) |
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

## `preferences.conf` items

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

## Data directory
All state and cache lives under `var/` in the checkout by default. Set `DATA_DIR` to relocate it (cache moves to `$DATA_DIR/cache`); in Docker it is `/data`, the host's `/opt/finbot-data` (see [docker.md](docker.md)).
Reference data (`finbot_adr.json`, `finbot_sws_*.json`, `reminder.json`) ships in `defaults/`. A file of the same name in the data directory takes precedence. Defaults are never copied or overwritten automatically; to see or pull in updates run:
```
util/sync_defaults.py          # dry run
util/sync_defaults.py --apply  # copy missing files (including a starter preferences.conf)
util/sync_defaults.py --force  # also replace changed files, keeping .bak copies
util/sync_defaults.py --dest /srv/finbot --apply  # target another directory instead of the data directory
util/sync_defaults.py --dest /srv/finbot --create --apply  # and make it (mode 750) if it does not exist yet
```
`reminder.json` holds the reminders that the `reminder` report posts on their day. Each entry has a `month_day` (`06-30`) and a `message`, which is one line or a list of lines, and may name a `year` (`2026`) and a `gate_country` (posted only when `country_code` in `preferences.conf` matches; `{flag}` in its message becomes that country's flag). A message is text, with two kinds of markup that each network gets in its own form: `[text](https://example.com)` is a link, and a line wrapped in underscores, `_like this_`, is in italics. The Australian end of financial year checklist (23 June) is such an entry: if you keep your own `reminder.json` in the data directory, `util/sync_defaults.py` shows what it lacks.

With systemd `DynamicUser=yes` and `StateDirectory=finbot`, `DATA_DIR` defaults to systemd's `$STATE_DIRECTORY` (`/var/lib/finbot`), so no setting is needed; move existing data once with `cp -a /opt/finbot/var/. /var/lib/finbot/`. An explicit `DATA_DIR` always wins.

In Docker, one container is enough: `bot.py` runs the schedule too, so there is no cron or scheduler sidecar to set up. Each start copies the defaults the data directory lacks (`util/sync_defaults.py --apply`).

## Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to `finbot.env`. Example:
```
sharesight_code=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_id=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_secret=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
```

## Portfolios
Portfolios are auto-discovered, including other people's portfolios which are shared to you. To exclude specific portfolios, add their IDs to `exclude_portfolios` in the `preferences.conf`:
```
exclude_portfolios=100003 100004
```

Alternatively, you can include only specific portfolios:
```
include_portfolios=100001 100002
```

## Hyperlinks
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
