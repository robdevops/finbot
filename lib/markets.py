"""Markets: each one's flag, currency and Yahoo suffix by its code, the names exchanges go by, and ticker translation
between Sharesight, Google and Yahoo."""
import typing


class Market(typing.NamedTuple):
	"""A market: its flag; its currency, None where it quotes in several (HKEX takes others too); the suffix of its
	Yahoo tickers, '' where they take none (a US venue) and None where Yahoo has several (EURONEXT is five exchanges);
	and Google Finance's code for it, where that is not the same."""
	flag: str
	currency: str | None
	yahoo: str | None
	google: str | None = None


US = Market('🇺🇸', 'USD', '')
MARKETS = { # by Sharesight's codes (TSE is Toronto, TYO Tokyo), and Google's where they are others
	'ASX': Market('🇦🇺', 'AUD', 'AX'),
	'NZX': Market('🇳🇿', 'NZD', 'NZ', 'NZE'),
	'NASDAQ': US, 'NYSE': US, 'BATS': US, 'NYSEARCA': US,
	'AMEX': US._replace(google='NYSEAMERICAN'),
	**dict.fromkeys(('OTC', 'OTCBB', 'OTCMKTS'), US._replace(google='OTCMKTS')),
	**dict.fromkeys(('TSE', 'TSX'), Market('🇨🇦', 'CAD', 'TO', 'TSE')), # Toronto: Google calls it TSE too
	'CVE': Market('🇨🇦', 'CAD', 'V'), # TSX Venture
	'CNSX': Market('🇨🇦', 'CAD', 'CN'),
	'NEO': Market('🇨🇦', 'CAD', 'NE'),
	'BMV': Market('🇲🇽', 'MXN', 'MX'),
	'BVMF': Market('🇧🇷', 'BRL', 'SA'),
	'LSE': Market('🇬🇧', 'GBP', 'L', 'LON'), # it takes other currencies, but GBP beats the brokerage's (AUD on CMC)
	**dict.fromkeys(('XETR', 'ETR'), Market('🇩🇪', 'EUR', 'DE', 'ETR')), # Xetra
	**dict.fromkeys(('FRA', 'FWB'), Market('🇩🇪', 'EUR', 'F', 'FRA')), # Frankfurt
	'EURONEXT': Market('🇪🇺', 'EUR', None),
	'EPA': Market('🇫🇷', 'EUR', 'PA'), 'AMS': Market('🇳🇱', 'EUR', 'AS'), 'EBR': Market('🇧🇪', 'EUR', 'BR'),
	'DUB': Market('🇮🇪', 'EUR', 'IR'),
	'BIT': Market('🇮🇹', 'EUR', 'MI'),
	'BME': Market('🇪🇸', 'EUR', 'MC'),
	'VIE': Market('🇦🇹', 'EUR', 'VI'),
	**dict.fromkeys(('ASE', 'ATH'), Market('🇬🇷', 'EUR', 'AT', 'ATH')),
	'HEL': Market('🇫🇮', 'EUR', 'HE'),
	**dict.fromkeys(('STO', 'OM'), Market('🇸🇪', 'SEK', 'ST', 'STO')),
	**dict.fromkeys(('CSE', 'CPSE'), Market('🇩🇰', 'DKK', 'CO', 'CPH')),
	**dict.fromkeys(('OSL', 'OB'), Market('🇳🇴', 'NOK', 'OL', 'OSL')),
	'ICSE': Market('🇮🇸', 'ISK', 'IC', 'ICE'),
	**dict.fromkeys(('SWX', 'SIX', 'VTX'), Market('🇨🇭', 'CHF', 'SW', 'SWX')),
	'WAR': Market('🇵🇱', 'PLN', 'WA', 'WSE'),
	'MISX': Market('🇷🇺', 'RUB', 'ME', 'MCX'),
	'JSE': Market('🇿🇦', 'ZAR', 'JO'),
	**dict.fromkeys(('TASE', 'TLV'), Market('🇮🇱', 'ILS', 'TA', 'TLV')),
	'TYO': Market('🇯🇵', 'JPY', 'T'),
	'HKG': Market('🇭🇰', None, 'HK'),
	'SGX': Market('🇸🇬', 'SGD', 'SI'),
	'KRX': Market('🇰🇷', 'KRW', 'KS'), 'KOSDAQ': Market('🇰🇷', 'KRW', 'KQ'),
	'TAI': Market('🇹🇼', 'TWD', 'TW', 'TPE'), # the Taiwan Stock Exchange, Google's TPE
	'TPE': Market('🇹🇼', 'TWD', 'TWO'), # the Taipei Exchange, which Google lacks
	**dict.fromkeys(('BSE', 'BOM'), Market('🇮🇳', 'INR', 'BO', 'BOM')),
	'NSE': Market('🇮🇳', 'INR', 'NS'),
	**dict.fromkeys(('SHG', 'SHA'), Market('🇨🇳', 'CNY', 'SS', 'SHA')),
	'SHE': Market('🇨🇳', 'CNY', 'SZ'),
	'BKK': Market('🇹🇭', 'THB', 'BK'),
	'IDX': Market('🇮🇩', 'IDR', 'JK'),
	'KLS': Market('🇲🇾', 'MYR', 'KL', 'KLSE'),
	'PHS': Market('🇵🇭', 'PHP', 'PS', 'PSE'),
}

VENUES = { # the other names of an exchange -> its code in MARKETS: its Yahoo tickers' suffix, and Yahoo's names
	**{market.yahoo: code for code, market in reversed(MARKETS.items()) if market.yahoo},
	'NYSEArca': 'NYSEARCA', 'NYSE American': 'AMEX', 'Cboe US': 'BATS', # other Nasdaq and NYSE names: see code()
	**dict.fromkeys(('Other OTC', 'PNK', 'OTCPK'), 'OTC'),
	**dict.fromkeys(('Toronto', 'TOR'), 'TSE'),
	**dict.fromkeys(('NZSE', 'NZE', 'New Zealand', 'Auckland'), 'NZX'),
	'London': 'LSE', 'XETRA': 'XETR', 'Frankfurt': 'FRA',
	'Paris': 'EPA', 'Amsterdam': 'AMS', 'Brussels': 'EBR', 'Irish': 'DUB', 'Milan': 'BIT', 'Vienna': 'VIE',
	'Helsinki': 'HEL', 'Stockholm': 'STO', 'Copenhagen': 'CSE', 'Oslo': 'OSL', 'Swiss': 'SWX',
	'Johannesburg': 'JSE', 'Tel Aviv': 'TASE', 'Mexico': 'BMV', 'São Paulo': 'BVMF',
	**dict.fromkeys(('Tokyo', 'JPX'), 'TYO'),
	'HKSE': 'HKG', 'SES': 'SGX', 'KSE': 'KRX', 'KSC': 'KRX', 'KOE': 'KOSDAQ',
	'Taiwan': 'TAI', 'Taipei Exchange': 'TPE', 'Taipei': 'TPE',
	'Shanghai': 'SHG', 'Shenzhen': 'SHE', 'Thailand': 'BKK', 'Jakarta': 'IDX', 'Kuala Lumpur': 'KLS',
}

def code(name):
	"""MARKETS' code for an exchange by any name it goes by: Sharesight's code or Google's, the suffix of its Yahoo
	tickers, or Yahoo's name for it (each Nasdaq tier has one: NasdaqGS); the name itself when unknown."""
	if name in MARKETS:
		return name
	if name in VENUES:
		return VENUES[name]
	return 'NASDAQ' if name.startswith('Nasdaq') else 'NYSE' if name.startswith('NYSE') else name


def flag_from_market(name):
	"""The flag of an exchange by any name it goes by (see code), '' when unknown."""
	market = MARKETS.get(code(name))
	return market.flag if market else ''


def currency_from_market(name):
	"""The currency of an exchange by any name it goes by (see code); None where it quotes in several, or is unknown."""
	market = MARKETS.get(code(name))
	return market.currency if market else None


def flag_from_ticker(ticker):
	"""The flag of a Yahoo ticker's market by its suffix, '' when unknown; a ticker without one is a US listing."""
	return flag_from_market(ticker.split('.')[1]) if '.' in ticker else '🇺🇸'


def transform_to_google(exchange):
	"""Google Finance's code for an exchange by any name it goes by (see code); the name itself when unknown."""
	market = MARKETS.get(code(exchange))
	return (market.google or code(exchange)) if market else exchange


def exchange_human(exchange):
	"""The country an exchange is in ('US', 'AU' and so on: the letters of its flag), or its name when unknown."""
	flag = flag_from_market(exchange)
	return ''.join(chr(ord(letter) - ord('🇦') + ord('A')) for letter in flag) or exchange


def transform_to_yahoo(ticker, market=None):
	"""Yahoo's symbol for a ticker: 'BHP:ASX', 'BHP.ASX' or ('BHP', 'ASX') give 'BHP.AX' (a market by its code in
	MARKETS; a code Yahoo uses itself, like AX, stays as it is). US venues take no suffix, and class shares a dash
	('BRK.B' gives 'BRK-B')."""
	split = ticker.replace(':', '.').split('.')
	if len(split) > 1:
		ticker, market = split[0], split[1]
	if not market:
		return ticker
	if market in {'A', 'B', 'C'}: # class shares
		return ticker + '-' + market
	known = MARKETS.get(market)
	suffix = market if known is None or known.yahoo is None else known.yahoo
	return ticker + '.' + suffix if suffix else ticker
