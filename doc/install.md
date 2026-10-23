# Installing on a host

finbot runs wherever Python 3.12 or later does (Linux, macOS, WSL). Production runs Debian's own packages under
systemd, as below.

To run it in a container instead, see [docker.md](docker.md).

## Requirements

* Most features need a Sharesight paid plan and an API key ([configuration.md](configuration.md#sharesight)).

* A Telegram bot, a Slack app or a Discord bot: see its guide, [Telegram](telegram.md), [Slack](slack.md) or
  [Discord](discord.md).

* Python 3.13.5 (3.12 is the minimum), with `requests` and Pillow for the charts. The charts use DejaVu Sans, which most
  Linux systems have (Debian: `fonts-dejavu-core`).

* By default, finbot fetches its updates from your chatbot itself (pull mode). It only makes outgoing connections, so
  nothing has to listen on the internet.

  Push mode is the alternative: your chatbot posts its updates to an HTTPS server you run.

* One more library for the way you receive updates:

  * `waitress`, for push mode
  * `websocket-client`, for Slack or Discord in pull mode
  * `PyNaCl`, for Discord in push mode

  Docker and the venv below install them all. On Debian, install the ones you need.

## Debian

1. Install the packages, and those for the way you receive updates:

   ```
   sudo apt install git python3 python3-requests python3-pil fonts-dejavu-core
   sudo apt install python3-waitress     # push mode
   sudo apt install python3-websocket    # Slack or Discord in pull mode
   sudo apt install python3-nacl         # Discord in push mode
   ```

2. Get the code, in `/opt/finbot`:

   ```
   sudo git clone https://github.com/robdevops/finbot.git /opt/finbot
   ```

3. Make the startup file from its template:

   ```
   sudo cp /opt/finbot/defaults/finbot.env /etc/finbot.env && sudo chmod 600 /etc/finbot.env && sudo chown root:root /etc/finbot.env
   ```

   Then add your chatbot's API key (see its guide above), and Sharesight's:

   ```
   sudoedit /etc/finbot.env
   ```

4. Check it:

   ```
   /opt/finbot/util/check_config.py /etc/finbot.env
   ```

5. Run it under systemd, [below](#daemonize-systemd).

6. Optional, to change settings. Copy the `settings.conf` template, edit it, check it, and reload:

   ```
   sudo /opt/finbot/util/sync_defaults.py --apply
   sudoedit /var/lib/finbot/settings.conf
   sudo /opt/finbot/util/check_config.py /etc/finbot.env
   sudo systemctl reload finbot
   ```

[configuration.md](configuration.md) has every key and setting.

## Anywhere else: a Python venv

For macOS, WSL, or any setup without the Debian packages. You need git and Python 3.12 or later.

```
# Debian or Ubuntu only: sudo apt install python3-venv
git clone https://github.com/robdevops/finbot.git ~/finbot
cd ~/finbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-optional.txt
```

Or with [uv](https://docs.astral.sh/uv/), which also fetches the exact Python from `.python-version`:

```
uv venv && uv pip install -r requirements.txt -r requirements-optional.txt
```

Make the startup file as in step 3 above (anywhere: `~/finbot.env`, say), check it, and start the bot:

```
.venv/bin/python util/check_config.py ~/finbot.env
(set -a && . ~/finbot.env && exec .venv/bin/python bot.py)
```

To run the venv under systemd, put the Git checkout in `/opt/finbot`, make the venv there, and set `ExecStart=` to
`/opt/finbot/.venv/bin/python /opt/finbot/bot.py`.

## Daemonize (systemd)

`finbot.service` keeps `bot.py` running in the background and starts it on boot.

It expects the Git checkout in `/opt/finbot` and the startup file at `/etc/finbot.env`, as above. It needs no editing.

```
sudo cp -v /opt/finbot/finbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable finbot --now
```

finbot's data (its state and settings) is in `/var/lib/finbot`.

After a change, `sudo systemctl reload finbot` re-reads `settings.conf`. A change to `finbot.env` needs
`sudo systemctl restart finbot`.

The log:

```
journalctl -fu finbot
```

### Hardening (recommended)

An optional file adds a sandbox and resource limits to the unit. finbot can then only write to `/var/lib/finbot`, and
gets no privileges.

```
sudo mkdir -p /etc/systemd/system/finbot.service.d
sudo cp -v /opt/finbot/finbot.service.d/hardening.conf /etc/systemd/system/finbot.service.d/
sudo systemctl daemon-reload && sudo systemctl restart finbot
```

It needs the Git checkout outside `/home`, as in `/opt/finbot`.

`systemd-analyze security finbot` scores the result: about 1.3 (OK) with the file, about 8 (exposed) without.

The memory and task limits are starting values. After a few days, check
`systemctl show finbot -p MemoryPeak -p TasksCurrent` and adjust them.

If the sandbox ever gets in the way, delete the file and restart finbot.
