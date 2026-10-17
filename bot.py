#!/usr/bin/env python3

import signal
if __name__ == '__main__':
	# ignored until startup is done (the reload handler is installed last): its default action kills the bot
	signal.signal(signal.SIGHUP, signal.SIG_IGN)
	signal.signal(signal.SIGUSR1, signal.SIG_IGN) # likewise the cache flush
import collections, dataclasses, json, os, re, sys, threading, time, traceback
from pathlib import Path

from lib import log
from lib import config
from lib import discord_common
from lib import discord_webhook
from lib import discord_websocket
from lib import inbound
from lib import worker
from lib import jobs
from lib import net
from lib import slack_webhook
from lib import slack_websocket
from lib import telegram_common
from lib import telegram_longpolling
from lib import telegram_webhook
from lib import delivery
from lib import render
from lib.reports import cleanup

ROUTED = 'finbot.routed' # a request's WSGI environ: the network whose webhook path it came to (the path is a secret)
AUTHENTICATED = 'finbot.authenticated' # set once it has passed that network's check
MAX_BODY = 1 << 20 # bytes in a request body, at most: an update from Telegram or Slack takes a few thousand
WEBHOOKS = (telegram_webhook.WEBHOOK, slack_webhook.WEBHOOK, discord_webhook.WEBHOOK) # HTTP: each network posts
LISTENERS = (telegram_longpolling.TelegramPoll, slack_websocket.SlackSocket, discord_websocket.DiscordGateway) # pull
_updates_seen = collections.OrderedDict() # (service, update id) of the last updates taken, oldest first
_updates_lock = threading.Lock() # updates arrive on several threads: a resent one may race its first copy
DOUBLED = 1 # seconds in which the same message, from the same person in the same chat, is taken once
_said = {} # (service, chat, user, text) of the messages taken in the last DOUBLED seconds: when

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

def route(path):
	"""The webhook whose path this is, or None."""
	return next((hook for hook in WEBHOOKS if hook.path() and path == hook.path()), None)

def listeners():
	"""The listeners finbot.env asks for, each network's with its bot token and no webhook URL (Slack's also needs its
	app-level token): finbot fetches the updates of those networks itself."""
	return [kind() for kind in LISTENERS if kind.wanted()]

def doubled(message):
	"""Whether this message repeats one that the same person sent in the same chat in the last DOUBLED seconds:
	Telegram's mobile app can send a command twice (/start in a new chat), each its own update, and one answer is
	enough."""
	key = (message.service, message.chat_id, message.user, message.text.strip())
	now = time.monotonic()
	with _updates_lock:
		for old in [said for said, at in _said.items() if now - at > DOUBLED]:
			del _said[old]
		if key in _said:
			return True
		_said[key] = now
	return False

def main(environ, start_response):
	"""WSGI entry point. Never lets an exception escape. A failure handling an authenticated request is logged as an
	error report (report_error) and answered 200, so the service does not retry it into the chat again; before
	authentication, as a failed request, with a 500. Either names the network, not the path: a webhook's path is a
	secret (telegramOutgoingWebhook, slackOutgoingWebhook)."""
	try:
		return handle(environ, start_response)
	except Exception as e:
		if environ.get(AUTHENTICATED):
			delivery.report_error(e, context=environ[ROUTED])
			status = '200 OK'
		else:
			where = environ.get(ROUTED) or repr(environ.get('PATH_INFO'))
			log.error(f"request to {where} failed:", delivery.error_line(e))
			log.error(net.redact(traceback.format_exc()), end='')
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
		"""Answer the request: a status line and a body (logged, naming the network, not the path: at DEBUG when it is
		a success, the routine; else at INFO). Work that must wait for the answer starts once the server has sent it."""
		network = environ.get(ROUTED) or 'no network'
		(log.debug if response.status.startswith('2') else log.info)(
			f"{environ['REQUEST_METHOD']} from {network}: we answered {response.status}")
		start_response(response.status, [('Content-type', 'application/json')])
		return Sent([response.body], response.then) if response.then else [response.body]
	def print_headers(say=log.info):
		"""Log the request headers (at INFO, or as say() logs), Telegram's secret header redacted."""
		for name, value in sorted(environ.items()):
			say((name, '<redacted>' if name == 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' else value))
	if config.settings.print_headers:
		print_headers()
	path = environ.get('PATH_INFO', '')
	source = route(path)
	if source is None:
		log.warn("Unknown URI", repr(path))
		return respond(inbound.NOT_FOUND)
	environ[ROUTED] = source.service
	if why := source.refuse_unread(environ): # strangers are turned away before their body is read
		print_headers(log.warn)
		log.warn("refused:", why)
		return respond(inbound.FORBIDDEN)
	length = environ.get('CONTENT_LENGTH') or '0'
	if not length.isdigit() or int(length) > MAX_BODY:
		log.warn(f"{source.service.capitalize()} a body of {length!r} bytes refused unread")
		return respond(inbound.TOO_LARGE if length.isdigit() else inbound.BAD_REQUEST)
	body = environ['wsgi.input'].read(int(length)) # the body and no more: a server need not end the stream there
	try:
		update = source.decode(body)
	except ValueError:
		log.warn(f"{source.service.capitalize()} request body is not a JSON object")
		return respond(inbound.BAD_REQUEST)
	if why := source.refuse(environ, body, update):
		shown = {k: '<redacted>' if k == 'token' else v for k, v in update.items()} # Slack's verification token
		log.warn("warning:", why)
		log.warn(f"{source.service.capitalize()} refused update", json.dumps(shown, indent=4, default=str))
		return respond(source.REFUSED)
	environ[AUTHENTICATED] = True
	return respond(take(source.network, update))

class WholeLines:
	"""stderr, a whole line at a time. Threads log at once (a report's fetches, say), and print() writes its arguments,
	the spaces between them and the newline one by one, so their lines would mix ("TTL:cache hit:  34254 s/var/..."):
	each thread's pieces wait in a buffer of its own until its line ends, and the line goes out in one write."""
	def __init__(self, stream):
		"""stream: where the lines go."""
		self.stream = stream
		self.held = threading.local() # each thread's line so far
		self.lock = threading.RLock() # re-entrant: a signal handler that logs may interrupt a write

	def write(self, text):
		"""Hold text until its line ends, then write the whole line; returns its length, as a stream does."""
		lines, newline, rest = (getattr(self.held, 'text', '') + text).rpartition('\n')
		self.held.text = rest
		if newline:
			with self.lock:
				self.stream.write(lines + newline)
				self.stream.flush()
		return len(text)

	def flush(self):
		"""Write what this thread holds, though its line has not ended."""
		text, self.held.text = getattr(self.held, 'text', ''), ''
		with self.lock:
			if text:
				self.stream.write(text)
			self.stream.flush()

	def __getattr__(self, name):
		"""Anything else as the stream has it: fileno, encoding, isatty."""
		return getattr(self.stream, name)

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
	thread of its own (dispatch), unless it is a repeat (the same update resent, the same message sent again at once:
	doubled, or the same button pressed again: worker.repeated, acknowledged without a toast), or a press of a command
	only the admins may use, by someone else (worker.refused_press: an alert says so). It is acknowledged
	first, the one place that does (Network.acknowledge: Telegram's toast for a press). Returns the inbound.Response
	for the network; when the network must have it before any reply (Discord's interactions), the work waits in its
	`then`, for whoever delivers it."""
	event = network.parse(update)
	if isinstance(event, inbound.Response):
		return event
	if isinstance(event, inbound.Suggest): # answered here and at once, while the command is typed
		return network.suggestions(worker.suggest(f'{event.service}:{event.chat_id}', event.text))
	if seen_before(network.service, network.update_id(update)):
		log.info(f"{network.service.capitalize()} update {network.update_id(update)} seen already, not run again")
		return inbound.OK
	if isinstance(event, inbound.Message) and not event.interaction and doubled(event): # each interaction is answered
		who = f"{network.service.capitalize()} {event.chat_id} {event.user}"
		log.info(log.cut(f"{who} sent it again within {DOUBLED} s, not run again: {event.text}"))
		return inbound.OK
	if isinstance(event, inbound.Press) and (why := worker.refused_press(event)):
		log.info(f"{network.service.capitalize()} {event.chat_id} {event.user} refused: a button of an admins' command")
		return network.acknowledge(event, toast=why) or inbound.OK
	if isinstance(event, inbound.Press) and worker.repeated(event):
		log.info(f"{network.service.capitalize()} duplicate button press ignored")
		return network.acknowledge(event, toast=False) or inbound.OK
	answer = network.acknowledge(event)
	if answer is not None:
		return dataclasses.replace(answer, then=lambda: dispatch(event))
	dispatch(event)
	return inbound.OK

def dispatch(event):
	"""Hand a message or a button press to lib/worker, in a thread of its own, which it returns."""
	if isinstance(event, inbound.Press):
		log.debug(f"{event.service.capitalize()} button", event.user, "chat", event.chat_id, event.data)
		target = worker.process_callback
	else:
		log.info(log.cut(f"{event.service.capitalize()} {event.chat_id} {event.user} {event.text}"))
		target = worker.process_request
	thread = threading.Thread(target=target, args=(event,))
	thread.start()
	return thread

def git_version(checkout=None):
	"""Short hash of the checked-out commit, read straight from the .git directory: no git binary to run, and no
	"dubious ownership" refusal when the service user does not own the checkout. Without one (a Docker image), the
	commit it was built from (FINBOT_COMMIT); 'unknown' when neither can be read."""
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
		if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', head):
			return head[:7]
	except (OSError, IndexError):
		pass
	built = os.environ.get('FINBOT_COMMIT', '')
	return built[:7] if re.fullmatch(r'[0-9a-f]{7,64}', built) else 'unknown'

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
	"""SIGHUP: re-read settings.conf; a bad one is reported and leaves the running config untouched. A key set in
	defaults/settings.conf, which is never read, is pointed at the file to set it in. (Each chat's jobs need no
	reload: a change made with .jobs counts at once.)"""
	try:
		changes = config.reload()
		for change in changes:
			log.info('config:', change)
		log.info(f"config: reloaded {config.settings_path}, {len(changes)} change{'' if len(changes) == 1 else 's'}")
	except config.ConfigError as e:
		config.print_errors(e)
	if note := config.template_note(config.settings_path):
		log.warn('WARN config:', note)

def flush_cache(*args):
	"""SIGUSR1 (`systemctl kill -s USR1 finbot`): delete the cache and keep the state (watchlist, seen trades, ratings,
	schedule), then fill it again straight away with the warm jobs, in a thread of their own (a reload need not wait
	for them)."""
	try:
		removed = cleanup.run(days=0)
		log.info(f"cache: flushed {removed} file{'' if removed == 1 else 's'} from {config.env.cache_dir}")
	except Exception as e:
		log.error('ERROR', delivery.error_line(e, 'cache flush'))
	jobs.start_thread(jobs.warm_now, jobs.current)

def http_server():
	"""The HTTP server for the networks that post to finbot (those whose webhook is set), bound to ip and port, or None
	when none does. waitress is imported only then. Raises OSError when the port cannot be had."""
	if not any(hook.path() for hook in WEBHOOKS):
		return None
	import waitress
	return waitress.create_server(main, host=config.env.ip, port=config.env.port)

if __name__ == '__main__':
	sys.stderr = WholeLines(sys.stderr) # threads log at once: each line goes out whole
	log.info(f'Starting finbot {git_version()}')
	try:
		config.check_startup_environment()
	except config.ConfigError as e:
		config.print_errors(e)
		sys.exit(1)
	for line in config.startup_report():
		log.info('config:', line)
	for line in config.startup_warnings():
		log.warn('WARN config:', line)
	if os.getuid() == 0:
		log.warn("Running as superuser. This is not recommended.")
	jobs.current = jobs.Scheduler() # the scheduled jobs, which the .jobs chat command lists and changes
	jobs.current.load()
	render.preload()
	try:
		server = http_server() # bound before Telegram is given the URL
	except OSError as e:
		log.error(e)
		sys.exit(1)
	if server:
		log.info(f'Opening socket on http://{config.env.ip}:{server.effective_port}')
	else:
		log.info('No webhook is set: finbot takes no HTTP requests')
	if config.env.telegramBotToken:
		try: # here only, never on import: the webhook set (HTTP mode), or deleted for getUpdates (pull mode)
			(telegram_webhook if config.env.telegramOutgoingWebhook else telegram_longpolling).register()
			telegram_common.READER.bot_name = telegram_common.bot_name()
		except Exception as e:
			log.error('ERROR', delivery.error_line(e, 'telegram'))
			sys.exit(1)
		telegram_common.set_commands(worker.slash_commands()) # the menu; /profile and /job work typed
		threading.Thread(target=worker.refresh_keyboards, daemon=True).start() # stale DM keyboards, in the background
	if config.env.discordBotToken:
		discord_common.version = git_version() # in each request's User-Agent, as Discord asks
		try:
			discord_common.READER.bot_id = discord_common.register(worker.slash_commands())
		except Exception as e:
			log.error('ERROR', delivery.error_line(e, 'discord'))
			sys.exit(1)
	threading.Thread(target=jobs.current.run_forever, daemon=True).start() # the scheduled reports, formerly cron jobs
	for listener in listeners(): # the networks without a webhook: finbot fetches their updates
		threading.Thread(target=listener.run, args=(take,), daemon=True).start()
	# Startup is done. systemctl reload finbot: pick up an edited settings.conf
	signal.signal(signal.SIGHUP, in_thread(reload_all))
	signal.signal(signal.SIGUSR1, in_thread(flush_cache)) # systemctl kill -s USR1 finbot: delete the cache
	log.info('finbot is running: SIGHUP reloads, SIGUSR1 flushes the cache')
	if server:
		server.run()
	while True: # the threads do the work; this one waits for signals
		signal.pause()
