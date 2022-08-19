# sharesight-bot
Notify Discord, Slack and/or Telegram of trades from Sharesight

![screenshot of Slack message](screenshot.png?raw=true "Screenshot of Slack message")


## Dependencies
* Email Sharesight support to get an API key and add the [access details](https://portfolio.sharesight.com/oauth_consumers) to the .env file
* Set up Slack and/or Discord webhooks and/or a Telegram bot user, and add their URLs to the .env file
* Python 3
* Python modules:
```
sudo pip3 install requests datetime python-dotenv
```

## Configuration Details

### Discord
* We use Discord's Slack compatibility webhook by appending `/slack` to the Discord webhook in the .env file:
```
discord_webhook='https://discord.com/api/webhooks/1009998000000000000/AbCdEfGhIjKlMnOpQrStUvWxYz-AbCdEfGhIjKlMn/slack'
```

### Slack
* Slack support simply requires the Slack webhook in the .env file. Example:
```
slack_webhook='https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AbCdEfGhIjKlMnOpQrStUvWxYz'
```

### Telegram
* Set up the bot by messaging [BotFather](https://telegram.me/BotFather)
* Prepend the bot id with `bot` in the .env file.
* In the .env file, append `/sendMessage?chat_id=-CHAT_ID` to the bot URL, where _CHAT_ID_ is the unique identifier.
* For channels, _CHAT_ID_ should be negative and 13 characters. Prepend `-100` if necessary.
* For Telegram groups, be aware the group id can change if you edit group settings (it becomes a "supergroup")
* Example .env entry:
```
telegram_chat='https://api.telegram.org/bot0123456789:AbCdEfGhIjKlMnOpQrStUvWxYz/sendMessage?chat_id=-1001234567890'
```

## Running the script
This has been designed to run from AWS Lambda, but you can run it on a normal Python environment with `python3 sharesight.py`

To prepare zip for upload to Lambda:
```
cd sharesight-bot
pip3 install requests datetime python-dotenv --upgrade --target=$(pwd)
zip -r script.zip .
```

## Limitations
* Sharesight V2 API only provides trade times to the granularity of one day. So this has been designed to run from cron once per day after market close. In the future, it could store trades locally and ignore known trades, so that it can be run with higher frequency.
* Discord shows garbage link previews from Sharesight. Modify the script to remove hyperlinks, or disable this for your Discord account under _Settings > Text & Images > Embeds and link previews._
