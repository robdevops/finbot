# sharesight-bot

## Description
* Daily trade notifications across all portfolios
* Daily price movements of holdings over a defined threshold
* Earnings date reminders for your holdings
* Ex-dividend date reminders for your holdings
* Discord, Slack and Telegram support
* For speed and reliability, it uses no uncommon libraries or screen scraping

![screenshot of Slack message](screenshot.png?raw=true "Screenshot of Slack message")



## Dependencies
* Sharesight paid plan, preferably with automatic trade imports, and an API key
* Slack / Discord webhooks / Telegram bot user
* Python 3
* Python modules:
```
pip3 install datetime python-dotenv requests
```

## Configuration Details

### Sharesight
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to the .env file. Example:
```
sharesight_code='87428fc522803d31065emockupf03fe475096631e5e07bbd7a0fde60c4cf25c7'
sharesight_client_id='0263829989b6fd954f72bnot2fc64bc2e2f01d692d4de72986ea808f6e99813f'
sharesight_client_secret='a3a5e715f0cc574a73c3realbb6bc24f32ffd5b67b387244c2c909da779a1478'
```

### Discord
* We use Discord's Slack compatibility by appending `/slack` to the Discord webhook in the .env file. Example:
```
discord_webhook='https://discord.com/api/webhooks/1009998000000000000/AbCdEfGhIjKlMnOpQrStUvWxYz-AbCdEfGhIjKlMn/slack'
```

### Slack
* Slack support simply requires the Slack webhook in the .env file. Example:
```
slack_webhook='https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AbCdEfGhIjKlMnOpQrStUvWxYz'
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
telegram_url='https://api.telegram.org/bot0123456789:AbCdEfGhIjKlMnOpQrStUvWxYz/sendMessage?chat_id=-1001234567890'
```
### Trade updates
Setting `trade_updates=true` in the .env file will tell the bot to send Sharesight trades to your configured chat services.

### Price alerts
Setting `price_updates=true` in the .env file will trigger price alerts for holdings which moved by a certain percentage in the most recent session. This data is sourced from Yahoo! Finance, based on the holdings in your Sharesight portfolio(s). The default threshold is 10% but you can change it by setting `price_updates_percentage` in the .env file. Example:
```
price_updates=true
price_updates_percentage=10
```

### Earnings reminders
Setting `earnings=true` in the .env file will trigger upcoming earnings date alerts. The data is sourced from Yahoo! Finance. Events more than `earnings_days` into the future will be ignored. Earnings reminders will only run on `earnings_weekday`. Set `earnings_weekday=any` to run it on every execution of the script. Example:
```
earnings=true
earnings_days=7
earnings_weekday=Friday
```

### Ex-dividend reminders
Setting `ex_dividend=true` in the .env file will trigger upcoming ex-dividend date alerts. The data is sourced from Yahoo! Finance. Events more than `ex_dividend_days` into the future will be ignored. Ex-dividend reminders will only run on `ex_dividend_weekday`. Set `ex_dividend_weekday=any` to run it on every execution of the script. Example:
```
ex_dividend=true
ex_dividend_days=7
ex_dividend_weekday=Friday
```

## Running the script
The script has been designed to run from AWS Lambda, but you can run it on a normal Python environment with `python3 sharesight-bot.py`


### Linux
#### Installation
```
sudo pip3 install datetime python-dotenv requests
```
```
sudo su -c 'git clone https://github.com/robdevops/sharesight-bot.git /usr/local/bin/sharesight-bot/'
```

#### Configuration
```
sudo vi /usr/local/bin/sharesight-bot/.env
```

#### Scheduling
Add a wrapper to /etc/cron.daily/:
```
echo '!#/bin/bash; cd /usr/local/bin/sharesight-bot/; python3 sharesight-bot.py' | sudo tee /etc/cron.daily/sharesight-bot
````
Ensure it's executable:
```
sudo chmod u+x /etc/cron.daily/sharesight-bot
```

### Amazon Lambda
#### Installation
To prepare zip for upload to Lambda:
```
cd sharesight-bot
pip3 install datetime python-dotenv requests --upgrade --target=$(pwd)
zip -r script.zip .
```

#### Configuration
For four portfolios (72 holdings), this script takes around 10 seconds to execute trade alerts, 20 seconds to execute earnings reminders and price alerts, and  30 seconds to execute ex-dividend alerts. It is recommended to set _Lambda > Functions > YOUR_FUNCTION > Configuration > General configuration > Edit > Timeout_ to 2 minutes.

#### Scheduling
Go to _Lambda > Functions > YOUR_FUNCTION > Add Trigger > EventBridge (Cloudwatch Events)_, and set _Schedule expression_ to, for example, This means 10 PM Monday to Friday UTC:
```
cron(0 22 ? * 2-6 *)
```

## Limitations
* Sharesight V2 API only provides trade times to the granularity of one day. So this script has been designed to run from cron once per day after market close. In the future, it could store trades locally and ignore known trades, so that it can be run with higher frequency.
* Discord shows garbage link previews from Sharesight. Modify the script to remove hyperlinks, or disable this for your Discord account under _Settings > Text & Images > Embeds and link previews._
