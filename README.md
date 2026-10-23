# finbot

finbot is a chat bot that follows your [Sharesight](https://www.sharesight.com/au/)
portfolios and each chat's watchlist with Yahoo Finance data. It posts trades, price moves, earnings and ex-dividend
dates, analyst rating changes and more on a schedule, and answers commands with reports and charts.

If you don't have Sharesight, you can still add your holdings manually via the watchlist (`/watchlist add SYMBOL`).

## Features
* Telegram, Slack and Discord (either the push or the pull method, depending on your environment)
* Sharesight trades as they happen, portfolio performance comparisons
* Charts with buttons to change the time period
* Alerts of daily price movements past a threshold, earnings and ex-dividend dates, analyst rating changes, short
  interest, record highs
* Stock lookup and comparisons, rankings by P/E, PEG, market cap or analyst rating
* /command, @bot, schedule, or button driven.

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

## Quick start
Run finbot with Docker or with Python. Both start the same way:

1. `sudo git clone https://github.com/robdevops/finbot /opt/finbot`, then
   `sudo cp /opt/finbot/defaults/finbot.env /etc/finbot.env && sudo chmod 600 /etc/finbot.env`, then set the keys of
   each network you use in it (below)

### With Docker
On a Linux host with Docker:
2. `sudo /opt/finbot/util/docker_setup.sh`
3. `cd /opt/finbot && sudo docker compose up -d --build`
4. `sudo docker compose logs -f`

### With Python
On Linux, macOS or WSL, with Python 3.12 or later and its `venv` module:
2. `cd /opt/finbot && sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt -r requirements-optional.txt`
3. `sudo .venv/bin/python util/check_config.py /etc/finbot.env`
4. `sudo sh -c 'set -a && . /etc/finbot.env && exec .venv/bin/python bot.py'`, which logs to the terminal until Ctrl-C

To run it as a service, under systemd on a Debian host, see [doc/install.md](doc/install.md).

### The chat networks
By default, finbot fetches its updates from each network itself (pull mode), which is what this quick start guide covers.
Alternatively, if you prefer to run an HTTPS gateway (a reverse proxy on a domain with a valid certificate), push mode
subscribes the bot to the updates each network pushes to it.
* **Telegram:** create the bot with [@BotFather](https://telegram.me/BotFather), set `telegramBotToken` in the env file, restart
  finbot ([guide](doc/telegram.md)).
* **Slack:** create the app from the manifest that `util/slack_manifest.py` prints, add an app-level token, set
  `slackBotToken` and `slackAppToken` in the env file, restart finbot ([guide](doc/slack.md)).
* **Discord:** create the application and its bot, turn on its Message Content intent, set `discordBotToken` in the env file,
  restart finbot ([guide](doc/discord.md)).

Then send `/help` in a chat with the bot. Commands work as plain messages too (`.help`), which are quicker to type on a
phone ([Commands](doc/commands.md#supported-commands)). From its first command, each chat has the default scheduled
jobs, which `/jobs` switches on and off, adds to and runs ([Scheduling](doc/scheduling.md)).

## Documentation
* [Commands and reports](doc/commands.md), with screenshots
* [Scheduling](doc/scheduling.md): each chat's jobs, and the reports they can run
* [Configuration](doc/configuration.md): `finbot.env` and `settings.conf`, the data directory, Sharesight
* [Caching](doc/caching.md)
* Installing: [Docker](doc/docker.md) · [Python, or a Debian host with systemd](doc/install.md)
* Networks: [Telegram](doc/telegram.md) · [Slack](doc/slack.md) · [Discord](doc/discord.md)

## Issues
* [Bug reports](https://github.com/robdevops/finbot/issues) welcomed
* PRs are welcome, but not guaranteed to be merged
