"""What finbot can do: the .help text, and the .jobs listing of the schedule (with running a job from it)."""
import re
from lib import jobs
from lib import links
from lib import webhook

def prepare_jobs_payload(service, args):
	"""`.jobs` lists the scheduled commands, each once; `.jobs run <number|command>` runs one now, as cron would.
	Returns (payload, reply_markup): Telegram gets a button per command."""
	scheduler = jobs.current
	if scheduler is None:
		return ['Scheduled jobs are off (scheduler=False)'], None
	args = (args or '').strip()
	if not args:
		commands = scheduler.commands()
		if not commands:
			return ['No scheduled jobs'], None
		payload = [webhook.bold('Scheduled commands:', service)]
		for number, (label, _, _) in enumerate(commands, 1):
			payload.append(f"{number}. {jobs.display(label)}" + (' (running)' if label in scheduler.busy else ''))
		payload.append("\nRun one with .jobs run NUMBER" + (' or tap it' if service == 'telegram' else ''))
		markup = None
		if service == 'telegram':
			buttons = [{'text': f"{number}. {jobs.display(label)}"[:30], 'callback_data': f"j|{number}|{jobs.checksum(label)}"} for number, (label, _, _) in enumerate(commands, 1)]
			markup = {'inline_keyboard': [buttons[i:i + 2] for i in range(0, len(buttons), 2)]}
		return payload, markup
	m = re.fullmatch(r'run(?:\s+(.+))?', args, re.IGNORECASE)
	if not m or not m.group(1):
		return ['Usage: .jobs [run NUMBER|COMMAND]'], None
	return [run_job_line(scheduler, m.group(1))], None

def run_job_line(scheduler, text):
	"""Run a scheduled command now and say how it went in one line."""
	try:
		return job_line(scheduler, *scheduler.run_now(text))
	except jobs.ScheduleError as e:
		return str(e)

def job_line(scheduler, label, outcome):
	number = [command[0] for command in scheduler.commands()].index(label) + 1
	return f"{number}. {jobs.display(label)}: {outcome}"

def prepare_help(service, botName):
	payload = []
	payload.append(webhook.bold("Tracked securities:", service))
	payload.append(".holdings")
	payload.append(".pie PORTFOLIO [sector]")
	payload.append(".watchlist [add|del SYMBOL]")
	payload.append(".who SYMBOL")

	payload.append(webhook.bold("\nCompany info:", service))
	payload.append('.SYMBOL')
	payload.append(".dividend [period|SYMBOL]")
	payload.append(".earnings [period|SYMBOL]")
	payload.append(".marketcap [SYMBOL|bottom|top]")

	payload.append(webhook.bold("\nPrice:", service))
	payload.append(".beta")
	payload.append(".compare SYMBOL SYMBOL [...] [period|max]")
	payload.append(".history SYMBOL")
	payload.append(".performance [period] [portfolio]")
	payload.append(".price [percent|SYMBOL] [period]")
	payload.append(".session [percent|SYMBOL]")
	payload.append(".premarket [percent|SYMBOL]")

	payload.append(webhook.bold("\nRisk & Value:", service))
	payload.append(".buy")
	payload.append(".sell")
	payload.append(".pe [SYMBOL|top|bottom]")
	payload.append(".forwardpe [SYMBOL|top|bottom|negative]")
	payload.append(".peg [SYMBOL|top|bottom|negative]")
	payload.append(".shorts [percent|SYMBOL]")

	payload.append(webhook.bold("\nTrades:", service))
	payload.append(".trades [period] [portfolio]")

	payload.append(webhook.bold("\nScheduled jobs:", service))
	payload.append(".jobs [run NUMBER|COMMAND]")

	payload.append(webhook.bold("\nAlternative syntax:", service))
	if service == 'slack':
		payload.append('<' + botName + '> trades')
	else:
		payload.append(botName + ' price')
	payload.append("")
	payload.append(f"Full help on {links.link('https://github.com/robdevops/finbot', 'GitHub', service)}")
	return payload
