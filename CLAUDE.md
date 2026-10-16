# finbot: how to work in this repo

## Iterating (auto mode)
The owner chats back and forth; every message that asks for a change gets a change.
1. Make the change, run the tests (`.venv/bin/python -m unittest discover -s tests -b`), fix what breaks.
2. Commit (with the attribution trailer) and **push to the work branch** (`git push -u origin <branch>`). Do this every iteration, so the branch always holds the latest working state. If a PR from the work branch is open, update its title and description in the same iteration (see below).
3. Reply briefly: what changed, test result, and the pushed commit's short hash.

## The work branch is the dev branch
The work branch named in the session instructions (`claude/...`) is the persistent dev branch. The owner's test environment pulls it and restarts the service, so:
- **Never rewrite the work branch's history, and never reset the branch after a merge**: no reset to `main`, no rebase, no amend of pushed commits, no force-push. A force-push breaks `git pull` on the test environment. After a merge, leave the branch as it is.
- If the owner wants a fixed name such as `dev`, they will say so; only push to another branch with their explicit permission.

## Pull requests from the work branch
An open PR takes in every commit pushed to its branch, so a PR opened for one small change can merge far more under its old title (#35 was titled as a CI tweak and merged 14 review fixes). The merge commit on `main` keeps that title for good.
- Before each push, check for an open PR from the work branch. If there is one, update its title and description so they cover every commit it now holds, not only the change it was opened for.
- Never make such a PR mergeable (resolve its conflict, merge `main` into it, enable auto-merge) while its title or description is out of date.
- To merge: `main` takes only a branch that is up to date with it and green on every CI job. Merge `origin/main` into the work branch (a merge commit, never a rebase), run the tests, push, wait for CI on that head, then merge the PR with a merge commit.

## Facts
- Python 3.13.5; tests are offline and need no network (`tests/`). CI runs them on the latest 3.x and 3.13.5, and
  its `docker` job builds the image (`Dockerfile`, Debian's packages), imports every module in it and starts it as
  `compose.yaml` does; all except for pull requests that change only README.md, CLAUDE.md, `doc/*.md` or `img/*.png`
  (install, compile, tests and the build are skipped; the allowlist in `.github/workflows/ci.yml` must never include a
  path a test reads). This cloud environment cannot reach `deb.debian.org`, so only CI builds the image.
- Production runs the Debian system packages; `requirements.txt` is for pip/uv users and CI. The libraries in `requirements-optional.txt` are each imported only
  inside the code of the mode that needs it, never at module load (a test starts finbot with them all blocked).
- A new preference goes in three places: a `Prefs` field with its default (`lib/config.py`; its type says how it is
  read), `defaults/preferences.conf` (commented out at its default, `#key=value`: the template sets nothing, and finbot
  never reads it), and the preferences table of `doc/configuration.md`. The tests catch a key
  missing from the template or a default that differs, but not the docs (no test may read README.md or `doc/*.md`: CI
  skips the tests for a change to the docs alone).
- If Yahoo and Sharesight are unreachable (the cloud environment's network policy can block them), check behaviour
  against the offline fixtures in `tests/common.py`.
- For a refactor, `util/record_outputs.py` (or `--against COMMIT`) records what every command, button and scheduled
  report posts, for this tree and for HEAD in the same run, and prints the steps that differ (exit status 1 when any
  do). A change to how the tests capture output goes in `tests/common.py`'s `REAL_SENDING`, which the tool puts back to
  record real requests.

## Code map (open the one file you need)
- `bot.py`, which puts the networks together: the WSGI entry (`route()` by path to a network's `WEBHOOK`, verify,
  parse, then a thread of `lib/worker.py` per message or button press), served by waitress only when some network's
  webhook is set; the pull listeners that finbot.env asks for (`listeners()`), a thread each; each network registered
  at start (Telegram's webhook set or deleted, and its menu; Discord's slash commands); plain threads, no gevent;
  SIGHUP reload and SIGUSR1 cache flush, each in a thread. `bot.take(network, update)` takes an update however it
  arrived, and is the one place a press is acknowledged (the worker never does). An answer the network must have
  before any reply (Discord's deferred interaction) carries the work in its `then`: started once the HTTP answer is
  sent (`bot.Sent`) or, over the gateway, posted to its callback.
- Each network in three modules, flat in `lib/`. `<network>_common.py`, what both ways in share: the API calls (`call`,
  `try_call`; Discord's wait out its rate limits), the reader of its updates (`READER`: a `Message`, a `Press`, a
  `Suggest` or a `Response` given straight back; `acknowledge` where the network waits for that: Telegram's toast,
  Discord's interaction answer) and its bot (`TelegramBot`, `SlackBot`, `DiscordBot`). `<network>_webhook.py`, the HTTP
  mode: the path and how a request proves itself (`WEBHOOK`). The pull mode's persistent client, handing its updates
  to `bot.take`: `telegram_longpolling.py` (`TelegramPoll`: getUpdates), `slack_websocket.py` (`SlackSocket`: Socket
  Mode, over websocket-client), `discord_websocket.py` (`DiscordGateway`: discord.py's raw events). Telegram's
  `register()`, in each mode's module, sets the webhook or deletes it; Discord's slash commands are registered at start
  in both modes (`discord_common.register`, from `worker.slash_commands()`). What no network owns: `lib/inbound.py`
  (`Message`, `Press`, `Suggest`, `Response`; the `Network` and `Webhook` bases), `lib/pull.py` (the `Listener` base,
  which waits longer after each failure in a row: `backoff`), `lib/transports.py` (the `Transport` base, below).
- `lib/worker.py`: `COMMANDS`, a table of `Command(names, handler, usage, section, buttons, percent, period,
  keywords, job)`, which also makes `.help`, the commands a job may run (`job_commands()`, each a `CommandJob`: every
  one but those that change something, `job=False`, and those a report runs, `REPORTED`), the Telegram command keyboard, kept current in DMs, and `slash_commands()`, which
  every network gets (Telegram's menu, Slack's manifest from `util/slack_manifest.py`, Discord's registered commands);
  `suggest(chat, text)` completes a slash command's arguments as they are typed (Discord's autocomplete), from the
  cache alone. `read()` finds the
  command by its whole name (any other first word that may be a ticker is `.SYMBOL`) and `read_args()` its `Args`: a
  percent, a period and a keyword from either end, the words between; a handler raises `Usage` for arguments it cannot
  take, and gets a ticker with `ticker(args)`. `Request` (`request.reply(lines, chart, buttons)`); each command gets
  the typing notice while it works. `process_request(message)` and `process_callback(press)` take inbound's objects.
- `lib/reports/`: what finbot says. Scheduled (each has `run(dest=None, **kwargs)`, which posts to the chat that asked
  or the job's chat, and with no dest raises: there are no home chats; `job(argv)`, its arguments' parser; and
  `ARGUMENTS`, what `.jobs add` lists):
  `price performance trades shorts cal rating milestone message podcasts cleanup sharesight_warm yahoo_warm`. trades,
  rating, milestone and podcasts keep a record per chat of what they told it (`state.load_for`, `state.edit_for`),
  added to only by a scheduled run (`delivery.interactive(dest)` is false).
  Chat-only (`prepare_*`): `about` (.help, and the .jobs menu's screens: `jobs_screen`, `add_screen`, `next_screen`), `history` (.history .compare), `holdings` (.holdings .who .pie .treemap
  .watchlist), `profile` (.SYMBOL), `rankings` (.marketcap .pe .fpe .peg .beta .buy .sell).
- `lib/delivery.py`: `Report(lines, chart, buttons)`, the destinations (the chat that asked, or a chat by its key with
  `chat(key)`, as its network's bot), `deliver(dest, report)` (a chart refused goes again with its heading alone as the
  caption, the lines as text after it), the one-line error report (to its chat; one that belongs to no chat only
  logged). A caption is cut to fit as the network counts it (`Dialect.visible`: Telegram's in UTF-16 code units).
  `lib/transports.py`: `Transport`, the base of each network's bot, every one taking charts and buttons: splitting,
  captions, charts, buttons, edits, and the typing notice (`start_typing`: after half a second; Slack's ⏳ on the
  message), which `text()` and `chart()` stop before posting. `DiscordBot`: a slash command's first message replaces
  its "thinking…" through its `interaction` (application id/token), and a pressed message is edited through the
  press's.
- `lib/buttons.py`: `Button`, a chart's period buttons (`keyboard`), the `.jobs` menu's (`menu_button`, a
  `MenuPress`; older lists' `j|`/`e|` buttons still parse), what a pressed button's data asks for (`parse`), and the
  toast it gets at once (`toast`); each transport draws them, and Slack and Discord take a button's data as its id, so
  it is unique in a message.
  `lib/charts.py`: a chart with period buttons, built by its kind's builder (`build`) for the command's first view
  (`worker.chart_reply`) and for each press.
- `lib/dialects.py`: each network's markup and message sizes. `lib/markets.py`: one table by market code (flag,
  currency, Yahoo suffix, Google code; Sharesight's codes, so TSE is Toronto), and `code(name)` for any name an exchange
  goes by. `lib/formats.py`: names, units, dates, percents in words. `lib/links.py`: stock links. `lib/render.py`:
  every chart, `Chart` specs and `draw()`.
- `lib/yahoo.py lib/sharesight.py lib/shortman.py lib/simplywallst.py`: data sources. Yahoo's and Sharesight's answers
  are cached in `DATA_DIR/cache` as sent, not parsed, so a parser fix needs no flush (`cache.cached`); `util/flush.py`
  deletes cache files by when they were written (`--before`/`--after TIME`, or `all`), never the state.
  `yahoo.symbol(typed)` is Yahoo's symbol for a ticker as written, tried on the local exchange (`exchange_suffix`)
  when Yahoo does not know it bare: every ticker a chat gives goes through it. `sharesight.portfolios(name=None)` gives
  `Portfolio` objects: `holdings()`, `tickers()`, `gain(days)` (the portfolio's), `trades(days)`. Sharesight is
  optional (`sharesight.configured()`): without its keys `tickers()` is empty, so reports cover the watchlist alone, and
  `portfolios()` raises `NotSetUp`, an answer.
- `lib/log.py`: the log, by level (`error warn info debug`), as the `log_level` preference lets in, and `cut()`, which
  keeps a line that can run long (a request's, a chat message's) on one line, within the `log_width` preference;
  bot.py's `WholeLines` writes each line whole, whichever threads log at once. `lib/cache.py`: cache files (any may vanish at any time). `lib/state.py`: state files in `DATA_DIR`, which must last;
  change one with `with state.edit(name, default) as data:`, never load-then-save; a file of one record per chat with
  `state.load_for(chat, name, default)` and `state.edit_for`. A chat's key is its network and id (`Transport.key`,
  `telegram:-1001234`), the same in both modes. `lib/watchlist.py`: each chat's watchlist (`tickers(chat)`), and
  `with_holdings(chat)`, the stocks a report in that chat covers; a report takes the chat from its destination.
- `lib/config.py`: `config.env` (finbot.env, fixed at start) and `config.prefs` (preferences.conf, a new object on
  each reload). `lib/jobs.py`: the scheduler: each chat's jobs, the default ones and those it added (`JOBS_FILE`, by
  chat key: the defaults it switched off and those it removed, `'deleted'`, the jobs it added; a direct message's
  defaults start off, `'defaults': 'off'` with those switched on, and it is marked `'dm'`; `see` makes a chat known at
  its first command, a DM as `inbound.Message.dm` or `is_dm` says; `add`, `delete`, `delete_all`, `switch`,
  `toggle`, `switch_all`, `run`, `upcoming`, which `.jobs` calls through `jobs.current`; `parse_add` reads `.jobs add`),
  and the fixed `SYSTEM` jobs, its shared state under one lock. A job is an action of `actions()`: a report module of
  `ACTIONS` (`message` among them) or a command of `.help` (`command_actions()`), with the arguments its `job()` takes
  as words, never a command line; one stored that is anything else is logged and left out. Each job runs in the bot's process, in a thread (`run_in_process`), reported once if still
  running after `JOB_TIMEOUT` and left to finish (every request goes through `net`, with its timeouts: a test checks);
  each job's next run is worked out once and again only after it runs, so a tick costs little. `lib/when.py`: a job's
  `Schedule` (days, a time or a repeat, or a span across days, in a zone): `parse()` of the English a chat types,
  `describe()`, `next_after()` through daylight saving; `cycle()` the months of a quarterly or bi-annual one from its
  start month. `lib/catalog.py`: the default jobs (`ITEMS`), each with its
  name and schedule; the period of performance and price follows how often it runs (`period_args`).
  `lib/migrate.py`: once, on an upgrade, the old home chats (the retired telegramChatID, slackChannelID and
  discordChannelID, which it alone reads, from the environment) become chats finbot knows, and the watchlist, the
  plans and the reports' shared records become theirs; one-off upgrades run at one start only (`once`, recorded in
  `UPGRADES`): `dm_jobs_off` switched off the jobs of the DMs known before DMs started with them off, and `mark_dms`
  marked them `'dm'`, for the log's count of group chats and DMs.
- `tests/common.py`: `FinbotCase` (offline fixtures). `self.command('.price')` returns what was sent:
  `('text', lines)` or `('photo', size, caption)`. `wsgi_environ(path, body, **headers)` is a request for `bot.main`.
  `ProviderCase` runs the real parsers on the answers saved under `doc/` (`sample`), as `Resp` and `serve` return
  them; `temp_dir(self)` is a directory removed after the test, `bare_environment()` the environment without finbot's
  settings.
- Which test file: commands and scheduled reports `test_reports`; failures, bad input, secrets in logs, signals
  `test_edges`; webhook requests, Slack events, slash commands and signatures, and the Slack manifest `test_inbound`;
  the pull modes `test_pull`; the Discord bot `test_discord`; Yahoo `test_yahoo`; Sharesight `test_sharesight`; posting
  to each network `test_sending`; Telegram's webhook and command menu `test_telegram_api`; job actions and arguments,
  the default jobs, the messages and the migration `test_schedule`; the scheduler, and `.jobs` and its menu in a chat
  `test_scheduler`; config `test_config`; charts `test_charts` (refresh goldens with `UPDATE_GOLDEN=1`); markets,
  formats, links, buttons, schedules (`lib/when.py`), cache and state files `test_util`; data dir `test_datadir`; log levels, request lines and whole lines `test_edges`; chunking, git_version, and the docstring, stdout, line-width and no-pandas
  checks `test_finbot`.

## Conventions
- Read settings as `config.env.<name>` / `config.prefs.<name>` where they are used, never into a default or module
  constant (a reload must be seen); in tests, `self.env(...)` / `self.prefs(...)` change them.
- A report is a list of lines. `service` is a dialect (`lib/dialects.py`), which equals the network's name: markup
  with `service.bold(text)`, `.italic`, `.strike`, `.link(url, text)`, user-written text through
  `service.escape(text)`, stock links through `links.finance_link(symbol, exchange, service)`. Tests pass `TELEGRAM`,
  `SLACK`, `DISCORD`.
- A command that cannot give what was asked (no such portfolio, no prices) raises `answer.Answer(*lines)`, which the
  chat gets as a plain reply; `yahoo.NoData` is one. Any other exception becomes a one-line ⚠️ error report.
- Every function and method has a docstring, tests included (a test checks): one line where it fits, reworded rather
  than spilling a few words onto a second. Tabs everywhere (`.editorconfig`). Every line stays within 120 columns,
  tabs counting 4 (an edit quotes whole lines); a test checks all but README.md, CLAUDE.md and `doc/`.
- Log with `lib/log.py`, at a level, with print()'s arguments: `log.error` (failed and lost: a message not sent),
  `log.warn` (failed and got over: a retry, a fallback, a refused request), `log.info` (what finbot does: a message
  sent, a job run; `net` logs each request it sends), `log.debug` (cache misses, hits and writes; the routine of a
  press: the press, its acknowledgement and the edit in place, sent with `logged='debug'`, and a success answered to
  a network). The
  `log_level` preference sets what reaches the log; `lib/config.py` prints its own errors (it loads before
  preferences exist). Everything goes to stderr: systemd discards stdout (`StandardOutput=null`), so the bot and its reports
  never print there (a test checks); only the util/ tools, run by hand, do.
- A report gives its chart as a `render.Chart` spec, not a drawing: `deliver()` draws it only for a chat that takes
  charts, through `render.draw()`, which caches the image by the spec's hash (and the drawing code's).
- A chart renderer in `lib/render.py` takes its `Chart` and is listed in `RENDERERS` by kind; it gets `@_drawn`, which
  draws one chart at a time (matplotlib's caches are shared by every thread).
- A new command: a `Command` in `COMMANDS` (its names, and what its arguments may hold), whose usage, section and
  buttons make its `.help` lines and keyboard buttons, and the command list of `doc/commands.md`. A job may run every
  command of `.help`, so one that changes anything takes `job=False`.

## Saving tokens
- Run the tests quietly: `.venv/bin/python -m unittest discover -s tests -b` prints only failures (about 0.4 KB when
  green). One module: `.venv/bin/python -m unittest tests.test_reports -b`.
- README.md is short: what finbot is, a quick start, and links. The rest is in `doc/`, a file per topic: `commands.md`
  (the commands and reports, 16 KB: grep for the section instead of reading it whole), `configuration.md` (the keys
  and preferences), `scheduling.md`, `caching.md`, `install.md` (a Debian host), `docker.md`, and a guide per network,
  `telegram.md`, `slack.md` and `discord.md`: a change to a network's setup or keys goes in its guide. `doc/yahoo/` and
  `doc/sharesight/` hold large API samples that the tests replay: inspect them with python, don't read them.
