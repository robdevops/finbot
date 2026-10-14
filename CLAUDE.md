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
- Python 3.13.5; tests are offline and need no network (`tests/`). CI runs them on the latest 3.x and 3.13.5, except for pull requests that change only README.md, CLAUDE.md or `img/*.png` (install, compile and tests are skipped; the allowlist in `.github/workflows/ci.yml` must never include a path a test reads).
- Production runs the Debian system packages (including `python3-croniter`, for the scheduler in `lib/jobs.py`); `requirements.txt` is for pip/uv users and CI.
- A new preference goes in five places: `PREFERENCE_KEYS` and `preference_values` (`lib/config.py`), `defaults/preferences.conf`, the README's preferences table, and `DEFAULTS` plus the key count in `tests/test_config.py`. The tests catch all but the README (no test may read README.md: CI skips the tests for a README-only change).
- If Yahoo and Sharesight are unreachable (the cloud environment's network policy can block them), check behaviour against the offline fixtures in `tests/common.py`. For a refactor, compare old and new output: load `git show HEAD:<file>` as a module beside the new one and diff what both produce for the same inputs.

## Code map (open the one file you need)
- `bot.py`: WSGI entry; routes /telegram and /slack, authenticates, hands each message to `lib/worker.py` in a thread; SIGHUP reload, SIGUSR1
  cache flush.
- `lib/worker.py`: `COMMANDS` (regex → `on_*` handler, first match wins, `.SYMBOL` last); `Request`; the typing indicator.
- `lib/reports.py`: `prepare_*` builders for the chat-only reports (lines, plus a chart spec).
- `price.py performance.py trades.py shorts.py cal.py rating.py milestone.py reminder.py podcasts.py cleanup.py`: reports that also
  run on a schedule; each has `lambda_handler()` and `job(argv)` (its schedule-line argument parser).
- `lib/webhook.py`: sending (chunking, photos, Slack upload), markup, escaping, error reporting. `lib/telegram.py`: Bot API calls.
- `lib/charts.py`: Telegram period buttons and the rebuild behind them. `lib/util.py`: formatting, links, market tables, cache and
  state files, all matplotlib rendering.
- `lib/yahoo.py lib/sharesight.py lib/shortman.py lib/simplywallst.py`: data sources, cached in `DATA_DIR/cache`.
- `lib/config.py`: finbot.env + preferences.conf → `config_*` names (star-imported), reload. `lib/jobs.py` + `lib/jobrun.py`: the
  scheduler; each run is a child process.
- `tests/common.py`: `FinbotCase` (offline fixtures). `self.command('.price')` returns what was sent: `('text', lines)` or
  `('photo', size, caption)`.
- Which test file: commands and scheduled reports `test_reports`; failures, bad input, WSGI and Slack events `test_edges`;
  Yahoo/Sharesight parsing, sending, Telegram API `test_providers`; scheduler `test_jobs`; config `test_config`; charts
  `test_charts` (refresh goldens with `UPDATE_GOLDEN=1`); pure helpers `test_util`; data dir `test_datadir`; chunking, git_version
  `test_finbot`.

## Conventions
- A report is a list of lines. Markup through `webhook.bold/italic(text, service)`, user-written text through
  `webhook.escape(text, service)`, links through `util.link`/`util.finance_link`.
- Tabs in code; in tests match the file. New and changed lines stay under 120 characters (an edit quotes whole lines).
- stdout is discarded under systemd (`StandardOutput=null`): anything worth logging goes to stderr.
- A new command: `COMMANDS`, `prepare_help`, the README command list, and `command_keyboard` if it gets a button.

## Saving tokens
- Run the tests quietly: `.venv/bin/python -m unittest discover -s tests -b` prints only failures (about 0.4 KB when green). One
  module: `.venv/bin/python -m unittest tests.test_reports -b`.
- README.md is 38 KB: grep for the section instead of reading it whole. `doc/` holds large API samples that the tests replay:
  inspect them with python, don't read them.
