"""Plumbing: message chunking, timezones, the WSGI handler."""
import contextlib, datetime, io, json, subprocess, tempfile, unittest, zoneinfo
from pathlib import Path
from unittest import mock
from tests.common import *


class Plumbing(FinbotCase):
    def test_chunked_send_keeps_keyboard_on_last_chunk(self):
        posted = []

        class Response:
            status_code = 200
            def json(self): return {'ok': True, 'result': {'message_id': len(posted), 'chat': {'id': 5}}}

        def post(url, **kwargs):
            posted.append(kwargs['json'])
            return Response()

        with mock.patch.object(webhook.requests, 'post', post), mock.patch.object(webhook.time, 'sleep', lambda s: None):
            results = REAL_PAYLOAD_WRAPPER('telegram', 'https://api.telegram.org/botX/sendMessage?chat_id=5',
                ['x' * 60] * 300, '5', reply_markup={'keyboard': []})
        self.assertGreater(len(results), 1)
        self.assertEqual(len(posted), len(results))
        self.assertIn('reply_markup', posted[-1])
        self.assertTrue(all('reply_markup' not in p for p in posted[:-1]))

    def test_zoneinfo_offset_is_not_lmt(self):
        tz = zoneinfo.ZoneInfo('Australia/Melbourne')
        self.assertEqual(datetime.datetime(2022, 8, 18, tzinfo=tz).utcoffset(), datetime.timedelta(hours=10))

    def test_reminder_runs(self):
        with mock.patch.object(reminder, 'load_reminders', lambda: []):
            reminder.lambda_handler()

    def test_bot_handler(self):
        def post(message):
            body = json.dumps({'update_id': 1, 'message': dict({'message_id': 5, 'chat': {'id': 55, 'type': 'private'},
                'from': {'id': 9, 'first_name': 'Rob'}, 'date': 1}, **message)}).encode()
            env = {'PATH_INFO': '/telegram', 'wsgi.input': io.BytesIO(body), 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': 'tok'}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                out = bot.main(env, lambda *a, **k: None)
            return out, err.getvalue()
        self.assertEqual(post({'sticker': {'file_id': 'x'}}), ([b''], '')) # stickers: silent, not logged
        self.assertGreaterEqual(len(bot.git_version()), 7)
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=bot.__file__.rsplit('/', 1)[0], capture_output=True, text=True).stdout.strip()
        self.assertEqual(bot.git_version(), head[:7]) # matches what git says


class GitVersion(unittest.TestCase):
    SHA = '0123456789abcdef0123456789abcdef01234567'

    def repo(self, tmp, head, refs=None, packed=None):
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
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as c:
            self.repo(a, 'ref: refs/heads/work', {'refs/heads/work': self.SHA})
            self.repo(b, self.SHA)
            self.repo(c, 'ref: refs/heads/work', packed=f'{self.SHA} refs/heads/work\n{"f" * 40} refs/heads/other\n')
            self.assertEqual([bot.git_version(d) for d in (a, b, c)], ['0123456'] * 3)

    def test_linked_worktree(self):
        with tempfile.TemporaryDirectory() as main, tempfile.TemporaryDirectory() as tree:
            git = self.repo(main, 'ref: refs/heads/main', {'refs/heads/main': self.SHA})
            linked = git / 'worktrees' / 'w'
            linked.mkdir(parents=True)
            (linked / 'HEAD').write_text('ref: refs/heads/main\n')
            (linked / 'commondir').write_text('../..\n')
            Path(tree, '.git').write_text(f'gitdir: {linked}\n')
            self.assertEqual(bot.git_version(tree), '0123456')

    def test_unreadable_is_unknown(self):
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as odd:
            self.repo(odd, 'ref: refs/heads/gone')
            self.assertEqual([bot.git_version(empty), bot.git_version(odd), bot.git_version('/nonexistent')], ['unknown'] * 3)
            self.repo(empty, 'garbage')
            self.assertEqual(bot.git_version(empty), 'unknown')

    def test_does_not_run_git(self):
        with mock.patch('subprocess.run', side_effect=AssertionError('git was run')):
            self.assertGreaterEqual(len(bot.git_version()), 7)


if __name__ == '__main__':
    unittest.main()
