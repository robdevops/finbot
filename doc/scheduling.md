# Scheduling

Each chat has its own jobs: reports that run on a schedule and post to that chat. Anyone in the chat manages them there,
with `/jobs` (or `/job`; as a message, also `.cron`, `.crons` or `.schedule`). A new chat has none until it adds
them:
```
/jobs                      this chat's jobs, numbered, each with its next run; then the system jobs
/jobs add                  the reports a job can run, and what each takes
/jobs add 29 21 * * Mon-Fri price interday
/jobs run                  the list, with a button per job that runs it now; /jobs run 2 runs job 2
/jobs toggle               the list, with a button per job that switches it on or off; /jobs toggle 2
/jobs del 2                deletes job 2
```

A job is a time in crontab's syntax, then one or more reports with their arguments:
* **The time** is five fields (minute, hour, day of month, month, day of week; `*/20`, `Mon-Fri`, ranges and lists
  work) or an `@macro` such as `@daily`. A time that cannot be or never comes (minute 61, 30 February) is refused,
  saying why.
* **Times are in UTC**, which keeps the ASX's jobs and NYSE's each within an hour of their local times all year. To
  follow one market's clocks exactly, a job names its zone first, as crontab writes it:
  `/jobs add CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession`. `/jobs` shows each next run in UTC and in
  the `timezone` preference.
* **The reports** are `trades`, `price midsession|interday|premarket|close|DAYS`, `cal earnings|ex-dividend`,
  `performance [DAYS]`, `rating`, `milestone`, `shorts`, `reminder` and `podcasts FEED_URL`. Several, separated by `;`,
  run one after another: `/jobs add 28 21 * * Sat cal earnings; cal ex-dividend; price 7; performance 7; rating`.
  Quote an argument that holds spaces or a `;` (a feed URL, say).
* A chat has 30 jobs at most.

A job posts to its own chat, whichever way that chat's updates reach finbot: the jobs are kept by network and chat id
(`finbot_schedule.json` in the data directory), so switching a network between pull and HTTP mode keeps them. Each chat
also keeps its own record of what a report has told it (trades, rating changes, record highs, podcast episodes), so the
same report scheduled in two chats tells each of them once. A run from `/jobs run` is a scheduled run: it posts to the
chat and updates the same record. A change counts at once, with no reload.

**The system jobs**, fixed in `lib/jobs.py` and listed by `/jobs` under _System_, keep the cache full and tidy:
`sharesight_warm` every 30 minutes, `yahoo_warm` every 8 hours (see [Caching](caching.md)), and `cleanup 30` weekly,
which deletes cache files older than 30 days. A chat cannot add, switch or run them, and a failure of one goes to the
log.

**From `schedule.cron`**, where the schedule used to be: on an upgrade from before jobs per chat, the first start
gives each chat that the retired `telegramChatID`, `slackChannelID` or `discordChannelID` still names in `finbot.env`
the jobs of the data directory's `schedule.cron`, else of the shipped `defaults/schedule.cron`, each in the zone it
ran in (the server's), without the system jobs. It copies the reports' records to those chats too, so that nothing old
is told again. It logs what it did, and any line it left out, and reads the file no more: delete the data directory's
copy afterwards, and the retired keys.

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
