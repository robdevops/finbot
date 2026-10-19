# Configuration

Configuration is split into two files -- finbot.env for startup environment variables, and settings.conf for values that can be changed at runtime.

Copy the shipped template:
```
sudo cp ~/finbot/defaults/finbot.env /opt/finbot.env && sudo chmod 600 /opt/finbot.env && sudo chown root:root /opt/finbot.env
```

## `finbot.env`
**Load `finbot.env` with your launcher:**
* **systemd:** `EnvironmentFile=/opt/finbot.env` in `finbot.service`, plus `ExecStartPre=+.../util/check_config.py /opt/finbot.env` for pre-flight lint.
* **Docker:** `compose.yaml` loads it, and checks it before the bot starts (see [docker.md](docker.md)). Write the values without quotes.
* **init.d / shell:** `util/check_config.py /opt/finbot.env && set -a && . /opt/finbot.env && set +a && ./bot.py` (`set -a` is what exports the values to the bot).
* **Scheduled jobs:** they are run by `bot.py` (see [Scheduling](scheduling.md)), so they run on the same settings. For a one-off run, send `/jobs run` in the chat.

The startup keys, read by your launcher. A change needs a restart. Blank means unset. Each network's guide says which
of the chat network keys it needs.

| Key | Default | Description |
|---|---|---|
| `DATA_DIR` | `var/` in the checkout (`$STATE_DIRECTORY` under systemd `StateDirectory=`) | Where state and cache live |
| `ip` | `127.0.0.1` | Address the bot listens on, in push mode |
| `port` | `5000` | Port the bot listens on, in push mode |
| `scheduler_catchup` | `5` | Minutes: a run missed while the bot was down still fires if it was due this recently |
| `sharesight_client_id` | | Sharesight API access |
| `sharesight_client_secret` | | Sharesight API access |
| `telegramBotToken` | | Telegram bot token: reports, and commands (finbot fetches its updates unless `telegramOutgoingWebhook` is set) |
| `slackBotToken` | | Slack bot token, for replies and chart uploads in Slack |
| `slackAppToken` | | Slack app-level token (`xapp-`): commands over a socket finbot opens to Slack (Socket Mode), when `slackOutgoingWebhook` is empty |
| `telegramOutgoingWebhook` | | The URL Telegram posts its updates to (push mode); empty, finbot fetches them (pull mode) |
| `telegramOutgoingToken` | | Secret token Telegram must present (push mode) |
| `slackOutgoingWebhook` | | The URL Slack posts its events and button presses to (push mode); empty, Socket Mode with `slackAppToken` |
| `slackOutgoingToken` | | Token Slack must present (push mode): the older way, which Slack has deprecated; not needed with `slackSigningSecret` |
| `slackSigningSecret` | | Secret Slack signs each request with (push mode) |
| `discordBotToken` | | Discord bot token: replies, and commands over the gateway API unless `discordOutgoingWebhook` is set |
| `discordOutgoingWebhook` | | The Interactions Endpoint URL Discord posts slash commands and button presses to (push mode); empty, the gateway API (pull mode) |
| `discordPublicKey` | | The app's public key, which checks the signature of each interaction (push mode) |

Retired keys do nothing, and only get a note at start (and from check_config) saying to delete the line: `telegramChatID`, `slackChannelID` and `discordChannelID` (there are no home chats: each chat has its own jobs, and an error that belongs to no chat goes to the log), and `slack_webhook` and `discord_webhook`.

## `settings.conf` items

The settings, read by the bot itself from `<DATA_DIR>/settings.conf`; without that file, finbot runs on the built-in defaults below. `defaults/settings.conf` is only its template: every key in it is commented out at its default, and finbot never reads it. To change a setting, copy the template into the data directory (this never overwrites a file there):
```
util/sync_defaults.py [--dest DIR] --apply
```
then remove the `#` before the key and edit its value. A key set in `defaults/settings.conf` itself does nothing: the log at start (and check_config) says so, and where to set it instead.

A change takes effect on a reload. A true/false setting takes `true`/`false`, `yes`/`no`, `on`/`off` or `1`/`0`; anything else is a mistake, reported like any other. A blank value means the default.

| Key | Default | Description |
|---|---|---|
| `admin_only` | `jobs` | The commands only the admins may use, by name, space separated (`jobs watchlist`). Closed by default: `/jobs` is one, and only the admins may use it (see `admins`: a chat's own administrators are admins there). Blank (`admin_only=`) restricts no command. Someone else gets a refusal, and a press of one of those commands' buttons is refused with a message to them alone (an alert on Telegram, a message only they see on Slack and Discord) |
| `admins` | | Who the admins are besides each chat's own administrators (below), space separated, each the network and the sender's id as the log shows them: `telegram:@username` (or the numeric user id; never a first name, which anyone may take), `slack:U0123ABCD` (`<@U0123ABCD>` in the log), `discord:123456789012345678` |

The administrators of the chat a person is in are admins there with no setting: the creator and administrators of a Telegram group (the bot asks `getChatMember`), the owner and anyone with an Administrator role in a Discord server, and the owners and admins of a Slack workspace (`users.info`; needs the `users:read` scope, which the manifest has). In a direct message with the bot, a person is an admin if they are one in any Telegram group finbot has seen, or Discord server the bot is in (a Slack workspace's admins are admins everywhere). finbot asks again every five minutes, so a change shows soon. A question whose connection fails is asked once more at once; where it still fails (a network down, or a scope missing), the network's last answer stands, else the `admins` setting alone decides, and the next message asks again.
| `past_days` | `28` | How many days back reports look |
| `future_days` | `30` | How many days ahead the events calendar looks |
| `price_percent` | `5` | Movers threshold, percent: the moves `/movers`, `/session` and their jobs list |
| `shorts_percent` | `15` | Short interest alert threshold, percent |
| `min_analysts` | `7` | `/buy`, `/sell`, `/pe` and `/peg` list only stocks covered by at least this many analysts; with fewer, a consensus or an estimate says little (thinly covered small caps are nearly all a perfect buy). Their charts say so in the subtitle |
| `demote_volatile` | `True` | Volatile (small cap, high beta) stocks need a bigger move to alert |
| `demote_leveraged` | `True` | Leveraged (2x, 3x) funds need a bigger move to alert |
| `volatility_multiplier` | `2` | How much bigger a move volatile stocks need |
| `exclude_portfolios` | | Sharesight portfolio IDs to leave out, space separated |
| `include_portfolios` | | Sharesight portfolio IDs to report on, space separated (empty: all that are not excluded) |
| `trades_use_yahoo` | `True` | Use Yahoo for trades; set `False` if Yahoo breaks |
| `graph` | `True` | Send charts with reports |
| `hyperlink` | `True` | Hyperlink tickers in reports |
| `hyperlinkFooter` | `True` | Add a website link footer to stock lookups |
| `hyperlinkProvider` | `google` | Where ticker links go: `google` or `yahoo` (any other value stops a start or a reload, naming the key) |
| `exchange_suffix` | `AX` | Regional: Yahoo's suffix for your exchange (`AX` for the ASX, `NZ`, `L`, `TO` and so on). A bare symbol Yahoo does not know is tried again with it, in every command that takes a symbol (`BHP` becomes `BHP.AX`); empty, a symbol is taken as written |
| `country_code` | `AU` | Regional: your country, in any case, for the default jobs' messages that are for one (`AU`: the tax year's reminders) |
| `timezone` | `Australia/Melbourne` | Regional: your time zone, the clock of the times `/jobs` takes and shows, a job's zone where it names none, and what "today" is (ytd, reports' dates); a name that is no zone stops a start or a reload, naming the key |
| `telegram_preload_chat` | | A private Telegram channel or group of your own, by its id (`-1001234567890`, as the log shows a chat's): as a chart with period or portfolio buttons goes out, its other periods and portfolios are uploaded there, so that a press shows them without an upload (see [Telegram](telegram.md#preloading-charts)). Empty: off |
| `slack_preload_chat` | | The same on Slack: a private channel's id (`C0123ABCD`), the bot invited (see [Slack](slack.md#preloading-charts)). Empty: off |
| `preload_gap` | `0.1` | Seconds between the starts of two charts preloaded to a network (two uploads at a time, on Telegram and Slack alike, each chart sent as soon as it is drawn). A rate limit is waited out once and the upload tried again, as every request to a network is |
| `cache` | `True` | Cache Yahoo and Sharesight responses |
| `cache_seconds` | `21600` | Cache lifetime in seconds (6 hours) |
| `performance_cache_seconds` | `2400` | Cache lifetime of Sharesight performance reports in seconds: longer than the 30 minutes between `sharesight_warm` runs, so the holdings never run out |
| `http_timeout` | `18` | Seconds to wait on outbound HTTP requests |
| `log_level` | `INFO` | What the log shows: that level and those above it, syslog style. `ERROR`: what failed and was lost (a message not sent); `WARN`: what failed and was got over (a retry, a fallback, a request refused); `INFO`: what finbot does (each message sent, each job run, each request sent, each request refused); `DEBUG`: the routine of a button press too (the press, its acknowledgement, the message edited in place), each request answered with success, and each cache miss, hit and write. Replaces `debug` |
| `log_width` | `71` | The most characters of a log line that can run long: a longer one is cut there, ending in `…`. That is each request's line (its method and URL) and each chat message's (who sent what, in which network). A message of several lines is logged on one line, its line breaks spaces. `0`: no line is cut |
| `print_headers` | `False` | Log inbound request headers |

A key in the wrong file, or one that is not listed, stops finbot starting; on a reload it is reported and nothing is applied. A key finbot no longer reads (`alliterate`, `chunk_maxlines`) is ignored, and the log at start says to delete it.

edit `settings.conf`, then reload if running. The service log shows what changed (`config: future_days 30 -> 45`). If the file has a mistake, the reload reports it (`ERROR config: ...`), applies nothing and leaves finbot running on its previous settings. Check an edit before reloading with `util/check_config.py /opt/finbot.env`. Edit `finbot.env`, then restart: a running bot cannot see it change.

**Upgrading from a version before 16 Oct 2026?** Start commit `ff52f2b` once first, as [Scheduling](scheduling.md#from-an-earlier-version) says: it splits one old `.env` (`util/split_env.py`, which it asks for) and renames `preferences.conf` to `settings.conf`, which later versions no longer do.

## Data directory
All state and cache lives under `var/` in the checkout by default. Set `DATA_DIR` to relocate it (cache moves to `$DATA_DIR/cache`); in Docker it is `/data`, the host's `/opt/finbot-data` (see [docker.md](docker.md)).
Reference data (`finbot_adr.json`, `finbot_sws_*.json`) ships in `defaults/`. A file of the same name in the data directory takes precedence. Defaults are never copied or overwritten automatically; to see or pull in updates run:
```
util/sync_defaults.py          # dry run
util/sync_defaults.py --apply  # copy missing files (including a starter settings.conf)
util/sync_defaults.py --force  # also replace changed files, keeping .bak copies
util/sync_defaults.py --dest /srv/finbot --apply  # target another directory instead of the data directory
util/sync_defaults.py --dest /srv/finbot --create --apply  # and make it (mode 750) if it does not exist yet
```
The reminders that `reminder.json` held are default jobs now (see [Scheduling](scheduling.md#the-default-jobs)), and finbot reads `reminder.json` no more: delete the data directory's copy. A chat adds its own with `/jobs add reminder SCHEDULE "TEXT"`.

With systemd `DynamicUser=yes` and `StateDirectory=finbot`, `DATA_DIR` defaults to systemd's `$STATE_DIRECTORY` (`/var/lib/finbot`), so no setting is needed; move existing data once with `cp -a /opt/finbot/var/. /var/lib/finbot/`. An explicit `DATA_DIR` always wins.

In Docker, one container is enough: `bot.py` runs the schedule too, so there is no cron or scheduler sidecar to set up. Each start copies the defaults the data directory lacks (`util/sync_defaults.py --apply`).

## Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to `finbot.env`. Example:
```
sharesight_client_id=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
sharesight_client_secret=01d692d4de7 samplefc64bc2e2f01d692d4de72986ea808f6e99813f
```
* Sharesight is optional. Without its keys, a chat's reports cover its watchlist alone, so add your holdings to it (`/watchlist add SYMBOL`); `/holdings`, `/trades`, `/performance`, `/who`, `/pie` and `/treemap` say Sharesight is not set up, and the trades and performance jobs are not among the default jobs.

## Portfolios
Portfolios are auto-discovered, including other people's portfolios which are shared to you. To exclude specific portfolios, add their IDs to `exclude_portfolios` in the `settings.conf`:
```
exclude_portfolios=100003 100004
```

Alternatively, you can include only specific portfolios:
```
include_portfolios=100001 100002
```

## Hyperlinks
These `settings.conf` options relate to hyperlinks:

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
