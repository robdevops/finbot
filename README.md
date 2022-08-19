# sharesight-bot
Notify Slack and Discord of trades from Sharesight

![screenshot of Slack message](screenshot.png?raw=true "Screenshot of Slack message")


## Dependencies
* Email Sharesight support to get an API key and add the access details to the .env file
* Set up Slack and/or Discord webhooks and add them to the .env file
* Python 3
* Python modules:
```
sudo pip3 install requests datetime python-dotenv
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
Sharesight V2 API only provides trade times to the granularity of one day. So this has been designed to run from cron once per day after market close. In the future, it could store trades locally and ignore known trades, so that it can be run with higher frequency.
