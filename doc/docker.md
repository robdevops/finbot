# Docker

finbot runs in a container as it runs on a Debian host: the image is `debian:trixie-slim` with Debian's own `python3-*`
packages, every optional library included, so it runs every network in either mode. The image holds only the code.
The configuration lives on the host, outside the image (the startup file in `/etc`, the data beside the Git checkout), so a rebuild or an update never touches it.

## Quick start

1. `git clone https://github.com/robdevops/finbot /opt/finbot`
2. `sudo /opt/finbot/util/docker_setup.sh`
3. Set your chatbot's API key in `/etc/finbot.env` (`telegramBotToken` for Telegram; see the
   [Telegram](telegram.md), [Slack](slack.md) and [Discord](discord.md) guides).
4. `cd /opt/finbot && sudo docker compose up -d --build`
5. `journalctl CONTAINER_NAME=finbot -f`

## The layout on the host

| Path | What | In the container |
|---|---|---|
| `/opt/finbot` | the Git checkout, with `Dockerfile` and `compose.yaml` | the image's `/opt/finbot`, copied at build |
| `/etc/finbot.env` | the startup file: the tokens, and the mode of each network | the environment, and `/run/finbot.env`, read-only, for the check |
| `/opt/finbot-data` | `DATA_DIR`: `settings.conf`, each chat's jobs and watchlist, the records, the cache | `/data` |

`compose.yaml` reads the startup file at `/etc/finbot.env` and finds the data dir beside the Git checkout
(`../finbot-data`): clone it elsewhere and the data dir moves with it. The startup file stays out of the image because
it holds the secrets, and the data dir because it must outlast every container..

## What `util/docker_setup.sh` does

Run it once, as root; it is safe to run again. It:
1. runs `util/sync_defaults.py --create --apply --dest /opt/finbot-data`, which makes the data dir (mode 750) and copies
   the shipped defaults into it: `settings.conf` and the data files. It never replaces a file you
   have changed. The script needs only the standard library, so any `python3` on the host runs it.
2. gives the data dir to the container's user: `chown -R 10001:10001 /opt/finbot-data`.
3. copies `defaults/finbot.env` to `/etc/finbot.env` if there is none, owned by `root:10001`, mode 640: root and the
   container can read it, nobody else.

By hand, that is:
```
sudo python3 /opt/finbot/util/sync_defaults.py --create --apply --dest /opt/finbot-data
sudo chown -R 10001:10001 /opt/finbot-data
sudo cp /opt/finbot/defaults/finbot.env /etc/finbot.env
sudo chown root:10001 /etc/finbot.env && sudo chmod 640 /etc/finbot.env
```

The startup file is `KEY=value` lines, as for systemd; write the values without quotes.

## Build and start

```
cd /opt/finbot && sudo GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
```
`GIT_COMMIT` is optional: it names the commit in the log's first line (`Starting finbot 0123456`), as the image has no
`.git` to read it from.

Each start of the container, in order:
1. `util/sync_defaults.py --apply` copies into `/data` any default it lacks, such as a data file added by an update;
2. `util/check_config.py /run/finbot.env` checks the startup file and `settings.conf`. A mistake stops the start
   here, and the log says which key and why;
3. the bot starts.

## Logs

The log goes to the host's journal:
```
journalctl CONTAINER_NAME=finbot -f
```
On a host without journald, set `FINBOT_LOG_DRIVER=json-file` (in the environment of `docker compose`, or in a `.env`
file beside `compose.yaml`), and read it with `sudo docker compose logs -f`.

## Reload, flush, update

```
sudo docker compose kill -s HUP finbot     # re-read settings.conf
sudo docker compose kill -s USR1 finbot    # flush the cache, and fill it again
sudo docker compose exec finbot util/flush.py --after 24h    # flush the files of the last day (see caching.md)
cd /opt/finbot && sudo git pull && sudo GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build
```
A change to `/etc/finbot.env` needs a restart: `sudo docker compose up -d`.

## Push mode

In pull mode, the default, finbot fetches its updates and needs no port. In push mode (a network's webhook URL set),
it listens inside the container on port 5000 of every interface (`ip: 0.0.0.0` in `compose.yaml`). Publish the port
on the host's loopback only, by uncommenting `ports` in `compose.yaml`:
```
    ports:
      - 127.0.0.1:5000:5000
```
and put your reverse proxy in front of it, as each network's guide describes for a host install.

## Hardening

`compose.yaml` takes away everything the bot does not need:

| Setting | Why |
|---|---|
| `user: "10001:10001"` | the bot runs as a user of its own, never root; the code belongs to root, so the bot cannot change it |
| `read_only: true`, `tmpfs: /tmp` | nothing outside `/data` and `/tmp` can be written; the code is compiled at build, so nothing needs to be |
| `cap_drop: [ALL]` | no Linux capabilities: the bot binds no port below 1024 and changes no owner |
| `security_opt: no-new-privileges:true` | nothing in the container can gain privileges, setuid binaries included |
| `pids_limit: 256` | a runaway can start only so many threads |
| `mem_limit: 400m`, `memswap_limit: 400m` | 400 MB, with no swap on top: the bot starts at about 40 MB and stays under 50 MB drawing charts |
| `init: true` | a minimal init as process 1, which passes `SIGHUP` and `SIGUSR1` on to the bot and reaps children |
| no `ports` | nothing listens on the host unless you publish a port |

To give it more memory, raise both `mem_limit` and `memswap_limit`.

## Moving a host install into Docker

```
sudo systemctl disable --now finbot
sudo cp -a /var/lib/finbot/. /opt/finbot-data/    # or /opt/finbot/var/. for the default DATA_DIR
sudo chown -R 10001:10001 /opt/finbot-data
```
then `util/docker_setup.sh` (it keeps your files) and start as above.

## Troubleshooting

* **The container stops at once and keeps restarting:** the log says why. `ERROR config: ... unknown key ...` is a
  mistake in `/etc/finbot.env` or `settings.conf`; fix it and `sudo docker compose up -d`.
* **`PermissionError` on `/data`:** the data dir is not the container user's: `sudo chown -R 10001:10001
  /opt/finbot-data`.
* **`/data does not exist: --create makes it`:** the data dir is not mounted: `compose.yaml` mounts
  `../finbot-data`; run `util/docker_setup.sh` to make it.
* **No log in the journal:** the host has no journald; use `FINBOT_LOG_DRIVER=json-file` (see [Logs](#logs)).
