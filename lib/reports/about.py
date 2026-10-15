"""What finbot can do: the .help text, and the .jobs listing of a chat's jobs and the reports a job can run."""
from lib import buttons
from lib import config
from lib import formats
from lib import jobs

def prepare_jobs_payload(service, chat, action=None, tappable=False):
	"""`.jobs`: a chat's jobs (by its key), numbered, each with its line, whether it is on and its next run, in UTC and
	in the timezone preference; then the system jobs, under their own heading and unnumbered: they run on their
	schedule only; then the subcommands. With action ('run' or 'toggle'), the list of what a tap does, and where the
	chat takes buttons (tappable) a button per job that runs it now or switches it on or off, two to a row. Returns
	(payload, buttons)."""
	scheduler = jobs.current
	if scheduler is None:
		return ['No schedule is running'], None
	own = scheduler.chat_jobs(chat)
	running = scheduler.running(chat)
	payload = [service.bold('Jobs here:')] + [job_entry(service, scheduler, number, job, running)
		for number, job in enumerate(own, 1)] if own else ['No jobs here yet: add one with .jobs add']
	system = scheduler.system_jobs()
	payload += ['', service.bold('System:')] + [f"{job.when} {job.text}" + (' (running)' if any(
		label in running for label, _, _ in job.commands) else '') for job in system]
	if action and own:
		payload.append('\n' + ('Tap one to run it now' if action == 'run' else 'Tap one to switch it on or off')
			if tappable else f"\nSend .jobs {action} NUMBER")
	elif not action:
		payload += ['', '.jobs run [NUMBER]: run one now', '.jobs toggle [NUMBER]: switch one on or off',
			'.jobs add [CRON_TZ=ZONE] TIME REPORT: add one (.jobs add lists the reports)',
			'.jobs del NUMBER: delete one']
	markup = None
	if action and tappable and own:
		row = [buttons.job_button(number, job.text, jobs.checksum(job.key), action)
			for number, job in enumerate(own, 1)]
		markup = [row[i:i + 2] for i in range(0, len(row), 2)]
	return payload, markup

def job_entry(service, scheduler, number, job, running=()):
	"""'1. */20 * * * Mon-Fri trades: on, next Thu 14:20 UTC (Fri 01:20 AEDT)': a job in .jobs."""
	state = 'running' if any(label in running for label, _, _ in job.commands) else 'on' if job.on else 'off'
	when = scheduler.next_run(job)
	if when is None:
		return f"{number}. {job.line}: {state}"
	utc, local = when.astimezone(jobs.UTC), when.astimezone(formats.zone())
	shown = f"{utc:%a %H:%M} UTC" + ('' if local.utcoffset() == utc.utcoffset() else f" ({local:%a %H:%M %Z})")
	return f"{number}. {job.line}: {state}, next {shown}"

def job_line(number, job, outcome):
	"""'3. trades: done': a job's number in the .jobs list, its reports, and how its run went."""
	return f"{number}. {job.text}: {outcome}"

def prepare_reports(service):
	"""`.jobs add` alone: the reports a job can run, each with what it takes, and examples."""
	names = [name for name in jobs.SCRIPTS if name not in jobs.SYSTEM_SCRIPTS]
	return [service.bold('Reports a job can run:')] + [f"{name} {jobs.SCRIPTS[name].ARGUMENTS}".strip()
		for name in sorted(names)] + ['', service.bold('For example:'), '.jobs add 29 21 * * Mon-Fri price interday',
		'.jobs add 28 21 * * Sat cal earnings; price 7 (several in turn)',
		'.jobs add CRON_TZ=America/New_York 15 13 * * Mon-Fri price midsession (UTC unless it says)']

def prepare_help(service, botName, sections):
	"""The .help text: each section's command lines under its heading (worker.help_sections() has them), then the bot's
	@name as another way to start a command. botName is the bot's @name. On Discord the lines are slash commands, and
	the other ways, which are messages, work only over the gateway."""
	if service == 'discord':
		example = None if config.env.discordOutgoingWebhook else f'.price, or <{botName}> price'
	else:
		example = '<' + botName + '> trades' if service == 'slack' else botName + ' price'
	return formats.sections(*([service.bold(heading + ":")] + lines for heading, lines in sections),
		[service.bold("Alternative syntax:"), example] if example else [],
		[f"Full help on {service.link('https://github.com/robdevops/finbot', 'GitHub')}"])
