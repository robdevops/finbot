# Installing on a host

finbot runs on any Linux host with Python 3.12 or later; production runs Debian's own packages under systemd, as
below. To run it in a container instead, see [docker.md](docker.md).

## Requirements
* Most features need a Sharesight paid plan, preferably with automatic trade imports, and an API key
  ([configuration.md](configuration.md#sharesight)).
* A Telegram bot, a Slack app or a Discord bot: see the network's guide, [Telegram](telegram.md), [Slack](slack.md) or
  [Discord](discord.md).
* No server: finbot fetches its updates from each network itself (pull mode: Telegram's long polling, Slack's Socket
  Mode, Discord's gateway). In HTTP mode instead, a network posts them to a public web server with a domain name and a
  matching certificate, which proxies them to the bot (each guide's _HTTP mode_).
* Python 3.13.5 (the version in `.python-version`; 3.12 is the minimum), and these modules, pinned to versions with
  3.13 support in `requirements.txt`: croniter, python-dateutil, requests, matplotlib and numpy.
* For a network in HTTP mode (its webhook URL set), also waitress; for Slack in Socket Mode, websocket-client; for
  Discord's gateway, discord.py, and for its HTTP mode, PyNaCl. These are in `requirements-optional.txt`, each imported
  only by the mode that needs it.

## Debian
1. The packages, and those of the modes you use:
   ```
   sudo apt install git python3 python3-requests python3-croniter python3-dateutil python3-matplotlib python3-numpy
   sudo apt install python3-waitress     # any network in HTTP mode
   sudo apt install python3-websocket    # Slack's Socket Mode
   sudo apt install python3-discord      # Discord's gateway
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
   `/var/lib/finbot` with `DynamicUser=`) and gives each home chat its first jobs ([scheduling.md](scheduling.md)).

[configuration.md](configuration.md) has every key and preference.

## Other distributions: pip or uv
```
sudo $(which apt dnf yum) install git python3-pip
git clone https://github.com/robdevops/finbot.git ~/finbot
cd ~/finbot
pip3 install -r requirements.txt -r requirements-optional.txt
```
Or, with [uv](https://docs.astral.sh/uv/), which also fetches the exact Python from `.python-version`:
```
uv venv && uv pip install -r requirements.txt -r requirements-optional.txt
```
`requirements-optional.txt` can be left out, or cut down to the modes you use.

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
