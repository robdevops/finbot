# sharesight-bot

_This project has no affiliation with Sharesight Ltd._

## Description
* Daily trade notifications across all portfolios
* Daily price movements of holdings over a defined threshold
* Earnings date reminders for your holdings
* Ex-dividend date warnings for your holdings
* Highly shorted stock warnings for your holdings (AU, US)
* Discord, Slack and Telegram support
* For speed and reliability, it uses no uncommon libraries and minimal screen scraping

![screenshot of Slack message](img/screenshot.png?raw=true "Screenshot of Slack message")

## Dependencies
* Sharesight paid plan, preferably with automatic trade imports, and an API key
* Slack / Discord webhooks / Telegram bot user
* Python 3
* Python modules:
```
bs4 datetime python-dotenv requests
```

## Installation (Linux)
```
sudo pip3 install git bs4 datetime python-dotenv requests
```

```
sudo su -c 'git clone https://github.com/robdevops/sharesight-bot.git /usr/local/bin/sharesight-bot/'
```


## Setup
Configuration is set by the .env file in the parent directory. Example:
```
vi /usr/local/bin/sharesight-bot/.env
```

### Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to the .env file. Example:
```
sharesight_code='87428fc522803d31065emockupf03fe475096631e5e07bbd7a0fde60c4cf25c7'
sharesight_client_id='0263829989b6fd954f7mockupfc64bc2e2f01d692d4de72986ea808f6e99813f'
sharesight_client_secret='a3a5e715f0cc574a73cmockupb6bc24f32ffd5b67b387244c2c909da779a1478'
```

### Discord
* We use Discord's Slack compatibility by appending `/slack` to the Discord webhook in the .env file. Example:
```
discord_webhook='https://discord.com/api/webhooks/1009998000000000000/AbCdEfGhIjKlMnOmockupvWxYz-AbCdEfGhIjKlMn/slack'
```

### Slack
* Slack support simply requires the Slack webhook in the .env file. Example:
```
slack_webhook='https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AbCdEfGhmockupOpQrStUvWxYz'
```

### Telegram
* Set up the bot by messaging [BotFather](https://telegram.me/BotFather).
* Add your bot to a group or channel.
* Prepend the bot id with `bot` in the .env file.
* In the .env file, append `/sendMessage?chat_id=-CHAT_ID` to the bot URL, where _CHAT_ID_ is the unique identifier.
* For channels, _CHAT_ID_ should be negative and 13 characters. Prepend `-100` if necessary.
* For Telegram groups, be aware the group id can change if you edit group settings (it becomes a "supergroup")
* Example .env entry:
```
telegram_url='https://api.telegram.org/bot0123456789:AbCdEfGhmockupOpQrStUvWxYz/sendMessage?chat_id=-1001000000000'
```

## Reports

### Trades
![trade update in Slack](img/trades.png?raw=true "Trade update in Slack")

`trades.py` sends recent Sharesight trades to your configured chat services.
* To avoid duplicate trades, you can either limit this to one run per day (after market close), or run it in an environment with persistent storage. To allow frequent runs, known trades are stored in a temp file defined by `config_state_file_path` in the .env file:
* By default, it only checks for trades from the current day. You can override this with `trade_updates_past_days` in the .env file. This is useful if Sharesight imports trades with past dates for any reason. Without persistent storage, it is recommended to leave this set to 0. With persistent storage, it is recommended to set it to 31. In this case, the first run will notify all historical trades for the period.
```
config_state_file_path = '/tmp/sharesight-bot-trades.txt'
trade_updates_past_days = 31
```

### Price alerts
![price alert in Slack](img/price.png?raw=true "Price alert in Slack")

`prices.py` sends intraday price alerts if the movement is over a percentage threshold. This data is sourced from Finviz (US) and Yahoo! Finance, based on the holdings in your Sharesight portfolio(s). The default threshold is 10% but you can change it by setting `price_updates_percent` in the .env file. Example:
```
price_updates_percent = 10
```

### Earnings reminders
![earnings message in Slack](img/earnings.png?raw=true "Earnings message in Slack")

`earnings.py` sends upcoming earnings date alerts. The data is sourced from Finviz (US) and Yahoo! Finance. Events more than `earnings_future_days` into the future will be ignored.
```
earnings_future_days = 7
```

### Ex-dividend warnings
![ex-dividend warning in Slack](img/ex-dividend.png?raw=true "Ex-dividend warning in Slack")

`ex-dividend.py` sends upcoming ex-dividend date alerts. The data is sourced from Yahoo! Finance. Events more than `ex_dividend_future_days` into the future will be ignored.
```
ex_dividend_future_days = 7
```

### Highly shorted stock warnings
`shorts.py` sends highly shorted stock warnings. The data is sourced from Finviz (US) and Shortman (AU). `shorts_percent` defines the alert threshold for the percentage of a stock's float shorted. Example:
```
shorts_percent = 15
```


## Scheduling example
Recommended for a machine set to UTC:
```
# run calendar reminders once per day
29  21 * * * /usr/local/bin/sharesight-bot/finance_calendar.py

# run trade updates every 20 minutes on weekdays
*/20 * * * Mon-Fri /usr/local/bin/sharesight-bot/trades.py

# run short advisories once per month
29  21 1 * * /usr/local/bin/sharesight-bot/shorts.py

# run other advisories once per week
30  21 * * Fri cd /usr/local/bin/sharesight-bot/; ./earnings.py; ./ex-dividend.py; ./price.py
```
## Serverless
_The following are notes from an AWS Lambda install and may not be current_
### Installation
To prepare zip for upload to cloud:
```
cd sharesight-bot
pip3 install datetime python-dotenv requests --upgrade --target=$(pwd)
zip -r script.zip .
```

### Configuration
For four portfolios (72 holdings) and with all features enabled, this script takes the better part of a minute to run. It is recommended to set _Lambda > Functions > YOUR_FUNCTION > Configuration > General configuration > Edit > Timeout_ to 2 minutes.

### Scheduling
For AWS, go to _Lambda > Functions > YOUR_FUNCTION > Add Trigger > EventBridge (Cloudwatch Events)_, and set _Schedule expression_ to, for example, 10 PM Monday to Friday UTC:
```
cron(0 22 ? * 2-6 *)
```

## Limitations
* Discord shows garbage link previews from Sharesight. Modify the script to remove hyperlinks, or disable this for your Discord account under _Settings > Text & Images > Embeds and link previews._

## Suggestions
* Know a chat or notification service with a REST API?
* Is my code is doing something the hard way?
* Something important is missing from this README?

Log an [issue](https://github.com/robdevops/sharesight-bot/issues)!
