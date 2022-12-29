# finbot

## Description

### Features
* Sharesight Trade notifications
* Yahoo Finance data for Sharesight holdings:
  * Intraday and premarket price movements over a defined threshold
  * Earnings date reminders
  * Ex-dividend date warnings
  * Highly shorted stock warnings (AU, US)
* Interactive chat commands for stock info (Slack & Telegram):
  * Stock lookup with price/valuation related stats and warnings
  * Company profiles
  * Shared watch list
* Discord, Slack and Telegram support

![Screenshot of showing trade notifications on Slack](img/screenshot.png?raw=true "Screenshot showing trade notifications on Slack")

Trade notifications are peformed by polling the Sharesight trades API from a cron job, and notifying your configured chat networks of any new trades. Thus, it works best if your trades are auto-imported into Sharesight through its broker integrations, and if your environment has persistent storage so that the bot can keep track of known trade ids between runs. Persistent storage enables a polling frequency greater than daily, such as every 5 minutes.

The other various reports can also run from cron (e.g. daily or weekly), or on demand through the interactive bot. They query the Yahoo Finance API for stock data based on current holdings combined across your Sharesight portfolios, your friends' Sharesight portfolios, plus a custom watch list. Depending on how they're triggered, they will either report to all configured chat networks, or reply to the chat which triggered them.

The interactive bot requires you to host a web service on a domain with a trusted certificate. It subscribes to push updates from native Slack apps / Telegram bots, and reacts to certain regex seen in chat. It can: 
* Run the aforementioned reports on demand
* Look up stock facts when given a ticker code
* Allow your chat group to maintain a shared watch list that is picked up by the various reports.

![Screenshot showing stock info on Slack](img/stockinfo.png?raw=true "Screenshot showing stock info on Slack")

## Dependencies
* Sharesight paid plan, preferably with automatic trade imports, and an API key
* Slack / Discord webhooks / Telegram bot user
* The interactive bot requires a web server with domain name and matching certificate, plus the gevent Python module
* Python 3.8.10
* Python modules:
```
datetime python-dotenv requests gevent
```

## Installation (Linux)
```
pip3 install datetime python-dotenv requests gevent
```

```
sudo $(which apt dnf yum) install git
```
```
git clone https://github.com/robdevops/finbot.git ~/finbot
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
A Slack webhook can be provisioned by creating a new app at https://api.slack.com/apps/ then navigating to _Incoming Webhooks_. Once the link is generated, add it to the .env file. Example:
```
slack_webhook = 'https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA'
```
The webhook is only used for the trade notifications and scheduled reports. The interactive bot requires further configuration of this Slack app (see below).

### Telegram
* Set up the bot by messaging [BotFather](https://telegram.me/BotFather).
* Add your bot to a group or channel.
* Optionally, make the bot an admin (for interactive features).
* In the .env file, set `telegramBotToken` to the token BotFather gave you.
* In the .env file, set `telegramChatID` to the chat group or channel id.
   * For channels and supergroups, _CHAT_ID_ should be negative and 13 characters. Prepend `-100` if necessary.
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
Many object sources are cached for just under one day by default. Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache = True
cache_seconds = 82800
```

### Watchlist
Tracks securities which are not in your Sharesight holdings. Use the Yahoo! Finance ticker format. Example:
```
watchlist = "RMBS STEM ZS SYR.AX 2454.TW"
```
Once this value is loaded into the interactive bot, it is not read again. The interactive mode uses its own watchlist file.

## Reports

"Reports" refers to the cron initiated non-interactive notifications from the bot.

### Trades
![trade update in Slack](img/trades.png?raw=true "Trade update in Slack")

`trades.py` sends recent Sharesight trades to your configured chat services.
By default, this report searches Sharesight for trades from the current day only. You can override this with `past_days` in the .env file. 

Without persistent storage, it is recommended to leave `past_days=0` to avoid duplicate trade notifications. The cron that triggers the report must do so exactly once per day, after market close.

With persistent storage, it is recommended to set `past_days=30`. This is useful if Sharesight imports trades with past dates for any reason. Note that the initial run will notify on all historical trades for the `past_days` period. It is recommended to set the cron frequency to every 20 minutes.

```
past_days = 30
```

### Price alerts
![price alert in Slack](img/price.png?raw=true "Price alert in Slack")

`prices.py` sends intraday price alerts for Sharesight holdings if the movement is over a percentage threshold. This data is sourced from Yahoo! Finance. The default threshold is 10% but you can change it by setting `price_percent` in the .env file. Decimal fractions are accepted. Example:
```
price_percent = 9.4
```

### Price alerts (pre-market)
`premarket.py` sends pre/post market price alerts for Sharesight holdings if the movement is over a percentage threshold. This data is sourced from Yahoo! Finance. The default threshold is 10% but you can change it by setting `price_percent` in the .env file. Decimal fractions are accepted. Example:
```
price_percent = 9.4
```

### Earnings reminders
![earnings message in Slack](img/earnings.png?raw=true "Earnings message in Slack")

`earnings.py` sends upcoming earnings date alerts. The data is sourced from Yahoo! Finance. Events more than `future_days` into the future will be ignored. **Explanation:** when a company releases its quarterly earnings report, the stock price may undergo a signficant positive or negative movement, depending on whether the company beat or missed market expectations. You may wish to hold off buying more of this stock until after its earnings report, unless you think the stock will beat market expectations.
```
future_days = 7
```

### Ex-dividend warnings
![ex-dividend warning in Slack](img/ex-dividend.png?raw=true "Ex-dividend warning in Slack")

`ex-dividend.py` sends upcoming ex-dividend date alerts. The data is sourced from Yahoo! Finance. Events more than `future_days` into the future will be ignored. **Explanation:** When a stock goes ex-dividend, the share price [typically drops](https://www.investopedia.com/articles/stocks/07/ex_dividend.asp) by the amount of the dividend paid. If you buy right before the ex-dividend date, you can expect an unrealised capital loss, plus a tax obligation for the dividend. Thus, you may wish to wait for the ex-dividend date before buying more of this stock.
```
future_days = 7
```

### Highly shorted stock warnings
`shorts.py` sends short interest warnings. The data is sourced from Yahoo Finance and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. **Explanation:** A high short ratio indicates a stock is exposed to high risks, such as potential banktrupcy. It may also incentivise negative news articles which harm the stock price. If the market is wrong, however, risk tolerant investors may receive windfall gains. This report is intended to alert you to an above-average risk, and prompt you to investigate this stock more closely. 
```
shorts_percent = 15
```

## Scheduling example
Recommended for a machine set to UTC:
```
# Every 20 minutes on weekdays
*/20 * * * Mon-Fri ~/finbot/trades.py > /dev/null

# Daily
30  21 * * * ~/finbot/finance_calendar.py > /dev/null

# Daily on weekdays
29  21 * * Mon-Fri ~/finbot/price.py > /dev/null
10  11 * * Mon-Fri ~/finbot/premarket.py > /dev/null

# Weekly
28  21 * * Fri { cd ~/finbot/; ./earnings.py; ./ex-dividend.py ;} > /dev/null

# Monthly
27  21 1 * * ~/finbot/shorts.py > /dev/null
```
The above can be installed with:
```
(crontab -l ; cat ~/finbot/crontab.txt)| crontab -
```

## Interactive bot
Currently supporting Slack and Telegram, the interactive bot adds:
* Stock lookup (financials and company profile)
* Group maintainable watch list
* Listing of portfolios and their current holdings
* Running the other stock reports on command

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
		allow 91.108.4.0/22
		deny all;
	}
}
```
Note: The utils folder contains a script to generate `/etc/nginx/aws_subnets`. It can be run once, or placed in `/etc/cron.daily/`.

### Integrating the interactive bot with chat networks

For Telegram, message BotFather to create a bot. Set .env file `telegramBotToken` to the token given by BotFather.
Set .env `telegram_outgoing_webhook` to your web server (https://www.example.com:8443/telegram). Finally, set `telegramOutgoingToken` to a password of your choosing. Telegram will use this to authenticate with finbot. Add your Telegram bot to a group, and give it group admin access so it can read the group chat. With these options set, your bot will auto-subscribe your URL to events the bot sees, when you run `bot.py`.

For Slack, visit https://api.slack.com/apps/ to create a new Slack app. Put the token from _OAuth & Permissions > Bot User OAuth Token_ into .env file `slackOAuthToken` and the token from _Basic Information > Verification Token_ into the .env file `slackVerifyToken`. Put your web server URL (https://www.example.com:8443/slack) into _Event Subscriptions > Enable Events_ (the bot will auto verify Slack's verification request if `bot.py` is running and reachable), and finally, under _Event Subscriptions > Subscribe to bot events_, add event `app_mention` for the bot to see _@botname_ mentions.
* Alternatively, you can subscribe to `message.channels` if you want your bot to see everything and respond to `!` commands. To avoid duplicate responses, don't subscribe to `app_mention` and `message.channels` at the same time.
* If you want to DM the bot, subscribe to `message.im`, and check the box _App Home > Allow users to send Slash commands and messages from the messages tab_.

### Supported commands:
```
!AAPL
!AAPL bio
!holdings
!premarket [percent]
!shorts [percent]
!trades [days]
!watchlist
!watchlist [add|del] AAPL
@botname AAPL
@botname AAPL bio
@botname holdings
@botname premarket [percent]
@botname shorts [percent]
@botname trades [days]
@botname watchlist
@botname watchlist [add|del] AAPL
```

### Daemonize (systemd)
`finbot.service` can take care of keeping `bot.py` running in the background and starting on boot. Copy `finbot.service` to `/etc/systemd/system/`, edit it to set the `User` and `ExecStart`, then enable and start it:
```
sed -i 's/CHANGEME/YOUR USERNAME/' finbot.service
```

```
sudo cp -v finbot.service /etc/systemd/system/finbot.service
```

```
sudo systemctl enable finbot --now
```

## Limitations
* Discord shows garbage link previews from Sharesight. Modify the script to remove hyperlinks, or disable this for your Discord account under _Settings > Text & Images > Embeds and link previews._

## Suggestions
* Know a chat or notification service with a REST API?
* Is my code is doing something the hard way?
* Something important is missing from this README?

Log an [issue](https://github.com/robdevops/finbot/issues)!
