"""The two config files: finbot.env (the startup file, which the launcher loads) and settings.conf (reloadable)."""
import ast, contextlib, dataclasses, io, os, re, shutil, subprocess, sys, types, unittest
from pathlib import Path
from unittest import mock
from tests import common # first: it sets the environment that lib.config reads as it loads
from lib import config
from util import check_config
import bot
from lib import cache

REPO = Path(config.__file__).resolve().parent.parent


def fields(settings):
	"""A Settings as {name: value}, without the file's own lines."""
	return {name: getattr(settings, name) for name in config.SETTING_KEYS}


def keys_in(path):
	"""Every KEY= in a template, active or commented out."""
	return re.findall(r'^#?\s*([A-Za-z_][A-Za-z0-9_]*)=', Path(path).read_text(), re.M)


class Tables(unittest.TestCase):
	def test_the_two_key_sets_are_disjoint_and_cover_everything_config_reads(self):
		"""Startup and setting keys do not overlap: config.py reads each startup key by name, and each setting
		as a field of Settings."""
		self.assertEqual(set(config.STARTUP_KEYS) & set(config.SETTING_KEYS), set())
		source = (REPO / 'lib' / 'config.py').read_text()
		read = set(re.findall(r"""(?:\br\.\w+|getenv)\(\s*['"]([A-Za-z_]+)['"]""", source))
		read -= {'STATE_DIRECTORY'} # systemd's own variable, a source for DATA_DIR
		self.assertEqual(read, set(config.STARTUP_KEYS))

	def test_secrets_are_startup_keys(self):
		"""Every secret is a startup key: settings.conf holds none."""
		self.assertTrue(set(config.SECRET_KEYS) <= set(config.STARTUP_KEYS))
		self.assertEqual(len(config.SECRET_KEYS), 13)

	def test_unset_settings_take_their_defaults(self):
		"""An unset setting takes its field's default, as it is: reading tidies nothing away."""
		values = config.setting_values(lambda name, default=None: default)
		self.assertEqual(fields(values), fields(config.Settings()))

	def test_templates_have_every_key_and_the_real_defaults(self):
		"""defaults/settings.conf lists every key, commented out at its built-in default, so that it sets none;
		finbot.env lists every key; both are valid as shipped."""
		template = REPO / 'defaults' / 'settings.conf'
		self.assertEqual(sorted(keys_in(template)), sorted(config.SETTING_KEYS))
		self.assertEqual(sorted(keys_in(REPO / 'defaults' / 'finbot.env')), sorted(config.STARTUP_KEYS))
		self.assertEqual((config.read_settings(template), config.template_keys()), ({}, [])) # it sets nothing
		shown = dict(re.findall(r'^#([A-Za-z_][A-Za-z0-9_]*)=(.*)$', template.read_text(), re.M)) # #key=value lines
		self.assertEqual(sorted(shown), sorted(config.SETTING_KEYS))
		self.assertEqual(fields(config.setting_values(config._getenv_for(shown))), fields(config.Settings()))
		startup = config.read_startup_file(REPO / 'defaults' / 'finbot.env')
		config.startup_values(lambda name, default=None: startup.get(name, default)) # and is valid as it stands


class Parsing(unittest.TestCase):
	def parse(self, text):
		"""(what read_settings makes of text, the file it was written to)."""
		path = Path(common.temp_dir(self), 'settings.conf')
		path.write_text(text)
		return config.read_settings(path), path

	def errors(self, text):
		"""The errors read_settings raises for text."""
		with self.assertRaises(config.ConfigError) as caught:
			self.parse(text)
		return caught.exception.errors

	def test_comments_blanks_quotes_and_equals_in_values(self):
		"""Comments and blank lines are skipped, quotes come off, and spaces and blanks in values are kept."""
		values, _ = self.parse('# c\n\nfuture_days = 30\nhyperlinkProvider="google"\nexclude_portfolios=1 2\n'
			'country_code=\n')
		self.assertEqual(values,
			{'future_days': '30', 'hyperlinkProvider': 'google', 'exclude_portfolios': '1 2', 'country_code': ''})

	def test_missing_file_is_none(self):
		"""No settings.conf is not an error: None."""
		self.assertIsNone(config.read_settings(Path(common.temp_dir(self), 'nope')))

	def test_unknown_key_gets_a_hint_and_a_line_number(self):
		"""An unknown key is reported with its line number and the key it was probably meant to be."""
		errors = self.errors('future_days=3\nfutur_days=3\n')
		self.assertEqual(len(errors), 1)
		self.assertIn('line 2: unknown key futur_days (did you mean future_days?)', errors[0])

	def test_a_startup_key_in_settings_says_where_it_belongs(self):
		"""A startup key in settings.conf is sent to finbot.env, without printing its value."""
		errors = self.errors('slackOutgoingWebhook=https://x\nip=0.0.0.0\nport=5\nscheduler_catchup=3\n')
		self.assertEqual(len(errors), 4)
		for line in errors:
			self.assertIn('belongs in finbot.env (a change needs a restart)', line)
		self.assertNotIn('https://x', ''.join(errors)) # a value is never printed

	def test_malformed_lines_sections_duplicates_and_the_old_name(self):
		"""Sections, lines not KEY=value, a key set twice and a key that is none (the old volatile_multiplier, say: the
		key it may be is named) are all reported."""
		errors = self.errors('[reports]\nnot a setting\nfuture_days=1\nfuture_days=2\nvolatile_multiplier=3\n')
		self.assertEqual(len(errors), 4)
		self.assertIn('no sections', errors[0])
		self.assertIn('expected KEY=value', errors[1])
		self.assertIn('future_days is set twice', errors[2])
		self.assertIn('unknown key volatile_multiplier (did you mean volatility_multiplier?)', errors[3])

	def test_every_problem_is_reported_not_just_the_first(self):
		"""Every problem in the file is reported at once."""
		self.assertEqual(len(self.errors('futur_days=1\nport=1\n[x]\n')), 3)

	def test_invalid_values_are_named(self):
		"""A value of the wrong type is reported with its key and value."""
		settings = {'future_days': 'abc', 'price_percent': 'x'}
		with self.assertRaises(config.ConfigError) as caught:
			config.setting_values(config._getenv_for(settings))
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn("future_days='abc' is not a whole number", caught.exception.errors[0])

	def test_booleans_take_the_usual_words_and_refuse_a_typo(self):
		"""Booleans take true/false, yes/no, on/off and 1/0 in any case; a typo is an error (it used to mean False)."""
		for word, value in (('True', True), ('yes', True), ('ON', True), ('1', True), ('false', False), ('No', False),
				('off', False), ('0', False)):
			with self.subTest(word=word):
				self.assertIs(config.setting_values(config._getenv_for({'graph': word})).graph, value)
		with self.assertRaises(config.ConfigError) as caught: # it used to mean False without a word
			config.setting_values(config._getenv_for({'graph': 'Ture'}))
		self.assertIn("graph='Ture' is not true or false", caught.exception.errors[0])

	def test_a_blank_value_means_the_default(self):
		"""A key with a blank value takes its default, but for exchange_suffix, where blank means no suffix to try."""
		values = config.setting_values(config._getenv_for({'cache': '', 'future_days': '', 'country_code': ''}))
		self.assertEqual((values.cache, values.future_days, values.country_code), (True, 30, 'AU'))
		for given, suffix in (('', ''), ('AX', 'AX'), ('.ax', 'AX'), (' NZ ', 'NZ')):
			with self.subTest(given=given):
				values = config.setting_values(config._getenv_for({'exchange_suffix': given}))
				self.assertEqual(values.exchange_suffix, suffix)
		self.assertEqual(config.setting_values(config._getenv_for({})).exchange_suffix, 'AX') # unset: the default

	def test_log_level_is_one_of_syslogs_levels_in_any_case(self):
		"""log_level takes ERROR, WARN, INFO or DEBUG, in any case, INFO by default; anything else is a mistake that
		names the levels."""
		for given, level in (('warn', 'WARN'), ('Debug', 'DEBUG'), ('ERROR', 'ERROR'), ('', 'INFO')):
			with self.subTest(log_level=given):
				values = config.setting_values(config._getenv_for({'log_level': given}))
				self.assertEqual(values.log_level, level)
		with self.assertRaises(config.ConfigError) as caught:
			config.setting_values(config._getenv_for({'log_level': 'loud'}))
		self.assertEqual(caught.exception.errors, ["log_level='loud' is not one of ERROR, WARN, INFO, DEBUG"])

	def test_a_retired_key_is_accepted_and_said_to_do_nothing(self):
		"""A key finbot no longer reads (alliterate in settings.conf, slack_webhook in finbot.env, say) does not stop
		a start, as an unknown key would: it is ignored, and the log at start (and check_config) says what to do
		instead."""
		path = Path(common.temp_dir(self), 'settings.conf')
		path.write_text(''.join(f'{key}=True\n' for key in config.RETIRED) + 'future_days=45\n')
		values = config.read_settings(path)
		self.assertEqual(config.setting_values(config._getenv_for(values)).future_days, 45)
		notes = [f'{key} in settings.conf does nothing any more: {instead}'
			for key, instead in config.RETIRED.items()]
		self.assertEqual(config.retired_notes(values), notes)
		self.assertEqual(check_config.notes(path), config.retired_notes(values))
		startup = Path(common.temp_dir(self), 'finbot.env')
		startup.write_text('slack_webhook=https://hooks.slack.com/services/x\nport=80\n')
		self.assertEqual(check_config.check(startup, path), [])
		self.assertEqual(check_config.notes(path, startup)[0], "slack_webhook in finbot.env does nothing any more:"
			" each chat's jobs (/jobs) post there as the bot (slackBotToken); delete the line")
		with mock.patch.dict(os.environ, {'discord_webhook': 'https://discord.com/api/webhooks/1/x',
				'telegramChatID': '-1001'}):
			report = config.startup_report()
		self.assertIn("discord_webhook in finbot.env does nothing any more: each chat's jobs (/jobs) post there as"
			' the bot (discordBotToken); delete the line', report)
		self.assertIn('telegramChatID in finbot.env does nothing any more: each chat has its own jobs (/jobs)',
			'\n'.join(report)) # there are no home chats

	def test_unreadable_file_is_an_error_naming_it(self):
		"""A settings file that cannot be read is an error that names it."""
		path = Path(common.temp_dir(self), 'settings.conf')
		path.mkdir() # reading a directory fails like a permission error would
		with self.assertRaises(config.ConfigError) as caught:
			config.read_settings(path)
		self.assertIn(f'cannot read {path}', caught.exception.errors[0])

	def test_precedence_file_then_environment_then_default(self):
		"""A setting comes from the file, else the environment, else its default."""
		with mock.patch.dict(os.environ, {'future_days': '5', 'past_days': '4'}):
			values = config.setting_values(config._getenv_for({'future_days': '30'}))
		self.assertEqual((values.future_days, values.past_days, values.shorts_percent), (30, 4, 15))

	def test_startup_file_linting(self):
		"""util/check_config.py reports bad lines in finbot.env first, then bad values, and nothing for a good file."""
		path = Path(common.temp_dir(self), 'finbot.env')
		path.write_text('ip=1.2.3.4\nfuture_days=3\nslackBotTokn=x\nport=http\n')
		problems = check_config.check(path, Path(common.temp_dir(self), 'none'))
		self.assertEqual(len(problems), 2) # the two bad lines; the bad value is only found once the lines are valid
		self.assertIn('future_days belongs in settings.conf (it is reloadable)', problems[0])
		self.assertIn('unknown key slackBotTokn (did you mean slackBotToken?)', problems[1])
		path.write_text('port=http\n')
		nowhere = Path(common.temp_dir(self), 'none')
		self.assertIn("port='http' is not a whole number", check_config.check(path, nowhere)[0])
		path.write_text('port=80\n')
		self.assertEqual(check_config.check(path, Path(common.temp_dir(self), 'none')), [])

	def test_check_config_warns_when_finbot_env_is_not_600_root(self):
		"""util/check_config.py warns, naming the fix, when finbot.env is not mode 600 owned by root:root, and says
		nothing for one that is, or for a file it cannot stat."""
		def stat_of(mode, uid=0, gid=0):
			"""What os.stat says of a file with this mode, owner and group."""
			return types.SimpleNamespace(st_mode=0o100000 | mode, st_uid=uid, st_gid=gid)
		with mock.patch.object(check_config.os, 'stat', return_value=stat_of(0o600)):
			self.assertEqual(check_config.permission_warnings('/opt/finbot.env'), [])
		with mock.patch.object(check_config.os, 'stat', return_value=stat_of(0o644)):
			warning, = check_config.permission_warnings('/opt/finbot.env')
		self.assertIn('/opt/finbot.env is 644 root:root, not 600 root:root', warning)
		self.assertIn('chmod 600 /opt/finbot.env && chown root:root /opt/finbot.env', warning)
		with mock.patch.object(check_config.os, 'stat', return_value=stat_of(0o600, uid=54321, gid=54321)):
			self.assertIn('600 54321:54321, not 600 root:root', check_config.permission_warnings('x')[0])
		self.assertEqual(check_config.permission_warnings('/no/such/finbot.env'), [])

	def test_check_config_gives_the_startup_warnings_of_a_valid_file(self):
		"""check_config shows what bot.py would warn about at start for the file it checks: here a Telegram token for
		a webhook that is not set (pull mode)."""
		path = Path(common.temp_dir(self), 'finbot.env')
		path.write_text('telegramOutgoingToken=tok\n')
		self.assertEqual(check_config.check(path, Path(common.temp_dir(self), 'none')), [])
		self.assertEqual(check_config.warnings(path), ['telegramOutgoingToken is set but telegramOutgoingWebhook is'
			' not: finbot fetches its Telegram updates (pull mode), and the token is not used'])
		path.write_text('telegramOutgoingToken=tok\ntelegramOutgoingWebhook=https://example.com/t\n')
		self.assertEqual(check_config.warnings(path), [])


class Reload(unittest.TestCase):
	def setUp(self):
		"""An empty settings.conf of this test's own, put back to the defaults afterwards."""
		self.file = Path(common.temp_dir(self), 'settings.conf')
		self.file.write_text('')
		patch = mock.patch.object(config, 'settings_path', str(self.file))
		patch.start()
		self.addCleanup(patch.stop)
		self.addCleanup(self.back_to_defaults)

	def back_to_defaults(self):
		"""Empty the file and reload, so the next test starts from the defaults."""
		self.file.write_text('')
		config.reload()

	def write(self, text):
		"""Write the settings file."""
		self.file.write_text(text)

	def test_a_change_is_seen_at_once(self):
		"""A reload applies every change, says which, and swaps in a new object, so no request sees half a reload."""
		self.write('future_days=45\nprice_percent=7\nshorts_percent=12\nexclude_portfolios=1156263\n'
			'exchange_suffix=nz\nhyperlinkProvider=yahoo\nhyperlinkFooter=false\nlog_level=debug\ngraph=0\n'
			'demote_volatile=0\nvolatility_multiplier=3\npast_days=14\nmin_analysts=3\n')
		before = config.settings
		changes = config.reload()
		self.assertEqual(len(changes), 13)
		self.assertIn('future_days 30 -> 45', changes)
		self.assertIsNot(config.settings, before) # one new object: no request sees half a reload
		self.assertEqual((config.settings.future_days, config.settings.past_days, config.settings.price_percent,
			config.settings.min_analysts), (45, 14, 7.0, 3))
		settings = config.settings
		self.assertEqual((settings.exclude_portfolios, settings.exchange_suffix, settings.hyperlinkProvider,
			settings.hyperlinkFooter), (('1156263',), 'NZ', 'yahoo', False))
		self.assertEqual((config.settings.log_level, config.settings.graph, config.settings.demote_volatile,
			config.settings.volatility_multiplier), ('DEBUG', False, False, 3.0))
		self.assertEqual(config.reload(), []) # nothing more to change

	def test_a_value_removed_from_the_file_goes_back_to_its_default(self):
		"""A key taken out of the file goes back to its default on reload."""
		self.write('future_days=45\n')
		config.reload()
		self.write('# empty\n')
		self.assertEqual(config.reload(), ['future_days 45 -> 30'])
		self.assertEqual(config.settings.future_days, 30)

	def test_defaults_that_follow_a_setting_are_read_when_called(self):
		"""A cache read without seconds follows cache_seconds as reloaded; an explicit value always wins."""
		cache_file = Path(config.env.cache_dir, 'finbot_test_reload.json')
		cache_file.write_text('{"a": 1}')
		self.addCleanup(cache_file.unlink)
		past = cache_file.stat().st_mtime - 100
		os.utime(cache_file, (past, past)) # 100 seconds old
		self.write('cache_seconds=50\n')
		config.reload()
		self.assertIsNone(cache.read('finbot_test_reload.json')) # too old for 50 s
		self.write('cache_seconds=200\n')
		config.reload()
		self.assertEqual(cache.read('finbot_test_reload.json'), {'a': 1})
		self.assertIsNone(cache.read('finbot_test_reload.json', 50)) # an explicit value always wins

	def test_an_error_applies_nothing(self):
		"""A reload that finds any error applies nothing."""
		self.write('future_days=45\n')
		config.reload()
		for text in ('future_days=3\nprice_percent=abc\n', 'future_days=3\nfutur_days=4\n',
				'future_days=3\nslackBotToken=x\n'):
			self.write(text)
			with self.assertRaises(config.ConfigError):
				config.reload()
			self.assertEqual(config.settings.future_days, 45)

	def test_a_missing_file_is_an_error_and_keeps_the_running_values(self):
		"""A reload with the file gone is an error and keeps the running values."""
		self.write('future_days=45\n')
		config.reload()
		self.file.unlink()
		with self.assertRaises(config.ConfigError) as caught:
			config.reload()
		self.assertIn('does not exist; nothing reloaded', caught.exception.errors[0])
		self.assertEqual(config.settings.future_days, 45)
		self.file.write_text('')

	def test_nothing_copies_the_config_or_freezes_a_setting(self):
		"""Modules read config.settings.<name> when they run, so that a reload is seen: no star import (which copied
		every name into each module), and no function default or module constant computed from a setting."""
		def reads_settings(node):
			"""Whether an expression reads config.settings."""
			return any(isinstance(n, ast.Attribute) and n.attr == 'settings' and isinstance(n.value,
				ast.Name) and n.value.id == 'config' for n in ast.walk(node))
		offenders = []
		for path in sorted([*(REPO / 'lib').rglob('*.py'), *REPO.glob('*.py'), *(REPO / 'util').glob('*.py')]):
			tree = ast.parse(path.read_text())
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom) and node.module == 'lib.config':
					names = ', '.join(a.name for a in node.names)
					offenders.append(f'{path.name}:{node.lineno} from lib.config import {names}')
				if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d]]:
						if reads_settings(default):
							offenders.append(f'{path.name}:{node.lineno} default of {node.name}')
			for node in tree.body:
				if isinstance(node, ast.Assign) and reads_settings(node.value):
					offenders.append(f'{path.name}:{node.lineno} module constant')
		self.assertEqual(offenders, [])

	def test_a_scheduled_job_runs_on_the_settings_in_force_not_the_edited_file(self):
		"""A scheduled job runs in the bot's process, on the settings of the last reload: a file edited since, and
		not reloaded, is not read."""
		from lib import jobs
		seen = []
		self.write('future_days=45\n')
		config.reload()
		self.write('future_days=99\n') # edited, no reload sent
		module = types.SimpleNamespace(run=lambda: seen.append(config.settings.future_days))
		jobs.run_in_process('look.py', module, {})
		self.assertEqual(seen, [45])


class Startup(unittest.TestCase):
	def run_config(self, code='from lib import config as c; print(c.settings.future_days)', settings=None, **env):
		"""Run code in a new interpreter: own data dir, settings as settings.conf, no settings in the environment."""
		data = common.temp_dir(self)
		if settings is not None:
			Path(data, 'settings.conf').write_text(settings)
		env = {**common.bare_environment(), 'DATA_DIR': data, **env}
		return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=env,
			capture_output=True, text=True)

	def test_no_settings_file_is_fine(self):
		"""finbot starts without a settings.conf, on the defaults."""
		out = self.run_config()
		self.assertEqual((out.returncode, out.stdout.split()[-1]), (0, '30'))

	def test_a_settings_file_is_read_at_start(self):
		"""settings.conf is read at start."""
		self.assertEqual(self.run_config(settings='future_days=45\n').stdout.split()[-1], '45')

	def test_a_broken_settings_file_refuses_to_start(self):
		"""A bad value, unknown key, startup key or malformed line in settings.conf stops the start, saying why."""
		for settings, expect in (('future_days=abc\n', "future_days='abc' is not a whole number"),
			('futur_days=1\n', 'unknown key futur_days'),
				('slackBotToken=x\n', 'belongs in finbot.env'), ('what\n', 'expected KEY=value')):
			out = self.run_config(settings=settings)
			self.assertEqual(out.returncode, 1, settings)
			self.assertIn('ERROR config:', out.stderr)
			self.assertIn(expect, out.stderr)

	def test_the_template_is_never_read_and_a_key_set_there_is_pointed_elsewhere(self):
		"""defaults/settings.conf is only a template: a key set there changes nothing, and the log at start says to
		set it in the data dir's settings.conf, or to make that file first with util/sync_defaults.py."""
		tree = Path(common.temp_dir(self)) # config.py and a template of its own, which sets a key
		(tree / 'lib').mkdir()
		shutil.copy(REPO / 'lib' / 'config.py', tree / 'lib')
		(tree / 'defaults').mkdir()
		(tree / 'defaults' / 'settings.conf').write_text('# a comment\n#past_days=28\nfuture_days=45\n')
		code = 'from lib import config as c; print(c.settings.future_days); print(*c.startup_warnings(), sep="\\n")'
		for made in (False, True):
			data = common.temp_dir(self)
			if made:
				Path(data, 'settings.conf').write_text('#future_days=30\n')
			with self.subTest(settings_conf=made):
				out = subprocess.run([sys.executable, '-c', code], cwd=tree,
					env={**common.bare_environment(), 'DATA_DIR': data}, capture_output=True, text=True)
				conf = f'{data}/settings.conf'
				fix = f'edit {conf} instead' if made else f'run util/sync_defaults.py --apply, then edit {conf}'
				self.assertEqual(out.stdout.split('\n')[:2], ['30',
					f'defaults/settings.conf sets future_days, but finbot never reads it: {fix}'], out.stderr)

	def test_an_unreadable_settings_file_refuses_to_start(self):
		"""A settings.conf that cannot be read stops the start."""
		data = common.temp_dir(self)
		Path(data, 'settings.conf').mkdir()
		out = subprocess.run([sys.executable, '-c', 'from lib import config'], cwd=REPO,
			env={**os.environ, 'DATA_DIR': data}, capture_output=True, text=True)
		self.assertEqual(out.returncode, 1)
		self.assertIn('cannot read', out.stderr)

	def test_a_bad_startup_value_refuses_to_start(self):
		"""A bad value in finbot.env stops the start, saying which."""
		out = self.run_config(port='http')
		self.assertEqual(out.returncode, 1)
		self.assertIn("port='http' is not a whole number", out.stderr)

	def test_a_setting_in_the_environment_is_refused_by_the_bot(self):
		"""A setting in the bot's environment (finbot.env) is refused, but a job process gets its settings that
		way, and startup keys belong there."""
		with mock.patch.dict(os.environ, {'future_days': '30', 'log_level': 'DEBUG'}):
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn('future_days is a setting; move it from finbot.env to settings.conf',
			'\n'.join(caught.exception.errors))
		with mock.patch.dict(os.environ, {'ip': '1.2.3.4', 'port': '80'}):
			config.check_startup_environment() # startup keys are what the environment is for

	def test_the_bot_refuses_to_start_with_a_setting_in_its_environment(self):
		"""bot.py exits 1 when finbot.env holds a setting."""
		out = subprocess.run([sys.executable, 'bot.py'], cwd=REPO, capture_output=True, text=True, timeout=60,
			env={**os.environ, 'DATA_DIR': common.temp_dir(self), 'future_days': '30'})
		self.assertEqual(out.returncode, 1)
		self.assertIn('future_days is a setting', out.stderr)

	def test_the_telegram_api_is_the_bot_tokens(self):
		"""Telegram's Bot API base is made from the bot token (a trailing slash dropped), and is empty without one."""
		for token, api in (('123:abc', 'https://api.telegram.org/bot123:abc/'), ('123:abc/',
				'https://api.telegram.org/bot123:abc/'), ('', '')):
			values = config.startup_values(lambda name, default=None: token if name == 'telegramBotToken' else default)
			self.assertEqual(values.telegram_api, api)

	def test_settings_that_leave_part_of_the_bot_unable_to_work_are_warned_about(self):
		"""A startup warning for Slack commands without slackBotToken (no reply), and for an inbound webhook without its
		secret (every request would be refused)."""
		hooks = dict(slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='stok',
			slackBotToken='xoxb-1', telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok')
		deaf = ('slackBotToken is set but neither slackAppToken nor slackOutgoingWebhook is: finbot hears nothing from'
			' Slack, so its commands and buttons get no answer')
		no_reply = 'slackOutgoingWebhook is set but slackBotToken is not: Slack commands will get no reply'
		slack_refused = ('slackOutgoingWebhook is set but neither slackSigningSecret nor slackOutgoingToken is:'
			' every Slack request will be refused')
		telegram_refused = ('telegramOutgoingWebhook is set but telegramOutgoingToken is not: every Telegram update'
			' will be refused')
		unused = ('telegramOutgoingToken is set but telegramOutgoingWebhook is not: finbot fetches its Telegram updates'
			' (pull mode), and the token is not used')
		app_no_reply = 'slackAppToken is set but slackBotToken is not: Slack commands will get no reply'
		app_unused = ('slackAppToken is set but so is slackOutgoingWebhook: Slack posts its updates there (http mode),'
			' and the app-level token is not used')
		not_app = ("slackAppToken does not start with xapp-: it must be an app-level token (the app's Basic"
			' Information, App-Level Tokens), not the bot token')
		bad_secret = ("telegramOutgoingToken is not 1 to 256 letters, digits, _ or -: Telegram takes no other as the"
			" webhook's secret, so setting the webhook will fail")
		cases = (({}, []), ({'slackBotToken': ''}, [no_reply]), ({'slackOutgoingToken': ''}, [slack_refused]),
			({'slackOutgoingToken': '', 'slackSigningSecret': 's'}, []),
			({'telegramOutgoingToken': ''}, [telegram_refused]), ({'telegramOutgoingWebhook': ''}, [unused]),
			({'telegramOutgoingWebhook': '', 'telegramOutgoingToken': ''}, []),
			({'telegramOutgoingToken': 'A-z_09' * 40}, []), ({'telegramOutgoingToken': 'x' * 257}, [bad_secret]),
			({'telegramOutgoingToken': 'pass word!'}, [bad_secret]),
			({'slackOutgoingWebhook': '', 'slackAppToken': 'xapp-1'}, []),
			({'slackOutgoingWebhook': '', 'slackAppToken': 'xapp-1', 'slackBotToken': ''}, [app_no_reply]),
			({'slackAppToken': 'xapp-1'}, [app_unused]),
			({'slackOutgoingWebhook': '', 'slackAppToken': 'xoxb-1'}, [not_app]),
			({'slackOutgoingWebhook': ''}, [deaf]))
		for changes, warnings in cases:
			with self.subTest(changes=changes), \
					mock.patch.object(config, 'env', dataclasses.replace(config.env, **{**hooks, **changes})):
				self.assertEqual(config.startup_warnings(), warnings)

	def test_discord_settings_that_leave_part_of_it_unable_to_work_are_warned_about(self):
		"""A startup warning for Discord's endpoint without the bot token, the endpoint without the app's public key
		(every interaction refused), and the key without the endpoint (the gateway is used)."""
		key = 'ab' * 32
		http = dict(discordBotToken='x', discordOutgoingWebhook='https://example.com/discord', discordPublicKey=key)
		no_reply = 'discordOutgoingWebhook is set but discordBotToken is not: Discord commands will get no reply'
		refused = ("discordOutgoingWebhook is set but discordPublicKey is not the app's public key (64 hex digits):"
			' every Discord interaction will be refused')
		unused = ('discordPublicKey is set but discordOutgoingWebhook is not: finbot keeps to the Discord gateway (pull'
			' mode), and the key is not used')
		cases = (({}, []), ({'discordBotToken': ''}, [no_reply]),
			({'discordBotToken': '', 'discordOutgoingWebhook': ''}, [unused]),
			({'discordPublicKey': 'not-hex'}, [refused]), ({'discordPublicKey': ''}, [refused]),
			({'discordOutgoingWebhook': ''}, [unused]), ({'discordOutgoingWebhook': '', 'discordPublicKey': ''}, []))
		for changes, warnings in cases:
			with self.subTest(changes=changes), \
					mock.patch.object(config, 'env', dataclasses.replace(config.env, **{**http, **changes})):
				self.assertEqual(config.startup_warnings(), warnings)

	def test_startup_report_is_a_short_count_never_names_or_values(self):
		"""The startup report counts the startup keys set and the settings, and never names them or shows their
		values."""
		with mock.patch.dict(os.environ, {'slackOutgoingWebhook': 'https://secret.example/abc', 'port': '5000'},
				clear=True):
			lines = config.startup_report()
		self.assertEqual(lines[0], 'startup environment (2 keys set)')
		self.assertNotIn('secret.example', ''.join(lines))
		self.assertNotIn('slackOutgoingWebhook', ''.join(lines))
		with mock.patch.dict(os.environ, {'port': '5000'}, clear=True):
			self.assertEqual(config.startup_report()[0], 'startup environment (1 key set)')
		conf = Path(common.temp_dir(self), 'settings.conf')
		conf.write_text('graph = false\n')
		for source, count in (({'graph': 'false'}, '1 key'), ({'log_level': 'DEBUG', 'graph': 'false'}, '2 keys')):
			with self.subTest(source=source), mock.patch.object(config, 'settings_path', str(conf)), \
					mock.patch.object(config, 'settings', dataclasses.replace(config.settings, source=source)):
				self.assertEqual(config.startup_report()[1], f'{conf} ({count} set; SIGHUP to reload)')
		with mock.patch.object(config, 'settings_path', str(conf.with_name('missing.conf'))):
			self.assertEqual(config.startup_report()[1], f'no settings.conf in {config.env.data_dir}, reload'
				' unavailable')


class SigHup(unittest.TestCase):
	def restore(self, file):
		"""Empty the settings file and reload: back to the defaults."""
		with mock.patch.object(config, 'settings_path', str(file)):
			file.write_text('')
			config.reload()

	def test_reload_all_reloads_settings_and_keeps_them_on_an_error(self):
		"""SIGHUP reloads settings; on an error (logged) the running ones stay, and the bot survives it. The jobs
		need no reload: a change made with .jobs counts at once."""
		file = Path(common.temp_dir(self), 'settings.conf')
		file.write_text('future_days=45\n')
		self.addCleanup(self.restore, file)
		with mock.patch.object(config, 'settings_path', str(file)):
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('config: future_days 30 -> 45', err.getvalue())
			file.write_text('futur_days=1\n')
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('ERROR config:', err.getvalue())
			self.assertEqual(config.settings.future_days, 45)

	def test_a_reload_points_a_key_set_in_the_template_at_the_file_to_set_it_in(self):
		"""A key set in defaults/settings.conf, which finbot never reads, is reported on a reload too, with the file
		to set it in."""
		file = Path(common.temp_dir(self), 'settings.conf')
		file.write_text('')
		self.addCleanup(self.restore, file)
		template = Path(common.temp_dir(self), 'template.conf')
		template.write_text('#past_days=28\nlog_level=DEBUG\n')
		with mock.patch.object(config, 'settings_path', str(file)), mock.patch.object(config, 'TEMPLATE', template):
			with contextlib.redirect_stderr(io.StringIO()) as err:
				bot.reload_all()
		self.assertIn(f'WARN config: defaults/settings.conf sets log_level, but finbot never reads it: edit {file}'
			' instead', err.getvalue())
		self.assertEqual(config.settings.log_level, 'INFO')


class Tools(unittest.TestCase):
	def test_check_config_script_exit_status_and_it_does_not_create_directories(self):
		"""check_config exits 0 for a good file, 1 for a bad one, and makes no data dir (systemd may run it as root)."""
		d = Path(common.temp_dir(self))
		(d / 'finbot.env').write_text('port=80\n')
		data = d / 'data'
		run = lambda: subprocess.run([sys.executable, str(REPO / 'util' / 'check_config.py'), str(d / 'finbot.env')],
			capture_output=True, text=True, env={**os.environ, 'DATA_DIR': str(data)})
		out = run()
		self.assertEqual(out.returncode, 0, out.stderr)
		self.assertFalse(data.exists()) # may run as root from systemd: must not create the data directory
		(d / 'finbot.env').write_text('future_days=3\n')
		out = run()
		self.assertEqual(out.returncode, 1)
		self.assertIn('ERROR config:', out.stderr)


if __name__ == '__main__':
	unittest.main()
