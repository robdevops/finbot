"""Where a report goes and how: Report, the destinations (the chat that asked, or whose job it is), deliver(), and the
one-line error report. A destination is a transport: a network's bot (TelegramBot, SlackBot, DiscordBot)."""
import concurrent.futures
import dataclasses
import traceback

from lib import log
from lib import config
from lib import discord_common
from lib import net
from lib import render
from lib import slack_common
from lib import telegram_common
from lib import transports


@dataclasses.dataclass
class Report:
	"""What a report says: its lines; perhaps a chart, a render.Chart spec that deliver() draws only for a destination
	that takes charts; and buttons, rows of buttons.Button (or, on Telegram, a keyboard markup of its own)."""
	lines: list
	chart: object = None
	buttons: list = None


REPLIES = {bot.name: bot for bot in (telegram_common.TelegramBot, slack_common.SlackBot, discord_common.DiscordBot)}


def reply_to(service, chat, message=None, interaction='', pressed=False):
	"""The destination of a reply into a chat: to `message`, the one being answered, if given; through `interaction`
	where the network answers one (Discord's slash command, or with pressed, its button press). None for a network that
	takes no replies."""
	kind = REPLIES.get(service)
	return kind(chat, message, interaction, pressed) if kind else None


def chat(key, scheduled=False, asked=False):
	"""The destination of a chat by its key ('telegram:-1001234', Transport.key), as its network's bot; scheduled: for a
	scheduled run, whose reports keep their record of what they told it; asked: one that someone asked for (Run now,
	.jobs run), which says when it has nothing to show."""
	network, where = transports.split_key(key)
	dest = reply_to(network, where)
	if dest is None:
		raise ValueError(f'no chat {key!r}: no such network')
	dest.scheduled, dest.asked = scheduled, asked
	return dest


class Preloader:
	"""Charts drawn ahead of presses that may ask for them (the other periods or portfolios of a chart that went out),
	preloaded to their network's preload chat, where a setting names one, so that a press shows one without an upload.
	Each is handed over (add) as it is drawn and goes at once, PRELOAD_PARALLEL uploads at a time (Transport.preload):
	it is usable as soon as it lands, not when the last is drawn. One that fails stops the rest. finish waits for
	them."""

	def __init__(self, service):
		"""A preloader for charts of a network (a dialect); it does nothing where no preload chat is named (the setting
		its bot's PRELOAD_CHAT names)."""
		setting = getattr(REPLIES.get(service), 'PRELOAD_CHAT', '')
		where = setting and getattr(config.settings, setting)
		self.chat = reply_to(service, where) if where else None
		self.pool = concurrent.futures.ThreadPoolExecutor(transports.PRELOAD_PARALLEL) if self.chat else None
		self.failed = False

	def add(self, image):
		"""Preload a drawn chart (a file object) in the background."""
		if self.pool and image is not None and not self.failed:
			self.pool.submit(self.send, image.getvalue())

	def send(self, photo):
		"""Preload one chart, unless an earlier one failed."""
		if not self.failed and not self.chat.preload(photo):
			self.failed = True

	def finish(self):
		"""Wait for the uploads started."""
		if self.pool:
			self.pool.shutdown(wait=True)


def interactive(dest):
	"""Whether a report answers a command (dest, the chat that asked), not a scheduled run (dest a job's chat): a
	scheduled run tells each chat only what it has not told it before."""
	return dest is not None and not dest.scheduled


def asked(dest):
	"""Whether someone asked for what goes to dest, and is told when there is nothing to show (answer.Nothing): a
	command (interactive) or a job run now; a run on schedule posts nothing then."""
	return dest is not None and (not dest.scheduled or dest.asked)


def target(dest):
	"""Where a report goes: the chat that asked for it, or whose job it is (dest). Raises RuntimeError without one."""
	if dest is None:
		raise RuntimeError('nowhere to post: a report goes to the chat that asked for it, or whose job it is')
	return dest


def deliver(dest, report):
	"""Post a report: its chart, drawn here only where it can go (a destination that takes charts, with the graph
	setting on), with the lines as its caption; else the lines, and the buttons under the last message unless they
	were the chart's. A chart the network refuses goes again with its heading (the first line) alone as its caption, the
	lines following as text; refused again, the lines go as text alone, without its buttons. A chart that may have
	arrived after all (a timeout) is not sent again. Returns the network's answers, one per message."""
	chart = report.chart
	if chart is None or not (dest.takes_charts and config.settings.graph and chart.rows):
		return dest.text(report.lines, report.buttons if chart is None else None)
	caption = '\n'.join(map(str, report.lines)) or chart.title
	image = render.draw(chart)
	answer = dest.chart(image, caption, report.buttons)
	if answer is transports.MAYBE_SENT:
		return []
	if answer is not None:
		return [answer]
	heading = caption.split('\n', 1)[0]
	if heading != caption: # the caption may be what was refused: too long, or markup the network cannot read
		log.warn("chart not sent, sending it again with its heading alone, and the report as text")
		answer = dest.chart(image, heading, report.buttons)
		if answer is not None:
			return ([] if answer is transports.MAYBE_SENT else [answer]) + dest.text(caption.split('\n'))
	log.warn("chart not sent, sending the report as text")
	return dest.text(caption.split('\n'))


def error_line(e, context=None, limit=200):
	"""One-line, secret-free summary of an exception (or string)."""
	if isinstance(e, BaseException):
		text = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
	else:
		text = str(e)
	text = ' '.join(net.redact(text).split())
	if len(text) > limit:
		text = text[:limit - 1] + '…'
	return f"⚠️ {context}: {text}" if context else f"⚠️ {text}"


def report_error(e, dest=None, context=None):
	"""Log a one-line error summary, with its traceback, and send the line to dest, the chat that asked or whose job it
	is (its transport); an error that belongs to no chat stays in the log. The line is escaped as the network's markup
	asks (Telegram's HTML refuses a stray < such as the one in <redacted>). Never raises: error reporting must not
	become a second failure."""
	try:
		line = error_line(e, context)
		log.error(line)
		if isinstance(e, BaseException):
			trace = ''.join(traceback.format_exception(e))
			log.error(net.redact(trace), end='') # a request's error carries its URL
		if dest is not None:
			try:
				dest.text([dest.dialect.escape(line)])
			except Exception as send_error:
				log.error("Failed to report error to", dest.name, ":", send_error)
	except Exception as reporting_error:
		log.error("Failed to report error:", reporting_error)

