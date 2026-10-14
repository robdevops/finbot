import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from lib import config
from util import sync_defaults
from tests.common import FinbotCase

REPO = Path(config.__file__).resolve().parent.parent


def run_config(code, **env):
	e = {k: v for k, v in os.environ.items() if k != 'DATA_DIR'}
	e.update(env)
	return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=e, capture_output=True, text=True, check=True).stdout.strip()


class DataDirTests(FinbotCase):
	def test_default_unchanged(self):
		out = run_config("from lib import config as c; print(c.config_var_dir, c.config_cache_dir)")
		self.assertEqual(out.split()[-2:], ['var', 'var/cache'])

	def test_data_dir_moves_var_and_cache(self):
		with tempfile.TemporaryDirectory() as d:
			out = run_config("from lib import config as c; print(c.config_var_dir, c.config_cache_dir)", DATA_DIR=d)
			self.assertEqual(out.split()[-2:], [d, d + '/cache'])
			self.assertTrue(os.path.isdir(d + '/cache'))

	def test_config_reads_environment_only(self):
		out = run_config("import sys; from lib import config as c; print(c.config_price_percent, 'dotenv' in sys.modules)", price_percent='3.3')
		self.assertEqual(out.split()[-2:], ['3.3', 'False'])

	def test_state_directory_fallback(self):
		show = "from lib import config as c; print(c.config_var_dir, c.config_cache_dir, c.os.environ['MPLCONFIGDIR'])"
		with tempfile.TemporaryDirectory() as d:
			e = {k: v for k, v in os.environ.items() if k not in ('DATA_DIR', 'MPLCONFIGDIR')}
			def run(**env):
				return subprocess.run([sys.executable, '-c', show], cwd=REPO, env=dict(e, **env), capture_output=True, text=True, check=True).stdout.split()[-3:]
			self.assertEqual(run(STATE_DIRECTORY=d + ':/x/y'), [d, d + '/cache', d + '/cache/matplotlib'])
			self.assertEqual(run(STATE_DIRECTORY='/x/y', DATA_DIR=d)[0], d) # DATA_DIR wins
			self.assertEqual(run(DATA_DIR=d, MPLCONFIGDIR='/custom')[2], '/custom') # explicit value kept

	def test_util_import_sets_mplconfigdir_without_home(self):
		e = {k: v for k, v in os.environ.items() if k not in ('MPLCONFIGDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'HOME')}
		code = "import os; from lib import util; import matplotlib.dates; print(os.environ['MPLCONFIGDIR'])" # util loads matplotlib lazily
		with tempfile.TemporaryDirectory() as d:
			out = subprocess.run([sys.executable, '-c', code], cwd=REPO, env=dict(e, DATA_DIR=d), capture_output=True, text=True, check=True).stdout.strip()
			self.assertEqual(out.split()[-1], d + '/cache/matplotlib')

	def test_data_file_override_and_fallback(self):
		name = 'finbot_adr.json'
		self.assertEqual(config.data_file(name), str(REPO / 'defaults' / name))
		Path(config.config_var_dir, name).write_text('{}')
		self.assertEqual(config.data_file(name), config.config_var_dir + '/' + name)

	def test_sync_defaults(self):
		self.assertIn(('finbot_adr.json', 'would copy'), sync_defaults.sync())
		self.assertFalse(Path(config.config_var_dir, 'finbot_adr.json').exists()) # dry run
		sync_defaults.sync(apply=True)
		self.assertTrue(Path(config.config_var_dir, 'finbot_adr.json').exists())
		self.assertTrue(Path(config.config_var_dir, 'preferences.conf').exists())
		self.assertFalse(Path(config.config_var_dir, 'finbot.env').exists()) # the startup file is never copied into the data dir
		mine = Path(config.config_var_dir, 'finbot_adr.json')
		mine.write_text('{"mine": 1}')
		sync_defaults.sync(apply=True)
		self.assertEqual(mine.read_text(), '{"mine": 1}') # never overwritten without --force
		self.assertIn(('finbot_adr.json', 'skipped - destination differs'), sync_defaults.sync()) # existing files are skipped, and said so
		sync_defaults.sync(force=True)
		self.assertNotEqual(mine.read_text(), '{"mine": 1}')
		self.assertEqual(Path(str(mine) + '.bak').read_text(), '{"mine": 1}')

	def test_sync_defaults_to_another_destination(self):
		other = Path(config.config_var_dir, 'elsewhere')
		self.assertIn(('finbot_adr.json', 'would copy'), sync_defaults.sync(dest=other))
		self.assertFalse(other.exists()) # dry run
		sync_defaults.sync(apply=True, dest=other)
		self.assertTrue((other / 'finbot_adr.json').exists())
		self.assertFalse(Path(config.config_var_dir, 'finbot_adr.json').exists()) # the data dir is untouched
