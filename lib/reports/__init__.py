"""What finbot says. A module per scheduled report: cal, cleanup (of the cache), message (a text, posted as it is),
milestone, performance, podcasts, price, rating, shorts, trades, and sharesight_warm and yahoo_warm (which fill the
cache), each with job(argv), which parses a job's arguments, and run(dest=None, **kwargs), which runs it, to the chat
that asked or whose job it is (dest); the scheduler runs them in the bot's process, and `.jobs run` runs one now. And
the chat-only reports: about (.help, .jobs), history (.compare, .history its other name), holdings (.holdings, .who,
.pie, .treemap, .watchlist), profile (.SYMBOL) and rankings (.marketcap, .pe and the rest)."""


def no_arguments(name):
	"""The job() of a report, called name, that a scheduled run gives no arguments: its label is its name, and an
	argument raises ValueError."""
	def job(argv):
		"""A scheduled run's arguments: (label, run's keyword arguments), of which it takes none."""
		if argv:
			raise ValueError('no arguments')
		return name, {}
	return job
