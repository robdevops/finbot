"""Markets: flags and currencies by market, exchange names, and ticker translation between Sharesight, Google and Yahoo."""

MARKETS = { # Sharesight market code -> (flag, currency); no currency where a market quotes in several (LSE and HKEX allow non-home currencies)
	'ASX': ('🇦🇺', 'AUD'),
	'BOM': ('🇮🇳', 'INR'), 'NSE': ('🇮🇳', 'INR'),
	'BMV': ('🇲🇽', 'MXN'),
	'BKK': ('🇹🇭', 'THB'),
	'BVMF': ('🇧🇷', 'BRL'),
	'SHE': ('🇨🇳', 'CNY'), 'SHA': ('🇨🇳', 'CNY'),
	'CPSE': ('🇩🇰', 'DKK'),
	**dict.fromkeys(('EURONEXT', 'AMS', 'ATH', 'BIT', 'BME', 'DUB', 'EBR', 'EPA', 'ETR', 'FWB', 'FRA', 'VIE'), ('🇪🇺', 'EUR')),
	'HKG': ('🇭🇰', None),
	'ICSE': ('🇮🇸', 'ISK'),
	'JSE': ('🇿🇦', 'ZAR'),
	'KRX': ('🇰🇷', 'KRW'), 'KOSDAQ': ('🇰🇷', 'KRW'),
	'LSE': ('🇬🇧', 'GBP'), # better than trades.py using brokerage_currency_code, which is AUD on CMC
	'MISX': ('🇷🇺', 'RUB'),
	'OM': ('🇸🇪', 'SEK'), 'STO': ('🇸🇪', 'SEK'),
	'SWX': ('🇨🇭', 'CHF'), 'VTX': ('🇨🇭', 'CHF'),
	'TAI': ('🇹🇼', 'TWD'), 'TPE': ('🇹🇼', 'TWD'),
	'TASE': ('🇮🇱', 'ILS'),
	'NZX': ('🇳🇿', 'NZD'),
	'OB': ('🇳🇴', 'NOK'),
	'SGX': ('🇸🇬', 'SGD'),
	'TSE': ('🇯🇵', 'JPY'),
	'TSX': ('🇨🇦', 'CAD'),
	'NASDAQ': ('🇺🇸', 'USD'), 'NYSE': ('🇺🇸', 'USD'), 'BATS': ('🇺🇸', 'USD'), 'AMEX': ('🇺🇸', None),
	'WAR': ('🇵🇱', 'PLN'),
}

YAHOO_COUNTRY = { # country -> its Yahoo ticker suffix, for a listing that has none (cal.py)
	'Argentina': 'BA',
	'Austria': 'VI',
	'Australia': 'AX',
	'Belgium': 'BR',
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
	'Ireland': 'IR',
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
	'Saudi Arabia': 'SR',
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

def flag_from_market(market):
	"""The flag of a market by its Sharesight code: US for the NASDAQ and NYSE variants, '' when unknown."""
	if market in MARKETS:
		return MARKETS[market][0]
	return '🇺🇸' if market.lower().startswith(('nasdaq', 'nyse')) else ''

TICKER_FLAGS = {'AS': '🇳🇱', 'AX': '🇦🇺', 'HK': '🇭🇰', 'KS': '🇰🇷', 'KQ': '🇰🇷', 'L': '🇬🇧', 'NS': '🇮🇳', 'NZ': '🇳🇿', 'SI': '🇸🇬', 'T': '🇯🇵', 'TA': '🇮🇱',
	'TW': '🇹🇼', 'TWO': '🇹🇼', 'TO': '🇨🇦'} # Yahoo suffix -> flag

def flag_from_ticker(ticker):
	"""The flag of a Yahoo ticker's market suffix, '' when unknown; a ticker without one is a US listing."""
	return TICKER_FLAGS.get(ticker.split('.')[1], '') if '.' in ticker else '🇺🇸'

def currency_from_market(market):
	"""The currency of a market by its Sharesight code; None where it quotes in several, or is unknown."""
	return MARKETS.get(market, (None, None))[1]

VENUES = { # the names Yahoo, Sharesight and Google give an exchange -> (Google Finance code, country)
	**dict.fromkeys(('OTC', 'PNK', 'Other OTC', 'OTCPK'), ('OTCMKTS', None)),
	**dict.fromkeys(('TO', 'TOR', 'Toronto'), ('TSE', 'CA')),
	**dict.fromkeys(('TW', 'TWO', 'TAI', 'Taiwan', 'Taipei Exchange', 'Taipei'), ('TPE', 'TW')),
	**dict.fromkeys(('HK', 'HKG', 'HKSE'), ('HKG', 'HK')),
	**dict.fromkeys(('KQ', 'KOE', 'KOSDAQ'), ('KOSDAQ', 'KR')),
	**dict.fromkeys(('KS', 'KRX', 'KSE', 'KSC'), ('KRX', 'KR')),
	**dict.fromkeys(('L', 'LSE', 'London'), ('LON', 'UK')),
	**dict.fromkeys(('T', 'TYO', 'JPX', 'Tokyo'), ('TYO', 'JP')),
	**dict.fromkeys(('TA', 'TLV', 'Tel Aviv'), ('TLV', 'IL')),
	**dict.fromkeys(('NZSE', 'NZE', 'New Zealand', 'Auckland'), (None, 'NZ')),
}

def transform_to_google(exchange):
	"""Google Finance's code for an exchange, as Yahoo, Sharesight or Google name it; the name itself when unknown."""
	if 'Nasdaq' in exchange:
		return 'NASDAQ'
	if exchange == 'Cboe US':
		return 'BATS'
	return VENUES.get(exchange, (None, None))[0] or exchange

def exchange_human(exchange):
	"""The country an exchange is in ('US', 'AU' and so on), or its name when unknown."""
	if 'Nasdaq' in exchange or 'NYSE' in exchange or 'Other OTC' in exchange:
		return 'US'
	return VENUES.get(exchange, (None, None))[1] or exchange

YAHOO_SUFFIX = { # exchange code (Sharesight, Google) -> Yahoo's ticker suffix
	'ASX': 'AX', 'HKG': 'HK', 'KRX': 'KS', 'KOSDAQ': 'KQ', 'LSE': 'L', 'NZX': 'NZ', 'SGX': 'SI',
	'TAI': 'TW', # Taiwan in YF and Sharesight; TPE in GF
	'TPE': 'TWO', # Taipei in YF, Taiwan in GF (GF format will not work as input); missing from GF
	'TSE': 'T', 'TYO': 'T', # Tokyo: TSE in Sharesight (Google's TSE is Toronto, which Sharesight calls TSX), TYO in GF
	'TSX': 'TO', 'TLV': 'TA',
}

def transform_to_yahoo(ticker, market=None):
	"""Yahoo's symbol for a ticker: 'BHP:ASX', 'BHP.ASX' or ('BHP', 'ASX') give 'BHP.AX'. US venues take no suffix, and
	class shares a dash ('BRK.B' gives 'BRK-B')."""
	split = ticker.replace(':', '.').split('.')
	if len(split) > 1:
		ticker = split[0]
		market = split[1]
	if not market:
		return ticker
	market = YAHOO_SUFFIX.get(market, market)
	if market in {'NASDAQ', 'NYSE', 'BATS', 'OTCMKTS', 'AMEX', 'NYSEARCA'}: # US venues: Yahoo symbols carry no suffix
		return ticker
	if market in {'A', 'B', 'C'}: # class shares
		return ticker + '-' + market
	return ticker + '.' + market
