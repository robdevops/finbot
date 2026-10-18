"""A reply in place of the report asked for. A command that cannot give what was asked (a portfolio name that is none of
them, a ticker with no price history) raises Answer, and the chat gets its lines as an ordinary reply, where any other
exception becomes a one-line error report."""


class Answer(Exception):
	"""The lines to reply with instead of the report."""

	def __init__(self, *lines):
		"""lines: the reply, a line each."""
		self.lines = [str(line) for line in lines]
		super().__init__(' '.join(self.lines))


class Nothing(Answer):
	"""Nothing to show (no trades, no stock rated buy): its lines go to a chat that asked (a command, a button, Run now
	or .jobs run: delivery.asked), and a job's run on schedule posts nothing (worker.answered for a command,
	Scheduler.execute for a report)."""
