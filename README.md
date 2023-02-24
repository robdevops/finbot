# finbot

## Description

### Features
* Discord, Slack and Telegram support
* Sharesight Trade notifications
* Yahoo Finance data for Sharesight holdings:
  * Intraday and premarket price movements over a defined threshold
  * Earnings date reminders
  * Ex-dividend date warnings
  * Highly shorted stock warnings (AU, US)
* Interactive chat commands (Slack & Telegram):
  * Stock lookup with price/valuation related stats and warnings
  * Company profiles
  * Shared watch list
  * List current Sharesight holdings

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

### Supported commands
Where _symbol_ is any Yahoo Finance symbol:
```
.symbol
.bio symbol
.dividend [days|symbol]
.earnings [days|symbol]
.holdings
.marketcap symbol
.price [percent|symbol]
.premarket [percent|symbol]
.shorts [percent|symbol]
.trades [days|portfolio]
.watchlist [add|del symbol]
@botname symbol
@botname bio symbol
@botname dividend [days|symbol]
@botname earnings [days|symbol]
@botname holdings
@botname marketcap symbol
@botname price [percent|symbol]
@botname premarket [percent|symbol]
@botname shorts [percent|symbol]
@botname trades [days|portfolio]
@botname watchlist [add|del symbol]
```

Trade notifications are peformed by polling the Sharesight trades API from a cron job, and notifying your configured chat networks of any new trades. Thus, it works best if your trades are auto-imported into Sharesight through its broker integrations, and if your environment has persistent storage so that the bot can keep track of known trade ids between runs.

The other various reports can also run from cron (e.g. daily or weekly), or on demand through the interactive bot. They query the Yahoo Finance API for stock data based on current holdings across your Sharesight portfolios, your friends' Sharesight portfolios, plus a custom watch list. Depending on how they're triggered, they will either report to all configured chat networks, or reply to the chat which triggered them.

The interactive bot component requires you to host a web service on a domain with a trusted certificate. It subscribes to push updates from native Slack apps / Telegram bots, and reacts to certain regex seen in chat. It provides:
* Stock lookup (financials and company profile)
* Group maintainable watch list, picked up by the various reports
* Listing of portfolios and their current holdings
* Running the other stock reports on demand

## Reports

### Stock lookup
![Screenshot showing stock info on Slack](img/stockinfo.png?raw=true "Screenshot showing stock info on Slack")

The stock lookup returns various stats relevant to a stock's valuation, growth and risk factors.

#### Emoji legend
* The colored circle next to the symbol at the top indicates the current market state:
    * 🔴 market closed
    * 🟠 pre/post-market
    * 🟢 normal trading
* The emoji grid indicates the directional change in the company earnings and revenue for each reporting period. A red arrow indicates the absolute earnings was negative:
    * 🔼 earnings/revenue increased from the previous period
    * 🔽 earnings/revenue decreased from the previous period
    * 🔺 earnings increased from the previous period but remained negative
    * 🔻 earnings decreased from the previous period and was negative
    * ▪ earnings/revenue matched the previous period
* Using the example screenshot above, the company reported:
    * 🔼🔼🔼 revenue increased in all of the past three quarters
    * 🔺🔻🔻 In the past three quarters, earnings initially increased, then decreased for two quarters, and was negative in every quarter
    * 🔼🔼🔼 revenue increased in all of the past three years
    * 🔻🔺🔻 In the past three years, earnings decreased, increased, then decreased, and was negative for all three years

This report can only be run through the interactive bot. Example usage:
```
.AAPL
```
```
@botname AAPL
```

### Stock bio
![Screenshot showing stock bio on Slack](img/bio.png?raw=true "Screenshot showing stock bio on Slack")

This report can only be run through the interactive bot. Example usage:
```
.bio AAPL
```
```
@botname bio AAPL
```

### Trades
![trade update in Slack](img/trades.png?raw=true "Trade update in Slack")

`trades.py` sends recent Sharesight trades to your configured chat services.
By default, this report searches Sharesight for trades from the current day only. You can override this with `past_days` in the .env file, or by providing a number as argument when triggered through the chat bot.

Without persistent storage, it is recommended to leave `past_days = 0` to avoid duplicate trade notifications. In this case, the cron that triggers the report must do so exactly once per day, after market close.

With persistent storage, it is recommended to set `past_days = 30`. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to set the cron frequency to 20 minutes.

```
past_days = 30
```

Interactive trigger:
```
.trades [days]
```
```
@botname trades [days]
```

You can also specify a portfolio name to get today's trades for just that portfolio:
```
.trades [portfolio]
```
```
@botname trades [portfolio]
```


### Price alerts
![price alert in Slack](img/price.png?raw=true "Price alert in Slack")

`prices.py` sends intraday and premarket price alerts for Sharesight holdings if the movement is over a percentage threshold. This data is sourced from Yahoo! Finance. The default threshold is 10% but you can change it by setting `price_percent` in the .env file, or by providing a number as argument when triggered through the chat bot. Decimal fractions are accepted.

Config example:
```
price_percent = 9.4
```

Cron trigger:
```
./price.py [ignoreclosed|intraday|premarket]
```
The mode must be passed as an execution argument.
* If `ignoreclosed` is passed, it only reports for markets currently in session. This is intended to run from Cron to provide mid-session alerts for big price movements of your holdings. For example, it could be run twice per day 12 hours apart, to capture markets in different timezones.
* If `intraday` is passed, it reports current price against the previous market close.
* If `premarket` is passed, it only reports on pre/post market price movements.


Interactive trigger:
```
.price [percent]
```
```
@botname price [percent]
```

Interactive trigger (pre-market):
```
.premarket [percent]
```
```
@botname premarket [percent]
```

### Events calendar
![earnings message in Slack](img/earnings.png?raw=true "Earnings message in Slack")

`cal.py` sends upcoming earnings and ex-dividend date alerts. The data is sourced from Yahoo! Finance. It reports on events up to `future_days` into the future. This is set in the .env file for triggering the report from Cron, or can be specified as an argument when triggered through the chat bot.

**Earnings:** when a company releases its quarterly earnings report, the stock price may undergo a signficant positive or negative movement, depending on whether the company beat or missed market expectations. You may wish to hold off buying more of this stock until after its earnings report, unless you think the stock will beat market expectations.

**Ex-dividend:** When a stock goes ex-dividend, the share price [typically drops](https://www.investopedia.com/articles/stocks/07/ex_dividend.asp) by the amount of the dividend paid. If you buy right before the ex-dividend date, you can expect an unrealised capital loss, plus a tax obligation for the dividend. Thus, you may wish to wait for the ex-dividend date before buying more of this stock.
```
future_days = 7
```

Cron execution:
```
./cal.py [earnings|ex-dividend]
```

Interactive trigger (earnings):
```
.earnings [days]
```
```
@botname earnings [days]
```

Interactive trigger (ex-dividend):
```
.dividend [days]
```
```
@botname dividend [days]
```

### Highly shorted stock warnings
![short warnings in Slack](img/shorts.png?raw=true "Short warnings in Slack")

`shorts.py` sends short interest warnings. The data is sourced from Yahoo Finance and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. This can be specified in the .env file for running the report from Cron, or as an argument when triggered through the chat bot.

**Explanation:** A high short ratio indicates a stock is exposed to high risks, such as potential banktrupcy. It may also incentivise negative news articles which harm the stock price. If the market is wrong, however, risk tolerant investors may receive windfall gains. This report is intended to alert you to an above-average risk, and prompt you to investigate this stock more closely.
```
shorts_percent = 15
```

Interactive trigger:
```
.shorts [percent]
```
```
@botname shorts [percent]
```

### Watchlist
![Shared watchlist in Slack](img/watchlist.png?raw=true "Shared watchlist in Slack")

Tracks additional securities which are not in your Sharesight holdings.

It is stored in `var/cache/finbot_watchlist.json` by default. It uses JSON list format with Yahoo symbols. Example:
```
["2454.TW", "3217.TWO", "ASO.AX", "STEM"]
```

When run interactively, the watchlist is dynamic and can be edited by members of a chat group. In this case, there is no need to create/edit the file manually.

Interactive trigger:
```
.watchlist
```
```
.watchlist [add|del] AAPL
```
```
@botname watchlist
```
```
@botname watchlist [add|del] AAPL
```

## Dependencies
* Sharesight paid plan, preferably with automatic trade imports, and an API key
* Discord/Slack webhooks / Telegram bot user
* The interactive bot requires a web server with domain name and matching certificate, plus the _gevent_ Python module
* Python 3.8.10+
* Python modules:
```
datetime python-dotenv requests gevent
```

## Installation (Linux)
```
sudo $(which apt dnf yum) install git
```
```
git clone https://github.com/robdevops/finbot.git ~/finbot
```
```
cd ~/finbot
```
```
pip3 install -r requirements.txt
```

## Setup
Configuration is set by the .env file in the main directory. Example:
```
vi ~/finbot/.env
```

### Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to the .env file. Example:
```
sharesight_code = '01d692d4de7mockupfc64bc2e2f01d692d4de72986ea808f6e99813f'
sharesight_client_id = '01d692d4de7mockupfc64bc2e2f01d692d4de72986ea808f6e99813f'
sharesight_client_secret = '01d692d4de7mockupfc64bc2e2f01d692d4de72986ea808f6e99813f'
```

### Discord
Discord support is currently only for trade notifications and scheduled reports.
The Discord webhook can be provisioned under _Server Settings > Integrations > Webhooks_.
We use Discord's Slack compatibility by appending `/slack` to the Discord webhook in the .env file. Example:
```
discord_webhook = 'https://discord.com/api/webhooks/1009998000000000000/aaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbb/slack'
```

### Slack
A Slack webhook can be provisioned by creating a new app from scratch at https://api.slack.com/apps/ then navigating to _Incoming Webhooks_. Once the link is generated, add it to the .env file. Example:
```
slack_webhook = 'https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA'
```
The webhook is only used for the trade notifications and scheduled reports. The interactive bot requires further configuration of this Slack app (see below).

### Telegram
* Set up the bot by messaging [BotFather](https://telegram.me/BotFather).
* Add your bot to a group or channel.
* For security, run `/setjoingroups` and set to `Disabled`
* Optionally, make the bot a group admin (for interactive features).
* In the .env file, set `telegramBotToken` to the token BotFather gave you.
* In the .env file, set `telegramChatID` to the chat group or channel id.
   * For channels and supergroups, `telegramChatID` should be negative and 13 characters. Prepend `-100` if necessary.
   * Be aware a group id can change if you edit group settings and it becomes a "supergroup". Currently, the bot does not automatically handle this.
* Example .env entry:
```
telegramBotToken = '0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA'
telegramChatID = -1001000000000
```

### Portfolios
Portfolios are auto-discovered, including other people's portfolios which are shared to you. To exclude specific portfolios, add their IDs to `exclude_portfolios` in the .env file:
```
exclude_portfolios = "100003 100004"
```

Alternatively, you can include only specific portfolios:
```
include_portfolios = "100001 100002"
```

### Caching
Many objects are cached for just under one day by default. Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache = True
cache_seconds = 82800
```

## Scheduling example
Recommended for a machine set to UTC:
```
# Every 20 minutes on weekdays
*/20 * * * Mon-Fri ~/finbot/trades.py > /dev/null

# Mid-session
00 01 * * Mon-Fri ~/finbot/price.py ignoreclosed > /dev/null # AU
15 17 * * Mon-Fri ~/finbot/price.py ignoreclosed > /dev/null # US

# Daily
30  21 * * * ~/finbot/reminder.py > /dev/null

# Daily on weekdays
29  21 * * Mon-Fri ~/finbot/price.py intraday > /dev/null
10  11 * * Mon-Fri ~/finbot/price.py premarket > /dev/null

# Weekly
28  21 * * Fri { cd ~/finbot/; ./cal.py earnings; ./cal.py ex-dividend;} > /dev/null

# Monthly
27  21 1 * * ~/finbot/shorts.py > /dev/null
```
The above can be installed with:
```
(crontab -l ; cat ~/finbot/crontab.txt)| crontab -
```

## Interactive bot setup
The backend `bot.py` needs a frontend https server on a valid domain name with a valid x509 certifcate.
It defaults to listening on http://127.0.0.1:5000/, which can be changed with `ip` and `port` in the .env file.

Example frontend https server config (nginx):
```
server {
	listen 8443 ssl;
	deny all;

	server_name         www.example.com;
	ssl_certificate     /etc/letsencrypt/live/www.example.com/fullchain.pem;
	ssl_certificate_key /etc/letsencrypt/live/www.example.com/privkey.pem;
	ssl_protocols       TLSv1 TLSv1.1 TLSv1.2;
	ssl_ciphers         HIGH:!aNULL:!MD5;

	location /slack {
		proxy_pass http://127.0.0.1:5000/slack;
                include /etc/nginx/aws_subnets;
                deny all;
	}
	location /telegram {
		proxy_pass http://127.0.0.1:5000/telegram;
		include /etc/nginx/telegram_subnets;
		deny all;
	}
}
```
Note: The utils folder contains scripts to generate `/etc/nginx/aws_subnets` and `/etc/nginx/telegram_subnets`. They can be run once, or placed in `/etc/cron.daily/`.

### Integrating the interactive bot with chat networks

#### Telegram
* Message BotFather to create a bot user.
  * Set .env file `telegramBotToken` to the token given by BotFather.
  * Add your Telegram bot user to a group
    * Give the bot group admin access so it can read the group chat.
    * For security, message BotFather and disable `/setjoingroups`.
* Set .env `telegramOutgoingWebhook` to your web server (e.g. https://www.example.com:8443/telegram).
* Set `telegramOutgoingToken` to a password of your choosing. Telegram will use this to authenticate with finbot.
With these options set, your bot will auto-subscribe your URL to events the bot sees, when you run `bot.py`.

#### Slack
Visit https://api.slack.com/apps/ to create a new Slack app from scratch (if you already created one for a finbot webhook, you can reuse that app).
* From _Basic Information > Verification Token_, copy _Verification token_ into the .env file variable `slackOutgoingToken`
* In the .env file, put your web server URL (e.g. https://www.example.com:8443/slack) into `slackOutgoingWebhook`
* Save the .env file and (re)start `bot.py`
* Under _Event Subscriptions_:
  * Go to _Enable Events > On > Request URL_ and enter your web server URL (e.g. https://www.example.com:8443/slack). The bot will auto verify Slack's verification request if it is reachable.
  * Go down to _Subscribe to bot events_ and add event `app_mention` for the bot to see _@botname_ mentions.
    * Alternatively, you can subscribe to `message.channels` if you want your bot to see everything and respond to `.` commands. To avoid duplicate responses, don't subscribe to `app_mention` and `message.channels` at the same time.
    * If you want to DM the bot:
      * Subscribe to `message.im`
      * Check the box _App Home > Allow users to send Slash commands and messages from the messages tab_
  * Save Changes
* Under _OAuth & Permissions_: 
  * Scroll down to _Scopes > Bot Token Scopes_, and add `chat:write`
  * Scroll up to _OAuth Tokens for Your Workspace_:
    * If _Bot User OAuth Token_ is not visible, hit _Install to Workspace > Allow_ 
    * Copy _Bot User OAuth Token_ into .env file `slackBotToken`
    * Restart `bot.py`



### Daemonize (systemd)
`finbot.service` can take care of keeping `bot.py` running in the background and starting it on boot. Copy `finbot.service` to `/etc/systemd/system/`, edit it to set the `User` and `ExecStart`, then enable and start it:

```
sudo cp -v finbot.service /etc/systemd/system/
```
```
sudo sed -i 's/CHANGEME/YOUR USERNAME/' /etc/systemd/system/finbot.service
```
```
sudo systemctl daemon-reload
```
```
sudo systemctl enable finbot --now
```
You can now monitor the bot's stderr with :
```
journalctl -fu finbot
```

## Limitations
* Discord shows garbage link previews from Sharesight. Modify the script to remove hyperlinks, or disable this for your Discord account under _Settings > Text & Images > Embeds and link previews._

## Suggestions
* Is my code is doing something the hard way?
* Something important is missing from this README?

Log an [issue](https://github.com/robdevops/finbot/issues)!
