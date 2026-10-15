"""Discord's REST API as the bot (discordBotToken): calls that wait out Discord's rate limits, and the slash commands
registered as finbot starts. The same in both modes: the gateway and the interactions endpoint only bring updates in."""
import sys
import time

from lib import config
from lib import net

API = 'https://discord.com/api/v10'
TRIES = 3 # a call that Discord rate-limits is tried this many times at most
LONGEST_WAIT = 10 # seconds: a rate limit asking for longer is waited this long
SUPPRESS_EMBEDS = 4 # message flag: no link previews
NO_MENTIONS = {'parse': []} # text that looks like @everyone or a mention pings nobody
GUILD, BOT_DM = 0, 1 # where a slash command may be used: in servers, and in a DM with the bot
OPTION = 'arguments' # the name of a slash command's one option: its arguments as text


def call(method, path, **kwargs):
	"""A REST call as the bot: Discord's answer as JSON, or None when it is empty. A 429 waits as long as Discord asks
	(LONGEST_WAIT at most) and tries again. Raises RuntimeError with Discord's reason when it refuses, or a requests
	error."""
	headers = {'Authorization': 'Bot ' + config.env.discordBotToken, **kwargs.pop('headers', {})}
	for attempt in range(1, TRIES + 1):
		r = net.request(method, API + path, headers=headers, **kwargs)
		if r.status_code != 429 or attempt == TRIES:
			break
		time.sleep(min(retry_after(r), LONGEST_WAIT))
	if r.status_code >= 400:
		raise RuntimeError(f"Discord {method} {path}: {r.status_code} {reason(r)}")
	try:
		return r.json()
	except ValueError: # empty: 204 No Content
		return None


def try_call(method, path, **kwargs):
	"""call(), where a failure must not stop what the bot is doing: it is only logged, and None returned."""
	try:
		return call(method, path, **kwargs)
	except Exception as e:
		print(f"Discord {method} failed:", net.redact(e), file=sys.stderr)


def retry_after(response):
	"""The seconds a rate-limited answer asks to wait (its retry_after), or one when it does not say."""
	try:
		return float(response.json().get('retry_after'))
	except (ValueError, TypeError, AttributeError):
		return 1.0


def reason(response):
	"""Discord's reason for a refusal: its message and code, else the start of the body."""
	try:
		answer = response.json()
		return f"{answer['message']} ({answer.get('code')})"
	except (ValueError, TypeError, KeyError):
		return response.text[:200]


def command(name, description, arguments, completes=False):
	"""A slash command as Discord takes it: a chat command usable in servers and in a DM with the bot, and the arguments
	it takes, if any, as one optional text option that they describe; with completes, Discord asks finbot what to
	suggest as they are typed (an autocomplete interaction)."""
	option = {'type': 3, 'name': OPTION, 'description': arguments[:100], 'required': False, 'autocomplete': completes}
	return {'name': name, 'type': 1, 'description': description[:100], 'contexts': [GUILD, BOT_DM],
		'integration_types': [0], 'options': [option] if arguments else []}


def summary(commands):
	"""What of a list of slash commands Discord may differ on from ours, in a form to compare: an answer from Discord
	carries ids and versions besides."""
	return sorted((c['name'], c.get('description'), sorted(c.get('contexts') or []),
		[(o['name'], o.get('description'), o.get('required', False), o.get('autocomplete', False))
			for o in c.get('options') or []]) for c in commands)


def register(commands):
	"""Called once by bot.py as it starts, in both modes: make the application's slash commands these ([(name,
	description, arguments)], from worker.slash_commands), replacing them all only when they differ (Discord limits how
	many may be made in a day). Returns the bot's user id: a message that mentions it is for the bot. Raises
	RuntimeError, or a requests error."""
	application = call('GET', '/applications/@me')['id']
	wanted = [command(*entry) for entry in commands]
	path = f'/applications/{application}/commands'
	if summary(call('GET', path) or []) != summary(wanted):
		call('PUT', path, json=wanted)
		print(f"discord: {len(wanted)} slash commands registered", file=sys.stderr)
	return str(call('GET', '/users/@me')['id'])
