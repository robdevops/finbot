"""Pure helpers (lib/markets.py, formats.py, links.py) and the cache and state files: table-driven cases."""
import datetime, json, threading, unittest
from pathlib import Path
from tests.common import *
from lib import when


class Parsing(unittest.TestCase):
	def test_days_from_human_days(self):
		"""A period in days from 7, 7d, 2w, 3m, 1y or ytd."""
		for arg, days in (('7', 7), ('7d', 7), ('7D', 7), ('2w', 14), ('3m', 90), ('1y', 365), ('0', 0)):
			with self.subTest(arg=arg):
				self.assertEqual(formats.days_from_human_days(arg), days)
		today = datetime.date.today()
		self.assertEqual(formats.days_from_human_days('ytd'), (today - today.replace(month=1, day=1)).days)

	def test_days_from_human_days_rejects_non_periods(self):
		"""A ticker, an empty string or a malformed period is a ValueError, not a period."""
		for arg in ('AAPL', '', 'x5d', '1.5y', 'week'):
			with self.subTest(arg=arg), self.assertRaises(ValueError):
				formats.days_from_human_days(arg)

	def test_seconds_from_human(self):
		"""A time in seconds from 180s or 24h, or any period in days (7d, 2w, 3m, 1y, 7); anything else is a
		ValueError."""
		for arg, seconds in (('180s', 180), ('24H', 86400), ('7d', 7 * 86400), ('2w', 14 * 86400), ('3m', 90 * 86400),
				('1y', 365 * 86400), ('7', 7 * 86400), ('0s', 0)):
			with self.subTest(arg=arg):
				self.assertEqual(formats.seconds_from_human(arg), seconds)
		for arg in ('', 's', 'h5', '1.5h', '-5s', '5x', 'AAPL'):
			with self.subTest(arg=arg), self.assertRaises(ValueError):
				formats.seconds_from_human(arg)

	def test_transform_to_yahoo(self):
		"""Sharesight and Google tickers as Yahoo's: suffixes by market, none for US venues, a dash for class shares."""
		for args, expected in ((('AAPL',), 'AAPL'), (('FANG', 'ASX'), 'FANG.AX'), (('ARM', 'NASDAQ'), 'ARM'),
				(('ARM:NASDAQ',), 'ARM'), (('BHP.AX',), 'BHP.AX'), (('0700', 'HKG'), '0700.HK'),
				(('BRK', 'B'), 'BRK-B'), (('2330', 'TAI'), '2330.TW'), (('VOD', 'LSE'), 'VOD.L'),
				(('7203', 'TYO'), '7203.T'),
				(('SHOP', 'TSE'), 'SHOP.TO'), (('SHOP', 'TSX'), 'SHOP.TO'), (('AIR', 'NZX'), 'AIR.NZ'),
				(('D05', 'SGX'), 'D05.SI'), (('SAP', 'XETR'), 'SAP.DE'), (('SAP', 'ETR'), 'SAP.DE'),
				(('NSRGY', 'OTC'), 'NSRGY'), (('NESN', 'SWX'), 'NESN.SW'), (('SAP:FRA',), 'SAP.F')):
			with self.subTest(args=args):
				self.assertEqual(markets.transform_to_yahoo(*args), expected)

	def test_each_market_has_its_own_flag_and_currency(self):
		"""Sharesight's market codes each have their own flag and currency, the same as their Yahoo tickers' flags:
		TSE is Toronto and TYO Tokyo (as Sharesight has them), SGX Singapore, XETR Germany."""
		for market, ticker, flag, currency in (('TSE', 'SHOP.TO', '🇨🇦', 'CAD'), ('TYO', '7203.T', '🇯🇵', 'JPY'),
				('TSX', 'SHOP.TO', '🇨🇦', 'CAD'), ('NZX', 'AIR.NZ', '🇳🇿', 'NZD'), ('SGX', 'D05.SI', '🇸🇬', 'SGD'),
				('CPSE', 'NOVO-B.CO', '🇩🇰', 'DKK'), ('XETR', 'SAP.DE', '🇩🇪', 'EUR'), ('AMS', 'ASML.AS', '🇳🇱', 'EUR'),
				('EURONEXT', None, '🇪🇺', 'EUR'), ('HKG', '0700.HK', '🇭🇰', None), ('NASDAQ', 'AAPL', '🇺🇸', 'USD')):
			with self.subTest(market=market):
				self.assertEqual((markets.flag_from_market(market), markets.currency_from_market(market)),
					(flag, currency))
				if ticker:
					self.assertEqual(markets.flag_from_ticker(ticker), flag)

	def test_an_exchange_by_any_of_its_names(self):
		"""Yahoo's name for an exchange, its tickers' suffix or Sharesight's code give the same country, flag and
		Google code; a name nobody knows stays as it is."""
		for names, country, google in ((('NasdaqGS', 'NasdaqCM', 'NASDAQ'), 'US', 'NASDAQ'),
				(('NYSEArca', 'NYSEARCA'), 'US', 'NYSEARCA'), (('Cboe US', 'BATS'), 'US', 'BATS'),
				(('Other OTC', 'OTC'), 'US', 'OTCMKTS'), (('ASX', 'AX'), 'AU', 'ASX'),
				(('Toronto', 'TO', 'TSE'), 'CA', 'TSE'), (('London', 'L', 'LSE'), 'GB', 'LON'),
				(('XETRA', 'DE', 'XETR'), 'DE', 'ETR'), (('NZSE', 'NZ'), 'NZ', 'NZE'),
				(('Taiwan', 'TW', 'TAI'), 'TW', 'TPE'),
				(('Unheard of',), 'Unheard of', 'Unheard of')):
			for name in names:
				with self.subTest(name=name):
					found = markets.exchange_human(name), markets.transform_to_google(name)
					self.assertEqual(found, (country, google))
		self.assertEqual(markets.flag_from_market('NasdaqGS'), '🇺🇸') # a trade's market, with trades_use_yahoo

	def test_no_yahoo_suffix_is_also_a_market_code(self):
		"""A Yahoo suffix that is also a code in MARKETS would name two markets: BHP.AX typed in a chat must stay AX."""
		suffixes = {market.yahoo for market in markets.MARKETS.values()}
		self.assertEqual(suffixes & set(markets.MARKETS), set())

	def test_make_paragraphs_keeps_every_word(self):
		"""make_paragraphs breaks a long description into paragraphs at sentence ends without losing a word."""
		self.assertEqual(formats.make_paragraphs('Acme makes widgets. It sells them.'),
			'Acme makes widgets. It sells them.')
		long = ' '.join(['word'] * 22) + ' end. Tail sentence here.'
		self.assertEqual(formats.make_paragraphs(long), ' '.join(['word'] * 22) + ' end.\n\nTail sentence here.')

	def test_transform_title(self):
		"""Company names lose shouting and trailing legal suffixes (Inc, FPO, SE, a final &), with no double spaces."""
		self.assertEqual(formats.transform_title('APPLE INC'), 'Apple')
		self.assertEqual(formats.transform_title('Acme FPO'), 'Acme')
		self.assertEqual(formats.transform_title('Mixed Case Name'), 'Mixed Case Name')
		for title, expected in (('Allianz Se', 'Allianz'), ('Foo SE AG', 'Foo'),
			('Johnson & Johnson &', 'Johnson & Johnson'),
								('Black and White and', 'Black and White'), ('Big Holdings Things Ltd', 'Big Things')):
			with self.subTest(title=title): # a suffix comes off the end only; no run of spaces is left behind
				self.assertEqual(formats.transform_title(title), expected)

	def test_a_name_in_a_list_is_cut_to_fit_a_phone(self):
		"""A name over 30 characters is cut at a word, with an ellipsis (mid-word where a word break would cut it too
		short); a shorter one stays whole."""
		for name, shown in (('Global X Asia Semiconductor ETF', 'Global X Asia Semiconductor…'),
				('Global X China EV ETF', 'Global X China EV ETF'), ('A' * 40, 'A' * 29 + '…'),
				('Short Supercalifragilisticexpialidocious', 'Short Supercalifragilisticexp…')):
			with self.subTest(name=name):
				self.assertEqual(formats.short_name(name), shown)
				self.assertLessEqual(len(formats.short_name(name)), formats.NAME_LIMIT)

	def test_a_funds_name_loses_its_trusts(self):
		"""A fund's name loses the trust's before it, a repeated brand or ETF, and OFC; a company's repeated word, or a
		fund's own Trust, stays."""
		for title, expected in (('Global X ETF Series OFC Global X China EV ETF', 'Global X China EV ETF'),
				('iShares Trust iShares Core S&P 500 ETF', 'iShares Core S&P 500 ETF'),
				('SPDR Series Trust SPDR S&P Biotech ETF', 'SPDR S&P Biotech ETF'),
				('Betashares ETF Trust Global Cybersecurity ETF', 'Betashares Global Cybersecurity ETF'),
				('Global X Uranium ETF ETF', 'Global X Uranium ETF'),
				('VanEck Semiconductor ETF', 'VanEck Semiconductor ETF'),
				('SPDR S&P 500 ETF Trust', 'SPDR S&P 500 ETF Trust'), ('Johnson & Johnson', 'Johnson & Johnson'),
				('Johnson & Johnson Health', 'Johnson & Johnson Health')):
			with self.subTest(title=title):
				self.assertEqual(formats.transform_title(title), expected)


class Formatting(unittest.TestCase):
	def test_signed_percent(self):
		"""A signed percent: a plus for gains, thousands separators, and the decimals asked for."""
		for value, decimals, expected in ((12, None, '+12%'), (-3.5, None, '-3.5%'), (0, None, '0%'),
			(1234, None, '+1,234%'),
										  (2.345, 1, '+2.3%'), (-0.04, 1, '-0.0%')):
			with self.subTest(value=value):
				self.assertEqual(formats.signed_percent(value, decimals), expected)

	def test_days_english(self):
		"""None and 0 are today; 1 and 7 days are the past day and week."""
		for days, expected in ((None, 'today'), (0, 'today'), (1, 'the past day'), (7, 'the past week')):
			with self.subTest(days=days):
				self.assertEqual(formats.days_english(days), expected)

	def test_date_range_english(self):
		"""A span ending on a date, in words, across a year end too; a period is required."""
		end = datetime.date(2026, 10, 5)
		self.assertEqual(formats.date_range_english(7, end), '28 Sep - 5 Oct 2026')
		self.assertEqual(formats.date_range_english(30, end), '5 Sep - 5 Oct 2026')
		# crosses a year
		self.assertEqual(formats.date_range_english(10, datetime.date(2026, 1, 5)), '26 Dec 2025 - 5 Jan 2026')
		with self.assertRaises(TypeError):
			formats.date_range_english(None, end) # callers must pass a period

	def test_button_data_reads_back(self):
		"""A button's data says what was pressed: a period button of a known kind and period (as keyboard() makes
		them), a .jobs menu's button of a known screen made of plain letters and digits, and nothing for anything else:
		the job buttons of older lists (j|, e|) included."""
		self.assertEqual([buttons.parse(button.data) for button in buttons.keyboard('l', ['5', '0'])[0]],
			[buttons.ChartPress('l', key, '5,0') for key in 'dwmyx'])
		self.assertEqual(buttons.parse(buttons.menu_button('1 ✅ trades', 'on', [0, 1], 'abcd').data),
			buttons.MenuPress('on', ('0', '1'), 'abcd'))
		self.assertEqual(buttons.parse('m|add|abcd'), buttons.MenuPress('add', (), 'abcd'))
		self.assertEqual(buttons.menu_button('x' * 50, 'top', [0], 'abcd').label, 'x' * 40)
		for data in ('c|c|d|T1', 'c|z|w|T1', 'c|c|w', 'x|h|w|T1', '', 'c', 'm|zz|0|abcd', 'm|on', 'm|on|0|a b',
				'm|on|٨|abcd', 'm|on|0|1|' + 'a' * 60, 'j|8|abcd', 'e|8|abcd'):
			with self.subTest(data=data):
				self.assertIsNone(buttons.parse(data))

	def test_a_pickers_data_reads_back_in_few_bytes(self):
		"""A picker's button says what it asks for, with up to 32 ticked tickers in 64 bytes; data of no picker, with
		an act or a command it has not, is nothing, and only a refused tick is an alert."""
		press = buttons.PickPress('c', 's', 'x', 1, 2 ** 32 - 1, 'r31', 'a1b2')
		button = buttons.pick_button('x' * 99, press)
		self.assertEqual((buttons.parse(button.data), len(button.label), len(button.data)), (press, 40, 27))
		for data in ('k|z|0|x|0|0|p0|a1b2', 'k|c|0|x|0|0|z0|a1b2', 'k|c|0|x|0|zz|p0|a1b2', 'k|c|0|q|0|0|p0|a1b2',
				'k|c|0|x|0|0|p0', 'k|c|0|x|0|0|p0|a-b2', 'k|c|0|x|0|0|p|a1b2', 'k|c|0|x|0|3|z0|a1b2'):
			with self.subTest(data=data):
				self.assertIsNone(buttons.parse(data))
		acts = ('p0', 'm1', 'n1', 'r2', 'h0', 'f0')
		self.assertEqual([buttons.toast(f'k|c|0|x|0|3|{act}|a1b2') for act in acts],
			['Updating…', 'Updating…', 'Updating…', 'Loading…', 'Loading…', buttons.TOO_MANY])
		self.assertEqual([buttons.alert(f'k|c|0|x|0|3|{act}|a1b2') for act in ('m0', 'f0')], [False, True])

	def test_a_press_is_told_what_is_coming_from_its_data_alone(self):
		"""The toast a press gets as it arrives: the period a period button loads, 'Updating…' for the .jobs menu's, and
		none for other data (the older lists' job buttons among them)."""
		self.assertEqual([buttons.toast(button.data) for button in buttons.keyboard('l', ['5', '0'])[0]],
			['Loading 1D…', 'Loading 7D…', 'Loading 1M…', 'Loading 1Y…', 'Loading Max…'])
		self.assertEqual(buttons.toast('m|on|0|1|abcd'), 'Updating…')
		for data in ('c|f|d|', 'c|zz|m|T1', '', 'x', 'j|8|abcd', 'e|99|0000'):
			with self.subTest(data=data):
				self.assertIsNone(buttons.toast(data))

	def test_a_message_takes_links_and_italics_in_each_networks_markup(self):
		"""In a message job's text, [text](url) is a link and a line in _underscores_ is in italics, an underscore in a
		url included; the rest is text, escaped where the network needs it; plain() keeps the words alone."""
		line = '_See [R&D notes](https://x.example/a_b) & more_'
		self.assertEqual(formats.markup(line, TELEGRAM),
			'<i>See <a href="https://x.example/a_b">R&amp;D notes</a> &amp; more</i>')
		self.assertEqual(formats.markup(line, SLACK), '_See <https://x.example/a_b|R&amp;D notes> &amp; more_')
		self.assertEqual(formats.markup(line, DISCORD), '_See [R&D notes](<https://x.example/a_b>) & more_')
		self.assertEqual(formats.markup('a_b_c and _', TELEGRAM), 'a_b_c and _') # italic only when the whole line is
		self.assertEqual(formats.plain(line), 'See R&D notes & more')

	def test_strip_url(self):
		"""A link's text is its address without the scheme or www."""
		for url, text in (('https://www.apple.com', 'apple.com'), ('http://example.org/a?b', 'example.org/a?b'),
				('https://www3.example.com', 'www3.example.com'), ('apple.com', 'apple.com')):
			with self.subTest(url=url):
				self.assertEqual(formats.strip_url(url), text)

	def test_ordinal(self):
		"""Ordinal suffixes, the teens included."""
		for number, suffix in ((1, 'st'), (2, 'nd'), (3, 'rd'), (4, 'th'), (11, 'th'), (12, 'th'), (13, 'th'),
				(21, 'st'), (112, 'th')):
			with self.subTest(number=number):
				self.assertEqual(formats.ordinal(number), suffix)

	def test_get_emoji(self):
		"""An arrow up for a rise, down for a fall, a square for none."""
		self.assertEqual([formats.get_emoji(n) for n in (1, -1, 0)], ['🔼', '🔻', '▪️'])

	def test_links_per_service(self):
		"""A link is HTML on Telegram and <url|text> on Slack."""
		telegram_link = TELEGRAM.link('https://example.com/x', 'text')
		slack_link = SLACK.link('https://example.com/x', 'text')
		self.assertIn('<a href=', telegram_link)
		self.assertIn('|text', slack_link)

	def test_flags_for_known_and_unknown_markets(self):
		"""Known suffixes and US tickers have flags; an unknown suffix gives a string, not a crash."""
		self.assertTrue(markets.flag_from_ticker('BHP.AX'))
		self.assertTrue(markets.flag_from_ticker('AAPL'))
		self.assertIsInstance(markets.flag_from_ticker('XYZ.ZZ'), str) # unknown suffix must not crash


class Links(FinbotCase):
	def test_google_links_go_to_yahoo_where_google_has_no_page(self):
		"""With the google provider an index, a crypto pair and a Taipei listing link to Yahoo; the rest to Google, with
		the chart window nearest the period."""
		self.settings(hyperlinkProvider='google')
		for symbol, exchange in (('^GSPC', 'SNP'), ('BTC-USD', 'CCC'), ('6488.TWO', 'Taipei Exchange')):
			with self.subTest(symbol=symbol):
				self.assertIn('au.finance.yahoo.com/quote/' + symbol, links.finance_link(symbol, exchange, TELEGRAM))
		month = links.finance_link('BHP.AX', 'ASX', TELEGRAM, days=30)
		self.assertIn('google.com/finance/quote/BHP:ASX?window=1M', month)

	def test_without_hyperlinks_a_link_is_its_text(self):
		"""With the hyperlink setting off, either provider shows the link's text: BHP, not BHP.AX."""
		self.settings(hyperlink=False)
		for provider in ('google', 'yahoo'):
			with self.subTest(provider=provider):
				self.settings(hyperlinkProvider=provider)
				self.assertEqual(links.finance_link('BHP.AX', 'ASX', TELEGRAM), 'BHP')


class StateFiles(FinbotCase):
	def test_json_roundtrip_and_missing_file(self):
		"""A state file reads back what was saved; a missing one is None."""
		self.assertIsNone(state.load('absent.json'))
		state.save('state.json', {'a': [1, 2]})
		self.assertEqual(state.load('state.json'), {'a': [1, 2]})

	def test_a_failed_write_leaves_the_old_file_and_the_umask_alone(self):
		"""A write failing at replace or fsync keeps the old file and no temp file; umask untouched, files 0640."""
		state.save('state.json', {'a': 1})
		path = Path(config.env.data_dir, 'state.json')
		previous = os.umask(0o027)
		self.addCleanup(os.umask, previous)
		def disk_full(*a, **k):
			"""Fail like a full disk."""
			raise OSError(28, 'No space left on device')
		for broken in ('replace', 'fsync'):
			with self.subTest(broken=broken), mock.patch.object(cache.os, broken, disk_full):
				with self.assertRaises(OSError):
					state.save('state.json', {'a': 2})
			self.assertEqual(json.loads(path.read_text()), {'a': 1}) # whole or not at all
			self.assertEqual(os.listdir(config.env.data_dir), ['state.json']) # no temp file left behind
		with mock.patch.object(cache.os, 'replace', disk_full), self.assertRaises(OSError):
			cache.write_bytes('img.png', io.BytesIO(b'png'))
		self.assertEqual(os.listdir(config.env.data_dir), ['state.json'])
		self.assertEqual(os.umask(0o027), 0o027) # the umask was not touched
		state.save('state.json', {'a': 3})
		self.assertEqual((json.loads(path.read_text()), oct(path.stat().st_mode & 0o777)), ({'a': 3}, '0o640'))

	def test_edit_writes_only_a_change_and_never_changes_the_default(self):
		"""state.edit writes only if the block changed the data without failing, and never alters the default given."""
		default = {'seen': []}
		with state.edit('edit.json', default):
			pass
		self.assertIsNone(state.load('edit.json')) # nothing changed, nothing written
		with state.edit('edit.json', default) as data:
			data['seen'].append(1)
		self.assertEqual((state.load('edit.json'), default), ({'seen': [1]}, {'seen': []}))
		with self.assertRaises(ValueError), state.edit('edit.json', default) as data:
			data['seen'].append(2)
			raise ValueError
		self.assertEqual(state.load('edit.json'), {'seen': [1]}) # a block that fails writes nothing

	def test_edits_at_once_all_count(self):
		"""Each edit reads the file once the previous one wrote, so none overwrites another with stale data."""
		def edit(key):
			"""Set data[key] slowly, so that the other edits start meanwhile."""
			with state.edit('edit.json', {}) as data:
				time.sleep(0.01) # the other edits start meanwhile
				data[key] = True
		threads = [threading.Thread(target=edit, args=(key,)) for key in 'abc']
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()
		self.assertEqual(state.load('edit.json'), dict.fromkeys('abc', True))

	def test_read_cache_missing_or_expired_is_falsy(self):
		"""A missing or expired cache file reads as nothing."""
		self.assertFalse(cache.read('absent.json', 60))
		cache.write('old.json', {'a': 1})
		self.assertFalse(cache.read('old.json', -1)) # already expired

	def test_a_cache_file_that_goes_while_it_is_read_is_a_miss(self):
		"""A cache file deleted between the age check and the read (by cleanup or a flush) is a miss, not an error."""
		cache.write('gone.json', {'a': 1})
		real = Path.read_text
		def vanish(path, *a, **k):
			"""Delete gone.json as it is read, as cleanup or a flush might between the age check and the read."""
			if path.name == 'gone.json':
				path.unlink()
				raise FileNotFoundError(path)
			return real(path, *a, **k)
		with mock.patch.object(Path, 'read_text', vanish):
			self.assertIsNone(cache.read('gone.json', 60))

	def test_binary_cache_roundtrip(self):
		"""A drawn chart reads back from the cache as written."""
		self.assertFalse(cache.read_bytes('absent.png'))
		cache.write_bytes('img.png', io.BytesIO(b'png-bytes'))
		self.assertEqual(cache.read_bytes('img.png').read(), b'png-bytes')

	def test_holdings_and_watchlist_without_a_watchlist_file(self):
		"""On the first run there is no watchlist file: the holdings alone, GOOGL dropped when GOOG is held. A chat's
		watchlist adds to the holdings in that chat only; yahoo_warm keeps every chat's warm."""
		self.patch(sharesight, 'tickers', lambda: ['AAPL', 'GOOG', 'GOOGL'])
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		self.assertEqual(watchlist.with_holdings('telegram:1'), ['AAPL', 'GOOG']) # GOOGL dropped when GOOG is present
		self.assertEqual((watchlist.all_watched(), watchlist.all_followed()), ([], ['AAPL', 'GOOG']))
		watchlist.add('telegram:1', 'MSFT')
		watchlist.add('slack:C1', 'NVDA')
		watchlist.add('slack:C1', 'MSFT')
		self.assertEqual(watchlist.with_holdings('telegram:1'), ['AAPL', 'GOOG', 'MSFT'])
		self.assertEqual(watchlist.with_holdings('slack:C1'), ['AAPL', 'GOOG', 'MSFT', 'NVDA'])
		self.assertEqual(watchlist.with_holdings('discord:7'), ['AAPL', 'GOOG'])
		self.assertEqual(watchlist.all_watched(), ['MSFT', 'NVDA'])
		self.assertEqual(watchlist.all_followed(), ['AAPL', 'GOOG', 'MSFT', 'NVDA'])


class Schedules(unittest.TestCase):
	"""lib/when.py: schedules read from English, said back in words, and their next runs, daylight saving included."""
	MEL, SYD, NY = 'Australia/Melbourne', 'Australia/Sydney', 'America/New_York'
	OCTOBER = datetime.datetime(2026, 10, 15, tzinfo=when.UTC) # Melbourne and Sydney on summer time, New York too
	TRADES = {'span': ['mon 09:00', 'sat 15:00'], 'every': 20, 'zone': SYD}

	def at(self, zone, *args):
		"""A moment by a zone's clock: at(MEL, 2026, 10, 4, 3, 0)."""
		return datetime.datetime(*args, tzinfo=zoneinfo.ZoneInfo(zone))

	def test_english_becomes_a_schedule(self):
		"""Each form a chat may type becomes the schedule it says, in the zone it names or the timezone setting's."""
		for text, stored in (('daily', {'days': 'daily', 'at': '09:00'}), ('at 9am', {'days': 'daily', 'at': '09:00'}),
				('weekdays at 4:30pm', {'days': 'weekdays', 'at': '16:30'}),
				('weekly', {'days': ['sat'], 'at': '09:00'}),
				('every saturday at 9am', {'days': ['sat'], 'at': '09:00'}),
				('Saturdays at 21:30', {'days': ['sat'], 'at': '21:30'}),
				('weekly on sunday at 8:30am', {'days': ['sun'], 'at': '08:30'}),
				('tue-sat at 8:30am', {'days': ['tue', 'wed', 'thu', 'fri', 'sat'], 'at': '08:30'}),
				('mon to fri at 9', {'days': ['mon', 'tue', 'wed', 'thu', 'fri'], 'at': '09:00'}),
				('weekends at 10am', {'days': ['sat', 'sun'], 'at': '10:00'}),
				('monthly', {'days': {'day': 1}, 'at': '09:00'}),
				('first day of each month at 9am', {'days': {'day': 1}, 'at': '09:00'}),
				('1st of the month', {'days': {'day': 1}, 'at': '09:00'}),
				('monthly on the 2nd at 8:30am', {'days': {'day': 2}, 'at': '08:30'}),
				('quarterly', {'days': {'day': 1, 'months': [1, 4, 7, 10]}, 'at': '09:00'}),
				('quarterly on the 2nd', {'days': {'day': 2, 'months': [1, 4, 7, 10]}, 'at': '09:00'}),
				('quarterly from feb on the 15th', {'days': {'day': 15, 'months': [2, 5, 8, 11]}, 'at': '09:00'}),
				('bi-annual', {'days': {'day': 1, 'months': [1, 7]}, 'at': '09:00'}),
				('half-yearly', {'days': {'day': 1, 'months': [1, 7]}, 'at': '09:00'}),
				('bi-annual starting in march', {'days': {'day': 1, 'months': [3, 9]}, 'at': '09:00'}),
				('annual from aug', {'days': {'day': 1, 'months': [8]}, 'at': '09:00'}),
				('annual', {'days': {'day': 1, 'months': [1]}, 'at': '09:00'}),
				('every 31 mar at 8:30am', {'days': {'day': 31, 'months': [3]}, 'at': '08:30'}),
				('on 28 oct 2026', {'days': {'date': '2026-10-28'}, 'at': '09:00'}),
				('every 20 mins', {'days': 'daily', 'every': 20}),
				('every 45 minutes weekdays', {'days': 'weekdays', 'every': 45}),
				('hourly', {'days': 'daily', 'every': 60}),
				('every 2 hours between 9am and 5pm', {'days': 'daily', 'every': 120, 'from': '09:00', 'to': '17:00'}),
				('hourly at :01 weekdays from 10am to 9pm',
					{'days': 'weekdays', 'every': 60, 'from': '10:01', 'to': '21:01'}),
				('every 20 mins from mon 9am to sat 3pm', {'span': ['mon 09:00', 'sat 15:00'], 'every': 20}),
				('weekdays at 4:30pm New York', {'days': 'weekdays', 'at': '16:30', 'zone': self.NY}),
				('daily at 9am EST', {'days': 'daily', 'at': '09:00', 'zone': self.NY}),
				('daily at 9am america/new_york', {'days': 'daily', 'at': '09:00', 'zone': self.NY}),
				('daily at 21:30 UTC', {'days': 'daily', 'at': '21:30', 'zone': 'UTC'}),
				('saturdays at 9am hong kong', {'days': ['sat'], 'at': '09:00', 'zone': 'Asia/Hong_Kong'})):
			with self.subTest(text=text):
				self.assertEqual(when.parse(text, self.MEL).to_json(), {'zone': self.MEL, **stored})

	def test_what_is_no_schedule_is_refused_with_examples(self):
		"""Unreadable words, times and dates that are none, and a repeat at a time of day are refused, with examples."""
		for text in ('fortnightly', 'at 25:00', 'at 13pm', 'every 31 feb', 'every 20 mins at 9am',
				'weekly from 9am to 5pm', 'daily at 9am Atlantis', '', 'every 0 mins', 'the 32nd of each month',
				'monthly; rm -rf /'):
			with self.subTest(text=text):
				with self.assertRaises(when.ScheduleError) as caught:
					when.parse(text, self.MEL)
				self.assertIn('For example: daily at 9am', str(caught.exception))

	def test_a_schedule_says_itself_by_its_own_zones_clock(self):
		"""In a Melbourne chat in mid-October: Melbourne's zone in plain local time, UTC in 24 hours, another zone by
		its place, with the local time beside it only where the clocks differ, its days moved across midnight."""
		syd, ny = self.SYD, self.NY
		for stored, words in ((self.TRADES, 'every 20 mins, Mon 9am – Sat 3pm'),
				({'days': 'weekdays', 'at': '13:00', 'zone': syd}, 'weekdays at 1:00pm'),
				({'days': 'weekdays', 'at': '12:45', 'zone': ny},
					'weekdays at 12:45pm New York (3:45am local, Tue–Sat)'),
				({'days': 'weekdays', 'at': '07:15', 'zone': ny}, 'weekdays at 7:15am New York (10:15pm local)'),
				({'days': 'weekdays', 'at': '16:30', 'zone': 'Asia/Hong_Kong'},
					'weekdays at 4:30pm Hong Kong (7:30pm local)'),
				({'days': 'weekdays', 'at': '17:00', 'zone': 'Europe/London'},
					'weekdays at 5:00pm London (3:00am local, Tue–Sat)'),
				({'days': ['tue', 'wed', 'thu', 'fri', 'sat'], 'at': '08:30', 'zone': syd}, 'Tue–Sat at 8:30am'),
				({'days': 'weekdays', 'every': 60, 'from': '10:01', 'to': '21:01', 'zone': syd},
					'hourly at :01, weekdays 10am–9pm'),
				({'days': ['sun'], 'at': '08:30', 'zone': syd}, 'weekly, Sundays at 8:30am'),
				({'days': {'day': 2}, 'at': '08:30', 'zone': syd}, 'monthly, the 2nd at 8:30am'),
				({'days': {'day': 2, 'months': [1, 4, 7, 10]}, 'at': '08:30', 'zone': syd},
					'quarterly, 2 Jan/Apr/Jul/Oct at 8:30am'),
				({'days': {'day': 2, 'months': [1, 7]}, 'at': '08:30', 'zone': syd},
					'bi-annual, 2 Jan and 2 Jul at 8:30am'),
				({'days': {'day': 15, 'months': [2, 5, 8, 11]}, 'at': '09:00', 'zone': self.MEL},
					'quarterly, 15 Feb/May/Aug/Nov at 9:00am'),
				({'days': {'day': 1, 'months': [3, 9]}, 'at': '09:00', 'zone': self.MEL},
					'bi-annual, 1 Mar and 1 Sep at 9:00am'),
				({'days': {'day': 1, 'months': [1, 2]}, 'at': '09:00', 'zone': self.MEL},
					'yearly, 1 Jan/Feb at 9:00am'),
				({'days': {'day': 31, 'months': [3]}, 'at': '08:30', 'zone': syd}, 'annual, 31 Mar at 8:30am'),
				({'days': {'date': '2026-10-28'}, 'at': '08:30', 'zone': syd}, 'once, 28 Oct 2026 at 8:30am'),
				({'days': ['sat'], 'at': '09:00', 'zone': self.MEL}, 'weekly, Saturdays at 9:00am'),
				({'days': 'daily', 'at': '21:30', 'zone': 'UTC'}, 'daily at 21:30 UTC'),
				({'every': 30, 'from': '00:14', 'zone': 'UTC'}, 'every 30 mins from :14 UTC'),
				({'every': 480, 'from': '00:07', 'zone': 'UTC'}, 'every 8 hours at :07 UTC'),
				({'days': 'weekdays', 'every': 120, 'from': '09:00', 'to': '17:00', 'zone': self.MEL},
					'every 2 hours, weekdays 9am–5pm')):
			with self.subTest(words=words):
				self.assertEqual(when.Schedule.from_json(stored).describe(self.MEL, self.OCTOBER), words)

	def test_the_local_clock_beside_another_zones(self):
		"""Seen from New York, or by a bot on UTC, a Sydney job shows the local times too: a span moved, the days
		before, UTC in 24 hours."""
		syd = self.SYD
		for stored, local, words in ((self.TRADES, self.NY,
					'every 20 mins, Mon 9am – Sat 3pm Sydney (Sun 6pm – Sat 12am local)'),
				({'days': 'weekdays', 'at': '13:00', 'zone': syd}, self.NY,
					'weekdays at 1:00pm Sydney (10:00pm local, Sun–Thu)'),
				({'days': {'day': 2, 'months': [1]}, 'at': '08:30', 'zone': syd}, self.NY,
					'annual, 2 Jan at 8:30am Sydney (4:30pm local, the day before)'),
				({'days': 'weekdays', 'every': 60, 'from': '10:01', 'to': '21:01', 'zone': syd}, self.NY,
					'hourly at :01, weekdays 10am–9pm Sydney (7pm–6am local)'),
				({'days': 'weekdays', 'at': '13:00', 'zone': syd}, 'UTC', 'weekdays at 1:00pm Sydney (02:00 UTC)')):
			with self.subTest(words=words):
				self.assertEqual(when.Schedule.from_json(stored).describe(local, self.OCTOBER), words)

	def test_the_next_run_of_each_kind(self):
		"""next_after gives the first run after a moment, never at it: a week on, the next month with a 31st, 29
		February years on, a one-off's date and then none, a repeat's next step, within its window or its span."""
		mel, syd, trades = self.MEL, self.SYD, self.TRADES
		window = {'days': 'weekdays', 'every': 60, 'from': '10:01', 'to': '21:01', 'zone': syd}
		once = {'days': {'date': '2026-10-28'}, 'at': '08:30', 'zone': syd}
		for stored, after, run in (({'at': '09:00', 'zone': mel}, (2026, 10, 15, 8), (2026, 10, 15, 9)),
				({'at': '09:00', 'zone': mel}, (2026, 10, 15, 9), (2026, 10, 16, 9)),
				({'days': ['sat'], 'at': '09:00', 'zone': mel}, (2026, 10, 17, 10), (2026, 10, 24, 9)),
				({'days': 'weekdays', 'at': '09:00', 'zone': mel}, (2026, 10, 16, 10), (2026, 10, 19, 9)),
				({'days': {'day': 31}, 'at': '09:00', 'zone': mel}, (2026, 4, 1), (2026, 5, 31, 9)),
				({'days': {'day': 2, 'months': [1, 4, 7, 10]}, 'at': '08:30', 'zone': syd}, (2026, 10, 16),
					(2027, 1, 2, 8, 30)),
				({'days': {'day': 29, 'months': [2]}, 'at': '09:00', 'zone': mel}, (2026, 3, 1), (2028, 2, 29, 9)),
				(once, (2026, 10, 20), (2026, 10, 28, 8, 30)), (once, (2026, 10, 28, 9), None),
				({'every': 20, 'zone': mel}, (2026, 10, 15, 10, 5), (2026, 10, 15, 10, 20)),
				({'every': 45, 'zone': mel}, (2026, 10, 15, 23, 20), (2026, 10, 16, 0, 0)),
				(window, (2026, 10, 16, 21, 0), (2026, 10, 16, 21, 1)),
				(window, (2026, 10, 16, 21, 30), (2026, 10, 19, 10, 1)),
				(trades, (2026, 10, 17, 14, 50), (2026, 10, 17, 15)), (trades, (2026, 10, 17, 15), (2026, 10, 19, 9)),
				(trades, (2026, 10, 14, 23, 50), (2026, 10, 15, 0)),
				(trades, (2026, 10, 19, 8, 59), (2026, 10, 19, 9))):
			schedule = when.Schedule.from_json(stored)
			with self.subTest(stored=stored, after=after):
				expected = run and datetime.datetime(*run, tzinfo=schedule.tz)
				self.assertEqual(schedule.next_after(datetime.datetime(*after, tzinfo=schedule.tz)), expected)

	def test_a_job_keeps_its_zones_clock_through_daylight_saving(self):
		"""4:30pm New York is 4:30pm there on both sides of a change; a time the clocks skip runs at the first minute
		after the gap, and a time they repeat runs once, the first time, as does each step of a repeat."""
		close = when.Schedule.from_json({'days': 'weekdays', 'at': '16:30', 'zone': self.NY})
		friday = close.next_after(self.at(self.NY, 2026, 3, 6, 12)) # New York's clocks go forward on 8 March
		monday = close.next_after(friday)
		self.assertEqual([(run.weekday(), run.hour, run.minute) for run in (friday.astimezone(close.tz),
			monday.astimezone(close.tz))], [(4, 16, 30), (0, 16, 30)])
		self.assertEqual([run.astimezone(when.UTC).hour for run in (friday, monday)], [21, 20])
		self.assertEqual(when.Schedule.from_json({'at': '02:30', 'zone': self.NY}).next_after(
			self.at(self.NY, 2026, 3, 7, 12)), datetime.datetime(2026, 3, 8, 7, 0, tzinfo=when.UTC)) # 3am EDT
		night = when.Schedule.from_json({'at': '02:30', 'zone': self.MEL})
		self.assertEqual(night.next_after(self.at(self.MEL, 2026, 10, 3, 12)), self.at(self.MEL, 2026, 10, 4, 3, 0))
		first = night.next_after(self.at(self.MEL, 2026, 4, 4, 12)) # Melbourne repeats 2:00-2:59 on 5 April
		self.assertEqual(first, datetime.datetime(2026, 4, 4, 15, 30, tzinfo=when.UTC))
		self.assertEqual(night.next_after(first), self.at(self.MEL, 2026, 4, 6, 2, 30))
		steps, seen = when.Schedule.from_json({'every': 20, 'zone': self.MEL}), []
		moment = self.at(self.MEL, 2026, 4, 5, 1, 50)
		for _ in range(5):
			moment = steps.next_after(moment)
			seen.append(f'{moment.astimezone(when.UTC):%H:%M}')
		self.assertEqual(seen, ['15:00', '15:20', '15:40', '17:00', '17:20']) # 2:00-2:40 summer time, then 3am

	def test_a_kept_schedule_reads_back_and_junk_is_refused(self):
		"""to_json and from_json give the same schedule back; a kept schedule that is not one (an edited file) is a
		ScheduleError, never another exception."""
		for text in ('weekdays at 4:30pm New York', 'every 20 mins from mon 9am to sat 3pm', 'quarterly on the 2nd',
				'on 28 oct 2026', 'hourly at :01 weekdays from 10am to 9pm', 'tue-sat at 8:30am'):
			with self.subTest(text=text):
				schedule = when.parse(text, self.MEL)
				self.assertEqual(when.Schedule.from_json(json.loads(json.dumps(schedule.to_json()))), schedule)
		for junk in ([], 'daily', {'days': 'sometimes', 'at': '09:00'}, {'days': ['mon'], 'at': '25:00'},
				{'days': ['funday'], 'at': '09:00'}, {'at': '09:00', 'zone': '../../etc/passwd'},
				{'at': '09:00', 'zone': 5},
				{'span': ['mon 09:00'], 'every': 20}, {'every': True}, {'at': '09:00', 'every': 20},
				{'days': {'day': 'x'}, 'at': '09:00'}, {'days': {'date': '2026-02-30'}, 'at': '09:00'},
				{'days': [['mon']], 'at': '09:00'}, {'at': '9'}):
			with self.subTest(junk=junk), self.assertRaises(when.ScheduleError):
				when.Schedule.from_json(junk)

	def test_how_often_in_a_word(self):
		"""How often a schedule's days come round, in a word; None for several weekdays, and for a span."""
		for text, word in (('daily', 'daily'), ('weekdays', 'weekdays'), ('every sunday', 'weekly'),
				('monthly on the 2nd', 'monthly'), ('quarterly', 'quarterly'), ('bi-annual', 'bi-annual'),
				('quarterly from dec', 'quarterly'), ('bi-annual from mar', 'bi-annual'),
				('annual', 'annual'), ('every 31 mar', 'annual'), ('on 28 oct 2026', 'once'), ('tue-sat', None),
				('every 20 mins from mon 9am to sat 3pm', None)):
			with self.subTest(text=text):
				self.assertEqual(when.parse(text, self.MEL).frequency, word)
		self.assertIsNone(when.Schedule({'day': 1, 'months': (1, 2)}, at=540).frequency) # no cycle: yearly

	def test_a_cycle_runs_from_its_start_month(self):
		"""A quarterly or bi-annual cycle may start in any month: its months are the start and every 3 or 6 months on,
		and its next run is the next of them."""
		self.assertEqual([when.cycle(2, 4), when.cycle(12, 4), when.cycle(7, 2), when.cycle(3, 1)],
			[(2, 5, 8, 11), (3, 6, 9, 12), (1, 7), (3,)])
		self.assertEqual((when.cycle(1, 4), when.cycle(1, 2)), ((1, 4, 7, 10), (1, 7))) # no start month: January
		october = datetime.datetime(2026, 10, 14, tzinfo=zoneinfo.ZoneInfo(self.MEL))
		for text, run in (('quarterly from feb on the 15th', '2026-11-15 09:00'),
				('bi-annual from mar', '2027-03-01 09:00'), ('quarterly', '2027-01-01 09:00')):
			with self.subTest(text=text):
				found = when.parse(text, self.MEL).next_after(october).astimezone(zoneinfo.ZoneInfo(self.MEL))
				self.assertEqual(found.strftime('%Y-%m-%d %H:%M'), run)


if __name__ == '__main__':
	unittest.main()
