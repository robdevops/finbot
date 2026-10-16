# Scheduling

Each chat has its own jobs: reports and messages that run on a schedule and post to that chat. Anyone in the chat
manages them there, with `/jobs` (or `/job`; as a message, also `.cron`, `.crons` or `.schedule`).

Every chat starts with the [default jobs](#the-default-jobs): switched on in a group or a channel, and switched off in a
direct message with the bot, until the chat switches them. finbot knows a chat from its first command, and knows the
chats of an earlier version's schedule and its home chats. A direct message is a person's chat on Telegram, a `D…`
channel on Slack, and on Discord a message from no server.

## The menu
`/jobs` lists the chat's jobs, numbered, a page at a time: the default jobs, then those added here. Each line shows ✅
(on) or ❌ (off), a `*` if the job has never run, its name with a `†` if it is a default job, and its schedule in
words. The page ends with a key to the marks it shows:
```
1. ✅ trades† · every 20 mins, Mon 9am – Sat 3pm Sydney
3. ✅* price midsession US† · weekdays at 12:45pm New York (3:45am local, Tue–Sat)

* not run yet, † default (no delete, only disable)
```
Under it are buttons, each screen drawn in place of the last, with **Cancel** back to the list:
* **Enable/disable**: a button per job, its number, switch and name (`3 ✅ price midsession US`); a press switches the
  job on or off. **All on** switches every job of the chat on at once, or **All off**, shown when every job is on,
  switches them all off.
* **Delete**: a button per job added here. A default job has no button: switch it off instead.
* **Add**: the report, by name, and how often, then, a screen each, the rest down to the minute:
  * one-off: the date (the next 14 days), the hour, the minute;
  * daily and weekdays: the hour, the minute;
  * weekly: the day of the week, the hour, the minute;
  * monthly, quarterly and bi-annual: the day of the month, the hour, the minute;
  * annual: the month, the day, the hour, the minute;
  * repeating: the interval, then every day or weekdays.

  Each screen marks its default with `†` (`Sat†`, `09†`, `09:00†`) and says `† indicates default`. After the report's,
  each screen also has **Back**, a step back (the hour's has only Back: Discord takes 25 buttons). A message's text
  cannot come from a button, so its screen says how to type one.
* **Run now**: a button per job; a press runs it now, as its schedule would, and says how it went.
* **Upcoming**: the next runs, in time order.

A button drawn for a list that has since changed acts on nothing: the screen is drawn again as the list is now.

Or type:
```
/jobs                      the chat's jobs, with the buttons above
/jobs upcoming             the next 20 runs; a repeat's runs on one day are one entry
/jobs system               the system jobs
/jobs add                  the reports a job can run, what each takes, and examples
/jobs add price weekly
/jobs add price close weekdays at 4:30pm New York
/jobs add message every 31 mar at 8:30am "🥳 Happy EOFY"
/jobs run 2                runs job 2 now; /jobs run alone: the list with a button per job
/jobs toggle 2             switches job 2 on or off
/jobs del 36               deletes job 36, one added here
```

## A job in English
A job is a report and what it takes, then when it runs:
* **Days:** `daily`, `weekdays`, `weekends`, `weekly` (Saturdays), `every saturday` or `saturdays`, `tue-sat`, `monthly`
  (the 1st), `first day of each month`, `on the 15th`, `quarterly` (1 Jan, Apr, Jul and Oct), `bi-annual` (1 Jan and 1
  Jul), `annual` (1 Jan), `every 31 mar` (each year) or `on 28 oct 2026` (once).
* **Time:** `at 9`, `at 9am`, `at 9:30am` or `at 21:30`. Without one, 9am, or 8:30am for a message.
* **Repeating:** `every 20 mins`, `hourly`, `hourly at :01`, `every 2 hours` or any other number, counted from
  midnight. It can take days, and a window of hours (`from 10am to 9pm`, `between 9am and 5pm`) or a span across days
  (`from mon 9am to sat 3pm`).
* **Zone, last:**
  * Times are by the `timezone` preference's clock. A job keeps that zone, so it follows its daylight saving: 8am stays
    8am.
  * Name `UTC` for a time that never moves.
  * Name another zone for its clock: an IANA name (`America/New_York`), a place (`New York`, `Hong Kong`), or a
    common abbreviation (`ET`, `EST`, `PT`, `GMT`, `CET`, `HKT`, `JST`, `AEST`). An abbreviation means the zone with its
    daylight saving: `EST` follows New York's clock in summer too.
  * `/jobs` shows a job by its own zone's clock, with the local time beside it where the clocks differ: `weekdays at
    4:30pm New York (7:30am local, Tue–Sat)`.

The reports are `trades`, `price midsession|interday|premarket|close|DAYS`, `cal earnings|ex-dividend`, `performance
[DAYS]`, `rating`, `milestone`, `shorts`, `podcasts FEED_URL` and `message "TEXT"`.

The period of `performance` and `price` follows how often the job runs: weekly covers 7 days, monthly 30, quarterly
90, bi-annual 180 and annual 365, and a daily `price` is the day's moves. A number given (`price 30 weekly`) is used
instead.

A **message** posts its text as it is:
* The text comes last, in double quotes (or curly quotes, as phones type them). It runs from the first quote to the
  last, so quotes inside it stay, and it may run over several lines.
* `[text](url)` is a link, and a line wrapped in `_underscores_` is in italics.
* A one-off message (`on 28 oct 2026`) is deleted after its time has passed, when the list is next shown.

A job that is the same as a default job (the same report, days and times, in a zone with the same clock) switches that
default job on instead of being added. A chat can add 30 jobs.

## The default jobs
These are as a chat in Melbourne sees them in mid-October. The local times beside New York's, Hong Kong's and London's
move as either side's daylight saving changes.

| # | job | when |
|---|---|---|
| 1 | trades | every 20 mins, Mon 9am – Sat 3pm Sydney |
| 2 | price midsession AU | weekdays at 1:00pm Sydney |
| 3 | price midsession US | weekdays at 12:45pm New York (3:45am local, Tue–Sat) |
| 4 | price premarket US | weekdays at 7:15am New York (10:15pm local) |
| 5 | price close AU | weekdays at 4:30pm Sydney |
| 6 | price close HK | weekdays at 4:30pm Hong Kong (7:30pm local) |
| 7 | price close UK | weekdays at 5:00pm London (3:00am local, Tue–Sat) |
| 8 | price close US | weekdays at 4:30pm New York (7:30am local, Tue–Sat) |
| 9 | rating | Tue–Sat at 8:30am Sydney |
| 10 | milestone | Tue–Sat at 8:30am Sydney |
| 11 | podcasts Money Cafe | hourly at :01, weekdays 10am–9pm Sydney |
| 12 | podcasts Stocktake | hourly at :01, weekdays 10am–9pm Sydney |
| 13 | cal earnings | weekly, Sundays at 8:30am Sydney |
| 14 | cal ex-dividend | weekly, Sundays at 8:30am Sydney |
| 15 | shorts | weekly, Sundays at 8:30am Sydney |
| 16 | performance | weekly, Sundays at 8:30am Sydney |
| 17 | price | weekly, Sundays at 8:30am Sydney |
| 18 | performance | monthly, the 2nd at 8:30am Sydney |
| 19 | price | monthly, the 2nd at 8:30am Sydney |
| 20 | performance | quarterly, 2 Jan/Apr/Jul/Oct at 8:30am Sydney |
| 21 | price | quarterly, 2 Jan/Apr/Jul/Oct at 8:30am Sydney |
| 22 | performance | bi-annual, 2 Jan and 2 Jul at 8:30am Sydney |
| 23 | price | bi-annual, 2 Jan and 2 Jul at 8:30am Sydney |
| 24 | performance | annual, 2 Jan at 8:30am Sydney |
| 25 | price | annual, 2 Jan at 8:30am Sydney |
| 26 | message: 🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦 | annual, 31 Mar at 8:30am Sydney |
| 27 | message: SPCX IPO anniversary | annual, 12 Jun at 8:30am Sydney |
| 28 | message: 💸 Realise capital gains/losses by EOFY June 30 (AU) | annual, 23 Jun at 8:30am Sydney |
| 29 | message: 🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰 | annual, 30 Jun at 8:30am Sydney |
| 30 | message: ✍️ Submit 'Notice of Intent to Claim' … (AU) | annual, 7 Jul at 8:30am Sydney |
| 31 | message: finbot's birthday | annual, 18 Aug at 8:30am Sydney |
| 32 | message: 😓 Self-service individual tax returns are due Oct 31 (AU) | annual, 25 Oct at 8:30am Sydney |
| 33 | message: ubank draw 6/6 … (AU) | once, 28 Oct 2026 at 8:30am Sydney |
| 34 | message: 😰 Self-service individual tax returns are due today (AU) | annual, 31 Oct at 8:30am Sydney |
| 35 | message: SPCX 5th mensiversary … | once, 12 Nov 2026 at 8:30am Sydney |

* **Market reports run in their market's zone**, so they keep to its session through its daylight saving:
  * pre-market US at 7:15am New York;
  * mid-session about halfway through: 1:00pm Sydney for the ASX, 12:45pm New York for the NYSE;
  * the close 30 minutes after it: 4:30pm Sydney for the ASX, 4:30pm Hong Kong, 5:00pm London and 4:30pm New York.
* **The messages marked (AU)** are default jobs only where the `country_code` preference is `AU`.
* **A one-off leaves the list** once its date has passed.

## How jobs run
* A job is kept by its chat's network and id, in `finbot_chat_jobs.json` in the data directory, so switching a network
  between pull and HTTP mode keeps it. Only a chat's switches and the jobs it added are stored: the default jobs come
  from finbot's code, so a change to them reaches every chat.
* Each chat keeps its own record of what a report has told it (trades, rating changes, record highs, podcast
  episodes), so the same report scheduled in two chats tells each of them once. A run from **Run now** or `/jobs run`
  is a scheduled run: it posts to the chat and updates the same record. A change counts at once, with no reload.
* **A job can only run finbot's own reports.** It names an action from a fixed table in `lib/jobs.py` (a report, or
  posting a message), with arguments that report's own parser has checked: never a command, a script or code. A stored
  job naming anything else is logged and left out, never run.
* **The system jobs**, fixed in `lib/jobs.py` and listed by `/jobs system`, keep the cache full and tidy:
  * `sharesight_warm` every 30 minutes and `yahoo_warm` every 8 hours (see [Caching](caching.md));
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

**From an earlier version:**
* The cron jobs in `finbot_schedule.json` are not carried over. Its chats start with the default jobs, and the file
  can be deleted.
* At the first start of this version, every job of each direct message chat finbot knew was switched off, once
  (Discord's direct messages as Discord says). It is recorded in `finbot_upgrades.json`, so it never happens again.
* `reminder.json` is read no more: its reminders are default jobs now. Delete the data directory's copy.
