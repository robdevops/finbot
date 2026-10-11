import os, subprocess, sys, tempfile, unittest
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


class EnvFileTests(FinbotCase):
	def test_bin_run_exports_env_file_and_execs(self):
		with tempfile.TemporaryDirectory() as d:
			f = Path(d, 'f.env')
			f.write_text('# comment\nfoo_setting=bar baz\n')
			e = dict(os.environ, FINBOT_ENV=str(f))
			out = subprocess.run([str(REPO / 'bin' / 'run'), 'sh', '-c', 'echo "$foo_setting:$PWD"'], env=e, capture_output=True, text=True, check=True).stdout.strip()
			self.assertEqual(out, 'bar baz:' + str(REPO))

	def test_bin_run_keeps_existing_environment(self):
		with tempfile.TemporaryDirectory() as d:
			f = Path(d, 'f.env')
			f.write_text('foo_setting=from_file\n')
			e = dict(os.environ, FINBOT_ENV=str(f), foo_setting='from_env')
			out = subprocess.run([str(REPO / 'bin' / 'run'), 'sh', '-c', 'echo "$foo_setting"'], env=e, capture_output=True, text=True, check=True).stdout.strip()
			self.assertEqual(out, 'from_env')

	def test_migrate_env(self):
		from util import migrate_env
		old = "# c\nkey = 'val' # note\nnum = 5\nexport tok = \"a b\"\nbare\nurl=http://x/#frag\n\n"
		self.assertEqual(migrate_env.convert(old).splitlines(), ['# c', 'key=val', 'num=5', 'tok=a b', '# bare # no value, not a setting', 'url=http://x/#frag', ''])
