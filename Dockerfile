# finbot in a container, on Debian with Debian's own python3 packages (no pip), as on a Debian host. Every optional
# library is in, so the image runs every network in either mode. The startup file and DATA_DIR stay outside the image:
# see compose.yaml and doc/docker.md.
FROM debian:trixie-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends python3 python3-requests python3-croniter python3-dateutil \
		python3-matplotlib python3-numpy python3-waitress python3-websocket python3-discord python3-nacl \
		ca-certificates tzdata \
	&& rm -rf /var/lib/apt/lists/*

# the bot's user: no home, no shell; the code stays root's, so the bot cannot change it
RUN groupadd --system --gid 10001 finbot \
	&& useradd --system --uid 10001 --gid finbot --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin \
		finbot

WORKDIR /opt/finbot
COPY . .
# compiled now, so that a read-only root filesystem costs nothing at start
RUN python3 -m compileall -q bot.py lib util

ARG GIT_COMMIT=unknown
# the image has no .git: the log names the commit it was built from
ENV FINBOT_COMMIT=$GIT_COMMIT PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data HOME=/tmp
USER finbot

# each start: copy the defaults missing from /data, check the startup file, and only then start the bot
CMD ["sh", "-c", "util/sync_defaults.py --apply && util/check_config.py /run/finbot.env && exec ./bot.py"]
