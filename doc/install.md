# Installing on a host

finbot runs wherever Python 3.12 or later does (Linux, macOS, WSL); production runs Debian's own packages under
systemd, as below. To run it in a container instead, see [docker.md](docker.md).

## Requirements
* Most features need a Sharesight paid plan, preferably with automatic trade imports, and an API key
  ([configuration.md](configuration.md#sharesight)).
* A Telegram bot, a Slack app or a Discord bot: see the network's guide, [Telegram](telegram.md), [Slack](slack.md) or
  [Discord](discord.md).
* By default, finbot fetches its updates from each network itself (pull mode: Telegram's long polling, Slack's Socket
  Mode, Discord's gateway API). It only makes outgoing connections, so nothing has to listen on the internet.
  Alternatively, if you prefer to run an HTTPS gateway (a web server with a domain name and a matching certificate),
  HTTP mode subscribes the bot to push updates: each network posts its updates to the gateway, which passes them to
  the bot (each guide's _HTTP mode_).
* Python 3.13.5 (the version in `.python-version`; 3.12 is the minimum), and these modules, pinned to versions with
  3.13 support in `requirements.txt`: python-dateutil, requests, matplotlib and numpy.
* For a network in HTTP mode (its webhook URL set), also waitress; for Slack in Socket Mode, websocket-client; for
  Discord's gateway API, discord.py, and for its HTTP mode, PyNaCl. These are in `requirements-optional.txt`, each
  imported only by the mode that needs it. Docker and a Python venv install them all, Docker in its image and a venv
  from that file, so every mode works without choosing; on a Debian host, install the packages of the modes you use.

## Debian
1. The packages, and those of the modes you use:
   ```
   sudo apt install git python3 python3-requests python3-dateutil python3-matplotlib python3-numpy
   sudo apt install python3-waitress     # any network in HTTP mode
   sudo apt install python3-websocket    # Slack's Socket Mode
   sudo apt install python3-discord      # Discord's gateway API
   sudo apt install python3-nacl         # Discord's HTTP mode
   ```
2. The code:
   ```
   git clone https://github.com/robdevops/finbot.git ~/finbot
   ```
3. The startup file, from its template; then set each network's keys from its guide, and Sharesight's:
   ```
   sudo cp ~/finbot/defaults/finbot.env /opt/finbot.env && sudo chmod 600 /opt/finbot.env
   sudoedit /opt/finbot.env
   ```
4. Check it: `~/finbot/util/check_config.py /opt/finbot.env`
5. Run it under systemd, below. The first start makes the data directory (`var/` in the checkout, or
   `/var/lib/finbot` with `DynamicUser=`); each chat then has the default scheduled jobs, which `/jobs` changes
   ([scheduling.md](scheduling.md)).

[configuration.md](configuration.md) has every key and preference.

## Anywhere else: a Python venv
On Linux, macOS or WSL, with git and Python 3.12 or later (on Debian and Ubuntu, also `python3-venv`):
```
git clone https://github.com/robdevops/finbot.git ~/finbot
cd ~/finbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-optional.txt
```
Or, with [uv](https://docs.astral.sh/uv/), which also fetches the exact Python from `.python-version`:
```
uv venv && uv pip install -r requirements.txt -r requirements-optional.txt
```
`requirements-optional.txt` installs the library of every mode; it can be cut down to the modes you use. Then make the
startup file as in step 3 above (anywhere: `~/finbot.env`, say), check it, and start the bot with its values in its
environment:
```
.venv/bin/python util/check_config.py ~/finbot.env
(set -a && . ~/finbot.env && exec .venv/bin/python bot.py)
```
Under systemd (below), `ExecStart=` runs the venv's Python: `/home/<you>/finbot/.venv/bin/python
/home/<you>/finbot/bot.py`.

## Daemonize (systemd)
`finbot.service` can take care of keeping `bot.py` running in the background and starting it on boot. Copy
`finbot.service` to `/etc/systemd/system/`, edit it to set the `User`, `ExecStart` and the path of
[`finbot.env`](configuration.md#finbotenv) (`EnvironmentFile=`, and the `ExecStartPre=` check), then enable and start
it. `systemctl reload finbot` re-reads `preferences.conf` without a restart; a change to `finbot.env` needs
`systemctl restart finbot`:
```
sudo cp -v ~/finbot/finbot.service /etc/systemd/system/
sudo sed -i 's/CHANGEME/YOUR LINUX USERNAME/' /etc/systemd/system/finbot.service
sudo systemctl daemon-reload
sudo systemctl enable finbot --now
```
The bot's log:
```
journalctl -fu finbot
```
