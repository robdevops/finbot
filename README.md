# sharesight-bot
Notify Slack and Discord of trades from Sharesight

# Dependencies
* Email Sharesight support to get an API key and add the access details to the .env file
* Set up Slack and/or Discord webhooks and add them to the .env file
* Python 3
* Python modules:
```
sudo pip3 install requests datetime python-dotenv
```

# RUN
This has been designed to run from AWS Lambda, but can run it on a normal distro with `python3 sharesight.py`

To upload to Lambda:
cd sharesight-bot
pip3 install requests datetime python-dotenv --upgrade --target=$(pwd)
zip -r script.zip .

# LIMITATIONS
Sharesight only provides trade times to the granulality of 1 day. So this has been designed to run from cron once per day after market close. In the future, it could store trades locally and ignore known trades, so that it can be run with higher frequency.
