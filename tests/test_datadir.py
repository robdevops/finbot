import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from lib import config
from util import sync_defaults
from tests.common import FinbotCase

REPO = Path(config.__file__).resolve().parent.parent


def run_config(code, **env):
	e = {k: v for k, v in os.environ.items() if k not in ('DATA_DIR', 'var_dir', 'cache_dir')}
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

	def test_data_dir_env_file_loaded(self):
		with tempfile.TemporaryDirectory() as d:
			Path(d, '.env').write_text('price_percent = 3.3\n')
			out = run_config("from lib import config as c; print(c.config_price_percent)", DATA_DIR=d)
			self.assertEqual(out.split()[-1], '3.3')

	def test_data_file_override_and_fallback(self):
		name = 'finbot_adr.json'
		self.assertEqual(config.data_file(name), str(REPO / 'defaults' / name))
		Path(config.config_var_dir, name).write_text('{}')
		self.assertEqual(config.data_file(name), config.config_var_dir + '/' + name)

	def test_sync_defaults(self):
		self.assertIn(('finbot_adr.json', 'missing'), sync_defaults.sync())
		self.assertFalse(Path(config.config_var_dir, 'finbot_adr.json').exists()) # dry run
		sync_defaults.sync(apply=True)
		self.assertTrue(Path(config.config_var_dir, 'finbot_adr.json').exists())
		self.assertTrue(Path(config.config_var_dir, '.env').exists())
		mine = Path(config.config_var_dir, 'finbot_adr.json')
		mine.write_text('{"mine": 1}')
		sync_defaults.sync(apply=True)
		self.assertEqual(mine.read_text(), '{"mine": 1}') # never overwritten without --force
		sync_defaults.sync(force=True)
		self.assertNotEqual(mine.read_text(), '{"mine": 1}')
		self.assertEqual(Path(str(mine) + '.bak').read_text(), '{"mine": 1}')
