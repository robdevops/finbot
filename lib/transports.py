"""How a message gets to a network: Transport, the base of each network's bot (TelegramBot, SlackBot and DiscordBot,
in telegram_common, slack_common and discord_common), made for one destination (a chat). A transport knows its
dialect, what it can carry (charts, buttons, a typing notice) and the network's size limits; text() and chart() are
the same everywhere, and each network posts one message its own way (post_text, post_chart). Every bot takes buttons:
whichever way its network's updates arrive, their presses reach finbot."""
import threading
import time


MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows


class Transport:
	"""A destination. Subclasses set what it carries and post one message; the base splits and trims, and keeps the
	typing notice going while a command works."""
	name = '' # the network, in logs
	dialect = None
	takes_charts = True # a chart, with the report as its caption
	takes_buttons = True # buttons under a message
	shows_typing = True # a typing notice while a command works
	TYPING = (0.5, 7, 10) # the notice: first after 0.5 s (a quick answer gets none), then every 7 s, 10 times at most
	scheduled = False # posting a scheduled run's report (a chat's job), not a reply to a command
	_notices = None # the thread sending the notices
	_quiet = None # set to stop them

	def __init__(self, where, message=None, interaction='', pressed=False):
		"""where: the chat id; message: the id of the message being answered, if any;
		interaction: what the network answers through, where it has one (Discord's application id and token), for a
		slash command, or for a button press (pressed)."""
		self.where = where
		self.message = message
		self.interaction = interaction
		self.pressed = pressed

	def __repr__(self):
		"""<TelegramBot 55>: the kind and where, for logs and test failures."""
		return f'<{type(self).__name__} {self.where}>'

	@property
	def key(self):
		"""The chat's key, the same whichever way its network's updates arrive: 'telegram:-1001234'. A chat's jobs, its
		watchlist and what its reports have told it are kept under it."""
		return f'{self.name}:{self.where}'

	def start_typing(self):
		"""Show the typing notice while a command works, where the network has one (TYPING says when), until the first
		message goes out or the command ends (end_typing)."""
		if not self.shows_typing or self._notices:
			return
		delay, every, times = self.TYPING
		self._quiet = threading.Event()
		def notices():
			"""The notices, until quiet."""
			if self._quiet.wait(delay):
				return
			for _ in range(times):
				self.typing()
				if self._quiet.wait(every):
					return
		self._notices = threading.Thread(target=notices, daemon=True)
		self._notices.start()

	def stop_typing(self):
		"""Send no more notices, and wait for one on its way: none may arrive after the answer."""
		if self._notices:
			self._quiet.set()
			self._notices.join()

	def end_typing(self):
		"""The command is over: no more notices, and one that lasts until taken off (Slack's ⏳) taken off."""
		self.stop_typing()
		self.typing_done()

	def is_typing(self):
		"""Whether the notices are still going."""
		return bool(self._notices and self._notices.is_alive())

	def text(self, lines, buttons=None):
		"""Post lines of text: one message, or several when they are too long for one, buttons under the last; the
		typing notice stops first. Returns the network's answer for each message (None for one that failed)."""
		self.stop_typing()
		lines = [str(line) for line in lines]
		if not lines:
			return []
		limit = self.dialect.text_limit
		if len('\n'.join(lines)) <= limit:
			return [self.post_text('\n'.join(lines), buttons)]
		chunks = chunked(lines, limit)
		answers = []
		for i, chunk in enumerate(chunks):
			if i:
				time.sleep(0.5) # Telegram takes about one message a second in a chat
			answers.append(self.post_text('\n'.join(chunk), buttons if i == len(chunks) - 1 else None))
		return answers

	def chart(self, image, caption, buttons=None):
		"""Post a chart, the caption under it cut to fit, the typing notice stopped first: the network's answer,
		MAYBE_SENT, or None if it failed."""
		self.stop_typing()
		if hasattr(image, 'seek'):
			image.seek(0)
		return self.post_chart(image, fit_caption(caption, self.dialect), buttons)

	def post_text(self, text, buttons=None):
		"""Post one message. The network's answer, or None when it failed (logged)."""
		raise NotImplementedError

	def post_chart(self, image, caption, buttons=None):
		"""Post one chart with its caption (see chart())."""
		raise NotImplementedError

	def typing(self):
		"""Show the typing notice once, where the network has one."""

	def typing_done(self):
		"""Take the typing notice off, where it lasts until taken off (Slack's ⏳)."""

	def reshow(self, message, buttons):
		"""Show a chart message's period (the button marked) again as it was posted lately, where the network keeps
		that: True when it did. Here never: each period is drawn and sent anew."""
		return False


def chunked(lines, limit):
	"""The lines in messages of at most limit characters each, whole lines to a message; a line longer than limit on
	its own is cut short."""
	chunks, current, size = [], [], 0
	for line in lines:
		if len(line) > limit:
			line = line[:limit - 1] + '…'
		if current and size + 1 + len(line) > limit:
			chunks.append(current)
			current, size = [], 0
		size += len(line) + (1 if current else 0)
		current.append(line)
	if current:
		chunks.append(current)
	return chunks


def fit_caption(caption, dialect):
	"""The caption cut to the dialect's caption limit (none for Slack), as the network counts it (Telegram: the text
	its HTML shows, in UTF-16 code units): the whole lines that fit, and how many were left out."""
	limit = dialect.caption_limit
	if limit is None or dialect.visible(caption) <= limit:
		return caption
	lines = caption.split('\n')
	kept = []
	for line in lines:
		note = f"\n…and {len(lines) - len(kept) - 1} more in the chart"
		if dialect.visible('\n'.join(kept + [line])) + len(note) > limit:
			break
		kept.append(line)
	return '\n'.join(kept) + f"\n…and {len(lines) - len(kept)} more in the chart"
