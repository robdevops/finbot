import os, subprocess, sys, tempfile, time
from unittest import mock
from pathlib import Path
from lib import config
import contextlib, io
from util import flush, sync_defaults
from tests.common import FinbotCase, ROOT, bare_environment, temp_dir

REPO = Path(config.__file__).resolve().parent.parent


def run_config(code, **env):
	"""What `code` prints when run in a fresh interpreter in the checkout, with DATA_DIR cleared and `env` added."""
	e = {k: v for k, v in os.environ.items() if k != 'DATA_DIR'}
	e.update(env)
	return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=e, capture_output=True, text=True,
		check=True).stdout.strip()


class DataDirTests(FinbotCase):
	def test_default_unchanged(self):
		"""Without DATA_DIR, state lives in var/ in the checkout and the cache in var/cache, from whichever directory
		finbot starts; so does a relative DATA_DIR."""
		show = "from lib import config as c; print(c.env.data_dir, c.env.cache_dir)"
		var = str(REPO / 'var')
		self.assertEqual(run_config(show).split()[-2:], [var, var + '/cache'])
		env = {k: v for k, v in os.environ.items() if k != 'DATA_DIR'}
		env.update(PYTHONPATH=str(REPO), DATA_DIR='state', FINBOT_CHECK_ONLY='1') # check only: no directory is created
		elsewhere = subprocess.run([sys.executable, '-c', show], cwd='/', env=env, capture_output=True, text=True,
			check=True)
		self.assertEqual(elsewhere.stdout.split()[-2:], [str(REPO / 'state'), str(REPO / 'state/cache')])

	def test_data_dir_moves_var_and_cache(self):
		"""DATA_DIR moves both, and the cache directory is created."""
		with tempfile.TemporaryDirectory() as d:
			out = run_config("from lib import config as c; print(c.env.data_dir, c.env.cache_dir)", DATA_DIR=d)
			self.assertEqual(out.split()[-2:], [d, d + '/cache'])
			self.assertTrue(os.path.isdir(d + '/cache'))

	def test_config_reads_environment_only(self):
		"""Settings come from the environment; python-dotenv is not loaded."""
		code = "import sys; from lib import config as c; print(c.settings.price_percent, 'dotenv' in sys.modules)"
		out = run_config(code, price_percent='3.3')
		self.assertEqual(out.split()[-2:], ['3.3', 'False'])

	def test_state_directory_fallback(self):
		"""Without DATA_DIR, STATE_DIRECTORY's first entry is the data dir; MPLCONFIGDIR is in the cache unless set."""
		show = "from lib import config as c; print(c.env.data_dir, c.env.cache_dir, c.os.environ['MPLCONFIGDIR'])"
		with tempfile.TemporaryDirectory() as d:
			e = {k: v for k, v in os.environ.items() if k not in ('DATA_DIR', 'MPLCONFIGDIR')}
			def run(**env):
				"""The data dir, cache dir and MPLCONFIGDIR a fresh interpreter ends up with, given `env`."""
				return subprocess.run([sys.executable, '-c', show], cwd=REPO, env=dict(e, **env), capture_output=True,
					text=True, check=True).stdout.split()[-3:]
			self.assertEqual(run(STATE_DIRECTORY=d + ':/x/y'), [d, d + '/cache', d + '/cache/matplotlib'])
			self.assertEqual(run(STATE_DIRECTORY='/x/y', DATA_DIR=d)[0], d) # DATA_DIR wins
			self.assertEqual(run(DATA_DIR=d, MPLCONFIGDIR='/custom')[2], '/custom') # explicit value kept

	def test_render_import_sets_mplconfigdir_without_home(self):
		"""Importing render puts MPLCONFIGDIR in the cache before matplotlib loads: charts work without a home dir."""
		e = {k: v for k, v in os.environ.items() if k not in ('MPLCONFIGDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
			'HOME')}
		# render loads matplotlib lazily
		code = "import os; from lib import render; import matplotlib.dates; print(os.environ['MPLCONFIGDIR'])"
		with tempfile.TemporaryDirectory() as d:
			out = subprocess.run([sys.executable, '-c', code], cwd=REPO, env=dict(e, DATA_DIR=d), capture_output=True,
				text=True, check=True).stdout.strip()
			self.assertEqual(out.split()[-1], d + '/cache/matplotlib')

	def test_data_file_override_and_fallback(self):
		"""A data file is the user's copy in the data dir when there is one, else the shipped default."""
		name = 'finbot_adr.json'
		self.assertEqual(config.data_file(name), str(REPO / 'defaults' / name))
		Path(config.env.data_dir, name).write_text('{}')
		self.assertEqual(config.data_file(name), config.env.data_dir + '/' + name)

	def test_a_data_file_is_parsed_again_only_when_it_changes(self):
		"""config.data_json parses a file again only after its modification time changes."""
		path = Path(config.env.data_dir, 'finbot_adr.json')
		path.write_text('{"A": "B"}')
		self.assertEqual(config.data_json('finbot_adr.json'), {'A': 'B'})
		with mock.patch('json.load', side_effect=AssertionError('parsed again')):
			self.assertEqual(config.data_json('finbot_adr.json'), {'A': 'B'})
		path.write_text('{"A": "C"}')
		os.utime(path, (time.time() + 5, time.time() + 5)) # a later modification time
		self.assertEqual(config.data_json('finbot_adr.json'), {'A': 'C'})

	def test_sync_defaults(self):
		"""util/sync_defaults.py: a dry run by default, never finbot.env, never overwrites a changed file without
		--force (which keeps a .bak), and says what it skipped."""
		self.assertIn(('finbot_adr.json', 'would copy'), sync_defaults.sync())
		self.assertFalse(Path(config.env.data_dir, 'finbot_adr.json').exists()) # dry run
		sync_defaults.sync(apply=True)
		self.assertTrue(Path(config.env.data_dir, 'finbot_adr.json').exists())
		copied = Path(config.env.data_dir, 'settings.conf') # the template as it is: every key commented out
		self.assertEqual(copied.read_bytes(), (config.REPO_DIR / 'defaults' / 'settings.conf').read_bytes())
		self.assertEqual(config.read_settings(copied), {})
		# the startup file is never copied into the data dir
		self.assertFalse(Path(config.env.data_dir, 'finbot.env').exists())
		mine = Path(config.env.data_dir, 'finbot_adr.json')
		mine.write_text('{"mine": 1}')
		sync_defaults.sync(apply=True)
		self.assertEqual(mine.read_text(), '{"mine": 1}') # never overwritten without --force
		# existing files are skipped, and said so
		self.assertIn(('finbot_adr.json', 'skipped - destination differs'), sync_defaults.sync())
		sync_defaults.sync(force=True)
		self.assertNotEqual(mine.read_text(), '{"mine": 1}')
		self.assertEqual(Path(str(mine) + '.bak').read_text(), '{"mine": 1}')

	def test_sync_defaults_to_another_destination(self):
		"""util/sync_defaults.py --dest copies there and leaves the data dir alone; a destination that does not exist
		is an error that names --create, which makes it, mode 750, as it copies."""
		other = Path(config.env.data_dir, 'elsewhere')
		with self.assertRaisesRegex(FileNotFoundError, 'does not exist: --create makes it'):
			sync_defaults.sync(apply=True, dest=other)
		self.assertIn(('finbot_adr.json', 'would copy'), sync_defaults.sync(dest=other, create=True))
		self.assertFalse(other.exists()) # dry run
		sync_defaults.sync(apply=True, dest=other, create=True)
		self.assertTrue((other / 'finbot_adr.json').exists())
		self.assertEqual(other.stat().st_mode & 0o777, 0o750)
		self.assertFalse(Path(config.env.data_dir, 'finbot_adr.json').exists()) # the data dir is untouched
		self.assertTrue(sync_defaults.sync(dest=other)) # there now: no --create needed

	def test_sync_defaults_runs_with_any_python_and_creates_nothing_unasked(self):
		"""The tool needs only the standard library, so a bare python3 runs it (Docker's setup script does, on the
		host); importing lib.config creates no data directory, and a missing destination is refused, naming
		--create."""
		with tempfile.TemporaryDirectory() as tmp:
			dest = Path(tmp, 'data')
			env = {**bare_environment(), 'DATA_DIR': str(Path(tmp, 'never'))}
			run = lambda *args: subprocess.run([sys.executable, '-I', 'util/sync_defaults.py', *args], cwd=ROOT,
				env=env, capture_output=True, text=True, timeout=60)
			refused = run('--apply', '--dest', str(dest))
			self.assertEqual(refused.returncode, 2, refused.stderr)
			self.assertIn('does not exist: --create makes it', refused.stderr)
			made = run('--create', '--apply', '--dest', str(dest))
			self.assertEqual(made.returncode, 0, made.stderr)
			self.assertTrue((dest / 'settings.conf').exists())
			self.assertFalse(Path(tmp, 'never').exists())


class Flush(FinbotCase):
	"""util/flush.py: the cache files written before or after a time ago, or all of them; never the state."""

	def setUp(self):
		"""A data dir of this test's own: a state file, and cache files written 60 seconds, 400 seconds and 8 days ago,
		with a file in the cache that is not finbot's."""
		super().setUp()
		self.data = Path(temp_dir(self))
		self.cache = self.data / 'cache'
		self.cache.mkdir()
		(self.data / 'finbot_watchlist.json').write_text('{}')

	def make(self):
		"""The cache files, written that long ago."""
		for name, ago in (('finbot_new.json', 60), ('finbot_old.json', 400), ('finbot_week.json', 8 * 86400),
				('other.txt', 400)):
			path = self.cache / name
			path.write_text('{}')
			os.utime(path, (time.time() - ago,) * 2)

	def flush(self, *args):
		"""Run the tool on this data dir: (its exit status, what it printed, the cache files left)."""
		with contextlib.redirect_stdout(io.StringIO()) as out:
			status = flush.main([*args, '--data-dir', str(self.data)])
		return status, out.getvalue().strip(), sorted(path.name for path in self.cache.iterdir())

	def test_before_after_or_all_and_never_the_state(self):
		"""--before TIME deletes the cache files written more than TIME ago, --after TIME those written in the last
		TIME, all every one of them; nothing but finbot's files in the cache, and nothing in the data dir."""
		for args, left in ((['--before', '180s'], ['finbot_new.json', 'other.txt']),
				(['--after', '24h'], ['finbot_week.json', 'other.txt']),
				(['--after', '7d'], ['finbot_week.json', 'other.txt']), (['--after', '1y'], ['other.txt']),
				(['all'], ['other.txt'])):
			with self.subTest(args=args):
				self.make()
				status, said, files = self.flush(*args)
				self.assertEqual((status, files), (0, left))
				self.assertEqual(said, f"flushed {4 - len(left)} files from {self.cache}")
				self.assertTrue((self.data / 'finbot_watchlist.json').exists())

	def test_alone_it_shows_its_help_and_a_time_is_required(self):
		"""On its own it prints its help, with the examples; a time it does not know, or two of --before, --after and
		all, is refused."""
		with contextlib.redirect_stdout(io.StringIO()) as out:
			self.assertEqual(flush.main([]), 2)
		for example in ('--before 180s', '--after 24h', '--after 7d', '--after 3m', '--after 1y', 'util/flush.py all'):
			self.assertIn(example, out.getvalue())
		for args in (['--after', '7x'], ['all', '--before', '1h'], ['--before', '1h', '--after', '2h'], ['some']):
			with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
				flush.main(args)

	def test_it_runs_on_its_own_and_creates_nothing(self):
		"""As a script, it flushes the data dir it is given and creates no data dir of its own."""
		self.make()
		env = {**bare_environment(), 'DATA_DIR': str(self.data / 'never')}
		run = subprocess.run([sys.executable, 'util/flush.py', 'all', '--data-dir', str(self.data)], cwd=ROOT, env=env,
			capture_output=True, text=True, timeout=60)
		self.assertEqual((run.returncode, run.stdout.strip()), (0, f'flushed 3 files from {self.cache}'), run.stderr)
		self.assertFalse((self.data / 'never').exists())
