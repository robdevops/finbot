---
name: merge-when-green
description: Open a pull request for the current branch if needed, wait for CI to pass, then merge it with a merge commit and reset the working branch to main. This is the default for finished work in this repo: once tests pass, merge without waiting to be asked. Also use when the user says "merge", "pr", "pr and merge", or "merge when green". Never merges while CI is red or still running.
---

# Merge when green

**Default (the owner's standing instruction):** when a PR for this branch exists and every required check has passed, merge it. Do not wait for a separate "merge" message. Opening a PR for finished, committed work is likewise expected; do not leave work sitting on the branch. The "Never" rules below still apply: red or missing checks, conflicts, or unresolved human review requests mean stop and tell the user.

Repo: `robdevops/finbot`. Base branch: `main`. Work branch: the one named in the session instructions (`claude/...`).
Use the GitHub MCP tools (`mcp__github__*`; load them with ToolSearch if they are not in the tool list). There is no `gh` CLI.

## 1. Make sure there is a PR
1. `git status` and `git log origin/main..HEAD`. If there is uncommitted work, commit it first (attribution trailer from the session reminder) and push with `git push -u origin <branch>`.
2. `list_pull_requests` for `head: robdevops:<branch>`, `state: open`. If one exists, use it. If not, check `git log origin/main..HEAD` is non-empty ("No commits between main and branch" means a previous PR already merged: reset the branch to `origin/main` and tell the user, do not open an empty PR).
3. Otherwise `create_pull_request` (base `main`). Body: short bullet list of what changed and why, then the attribution lines from the session reminder (`🤖 Generated with [Claude Code](https://claude.com/claude-code)` and the session URL). Check for a PR template first (`.github/pull_request_template.md`); this repo has none today.

## 2. Wait for CI
1. `pull_request_read` with `get_check_runs` (and `get_status` / `get` for `mergeable_state`) on the PR head.
2. Required: every check run `completed` with conclusion `success` (neutral/skipped are fine). The CI workflow has two matrix legs, `test (3.x)` and `test (3.13.5)`; both must pass.
3. No checks reported yet: wait a minute and look again. If still none after a few minutes, the workflow did not trigger. Say so and ask before merging; do not assume green.
4. Checks still running: call `subscribe_pr_activity` for the PR and end the turn. Do not poll with `sleep`. Merge when the CI event says green. As a backup, schedule one `send_later` check-in about an hour out.

## 3. If CI is red
Do not merge. Read the failing job (`get_job_logs`), reproduce locally (`.venv/bin/python -m unittest discover -s tests`), fix the cause, and push. Rules:
- Never skip, disable or loosen a test (including the golden-image tolerance) just to get green. Refresh golden images only when the visual change was intended (`UPDATE_GOLDEN=1 python -m unittest tests.test_charts`).
- If the failure is not this PR's (reproduces on `main`, or an upstream outage), say what is failing and why, and ask the user whether to merge anyway.
- Re-check CI after each push; repeat until green.

## 4. Merge
1. Confirm: PR open, not draft, `mergeable` true / no conflicts, all checks green. On a conflict, merge `origin/main` into the branch, resolve, run the tests, push, and go back to step 2.
2. `merge_pull_request` with `merge_method: merge` (merge commit, never squash or rebase unless the user asks).
3. Reset the work branch so follow-up work starts clean:
   `git fetch origin main && git checkout -B <branch> origin/main && git push -q --force-with-lease -u origin <branch>`
   (this also clears the stop-hook's "unpushed commits" warning).
4. Unsubscribe from PR events if subscribed (`unsubscribe_pr_activity`).

## 5. Report
One short message: PR link, merge commit short hash, which checks passed, and anything the user must do next (for example "restart the service to pick up the change"). Use markdown links for PRs (`[robdevops/finbot#NN](url)`), never bare `#NN`.

## Never
- Merge with failing or missing checks without the user's explicit say-so.
- Push to `main` directly, force-push anything but the work branch, or rewrite history on someone else's branch.
- Merge a PR that has unresolved review requests from a human without telling the user.
