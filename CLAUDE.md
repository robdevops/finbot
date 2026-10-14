# finbot: how to work in this repo

## Iterating (auto mode)
The owner chats back and forth; every message that asks for a change gets a change.
1. Make the change, run the tests (`.venv/bin/python -m unittest discover -s tests`), fix what breaks.
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
- A new preference goes in five places: `PREFERENCE_KEYS` and `preference_values` (`lib/config.py`), `defaults/preferences.conf`, the README's preferences table and its key count, and `DEFAULTS` plus the key count in `tests/test_config.py`. The tests catch all but the README.
- If Yahoo and Sharesight are unreachable (the cloud environment's network policy can block them), check behaviour against the offline fixtures in `tests/common.py`. For a refactor, compare old and new output: load `git show HEAD:<file>` as a module beside the new one and diff what both produce for the same inputs.
