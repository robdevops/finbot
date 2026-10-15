"""The Discord bot: interactions and messages read as the other networks' updates, the interactions endpoint and its
signatures, REST calls and their rate limits, messages with charts and buttons, slash commands from the command table,
and the gateway."""
import contextlib, io, json, sys, types, unittest
from tests.common import *
from lib import discord, pull

try:
	from nacl.signing import SigningKey
except ImportError: # PyNaCl is optional: only Discord's http mode needs it
	SigningKey = None


def interaction(kind, **fields):
	"""An interaction of this type in channel 77, from Rob in a server (fields replace the defaults)."""
	return {'id': '900', 'application_id': '42', 'token': 'tok', 'type': kind, 'channel_id': '77',
		'member': {'user': {'id': '5', 'username': 'rob', 'global_name': 'Rob'}}, **fields}


COMMAND = interaction(2, data={'name': 'price', 'options': [{'name': 'arguments', 'type': 3, 'value': '5 7d'}]})
PRESS = interaction(3, id='901', data={'custom_id': 'c|h|y|T1', 'component_type': 2}, message={'id': '333'})
MESSAGE = {'id': '700', 'channel_id': '77', 'author': {'id': '5', 'username': 'rob'}, 'content': '<@99> price 7d'}


class Now:
	"""threading.Thread that runs its target at start(), so that a test needs no waiting."""
	def __init__(self, target, args=(), daemon=None):
		"""The target and its arguments."""
		self.target, self.args = target, args

	def start(self):
		"""Run the target now."""
		self.target(*self.args)


class Reading(FinbotCase):
	"""An interaction reads the same however it arrives; a gateway message reads as Slack's do."""

	def setUp(self):
		"""The bot's user id is 99."""
		super().setUp()
		self.patch(inbound.DISCORD, 'bot_id', '99')

	def test_a_slash_command_is_the_message_it_stands_for(self):
		"""/price with its arguments is the message '/price 5 7d', answered through its interaction; in a DM the person
		is the interaction's user."""
		expected = inbound.Message('discord', '77', '<@5>', '/price 5 7d', '@99', 'Rob', '', '42/tok')
		self.assertEqual(inbound.DISCORD.parse(COMMAND), expected)
		dm = {k: v for k, v in COMMAND.items() if k != 'member'} | {'user': {'id': '5', 'username': 'rob'}}
		self.assertEqual(inbound.DISCORD.parse(dm), dataclasses.replace(expected, user_name='rob'))
		self.assertEqual(inbound.DISCORD.parse({**COMMAND, 'data': {'name': 'beta'}}).text, '/beta')

	def test_a_press_is_a_press_of_its_message(self):
		"""A button pressed is a Press of its message, its custom_id the button's data."""
		self.assertEqual(inbound.DISCORD.parse(PRESS),
			inbound.Press('discord', '901', '77', '333', 'c|h|y|T1', '@rob', '42/tok'))

	def test_a_message_by_a_person_reads_with_its_mentions_as_slacks(self):
		"""A gateway message's mentions read as @id, so that '@bot price 7d' calls .price; one by a bot or a webhook
		(this bot's replies included) is not answered."""
		message = inbound.DISCORD.parse(MESSAGE)
		self.assertEqual(message, inbound.Message('discord', '77', '<@5>', '@99 price 7d', '@99', 'rob', '700'))
		command, args = worker.read(message.text, message.bot_name)
		self.assertEqual((command.names[0], args.days), ('price', 7))
		for other in ({**MESSAGE, 'author': {'id': '99', 'bot': True}}, {**MESSAGE, 'webhook_id': '1'}):
			self.assertIs(inbound.DISCORD.parse(other), inbound.OK)

	def test_the_endpoints_check_and_other_interactions(self):
		"""A PING gets its PONG at once; an interaction of another kind is not taken."""
		self.assertEqual(json.loads(inbound.DISCORD.parse(interaction(1)).body), {'type': 1})
		self.assertIs(inbound.DISCORD.parse(interaction(5)), inbound.UNSUPPORTED)

	def test_an_interaction_is_answered_before_its_work_starts(self):
		"""A slash command is answered "thinking…" and a press with nothing to see, and the work waits in the answer
		until whoever delivers it starts it; a gateway message needs no answer, and its work starts at once."""
		taken = []
		self.patch(worker, 'process_request', taken.append)
		self.patch(worker, 'process_callback', taken.append)
		answer = bot.take(inbound.DISCORD, COMMAND)
		self.assertEqual(json.loads(answer.body), {'type': 5})
		self.join_workers()
		self.assertEqual(taken, [])
		answer.then()
		self.assertEqual(json.loads(bot.take(inbound.DISCORD, PRESS).body), {'type': 6})
		self.assertIs(bot.take(inbound.DISCORD, MESSAGE), inbound.OK)
		self.join_workers()
		self.assertEqual([event.text if isinstance(event, inbound.Message) else event.data for event in taken],
			['/price 5 7d', '@99 price 7d'])


@unittest.skipUnless(SigningKey, 'PyNaCl is not installed')
class Endpoint(FinbotCase):
	"""Discord's interactions endpoint: each request signed with the app's key; a bad signature gets the 401 Discord
	looks for."""

	def setUp(self):
		"""Discord in http mode, with a key of the test's own."""
		super().setUp()
		self.key = SigningKey.generate()
		self.env(discordBotToken='x', discordOutgoingWebhook='https://example.com/discord',
			discordPublicKey=self.key.verify_key.encode().hex())
		self.taken = []
		self.patch(worker, 'process_request', self.taken.append)
		self.patch(worker, 'process_callback', self.taken.append)

	def post(self, update, signature=None, timestamp='1700000000'):
		"""Post an interaction to the endpoint, signed unless a signature is given: (status, answer, body object)."""
		body = json.dumps(update).encode()
		if signature is None:
			signature = self.key.sign(timestamp.encode() + body).signature.hex()
		status = []
		with contextlib.redirect_stderr(io.StringIO()):
			out = bot.main(wsgi_environ('/discord', body, HTTP_X_SIGNATURE_ED25519=signature,
				HTTP_X_SIGNATURE_TIMESTAMP=timestamp), lambda s, *a: status.append(s))
		return status[0], b''.join(out), out

	def test_a_signed_check_gets_its_pong(self):
		"""Discord's check of the URL, signed, gets its PONG."""
		status, answer, _ = self.post(interaction(1))
		self.assertEqual((status, json.loads(answer)), ('200 OK', {'type': 1}))

	def test_a_bad_or_missing_signature_gets_401(self):
		"""A request signed with another key, or with no signature, is refused with a 401 and taken no further."""
		other = SigningKey.generate().sign(b'1700000000' + json.dumps(COMMAND).encode()).signature.hex()
		self.assertEqual(self.post(COMMAND, signature=other)[0], '401 Unauthorized')
		self.assertEqual(self.post(COMMAND, signature='')[0], '401 Unauthorized')
		self.join_workers()
		self.assertEqual(self.taken, [])

	def test_the_work_starts_once_discord_has_its_answer(self):
		"""A slash command is answered "thinking…" (a press, nothing to see); the work starts only once the server has
		sent that answer, which it says by closing the body."""
		status, answer, out = self.post(COMMAND)
		self.assertEqual((status, json.loads(answer)), ('200 OK', {'type': 5}))
		self.join_workers()
		self.assertEqual(self.taken, [])
		out.close()
		self.join_workers()
		self.assertEqual([message.text for message in self.taken], ['/price 5 7d'])
		self.assertEqual(json.loads(self.post(PRESS)[1]), {'type': 6})


class Sending(FinbotCase):
	"""DiscordBot: what each message, chart, edit and typing notice sends, and the rate limits waited out."""

	def setUp(self):
		"""The bot token set, and Discord's API answered from self.answers (else 200 and a message)."""
		super().setUp()
		self.env(discordBotToken='x', discordChannelID='77')
		self.calls, self.answers = [], []
		def request(method, url, **kwargs):
			"""Note the call, and give the next answer."""
			self.calls.append((method, url.removeprefix(discord.API), kwargs))
			return self.answers.pop(0) if self.answers else Resp({'id': '1'})
		self.patch(discord.net, 'request', request)
		self.patch(transports.Transport, 'text', REAL_TEXT)
		self.patch(transports.Transport, 'chart', REAL_CHART)

	def test_a_message_has_no_previews_or_pings_and_its_buttons_in_rows_of_five(self):
		"""A message suppresses link previews and pings nobody; its buttons go in rows of five, the one shown now
		blurple, and past 25 they are left out."""
		row = [buttons.Button(f'B{i}', f'c|h|w|{i}', active=i == 0) for i in range(12)]
		with contextlib.redirect_stderr(io.StringIO()):
			transports.DiscordBot('77').text(['hello'], [row[:7], row[7:]])
		method, path, kwargs = self.calls[0]
		self.assertEqual((method, path), ('POST', '/channels/77/messages'))
		payload = kwargs['json']
		self.assertEqual((payload['content'], payload['flags'], payload['allowed_mentions']), ('hello', 4,
			{'parse': []}))
		self.assertEqual([len(r['components']) for r in payload['components']], [5, 5, 2])
		self.assertEqual([b['style'] for b in payload['components'][0]['components']], [1, 2, 2, 2, 2])
		self.assertEqual(len(transports.components([[buttons.Button('x', 'y')] * 30])), 5)

	def test_a_chart_is_attached_to_its_report(self):
		"""A chart goes as an attachment of the message that carries the report and the buttons."""
		with contextlib.redirect_stderr(io.StringIO()):
			transports.DiscordBot('77').chart(io.BytesIO(b'png'), 'caption', [[buttons.Button('7D', 'c|h|w|T1')]])
		method, path, kwargs = self.calls[0]
		payload = json.loads(kwargs['data']['payload_json'])
		self.assertEqual((method, path, payload['content'], payload['attachments']), ('POST', '/channels/77/messages',
			'caption', [{'id': 0, 'filename': 'chart.png'}]))
		self.assertEqual(kwargs['files']['files[0]'], ('chart.png', b'png', 'image/png'))
		self.assertEqual(payload['components'][0]['components'][0]['custom_id'], 'c|h|w|T1')

	def test_a_slash_commands_answer_replaces_its_thinking_and_the_rest_follow_up(self):
		"""A slash command's first message replaces Discord's "thinking…", through its interaction, and the rest
		follow it up; there is no typing notice besides."""
		chat = transports.DiscordBot('77', interaction='42/tok')
		self.assertFalse(chat.shows_typing)
		with contextlib.redirect_stderr(io.StringIO()):
			chat.text(['x' * 1500, 'y' * 1500])
		self.assertEqual([(m, p) for m, p, _ in self.calls], [('PATCH', '/webhooks/42/tok/messages/@original'),
			('POST', '/webhooks/42/tok')])
		chat.typing_done()
		self.assertEqual(len(self.calls), 2) # answered: nothing to delete

	def test_a_slash_command_that_says_nothing_has_its_thinking_deleted(self):
		"""A slash command over without a word, or one that reads as no command, has its "thinking…" deleted, or it
		would show for 15 minutes."""
		transports.DiscordBot('77', interaction='42/tok').typing_done()
		worker.process_request(inbound.Message('discord', '77', '<@5>', '/nothing@else', '@99', 'Rob', '', '42/t2'))
		self.assertEqual([(m, p) for m, p, _ in self.calls], [('DELETE', '/webhooks/42/tok/messages/@original'),
			('DELETE', '/webhooks/42/t2/messages/@original')])

	def test_a_press_edits_its_message_through_its_interaction(self):
		"""A press edits its message through its own interaction (a message that answered a slash command can be
		edited only so); a new message about it goes into the channel."""
		chat = transports.DiscordBot('77', interaction='42/tok', pressed=True)
		chat.edit_chart('333', io.BytesIO(b'png'), 'caption', [[buttons.Button('1Y', 'c|h|y|T1', True)]])
		chat.edit_text('333', 'list', [])
		with contextlib.redirect_stderr(io.StringIO()):
			chat.text(['Too few prices'])
		self.assertEqual([(m, p) for m, p, _ in self.calls], [('PATCH', '/webhooks/42/tok/messages/@original'),
			('PATCH', '/webhooks/42/tok/messages/@original'), ('POST', '/channels/77/messages')])
		self.assertEqual(json.loads(self.calls[0][2]['data']['payload_json'])['attachments'],
			[{'id': 0, 'filename': 'chart.png'}])
		self.assertEqual(self.calls[1][2]['json'], {'content': 'list', 'components': []})

	def test_a_command_in_a_message_shows_typing(self):
		"""A command in a message (the gateway's) shows "typing…" in its channel."""
		chat = transports.DiscordBot('77', '700')
		self.assertTrue(chat.shows_typing)
		chat.typing()
		self.assertEqual(self.calls[0][:2], ('POST', '/channels/77/typing'))

	def test_rate_limits_are_waited_out_and_refusals_raise(self):
		"""A 429 waits as long as Discord asks, then tries again, three times at most; a refusal raises with Discord's
		reason; the token in an interaction's path is never logged."""
		slept = []
		self.patch(discord.time, 'sleep', slept.append)
		self.answers += [Resp({'retry_after': 0.25}, 429), Resp({'id': '5'})]
		self.assertEqual(discord.call('GET', '/users/@me'), {'id': '5'})
		self.assertEqual(slept, [0.25])
		self.answers += [Resp({'retry_after': 99}, 429)] * 3
		with self.assertRaisesRegex(RuntimeError, '429'):
			discord.call('GET', '/users/@me')
		self.assertEqual(slept, [0.25, 10, 10])
		self.answers.append(Resp({'message': 'Missing Access', 'code': 50001}, 403))
		err = io.StringIO()
		with contextlib.redirect_stderr(err):
			self.assertIsNone(discord.try_call('PATCH', '/webhooks/42/s3cret-token/messages/@original'))
		self.assertIn('403 Missing Access (50001)', err.getvalue())
		self.assertNotIn('s3cret-token', err.getvalue())

	def test_scheduled_reports_go_to_the_channel_with_their_buttons(self):
		"""With discordChannelID and the bot token, scheduled reports go to that channel as the bot, buttons and all;
		without the token, nowhere on Discord."""
		self.env(telegramChatID='')
		chats = delivery.default_chats()
		self.assertEqual([(type(chat).__name__, chat.where) for chat in chats], [('DiscordBot', '77')])
		self.assertTrue(chats[0].takes_buttons and chats[0].takes_charts)
		self.env(discordBotToken='')
		with self.assertRaisesRegex(RuntimeError, 'nowhere to post'):
			delivery.default_chats()


class Commands(FinbotCase):
	"""The slash commands, one per .help line, from the command table, as every network registers them."""

	def test_each_help_line_is_a_slash_command_that_reads_as_its_command(self):
		"""Each .help line has a slash command, named as a slash command may be (.forward pe is /forwardpe), and
		/help, /stock and /profile besides; each reads as its command, its arguments where it takes any."""
		commands = worker.slash_commands()
		names = [name for name, _, _ in commands]
		self.assertEqual(len(names), len(set(names)))
		for expected in ('help', 'dividend', 'earnings', 'buy', 'sell', 'session', 'premarket', 'forwardpe', 'stock',
				'profile', 'jobs'):
			self.assertIn(expected, names)
		for name, description, arguments in commands:
			with self.subTest(name=name):
				self.assertRegex(name, r'^[a-z0-9_-]{1,32}$')
				self.assertTrue(0 < len(description) <= 100)
				command, args = worker.read(f'/{name} {arguments}'.strip(), BOT)
				self.assertIsNotNone(command)
				self.assertEqual(command.handler, (worker.COMMANDS[0] if name == 'help' else command).handler)
		self.assertEqual(dict((n, a) for n, _, a in commands)['price'], '[percent|SYMBOL|top|bottom] [period]')
		self.assertEqual(dict((n, a) for n, _, a in commands)['beta'], '')

	def test_stock_and_profile_are_the_profile_command(self):
		""".stock SYMBOL and /profile SYMBOL are .SYMBOL; without a symbol, the usage."""
		self.assertEqual(self.command('.stock T1'), self.command('.T1'))
		self.assertEqual(self.command('/profile T1'), self.command('.T1'))
		self.assertEqual(self.command('.stock'), [('text', ['Usage: .SYMBOL', 'Usage: .stock SYMBOL'])])

	def test_registering_replaces_the_commands_only_when_they_differ(self):
		"""Registering puts the commands only when Discord's differ from them, and gives the bot's user id."""
		wanted = [discord.command('price', 'price [period]', '[period]')]
		calls = []
		def call(method, path, **kwargs):
			"""Answer as Discord would, the commands as registered now."""
			calls.append((method, path))
			return {'/applications/@me': {'id': '42'}, '/users/@me': {'id': '99'}}.get(path, registered)
		self.patch(discord, 'call', call)
		registered = [{**wanted[0], 'id': '1', 'version': '2', 'application_id': '42'}]
		self.assertEqual(discord.register([('price', 'price [period]', '[period]')]), '99')
		self.assertNotIn(('PUT', '/applications/42/commands'), calls)
		registered = []
		with contextlib.redirect_stderr(io.StringIO()):
			discord.register([('price', 'price [period]', '[period]')])
		self.assertIn(('PUT', '/applications/42/commands'), calls)

	def test_help_on_discord_lists_the_slash_commands(self):
		""".help on Discord lists each command as its slash command, which works in both modes; the messages that also
		work are given only over the gateway."""
		self.patch(inbound.DISCORD, 'bot_id', '99')
		sent = []
		self.patch(transports.Transport, 'text', lambda dest, lines, buttons=None: sent.append(lines) or [])
		message = inbound.Message('discord', '77', '<@5>', '/help', '@99', 'Rob', '', '42/tok')
		worker.process_request(message)
		self.assertIn('/forwardpe [SYMBOL|top|bottom|negative]', sent[0])
		self.assertIn('/stock SYMBOL', sent[0])
		self.assertIn('.price, or <@99> price', sent[0])
		self.env(discordOutgoingWebhook='https://example.com/discord')
		worker.process_request(message)
		self.assertNotIn('.price, or <@99> price', sent[1])


class FakeClient:
	"""discord.py's Client, enough for the gateway listener: its handlers get the raw messages of the test."""
	raw = []

	def __init__(self, intents, enable_debug_events=False):
		"""Note how it was made."""
		self.intents, self.debug, self.handlers = intents, enable_debug_events, {}
		FakeClient.made = self

	def event(self, handler):
		"""Register a handler by its name."""
		self.handlers[handler.__name__] = handler
		return handler

	async def __aenter__(self):
		"""Enter."""
		return self

	async def __aexit__(self, *exc):
		"""Leave: closed."""
		self.closed = True

	async def start(self, token):
		"""Connect: ready, then the raw messages, then fail as Discord does on a refused token."""
		self.token = token
		await self.handlers['on_ready']()
		for message in self.raw:
			await self.handlers['on_socket_raw_receive'](json.dumps(message))
		raise RuntimeError('Improper token has been passed.')


class Gateway(FinbotCase):
	"""The gateway through discord.py: its raw events taken as the endpoint's, an interaction answered over REST."""

	def setUp(self):
		"""Discord in pull mode, with discord.py replaced by the fake client, and threads that run at once."""
		super().setUp()
		self.env(discordBotToken='x', discordOutgoingWebhook='')
		intents = types.SimpleNamespace(message_content=False)
		library = types.SimpleNamespace(Client=FakeClient, VoiceClient=types.SimpleNamespace(warn_nacl=True),
			Intents=types.SimpleNamespace(default=lambda: intents))
		self.library = library
		self.patch(sys, 'modules', {**sys.modules, 'discord': library})
		self.patch(pull, 'threading', types.SimpleNamespace(Thread=Now)) # the listener's threads only
		self.calls = []
		self.patch(discord, 'call', lambda method, path, **kwargs: self.calls.append((method, path, kwargs)))

	def test_messages_and_interactions_are_taken_and_an_interaction_answered_first(self):
		"""The client asks for the message intents and raw events; MESSAGE_CREATE and INTERACTION_CREATE go to take, the
		rest is the client's; an interaction's answer goes to its callback before its work starts; a client that stops
		waits the back-off."""
		taken, order = [], []
		def take(network, update):
			"""Note the update; answer an interaction as the reader would, its work noted when started."""
			taken.append(update.get('content') or update['type'])
			if 'token' in update:
				return inbound.Response(body=b'{"type": 5}', then=lambda: order.append(('work', len(self.calls))))
			return inbound.OK
		FakeClient.raw = [{'op': 11}, {'op': 0, 't': 'READY', 'd': {}},
			{'op': 0, 't': 'MESSAGE_CREATE', 'd': MESSAGE}, {'op': 0, 't': 'INTERACTION_CREATE', 'd': COMMAND}]
		listener = pull.DiscordGateway()
		listener.failures = 3
		err = io.StringIO()
		with contextlib.redirect_stderr(err):
			self.assertEqual(listener.poll(take), 5) # ready reset the failures; then the refused token
		client = FakeClient.made
		self.assertTrue(client.debug and client.intents.message_content and client.closed)
		self.assertFalse(self.library.VoiceClient.warn_nacl)
		self.assertEqual(taken, ['<@99> price 7d', 2])
		self.assertEqual(self.calls, [('POST', '/interactions/900/tok/callback', {'json': {'type': 5}})])
		self.assertEqual(order, [('work', 1)])
		self.assertIn('discord: the gateway failed, trying again in 5 s: Improper token', err.getvalue())

	@unittest.skipUnless(SigningKey, 'PyNaCl is not installed')
	def test_a_press_over_the_gateway_is_the_press_the_endpoint_gets(self):
		"""The same press, posted to the endpoint (http mode) or sent over the gateway (pull mode), reaches the worker
		as the same Press."""
		presses = []
		self.patch(worker, 'process_callback', presses.append)
		key = SigningKey.generate()
		self.env(discordOutgoingWebhook='https://example.com/discord', discordPublicKey=key.verify_key.encode().hex())
		body = json.dumps(PRESS).encode()
		signature = key.sign(b'1700000000' + body).signature.hex()
		with contextlib.redirect_stderr(io.StringIO()):
			bot.main(wsgi_environ('/discord', body, HTTP_X_SIGNATURE_ED25519=signature,
				HTTP_X_SIGNATURE_TIMESTAMP='1700000000'), lambda *a: None).close()
			self.join_workers()
			self.patch(bot, '_updates_seen', collections.OrderedDict()) # a restart in the other mode
			self.env(discordOutgoingWebhook='')
			FakeClient.raw = [{'op': 0, 't': 'INTERACTION_CREATE', 'd': PRESS}]
			pull.DiscordGateway().poll(bot.take)
		self.join_workers()
		self.assertEqual(len(presses), 2)
		self.assertEqual(presses[0], presses[1])
		self.assertEqual(self.calls[0][1:], ('/interactions/901/tok/callback', {'json': {'type': 6}}))

	def test_discord_is_listened_to_with_its_token_and_no_endpoint(self):
		"""The gateway is used with the bot token and no discordOutgoingWebhook; with the URL (http mode), or without
		the token, it is not."""
		self.env(telegramBotToken='')
		self.assertEqual([type(listener) for listener in pull.listeners()], [pull.DiscordGateway])
		self.env(discordOutgoingWebhook='https://example.com/discord')
		self.assertEqual(pull.listeners(), [])
		self.env(discordOutgoingWebhook='', discordBotToken='')
		self.assertEqual(pull.listeners(), [])


if __name__ == '__main__':
	unittest.main()
