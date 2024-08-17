import os
import json
from dotenv import load_dotenv

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
	webhooks['discord'] = os.getenv('discord_webhook').rstrip('/').removesuffix('/slack') + '/slack'
if os.getenv('telegramBotToken'):
	webhooks['telegram'] = 'https://api.telegram.org/bot' + os.getenv('telegramBotToken').rstrip('/') + '/'

config_alliterate = os.getenv("alliterate", 'False').lower() in ('true', '1', 't')
config_cache = os.getenv("cache", 'True').lower() in ('true', '1', 't')
config_cache_dir = os.getenv('cache_dir', 'var/cache').rstrip('/')
config_var_dir = os.getenv('var_dir', 'var').rstrip('/')
config_cache_seconds = int(os.getenv('cache_seconds', 43200 ))
config_country_code = os.getenv('country_code', 'AU')
config_chunk_maxlines = int(os.getenv('chunk_maxlines', 20))
config_exclude_portfolios = () # default
config_exclude_portfolios = os.getenv('exclude_portfolios', '').split()
config_future_days = int(os.getenv('future_days', 7))
config_http_timeout = int(os.getenv('http_timeout', 18))
config_graph = os.getenv("graph", 'True').lower() in ('true', '1', 't')
config_demote_volatile = os.getenv("demote_volatile", 'True').lower() in ('true', '1', 't')
config_volatility_multiplier = float(os.getenv('volatile_multiplier', 2))
config_hyperlink = os.getenv("hyperlink", 'True').lower() in ('true', '1', 't')
config_hyperlinkFooter = os.getenv("hyperlinkFooter", 'False').lower() in ('true', '1', 't')
config_hyperlinkProvider = os.getenv("hyperlinkProvider", 'yahoo').lower()
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
config_trades_use_yahoo = os.getenv("trades_use_yahoo", 'True').lower() in ('true', '1', 't') # set False if Yahoo breaks
debug = os.getenv("debug", 'False').lower() in ('true', '1', 't')

adjectives = [
	'absolutely',
	'amazingly',
	'awfully',
	'bitchingly',
	'bloodly',
	'comfortably',
	'darned',
	'distinctly',
	'especially',
	'ever so',
	'enjoyably',
	'exceedingly',
	'exceptionally',
	'extraordinarily',
	'extremely',
	'flatteringly',
	'fortunately',
	'fortuitously',
	'greatly',
	'honourably',
	'hugely',
	'humblingly',
	'inordinately',
	'jolly',
	'joyfully',
	'keenly',
	'kindly',
	'knowingly',
	'luckily',
	'memorably',
	'mostly',
	'needlessly',
	'overwhelmingly',
	'pleasurably',
	'questionably',
	'rewardingly',
	'serendipitously',
	'seriously',
	'significantly',
	'so',
	'super',
	'supremely',
	'surprisingly',
	'terribly',
	'terrifically',
	'thoroughly',
	'totally',
	'tremendously',
	'uber',
	'uncomprehensibly',
	'unexceptionably',
	'unquestionably',
	'unmentionably',
	'unusually',
	'discomfortingly',
	'incomprehensibly',
	'very',
	'wholesomely',
	'xtra',
	'yawningly',
	'zealously'
]

adjectives_two = [
	'amazing',
	'bitching',
	'comforting',
	'comprehensible',
	'dapper',
	'enjoyable',
	'exceptional',
	'extraordinary',
	'flattering',
	'fortuitous',
	'fortunate',
	'great',
	'grateful',
	'honouring',
	'huge',
	'humbling',
	'inordinate',
	'joyous',
	'keen',
	'knowing',
	'kind',
	'lucky',
	'memorable',
	'mentionable',
	'nice',
	'overwhelming',
	'pleasurable',
	'questionable',
	'rewarding',
	'serendipitous',
	'significant',
	'special',
	'super',
	'terrific',
	'tremendous',
	'useful',
	'virtuous',
	'wholesome',
	'xenial',
	'yawning',
	'zany'
]

verb = [
	'pretend to greet',
	'apparently share this moment with',
	'coincide in temporal reality with',
	'cross digital paths with',
	'simulate becoming acquainted with',
	'fire photons at',
	'traverse cyberspace with',
	'co-exist in spacetime with',
	'fire electrons at',
	'encode character sets with',
	'convert utf-8 to binary and then back to utf-8 with',
	'update this pixel matrix with',
	'lose money with',
	'maintain character with',
	'act like I comprehend'
]

searchVerb = [
	'Asking ChatGPT for',
	'Avoiding eye contact with',
	'Carrying the 1 on',
	'Conducting seance to make contact with',
	'Conjuring up',
	'Dispatching fluffy dogs to track',
	'Entering metaverse to inefficiently get',
	'Excavating',
	'Foraging for',
	'Hiring developers to troubleshoot',
	'Loading backup tapes for',
	'Manifesting',
	'Massaging data for',
	'Mining dogecoin to purchase report on',
	'Panning for',
	'Performing expert calculus on',
	'Plucking',
	'Poking a stick at',
	'Praying for',
	'Reciting incantations on',
	'Repairing file-system to restore',
	'Resetting Sharesight password to fetch',
	'Rummaging for',
	'SELECT * FROM topsecret WHERE',
	'Sacrificing wildebeest to recover',
	'Shooing rodents to access',
	'Summoning',
	'Training pigeons to fetch',
	'Transcribing Hebrew for',
	'Traversing the void for',
	'Unshredding documents for',
	'Unspilling coffee to read',
	'ls -l /var/lib/topsecret/ | grep'
]

noTradesVerb = [
	"The money is probably resting in another account",
	"Oh well. The market would have just gone down anyway",
	"Heating bills don't pay themselves you know",
	"You were fearful when others were also fearful",
	"I bet you're regretting that extra 1¢ on your limit order now",
	"This is why you can't have nice things",
	"But I'm sure that's just a rounding error",
	"Nothing + nothing = more nothing. Well played",
	"Or maybe there was. They don't pay me for this you know",
	"I guess that's right. Maybe... I'm kinda busy with ChatGPT in another window",
	"I like this contrarian play you're having on 'being in it to win it'",
	"With your stock picking skills, this is probably for the best"
]

filename = 'lib/finbot_adr.json'
if os.path.isfile(filename):
	with open(filename, "r", encoding="utf-8") as f:
		primary_listing = json.loads(f.read())

yahoo_country = {
	'Argentina': 'BA',
	'Austria': 'VI',
	'Australia': 'AX',
	'Belgium': 'AS',
	'Brazil': 'SA',
	'Canada': 'TO',
	'Chile': 'SN',
	'Colombia': 'CL',
	'Czech Republic': 'PR',
	'Denmark': 'CO',
	'Estonia': 'TL',
	'Finland': 'HE',
	'France': 'PA',
	'Germany': 'DE',
	'Hungary': 'BD',
	'Iceland': 'IC',
	'India': 'NS',
	'Indonesia': 'JK',
	'Ireland': '.IR',
	'Israel': 'TA',
	'Italy': 'MI',
	'Latvia': 'RG',
	'Lithuania': 'VS',
	'Mexico': 'MX',
	'Netherlands': 'AS',
	'New Zealand': 'NZ',
	'Norway': 'OL',
	'Portugal': 'LS',
	'Qatar': 'QA',
	'Saudi Arabia': 'SAU',
	'South Africa': 'JO',
	'Spain': 'MC',
	'Sweden': 'ST',
	'Switzerland': 'SW',
	'Thailand': 'BK',
	'Turkey': 'IS',
	'United Kingdom': 'L',
	'Venezuela': 'CR'
	# markets with numeric tickers purposefully omitted
}
