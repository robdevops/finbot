"""Runs one scheduled command in its own process: `python -m lib.jobrun <script> '<json kwargs>'`.

The bot starts this for every scheduled or manual run, so a job's CPU-heavy work (charts, pandas) happens off the bot's event
loop and cannot hold up incoming webhooks. Failures are reported to the channel and give a non-zero exit status."""
import importlib, json, re, sys

from lib import webhook


def main(argv):
	if len(argv) != 2 or not re.fullmatch(r'[a-z]+', argv[0]):
		print('usage: python -m lib.jobrun <script> <json kwargs>', file=sys.stderr)
		return 2
	name = argv[0]
	module = importlib.import_module(name)
	kwargs = json.loads(argv[1])
	webhook.guarded(f'{name}.py', module.lambda_handler, **kwargs) # reports a failure, then exits 1
	return 0


if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
