"""What finbot says. A module per scheduled report: cleanup (of the cache), earnings, message (a text, posted as it is),
milestone, movers, performance, podcasts, rating, shorts, trades, and sharesight_warm and yahoo_warm (which fill the
cache), each with run(chat, **kwargs), which posts to the chat (a command's, or a job's; a system job's takes none and
posts nothing), and where a scheduled run takes arguments, job(argv), which reads them, and ARGUMENTS, what .jobs add
lists (one without takes none: jobs.job_args); the scheduler runs them in the bot's process, and `.jobs run` runs one
now. And the chat-only reports: about (.help, .jobs), history (.price, also called .compare and .history), holdings
(.holdings, .who, .treemap, .watchlist), pick (the pickers' buttons), profile (.SYMBOL) and rankings (.marketcap, .ratio
and the rest)."""


def optional_days(name, key):
	"""The job() of a report, called name, whose scheduled run may give a number of days (its run's argument `key`):
	its label is its name, with the days where given; anything else raises ValueError with what it takes."""
	def job(argv):
		"""A scheduled run's arguments: (label, run's keyword arguments); a bad one raises ValueError with the usage."""
		match argv:
			case []:
				return name, {}
			case [days] if days.isdigit():
				return f'{name} {days}', {key: int(days)}
			case _:
				raise ValueError('[DAYS]')
	return job
