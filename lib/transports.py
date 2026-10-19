"""How a message gets to a network: Transport, the base of each network's bot (TelegramBot, SlackBot and DiscordBot,
in telegram_common, slack_common and discord_common), made for one destination (a chat). A transport knows its
dialect, what it can carry (charts, buttons, a typing notice) and the network's size limits; text(), chart() and
edit_chart() are the same everywhere, and each network posts or replaces one message its own way (post_text,
post_chart, replace_chart), raising when it fails. Every bot takes buttons: whichever way its network's updates
arrive, their presses reach finbot."""
import threading
import time

from lib import config
from lib import log
from lib import net


ADMINS_FOR = 300 # seconds a network's answer about who administers a chat counts, before it is asked again
PRELOAD_PARALLEL = 2 # uploads to a network's preload chat in flight at once: each waits on the network's answer
_administers = {} # (chat key, sender id) -> (when the network answered, whether they administer the chat)
_administers_lock = threading.Lock() # presses and messages are taken on threads of their own
MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows


class MaybeSent(Exception):
	"""Raised by the request that posts a chart when it timed out: the chart may have arrived (MAYBE_SENT)."""


def chat_key(network, where):
	"""A chat's key, its network and its id ('telegram:-1001234'), the same whichever way its network's updates arrive:
	a chat's jobs, its watchlist and what its reports have told it are kept under it."""
	return f'{network}:{where}'


def split_key(key):
	"""(network, id) of a chat's key (chat_key)."""
	network, _, where = key.partition(':')
	return network, where


class Transport:
	"""A destination. Subclasses set what it carries and post one message; the base splits and trims, and keeps the
	typing notice going while a command works."""
	name = '' # the network, in logs
	dialect = None
	takes_charts = True # a chart, with the report as its caption
	shows_typing = True # a typing notice while a command works
	TYPING = (0.5, 7, 10) # the notice: first after 0.5 s (a quick answer gets none), then every 7 s, 10 times at most
	CHUNK_GAP = 0.0 # seconds between the messages of a reply too long for one, where the network wants a gap
	PRELOAD_CHAT = '' # the setting that names the network's preload chat, where it preloads (see preload)
	scheduled = False # posting a job's report (on schedule, or Run now), not a reply to a command or a button
	preload_lock = None # paces the starts of the network's preloads: a network that preloads has its own lock
	preload_slots = None # its preloads in flight at once: a BoundedSemaphore(PRELOAD_PARALLEL) where it preloads
	preloaded_at = 0.0 # when the network's last preload began (time.monotonic)
	_notices = None # the thread sending the notices
	_quiet = None # set to stop them

	def __init_subclass__(cls, **kwargs):
		"""A network's bot that preloads (it names its PRELOAD_CHAT setting) gets its own lock and slots for it."""
		super().__init_subclass__(**kwargs)
		if 'PRELOAD_CHAT' in vars(cls):
			cls.preload_lock, cls.preload_slots = threading.Lock(), threading.BoundedSemaphore(PRELOAD_PARALLEL)

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
		"""The chat's key (chat_key): 'telegram:-1001234'."""
		return chat_key(self.name, self.where)

	@property
	def dm(self):
		"""Whether the chat is a direct message with the bot, as its id tells; None where the network's ids do not
		say (Discord's)."""
		return None

	def administers(self, ids):
		"""Whether the network makes any of these ids (inbound.Message.ids) an administrator of this chat: asked of the
		network (is_administrator) once in ADMINS_FOR seconds, and once more at once where the connection fails
		(net.twice). A question that fails (logged) is never kept as an answer: the network's last answer stands, else
		no, and the next message asks again."""
		for who in ids:
			with _administers_lock:
				answered, answer = _administers.get((self.key, who), (0, False))
			if time.time() - answered >= ADMINS_FOR:
				try:
					answer = bool(net.twice(lambda: self.is_administrator(who)))
					with _administers_lock:
						_administers[self.key, who] = (time.time(), answer)
				except Exception as e:
					log.warn(f"{self.name.capitalize()} cannot tell whether {who} administers {self.where}:", e)
			if answer:
				return True
		return False

	def is_administrator(self, who):
		"""Whether the network says this sender id administers the chat (asked of the network; raises on a failure).
		No chat has administrators unless the network's bot says so."""
		return False

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
		"""Post lines of text: one message, or several when they are too long for one (CHUNK_GAP apart), buttons under
		the last; the typing notice stops first. Returns the network's answer for each message (see sent)."""
		self.stop_typing()
		chunks = chunked([str(line) for line in lines], self.dialect.text_limit)
		answers = []
		for i, chunk in enumerate(chunks):
			if i:
				time.sleep(self.CHUNK_GAP)
			last = i == len(chunks) - 1
			answers.append(self.sent('message', lambda: self.post_text('\n'.join(chunk), buttons if last else None)))
		return answers

	def chart(self, image, caption, buttons=None):
		"""Post a chart (a file object), the caption under it cut to fit, the typing notice stopped first: the network's
		answer (see sent)."""
		self.stop_typing()
		caption = fit_caption(caption, self.dialect)
		return self.sent('chart', lambda: self.post_chart(image.getvalue(), caption, buttons))

	def sent(self, what, post):
		"""The answer of post(), which posts one message (what: 'message' or 'chart', for the log): the network's
		message; MAYBE_SENT when the request that posts a chart timed out (MaybeSent: it may have arrived); None when it
		failed, which is logged: an error for a message, which is lost, a warning for a chart, whose report goes as text
		instead (delivery.deliver). A request the server reset (a stale connection, which net.fresh avoids) is sent
		again once, whole: at worst a message or chart that did arrive comes twice."""
		network = self.name.capitalize()
		try:
			try:
				answer = post()
			except Exception as e:
				if not net.was_reset(e):
					raise
				log.warn(f"{network} {what} to {self.where} was reset, sending it again:", net.redact(e))
				answer = post()
		except MaybeSent as e:
			log.warn(f"{network} {what} to {self.where} timed out, it may still arrive:", net.redact(e))
			return MAYBE_SENT
		except Exception as e:
			(log.error if what == 'message' else log.warn)(f"{network} {what} to {self.where} failed:", net.redact(e))
			return None
		log.info(f"OK {self.name} {what} to {self.where}")
		return answer

	def post_text(self, text, buttons=None):
		"""Post one message: the network's answer. Raises when it fails (see sent)."""
		raise NotImplementedError

	def post_chart(self, photo, caption, buttons=None):
		"""Post one chart (its PNG bytes) with its caption: the network's answer. Raises when it fails, MaybeSent when
		the request that posts it timed out (see sent)."""
		raise NotImplementedError

	def typing(self):
		"""Show the typing notice once, where the network has one."""

	def typing_done(self):
		"""Take the typing notice off, where it lasts until taken off (Slack's ⏳)."""

	def view(self, buttons):
		"""What a chart message shows, for reshow: its chat and the period its buttons mark (a movers list is of the
		stocks its chat follows); None when no period button is marked."""
		period = marked(buttons)
		return f'{self.where} {period}' if period and period.startswith('c|') else None

	def reshow(self, message, buttons):
		"""Show a chart message's period (the button marked) again as it was posted lately, where the network keeps
		that: True when it did. Here never: each period is drawn and sent anew."""
		return False

	def preload(self, photo):
		"""Upload a chart (its PNG bytes) to this chat, the network's preload chat, ahead of a press that may ask for
		it, where the network can show it again without an upload and has it not (wants, send_ahead), in its turn
		(paced). False when it failed (logged): the caller stops preloading."""
		if self.preload_lock is None or not self.wants(photo):
			return True
		return self.paced(lambda: self.send_ahead(photo) if self.wants(photo) else None) # a press may have sent it

	def paced(self, send):
		"""Run send(), an upload ahead of a press, in its turn: in one of the network's preload_slots, starting
		preload_gap seconds (a setting) after the last one began (the gap is from start to start, so uploads in
		different slots overlap). False when it failed (logged; a rate limit is waited out once by each call:
		net.patiently)."""
		with self.preload_slots:
			with self.preload_lock:
				time.sleep(max(0.0, type(self).preloaded_at + config.settings.preload_gap - time.monotonic()))
				type(self).preloaded_at = time.monotonic()
			try:
				send()
			except Exception as e:
				log.warn(f"{self.name.capitalize()} preload to {self.where} failed:", net.redact(e))
				return False
		return True

	def wants(self, photo):
		"""Whether preloading a chart (its PNG bytes) would spare a press its upload. Here never."""
		return False

	def send_ahead(self, photo):
		"""Upload a chart (its PNG bytes) to this chat ahead of a press (see preload)."""
		raise NotImplementedError

	def edit_buttons(self, message, buttons):
		"""Change only the buttons under a message, its text or chart left as it is, where the network can: True when
		they show now. Here never: the message is edited whole."""
		return False

	def edit_text(self, message, text, buttons=None):
		"""Edit a message's text, and its buttons unless buttons is None ([] removes them); a failure is only logged.
		The text must fit one message: edit_lines splits."""
		raise NotImplementedError

	def edit_chart(self, message, image, caption, buttons=None):
		"""Replace a chart message's image (a file object), its caption, cut to fit, and its buttons, in place
		(replace_chart). Raises RuntimeError when the network refuses."""
		self.replace_chart(message, image.getvalue(), fit_caption(caption, self.dialect), buttons)

	def replace_chart(self, message, photo, caption, buttons):
		"""Replace a chart message's image (its PNG bytes), caption and buttons (see edit_chart)."""
		raise NotImplementedError

	def edit_lines(self, message, lines, buttons=None):
		"""Edit a message to show lines, split as text() splits them: what fits one message goes in the message edited,
		the rest in messages of their own after it, the buttons under the last."""
		parts = chunked([str(line) for line in lines], self.dialect.text_limit) or [[]]
		self.edit_text(message, '\n'.join(parts[0]), buttons if len(parts) == 1 else [])
		for i, part in enumerate(parts[1:], 1):
			self.text(part, buttons if i == len(parts) - 1 else None)


def marked(buttons):
	"""The data of the button marked as shown now, which names a chart message's period (None when none is)."""
	return next((button.data for row in buttons or [] for button in row if button.active), None)


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
