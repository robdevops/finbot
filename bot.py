#!/usr/bin/env python3

import signal
if __name__ == '__main__':
	# ignored until startup is done (the reload handler is installed last): its default action kills the bot
	signal.signal(signal.SIGHUP, signal.SIG_IGN)
	signal.signal(signal.SIGUSR1, signal.SIG_IGN) # likewise the cache flush
import collections, dataclasses, json, os, re, sys, threading, traceback
from pathlib import Path

from lib import config
from lib import discord
from lib import inbound
from lib import worker
from lib import jobs
from lib import migrate
from lib import net
from lib import pull
from lib import telegram
from lib import delivery
from lib import render
from lib.reports import cleanup

ROUTED = 'finbot.routed' # a request's WSGI environ: the network whose webhook path it came to (the path is a secret)
AUTHENTICATED = 'finbot.authenticated' # set once it has passed that network's check
MAX_BODY = 1 << 20 # bytes in a request body, at most: an update from Telegram or Slack takes a few thousand
_updates_seen = collections.OrderedDict() # (service, update id) of the last updates taken, oldest first
_updates_lock = threading.Lock() # updates arrive on several threads: a resent one may race its first copy

def seen_before(service, update_id, keep=1000):
	"""Whether this update was taken already: Telegram's update_id, Slack's event_id. Slack resends an event it got no
	answer to within 3 seconds and Telegram one that failed, and a command must not run twice. An update without an id
	is never a repeat."""
	if update_id is None:
		return False
	key = (service, update_id)
	with _updates_lock:
		if key in _updates_seen:
			return True
		_updates_seen[key] = None
		if len(_updates_seen) > keep:
			_updates_seen.popitem(last=False)
	return False

def main(environ, start_response):
	"""WSGI entry point. Never lets an exception escape. A failure handling an authenticated request is reported as one
	line to the default channel and answered 200, so the service does not retry it into the chat again. Before
	authentication a failure is only logged: a stranger must not be able to post into the chats. Either names the
	network, not the path: a webhook's path is a secret (telegramOutgoingWebhook, slackOutgoingWebhook)."""
	try:
		return handle(environ, start_response)
	except Exception as e:
		if environ.get(AUTHENTICATED):
			delivery.report_error(e, context=environ[ROUTED])
			status = '200 OK'
		else:
			where = environ.get(ROUTED) or repr(environ.get('PATH_INFO'))
			print(f"request to {where} failed:", delivery.error_line(e), file=sys.stderr)
			print(net.redact(traceback.format_exc()), end='', file=sys.stderr)
			status = '500 Internal Server Error'
		try:
			start_response(status, [('Content-type', 'text/plain')], sys.exc_info())
		except Exception:
			pass
		return [b'']

def handle(environ, start_response):
	"""Route a request by its path to the webhook of the network that posts there, turn it away unless it proves it
	comes from that network (before its body is read, when the proof is a header), read the update (CONTENT_LENGTH
	bytes, up to MAX_BODY) and take it (take): the network gets its answer at once."""
	def respond(response):
		"""Answer the request: a status line and a body (logged with the debug preference, naming the network, not the
		path). Work that must wait for the answer starts once the server has sent it."""
		if config.prefs.debug:
			print(f"[http] request for {environ.get(ROUTED) or 'no network'} answered {response.status}",
				file=sys.stderr)
		start_response(response.status, [('Content-type', 'application/json')])
		return Sent([response.body], response.then) if response.then else [response.body]
	def print_headers():
		"""Log the request headers, Telegram's secret header redacted."""
		for name, value in sorted(environ.items()):
			print((name, '<redacted>' if name == 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' else value), file=sys.stderr)
	if config.prefs.print_headers:
		print_headers()
	path = environ.get('PATH_INFO', '')
	source = inbound.route(path)
	if source is None:
		print("Unknown URI", repr(path), file=sys.stderr)
		return respond(inbound.NOT_FOUND)
	environ[ROUTED] = source.service
	if why := source.refuse_unread(environ): # strangers are turned away before their body is read
		print_headers()
		print("Fatal:", why, file=sys.stderr)
		return respond(inbound.FORBIDDEN)
	length = environ.get('CONTENT_LENGTH') or '0'
	if not length.isdigit() or int(length) > MAX_BODY:
		print(f"[{source.service}]: a body of {length!r} bytes refused unread", file=sys.stderr)
		return respond(inbound.TOO_LARGE if length.isdigit() else inbound.BAD_REQUEST)
	body = environ['wsgi.input'].read(int(length)) # the body and no more: a server need not end the stream there
	try:
		update = source.decode(body)
	except ValueError:
		print(f"[{source.service}]: request body is not a JSON object", file=sys.stderr)
		return respond(inbound.BAD_REQUEST)
	if why := source.refuse(environ, body, update):
		shown = {k: '<redacted>' if k == 'token' else v for k, v in update.items()} # Slack's verification token
		print("warning:", why, file=sys.stderr)
		print(f"[{source.service}]: refused update", json.dumps(shown, indent=4, default=str), file=sys.stderr)
		return respond(source.REFUSED)
	environ[AUTHENTICATED] = True
	return respond(take(source.network, update))

class Sent(list):
	"""A response body that starts some work once the server has sent it: WSGI calls close() then."""
	def __init__(self, body, then):
		"""body: the chunks; then: the work."""
		super().__init__(body)
		self.then = then

	def close(self):
		"""The answer is out: start the work."""
		self.then()

def take(network, update):
	"""An update from a network (an inbound.Network reads it), however it arrived: what it says goes to lib/worker in a
	thread of its own (dispatch), unless it is a repeat. It is acknowledged first, the one place that does
	(Network.acknowledge: Telegram's toast for a press). Returns the inbound.Response for the network; when the network
	must have it before any reply (Discord's interactions), the work waits in its `then`, for whoever delivers it."""
	event = network.parse(update)
	if isinstance(event, inbound.Response):
		return event
	if seen_before(network.service, network.update_id(update)):
		print(f"[{network.service}]: update {network.update_id(update)} seen already, not run again", file=sys.stderr)
		return inbound.OK
	answer = network.acknowledge(event)
	if answer is not None:
		return dataclasses.replace(answer, then=lambda: dispatch(event))
	dispatch(event)
	return inbound.OK

def dispatch(event):
	"""Hand a message or a button press to lib/worker, in a thread of its own, which it returns."""
	if isinstance(event, inbound.Press):
		print(f"[{event.service.capitalize()} button]:", event.user, "chat", event.chat_id, event.data, file=sys.stderr)
		target = worker.process_callback
	else:
		if config.prefs.debug:
			print(f"[{event.service.capitalize()}]:", event.user, event.text, file=sys.stderr)
		target = worker.process_request
	thread = threading.Thread(target=target, args=(event,))
	thread.start()
	return thread

def git_version(checkout=None):
	"""Short hash of the checked-out commit, read straight from the .git directory: no git binary to run, and no
	"dubious ownership" refusal when the service user does not own the checkout. 'unknown' when it cannot be read."""
	try:
		git = Path(checkout or config.REPO_DIR) / '.git'
		if git.is_file(): # a linked worktree or submodule: .git is a file saying "gitdir: <path>"
			git = (git.parent / git.read_text().split(':', 1)[1].strip()).resolve()
		# refs of a worktree
		common = (git / (git / 'commondir').read_text().strip()).resolve() if (git / 'commondir').is_file() else git
		head = (git / 'HEAD').read_text().strip()
		if head.startswith('ref:'):
			ref = head.split(':', 1)[1].strip()
			if (common / ref).is_file():
				head = (common / ref).read_text().strip()
			else: # the branch is only in packed-refs
				packed = (common / 'packed-refs').read_text().splitlines()
				head = next((line.split()[0] for line in packed if line.endswith(' ' + ref)), '')
		return head[:7] if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head) else 'unknown'
	except (OSError, IndexError):
		return 'unknown'

scheduler = None
_signal_work = threading.Lock() # one signal's work at a time: a second reload waits for the first

def in_thread(work):
	"""A signal handler that runs `work` in a thread of its own and returns at once: a handler must not wait on the
	network, nor on a lock that the code it interrupted may hold."""
	def run():
		"""The work, once any other signal's is done."""
		with _signal_work:
			work()
	return lambda *args: threading.Thread(target=run, daemon=True).start()

def reload_all(*args):
	"""SIGHUP: re-read preferences.conf; a bad one is reported and leaves the running config untouched. (Each chat's
	jobs need no reload: a change made with .jobs counts at once.)"""
	try:
		changes = config.reload()
		for change in changes:
			print('config:', change, file=sys.stderr)
		print(f"config: reloaded {config.preferences_path}, {len(changes)} change{'' if len(changes) == 1 else 's'}",
			file=sys.stderr)
	except config.ConfigError as e:
		config.print_errors(e)

def flush_cache(*args):
	"""SIGUSR1 (`systemctl kill -s USR1 finbot`): delete the cache and keep the state (watchlist, seen trades, ratings,
	schedule), then fill it again straight away with the warm jobs, in a thread of their own (a reload need not wait
	for them)."""
	try:
		removed = cleanup.run(days=0)
		print(f"cache: flushed {removed} file{'' if removed == 1 else 's'} from {config.env.cache_dir}",
			file=sys.stderr)
	except Exception as e:
		print('ERROR', delivery.error_line(e, 'cache flush'), file=sys.stderr)
	jobs.start_thread(jobs.warm_now, scheduler)

def http_server():
	"""The HTTP server for the networks that post to finbot (those whose webhook is set), bound to ip and port, or None
	when none does. waitress is imported only then. Raises OSError when the port cannot be had."""
	if not any(hook.path() for hook in inbound.WEBHOOKS):
		return None
	import waitress
	return waitress.create_server(main, host=config.env.ip, port=config.env.port)

if __name__ == '__main__':
	print(f'Starting finbot {git_version()}', file=sys.stderr)
	try:
		config.check_startup_environment()
	except config.ConfigError as e:
		config.print_errors(e)
		sys.exit(1)
	for line in config.startup_report():
		print('config:', line, file=sys.stderr)
	for line in config.startup_warnings():
		print('ERROR config:', line, file=sys.stderr)
	if os.getuid() == 0:
		print("Running as superuser. This is not recommended.", file=sys.stderr)
	migrate.run() # once: what was kept for all chats becomes the home chats', schedule.cron among it
	scheduler = jobs.Scheduler()
	scheduler.load()
	render.preload()
	try:
		server = http_server() # bound before Telegram is given the URL
	except OSError as e:
		print(e, file=sys.stderr)
		sys.exit(1)
	if server:
		print(f'Opening socket on http://{config.env.ip}:{server.effective_port}', file=sys.stderr)
	else:
		print('No webhook is set: finbot takes no HTTP requests', file=sys.stderr)
	if config.env.telegramBotToken:
		try:
			inbound.TELEGRAM.bot_name = telegram.register() # here only: the job processes import lib.telegram too
		except Exception as e:
			print('ERROR', delivery.error_line(e, 'telegram'), file=sys.stderr)
			sys.exit(1)
		telegram.set_commands(worker.slash_commands(aliases=False)) # the menu; /profile and /job work typed
		threading.Thread(target=worker.refresh_keyboards, daemon=True).start() # stale DM keyboards, in the background
	if config.env.discordBotToken:
		try:
			inbound.DISCORD.bot_id = discord.register(worker.slash_commands())
		except Exception as e:
			print('ERROR', delivery.error_line(e, 'discord'), file=sys.stderr)
			sys.exit(1)
	jobs.current = scheduler # for the .jobs chat command
	threading.Thread(target=scheduler.run_forever, daemon=True).start() # the scheduled reports, formerly cron jobs
	for listener in pull.listeners(): # the networks without a webhook: finbot fetches their updates
		threading.Thread(target=listener.run, args=(take,), daemon=True).start()
	# Startup is done. systemctl reload finbot: pick up an edited preferences.conf
	signal.signal(signal.SIGHUP, in_thread(reload_all))
	signal.signal(signal.SIGUSR1, in_thread(flush_cache)) # systemctl kill -s USR1 finbot: delete the cache
	print('finbot is running: SIGHUP reloads, SIGUSR1 flushes the cache', file=sys.stderr)
	if server:
		server.run()
	while True: # the threads do the work; this one waits for signals
		signal.pause()
