"""Where a report goes and how: Report, the destinations (the chat that asked, or the default chats), deliver(), and the
one-line error report. A destination is a transport: a network's bot (TelegramBot, SlackBot, DiscordBot)."""
import dataclasses
import html
import sys
import traceback

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


REPLIES = {'telegram': telegram_common.TelegramBot, 'slack': slack_common.SlackBot,
	'discord': discord_common.DiscordBot}


def reply_to(service, chat, message=None, interaction='', pressed=False):
	"""The destination of a reply into a chat: to `message`, the one being answered, if given; through `interaction`
	where the network answers one (Discord's slash command, or with pressed, its button press). None for a network that
	takes no replies."""
	kind = REPLIES.get(service)
	return kind(chat, message, interaction, pressed) if kind else None


def chat(key, scheduled=False):
	"""The destination of a chat by its key ('telegram:-1001234', Transport.key), as its network's bot; scheduled: for a
	scheduled run, whose reports keep their record of what they told it."""
	network, _, where = key.partition(':')
	dest = reply_to(network, where)
	if dest is None:
		raise ValueError(f'no chat {key!r}: no such network')
	dest.scheduled = scheduled
	return dest


def interactive(dest):
	"""Whether a report answers a command (dest, the chat that asked), not a scheduled run (dest a job's chat, or None
	for the home chats): a scheduled run tells each chat only what it has not told it before."""
	return dest is not None and not dest.scheduled


def default_chats():
	"""Where a scheduled report goes: each network's home chat (telegramChatID, slackChannelID, discordChannelID), as
	its bot. Raises RuntimeError when there is nowhere to post."""
	env = config.env
	chats = []
	for chat, token, kind in ((env.telegramChatID, env.telegramBotToken, telegram_common.TelegramBot),
			(env.slackChannelID, env.slackBotToken, slack_common.SlackBot),
			(env.discordChannelID, env.discordBotToken, discord_common.DiscordBot)):
		if chat and token:
			chats.append(kind(chat))
			chats[-1].scheduled = True
	if not chats:
		raise RuntimeError('nowhere to post: finbot.env sets no telegramChatID, slackChannelID or discordChannelID,'
			' each with its bot token')
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

