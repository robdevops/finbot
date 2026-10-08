---
name: merge-when-green
description: The ship pipeline, started manually by the owner. Open a pull request for the work branch if there is none, wait for CI, merge with a merge commit when green, then sync the branch (fast-forward from main, no history rewrite) and report. Use when the user sends "pr", "merge", "pr and merge", "ship", or "merge when green". Any one of those starts the whole pipeline; never ask for a second command. Never merges while CI is red or missing.
---

# Ship: PR, CI, merge

**Trigger:** the owner sends `pr`, `merge`, `pr and merge`, `ship`, or invokes this skill. Any one of them runs everything below to the end. Without a trigger, do not open a PR or merge; just commit and push to the work branch (see `CLAUDE.md`).

**Once triggered:** open the PR if needed, wait for CI, merge when every required check has passed. No further confirmation is needed. The "Never" rules below still apply: red or missing checks, conflicts, or unresolved human review requests mean stop and tell the user.

Repo: `robdevops/finbot`. Base branch: `main`. Work branch: the one named in the session instructions (`claude/...`).
Use the GitHub MCP tools (`mcp__github__*`; load them with ToolSearch if they are not in the tool list). There is no `gh` CLI.

## 1. Make sure there is a PR
1. `git status` and `git log origin/main..HEAD`. If there is uncommitted work, commit it first (attribution trailer from the session reminder) and push with `git push -u origin <branch>`.
2. `list_pull_requests` for `head: robdevops:<branch>`, `state: open`. If one exists, use it. If not, check `git log origin/main..HEAD` is non-empty ("No commits between main and branch" means everything already shipped: sync the branch with `git merge origin/main`, tell the user, and do not open an empty PR).
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
3. Sync the work branch. It is the persistent dev branch the owner's test environment pulls, so never reset, rebase or force-push it:
   `git fetch origin main && git merge origin/main && git push -u origin <branch>`
   (after a merge-commit merge this is a fast-forward or a trivial merge; it also clears the stop-hook's "unpushed commits" warning).
4. Unsubscribe from PR events if subscribed (`unsubscribe_pr_activity`).

## 5. Report
One short message: PR link, merge commit short hash, which checks passed, and anything the user must do next (for example "restart the service to pick up the change"). Use markdown links for PRs (`[robdevops/finbot#NN](url)`), never bare `#NN`.

## Never
- Merge with failing or missing checks without the user's explicit say-so.
- Push to `main` directly, or rewrite history on any branch (no reset, rebase, amend or force-push on the work branch either).
- Merge a PR that has unresolved review requests from a human without telling the user.
