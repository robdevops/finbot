"""How each chat network marks text up: bold, italic, struck-through, links, user text made safe, and message sizes. A dialect is
also the network's name (TELEGRAM == 'telegram'), so it can stand wherever the name did: reports take one as `service` and write
`service.bold(text)`. dialects.of('slack') gives the one for a name."""
import html
import re

from lib import config


class Dialect(str):
	"""A network's markup. Subclasses set the styles, link markup and limits."""
	__slots__ = ()
	styles = {} # style -> (before, after)
	text_limit = 4096 # characters in one message
	caption_limit = None # characters under a chart, as visible() counts them; None: no limit of its own

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
		"""text linking to url; just the text with the hyperlink preference off."""
		return self._link(url, text) if config.prefs.hyperlink else text

	def escape(self, text):
		"""Text a user wrote (a .plan entry, a name) made safe to show: Telegram's HTML and Slack's markup both take &amp; &lt; &gt;.
		It is unescaped first because it may arrive escaped already (Slack escapes what it sends; bot.py escapes Telegram names):
		escaping twice would show &amp;amp;."""
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
		"""The length without the HTML tags, which Telegram does not count."""
		return len(re.sub(r'<[^>]+>', '', text))


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

	def _link(self, url, text):
		"""A masked link: <url> stops a preview; brackets in the text and parentheses in the url would end it early."""
		return '[' + text.replace('[', '\\[').replace(']', '\\]') + '](<' + url.replace('(', '%28').replace(')', '%29') + '>)'

	def escape(self, text):
		"""The plain text: Discord's markdown shows entities as written."""
		return html.unescape(str(text))


TELEGRAM, SLACK, DISCORD = Telegram('telegram'), Slack('slack'), Discord('discord')
_BY_NAME = {dialect: dialect for dialect in (TELEGRAM, SLACK, DISCORD)}


def of(network):
	"""The dialect of a network by name ('telegram', 'slack' or 'discord'); a dialect is its own."""
	return _BY_NAME[network]
