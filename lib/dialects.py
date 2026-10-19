"""How each chat network marks text up: bold, italic, struck-through, links, user text made safe, and how much a
message holds (its text, a chart's caption, its buttons). A dialect is also the network's name (TELEGRAM ==
'telegram'), so it can stand wherever the name did: reports take one as `service` and write `service.bold(text)`.
dialects.of('slack') gives the one for a name."""
import html
import re

from lib import config


class Dialect(str):
	"""A network's markup. Subclasses set the styles, link markup and limits."""
	__slots__ = ()
	styles = {} # style -> (before, after)
	text_limit = 4096 # characters in one message
	caption_limit = None # characters under a chart, as visible() counts them; None: no limit of its own
	button_rows = None # rows of buttons a message holds, five buttons to a row at most; None: more than finbot draws

	def room(self, per_row, kept=1, otherwise=None):
		"""How many buttons a screen may show in rows of `per_row`, where the network holds few rows (button_rows): all
		they hold but `kept` rows, kept for the screen's others (Back, ◀ ▶); else `otherwise`."""
		return (self.button_rows - kept) * per_row if self.button_rows else otherwise

	def bold(self, text):
		"""text in bold."""
		return self._styled('bold', text)

	def italic(self, text):
		"""text in italics."""
		return self._styled('italic', text)

	def strike(self, text):
		"""text struck through."""
		return self._styled('strike', text)

	def _styled(self, style, text):
		"""text between the markers of a style: bold, italic or strike."""
		before, after = self.styles[style]
		return before + text + after

	def link(self, url, text):
		"""text linking to url; just the text with the hyperlink setting off."""
		return self._link(url, text) if config.settings.hyperlink else text

	def escape(self, text):
		"""Text a user wrote (a name) made safe to show: Telegram's HTML and Slack's markup both take
		&amp; &lt; &gt;. It is unescaped first because it may arrive escaped already (inbound escapes Telegram names as
		they arrive): escaping twice would show &amp;amp;."""
		return html.escape(html.unescape(str(text)), quote=False)

	def visible(self, text):
		"""The length of text as the network counts it against caption_limit."""
		return len(text)


class Telegram(Dialect):
	"""Telegram's HTML parse mode."""
	__slots__ = ()
	styles = {'bold': ('<b>', '</b>'), 'italic': ('<i>', '</i>'), 'strike': ('<s>', '</s>')}
	caption_limit = 1024

	def _link(self, url, text):
		"""An HTML link."""
		return '<a href="' + url + '">' + text + '</a>'

	def visible(self, text):
		"""The length as Telegram counts it: the text the HTML shows (no tags, &amp; one character), in UTF-16 code
		units, so an emoji such as 🔼 counts 2."""
		return len(html.unescape(re.sub(r'<[^>]+>', '', text)).encode('utf-16-le')) // 2


class Slack(Dialect):
	"""Slack's mrkdwn."""
	__slots__ = ()
	styles = {'bold': ('*', '*'), 'italic': ('_', '_'), 'strike': ('~', '~')}

	def _link(self, url, text):
		"""A mrkdwn link: <url|text>."""
		return '<' + url + '|' + text + '>'


class Discord(Dialect):
	"""Discord's markdown."""
	__slots__ = ()
	styles = {'bold': ('**', '**'), 'italic': ('_', '_'), 'strike': ('~~', '~~')}
	text_limit = caption_limit = 2000 # markup included
	button_rows = 5 # an action row each

	def _link(self, url, text):
		"""A masked link: <url> stops a preview; brackets in the text and parentheses in the url would end it early."""
		return '[' + text.replace('[', '\\[').replace(']', '\\]') + '](<' + url.replace('(', '%28').replace(')',
			'%29') + '>)'

	def escape(self, text):
		"""The plain text: Discord's markdown shows entities as written."""
		return html.unescape(str(text))


TELEGRAM, SLACK, DISCORD = Telegram('telegram'), Slack('slack'), Discord('discord')
_BY_NAME = {dialect: dialect for dialect in (TELEGRAM, SLACK, DISCORD)}


def of(network):
	"""The dialect of a network by name ('telegram', 'slack' or 'discord'); a dialect is its own."""
	return _BY_NAME[network]
