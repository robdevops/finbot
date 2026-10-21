# Classes

Every class in `bot.py` and `lib/`, by what it is for. A class named in two places (`Telegram`, `Slack`, `Discord`) is
a network's update reader in its `*_common.py` and a markup dialect in `lib/dialects.py`.

## Networks: updates in, messages out
| Network | Reader of its updates | Bot that posts | Webhook (push) | Pull client |
|---|---|---|---|---|
| Telegram | `Telegram` | `TelegramBot` | `TelegramWebhook` | `TelegramPoll` (long polling) |
| Slack | `Slack` | `SlackBot` | `SlackWebhook` | `SlackSocket` (Socket Mode) |
| Discord | `Discord` | `DiscordBot` | `DiscordInteractions` | `DiscordGateway` |

- **Bases:** `inbound.Network` (a reader), `inbound.Webhook`, `transports.Transport` (a bot), `pull.Listener` and
  `pull.SocketListener` (a pull client; `pull.WebSocket` is its connection, `pull.Closed` raised when the server closes it).
- **What a reader hands on** (`lib/inbound.py`): `Message`, `Press` (a button pressed), `Suggest` (a slash command's
  arguments as typed) and `Response` (what the network gets back at once); `Recent` remembers what was taken lately, to
  drop repeats.
- **`bot.py`:** `WholeLines` writes each log line whole, whichever threads log at once; `Sent` is a response body that
  starts some work once the server has sent it.

## Markup and delivery
- `Dialect` (a `str` of the network's name) with `Telegram`, `Slack` and `Discord`: its markup, link syntax and limits.
- `delivery.Report` (lines, a chart spec, buttons) and `delivery.Preloader` (charts drawn ahead of presses).

## Commands and buttons
- `worker.Command` (a row of the command table), `CommandJob` (a command run as a job), `Args` (what a command was
  given), `Request` (a command being answered), `Slash` (a slash command to register) and `Usage` (raised for arguments a
  command cannot take).
- `buttons.Button`; `ChartPress`, `MenuPress` and `PickPress` (a press, read from its data); `Act` (what a picker's
  press asks for).

## Scheduling
- `jobs.Scheduler` (runs the jobs) and `Job`; `catalog.Item` (a default job); `when.Schedule` (when a job runs).

## Reports and charts
- `render.Chart` (a chart spec, drawn later); `render._Canvas` and `_Axes` (what a chart is drawn on).
- Data a report works from: `movers.Moves`, `trades.Trade`, `yahoo.Line` (a price line) and `markets.Market`.

## Data sources and configuration
- `sharesight.Portfolio`.
- `config.Env` (finbot.env, fixed at start), `Settings` (settings.conf, new on each reload) and the private `_Reader`
  that reads their typed fields.

## Errors
- **Replies, not failures:** `answer.Answer` (lines to reply with in place of the report) and `answer.Nothing` (nothing
  to show: said only to a command or a button, never in a job's run). Both are also raised by:
  - `sharesight.NotSetUp` and `PortfolioNotFound`;
  - `yahoo.NoData`.
- **Failures:**
  - `net.RateLimited` (a 429 and the wait it asks for);
  - `transports.MaybeSent` (a chart's post timed out: it may have arrived);
  - `sharesight.Refused` (credentials refused: the token is renewed);
  - `when.ScheduleError` (a schedule or job that cannot be);
  - `config.ConfigError` (problems in finbot.env or settings.conf, each naming its file and line).
