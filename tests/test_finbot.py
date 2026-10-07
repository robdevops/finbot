"""Plumbing: message chunking, timezones, the WSGI handler."""
import contextlib, datetime, io, json, unittest, zoneinfo
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


if __name__ == '__main__':
    unittest.main()
