import os, subprocess, sys, tempfile, time
from unittest import mock
from pathlib import Path
from lib import config
from util import sync_defaults
from tests.common import FinbotCase

REPO = Path(config.__file__).resolve().parent.parent


def run_config(code, **env):
	"""What `code` prints when run in a fresh interpreter in the checkout, with DATA_DIR cleared and `env` added."""
	e = {k: v for k, v in os.environ.items() if k != 'DATA_DIR'}
	e.update(env)
	return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=e, capture_output=True, text=True, check=True).stdout.strip()


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
		out = run_config("import sys; from lib import config as c; print(c.prefs.price_percent, 'dotenv' in sys.modules)", price_percent='3.3')
		self.assertEqual(out.split()[-2:], ['3.3', 'False'])

	def test_state_directory_fallback(self):
		"""Without DATA_DIR, STATE_DIRECTORY's first entry is the data dir; MPLCONFIGDIR is in the cache unless set."""
		show = "from lib import config as c; print(c.env.data_dir, c.env.cache_dir, c.os.environ['MPLCONFIGDIR'])"
		with tempfile.TemporaryDirectory() as d:
			e = {k: v for k, v in os.environ.items() if k not in ('DATA_DIR', 'MPLCONFIGDIR')}
			def run(**env):
				"""The data dir, cache dir and MPLCONFIGDIR a fresh interpreter ends up with, given `env`."""
				return subprocess.run([sys.executable, '-c', show], cwd=REPO, env=dict(e, **env), capture_output=True, text=True, check=True).stdout.split()[-3:]
			self.assertEqual(run(STATE_DIRECTORY=d + ':/x/y'), [d, d + '/cache', d + '/cache/matplotlib'])
			self.assertEqual(run(STATE_DIRECTORY='/x/y', DATA_DIR=d)[0], d) # DATA_DIR wins
			self.assertEqual(run(DATA_DIR=d, MPLCONFIGDIR='/custom')[2], '/custom') # explicit value kept

	def test_render_import_sets_mplconfigdir_without_home(self):
		"""Importing render puts MPLCONFIGDIR in the cache before matplotlib loads: charts work without a home dir."""
		e = {k: v for k, v in os.environ.items() if k not in ('MPLCONFIGDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'HOME')}
		code = "import os; from lib import render; import matplotlib.dates; print(os.environ['MPLCONFIGDIR'])" # render loads matplotlib lazily
		with tempfile.TemporaryDirectory() as d:
			out = subprocess.run([sys.executable, '-c', code], cwd=REPO, env=dict(e, DATA_DIR=d), capture_output=True, text=True, check=True).stdout.strip()
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
		self.assertTrue(Path(config.env.data_dir, 'preferences.conf').exists())
		self.assertFalse(Path(config.env.data_dir, 'finbot.env').exists()) # the startup file is never copied into the data dir
		mine = Path(config.env.data_dir, 'finbot_adr.json')
		mine.write_text('{"mine": 1}')
		sync_defaults.sync(apply=True)
		self.assertEqual(mine.read_text(), '{"mine": 1}') # never overwritten without --force
		self.assertIn(('finbot_adr.json', 'skipped - destination differs'), sync_defaults.sync()) # existing files are skipped, and said so
		sync_defaults.sync(force=True)
		self.assertNotEqual(mine.read_text(), '{"mine": 1}')
		self.assertEqual(Path(str(mine) + '.bak').read_text(), '{"mine": 1}')

	def test_sync_defaults_to_another_destination(self):
		"""util/sync_defaults.py --dest copies there and leaves the data dir alone."""
		other = Path(config.env.data_dir, 'elsewhere')
		self.assertIn(('finbot_adr.json', 'would copy'), sync_defaults.sync(dest=other))
		self.assertFalse(other.exists()) # dry run
		sync_defaults.sync(apply=True, dest=other)
		self.assertTrue((other / 'finbot_adr.json').exists())
		self.assertFalse(Path(config.env.data_dir, 'finbot_adr.json').exists()) # the data dir is untouched
