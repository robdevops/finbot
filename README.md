# finbot

finbot is a chat bot for Telegram, Slack and Discord that follows your [Sharesight](https://www.sharesight.com/au/)
portfolios and each chat's watchlist with Yahoo Finance data. It posts trades, price moves, earnings and ex-dividend
dates, analyst rating changes and more on a schedule, and answers commands with reports and charts.

## Features
* Telegram, Slack and Discord, with no server to host: finbot fetches its updates itself (or, in HTTP mode, a network
  posts them to your HTTPS server)
* Sharesight trades as they happen, portfolio performance and holdings
* Price moves past a threshold, earnings and ex-dividend dates, analyst rating changes, short interest, record highs
* Stock lookup, price history charts and comparisons, rankings by P/E, PEG, market cap or analyst rating
* Commands as messages (`.price`) or slash commands (`/price`), completed as they are typed where the network allows
* Each chat's own scheduled jobs and watchlist, managed in the chat (`.jobs`, `.watchlist`)
* Docker or a Debian host, hardened either way

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

## Quick start
With Docker:
1. `git clone https://github.com/robdevops/finbot /opt/finbot`
2. `sudo /opt/finbot/util/docker_setup.sh`
3. Set the keys of each network you use in `/opt/finbot.env` (below)
4. `cd /opt/finbot && sudo docker compose up -d --build`
5. `journalctl CONTAINER_NAME=finbot -f`

To install on a Debian host with systemd instead, see [doc/install.md](doc/install.md).

Each network needs a bot of its own, and finbot fetches its updates with no server (its pull mode):
* **Telegram:** create the bot with [@BotFather](https://telegram.me/BotFather), set `telegramBotToken` and
  `telegramChatID`, restart finbot ([guide](doc/telegram.md)).
* **Slack:** create the app from the manifest that `util/slack_manifest.py` prints, add an app-level token, set
  `slackBotToken`, `slackAppToken` and `slackChannelID`, restart finbot ([guide](doc/slack.md)).
* **Discord:** create the application and its bot, turn on its Message Content intent, set `discordBotToken` and
  `discordChannelID`, restart finbot ([guide](doc/discord.md)).

Then send `.help` in the chat.

## Documentation
* [Commands and reports](doc/commands.md), with screenshots
* [Scheduling](doc/scheduling.md): each chat's jobs, and the reports they can run
* [Configuration](doc/configuration.md): `finbot.env` and `preferences.conf`, the data directory, Sharesight
* [Caching](doc/caching.md)
* Installing: [Docker](doc/docker.md) · [a Debian host with systemd](doc/install.md)
* Networks: [Telegram](doc/telegram.md) · [Slack](doc/slack.md) · [Discord](doc/discord.md)

## Suggestions
* Is my code doing something the hard way?
* Is something important missing from the docs?

Log an [issue](https://github.com/robdevops/finbot/issues)!
