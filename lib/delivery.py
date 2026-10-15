"""Where a report goes and how: Report, the destinations (the chat that asked, or the default chats), deliver(), and the
one-line error report. A destination is a transport (lib/transports.py)."""
import dataclasses
import html
import sys
import traceback

from lib import config
from lib import net
from lib import render
from lib import transports


@dataclasses.dataclass
class Report:
	"""What a report says: its lines; perhaps a chart, a render.Chart spec that deliver() draws only for a destination
	that takes charts; and buttons, rows of buttons.Button (or, on Telegram, a keyboard markup of its own)."""
	lines: list
	chart: object = None
	buttons: list = None


REPLIES = {'telegram': transports.TelegramBot, 'slack': transports.SlackBot} # a reply into the chat that asked


def reply_to(service, chat, message=None):
	"""The destination of a reply into a chat (to `message`, the one being answered, if given), or None for a network
	that takes none."""
	kind = REPLIES.get(service)
	return kind(chat, message) if kind else None


def default_chats():
	"""Where a scheduled report goes, in this order: Telegram's telegramChatID; Slack's slackChannelID as the bot, with
	slackBotToken (so that charts go too), else its incoming webhook; Discord's webhook. Raises RuntimeError when there
	is nowhere to post."""
	env = config.env
	chats = []
	if env.telegramChatID and 'telegram' in env.webhooks:
		chats.append(transports.TelegramBot(env.telegramChatID))
	if env.slackChannelID and env.slackBotToken:
		chats.append(transports.SlackBot(env.slackChannelID))
	elif 'slack' in env.webhooks:
		chats.append(transports.SlackWebhook(env.webhooks['slack']))
	if 'discord' in env.webhooks:
		chats.append(transports.DiscordWebhook(env.webhooks['discord']))
	if not chats:
		raise RuntimeError('nowhere to post: finbot.env sets no telegramChatID, slackChannelID, slack_webhook or'
			' discord_webhook')
	return chats


def targets(dest):
	"""Where a report goes: the chat that asked for it (dest), else the default chats."""
	return [dest] if dest else default_chats()


def deliver(dest, report):
	"""Post a report: its chart, drawn here only where it can go (a destination that takes charts, with the graph
	preference on), with the lines as its caption; else the lines, and the buttons under the last message unless they
	were the chart's. A chart the network refuses goes as text without its buttons, unless it may have arrived after all
	(a timeout). Returns the network's answers, one per message."""
	chart = report.chart
	if chart is None or not (dest.takes_charts and config.prefs.graph and chart.rows):
		return dest.text(report.lines, report.buttons if chart is None else None)
	caption = '\n'.join(map(str, report.lines)) or chart.title
	answer = dest.chart(render.draw(chart), caption, report.buttons)
	if answer is transports.MAYBE_SENT:
		return []
	if answer:
		return [answer]
	print("chart not sent, sending the report as text", file=sys.stderr)
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
	"""Send a one-line error summary to dest, the chat that asked (its transport), else to every default chat. The line
	is escaped for Telegram (sent as HTML, which refuses a stray < such as the one in <redacted>) and Slack (which asks
	for the same escapes). Never raises: error reporting must not become a second failure."""
	try:
		line = error_line(e, context)
		print(line, file=sys.stderr)
		if isinstance(e, BaseException):
			trace = ''.join(traceback.format_exception(e))
			print(net.redact(trace), end='', file=sys.stderr) # a request's error carries its URL
		for chat in targets(dest):
			try:
				chat.text([line if chat.dialect == 'discord' else html.escape(line, quote=False)])
			except Exception as send_error:
				print("Failed to report error to", chat.name, ":", send_error, file=sys.stderr)
	except Exception as reporting_error:
		print("Failed to report error:", reporting_error, file=sys.stderr)


def guarded(context, func, *args, exit=True, **kwargs):
	"""Run a scheduled entry point; on failure report one line to the default channel, then exit non-zero (exit=True,
	for the command line) or just return None (exit=False, when the bot runs it in-process). A SystemExit inside counts
	as a failure."""
	try:
		return func(*args, **kwargs)
	except (Exception, SystemExit) as e:
		report_error(e, context=context)
		if exit:
			sys.exit(1)


def cli(script, job, handler, argv=None):
	"""Command line entry point of a report script: parse its arguments with `job(argv) -> (label, kwargs)`, print the
	usage on a bad argument, else run the handler guarded."""
	try:
		label, kwargs = job(sys.argv[1:] if argv is None else argv)
	except ValueError as e:
		print("Usage:", script, e, file=sys.stderr)
		sys.exit(1)
	guarded(label, handler, **kwargs)
