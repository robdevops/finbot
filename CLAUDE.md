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
- To merge: `main` takes only a branch that is up to date with it and green on both CI jobs. Merge `origin/main` into the work branch (a merge commit, never a rebase), run the tests, push, wait for CI on that head, then merge the PR with a merge commit.

## Facts
- Python 3.13.5; tests are offline and need no network (`tests/`). CI runs them on the latest 3.x and 3.13.5, except for
  pull requests that change only README.md, CLAUDE.md, `doc/*.md` or `img/*.png` (install, compile and tests are
  skipped; the allowlist in `.github/workflows/ci.yml` must never include a path a test reads).
- Production runs the Debian system packages (including `python3-croniter`, for the scheduler in `lib/jobs.py`); `requirements.txt` is for pip/uv users and CI.
- A new preference goes in five places: a `Prefs` field and its line in `preference_values` (`lib/config.py`), `defaults/preferences.conf`, the README's preferences table, and `DEFAULTS` plus the key count in `tests/test_config.py`. The tests catch all but the README (no test may read README.md: CI skips the tests for a README-only change).
- If Yahoo and Sharesight are unreachable (the cloud environment's network policy can block them), check behaviour
  against the offline fixtures in `tests/common.py`.
- For a refactor, `util/record_outputs.py` (or `--against COMMIT`) records what every command, button and scheduled
  report posts, for this tree and for HEAD in the same run, and prints the steps that differ (exit status 1 when any
  do). A change to how the tests capture output goes in `tests/common.py`'s `REAL_SENDING`, which the tool puts back to
  record real requests.

## Code map (open the one file you need)
- `bot.py`: WSGI entry (route, verify, parse, then a thread of `lib/worker.py` per message or button press); SIGHUP
  reload, SIGUSR1 cache flush. `lib/inbound.py`: a class per network that posts to the bot (`Telegram`, `Slack`): its
  path, how it proves itself, and its updates as `Message`, `Press` or a `Response` given straight back.
- `lib/worker.py`: `COMMANDS`, a table of `Command(pattern, handler, usage, section, buttons)` (first match wins,
  `.SYMBOL` last), which also makes `.help` and the Telegram command keyboard, kept current in DMs; `Request`
  (`request.reply(lines, chart, buttons)`); the typing notice, which every command gets after half a second.
- `lib/reports/`: what finbot says. Scheduled (each has `lambda_handler()` and `job(argv)`, its schedule-line parser): `price
  performance trades shorts cal rating milestone reminder podcasts cleanup`; the top-level `price.py` and the rest are shims
  that run them. Chat-only (`prepare_*`): `about` (.help .jobs), `history` (.history .compare), `holdings` (.holdings .who .pie
  .watchlist), `profile` (.SYMBOL), `rankings` (.marketcap .pe .fpe .peg .beta .buy .sell).
- `lib/delivery.py`: `Report(lines, chart, buttons)`, the destinations (the chat that asked, or the default chats),
  `deliver(dest, report)`, the one-line error report. `lib/transports.py`: a class per way of posting (`TelegramBot`,
  `SlackBot`, `SlackWebhook`, `DiscordWebhook`): splitting, captions, charts, buttons, edits, typing. `lib/telegram.py`:
  Bot API calls.
- `lib/buttons.py`: `Button` and a chart's period buttons (each transport draws them). `lib/charts.py`: a period
  button press rebuilds its chart.
- `lib/dialects.py`: each network's markup and message sizes. `lib/markets.py`: market tables, flags, ticker translation.
  `lib/formats.py`: names, units, dates, percents in words. `lib/links.py`: stock links. `lib/render.py`: every chart.
- `lib/yahoo.py lib/sharesight.py lib/shortman.py lib/simplywallst.py`: data sources, cached in `DATA_DIR/cache`.
  `sharesight.portfolios(name=None)` gives `Portfolio` objects: `holdings()`, `tickers()`, `performance(days)`,
  `trades(days)`.
- `lib/cache.py`: cache files (any may vanish at any time). `lib/state.py`: state files in `DATA_DIR`, which must last;
  change one with `with state.edit(name, default) as data:`, never load-then-save. `lib/watchlist.py`: the watchlist.
- `lib/config.py`: `config.env` (finbot.env, fixed at start) and `config.prefs` (preferences.conf, a new object on each reload).
  `lib/jobs.py` + `lib/jobrun.py`: the scheduler; each run is a child process.
- `tests/common.py`: `FinbotCase` (offline fixtures). `self.command('.price')` returns what was sent: `('text', lines)` or
  `('photo', size, caption)`.
- Which test file: commands and scheduled reports `test_reports`; failures, bad input, WSGI and Slack events `test_edges`;
  Yahoo/Sharesight parsing, sending, Telegram API `test_providers`; scheduler `test_jobs`; config `test_config`; charts
  `test_charts` (refresh goldens with `UPDATE_GOLDEN=1`); markets, formats, links, cache and state files `test_util`; data dir
  `test_datadir`; chunking, git_version `test_finbot`.

## Conventions
- Read settings as `config.env.<name>` / `config.prefs.<name>` where they are used, never into a default or module constant (a
  reload must be seen); in tests, `self.env(...)` / `self.prefs(...)` change them.
- A report is a list of lines. `service` is a dialect (`lib/dialects.py`), which equals the network's name: markup with
  `service.bold(text)`, `.italic`, `.strike`, `.link(url, text)`, user-written text through `service.escape(text)`, stock links
  through `links.finance_link(symbol, exchange, service)`. Tests pass `TELEGRAM`, `SLACK`, `DISCORD`.
- A command that cannot give what was asked (no such portfolio, no prices) raises `answer.Answer(*lines)`, which the
  chat gets as a plain reply; `yahoo.NoData` is one. Any other exception becomes a one-line ⚠️ error report.
- Every function and method has a docstring, tests included (a test checks): one line where it fits, reworded rather
  than spilling a few words onto a second. Tabs everywhere (`.editorconfig`). New and changed lines stay within 120
  columns, tabs counting 4 (an edit quotes whole lines).
- Log with `print(..., file=sys.stderr)`. systemd discards stdout (`StandardOutput=null`), so the bot and its reports never
  print there (a test checks); only the util/ tools, run by hand, do.
- A chart renderer in `lib/render.py` gets `@_drawn` (the bot draws in one native thread); it must not call another `@_drawn`
  function, or that thread waits on itself.
- A new command: a `Command` in `COMMANDS`, whose usage, section and buttons make its `.help` lines and keyboard
  buttons, and the README command list.

## Saving tokens
- Run the tests quietly: `.venv/bin/python -m unittest discover -s tests -b` prints only failures (about 0.4 KB when green). One
  module: `.venv/bin/python -m unittest tests.test_reports -b`.
- README.md is 38 KB: grep for the section instead of reading it whole. Each network's setup is in its own guide,
  `doc/telegram.md`, `doc/slack.md` and `doc/discord.md`: a change to a network's setup or keys goes there. `doc/yahoo/`
  and `doc/sharesight/` hold large API samples that the tests replay: inspect them with python, don't read them.
