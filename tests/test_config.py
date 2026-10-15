"""The two config files: finbot.env (the startup file, which the launcher loads) and preferences.conf (reloadable)."""
import ast, contextlib, dataclasses, io, os, re, subprocess, sys, unittest
from pathlib import Path
from unittest import mock
from tests import common # first: it sets the environment that lib.config reads as it loads
from lib import config
from util import check_config, split_env
import bot
from lib import cache, yahoo

REPO = Path(config.__file__).resolve().parent.parent


def fields(prefs):
	"""A Prefs as {name: value}, without the file's own lines."""
	return {name: getattr(prefs, name) for name in config.PREFERENCE_KEYS}


def keys_in(path):
	"""Every KEY= in a template, active or commented out."""
	return re.findall(r'^#?\s*([A-Za-z_][A-Za-z0-9_]*)=', Path(path).read_text(), re.M)


class Tables(unittest.TestCase):
	def test_the_two_key_sets_are_disjoint_and_cover_everything_config_reads(self):
		"""Startup and preference keys do not overlap: config.py reads each startup key by name, and each preference
		as a field of Prefs."""
		self.assertEqual(set(config.STARTUP_KEYS) & set(config.PREFERENCE_KEYS), set())
		source = (REPO / 'lib' / 'config.py').read_text()
		read = set(re.findall(r"""(?:\br\.\w+|getenv)\(\s*['"]([A-Za-z_]+)['"]""", source))
		read -= {'STATE_DIRECTORY'} # systemd's own variable, a source for DATA_DIR
		self.assertEqual(read, set(config.STARTUP_KEYS))

	def test_secrets_are_startup_keys(self):
		"""Every secret is a startup key: preferences.conf holds none."""
		self.assertTrue(set(config.SECRET_KEYS) <= set(config.STARTUP_KEYS))
		self.assertEqual(len(config.SECRET_KEYS), 12)

	def test_unset_preferences_take_their_defaults(self):
		"""An unset preference takes its field's default, as it is: reading tidies nothing away."""
		values = config.preference_values(lambda name, default=None: default)
		self.assertEqual(fields(values), fields(config.Prefs()))

	def test_templates_have_every_key_and_the_real_defaults(self):
		"""defaults/preferences.conf and finbot.env list every key, change no default, and are valid as shipped."""
		self.assertEqual(sorted(keys_in(REPO / 'defaults' / 'preferences.conf')), sorted(config.PREFERENCE_KEYS))
		self.assertEqual(sorted(keys_in(REPO / 'defaults' / 'finbot.env')), sorted(config.STARTUP_KEYS))
		prefs = config.read_preferences(REPO / 'defaults' / 'preferences.conf')
		shipped = config.preference_values(config._getenv_for(prefs))
		self.assertEqual(fields(shipped), fields(config.Prefs())) # the template changes nothing
		startup = config.read_startup_file(REPO / 'defaults' / 'finbot.env')
		config.startup_values(lambda name, default=None: startup.get(name, default)) # and is valid as it stands


class Parsing(unittest.TestCase):
	def parse(self, text):
		"""(what read_preferences makes of text, the file it was written to)."""
		path = Path(common.temp_dir(self), 'preferences.conf')
		path.write_text(text)
		return config.read_preferences(path), path

	def errors(self, text):
		"""The errors read_preferences raises for text."""
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
		"""No preferences.conf is not an error: None."""
		self.assertIsNone(config.read_preferences(Path(common.temp_dir(self), 'nope')))

	def test_unknown_key_gets_a_hint_and_a_line_number(self):
		"""An unknown key is reported with its line number and the key it was probably meant to be."""
		errors = self.errors('future_days=3\nfutur_days=3\n')
		self.assertEqual(len(errors), 1)
		self.assertIn('line 2: unknown key futur_days (did you mean future_days?)', errors[0])

	def test_a_startup_key_in_preferences_says_where_it_belongs(self):
		"""A startup key in preferences.conf is sent to finbot.env, without printing its value."""
		errors = self.errors('slack_webhook=https://x\nip=0.0.0.0\ntelegramChatID=5\nscheduler=False\n')
		self.assertEqual(len(errors), 4)
		for line in errors:
			self.assertIn('belongs in finbot.env (a change needs a restart)', line)
		self.assertNotIn('https://x', ''.join(errors)) # a value is never printed

	def test_malformed_lines_sections_duplicates_and_the_old_name(self):
		"""Sections, lines not KEY=value, a key set twice and the renamed volatile_multiplier are all reported."""
		errors = self.errors('[reports]\nnot a setting\nfuture_days=1\nfuture_days=2\nvolatile_multiplier=3\n')
		self.assertEqual(len(errors), 4)
		self.assertIn('no sections', errors[0])
		self.assertIn('expected KEY=value', errors[1])
		self.assertIn('future_days is set twice', errors[2])
		self.assertIn('renamed to volatility_multiplier', errors[3])

	def test_every_problem_is_reported_not_just_the_first(self):
		"""Every problem in the file is reported at once."""
		self.assertEqual(len(self.errors('futur_days=1\nport=1\n[x]\n')), 3)

	def test_invalid_values_are_named(self):
		"""A value of the wrong type is reported with its key and value."""
		prefs = {'future_days': 'abc', 'price_percent': 'x'}
		with self.assertRaises(config.ConfigError) as caught:
			config.preference_values(config._getenv_for(prefs))
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn("future_days='abc' is not a whole number", caught.exception.errors[0])

	def test_booleans_take_the_usual_words_and_refuse_a_typo(self):
		"""Booleans take true/false, yes/no, on/off and 1/0 in any case; a typo is an error (it used to mean False)."""
		for word, value in (('True', True), ('yes', True), ('ON', True), ('1', True), ('false', False), ('No', False),
				('off', False), ('0', False)):
			with self.subTest(word=word):
				self.assertIs(config.preference_values(config._getenv_for({'graph': word})).graph, value)
		with self.assertRaises(config.ConfigError) as caught: # it used to mean False without a word
			config.preference_values(config._getenv_for({'graph': 'Ture'}))
		self.assertIn("graph='Ture' is not true or false", caught.exception.errors[0])

	def test_a_blank_value_means_the_default(self):
		"""A key with a blank value takes its default, but for exchange_suffix, where blank means no suffix to try."""
		values = config.preference_values(config._getenv_for({'cache': '', 'future_days': '', 'country_code': ''}))
		self.assertEqual((values.cache, values.future_days, values.country_code), (True, 30, 'AU'))
		for given, suffix in (('', ''), ('AX', 'AX'), ('.ax', 'AX'), (' NZ ', 'NZ')):
			with self.subTest(given=given):
				values = config.preference_values(config._getenv_for({'exchange_suffix': given}))
				self.assertEqual(values.exchange_suffix, suffix)
		self.assertEqual(config.preference_values(config._getenv_for({})).exchange_suffix, 'AX') # unset: the default

	def test_a_retired_key_is_accepted_and_said_to_do_nothing(self):
		"""A key finbot no longer reads (alliterate, say) does not stop a start, as an unknown key would: it is ignored,
		and the log at start says to delete it."""
		path = Path(common.temp_dir(self), 'preferences.conf')
		path.write_text(''.join(f'{key}=True\n' for key in config.RETIRED) + 'future_days=45\n')
		values = config.read_preferences(path)
		self.assertEqual(config.preference_values(config._getenv_for(values)).future_days, 45)
		notes = [f'{key} in preferences.conf does nothing any more: delete the line' for key in config.RETIRED]
		self.assertEqual(config.retired_notes(values), notes)
		self.assertEqual(check_config.notes(path), config.retired_notes(values))

	def test_unreadable_file_is_an_error_naming_it(self):
		"""A preferences file that cannot be read is an error that names it."""
		path = Path(common.temp_dir(self), 'preferences.conf')
		path.mkdir() # reading a directory fails like a permission error would
		with self.assertRaises(config.ConfigError) as caught:
			config.read_preferences(path)
		self.assertIn(f'cannot read {path}', caught.exception.errors[0])

	def test_precedence_file_then_environment_then_default(self):
		"""A preference comes from the file, else the environment, else its default."""
		with mock.patch.dict(os.environ, {'future_days': '5', 'past_days': '4'}):
			values = config.preference_values(config._getenv_for({'future_days': '30'}))
		self.assertEqual((values.future_days, values.past_days, values.shorts_percent), (30, 4, 15))

	def test_the_old_multiplier_name_is_gone_everywhere(self):
		"""volatile_multiplier is no longer read, and in the environment it stops the start with the new name."""
		with mock.patch.dict(os.environ, {'volatile_multiplier': '3'}):
			# not read any more
			self.assertEqual(config.preference_values(config._getenv_for({})).volatility_multiplier, 2.0)
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertIn('volatile_multiplier was renamed to volatility_multiplier', caught.exception.errors[0])
		values = config.preference_values(config._getenv_for({'volatility_multiplier': '4'}))
		self.assertEqual(values.volatility_multiplier, 4.0)

	def test_startup_file_linting(self):
		"""util/check_config.py reports bad lines in finbot.env first, then bad values, and nothing for a good file."""
		path = Path(common.temp_dir(self), 'finbot.env')
		path.write_text('ip=1.2.3.4\nfuture_days=3\nslak_webhook=x\nport=http\n')
		problems = check_config.check(path, Path(common.temp_dir(self), 'none'))
		self.assertEqual(len(problems), 2) # the two bad lines; the bad value is only found once the lines are valid
		self.assertIn('future_days belongs in preferences.conf (it is reloadable)', problems[0])
		self.assertIn('unknown key slak_webhook (did you mean slack_webhook?)', problems[1])
		path.write_text('port=http\n')
		nowhere = Path(common.temp_dir(self), 'none')
		self.assertIn("port='http' is not a whole number", check_config.check(path, nowhere)[0])
		path.write_text('port=80\n')
		self.assertEqual(check_config.check(path, Path(common.temp_dir(self), 'none')), [])


class Reload(unittest.TestCase):
	def setUp(self):
		"""An empty preferences.conf of this test's own, put back to the defaults afterwards."""
		self.file = Path(common.temp_dir(self), 'preferences.conf')
		self.file.write_text('')
		patch = mock.patch.object(config, 'preferences_path', str(self.file))
		patch.start()
		self.addCleanup(patch.stop)
		self.addCleanup(self.back_to_defaults)

	def back_to_defaults(self):
		"""Empty the file and reload, so the next test starts from the defaults."""
		self.file.write_text('')
		config.reload()

	def write(self, text):
		"""Write the preferences file."""
		self.file.write_text(text)

	def test_a_change_is_seen_at_once(self):
		"""A reload applies every change, says which, and swaps in a new object, so no request sees half a reload."""
		self.write('future_days=45\nprice_percent=7\nshorts_percent=12\nexclude_portfolios=1156263\n'
			'exchange_suffix=nz\nhyperlinkProvider=yahoo\n'
			'hyperlinkFooter=false\ndebug=1\ngraph=0\ndemote_volatile=0\nvolatility_multiplier=3\npast_days=14\n'
			'min_analysts=3\n')
		before = config.prefs
		changes = config.reload()
		self.assertEqual(len(changes), 13)
		self.assertIn('future_days 30 -> 45', changes)
		self.assertIsNot(config.prefs, before) # one new object: no request sees half a reload
		self.assertEqual((config.prefs.future_days, config.prefs.past_days, config.prefs.price_percent,
			config.prefs.min_analysts), (45, 14, 7.0, 3))
		prefs = config.prefs
		self.assertEqual((prefs.exclude_portfolios, prefs.exchange_suffix, prefs.hyperlinkProvider,
			prefs.hyperlinkFooter), (('1156263',), 'NZ', 'yahoo', False))
		self.assertEqual((config.prefs.debug, config.prefs.graph, config.prefs.demote_volatile,
			config.prefs.volatility_multiplier), (True, False, False, 3.0))
		self.assertEqual(config.reload(), []) # nothing more to change

	def test_a_value_removed_from_the_file_goes_back_to_its_default(self):
		"""A key taken out of the file goes back to its default on reload."""
		self.write('future_days=45\n')
		config.reload()
		self.write('# empty\n')
		self.assertEqual(config.reload(), ['future_days 45 -> 30'])
		self.assertEqual(config.prefs.future_days, 30)

	def test_defaults_that_follow_a_preference_are_read_when_called(self):
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
				'future_days=3\nslack_webhook=x\n'):
			self.write(text)
			with self.assertRaises(config.ConfigError):
				config.reload()
			self.assertEqual(config.prefs.future_days, 45)

	def test_a_missing_file_is_an_error_and_keeps_the_running_values(self):
		"""A reload with the file gone is an error and keeps the running values."""
		self.write('future_days=45\n')
		config.reload()
		self.file.unlink()
		with self.assertRaises(config.ConfigError) as caught:
			config.reload()
		self.assertIn('does not exist; nothing reloaded', caught.exception.errors[0])
		self.assertEqual(config.prefs.future_days, 45)
		self.file.write_text('')

	def test_nothing_copies_the_config_or_freezes_a_preference(self):
		"""Modules read config.prefs.<name> when they run, so that a reload is seen: no star import (which copied every
		name into each module), and no function default or module constant computed from a preference."""
		def reads_prefs(node):
			"""Whether an expression reads config.prefs."""
			return any(isinstance(n, ast.Attribute) and n.attr == 'prefs' and isinstance(n.value,
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
						if reads_prefs(default):
							offenders.append(f'{path.name}:{node.lineno} default of {node.name}')
			for node in tree.body:
				if isinstance(node, ast.Assign) and reads_prefs(node.value):
					offenders.append(f'{path.name}:{node.lineno} module constant')
		self.assertEqual(offenders, [])

	def test_a_job_process_runs_on_the_snapshot_not_the_edited_file(self):
		"""A job process gets the bot's preferences in its environment and does not read the file, which may have been
		edited since; a script run by hand reads the file."""
		self.write('future_days=45\n')
		config.reload()
		env = config.child_environment()
		self.assertEqual((env['future_days'], env[config.PASSED]), ('45', '1'))
		self.write('future_days=99\n') # edited, no reload sent
		data = common.temp_dir(self)
		Path(data, 'preferences.conf').write_text('future_days=99\n')
		show = "from lib import config as c; print(c.prefs.future_days)"
		parent = {k: v for k, v in os.environ.items() if k not in config.PREFERENCE_KEYS and k != config.PASSED}
		run = lambda **extra: subprocess.run([sys.executable, '-c', show], cwd=REPO, capture_output=True, text=True,
			check=True, env={**parent, 'DATA_DIR': data, **extra}).stdout.split()[-1]
		self.assertEqual(run(**env), '45') # the parent's values, and the file is not read
		self.assertEqual(run(), '99') # a script run by hand reads the file itself

	def test_run_child_hands_the_snapshot_to_the_job(self):
		"""run_child passes the preferences in force to the job process."""
		from lib import jobs
		seen = {}
		real = jobs.subprocess.Popen
		def popen(args, **kw):
			"""Note the environment the job is started with, and run a no-op instead."""
			seen.update(kw.get('env', {}))
			return real([sys.executable, '-c', 'pass'])
		self.write('future_days=45\n')
		config.reload()
		with mock.patch.object(jobs.subprocess, 'Popen', popen):
			from lib.reports import cleanup
			self.assertEqual(jobs.run_child('cleanup.py', cleanup, {}), 0)
		self.assertEqual((seen['future_days'], seen[config.PASSED]), ('45', '1'))


class Startup(unittest.TestCase):
	def run_config(self, code='from lib import config as c; print(c.prefs.future_days)', prefs=None, **env):
		"""Run code in a new interpreter: own data dir, prefs as preferences.conf, no settings in the environment."""
		data = common.temp_dir(self)
		if prefs is not None:
			Path(data, 'preferences.conf').write_text(prefs)
		env = {**common.bare_environment(), 'DATA_DIR': data, **env}
		return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=env,
			capture_output=True, text=True)

	def test_no_preferences_file_is_fine(self):
		"""finbot starts without a preferences.conf, on the defaults."""
		out = self.run_config()
		self.assertEqual((out.returncode, out.stdout.split()[-1]), (0, '30'))

	def test_a_preferences_file_is_read_at_start(self):
		"""preferences.conf is read at start."""
		self.assertEqual(self.run_config(prefs='future_days=45\n').stdout.split()[-1], '45')

	def test_a_broken_preferences_file_refuses_to_start(self):
		"""A bad value, unknown key, startup key or malformed line in preferences.conf stops the start, saying why."""
		for prefs, expect in (('future_days=abc\n', "future_days='abc' is not a whole number"),
			('futur_days=1\n', 'unknown key futur_days'),
				('slack_webhook=x\n', 'belongs in finbot.env'), ('what\n', 'expected KEY=value')):
			out = self.run_config(prefs=prefs)
			self.assertEqual(out.returncode, 1, prefs)
			self.assertIn('ERROR config:', out.stderr)
			self.assertIn(expect, out.stderr)

	def test_an_unreadable_preferences_file_refuses_to_start(self):
		"""A preferences.conf that cannot be read stops the start."""
		data = common.temp_dir(self)
		Path(data, 'preferences.conf').mkdir()
		out = subprocess.run([sys.executable, '-c', 'from lib import config'], cwd=REPO,
			env={**os.environ, 'DATA_DIR': data}, capture_output=True, text=True)
		self.assertEqual(out.returncode, 1)
		self.assertIn('cannot read', out.stderr)

	def test_a_bad_startup_value_refuses_to_start(self):
		"""A bad value in finbot.env stops the start, saying which."""
		out = self.run_config(port='http')
		self.assertEqual(out.returncode, 1)
		self.assertIn("port='http' is not a whole number", out.stderr)

	def test_a_preference_in_the_environment_is_refused_by_the_bot(self):
		"""A preference in the bot's environment (finbot.env) is refused, but a job process gets its preferences that
		way, and startup keys belong there."""
		with mock.patch.dict(os.environ, {'future_days': '30', 'debug': '1'}):
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn('future_days is a preference; move it from finbot.env to preferences.conf',
			'\n'.join(caught.exception.errors))
		with mock.patch.dict(os.environ, {'future_days': '30', config.PASSED: '1'}):
			config.check_startup_environment() # a job process gets its preferences this way
		with mock.patch.dict(os.environ, {'ip': '1.2.3.4', 'telegramChatID': '5'}):
			config.check_startup_environment() # startup keys are what the environment is for

	def test_the_bot_refuses_to_start_with_a_preference_in_its_environment(self):
		"""bot.py exits 1 when finbot.env holds a preference."""
		out = subprocess.run([sys.executable, 'bot.py'], cwd=REPO, capture_output=True, text=True, timeout=60,
			env={**os.environ, 'DATA_DIR': common.temp_dir(self), 'future_days': '30'})
		self.assertEqual(out.returncode, 1)
		self.assertIn('future_days is a preference', out.stderr)

	def test_a_leftover_env_in_the_checkout_refuses_to_start(self):
		"""An old .env in the checkout stops the start, pointing to util/split_env.py."""
		old = Path(common.temp_dir(self), '.env')
		with mock.patch.object(config, 'OLD_ENV', old):
			config.check_startup_environment() # none there: fine
			old.write_text("future_days = '30'\n")
			with self.assertRaises(config.ConfigError) as caught:
				config.check_startup_environment()
		self.assertEqual(len(caught.exception.errors), 2)
		self.assertIn(f'{old} is the old single config file, which finbot no longer reads', caught.exception.errors[0])
		self.assertIn('/util/split_env.py, which writes finbot.env.new and preferences.conf.new',
			caught.exception.errors[1])

	def test_a_discord_webhook_uses_the_native_endpoint(self):
		"""A Discord webhook URL is used as is, its old /slack suffix removed."""
		# the old setup's suffix
		for url in ('https://discord.com/api/webhooks/1/abc', 'https://discord.com/api/webhooks/1/abc/slack/'):
			values = config.startup_values(lambda name, default=None: url if name == 'discord_webhook' else default)
			self.assertEqual(values.webhooks['discord'], 'https://discord.com/api/webhooks/1/abc')

	def test_settings_that_leave_part_of_the_bot_unable_to_work_are_warned_about(self):
		"""A startup warning for Slack commands or slackChannelID without slackBotToken (no reply, no reports there),
		and for an inbound webhook without its secret (every request would be refused)."""
		hooks = dict(slackOutgoingWebhook='https://example.com/slack', slackOutgoingToken='stok',
			slackBotToken='xoxb-1', telegramOutgoingWebhook='https://example.com/telegram', telegramOutgoingToken='tok')
		no_reply = 'slackOutgoingWebhook is set but slackBotToken is not: Slack commands will get no reply'
		slack_refused = ('slackOutgoingWebhook is set but neither slackSigningSecret nor slackOutgoingToken is:'
			' every Slack request will be refused')
		telegram_refused = ('telegramOutgoingWebhook is set but telegramOutgoingToken is not: every Telegram update'
			' will be refused')
		no_bot = 'slackChannelID is set but slackBotToken is not: scheduled reports cannot go there as the bot'
		cases = (({}, []), ({'slackBotToken': ''}, [no_reply]), ({'slackOutgoingToken': ''}, [slack_refused]),
			({'slackChannelID': 'C9'}, []), ({'slackChannelID': 'C9', 'slackBotToken': ''}, [no_reply, no_bot]),
			({'slackOutgoingToken': '', 'slackSigningSecret': 's'}, []),
			({'telegramOutgoingToken': ''}, [telegram_refused]), ({'telegramOutgoingWebhook': ''}, []))
		for changes, warnings in cases:
			with self.subTest(changes=changes), \
					mock.patch.object(config, 'env', dataclasses.replace(config.env, **{**hooks, **changes})):
				self.assertEqual(config.startup_warnings(), warnings)

	def test_startup_report_is_a_short_count_never_names_or_values(self):
		"""The startup report counts the startup keys set, and never names them or shows their values."""
		with mock.patch.dict(os.environ, {'slack_webhook': 'https://secret.example/abc', 'port': '5000'}, clear=True):
			lines = config.startup_report()
		keys = len(config.STARTUP_KEYS)
		self.assertEqual(lines[0], f'startup environment provides 2 of {keys} startup keys (values hidden)')
		self.assertLessEqual(len('config: ' + lines[0]), 90) # the path in the second line depends on where DATA_DIR is
		self.assertNotIn('secret.example', ''.join(lines))
		self.assertNotIn('slack_webhook', ''.join(lines))


class SigHup(unittest.TestCase):
	def restore(self, file):
		"""Empty the preferences file and reload: back to the defaults."""
		with mock.patch.object(config, 'preferences_path', str(file)):
			file.write_text('')
			config.reload()

	def test_reload_all_reloads_preferences_and_the_schedule_independently(self):
		"""SIGHUP reloads preferences, keeping the running ones on an error (logged), and the schedule regardless."""
		file = Path(common.temp_dir(self), 'preferences.conf')
		file.write_text('future_days=45\n')
		scheduler = mock.Mock()
		self.addCleanup(self.restore, file)
		with mock.patch.object(config, 'preferences_path', str(file)), mock.patch.object(bot, 'scheduler', scheduler):
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('config: future_days 30 -> 45', err.getvalue())
			scheduler.reload.assert_called_once()
			# a preferences error does not stop the schedule reload, and the bot survives it
			file.write_text('futur_days=1\n')
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				bot.reload_all()
			self.assertIn('ERROR config:', err.getvalue())
			self.assertEqual(scheduler.reload.call_count, 2)
			self.assertEqual(config.prefs.future_days, 45)

	def test_reload_with_the_scheduler_off_still_reloads_preferences(self):
		"""With the scheduler off, SIGHUP still reloads preferences."""
		file = Path(common.temp_dir(self), 'preferences.conf')
		file.write_text('future_days=11\n')
		self.addCleanup(self.restore, file)
		with mock.patch.object(config, 'preferences_path', str(file)), mock.patch.object(bot, 'scheduler', None):
			with contextlib.redirect_stderr(io.StringIO()):
				bot.reload_all()
			self.assertEqual(config.prefs.future_days, 11)


class Tools(unittest.TestCase):
	def test_split_env(self):
		"""split_env sorts an old .env into startup keys and prefs, renames volatile_multiplier, lists what it drops."""
		startup, prefs, notes = split_env.split('slack_webhook=x\nfuture_days=3\nvolatile_multiplier=2\nslackToken=y\n'
			'STATE_DIRECTORY=/a\nbogus=1\nnot a setting\n# c\nport=80\n')
		self.assertEqual(startup, ['slack_webhook=x', 'port=80'])
		self.assertEqual(prefs, ['future_days=3', 'volatility_multiplier=2'])
		self.assertEqual(len(notes), 4)
		self.assertTrue(any('slackToken dropped' in n for n in notes) and any('unknown key bogus' in n for n in notes))

	def test_split_env_reads_the_old_dotenv_format_too(self):
		"""split_env reads the old dotenv format: quotes, export, comments after values and # inside URLs."""
		old = ("# c\nfuture_days = '30' # note\nexport slack_webhook = \"https://x/#frag\"\nport = 80 # comment\nbare\n"
			"discord_webhook=http://y/#z\n\n")
		startup, prefs, notes = split_env.split(old)
		self.assertEqual(startup, ['slack_webhook=https://x/#frag', 'port=80', 'discord_webhook=http://y/#z'])
		self.assertEqual(prefs, ['future_days=30'])
		self.assertEqual(notes, ['.env line 5: not KEY=value, left out'])

	def test_split_env_writes_next_to_the_file_and_never_overwrites(self):
		"""split_env writes finbot.env.new (mode 0600) and preferences.conf.new beside the file, refuses to overwrite
		them, and says so for a missing file."""
		d = Path(common.temp_dir(self))
		(d / 'old.env').write_text('port=80\nfuture_days=3\n')
		run = lambda: subprocess.run([sys.executable, str(REPO / 'util' / 'split_env.py'), str(d / 'old.env')],
			capture_output=True, text=True)
		self.assertEqual(run().returncode, 0)
		self.assertIn('port=80', (d / 'finbot.env.new').read_text())
		self.assertIn('future_days=3', (d / 'preferences.conf.new').read_text())
		self.assertEqual(oct((d / 'finbot.env.new').stat().st_mode & 0o777), '0o600')
		out = run()
		self.assertNotEqual(out.returncode, 0)
		self.assertIn('refusing to overwrite', out.stderr)
		out = subprocess.run([sys.executable, str(REPO / 'util' / 'split_env.py'), str(d / 'missing.env')],
			capture_output=True, text=True)
		self.assertEqual((out.returncode, out.stderr.strip()), (1, f'{d}/missing.env does not exist: nothing to split'))

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
