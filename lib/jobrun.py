"""Runs one scheduled command in its own process: `python -m lib.jobrun lib.reports.<name> '<json kwargs>'`.

The bot starts this for every scheduled or manual run, so a job's CPU-heavy work (charts, pandas) happens off the
bot's event loop and cannot hold up incoming webhooks. Failures are reported to the channel and give the exit status
REPORTED."""
import signal
if __name__ == '__main__':
	# a reload is for the bot, but `systemctl kill -s HUP` signals every process of the unit
	signal.signal(signal.SIGHUP, signal.SIG_IGN)
	# likewise a flush (systemctl kill -s USR1); its default action would kill the job
	signal.signal(signal.SIGUSR1, signal.SIG_IGN)
import importlib, json, re, sys

from lib import delivery

# exit status of a run that failed and said so in the chat; the bot reports any other non-zero status itself
REPORTED = 3


def main(argv):
	"""Run one scheduled command: argv is the report's module and its JSON keyword arguments. Returns the exit status: 0
	when it ran, REPORTED when it failed and said so in the chat, 2 for bad arguments."""
	if len(argv) != 2 or not re.fullmatch(r'[a-z][a-z_]*(\.[a-z][a-z_]*)*', argv[0]):
		print('usage: python -m lib.jobrun <module> <json kwargs>', file=sys.stderr)
		return 2
	module = argv[0]
	def run():
		"""Import the report and run it: an import that fails is reported like any other failure."""
		importlib.import_module(module).run(**json.loads(argv[1]))
		return True
	return 0 if delivery.guarded(module.rsplit('.', 1)[-1] + '.py', run, exit=False) else REPORTED


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
