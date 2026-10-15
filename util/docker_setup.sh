#!/bin/sh
# The host side of finbot's Docker install, set up once, as root; safe to run again (doc/docker.md). Beside the
# checkout, where compose.yaml looks for them: ../finbot-data (DATA_DIR) made, the defaults copied in, owned by the
# container's user (10001); and ../finbot.env from the template if there is none, readable by root and the container's
# group only. Cloned to /opt/finbot, they are /opt/finbot-data and /opt/finbot.env.
set -eu

repo=$(cd "$(dirname "$0")/.." && pwd)
parent=$(dirname "$repo")
data="$parent/finbot-data"
startup="$parent/finbot.env"

if [ "$(id -u)" -ne 0 ]; then
	echo "docker_setup: run it as root: sudo $0" >&2
	exit 1
fi

python3 "$repo/util/sync_defaults.py" --create --apply --dest "$data"
chown -R 10001:10001 "$data"

if [ ! -e "$startup" ]; then
	cp "$repo/defaults/finbot.env" "$startup"
	echo "docker_setup: $startup written from the template"
fi
chown root:10001 "$startup"
chmod 640 "$startup"

cat <<NEXT

Next:
  1. Set telegramBotToken and telegramChatID (or another network's keys) in $startup
  2. cd $repo && sudo docker compose up -d --build
  3. journalctl CONTAINER_NAME=finbot -f
NEXT
