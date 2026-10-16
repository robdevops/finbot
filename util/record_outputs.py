#!/usr/bin/env python3
"""Old/new output comparison for refactors. It records every HTTP request the bot posts (the URL with the bot token
redacted, the JSON or form body, a hash of each file) for a fixed list of chat commands, button presses and scheduled
reports, run on the offline fixtures of tests/common.py, and compares two recordings step by step.

	util/record_outputs.py                       this tree (uncommitted changes included) against HEAD
	util/record_outputs.py --against COMMIT      this tree against COMMIT; both are recorded in this run, so dates match
	util/record_outputs.py --record OUT.json     record the tree in the current directory only
	util/record_outputs.py --diff OLD.json NEW.json

--keep DIR keeps the two recordings; --full shows changed lines whole. The exit status is 0 when the recordings match,
1 when they differ."""
import argparse, contextlib, difflib, hashlib, importlib, inspect, io, json, os, random, subprocess, sys, tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMANDS = ['.help', '/start', '.hello', '.thanks', '.who T1', '.plan buy low', '.plan', '.holdings', '.holdings Rob',
	'.marketcap', '.marketcap bottom', '.marketcap T1', '.pe', '.pe bottom', '.pe T1', '.fpe', '.fpe bottom',
	'.fpe negative', '.forward pe T1', '.peg', '.peg negative', '.peg T1', '.beta', '.buy', '.sell', '.buy & sell',
	'.earnings', '.earnings T1', '.dividend', '.dividend T1', '.trades', '.trades 30d', '.trades 7d Nope', '.price',
	'.price 7d', '.price 3', '.price 3 7d', '.price top', '.price top 7d', '.price T1', '.price T1 7d', '.session',
	'.session T1', '.premarket', '.postmarket', '.shorts', '.shorts 30', '.shorts T1', '.performance',
	'.performance 7d', '.performance 1y', '.performance Nope', '.pie Rob', '.pie Rob sector', '.pie', '.compare T1 T2',
	'.compare T1 T2 3m', '.compare T1', '.history T1', '.history', '.watchlist', '.watchlist add MSFT',
	'.watchlist add MSFT', '.watchlist del MSFT', '.watchlist frob X', '.T1', '.jobs', '.jobs run', '.jobs toggle',
	'.jobs add', '.jobs add shorts daily at 22:00', '.jobs del 4', '.jobs run 1', '.jobs next', '.jobs system',
	'hi @bot', 'noise']
BUTTONS = ['c|h|m|T1', 'c|h|x|T1', 'c|p|w|T1', 'c|c|y|T1,T2', 'c|f|y|', 'c|l|d|3,0', 'c|l|m|0,10', 'c|zz|m|T1',
	'j|1|0000', 'e|1|0000', 'm|on|0|0000', 'm|add|0000', 'm|add|5|w|0000', 'm|next|0000']
JOBS = ['*/20 * * * Mon-Fri trades', '29 21 * * Mon-Fri price interday', # each chat's, for .jobs (as cron had them)
	'28 21 * * Sat cal earnings; cal ex-dividend; price 7; performance 7; rating']
ADDED = ['trades every 20 mins weekdays', 'price daily at 21:29', 'cal earnings every saturday at 21:28'] # since cron
SCHEDULED = ['trades', 'price midsession', 'price interday', 'price premarket', 'price close', 'price 7',
	'cal earnings', 'cal ex-dividend', 'performance 7', 'rating', 'shorts', 'milestone', 'reminder']
TELEGRAM_API = 'https://api.telegram.org/botX/'
ANSWER = {'ok': True, 'upload_url': 'https://files.slack.com/u', 'file_id': 'F1', 'id': '1'} # good enough for every API


def digest(value):
	"""A short hash of a file's bytes (or a file object's, or text), for a recording that stays small."""
	if hasattr(value, 'read'):
		if hasattr(value, 'seek'):
			value.seek(0)
		value = value.read()
	if isinstance(value, str):
		value = value.encode()
	return 'sha256:' + hashlib.sha256(value).hexdigest()[:16]


def record(output):
	"""Run every step on the tree in the current directory and write what each posted to `output` (JSON)."""
	here = Path(__file__).resolve().parent
	sys.path[:] = [os.getcwd()] + [path for path in sys.path if Path(path or '.').resolve() != here] # the tree's code
	from tests import common
	from lib import jobs, net, worker
	real_sending = getattr(common, 'REAL_SENDING', None)
	if real_sending is None: # a commit from before REAL_SENDING, when lib/webhook.py did the sending
		from lib import webhook
		real_sending = ((webhook, 'payload_wrapper', common.REAL_PAYLOAD_WRAPPER),
			(webhook, 'sendPhoto', common.REAL_SEND_PHOTO), (webhook, 'report_error', common.REAL_REPORT_ERROR))

	def handing(func, kind, *fields):
		"""A step that hands func the Message or Press (kind, its name in lib.inbound) of these fields, or the fields
		one by one to a commit from before it took the object."""
		if len(inspect.signature(func).parameters) > 1:
			return lambda: func(*fields)
		return lambda: func(getattr(common.inbound, kind)(*fields))

	def reader(service):
		"""The tree's reader of a network's updates: READER in lib/<service>_common.py, or in a commit from before the
		protocol code was split per network, lib/inbound.py's TELEGRAM, SLACK or DISCORD (None before the readers)."""
		try:
			return importlib.import_module(f'lib.{service}_common').READER
		except ImportError:
			return getattr(getattr(common, 'inbound', None), service.upper(), None)

	def pressing(service, *fields):
		"""A step that presses a button: acknowledged first where the tree's bot.take does that (Network.acknowledge),
		then handed to the worker as handing() does."""
		run = handing(worker.process_callback, 'Press', service, *fields)
		network = reader(service)
		if not hasattr(network, 'acknowledge'):
			return run
		def press():
			"""Acknowledge the press, then hand it to the worker."""
			network.acknowledge(common.inbound.Press(service, *fields))
			run()
		return press

	class Record(common.FinbotCase):
		"""The steps, as one test, so that FinbotCase's fixtures (and their cleanup) apply."""
		def runTest(self):
			"""Record what each step posts: the real sending code runs, and net.post notes each request."""
			posts = []
			def post(url, method='POST', **kwargs):
				"""Note a request, the typing notices aside (Telegram's, Slack's ⏳, Discord's: timing, not output), and
				answer like the APIs do."""
				if 'sendChatAction' in url or '/reactions.' in url or url.endswith('/typing'):
					return common.mock.Mock(status_code=200, json=lambda: {'ok': True, 'result': True})
				entry = {'url': url.replace('botX/', 'bot<token>/'), **({'method': method} if method != 'POST' else {})}
				for key in ('json', 'data', 'params'):
					body = kwargs.get(key)
					if isinstance(body, dict):
						entry[key] = {k: digest(v) if isinstance(v, (bytes, bytearray)) else v for k, v in body.items()}
					elif body is not None:
						entry[key] = digest(body)
				if kwargs.get('files'):
					entry['files'] = {name: [part[0], digest(part[1])] for name, part in kwargs['files'].items()}
				posts.append(entry)
				answer = {**ANSWER, 'result': {'message_id': len(posts), 'chat': {'id': 5}}}
				return common.mock.Mock(status_code=200, json=lambda: answer, text='OK')
			self.patch(net, 'post', post)
			if hasattr(net, 'request'): # Discord's calls, since the Discord bot
				self.patch(net, 'request', lambda method, url, **kwargs: post(url, method, **kwargs))
			for target, name, real in real_sending: # what the fixture replaces with recorders, put back
				self.patch(target, name, real)
			self.patch(common.time, 'sleep', lambda seconds: None) # no pauses between a long report's messages
			self.env(slackBotToken='xoxb-test', slackOutgoingWebhook='https://example.com/slack') # Slack's buttons too
			if 'discordBotToken' in {field.name for field in common.dataclasses.fields(common.config.env)}:
				self.env(discordBotToken='discord-test')
			chats = ('telegram:55', 'slack:C1', 'discord:77')
			if hasattr(jobs, 'JOBS_FILE'): # the default jobs and those each chat added, since schedules of finbot's own
				added = [jobs.make_job(*jobs.parse_add(text, 'UTC'), 'telegram:55').stored() for text in ADDED]
				common.state.save(jobs.JOBS_FILE, {key: {'jobs': added} for key in chats})
				schedule = jobs.Scheduler(clock=lambda: common.datetime.datetime(2026, 10, 15, tzinfo=common.UTC))
			elif hasattr(jobs, 'SCHEDULE_FILE'): # each chat's jobs, since jobs per chat
				entries = [{'when': job.when, 'reports': job.text, 'zone': 'UTC', 'on': True}
					for job in map(jobs.parse_job, JOBS)]
				common.state.save(jobs.SCHEDULE_FILE, {key: entries for key in chats})
				schedule = jobs.Scheduler()
			else: # one schedule for all chats, the shipped one
				schedule = jobs.Scheduler(lambda: REPO / 'defaults' / 'schedule.cron', zone=common.UTC)
			with contextlib.redirect_stderr(io.StringIO()):
				schedule.load()
			self.patch(jobs, 'current', schedule)
			steps = []
			def step(label, run):
				"""Run one step and note what it posted, or what it raised."""
				posts.clear()
				random.seed(0)
				try:
					run()
					raised = None
				except Exception as e:
					raised = f'{type(e).__name__}: {e}'
				steps.append({'step': label, 'posts': list(posts), 'raised': raised})
			for service, chat, user in (('telegram', '55', '@u'), ('slack', 'C1', '<@U1>'), ('discord', '77', '<@5>')):
				for text in COMMANDS:
					step(f'{service} {text}', handing(worker.process_request, 'Message', service, chat, user, text,
						common.BOT, 'U'))
			for service, chat, message in (('telegram', '55', '9'), ('slack', 'C1', '1.5'), ('discord', '77', '333')):
				for data in BUTTONS:
					label = f'button {data}' if service == 'telegram' else f'{service} button {data}'
					step(label, pressing(service, 'cb', chat, message, data))
			# the scheduled reports go to a chat of each network as its bot: each job's chat, or before they retired,
			# the home chats (a commit from before telegram_api had webhooks, the incoming ones among them, and one
			# from before the Discord bot no discordChannelID)
			fields = {field.name for field in common.dataclasses.fields(common.config.env)}
			api = {'telegram_api': TELEGRAM_API} if 'telegram_api' in fields else {
				'webhooks': {'telegram': TELEGRAM_API}}
			homes = {'telegramChatID': '1', 'slackChannelID': 'C9'} if 'telegramChatID' in fields else {}
			discord = {'discordChannelID': '78'} if 'discordChannelID' in fields else {}
			self.env(**homes, **api, **discord)
			def scheduled(run, kwargs):
				"""A scheduled run to a chat of each network: one run to the home chats, or else one run per chat."""
				if homes:
					return lambda: run(**kwargs)
				from lib import delivery # a tree without home chats has it: an older one may not
				keys = ('telegram:1', 'slack:C9', 'discord:78')
				return lambda: [run(delivery.chat(key, scheduled=True), **kwargs) for key in keys]
			for line in SCHEDULED:
				if hasattr(jobs, 'ACTIONS'): # a job is an action and its arguments, since schedules of finbot's own
					name, *arguments = line.split()
					if name not in jobs.ACTIONS: # the reminder report, which message jobs replaced
						continue
					module = jobs.ACTIONS[name]
					label, kwargs = module.job(arguments)
				elif hasattr(jobs, 'parse_reports'):
					label, module, kwargs = jobs.parse_reports(line)[0]
				else: # a commit from before jobs per chat, whose reports were scripts
					name, _, arguments = line.partition(' ')
					label, module, kwargs = jobs.parse_command(f'{name}.py {arguments}'.strip())[0]
				run = getattr(module, 'run', None) or module.lambda_handler # lambda_handler: a commit before run()
				step(f'scheduled {line}', scheduled(run, kwargs))
			Path(output).write_text(json.dumps(steps, indent=1, sort_keys=True, default=str))

	result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(Record())
	for _, trace in result.errors + result.failures:
		print(trace, file=sys.stderr)
	return 0 if result.wasSuccessful() and Path(output).exists() else 2


def record_tree(tree, output):
	"""Record the tree at `tree` in a fresh interpreter of its own, with a data dir of its own. Exits when it fails."""
	with tempfile.TemporaryDirectory() as data:
		command = [sys.executable, str(Path(__file__).resolve()), '--record', str(output)]
		run = subprocess.run(command, cwd=tree, env={**os.environ, 'DATA_DIR': data}, stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE, text=True)
	if run.returncode:
		raise SystemExit(f'recording {tree} failed:\n{run.stderr[-3000:]}')


def compare(old, new, full=False):
	"""Print each step whose posts differ between two recordings, as a diff of its JSON. Returns how many differ."""
	def by_label(path):
		"""A recording's steps by label; a step run twice (the second .watchlist add) is told apart by a count."""
		steps, seen = {}, {}
		for step in json.loads(Path(path).read_text()):
			seen[step['step']] = seen.get(step['step'], 0) + 1
			steps[step['step'] + (f' ({seen[step["step"]]})' if seen[step['step']] > 1 else '')] = step
		return steps
	old_steps, new_steps = by_label(old), by_label(new)
	differ = 0
	for label in dict.fromkeys([*old_steps, *new_steps]):
		a, b = old_steps.get(label), new_steps.get(label)
		if a == b:
			continue
		differ += 1
		where = ' (only in the new recording)' if a is None else ' (only in the old recording)' if b is None else ''
		print(f'== {label}{where}')
		if a and b:
			lines = difflib.unified_diff(json.dumps(a, indent=1, sort_keys=True).splitlines(),
				json.dumps(b, indent=1, sort_keys=True).splitlines(), lineterm='', n=1)
			for line in list(lines)[2:]: # without the ---/+++ header
				print(line if full or len(line) <= 220 else line[:217] + '...')
	print(f'{len(new_steps)} steps, {differ} differ' if differ else f'{len(new_steps)} steps, identical')
	return differ


def against(commit, keep=None, full=False):
	"""Record `commit` (checked out in a temporary worktree) and this tree one after the other, then compare them."""
	with tempfile.TemporaryDirectory() as tmp:
		out = Path(keep) if keep else Path(tmp)
		out.mkdir(parents=True, exist_ok=True)
		tree = Path(tmp, 'tree')
		subprocess.run(['git', 'worktree', 'add', '--quiet', '--detach', str(tree), commit], cwd=REPO, check=True)
		try:
			record_tree(tree, out / 'old.json')
			record_tree(REPO, out / 'new.json')
		finally:
			subprocess.run(['git', 'worktree', 'remove', '--force', str(tree)], cwd=REPO, check=True)
		if keep:
			print(f'recordings: {out / "old.json"} ({commit}), {out / "new.json"} (this tree)')
		return compare(out / 'old.json', out / 'new.json', full)


def main(argv):
	"""Parse the arguments and run the mode they ask for; returns the exit status."""
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
		formatter_class=argparse.RawDescriptionHelpFormatter)
	mode = parser.add_mutually_exclusive_group()
	mode.add_argument('--against', metavar='COMMIT', default='HEAD', help='compare this tree with COMMIT (HEAD)')
	mode.add_argument('--record', metavar='OUT', help='record the tree in the current directory to OUT')
	mode.add_argument('--diff', nargs=2, metavar=('OLD', 'NEW'), help='compare two recordings')
	parser.add_argument('--keep', metavar='DIR', help='with --against: keep the two recordings in DIR')
	parser.add_argument('--full', action='store_true', help='show changed lines whole')
	args = parser.parse_args(argv)
	if args.record:
		return record(os.path.abspath(args.record))
	if args.diff:
		return 1 if compare(*args.diff, full=args.full) else 0
	return 1 if against(args.against, args.keep, args.full) else 0


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
