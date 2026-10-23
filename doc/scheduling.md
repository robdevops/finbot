# Scheduling

Each chat has its own jobs: reports and messages that run on a schedule and post to that chat. finbot's admins
(a chat's own administrators, and those the `admins` setting names: [configuration](configuration.md); `/jobs` is one of the `admin_only` commands) manage them
there, with `/jobs` (or `/job`; as a message, also `.cron`, `.crons` or `.schedule`).

Every chat starts with the [default jobs](#the-default-jobs): switched on in a group or a channel, and switched off in a
direct message with the bot, until the chat switches them. finbot knows a chat from its first command. A direct message is a person's chat on Telegram, a `D…`
channel on Slack, and on Discord a message from no server.

## The menu
`/jobs` lists the chat's jobs, numbered (the top level shows as many as fit a message, then how many more there are, with no page buttons: Edit and Run list every job, a page at a time), the jobs of each report together under a heading with its name (Movers, Shorts, ...), the reminders last under theirs. Each line is struck through and marked ❌ when the job is off, with a `*` if the job has While a job is added, each step shows the list under its question.
never run, its name and its schedule in words. Under the list, in italics, is how Add is typed:
```
1. trades · every 20 mins, Mon 9am – Sat 3pm Sydney
3. * movers midsession US · weekdays at 12:45pm New York (3:45am local, Tue–Sat)

* not run yet

/jobs add REPORT SCHEDULE
/jobs add reminder SCHEDULE "TEXT"
```
Under it is one row of buttons, each there only where it has something to act on (**+** always; **Edit** and **Run...** with any job, **Upcoming** with one that is on). Each screen is drawn in place of the last:
* **+**: what the job runs, how often, then the rest down to the minute ([below](#add-step-by-step)).
* **Edit**: the list with a button per job, the default ones too; a press selects the job (its button turns red, on Telegram, Slack and Discord alike) or takes it out of the selection again. It starts with the jobs that are off selected, and nothing changes until **OK**, which switches the selected jobs off and the rest on. **OK** shows only where the selection differs from the jobs as they are, and **Delete** only while any job is selected; **Delete** asks first ("Delete the 3 selected jobs?"), then deletes them. **Select all** selects every job, and reads **Select none** once all are selected. **Cancel** goes back to the list, whatever was selected. A default job that is deleted comes back when the same job is added again.
* **Run...**: a button per job; a press runs it now, as its schedule would. What the job posts shows it ran; a
  message says so only when it failed, or was running already. The same button pressed again within a minute does
  nothing more, as with every button.
* **Upcoming**: the next runs, in time order.

The typed `/jobs enable`, `disable` and `delete` alone open **Edit**; with a number they act on that job at once.

A button drawn for a list that has since changed acts on nothing: the screen is drawn again as the list is now.

### Add, step by step
Each screen marks its default with `†` (`Sat†`, `09†`) and says _† indicates default_; after the first, **Back** takes a
step back. Times are by the `timezone` setting's clock.

First what the job runs: a report, or a command of `/help` ([below](#a-job-in-english)). A reminder's text, and the stock of `/who` and `/stock`, cannot come from a button, so their screen says how to type
them; `/treemap`, `/holdings` and `/price` run as typed bare. Then how often:

| how often | then | added as, for example |
|---|---|---|
| one-off | the year (this one and the nine after), the month, the day (from today; tomorrow by default), the hour, the minute | once, 20 Mar 2027 at 8:00am |
| hourly | every day or weekdays, the start hour, the start minute, the end time (a run after the start, or the end of the day) | hourly at :05, weekdays 10am–4pm |
| daily | the hour, the minute | daily at 9:00am |
| weekly | the day of the week, the hour, the minute | weekly, Saturdays at 9:00am |
| monthly | the day of the month, the hour, the minute | monthly, the 1st at 9:00am |
| quarterly | the start month (then every 3 months), the day of the month, the hour, the minute | quarterly, 15 Feb/May/Aug/Nov at 9:00am |
| bi-annual | the start month (and 6 months later), the day of the month, the hour, the minute | bi-annual, 1 Mar and 1 Sep at 9:00am |
| annual | the start month, the day of the month (those it has), the hour, the minute | annual, 31 Mar at 9:00am |
| every... | 5, 10, 15, 20 or 30 mins, or 2, 3, 4, 6 or 12 hours, then as hourly; or weekday, then the hour and the minute | every 20 mins, weekdays 10:05am–4:05pm; weekdays at 9:00am |

A span across days (`every 20 mins from mon 9am to sat 3pm`), or a window of hours across midnight, is typed. The last
screen is the whole list, headed "Added", the new job in bold with a 👉 before it, with the list's buttons (**+** adds another). A job added by
`/jobs add` shows the same.

Or type:
```
/jobs                      the chat's jobs, with the buttons above
/jobs upcoming             the next 20 runs; a repeat's runs on one day are one entry
/jobs system               the system jobs
/jobs add                  what a job can run, what each takes, and examples
/jobs add movers weekly
/jobs add movers close weekdays at 4:30pm New York
/jobs add peg top weekly
/jobs add price AAPL MSFT 1y monthly
/jobs add reminder every 31 mar at 8:30am "🥳 Happy EOFY"
/jobs run 2                runs job 2 now, saying so only if it failed; /jobs run alone: a button per job
/jobs enable 2             switches job 2 on; /jobs disable 2 off; /jobs toggle 2 the other way
/jobs delete 36            deletes job 36 (or /jobs remove 36, /jobs del 36)
```

## A job in English
A job is a report and what it takes, then when it runs:
* **Days:** `daily`, `weekdays`, `weekends`, `weekly` (Saturdays), `every saturday` or `saturdays`, `tue-sat`, `monthly`
  (the 1st), `first day of each month`, `on the 15th`, `quarterly` (1 Jan, Apr, Jul and Oct; `quarterly from feb`: Feb,
  May, Aug and Nov), `bi-annual` (1 Jan and 1 Jul; `bi-annual starting mar`: Mar and Sep), `annual` (1 Jan;
  `annual from aug`), `every 31 mar` (each year) or `on 28 oct 2026` (once).
* **Time:** `at 9`, `at 9am`, `at 9:30am` or `at 21:30`. Without one, 9am, or 8:30am for a reminder.
* **Repeating:** `every 20 mins`, `hourly`, `hourly at :01`, `every 2 hours` or any other number, counted from
  midnight. It can take days, and a window of hours (`from 10am to 9pm`, `between 9am and 5pm`) or a span across days
  (`from mon 9am to sat 3pm`).
* **Zone, last:**
  * Times are by the `timezone` setting's clock. A job keeps that zone, so it follows its daylight saving: 8am stays
    8am.
  * Name `UTC` for a time that never moves.
  * Name another zone for its clock: an IANA name (`America/New_York`), a place (`New York`, `Hong Kong`), or a
    common abbreviation (`ET`, `EST`, `PT`, `GMT`, `CET`, `HKT`, `JST`, `AEST`). An abbreviation means the zone with its
    daylight saving: `EST` follows New York's clock in summer too.
  * `/jobs` shows a job by its own zone's clock, with the local time beside it where the clocks differ: `weekdays at
    4:30pm New York (7:30am local, Tue–Sat)`. A zone that keeps another clock is named in every season: a Brisbane job
    seen from Melbourne reads `weekdays at 9:00am Brisbane` in winter, when both clocks agree.

The reports are `trades`, `movers midsession|interday|premarket|close|DAYS`, `earnings`,
`performance [PERIOD]`, `rating`, `milestone`, `shorts`, `podcasts FEED_URL` and `reminder "TEXT"` (`message` works too). A job a chat added
as `price` before the movers report took its name runs as `movers`; `price` in a job added now is the line chart.

A job can also run a command of `/help`, with what it takes, and posts what the command posts when typed in the chat:
`pe [SYMBOL|top|bottom|negative]`, `peg`, `marketcap`, `beta`, `buysell` (the buys and the sells in one message),
`price [SYMBOL…]`, `stock SYMBOL`, and with Sharesight `holdings [PORTFOLIO]`,
`treemap [PORTFOLIO]` and `who SYMBOL`. Without the words in brackets, a job posts what the
command typed bare posts: the first portfolio, or for `price` the biggest holding, with the buttons to pick another.
The commands that change something (`watchlist`, `plan`, `jobs`) are no jobs, and movers, performance, trades, shorts,
earnings, dividends, session and premarket are run by their reports above.

The period of `performance` and `movers` follows how often the job runs: weekly covers 7 days, monthly 30, quarterly
90, bi-annual 180 and annual 365, and a daily `movers` is the day's moves. A number given (`movers 30 weekly`) is used
instead.

A **reminder** posts its text as it is:
* The text comes last, in double quotes (or curly quotes, as phones type them). It runs from the first quote to the
  last, so quotes inside it stay, and it may run over several lines.
* `[text](url)` is a link, a line wrapped in `_underscores_` is in italics, and `{years since YYYY-MM-DD}` becomes the
  years since then (`4th`), for an anniversary.
* A one-off reminder (`on 28 oct 2026`) is deleted after its time has passed, when the list is next shown.

A job that is the same as a default job (the same report, days and times, in a zone with the same clock) switches that
default job on instead of being added, and brings it back where the chat removed it. A chat can add 30 jobs.

## The default jobs
These are as a chat in Melbourne sees them in mid-October. The local times beside New York's, Hong Kong's and London's
move as either side's daylight saving changes.

| # | job | when |
|---|---|---|
| 1 | trades | every 20 mins, Mon 9am – Sat 3pm Sydney |
| 2 | movers midsession AU | weekdays at 1:00pm Sydney |
| 3 | movers midsession US | weekdays at 12:45pm New York (3:45am local, Tue–Sat) |
| 4 | movers premarket US | weekdays at 7:15am New York (10:15pm local) |
| 5 | movers close AU | weekdays at 4:30pm Sydney |
| 6 | movers close HK | weekdays at 4:30pm Hong Kong (7:30pm local) |
| 7 | movers close UK | weekdays at 5:00pm London (3:00am local, Tue–Sat) |
| 8 | movers close US | weekdays at 4:30pm New York (7:30am local, Tue–Sat) |
| 9 | rating | Tue–Sat at 8:30am Sydney |
| 10 | milestone | Tue–Sat at 8:30am Sydney |
| 11 | podcasts Money Cafe | hourly at :01, weekdays 10am–9pm Sydney |
| 12 | podcasts Stocktake | hourly at :01, weekdays 10am–9pm Sydney |
| 13 | earnings | weekly, Sundays at 8:30am Sydney |
| 14 | shorts | weekly, Sundays at 8:30am Sydney |
| 15 | performance | weekly, Sundays at 8:30am Sydney |
| 16 | movers | weekly, Sundays at 8:30am Sydney |
| 17 | performance | monthly, the 2nd at 8:30am Sydney |
| 18 | movers | monthly, the 2nd at 8:30am Sydney |
| 19 | performance | quarterly, 2 Jan/Apr/Jul/Oct at 8:30am Sydney |
| 20 | movers | quarterly, 2 Jan/Apr/Jul/Oct at 8:30am Sydney |
| 21 | performance | bi-annual, 2 Jan and 2 Jul at 8:30am Sydney |
| 22 | movers | bi-annual, 2 Jan and 2 Jul at 8:30am Sydney |
| 23 | performance | annual, 2 Jan at 8:30am Sydney |
| 24 | movers | annual, 2 Jan at 8:30am Sydney |
| 25 | 🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦 | annual, 31 Mar at 8:30am Sydney |
| 26 | 💸 Realise capital gains/losses by EOFY June 30 (AU) | annual, 23 Jun at 8:30am Sydney |
| 27 | 🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰 | annual, 30 Jun at 8:30am Sydney |
| 28 | ✍️ Submit 'Notice of Intent to Claim' … (AU) | annual, 7 Jul at 8:30am Sydney |
| 29 | finbot's birthday | annual, 18 Aug at 8:30am Sydney |
| 30 | 😓 Self-service individual tax returns are due Oct 31 (AU) | annual, 25 Oct at 8:30am Sydney |
| 31 | 😰 Self-service individual tax returns are due today (AU) | annual, 31 Oct at 8:30am Sydney |

* **Market reports run in their market's zone**, so they keep to its session through its daylight saving:
  * pre-market US at 7:15am New York;
  * mid-session about halfway through: 1:00pm Sydney for the ASX, 12:45pm New York for the NYSE;
  * the close 30 minutes after it: 4:30pm Sydney for the ASX, 4:30pm Hong Kong, 5:00pm London and 4:30pm New York.
* **The reminders (from 25 on)** marked (AU) are default jobs only where the `country_code` setting is `AU`. A chat
  adds its own with `/jobs add reminder` ([A job in English](#a-job-in-english)).
* **trades and performance** are default jobs only where Sharesight is set up (see
  [Configuration](configuration.md#sharesight)).

## How jobs run
* A job is kept by its chat's network and id, in `finbot_chat_jobs.json` in the data directory, so switching a network
  between pull and push mode keeps it. Only a chat's switches, the default jobs it removed and the jobs it added are
  stored: the default jobs come from finbot's code, so a change to them reaches every chat, and a new one arrives in
  every chat.
* Each chat keeps its own record of what a report has told it (trades, rating changes, record highs, podcast
  episodes), so the same report scheduled in two chats tells each of them once. A run from **Run now** or `/jobs run`
  is a scheduled run: it posts to the chat and updates the same record. A change counts at once, with no reload.
* A report or command with nothing to show (no new trades, no stock past the threshold, no rating changes) posts
  nothing when a job runs it, on schedule, from **Run now** or by `/jobs run`; typed as a command, or from a keyboard
  button, it says so. One that cannot give what it was asked for (a portfolio that is none, Sharesight not set up)
  says so as a command's reply does, from a job too.
* **A job can only run finbot's own reports and commands.** It names a report from a fixed table in `lib/jobs.py` (or
  posting a message), or a command of the table `/help` is made from (`lib/worker.py`) that changes nothing, with
  arguments its parser has checked, kept as words: never a command line, a script or code. A stored job naming anything
  else is logged and left out, never run.
* **The system jobs**, fixed in `lib/jobs.py` and listed by `/jobs system`, keep the cache full and tidy:
  * `sharesight_warm` every 30 minutes and `yahoo_warm` every 4 hours (see [Caching](caching.md));
  * `cleanup 30` weekly, which deletes cache files older than 30 days.

  A chat cannot add, switch or run them, and a failure of one goes to the log.
* **They run in `bot.py` itself**, each job in a thread of its own, sharing the bot's user, sandbox, environment, data
  directory, caches and connections. Charts are drawn one at a time, and a slow report holds up no chat command. There
  is no cron to set up: remove any old crontab entries that ran finbot's scripts, or their reports come twice.
* **Catch-up:** a run that was due while the bot was down (a restart, a deploy) still fires once, if it was due within
  the last `scheduler_catchup` minutes (default 5). A restart right after a run does not repeat it. A job that is
  switched off does not fire, and does not catch up when it is switched on again.
* **Daylight saving:** a time the clocks skip runs when they reach the first minute after the gap, and a time they
  repeat runs once.
* **Slow and failing jobs:** a job still running when it is next due is skipped. A job still running after 5 minutes is
  reported once and left to finish (a thread cannot be stopped, but every request it makes has a timeout); until then
  it is not started again. A failure is reported to the job's chat, and the bot logs each job as it runs
  (`journalctl -u finbot`).

## From an earlier version
An install from before 16 Oct 2026 starts commit `ff52f2b` once first (`git checkout ff52f2b`, start finbot and wait
for its schedule's line in the log, stop it, then `git checkout main`), as later versions no longer carry its one-off
upgrades: the chats of the old schedule (`finbot_schedule.json`, whose cron jobs are not carried over) and the old home
chats (the retired `telegramChatID`, `slackChannelID` and `discordChannelID`) become chats finbot knows, with the
default jobs, and the home chats get the watchlist, the plans and the reports' records kept for all chats before; the
jobs of the direct messages it knew are switched off. Then delete `finbot_schedule.json`, `finbot_upgrades.json` and
`reminder.json` (its reminders are default jobs now) from the data directory.
