from dotenv import load_dotenv
import os

# TO CONFIGURE, DO NOT EDIT THIS FILE. EDIT .env IN THE PARENT DIRECTORY

load_dotenv()
sharesight_auth = {
        "grant_type": 'client_credentials',
        "code": os.getenv('sharesight_code'),
        "client_id": os.getenv('sharesight_client_id'),
        "client_secret": os.getenv('sharesight_client_secret'),
        "redirect_uri": 'urn:ietf:wg:oauth:2.0:oob'
}
webhooks = {}
if os.getenv('slack_webhook'):
    webhooks['slack'] = os.getenv('slack_webhook')
if os.getenv('discord_webhook'):
    webhooks['discord'] = os.getenv('discord_webhook')
if os.getenv('telegram_url'):
    webhooks['telegram'] = os.getenv('telegram_url')

config_trade_updates_past_days = 0 # default
if os.getenv('trade_updates_past_days'):
    config_trade_updates_past_days = os.getenv('trade_updates_past_days')
    config_trade_updates_past_days = int(config_trade_updates_past_days)

config_price_updates_percent = 10 # default
if os.getenv('price_updates_percent'):
    config_price_updates_percent = os.getenv('price_updates_percent') 
    config_price_updates_percent = float(config_price_updates_percent)

config_earnings_days = 3 # default
if os.getenv('earnings_days'):
    config_earnings_days = os.getenv('earnings_days') 
    config_earnings_days = int(config_earnings_days)

config_ex_dividend_days = 7 # default
if os.getenv('ex_dividend_days'):
    config_ex_dividend_days = os.getenv('ex_dividend_days') 
    config_ex_dividend_days = int(config_ex_dividend_days)

config_shorts_percent = 15 # default
if os.getenv('shorts_weekday'):
    config_shorts_percent = int(os.getenv('shorts_percent'))

config_state_file_path = '/tmp/sharesight-bot-trades.txt' # default
if os.getenv('state_file_path'):
    config_state_file_path = os.getenv('state_file_path')

config_http_timeout = int(10) # default
if os.getenv('http_timeout'):
    config_http_timeout = int(os.getenv('http_timeout'))

config_country_code = str("AU") # default
if os.getenv('country_code'):
    config_country_code = str(os.getenv('country_code'))

config_timezone = str("Australia/Melbourne") # default
if os.getenv('timezone'):
    config_timezone = str(os.getenv('timezone'))

