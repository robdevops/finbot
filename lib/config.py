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
if os.getenv('telegramBotToken'):
    webhooks['telegram'] = 'https://api.telegram.org/bot' + os.getenv('telegramBotToken') + '/'

if os.getenv('slackToken'):
    config_slackToken = str(os.getenv('slackToken'))

if os.getenv('telegramChatID'):
    config_telegramChatID = str(os.getenv('telegramChatID'))

config_past_days = 0 # default
if os.getenv('past_days'):
    config_past_days = int(os.getenv('past_days'))

config_price_percent = 10 # default
if os.getenv('price_percent'):
    config_price_percent = float(os.getenv('price_percent'))

config_future_days = 7 # default
if os.getenv('future_days'):
    config_future_days = int(os.getenv('future_days'))

config_shorts_percent = 15 # default
if os.getenv('shorts_percent'):
    config_shorts_percent = int(os.getenv('shorts_percent'))

config_cache_dir = '/tmp' # default
if os.getenv('cache_dir'):
    config_cache_dir = os.getenv('cache_dir')

config_http_timeout = int(10) # default
if os.getenv('http_timeout'):
    config_http_timeout = int(os.getenv('http_timeout'))

config_country_code = str("AU") # default
if os.getenv('country_code'):
    config_country_code = str(os.getenv('country_code'))

config_timezone = str("Australia/Melbourne") # default
if os.getenv('timezone'):
    config_timezone = str(os.getenv('timezone'))

config_exclude_portfolios = () # default
if os.getenv('exclude_portfolios'):
    config_exclude_portfolios = set(os.getenv('exclude_portfolios').split())

config_include_portfolios = () # default
if os.getenv('include_portfolios'):
    config_include_portfolios = set(os.getenv('include_portfolios').split())

config_watchlist = () # default
if os.getenv('watchlist'):
    config_watchlist = set(os.getenv('watchlist').split())

config_chunk_maxlines = int(20) # default
if os.getenv('chunk_maxlines'):
    config_chunk_maxlines = int(os.getenv('chunk_maxlines'))

config_cache = True # default
if os.getenv('cache'):
    config_cache = os.getenv("cache", 'False').lower() in ('true', '1', 't')

config_cache_seconds = 82800 # default
if os.getenv('cache_seconds'):
    config_cache_seconds = int(os.getenv('cache_seconds'))

config_telegram_outgoing_webhook = str() # default
if os.getenv('telegram_outgoing_webhook'):
    config_telegram_outgoing_webhook = str(os.getenv('telegram_outgoing_webhook'))

