"""What finbot can do: the .help text, and the .jobs listing of the schedule (with running a job from it)."""
from lib import buttons
from lib import formats
from lib import jobs

def prepare_jobs_payload(service, run=None, tappable=False):
	"""`.jobs`: the scheduled commands, each once and numbered, then the system jobs (HIDDEN) under their own heading,
	unnumbered: they run on their schedule only. With `run` (a number in that list, or a command's text) that command
	run now, as cron would. Returns (payload, buttons): with tappable (the chat takes buttons) a button per numbered
	command, two to a row."""
	scheduler = jobs.current
	if scheduler is None:
		return ['Scheduled jobs are off (scheduler=False)'], None
	if run:
		return [run_job_line(scheduler, run)], None
	commands, system = scheduler.commands(), scheduler.commands(hidden=True)
	if not commands and not system:
		return ['No scheduled jobs'], None
	shown = lambda label: jobs.display(label) + (' (running)' if label in scheduler.busy else '')
	payload = []
	if commands:
		payload = [service.bold('Scheduled commands:')] + [f"{number}. {shown(label)}"
			for number, (label, _, _) in enumerate(commands, 1)]
	if system:
		payload += ([''] if payload else []) + [service.bold('System:')] + [shown(label) for label, _, _ in system]
	if commands:
		payload.append("\nRun one with .jobs run NUMBER" + (' or tap it' if tappable else ''))
	markup = None
	if tappable and commands:
		row = [buttons.job_button(number, jobs.display(label), jobs.checksum(label))
			for number, (label, _, _) in enumerate(commands, 1)]
		markup = [row[i:i + 2] for i in range(0, len(row), 2)]
	return payload, markup

def run_job_line(scheduler, text):
	"""Run a scheduled command now and say how it went in one line."""
	try:
		return job_line(scheduler, *scheduler.run_now(text))
	except jobs.ScheduleError as e:
		return str(e)

def job_line(scheduler, label, outcome):
	"""'3. trades.py: done': a command's number in the .jobs list, its name, and how its run went."""
	number = [command[0] for command in scheduler.commands()].index(label) + 1
	return f"{number}. {jobs.display(label)}: {outcome}"

def prepare_help(service, botName, sections):
	"""The .help text: each section's command lines under its heading (worker.help_sections() has them), then the bot's
	@name as another way to start a command. botName is the bot's @name."""
	example = '<' + botName + '> trades' if service == 'slack' else botName + ' price'
	return formats.sections(*([service.bold(heading + ":")] + lines for heading, lines in sections),
		[service.bold("Alternative syntax:"), example],
		[f"Full help on {service.link('https://github.com/robdevops/finbot', 'GitHub')}"])
