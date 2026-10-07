#!/bin/bash
# Claude Code on the web: provision the same Python as production (see .python-version) and the project dependencies.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
	exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
PYTHON_VERSION="$(tr -d '[:space:]' < .python-version)"

# uv downloads the exact CPython build if the machine does not have it
uv python install "$PYTHON_VERSION"

# (re)create .venv only when it is missing or on a different Python
if [ ! -x .venv/bin/python ] || [ "$(.venv/bin/python -c 'import platform; print(platform.python_version())')" != "$PYTHON_VERSION" ]; then
	rm -rf .venv
	uv venv --python "$PYTHON_VERSION" .venv
fi

# idempotent: a no-op when everything is already installed
uv pip install --python .venv/bin/python -r requirements.txt

# make `python` / `python3` resolve to the venv for the rest of the session
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
	{
		echo "export VIRTUAL_ENV=\"$PWD/.venv\""
		echo "export PATH=\"$PWD/.venv/bin:\$PATH\""
	} >> "$CLAUDE_ENV_FILE"
fi

.venv/bin/python --version
