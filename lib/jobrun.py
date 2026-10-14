"""Runs one scheduled command in its own process: `python -m lib.jobrun <script> '<json kwargs>'`.

The bot starts this for every scheduled or manual run, so a job's CPU-heavy work (charts, pandas) happens off the bot's event
loop and cannot hold up incoming webhooks. Failures are reported to the channel and give the exit status REPORTED."""
import signal
if __name__ == '__main__':
	signal.signal(signal.SIGHUP, signal.SIG_IGN) # a reload is for the bot, but `systemctl kill -s HUP` signals every process of the unit
	signal.signal(signal.SIGUSR1, signal.SIG_IGN) # likewise a flush (systemctl kill -s USR1); its default action would kill the job
import importlib, json, re, sys

from lib import webhook

REPORTED = 3 # exit status of a run that failed and said so in the chat; the bot reports any other non-zero status itself


def main(argv):
	if len(argv) != 2 or not re.fullmatch(r'[a-z]+', argv[0]):
		print('usage: python -m lib.jobrun <script> <json kwargs>', file=sys.stderr)
		return 2
	name = argv[0]
	def run(): # the import too: a script that cannot even be imported is reported like any other failure
		importlib.import_module(name).lambda_handler(**json.loads(argv[1]))
		return True
	return 0 if webhook.guarded(f'{name}.py', run, exit=False) else REPORTED


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
