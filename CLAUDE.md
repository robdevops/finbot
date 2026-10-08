# finbot: how to work in this repo

## Iterating (auto mode)
The owner chats back and forth; every message that asks for a change gets a change.
1. Make the change, run the tests (`.venv/bin/python -m unittest discover -s tests`), fix what breaks.
2. Commit (with the attribution trailer) and **push to the work branch** (`git push -u origin <branch>`). Do this every iteration, so the branch always holds the latest working state.
3. Reply briefly: what changed, test result, and the pushed commit's short hash.

## The work branch is the dev branch
The work branch named in the session instructions (`claude/...`) is the persistent dev branch. The owner's test environment pulls it and restarts the service, so:
- **Never rewrite its history**: no reset to `main`, no rebase, no amend of pushed commits, no force-push. A force-push breaks `git pull` on the test environment.
- If the owner wants a fixed name such as `dev`, they will say so; only push to another branch with their explicit permission.

## Facts
- Python 3.13.5; tests are offline and need no network (`tests/`). CI runs them on the latest 3.x and 3.13.5.
- Production runs the Debian system packages; `requirements.txt` is for pip/uv users and CI.
