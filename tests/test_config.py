"""The two config files: finbot.env (the startup file, loaded by the launcher) and preferences.conf (read by the bot, reloadable)."""
import ast, contextlib, inspect, io, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from lib import config
from util import check_config, split_env
import bot, cal
from lib import reports, sharesight, util, worker, yahoo
import performance, price, shorts, trades

REPO = Path(config.__file__).resolve().parent.parent
DEFAULTS = {'config_past_days': 28, 'config_future_days': 30, 'config_price_percent': 5.0, 'config_shorts_percent': 15,
	'config_cache_seconds': 43200, 'config_performance_cache_seconds': 1800, 'config_graph': True, 'config_http_timeout': 18,
	'config_chunk_maxlines': 20, 'config_country_code': 'AU', 'config_timezone': 'Australia/Melbourne', 'config_cache': True,
	'config_alliterate': False, 'config_hyperlink': True, 'config_hyperlinkFooter': True, 'config_hyperlinkProvider': 'google',
	'config_demote_volatile': True, 'config_demote_leveraged': True, 'config_volatility_multiplier': 2.0, 'config_exclude_portfolios': [],
	'config_include_portfolios': [], 'config_trades_use_yahoo': True, 'config_performance_use_sharesight': False,
	'config_print_headers': False, 'config_min_analysts': 7, 'debug': False}


def keys_in(path):
	"""Every KEY= in a template, active or commented out."""
	return re.findall(r'^#?\s*([A-Za-z_][A-Za-z0-9_]*)=', Path(path).read_text(), re.M)


class Tables(unittest.TestCase):
	def test_the_two_key_sets_are_disjoint_and_cover_everything_config_reads(self):
		self.assertEqual(set(config.STARTUP_KEYS) & set(config.PREFERENCE_KEYS), set())
		self.assertEqual((len(config.STARTUP_KEYS), len(config.PREFERENCE_KEYS)), (17, 26))
		source = (REPO / 'lib' / 'config.py').read_text()
		read = set(re.findall(r"""(?:\br\.\w+|getenv)\(\s*['"]([A-Za-z_]+)['"]""", source))
		read -= {'STATE_DIRECTORY'} # systemd's own variable, a source for DATA_DIR
		self.assertEqual(read, set(config.STARTUP_KEYS) | set(config.PREFERENCE_KEYS))

	def test_secrets_are_startup_keys(self):
		self.assertTrue(set(config.SECRET_KEYS) <= set(config.STARTUP_KEYS))
		self.assertEqual(len(config.SECRET_KEYS), 11)

	def test_the_preference_defaults_are_the_old_defaults(self):
		values = config.preference_values(lambda name, default=None: default)
		self.assertEqual(values, DEFAULTS)

	def test_templates_have_every_key_and_the_real_defaults(self):
		self.assertEqual(sorted(keys_in(REPO / 'defaults' / 'preferences.conf')), sorted(config.PREFERENCE_KEYS))
		self.assertEqual(sorted(keys_in(REPO / 'defaults' / 'finbot.env')), sorted(config.STARTUP_KEYS))
		prefs = config.read_preferences(REPO / 'defaults' / 'preferences.conf')
		self.assertEqual(config.preference_values(config._getenv_for(prefs)), DEFAULTS) # the template changes nothing
		startup = config.read_startup_file(REPO / 'defaults' / 'finbot.env')
		config.startup_values(lambda name, default=None: startup.get(name, default)) # and is valid as it stands
		self.assertFalse((REPO / 'defaults' / 'env.example').exists())


class Parsing(unittest.TestCase):
	def parse(self, text):
		path = Path(tempfile.mkdtemp(), 'preferences.conf')
		path.write_text(text)
		return config.read_preferences(path), path

	def errors(self, text):
		with self.assertRaises(config.ConfigError) as caught:
			self.parse(text)
		return caught.exception.errors

	def test_comments_blanks_quotes_and_equals_in_values(self):
		values, _ = self.parse('# c\n\nfuture_days = 30\nhyperlinkProvider="google"\nexclude_portfolios=1 2\ncountry_code=\n')
		self.assertEqual(values, {'future_days': '30', 'hyperlinkProvider': 'google', 'exclude_portfolios': '1 2', 'country_code': ''})

	def test_missing_file_is_none(self):
		self.assertIsNone(config.read_preferences(Path(tempfile.mkdtemp(), 'nope')))

	def test_unknown_key_gets_a_hint_and_a_line_number(self):
		errors = self.errors('future_days=3\nfutur_days=3\n')
		self.assertEqual(len(errors), 1)
		self.assertIn('line 2: unknown key futur_days (did you mean future_days?)', errors[0])

	def test_a_startup_key_in_preferences_says_where_it_belongs(self):
		errors = self.errors('slack_webhook=https://x\nip=0.0.0.0\ntelegramChatID=5\nscheduler=False\n')
		self.assertEqual(len(errors), 4)
		for line in errors:
			self.assertIn('belongs in finbot.env (a change needs a restart)', line)
		self.assertNotIn('https://x', ''.join(errors)) # a value is never printed

	def test_malformed_lines_sections_duplicates_and_the_old_name(self):
		errors = self.errors('[reports]\nnot a setting\nfuture_days=1\nfuture_days=2\nvolatile_multiplier=3\n')
		self.assertEqual(len(errors), 4)
		self.assertIn('no sections', errors[0])
		self.assertIn('expected KEY=value', errors[1])
		self.assertIn('future_days is set twice', errors[2])
		self.assertIn('renamed to volatility_multiplier', errors[3])

	def test_every_problem_is_reported_not_just_the_first(self):
		self.assertEqual(len(self.errors('futur_days=1\nport=1\n[x]\n')), 3)

	def test_invalid_values_are_named(self):
		prefs = {'future_days': 'abc', 'price_percent': 'x'}
		with self.assertRaises(config.ConfigError) as caught:
			config.preference_values(config._getenv_for(prefs))
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn("future_days='abc' is not a whole number", caught.exception.errors[0])

	def test_booleans_take_the_usual_words_and_refuse_a_typo(self):
		for word, value in (('True', True), ('yes', True), ('ON', True), ('1', True), ('false', False), ('No', False), ('off', False), ('0', False)):
			with self.subTest(word=word):
				self.assertIs(config.preference_values(config._getenv_for({'graph': word}))['config_graph'], value)
		with self.assertRaises(config.ConfigError) as caught: # it used to mean False without a word
			config.preference_values(config._getenv_for({'graph': 'Ture'}))
		self.assertIn("graph='Ture' is not true or false", caught.exception.errors[0])

	def test_a_blank_value_means_the_default(self):
		values = config.preference_values(config._getenv_for({'cache': '', 'future_days': '', 'country_code': ''}))
		self.assertEqual((values['config_cache'], values['config_future_days'], values['config_country_code']), (True, 30, 'AU'))

	def test_unreadable_file_is_an_error_naming_it(self):
		path = Path(tempfile.mkdtemp(), 'preferences.conf')
		path.mkdir() # reading a directory fails like a permission error would
		with self.assertRaises(config.ConfigError) as caught:
			config.read_preferences(path)
		self.assertIn(f'cannot read {path}', caught.exception.errors[0])

	def test_precedence_file_then_environment_then_default(self):
		with mock.patch.dict(os.environ, {'future_days': '5', 'past_days': '4'}):
			values = config.preference_values(config._getenv_for({'future_days': '30'}))
		self.assertEqual((values['config_future_days'], values['config_past_days'], values['config_shorts_percent']), (30, 4, 15))

	def test_the_old_multiplier_name_is_gone_everywhere(self):
		with mock.patch.dict(os.environ, {'volatile_multiplier': '3'}):
			self.assertEqual(config.preference_values(config._getenv_for({}))['config_volatility_multiplier'], 2.0) # not read any more
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertIn('volatile_multiplier was renamed to volatility_multiplier', caught.exception.errors[0])
		self.assertEqual(config.preference_values(config._getenv_for({'volatility_multiplier': '4'}))['config_volatility_multiplier'], 4.0)

	def test_startup_file_linting(self):
		path = Path(tempfile.mkdtemp(), 'finbot.env')
		path.write_text('ip=1.2.3.4\nfuture_days=3\nslak_webhook=x\nport=http\n')
		problems = check_config.check(path, Path(tempfile.mkdtemp(), 'none'))
		self.assertEqual(len(problems), 2) # the two bad lines; the bad value is only found once the lines are valid
		self.assertIn('future_days belongs in preferences.conf (it is reloadable)', problems[0])
		self.assertIn('unknown key slak_webhook (did you mean slack_webhook?)', problems[1])
		path.write_text('port=http\n')
		self.assertIn("port='http' is not a whole number", check_config.check(path, Path(tempfile.mkdtemp(), 'none'))[0])
		path.write_text('port=80\n')
		self.assertEqual(check_config.check(path, Path(tempfile.mkdtemp(), 'none')), [])


class Reload(unittest.TestCase):
	def setUp(self):
		self.file = Path(tempfile.mkdtemp(), 'preferences.conf')
		self.file.write_text('')
		patch = mock.patch.object(config, 'preferences_path', str(self.file))
		patch.start()
		self.addCleanup(patch.stop)
		self.addCleanup(self.back_to_defaults)

	def back_to_defaults(self):
		self.file.write_text('')
		config.reload()

	def write(self, text):
		self.file.write_text(text)

	def test_a_change_reaches_config_and_every_module_that_copied_it(self):
		self.write('future_days=45\nprice_percent=7\nshorts_percent=12\nexclude_portfolios=1156263\nalliterate=1\nhyperlinkProvider=yahoo\n'
			'hyperlinkFooter=false\ndebug=1\ngraph=0\ndemote_volatile=0\nvolatility_multiplier=3\npast_days=14\nmin_analysts=3\n')
		changes = config.reload()
		self.assertEqual(len(changes), 13)
		self.assertEqual(reports.config_min_analysts, 3) # .buy, .sell and .forward pe read it
		self.assertIn('future_days 30 -> 45', changes)
		want = {'config_future_days': 45, 'config_past_days': 14, 'config_price_percent': 7.0}
		for module in (config, cal, worker, price, trades, performance, shorts, sharesight, yahoo, util):
			for name, value in want.items():
				if hasattr(module, name):
					self.assertEqual(getattr(module, name), value, f'{module.__name__}.{name}')
		self.assertEqual(worker.config_future_days, 45)
		self.assertEqual((config.config_exclude_portfolios, config.config_alliterate, config.config_hyperlinkProvider, config.config_hyperlinkFooter),
			(['1156263'], True, 'yahoo', False))
		self.assertEqual((worker.debug, config.debug, yahoo.config_graph, price.config_demote_volatile, price.config_volatility_multiplier), (True, True, False, False, 3.0))
		self.assertEqual(config.reload(), []) # nothing more to change

	def test_a_value_removed_from_the_file_goes_back_to_its_default(self):
		self.write('future_days=45\n')
		config.reload()
		self.write('# empty\n')
		self.assertEqual(config.reload(), ['future_days 45 -> 30'])
		self.assertEqual(cal.config_future_days, 30)

	def test_defaults_that_follow_a_preference_are_read_when_called(self):
		cache_file = Path(config.config_cache_dir, 'finbot_test_reload.json')
		cache_file.write_text('{"a": 1}')
		self.addCleanup(cache_file.unlink)
		past = cache_file.stat().st_mtime - 100
		os.utime(cache_file, (past, past)) # 100 seconds old
		self.write('cache_seconds=50\n')
		config.reload()
		self.assertIsNone(util.read_cache('finbot_test_reload.json')) # too old for 50 s
		self.write('cache_seconds=200\n')
		config.reload()
		self.assertEqual(util.read_cache('finbot_test_reload.json'), {'a': 1})
		self.assertIsNone(util.read_cache('finbot_test_reload.json', 50)) # an explicit value always wins

	def test_an_error_applies_nothing(self):
		self.write('future_days=45\n')
		config.reload()
		for text in ('future_days=3\nprice_percent=abc\n', 'future_days=3\nfutur_days=4\n', 'future_days=3\nslack_webhook=x\n'):
			self.write(text)
			with self.assertRaises(config.ConfigError):
				config.reload()
			self.assertEqual((config.config_future_days, cal.config_future_days), (45, 45))

	def test_a_missing_file_is_an_error_and_keeps_the_running_values(self):
		self.write('future_days=45\n')
		config.reload()
		self.file.unlink()
		with self.assertRaises(config.ConfigError) as caught:
			config.reload()
		self.assertIn('does not exist; nothing reloaded', caught.exception.errors[0])
		self.assertEqual(cal.config_future_days, 45)
		self.file.write_text('')

	def test_signature_defaults_are_the_sentinel_not_a_frozen_value(self):
		sites = [(cal.lambda_handler, 'days'), (trades.lambda_handler, 'days'), (performance.lambda_handler, 'past_days'),
			(price.lambda_handler, 'threshold'), (shorts.lambda_handler, 'threshold'), (sharesight.get_trades, 'days'),
			(sharesight.get_performance, 'config_cache_seconds'), (sharesight.get_performance_wrapper, 'days'), (util.read_cache, 'maxSeconds'),
			(util.read_binary_cache, 'maxSeconds'), (yahoo.fetch_detail, 'seconds'), (yahoo.price_history, 'seconds'),
			(yahoo.price_history, 'graph'), (yahoo.fetch_chart_json, 'seconds')]
		for func, param in sites:
			self.assertIs(inspect.signature(func).parameters[param].default, config.UNSET, f'{func.__module__}.{func.__name__}({param})')

	def test_no_function_default_or_module_constant_freezes_a_preference(self):
		names = set(config.PREFERENCE_NAMES)
		offenders = []
		for path in sorted([*(REPO / 'lib').glob('*.py'), *REPO.glob('*.py')]):
			if path.name == 'config.py':
				continue
			tree = ast.parse(path.read_text())
			for node in ast.walk(tree):
				if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
						if {n.id for n in ast.walk(default) if isinstance(n, ast.Name)} & names:
							offenders.append(f'{path.name}:{node.lineno} default of {node.name}')
			for node in tree.body: # module-level constants copied from a preference
				if isinstance(node, ast.Assign) and {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)} & names:
					offenders.append(f'{path.name}:{node.lineno} module constant {[t.id for t in node.targets if isinstance(t, ast.Name)]}')
		self.assertEqual(offenders, [])

	def test_a_job_process_runs_on_the_snapshot_not_the_edited_file(self):
		self.write('future_days=45\n')
		config.reload()
		env = config.child_environment()
		self.assertEqual((env['future_days'], env[config.PASSED]), ('45', '1'))
		self.write('future_days=99\n') # edited, no reload sent
		data = tempfile.mkdtemp()
		Path(data, 'preferences.conf').write_text('future_days=99\n')
		show = "from lib import config as c; print(c.config_future_days)"
		run = lambda **extra: subprocess.run([sys.executable, '-c', show], cwd=REPO, capture_output=True, text=True, check=True,
			env={**{k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k != config.PASSED}, 'DATA_DIR': data, **extra}).stdout.split()[-1]
		self.assertEqual(run(**env), '45') # the parent's values, and the file is not read
		self.assertEqual(run(), '99') # a script run by hand reads the file itself

	def test_run_child_hands_the_snapshot_to_the_job(self):
		from lib import jobs
		seen = {}
		real = jobs.subprocess.Popen
		def popen(args, **kw):
			seen.update(kw.get('env', {}))
			return real([sys.executable, '-c', 'pass'])
		self.write('future_days=45\n')
		config.reload()
		with mock.patch.object(jobs.subprocess, 'Popen', popen):
			import cleanup
			self.assertEqual(jobs.run_child('cleanup.py', cleanup, {}), 0)
		self.assertEqual((seen['future_days'], seen[config.PASSED]), ('45', '1'))


class Startup(unittest.TestCase):
	def run_config(self, code='from lib import config as c; print(c.config_future_days)', prefs=None, **env):
		data = tempfile.mkdtemp()
		if prefs is not None:
			Path(data, 'preferences.conf').write_text(prefs)
		e = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k not in config.STARTUP_KEYS and k != config.PASSED}
		return subprocess.run([sys.executable, '-c', code], cwd=REPO, env={**e, 'DATA_DIR': data, **env}, capture_output=True, text=True)

	def test_no_preferences_file_is_fine(self):
		out = self.run_config()
		self.assertEqual((out.returncode, out.stdout.split()[-1]), (0, '30'))

	def test_a_preferences_file_is_read_at_start(self):
		self.assertEqual(self.run_config(prefs='future_days=45\n').stdout.split()[-1], '45')

	def test_a_broken_preferences_file_refuses_to_start(self):
		for prefs, expect in (('future_days=abc\n', "future_days='abc' is not a whole number"), ('futur_days=1\n', 'unknown key futur_days'),
				('slack_webhook=x\n', 'belongs in finbot.env'), ('what\n', 'expected KEY=value')):
			out = self.run_config(prefs=prefs)
			self.assertEqual(out.returncode, 1, prefs)
			self.assertIn('ERROR config:', out.stderr)
			self.assertIn(expect, out.stderr)

	def test_an_unreadable_preferences_file_refuses_to_start(self):
		data = tempfile.mkdtemp()
		Path(data, 'preferences.conf').mkdir()
		out = subprocess.run([sys.executable, '-c', 'from lib import config'], cwd=REPO, env={**os.environ, 'DATA_DIR': data}, capture_output=True, text=True)
		self.assertEqual(out.returncode, 1)
		self.assertIn('cannot read', out.stderr)

	def test_a_bad_startup_value_refuses_to_start(self):
		out = self.run_config(port='http')
		self.assertEqual(out.returncode, 1)
		self.assertIn("port='http' is not a whole number", out.stderr)

	def test_a_preference_in_the_environment_is_refused_by_the_bot(self):
		with mock.patch.dict(os.environ, {'future_days': '30', 'debug': '1'}):
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn('future_days is a preference; move it from finbot.env to preferences.conf', '\n'.join(caught.exception.errors))
		with mock.patch.dict(os.environ, {'future_days': '30', config.PASSED: '1'}):
			config.check_startup_environment() # a job process gets its preferences this way
		with mock.patch.dict(os.environ, {'ip': '1.2.3.4', 'telegramChatID': '5'}):
			config.check_startup_environment() # startup keys are what the environment is for

	def test_the_bot_refuses_to_start_with_a_preference_in_its_environment(self):
		out = subprocess.run([sys.executable, 'bot.py'], cwd=REPO, capture_output=True, text=True, timeout=60,
			env={**os.environ, 'DATA_DIR': tempfile.mkdtemp(), 'future_days': '30'})
		self.assertEqual(out.returncode, 1)
		self.assertIn('future_days is a preference', out.stderr)

	def test_a_leftover_env_in_the_checkout_refuses_to_start(self):
		old = Path(tempfile.mkdtemp(), '.env')
		with mock.patch.object(config, 'OLD_ENV', old):
			config.check_startup_environment() # none there: fine
			old.write_text("future_days = '30'\n")
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn(f'{old} is the old single config file, which finbot no longer reads', caught.exception.errors[0])
		self.assertIn('/util/split_env.py, which writes finbot.env.new and preferences.conf.new', caught.exception.errors[1])

	def test_slack_commands_without_a_bot_token_are_warned_about(self):
		with mock.patch.object(config, 'config_slackOutgoingWebhook', 'https://example.com/slack'):
			with mock.patch.object(config, 'config_slackBotToken', False):
				self.assertEqual(config.startup_warnings(), ['slackOutgoingWebhook is set but slackBotToken is not: Slack commands will get no reply'])
			with mock.patch.object(config, 'config_slackBotToken', 'xoxb-1'):
				self.assertEqual(config.startup_warnings(), [])

	def test_startup_report_is_a_short_count_never_names_or_values(self):
		with mock.patch.dict(os.environ, {'slack_webhook': 'https://secret.example/abc', 'port': '5000'}, clear=True):
			lines = config.startup_report()
		self.assertEqual(lines[0], 'startup environment provides 2 of 17 startup keys (values hidden)')
		self.assertLessEqual(len('config: ' + lines[0]), 90) # the path in the second line depends on where DATA_DIR is
		self.assertNotIn('secret.example', ''.join(lines))
		self.assertNotIn('slack_webhook', ''.join(lines))


class SigHup(unittest.TestCase):
	def restore(self, file):
		with mock.patch.object(config, 'preferences_path', str(file)):
			file.write_text('')
			config.reload()

	def test_reload_all_reloads_preferences_and_the_schedule_independently(self):
		file = Path(tempfile.mkdtemp(), 'preferences.conf')
		file.write_text('future_days=45\n')
		scheduler = mock.Mock()
		self.addCleanup(self.restore, file)
		with mock.patch.object(config, 'preferences_path', str(file)), mock.patch.object(bot, 'scheduler', scheduler):
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('config: future_days 30 -> 45', err.getvalue())
			scheduler.reload.assert_called_once()
			file.write_text('futur_days=1\n') # a preferences error does not stop the schedule reload, and the bot survives it
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('ERROR config:', err.getvalue())
			self.assertEqual(scheduler.reload.call_count, 2)
			self.assertEqual(cal.config_future_days, 45)

	def test_reload_with_the_scheduler_off_still_reloads_preferences(self):
		file = Path(tempfile.mkdtemp(), 'preferences.conf')
		file.write_text('future_days=11\n')
		self.addCleanup(self.restore, file)
		with mock.patch.object(config, 'preferences_path', str(file)), mock.patch.object(bot, 'scheduler', None):
			with contextlib.redirect_stderr(io.StringIO()):
				bot.reload_all()
			self.assertEqual(cal.config_future_days, 11)


class Tools(unittest.TestCase):
	def test_split_env(self):
		startup, prefs, notes = split_env.split('slack_webhook=x\nfuture_days=3\nvolatile_multiplier=2\nslackToken=y\nSTATE_DIRECTORY=/a\nbogus=1\nnot a setting\n# c\nport=80\n')
		self.assertEqual(startup, ['slack_webhook=x', 'port=80'])
		self.assertEqual(prefs, ['future_days=3', 'volatility_multiplier=2'])
		self.assertEqual(len(notes), 4)
		self.assertTrue(any('slackToken dropped' in n for n in notes) and any('unknown key bogus' in n for n in notes))

	def test_split_env_reads_the_old_dotenv_format_too(self):
		old = "# c\nfuture_days = '30' # note\nexport slack_webhook = \"https://x/#frag\"\nport = 80 # comment\nbare\ndiscord_webhook=http://y/#z\n\n"
		startup, prefs, notes = split_env.split(old)
		self.assertEqual(startup, ['slack_webhook=https://x/#frag', 'port=80', 'discord_webhook=http://y/#z'])
		self.assertEqual(prefs, ['future_days=30'])
		self.assertEqual(notes, ['.env line 5: not KEY=value, left out'])
		self.assertFalse((REPO / 'util' / 'migrate_env.py').exists()) # split_env does its job now

	def test_split_env_writes_next_to_the_file_and_never_overwrites(self):
		d = Path(tempfile.mkdtemp())
		(d / 'old.env').write_text('port=80\nfuture_days=3\n')
		run = lambda: subprocess.run([sys.executable, str(REPO / 'util' / 'split_env.py'), str(d / 'old.env')], capture_output=True, text=True)
		self.assertEqual(run().returncode, 0)
		self.assertIn('port=80', (d / 'finbot.env.new').read_text())
		self.assertIn('future_days=3', (d / 'preferences.conf.new').read_text())
		self.assertEqual(oct((d / 'finbot.env.new').stat().st_mode & 0o777), '0o600')
		out = run()
		self.assertNotEqual(out.returncode, 0)
		self.assertIn('refusing to overwrite', out.stderr)
		out = subprocess.run([sys.executable, str(REPO / 'util' / 'split_env.py'), str(d / 'missing.env')], capture_output=True, text=True)
		self.assertEqual((out.returncode, out.stderr.strip()), (1, f'{d}/missing.env does not exist: nothing to split'))

	def test_check_config_script_exit_status_and_it_does_not_create_directories(self):
		d = Path(tempfile.mkdtemp())
		(d / 'finbot.env').write_text('port=80\n')
		data = d / 'data'
		run = lambda: subprocess.run([sys.executable, str(REPO / 'util' / 'check_config.py'), str(d / 'finbot.env')], capture_output=True, text=True,
			env={**os.environ, 'DATA_DIR': str(data)})
		out = run()
		self.assertEqual(out.returncode, 0, out.stderr)
		self.assertFalse(data.exists()) # may run as root from systemd: must not create the data directory
		(d / 'finbot.env').write_text('future_days=3\n')
		out = run()
		self.assertEqual(out.returncode, 1)
		self.assertIn('ERROR config:', out.stderr)


if __name__ == '__main__':
	unittest.main()
