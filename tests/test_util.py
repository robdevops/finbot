"""Pure helpers (lib/markets.py, formats.py, links.py) and the cache and state files: table-driven pass and fail cases."""
import datetime, json, threading, unittest
from pathlib import Path
from tests.common import *


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

	def test_transform_to_yahoo(self):
		"""Sharesight and Google tickers as Yahoo's: suffixes by market, none for US venues, a dash for class shares."""
		for args, expected in ((('AAPL',), 'AAPL'), (('FANG', 'ASX'), 'FANG.AX'), (('ARM', 'NASDAQ'), 'ARM'),
							   (('ARM:NASDAQ',), 'ARM'), (('BHP.AX',), 'BHP.AX'), (('0700', 'HKG'), '0700.HK'),
							   (('BRK', 'B'), 'BRK-B'), (('2330', 'TAI'), '2330.TW'), (('VOD', 'LSE'), 'VOD.L'),
							   (('7203', 'TSE'), '7203.T'), (('SHOP', 'TSX'), 'SHOP.TO'), (('AIR', 'NZX'), 'AIR.NZ'), (('D05', 'SGX'), 'D05.SI')):
			with self.subTest(args=args):
				self.assertEqual(markets.transform_to_yahoo(*args), expected)

	def test_each_market_has_its_own_flag_and_currency(self):
		"""Sharesight's market codes each have their own flag and currency: TSE is Tokyo, TSX Toronto, SGX Singapore."""
		for market, ticker, flag, currency in (('TSE', '7203.T', '🇯🇵', 'JPY'), ('TSX', 'SHOP.TO', '🇨🇦', 'CAD'), ('NZX', 'AIR.NZ', '🇳🇿', 'NZD'),
											   ('SGX', 'D05.SI', '🇸🇬', 'SGD'), ('CPSE', None, '🇩🇰', 'DKK')):
			with self.subTest(market=market):
				self.assertEqual((markets.flag_from_market(market), markets.currency_from_market(market)), (flag, currency))
				if ticker:
					self.assertEqual(markets.flag_from_ticker(ticker), flag)

	def test_make_paragraphs_keeps_every_word(self):
		"""make_paragraphs breaks a long description into paragraphs at sentence ends without losing a word."""
		self.assertEqual(formats.make_paragraphs('Acme makes widgets. It sells them.'), 'Acme makes widgets. It sells them.')
		long = ' '.join(['word'] * 22) + ' end. Tail sentence here.'
		self.assertEqual(formats.make_paragraphs(long), ' '.join(['word'] * 22) + ' end.\n\nTail sentence here.')

	def test_transform_title(self):
		"""Company names lose shouting and trailing legal suffixes (Inc, FPO, SE, a final &), with no double spaces."""
		self.assertEqual(formats.transform_title('APPLE INC'), 'Apple')
		self.assertEqual(formats.transform_title('Acme FPO'), 'Acme')
		self.assertEqual(formats.transform_title('Mixed Case Name'), 'Mixed Case Name')
		for title, expected in (('Allianz Se', 'Allianz'), ('Foo SE AG', 'Foo'), ('Johnson & Johnson &', 'Johnson & Johnson'),
								('Black and White and', 'Black and White'), ('Big Holdings Things Ltd', 'Big Things')):
			with self.subTest(title=title): # a suffix comes off the end only; no run of spaces is left behind
				self.assertEqual(formats.transform_title(title), expected)


class Formatting(unittest.TestCase):
	def test_signed_percent(self):
		"""A signed percent: a plus for gains, thousands separators, and the decimals asked for."""
		for value, decimals, expected in ((12, None, '+12%'), (-3.5, None, '-3.5%'), (0, None, '0%'), (1234, None, '+1,234%'),
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
		self.assertEqual(formats.date_range_english(10, datetime.date(2026, 1, 5)), '26 Dec 2025 - 5 Jan 2026') # crosses a year
		with self.assertRaises(TypeError):
			formats.date_range_english(None, end) # callers must pass a period

	def test_ordinal(self):
		"""Ordinal suffixes, the teens included."""
		for number, suffix in ((1, 'st'), (2, 'nd'), (3, 'rd'), (4, 'th'), (11, 'th'), (12, 'th'), (13, 'th'), (21, 'st'), (112, 'th')):
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
		"""On the first run there is no watchlist file: the holdings alone, GOOGL dropped when GOOG is held."""
		self.patch(sharesight, 'tickers', lambda: ['AAPL', 'GOOG', 'GOOGL'])
		self.patch(watchlist, 'with_holdings', REAL_GET_HOLDINGS)
		self.assertEqual(watchlist.with_holdings(), ['AAPL', 'GOOG']) # GOOGL dropped when GOOG is present
		state.save('finbot_watchlist.json', ['MSFT'])
		self.assertEqual(watchlist.with_holdings(), ['AAPL', 'GOOG', 'MSFT'])


if __name__ == '__main__':
	unittest.main()
