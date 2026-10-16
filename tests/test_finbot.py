"""Plumbing: message chunking, timezones, the WSGI handler."""
import ast, contextlib, datetime, io, json, re, subprocess, tempfile, unittest, zoneinfo
from pathlib import Path
from unittest import mock
from tests.common import *
from lib.reports import message


class Plumbing(FinbotCase):
	def test_chunked_send_keeps_keyboard_on_last_chunk(self):
		"""A long report goes out in several messages, and only the last carries the keyboard."""
		posted = []

		class Response:
			status_code = 200
			def json(self):
				"""Telegram's answer to a message posted."""
				return {'ok': True, 'result': {'message_id': len(posted), 'chat': {'id': 5}}}

		def post(url, **kwargs):
			"""Record what was posted and answer like Telegram."""
			posted.append(kwargs['json'])
			return Response()

		with mock.patch.object(net, 'post', post), mock.patch.object(transports.time, 'sleep', lambda s: 0):
			results = REAL_TEXT(telegram_common.TelegramBot('5'), ['x' * 60] * 300, {'keyboard': []})
		self.assertGreater(len(results), 1)
		self.assertEqual(len(posted), len(results))
		self.assertIn('reply_markup', posted[-1])
		self.assertTrue(all('reply_markup' not in p for p in posted[:-1]))

	def test_chunks_respect_the_size(self):
		"""A message ends before the line that would take it past the size limit; an overlong line is cut short."""
		chunks = transports.chunked(['a' * 30] * 10 + ['b' * 500], limit=100)
		self.assertEqual([len(chunk) for chunk in chunks], [3, 3, 3, 1, 1]) # 3 x 30 and 2 newlines: 92; 4 pass 100
		self.assertTrue(all(len('\n'.join(chunk)) <= 100 for chunk in chunks))
		self.assertEqual(chunks[-1], ['b' * 99 + '…']) # a line over the limit on its own is cut short
		self.assertEqual(transports.chunked(['x'] * 9, limit=4096), [['x'] * 9]) # however many lines fit

	def test_zoneinfo_offset_is_not_lmt(self):
		"""zoneinfo gives Melbourne its real offset, not the local mean time pytz once gave for old dates."""
		tz = zoneinfo.ZoneInfo('Australia/Melbourne')
		self.assertEqual(datetime.datetime(2022, 8, 18, tzinfo=tz).utcoffset(), datetime.timedelta(hours=10))

	def test_a_message_job_runs(self):
		"""A message job posts its text to its chat."""
		message.run(scheduled(), lines=['hello'])
		self.assertEqual(self.sent, [('text', ['hello'])])

	def test_bot_handler(self):
		"""A sticker is answered 200, with nothing logged at INFO, and at DEBUG only the request's line: a success is
		the routine; git_version matches what git says."""
		def post(message):
			"""Post a Telegram message update to the WSGI handler: (its answer, what it logged)."""
			body = json.dumps({'update_id': 1, 'message': dict({'message_id': 5, 'chat': {'id': 55, 'type': 'private'},
				'from': {'id': 9, 'first_name': 'Rob'}, 'date': 1}, **message)}).encode()
			env = wsgi_environ('/telegram', body, HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='tok')
			err = io.StringIO()
			with contextlib.redirect_stderr(err):
				out = bot.main(env, lambda *a, **k: None)
			return out, err.getvalue()
		self.assertEqual(post({'sticker': {'file_id': 'x'}}), ([b''], ''))
		self.settings(log_level='DEBUG')
		self.assertEqual(post({'sticker': {'file_id': 'x'}}), ([b''], 'POST from telegram: we answered 200 OK\n'))
		self.assertGreaterEqual(len(bot.git_version()), 7)
		head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=bot.__file__.rsplit('/', 1)[0], capture_output=True,
			text=True).stdout.strip()
		self.assertEqual(bot.git_version(), head[:7]) # matches what git says


class Conventions(unittest.TestCase):
	def test_every_function_has_a_docstring(self):
		"""Every function and method, in the tests too and nested ones included, says what it does."""
		missing = []
		code = [*Path(ROOT, 'lib').rglob('*.py'), *Path(ROOT).glob('*.py'), *Path(ROOT, 'util').glob('*.py'),
			*Path(ROOT, 'tests').glob('*.py')]
		for path in sorted(code):
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node) is None:
					missing.append(f'{path.relative_to(ROOT)}:{node.lineno} {node.name}')
		self.assertEqual(missing, [])

	def test_every_line_fits_in_120_columns(self):
		"""Every line of the code, the tests, the shipped defaults, the units, the tools, CI and the Docker files fits
		in 120 columns, tabs counting 4: an edit quotes whole lines. README.md, CLAUDE.md and doc/ are left out (CI runs
		no tests for a change to those alone, so no test may read them), and so are data files."""
		patterns = ('*.py', '*.service', 'lib/**/*.py', 'tests/*.py', 'util/*', 'defaults/*', '.github/workflows/*.yml',
			'.claude/hooks/*', 'Dockerfile', 'compose.yaml', '.dockerignore')
		files = sorted({path for pattern in patterns for path in Path(ROOT).glob(pattern)
			if path.is_file() and path.suffix != '.json'})
		long = [f'{path.relative_to(ROOT)}:{number}' for path in files
			for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
			if len(line.expandtabs(4)) > 120]
		self.assertGreater(len(files), 60)
		self.assertEqual(long, [])

	def test_nothing_imports_pandas(self):
		"""finbot has no use for pandas, which took 0.8 s and 37 MB to load for three small jobs on dated closes: no
		module imports it, not even inside a function."""
		files = [*Path(ROOT).glob('*.py'), *Path(ROOT, 'lib').rglob('*.py'), *Path(ROOT, 'util').glob('*.py'),
			*Path(ROOT, 'tests').glob('*.py')]
		found = [f'{path.relative_to(ROOT)}:{number}' for path in files
			for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
			if re.match(r'\s*(import|from) pandas\b', line)]
		self.assertGreater(len(files), 60)
		self.assertEqual(found, [])

	def test_the_bot_and_its_reports_print_only_to_stderr(self):
		"""systemd discards stdout (StandardOutput=null), so only util/ tools, run by hand, may print there."""
		offenders = []
		for path in sorted([*Path(ROOT, 'lib').rglob('*.py'), *Path(ROOT).glob('*.py')]):
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'print' and \
						not any(keyword.arg == 'file' for keyword in node.keywords):
					offenders.append(f'{path.name}:{node.lineno}')
		self.assertEqual(offenders, [])


class Timeouts(unittest.TestCase):
	def test_every_request_goes_through_net_with_a_timeout(self):
		"""The scheduled reports run in the bot's threads, which cannot be stopped: every request must end. So no module
		but lib/net.py calls requests itself (net gives each call its timeouts), and none passes timeout=None."""
		call = re.compile(r'\brequests\.(?:get|post|put|patch|delete|head|request|Session)\(')
		offenders = []
		for path in sorted([*Path(ROOT, 'lib').rglob('*.py'), Path(ROOT, 'bot.py'), *Path(ROOT, 'util').glob('*.py')]):
			for number, line in enumerate(path.read_text().splitlines(), 1):
				where = f'{path.relative_to(ROOT)}:{number}'
				if call.search(line) and path.name != 'net.py':
					offenders.append(f'{where} calls requests itself')
				if re.search(r'\btimeout\s*=\s*None\b', line):
					offenders.append(f'{where} passes timeout=None')
		self.assertEqual(offenders, [])


class OutputComparison(unittest.TestCase):
	def test_steps_are_compared_by_name_and_a_repeated_one_by_its_count(self):
		"""util/record_outputs.py --diff shows a step that changed, appeared or went; a step run twice is told apart."""
		from util import record_outputs
		with tempfile.TemporaryDirectory() as tmp:
			old, new = Path(tmp, 'old.json'), Path(tmp, 'new.json')
			post = lambda text: {'url': 'u', 'json': {'text': text}}
			step = lambda label, *texts: {'step': label, 'posts': [post(t) for t in texts], 'raised': None}
			old.write_text(json.dumps([step('add', 'Ok'), step('add', 'Again'), step('gone', 'x')]))
			new.write_text(json.dumps([step('add', 'Ok'), step('add', 'Once more'), step('new', 'y')]))
			out = io.StringIO()
			with contextlib.redirect_stdout(out):
				self.assertEqual(record_outputs.compare(old, new), 3)
				self.assertEqual(record_outputs.compare(old, old), 0)
		shown = out.getvalue()
		self.assertIn('== add (2)\n', shown)
		self.assertIn('-    "text": "Again"', shown)
		self.assertIn('== gone (only in the old recording)', shown)
		self.assertIn('== new (only in the new recording)', shown)
		self.assertIn('3 steps, identical', shown)


class GitVersion(unittest.TestCase):
	SHA = '0123456789abcdef0123456789abcdef01234567'

	def repo(self, tmp, head, refs=None, packed=None):
		"""A fake .git in tmp: HEAD, loose refs and packed-refs as given."""
		git = Path(tmp, '.git')
		git.mkdir(parents=True)
		(git / 'HEAD').write_text(head + '\n')
		for ref, sha in (refs or {}).items():
			(git / ref).parent.mkdir(parents=True, exist_ok=True)
			(git / ref).write_text(sha + '\n')
		if packed:
			(git / 'packed-refs').write_text('# pack-refs with: peeled fully-peeled sorted\n' + packed)
		return git

	def test_loose_ref_detached_and_packed(self):
		"""The commit is found from a loose ref, a detached HEAD, and a ref only in packed-refs."""
		with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as c:
			self.repo(a, 'ref: refs/heads/work', {'refs/heads/work': self.SHA})
			self.repo(b, self.SHA)
			self.repo(c, 'ref: refs/heads/work', packed=f'{self.SHA} refs/heads/work\n{"f" * 40} refs/heads/other\n')
			self.assertEqual([bot.git_version(d) for d in (a, b, c)], ['0123456'] * 3)

	def test_linked_worktree(self):
		"""A linked worktree, whose .git is a file naming its gitdir, finds its refs in the main repository."""
		with tempfile.TemporaryDirectory() as main, tempfile.TemporaryDirectory() as tree:
			git = self.repo(main, 'ref: refs/heads/main', {'refs/heads/main': self.SHA})
			linked = git / 'worktrees' / 'w'
			linked.mkdir(parents=True)
			(linked / 'HEAD').write_text('ref: refs/heads/main\n')
			(linked / 'commondir').write_text('../..\n')
			Path(tree, '.git').write_text(f'gitdir: {linked}\n')
			self.assertEqual(bot.git_version(tree), '0123456')

	def test_unreadable_is_unknown(self):
		"""No .git, a dangling ref, or a garbled HEAD all give 'unknown'."""
		with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as odd:
			self.repo(odd, 'ref: refs/heads/gone')
			self.assertEqual([bot.git_version(empty), bot.git_version(odd), bot.git_version('/nonexistent')],
				['unknown'] * 3)
			self.repo(empty, 'garbage')
			self.assertEqual(bot.git_version(empty), 'unknown')

	def test_an_image_without_git_names_the_commit_it_was_built_from(self):
		"""A Docker image has no .git: the commit it was built from (FINBOT_COMMIT, from the build's GIT_COMMIT) names
		the version; a value that is no commit is 'unknown', and a .git still wins."""
		with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as checkout:
			self.repo(checkout, self.SHA)
			for built, expected in ((self.SHA, '0123456'), ('abcdef1', 'abcdef1'), ('unknown', 'unknown'),
					('', 'unknown'), ('$(id)', 'unknown')):
				with self.subTest(built=built), mock.patch.dict(os.environ, {'FINBOT_COMMIT': built}):
					self.assertEqual(bot.git_version(empty), expected)
			with mock.patch.dict(os.environ, {'FINBOT_COMMIT': 'f' * 40}):
				self.assertEqual(bot.git_version(checkout), '0123456')

	def test_does_not_run_git(self):
		"""git_version reads .git itself: no git binary is run."""
		with mock.patch('subprocess.run', side_effect=AssertionError('git was run')):
			self.assertGreaterEqual(len(bot.git_version()), 7)


if __name__ == '__main__':
	unittest.main()
