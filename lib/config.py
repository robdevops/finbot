from dotenv import load_dotenv
import os

# TO CONFIGURE, DO NOT EDIT THIS FILE. EDIT .env IN THE PARENT DIRECTORY

os.chdir(os.path.dirname(__file__) + '/../')
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
    webhooks['slack'] = os.getenv('slack_webhook').rstrip('/')
if os.getenv('discord_webhook'):
    webhooks['discord'] = os.getenv('discord_webhook').rstrip('/').replace('/slack', '') + '/slack'
if os.getenv('telegramBotToken'):
    webhooks['telegram'] = 'https://api.telegram.org/bot' + os.getenv('telegramBotToken').rstrip('/') + '/'

config_alliterate = os.getenv("alliterate", 'False').lower() in ('true', '1', 't')
config_cache = os.getenv("cache", 'True').lower() in ('true', '1', 't')
config_cache_dir = os.getenv('cache_dir', 'var/cache').rstrip('/')
config_cache_seconds = int(os.getenv('cache_seconds', 82800))
config_country_code = os.getenv('country_code', 'AU')
config_chunk_maxlines = int(os.getenv('chunk_maxlines', 20))
config_exclude_portfolios = () # default
config_exclude_portfolios = os.getenv('exclude_portfolios', '').split()
config_future_days = int(os.getenv('future_days', 7))
config_http_timeout = int(os.getenv('http_timeout', 10))
config_include_portfolios = os.getenv('include_portfolios', '').split()
config_ip = os.getenv('ip', '127.0.0.1')
config_past_days = int(os.getenv('past_days', 0))
config_port = int(os.getenv('port', 5000))
config_price_percent = float(os.getenv('price_percent', 9.4))
config_shorts_percent = int(os.getenv('shorts_percent', 15))
config_slackBotToken = os.getenv('slackBotToken', False)
config_slackOutgoingToken = os.getenv('slackOutgoingToken', False)
config_slackOutgoingWebhook = os.getenv('slackOutgoingWebhook', False)
config_telegramAllowedUserIDs = os.getenv('telegramAllowedUserIDs', '').split()
config_telegramBotToken = os.getenv('telegramBotToken', False)
config_telegramOutgoingWebhook = os.getenv('telegramOutgoingWebhook', False)
config_telegramChatID = os.getenv('telegramChatID', False)
config_telegramOutgoingToken = os.getenv('telegramOutgoingToken', False)
config_timezone = os.getenv('timezone', 'Australia/Melbourne')
debug = os.getenv("debug", 'False').lower() in ('true', '1', 't')

