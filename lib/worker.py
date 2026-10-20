"""Chat commands: a message is answered by the Command in COMMANDS whose name it starts with (read), or .SYMBOL. The
table also makes the .help text and the Telegram command keyboard (KEYBOARD), which is kept current in every DM."""
import dataclasses
import functools
import math
import re
import typing
from lib import log
from lib import answer
from lib import config
from lib import formats
from lib import delivery
from lib import inbound
from lib import render
from lib import buttons
from lib import charts
from lib.reports import about, earnings, holdings, movers, performance, pick, profile, rankings, shorts, trades
from lib import sharesight
from lib import telegram_common
from lib import jobs
from lib import watchlist
from lib import yahoo

@dataclasses.dataclass
class Request:
	"""A command being answered, a message's (delivery.answering) or a job's (CommandJob): the chat's transport (dest),
	which also keeps the typing notice going; who asked, by their handle, as a reply calls them (inbound.Message.user:
	none for a job); and the bot's @name."""
	dest: object
	user: str = ''
	bot_name: str = ''

	@property
	def service(self):
		"""The dialect of the chat's network."""
		return self.dest.dialect

	def reply(self, lines, chart=None, buttons=None):
		"""Answer in the chat (see delivery.deliver): the lines, perhaps a chart (drawn, or a spec drawn only where it
		can go) and buttons."""
		return delivery.deliver(self.dest, delivery.Report(lines, chart, buttons))

# a chart's kind -> the command it answers
CHART_COMMANDS = {'c': 'price', 'f': 'performance', 'l': 'movers', 'r': 'trades'}

def admin(service, ids, chat_id=None):
	"""Whether the sender of a message or a press (the ids its network gives: inbound.Message.ids) is one of the admins
	setting's: telegram:@username or the user id, slack:U0123ABCD, discord:1234... (with the <> and @ a log shows,
	in any case, or without); or, in the chat they are in (chat_id), one its network makes an administrator of it (a
	Telegram group's, a Discord server's, a Slack workspace's: Transport.administers)."""
	admins = {plain_id(who) for who in config.settings.admins}
	if any(plain_id(f'{service}:{who}') in admins for who in ids):
		return True
	return bool(chat_id) and delivery.reply_to(service, chat_id).administers(ids)

def plain_id(who):
	"""network:id without the <@ > or @ a log shows it with, in lower case: telegram:@Rob is telegram:rob."""
	return re.sub(r'[<@>]', '', who).lower()

def admin_only(command):
	"""Whether only the admins may use a command: the admin_only setting names it, by any of its names."""
	return bool({name.lstrip('./').lower() for name in config.settings.admin_only} & set(command.names))

def refused(service, ids, command, chat_id=None):
	"""Why the sender (its network's ids for it) may not use a command in a chat, or None where it may: one only the
	admins may use (admin_only), the sender not one of them (see admin). Closed by default: .jobs, and no admins
	but a chat's own."""
	if command and admin_only(command) and not admin(service, ids, chat_id):
		return f"⛔ Only finbot's admins may use .{command.names[0]}"
	return None

def refused_press(press):
	"""Why a press's sender may not use the command its button belongs to (see refused), or None."""
	return refused(press.service, press.ids, press_command(press.data), press.chat_id)

def press_command(data):
	"""The command whose button a press's data is (pressing), or None."""
	handling = pressing(buttons.parse(data))
	return next((command for command in COMMANDS if handling and handling[2] in command.names), None)

def pressing(pressed):
	"""How a press is answered, by what its data asks for (buttons.parse): (its handler, what an error report calls it,
	the name of the command whose button it is): the watchlist's, a picker's, the .jobs menu's or a chart's period
	button; None for data of none of them."""
	if isinstance(pressed, buttons.PickPress) and pressed.cmd == 'w':
		return watchlist_press, 'watchlist', 'watchlist'
	if isinstance(pressed, buttons.PickPress):
		return pick_press, 'pick', buttons.PICKERS[pressed.cmd]
	if isinstance(pressed, buttons.MenuPress):
		return menu_press, 'jobs', 'jobs'
	if isinstance(pressed, buttons.ChartPress):
		return chart_press, 'chart', CHART_COMMANDS.get(pressed.kind)
	return None

PRESSED = 60 # seconds in which the same button pressed again on the same message is taken once
FLIPPED = 2 # seconds, for a button that flips a job on or off (the same one flips it back): only a double tap
_presses = inbound.Recent() # (service, chat, message): the data of the last press taken there

def repeated(press):
	"""Whether a press repeats the last one taken on the same message, within PRESSED seconds of it: the same button
	pressed again, whose answer the message shows (or is on its way), or whose job (Run now) has run; bot.take drops
	it. Another button pressed between them, or the first press failing (forget), makes it a press of its own. The
	same button of a job's switch (the .jobs menu's Edit) is a repeat for FLIPPED seconds only: pressed later, it flips
	the job back."""
	pressed = buttons.parse(press.data)
	within = FLIPPED if isinstance(pressed, buttons.MenuPress) and pressed.screen == 'edit' else PRESSED
	return _presses.repeat((press.service, press.chat_id, press.message_id), press.data, within)

def forget(press):
	"""Forget a press that failed, so that the same button pressed again tries again (see repeated)."""
	_presses.forget((press.service, press.chat_id, press.message_id), press.data)

def menu_press(chat, press, pressed):
	"""A press in the .jobs menu (pressed, the buttons.MenuPress its data says): a screen to show; or first a job to
	switch, delete or run, as long as the list is the one the button was drawn for (its checksum), else the screen is
	drawn as the list is now, saying so; or a step of Add, the last adding the job. The pressed message then shows the
	screen; a run's outcome is a message of its own, unless it is done (what the job posts shows it)."""
	lines, markup = menu_screen(chat.dialect, chat, pressed)
	chat.edit_lines(press.message_id, lines, markup or [])

CHANGED = 'The jobs have changed: here they are now' # a press of a button drawn for another list of a chat's jobs

def menu_screen(service, chat, pressed):
	"""The screen that a press in the .jobs menu shows, once what it asks for is done (see menu_press)."""
	scheduler, key, screen, args = jobs.current, chat.key, pressed.screen, pressed.args
	if scheduler is None:
		return ['No schedule is running'], None
	if screen == 'next':
		return about.next_screen(service, key)
	if screen == 'add':
		return add_step(service, chat, args)
	page = int(args[0]) if args and args[0].isdigit() and len(args[0]) < 4 else 0
	if screen == 'edit' and len(args) == 3 and all(arg.isalnum() for arg in args):
		return edit_step(service, key, scheduler, pressed, page)
	note = None
	if screen == 'run' and len(args) == 2:
		own = scheduler.chat_jobs(key)
		if jobs.list_checksum(own) != pressed.checksum or (job := jobs.numbered(own, args[1])) is None:
			note = CHANGED
		else:
			run_now(chat, scheduler, job, args[1])
	return about.jobs_screen(service, key, screen, page, note)

def run_now(chat, scheduler, job, number):
	"""Run a chat's job now (the .jobs menu's Run, .jobs run): its outcome said in the chat, unless it is done, which
	what the job posts shows."""
	if (outcome := scheduler.run(job)) != 'done':
		delivery.deliver(chat, delivery.Report([about.job_line(chat.dialect, number, job, outcome)]))

def edit_step(service, chat, scheduler, pressed, page):
	"""A press of the .jobs editing screen, which carries the selection (a bit for each job: the jobs to disable, or to
	delete) in its data: the screen again with that selection (m), the jobs switched to it (ok: the selected off, the
	rest on), the selected jobs asked about (ask) or deleted (yes), as long as the list is the one the button was
	drawn for (its checksum), else the screen is drawn as the list is now, saying so."""
	own, what, mask = scheduler.chat_jobs(chat), pressed.args[1], pressed.args[2]
	selected = int(mask, 16) if all(c in '0123456789abcdef' for c in mask) else -1
	if jobs.list_checksum(own) != pressed.checksum or not 0 <= selected < 1 << len(own):
		return about.jobs_screen(service, chat, 'edit', page, CHANGED)
	chosen = [job for i, job in enumerate(own) if selected >> i & 1]
	if what == 'ask' and chosen:
		return about.delete_screen(service, chat, selected, page)
	if what == 'ok':
		off = on = 0
		try: # each set as stored, under the scheduler's lock
			for i, job in enumerate(own):
				if bool(selected >> i & 1) == job.on:
					scheduler.toggle(job, on=not selected >> i & 1)
					off, on = off + bool(selected >> i & 1), on + (not selected >> i & 1)
		except jobs.ScheduleError as e:
			return about.jobs_screen(service, chat, 'edit', page, service.escape(str(e)))
		said = [f"{how} {count} job{'' if count == 1 else 's'}" for count, how in ((off, 'disabled'), (on, 'enabled'))
			if count]
		return about.jobs_screen(service, chat, 'top', 0, ', '.join(said).capitalize() if said else 'Nothing changed')
	if what == 'yes':
		for job in chosen:
			scheduler.delete(job)
		s = '' if len(chosen) == 1 else 's'
		return about.jobs_screen(service, chat, 'top', 0, f"Deleted {len(chosen)} job{s}")
	return about.jobs_screen(service, chat, 'edit', page, selected=selected)

def add_step(service, chat, steps):
	"""A step of Add pressed: the next choice's screen; once every choice is made, the job added, or why it is not."""
	try:
		lines, made = about.add_screen(service, chat.key, steps)
	except ValueError: # data that is no step of Add: forged, or from an older finbot
		return about.jobs_screen(service, chat.key, 'top', 0, 'That is no step of Add')
	if lines is not None:
		return about.listed_with(service, chat.key, lines), made
	try:
		number = jobs.current.add(chat.key, *made)
	except jobs.ScheduleError as e:
		return about.add_failed(service, chat.key, steps, str(e))
	return about.added_screen(service, chat.key, number)

def pick_press(chat, press, pressed):
	"""A press in a picker (pressed, the buttons.PickPress its data says): the message shows the answer for what it
	shows now (`shown`), or for the item or OK pressed, with the screen the press asks for under it; a tick or a page
	of tickers changes only the buttons, where the network can (Transport.edit_buttons). Buttons drawn for another list
	of items start the picker again at its first answer, saying so."""
	service, cmd, group, period = chat.dialect, pressed.cmd, pressed.group, pressed.period
	shown, mask = pressed.shown, pressed.mask
	found = pick.items(cmd, chat.key)
	stale = buttons.checksum(found) != pressed.checksum
	letter, number = (pressed.act[0], int(pressed.act[1:])) if not stale else ('p', 0)
	act = buttons.ACTS[letter]
	if stale:
		shown, mask = pick.default(cmd, found)
	page = number if act.on == buttons.PAGE else 0
	if act.on == buttons.ITEM and number < len(found):
		shown, page = number + 1, number // pick.layout(service, cmd)[0]
	elif act.on == buttons.TICKED and mask:
		shown = pick.pack([i for i in range(len(found)) if mask >> i & 1])
	names = pick.shown_names(cmd, found, shown)
	note = 'The list has changed: here it is now' if stale else None
	lines, rows = pick.screen(service, cmd, found, group, period, shown, mask, act.view, page, note)
	if not names:
		return chat.edit_lines(press.message_id, lines, rows) # the picker alone: no answer yet, so text
	if act.alone and chat.edit_buttons(press.message_id, rows): # a tick, a page: the answer stays as it is
		return
	pick_answer(service, chat, press.message_id, cmd, group, period, names, rows, note)
	if cmd == 'c' and (stale or act.on == buttons.TICKED): # a new ticker or set
		prime_periods(chat, 'c', names, period)

def pick_content(service, chat, cmd, group, period, names):
	"""A picker's answer for the portfolio (treemap, holdings) or tickers (compare) `names`: (lines, chart or None)."""
	if cmd == 'h':
		try:
			return holdings.prepare_holdings_payload(names[0], service), None
		except answer.Nothing as e: # shown in place, under the picker's buttons
			return e.lines, None
	if cmd == 't':
		return holdings.prepare_treemap(names[0], holdings.grouping(group), service)
	return charts.build('c', names, service, chat.key, period=period if period != '0' else 'x')

def pick_answer(service, chat, message, cmd, group, period, names, rows, note=None):
	"""The pressed picker message turned into the answer of its command for the item (a portfolio's) or items
	(compare's tickers), the picker's button rows left under it, after a note if there is one: a chart, or text (the
	holdings)."""
	lines, chart = pick_content(service, chat, cmd, group, period, names)
	lines = ([note] if note else []) + lines
	if pick.as_photo(chat, cmd):
		chat.edit_chart(message, render.draw(chart) if chart and chart.rows else render.blank(), '\n'.join(lines),
			rows)
	else:
		chat.edit_lines(message, lines, rows)

def process_callback(press):
	"""A button pressed (an inbound.Press, which bot.take acknowledged as it arrived): the message pressed answers what
	its button asks for, in place (pressing: the watchlist's, a picker's, the .jobs menu's or a chart's period). An
	Answer (nothing to draw for that period, say) is said in the chat, as a command's is; any other failure is reported
	there, and the press forgotten, so that the same button pressed again tries again. Data of none of them is
	ignored."""
	pressed = buttons.parse(press.data)
	if (handling := pressing(pressed)) is None:
		return
	handler, context, _ = handling
	chat = delivery.answering(press)
	try:
		handler(chat, press, pressed)
	except answer.Answer as e:
		delivery.deliver(chat, delivery.Report(e.lines))
	except Exception as e:
		forget(press)
		delivery.report_error(e, chat, context=context)

def chart_press(chat, press, pressed):
	"""A chart's period button pressed (pressed, the buttons.ChartPress its data says): the chart rebuilt for that
	period, and the message edited to show it, the period marked; a text answer (the trades) its lines for it."""
	args = buttons.resolve(pressed.ref)
	markup = buttons.keyboard(pressed.kind, args, pressed.period)
	if pressed.kind in charts.TEXT:
		lines, _ = charts.build(pressed.kind, args, chat.dialect, chat.key, period=pressed.period)
		return chat.edit_lines(press.message_id, lines, markup)
	if chat.reshow(press.message_id, markup): # that period as posted lately (Slack, Telegram): nothing built
		return
	lines, chart = charts.build(pressed.kind, args, chat.dialect, chat.key, period=pressed.period)
	if chart and chart.rows and not chart.drawable: # a lone bar: the text alone
		return chat.edit_lines(press.message_id, lines, markup)
	if not (chart and chart.rows): # too few prices in that period to draw a line
		raise answer.Answer(f"Too few prices to draw {buttons.PERIODS[pressed.period][0]}")
	chat.edit_chart(press.message_id, render.draw(chart), '\n'.join(lines), markup)

def process_request(message):
	"""A chat message (an inbound.Message): the command it calls (see read) answers it, with the typing notice
	meanwhile, which the first message of the answer stops and the end of the command takes off; a message that calls
	none gets no answer. Arguments the command cannot take get its usage, and any failure a one-line reply in the
	chat."""
	request = Request(delivery.answering(message), message.user, message.bot_name)
	command, args = read(message.text, message.bot_name)
	if why := refused(message.service, message.ids, command, message.chat_id):
		log.info(log.cut(f"{message.service.capitalize()} {message.chat_id} {message.user} refused: {message.text}"))
		return request.reply([why])
	if command and jobs.current: # a chat finbot does not know yet starts with the default jobs (off in a DM)
		try:
			jobs.current.see(request.dest.key, message.dm)
		except Exception as e:
			log.warn('schedule: cannot take on', request.dest.key, delivery.error_line(e))
	if command:
		try:
			request.dest.start_typing()
			answered(request, command, args)
		except Exception as e:
			delivery.report_error(e, request.dest, context=message.text.split()[0][:30])
		finally:
			request.dest.end_typing()
	elif message.interaction: # a slash command that reads as none: its notice taken off (Discord's "thinking…")
		request.dest.end_typing()
	if message.service == 'telegram':
		try: # a DM's, after the reply; /start and /help give it again, as one a person cleared comes back no other way
			telegram_common.keep_keyboard(message.chat_id, KEYBOARD, again=bool(command) and command.handler is on_help)
		except Exception as e:
			log.warn("keyboard update failed:", e)

def answered(request, command, args):
	"""Answer a command (a message's, or a job's: CommandJob) as its handler does what it was given (args): arguments
	it cannot take (Usage, or more or fewer words than it takes: Command.fits) get its usage; an Answer (a portfolio
	that is none, a ticker with no prices) is the reply, but nothing to show (answer.Nothing) only for a command or a
	button: never in a job's run, on schedule or Run now. Any other failure raises."""
	try:
		if not command.fits(args):
			raise Usage
		command.handler(request, args)
	except Usage:
		request.reply([f"Usage: {slashed(line)}" for line in command.usage])
	except answer.Answer as e:
		if not isinstance(e, answer.Nothing) or delivery.interactive(request.dest):
			request.reply(e.lines)

@dataclasses.dataclass
class Args:
	"""What a command was given (read_args): its name as written, a percent and a period where it takes them, one of its
	keywords and one of its options, and the words left between, which say what it is about: tickers or a portfolio's
	name."""
	word: str
	text: str = '' # the arguments as written
	percent: float = None
	days: int = None
	keyword: str = None
	option: str = None
	words: list = dataclasses.field(default_factory=list)

	@property
	def rest(self):
		"""The words left between, as one string: a portfolio's name, say."""
		return ' '.join(self.words)

class Usage(Exception):
	"""Raised by a handler for arguments it cannot take: the chat gets the command's usage."""

TICKER = re.compile(r'[\w^][\w.:\-^=]*') # a word that may be a ticker: .SYMBOL's

def read(message, bot_name):
	"""(the Command a message calls, its Args, their word the name it was called by), or (None, None) for none.
	A command starts with . ! or / (a space may follow) or the bot's name, then one of the command's names as whole
	words, in any case, the longest that matches (.earnings & dividend, not .earnings): .price 7d, /price@bot 7d
	(Telegram's form in groups) and @bot price 7d are the same. The bot's name among the arguments is left out. A first
	word that is no command's name but may be a ticker calls .SYMBOL, that word its one word."""
	bot = re.escape(bot_name) if bot_name else '(?!)'
	m = re.match(rf"(?:[!./]\s?|{bot}\s+)(\S+?)(?:{bot})?(?=\s|$)", message, re.IGNORECASE)
	if not m:
		return None, None
	rest = re.sub(rf"(?<!\S){bot}(?!\S)", '', message[m.end():], flags=re.IGNORECASE)
	words = [m.group(1).lower()] + [word.lower() for word in rest.split()]
	found = [(len(name.split()), command, name) for command in COMMANDS for name in command.names
		if words[:len(name.split())] == name.split()]
	if found:
		size, command, name = max(found, key=lambda each: each[0]) # the first of the longest
		return command, read_args(command, name, re.sub(r'^\s*(?:\S+\s*){%d}' % (size - 1), '', rest))
	if TICKER.fullmatch(m.group(1)):
		return PROFILE, Args(m.group(1), m.group(1), words=[m.group(1)])
	return None, None

def read_args(command, word, text):
	"""The Args of a command called by `word`: from either end of its arguments, a percent where it takes one (5, 5% or
	2.5), a period where it takes one (7d, 3m, ytd; a bare number where it takes no percent), one of its keywords and
	one of its options, in any case; the words left between are what it is about."""
	args = Args(word, text.strip())
	def taken(word):
		"""Whether the word is an option the command takes and has not had yet, which it then has."""
		if command.percent and args.percent is None:
			try:
				args.percent = parse_percent(word)
				return True
			except ValueError:
				pass
		if command.period and args.days is None:
			try:
				args.days = formats.days_from_human_days(word)
				return True
			except ValueError:
				pass
		if args.keyword is None and word.lower() in command.keywords:
			args.keyword = command.keywords[word.lower()]
			return True
		if args.option is None and word.lower() in command.options:
			args.option = command.options[word.lower()]
			return True
		return False
	words = text.split()
	while words:
		if taken(words[0]):
			words.pop(0)
		elif taken(words[-1]):
			words.pop()
		else:
			break
	args.words = words
	return args

def parse_percent(arg):
	"""'5', '5%' or '2.5' -> the number. Raises ValueError for anything else, nan and inf too: those are tickers."""
	value = float(arg.removesuffix('%'))
	if not math.isfinite(value):
		raise ValueError(f"{arg} is not a percentage")
	return value

def ticker(args):
	"""The ticker a command is about, its first word, as Yahoo knows it (yahoo.symbol: BHP may be BHP.AX); None when it
	was given none."""
	return yahoo.symbol(args.words[0]) if args.words else None

def watchlist_press(chat, press, pressed):
	"""A press under the watchlist (pick.watchlist_screen): Edit offers its tickers; one marks or unmarks itself,
	struck through in the list; Delete deletes the marked; Cancel goes back. Buttons drawn for another watchlist start
	again, saying so."""
	found = sorted(watchlist.tickers(chat.key))[:pick.MOST_ITEMS]
	stale = buttons.checksum(found) != pressed.checksum
	act, number = buttons.ACTS[pressed.act[0]], int(pressed.act[1:])
	deleting = act.on == buttons.TICKED and not stale
	gone = [ticker for i, ticker in enumerate(found) if deleting and pressed.mask >> i & 1]
	for ticker in gone:
		watchlist.remove(chat.key, ticker)
	note = 'The list has changed: here it is now' if stale else 'Deleted: ' + ', '.join(gone) if gone else None
	editing = act.view == 'e' and not stale
	lines, rows = pick.watchlist_screen(chat.dialect, chat.key, pressed.mask if editing else 0, press.user,
		number if editing else 0, note, editing)
	chat.edit_lines(press.message_id, lines, rows)

def on_watchlist(request, args):
	""".watchlist [add|del SYMBOL]: this chat's watchlist, with buttons to remove tickers from it, or a change to it."""
	chat = request.dest.key
	if args.keyword and len(args.words) == 1: # what is removed is what is watched: Yahoo may know it no longer
		symbol = ticker(args) if args.keyword == 'add' else watchlist.watched(chat, args.words[0])
		changed = holdings.prepare_watchlist(request.service, chat, request.user, args.keyword, symbol)
		if watchlist.tickers(chat):
			lines, rows = pick.watchlist_screen(request.service, chat, 0, request.user, note=changed[0], editing=False)
			request.reply(lines, None, rows)
		else:
			request.reply(changed)
	elif args.keyword or args.words:
		raise Usage
	else:
		lines, rows = pick.watchlist_screen(request.service, chat, 0, request.user, editing=False)
		request.reply(lines, None, rows)

def on_help(request, args):
	""".help: every command (on Discord as its slash command, which works in both modes)."""
	sections = help_sections(slash=request.service == 'discord')
	request.reply(about.prepare_help(request.service, request.bot_name, sections))

def on_calendar(request, args):
	""".earnings [period|SYMBOL] (also .earningsdividend, and .earnings & dividend, once the keyboard's): the coming
	earnings and ex-dividend dates in one list by date; typed .dividend, only the ex-dividend ones."""
	event = 'ex-dividend' if args.word in DIVIDENDS else 'both'
	earnings.run(request.dest, days=args.days, specific_stock=ticker(args), event=event)

def on_performance(request, args):
	""".performance [period] [portfolio]: each portfolio's return, over a month by default (DEFAULT_PERIOD)."""
	days = buttons.PERIODS[buttons.DEFAULT_PERIOD['f']][1] if args.days is None else args.days
	if days < 1: # 0d, or ytd on 1 January
		raise answer.Answer("The period must cover a day or more, such as 7d, 3m or ytd")
	prime_periods(request.dest, *performance.run(request.dest, past_days=days, portfolio_select=args.rest or None))

# the modes of .movers session and premarket, which were commands of their own and still answer typed
SESSIONS = {'session': 'midsession', 'premarket': 'premarket', 'postmarket': 'premarket', 'permarket': 'premarket'}

def on_movers(request, args):
	""".movers [percent|top|bottom|session|premarket] [period]: the stocks followed whose price moved past a percent (a
	bare number, as on the other commands), today or over a period (a period has its unit), or the top and bottom ten:
	one change each, a bar chart with period buttons; with session or premarket, the moves mid-session or pre-market
	(and post-market) of those, or of one SYMBOL, without. One stock's price over time is .price SYMBOL."""
	if mode := SESSIONS.get(args.word) or SESSIONS.get(args.keyword):
		if args.days:
			raise Usage
		return movers.run(request.dest, mode=mode, threshold=args.percent, user=request.user,
			specific_stock=ticker(args))
	if args.words:
		raise Usage
	top = movers.TOP if args.keyword else None # top or bottom: one chart shows both ends
	if attached := movers.run(request.dest, mode='period' if args.days else 'interday',
			threshold=0 if top else args.percent, days=args.days, top=top, user=request.user):
		prime_periods(request.dest, *attached)

def on_shorts(request, args):
	""".shorts [percent|SYMBOL]: the most shorted stocks followed, or one stock's short interest."""
	shorts.run(request.dest, threshold=args.percent, specific_stock=ticker(args))

def on_trades(request, args):
	""".trades [period] [portfolio]: the buys and sells, of the past day by default."""
	days = buttons.PERIODS[buttons.DEFAULT_PERIOD['r']][1] if args.days is None else args.days
	trades.run(request.dest, days=days, user=request.user, portfolio_select=args.rest or None)

def on_holdings(request, args):
	""".holdings [PORTFOLIO]: what it holds; with no portfolio, the first one's, with buttons for them."""
	if not args.words:
		return picker(request, 'h', args)
	request.reply(holdings.prepare_holdings_payload(args.rest, request.service))

def on_marketcap(request, args):
	""".marketcap [SYMBOL|top|bottom]: stocks followed by market cap, largest (or smallest) first, or one stock's."""
	if args.words:
		request.reply([rankings.marketcap_line(request.service, ticker(args))])
	else:
		request.reply(rankings.marketcap_list(request.service, request.dest.key, bottom=args.keyword == 'bottom'))

def on_ratio(request, args):
	""".ratio [SYMBOL] [forward|current|peg] [top|bottom|negative|reverse]: the top (by default) or bottom (reverse) 15
	stocks by a ratio and its chart, the negative ones (where there can be any), or one ticker's ratio; the forward
	P/E by default, the trailing one given current, the PEG given peg. .pe and .peg are its names, .peg's the PEG."""
	kind = args.option or ('peg' if args.word == 'peg' else 'forward pe')
	if args.words:
		request.reply([rankings.ratio_line(request.service, ticker(args), kind)])
	else:
		request.reply(*rankings.ratio_list(request.service, request.dest.key, kind, args.keyword or 'top'))

def on_beta(request, args):
	""".beta: the volatile small caps among the stocks followed."""
	payload, chart = rankings.prepare_beta_payload(request.service, request.dest.key)
	request.reply(payload, chart)

def on_treemap(request, args):
	""".treemap [PORTFOLIO] [sector|industry|country|currency|market]: its holdings as tiles, grouped by industry
	unless told; with no portfolio, the first one's, with buttons for them and a menu of what to group by."""
	if not args.words:
		return picker(request, 't', args)
	payload, chart = holdings.prepare_treemap(args.rest, args.keyword or holdings.GROUPED, request.service)
	request.reply(payload, chart)

def on_rating(request, args):
	""".buy, .sell or both (.buy & sell, a keyboard button): the analysts' strongest buy or sell ratings, as asked,
	in one message."""
	actions = list(dict.fromkeys(re.findall('buy|sell', f'{args.word} {args.text}'.lower()))) # each once, as asked
	payload, chart = rankings.prepare_rating_payload(request.service, request.dest.key, actions,
		asked=delivery.interactive(request.dest))
	request.reply(payload, chart)

def on_compare(request, args):
	""".price (or .compare, .history) [SYMBOL...] [period]: their price changes on one chart, with period buttons where
	they work; one stock's alone; with no symbols, the biggest holding's, with buttons to pick others. What only the
	movers list takes (a percent, top or bottom, and no ticker), typed to .price, which it was, gets the .movers to
	type."""
	if args.word in PRICE_NAMES:
		_, listed = read('.movers ' + args.text, '')
		if not listed.words and (listed.percent is not None or listed.keyword):
			raise answer.Answer(f"The movers list is .movers now: .movers {args.text}")
	if not args.words:
		return picker(request, 'c', args)
	tickers = list(dict.fromkeys(yahoo.symbols(args.words))) # each once, in the order asked
	if not compare_picker(request, tickers, args.days):
		chart_reply(request, 'c', tickers, args.days)

def compare_picker(request, tickers, days):
	""".price of the tickers typed, with the picker's buttons under the chart (the period row and the ticker picker),
	where the tickers are among those it offers (held, else watched) and the period is one of the buttons: True when
	it did; else False, and the chart has its period buttons alone."""
	dest = request.dest
	period = buttons.period_for_days(days, 'x' if days is None else None)
	if period is None:
		return False
	try:
		found = pick.items('c', dest.key)
	except answer.Answer:
		return False
	if not set(tickers) <= set(found):
		return False
	numbers = [i for i, name in enumerate(found) if name in tickers]
	send_picker(request, 'c', found, '0', period, pick.pack(numbers), sum(1 << i for i in numbers))
	return True

def picker(request, cmd, args):
	"""A command typed with nothing to say what it is about (cmd, a key of buttons.PICKERS), or a job's run of it: its
	answer for the first portfolio, alphabetically, or the biggest holding (a ticker), with the picker's buttons under
	it, one message that a press then edits (see send_picker)."""
	dest = request.dest
	group = {name: key for key, name in holdings.GROUPS.items()}.get(args.keyword, '0')
	first = 'w' if cmd == 'c' and args.keyword != 'max' else 'x' # compare starts on 7D, unless asked for max
	period = buttons.period_for_days(args.days, first) if cmd == 'c' else '0'
	found = pick.items(cmd, dest.key)
	shown, mask = pick.default(cmd, found)
	send_picker(request, cmd, found, group, period, shown, mask)

def send_picker(request, cmd, found, group, period, shown, mask):
	"""The first message of a picker of the items `found`: the answer for what `shown` says, the buttons under it, and
	for a command asked for (not a job's run), the answer's other charts drawn in the background to fill the cache."""
	dest = request.dest
	_, rows = pick.screen(request.service, cmd, found, group, period, shown, mask, 'p')
	lines, chart = pick_content(request.service, dest, cmd, group, period, pick.shown_names(cmd, found, shown))
	if not pick.as_photo(dest, cmd):
		dest.text(lines, rows) # no chart goes (the holdings, the graph off): the answer as text
	elif chart and chart.rows:
		request.reply(lines, chart, rows)
	else: # nothing to draw (no holdings, too few prices): a photo all the same, which a press can turn into a chart
		dest.chart(render.blank(), '\n'.join(lines), rows)
	if cmd == 't' and pick.as_photo(dest, cmd) and delivery.interactive(dest): # the picker's other charts
		charts.prime_in_background(request.service, pick.treemaps(request.service, group, found, 0))
	elif cmd == 'c' and chart:
		prime_periods(dest, 'c', pick.shown_names(cmd, found, shown), period)

def chart_reply(request, kind, args, days=None):
	"""The first view of a chart with period buttons, built as a button press builds it (charts.build): its lines,
	chart and buttons where they go, the period shown marked (its kind's DEFAULT_PERIOD when days is None)."""
	lines, chart = charts.build(kind, args, request.service, request.dest.key, days=days)
	shown = buttons.period_for_days(days) if days else buttons.DEFAULT_PERIOD[kind]
	request.reply(lines, chart, buttons.keyboard(kind, args, shown) if chart else None)
	if chart:
		prime_periods(request.dest, kind, args, shown)

def prime_periods(dest, kind, args, shown):
	"""After a chart with period buttons is sent to a chat (dest; kind, args and the period `shown`: charts.build), its
	other periods are drawn in the background to fill the cache, where the chat can use them: a command asked for, or a
	picker's press, with charts."""
	if dest.takes_charts and config.settings.graph and delivery.interactive(dest):
		charts.prime_in_background(dest.dialect, charts.periods(kind, args, dest.dialect, dest.key, shown))

def on_who(request, args):
	""".who SYMBOL: the portfolios that hold it."""
	request.reply(holdings.prepare_who(request.service, re.split(r'[.:]', args.words[0].upper())[0]))

def on_jobs(request, args):
	""".jobs: this chat's jobs, with the menu's buttons; .jobs upcoming: the next runs; .jobs system: the system's;
	.jobs enable, disable, delete, run or toggle NUMBER: one switched on or off, deleted, run now, or switched the
	other way; without a number, enable, disable and delete open Edit, run a button per job to run it, toggle the list;
	.jobs add REPORT SCHEDULE, or .jobs add message SCHEDULE "TEXT": one more (alone, the reports a job can run)."""
	scheduler, chat, service = jobs.current, request.dest.key, request.service
	if scheduler is None:
		raise answer.Answer('No schedule is running')
	try:
		if args.keyword is None and not args.words:
			lines, markup = about.jobs_screen(service, chat)
			request.reply(lines, buttons=markup)
		elif args.keyword == 'upcoming' and not args.words:
			lines, markup = about.next_screen(service, chat)
			request.reply(lines, buttons=markup)
		elif args.keyword == 'system' and not args.words:
			request.reply(about.prepare_system(service))
		elif args.keyword == 'add':
			first, text = (args.text.split(None, 1) + [''])[:2]
			if first.lower() != 'add': # the job follows add
				raise Usage
			if not text.strip():
				return request.reply(about.prepare_reports(service))
			number = scheduler.add(chat, *jobs.parse_add(text, formats.zone().key))
			lines, markup = about.added_screen(service, chat, number)
			request.reply(lines, buttons=markup)
		elif args.keyword in JOB_SCREENS and not args.words:
			lines, markup = about.jobs_screen(service, chat, JOB_SCREENS[args.keyword])
			request.reply(lines, buttons=markup)
		elif args.keyword in JOB_SCREENS and len(args.words) == 1:
			number = args.words[0]
			job = scheduler.job(chat, number)
			if args.keyword == 'run':
				run_now(request.dest, scheduler, job, number)
			elif args.keyword == 'delete':
				scheduler.delete(job)
				request.reply([f"Deleted {number}. {service.escape(job.name)} · "
					f"{job.schedule.describe(formats.zone().key)}"])
			else: # enable, disable or toggle
				scheduler.toggle(job, {'enable': True, 'disable': False}.get(args.keyword))
				request.reply([about.job_entry(service, scheduler, number, scheduler.job(chat, number))])
		else:
			raise Usage
	except jobs.ScheduleError as e: # a job that cannot be, or a number that is none: said, as an answer
		raise answer.Answer(service.escape(str(e))) # escaped: it may quote what was typed

def on_profile(request, args):
	""".SYMBOL, or .stock (.profile) SYMBOL: the company's profile."""
	request.reply(profile.prepare_profile_payload(request.service, request.user, ticker(args)))

@dataclasses.dataclass(frozen=True)
class Command:
	"""A chat command: its names (typos too; a name may be several words, as 'forward pe'), the handler that answers
	it, its .help lines under its section's heading, the Telegram keyboard buttons that send it, and what its arguments
	may hold besides words (read_args): a percent, a period, its keywords and its options ({spelling: keyword}); then
	how many words it takes, and what they are."""
	names: tuple
	handler: typing.Callable
	usage: tuple = () # its lines in .help; none keeps it out of .help
	section: str = ''
	buttons: tuple = ()
	percent: bool = False
	period: bool = False
	keywords: dict = dataclasses.field(default_factory=dict)
	options: dict = dataclasses.field(default_factory=dict) # a word it may take beside a keyword (.pe top current)
	words: tuple = (0, None) # how many words it takes, at least and at most (None: any): others get its usage
	takes: str = '' # what its words are, for suggest and a job's example: 'ticker' or 'portfolio' (a name)
	job: bool = True # whether a job may run it (job_commands): not one that changes something

	def fits(self, args):
		"""Whether it takes as many words as args has (words)."""
		least, most = self.words
		return least <= len(args.words) and (most is None or len(args.words) <= most)

SECTIONS = TRACKED, COMPANY, PRICE, RISK, TRADES, JOBS = ('Tracked securities', 'Company info', 'Price', 'Risk & Value',
	'Trades', 'Scheduled jobs') # the headings of .help, in order

TOP = {'top': 'top', 'bottom': 'bottom'} # the ends of a ranked list
NEGATIVE = TOP | dict.fromkeys(('neg', 'negative', 'negatives'), 'negative') # the ratios that can be negative
ENDS = NEGATIVE | dict.fromkeys(('reverse', 'reversed'), 'bottom') # .ratio's: the lowest first, or the highest
RATIOS = {'forward': 'forward pe', 'current': 'trailing pe', 'trailing': 'trailing pe', 'peg': 'peg'} # .ratio's
DELETE = ('del', 'delete', 'rem', 'remove', 'rm') # how deleting is typed, to the watchlist and to .jobs
CHANGE = {'add': 'add'} | dict.fromkeys(DELETE, 'delete') # of the watchlist
BY = {word: name for name, words in holdings.NOUNS.items() for word in words} # .treemap's: sector, sectors, ...
# what .jobs does to a chat's jobs, and shows; next is what upcoming was called before
JOB_CHANGES = {'run': 'run', 'toggle': 'toggle', 'enable': 'enable', 'disable': 'disable', 'add': 'add',
	'system': 'system'} | dict.fromkeys(('upcoming', 'next'), 'upcoming') | dict.fromkeys(DELETE, 'delete')
JOB_SCREENS = {'enable': 'edit', 'disable': 'edit', 'delete': 'edit', 'run': 'run', 'toggle': 'top'} # each's screen
BUY_SELL = (*(a + sep + b for a, b in (('buy', 'sell'), ('sell', 'buy')) for sep in ('', '&', '/', '+')), 'buy', 'sell')
PRICE_NAMES = ('price', 'prices', 'prince', 'print', 'probe', 'piece', 'pierce', 'pence', 'prime') # .price, typos and
# all: the movers list's names until they became the line chart's (on_compare)
DIVIDENDS = ('dividends', 'dividend', 'exdividend', 'ex-dividend') # .earnings by names that ask for these dates alone
PROFILE = Command(('stock', 'profile'), on_profile, ('.SYMBOL', '.stock SYMBOL'), COMPANY, words=(1, 1),
	takes='ticker') # any first word that is no command's name but may be a ticker calls it too

COMMANDS = [ # .help lists a section's commands in this order. The odd spellings (earrings, prince, hospital...) are
	# kept on purpose.
	Command(('help', 'usage', 'start'), on_help, job=False), # /start is what Telegram sends when a chat opens
	Command(('holdings', 'holding'), on_holdings, ('.holdings [PORTFOLIO]',), TRACKED, takes='portfolio'),
	Command(('treemap',), on_treemap, ('.treemap [PORTFOLIO] [sector|industry|country|currency|market]',), TRACKED,
		('.treemap',), keywords=BY, takes='portfolio'),
	Command(('watchlist', 'wishlist'), on_watchlist, ('.watchlist [add|del SYMBOL]',), TRACKED, ('.watchlist',),
		keywords=CHANGE, words=(0, 1), takes='ticker', job=False),
	Command(('who',), on_who, ('.who SYMBOL',), TRACKED, words=(1, 1), takes='ticker'),
	Command(('earnings', 'earningsdividend', 'earning', 'earrings', 'earring', *DIVIDENDS,
		*(f'earnings {sign} {name}' for sign in ('&', 'and') for name in ('dividend', 'dividends'))), on_calendar,
		('.earnings [period|SYMBOL]',), COMPANY, ('.earnings',), period=True, words=(0, 1), takes='ticker'),
	Command(('marketcap', 'maletas', 'marketer'), on_marketcap, ('.marketcap [SYMBOL|top|bottom]',), COMPANY,
		keywords=TOP, words=(0, 1), takes='ticker'),
	Command(('beta',), on_beta, ('.beta',), PRICE, words=(0, 0)),
	Command((*PRICE_NAMES, 'compare', 'history', 'hospital', 'visual', 'hosiery', 'chart'), on_compare,
		('.price [SYMBOL ... up to 8] [period]',), PRICE, ('.price',), period=True,
		keywords={'max': 'max', 'all': 'max'}, words=(0, buttons.MAX_PICKED), takes='ticker'), # max: 10 years
	Command(('performance', 'performanc'), on_performance, ('.performance [period] [portfolio]',), PRICE,
		('.performance',), period=True, takes='portfolio'),
	Command(('movers', 'mover', 'moves', *SESSIONS), on_movers,
		('.movers [percent|top|bottom|session|premarket] [period]',), PRICE, ('.movers',), percent=True, period=True,
		keywords=TOP | {name: name for name in SESSIONS}, words=(0, 1)), # a word: session's or premarket's SYMBOL
	Command(BUY_SELL, on_rating, ('.buysell',), RISK, ('.buy & sell',)), # .buy & sell, .buy sell: both
	Command(('ratio', 'pe', 'forward pe', 'forwardpe', 'fpe', 'peg'), on_ratio,
		('.ratio [SYMBOL] [forward|current|peg] [top|bottom|negative|reverse]',), RISK, ('.ratio',), keywords=ENDS,
		options=RATIOS, words=(0, 1), takes='ticker'), # was .pe (the forward P/E) and .peg, still their names
	Command(('shorts', 'short'), on_shorts, ('.shorts [percent|SYMBOL]',), RISK, ('.shorts',), percent=True,
		words=(0, 1), takes='ticker'),
	Command(('trades', 'trade'), on_trades, ('.trades [period] [portfolio]',), TRADES, ('.trades',), period=True,
		takes='portfolio'),
	Command(('jobs', 'job', 'cron', 'crons', 'schedule'), on_jobs, ('.jobs [upcoming|system]',
		'.jobs enable|disable|delete|run [NUMBER]', '.jobs add REPORT SCHEDULE', '.jobs add message SCHEDULE "TEXT"'),
		JOBS, ('.schedule',), keywords=JOB_CHANGES, job=False),
	PROFILE,
]
KEYBOARD = tuple(text for command in COMMANDS for text in command.buttons) # Telegram's command keyboard in a DM

def help_sections(slash=False):
	"""The sections of .help: (heading, the .help lines of its commands, in table order), in SECTIONS order; with slash,
	each line as its slash command (/forwardpe for .forward pe, /stock SYMBOL for .SYMBOL)."""
	def shown(command, line):
		"""The line, or its slash command."""
		form = slash_form(command, line) if slash else None
		return f'/{form[0]} {form[1]}'.strip() if form else slashed(line)
	return [(section, list(dict.fromkeys(shown(command, line) for command in COMMANDS if command.section == section
		for line in command.usage))) for section in SECTIONS]

def slashed(line):
	"""A usage line (.price [SYMBOL]) as it is shown: with the standard slash (/price [SYMBOL]); typed with the dot, a
	command works as well."""
	return '/' + line[1:] if line.startswith('.') else line

SLASH_NAME = re.compile(r'[a-z0-9_]{1,32}') # what a slash command may be named, on every network

def slash_form(command, line):
	"""The slash command of one of a command's .help lines, (name, the arguments it shows): named by the command's name
	the line starts with where a slash command may be so named, else by the command's first name that may (.forward pe
	is /forwardpe, .SYMBOL /stock SYMBOL); None when none may."""
	valid = [name for name in command.names if SLASH_NAME.fullmatch(name)]
	if not valid:
		return None
	words = line.removeprefix('.').split()
	named = next((name for name in command.names if [w.lower() for w in words[:len(name.split())]] == name.split()),
		None)
	if named is None:
		return valid[0], ' '.join(words)
	return (named if named in valid else valid[0]), ' '.join(words[len(named.split()):])

class Slash(typing.NamedTuple):
	"""A slash command to register: its name, its description, the arguments it shows, and whether Discord asks for
	suggestions while they are typed (suggest)."""
	name: str
	description: str
	arguments: str
	completes: bool = False

def slash_commands():
	"""The slash commands to register (Slash), from the .help lines (slash_form), and /help; the arguments of a
	command's several lines joined by " | ". A command's other names (/profile, /job) are no slash commands: typed,
	they work as every name does."""
	found = {'help': (None, [])} # name -> (its command, the arguments of its lines)
	for command in COMMANDS:
		for line in command.usage:
			if form := slash_form(command, line):
				name, arguments = form
				if arguments not in found.setdefault(name, (command, []))[1]:
					found[name][1].append(arguments)
	return [Slash('help', 'every command, and what it takes', '') if name == 'help' else
		Slash(name, described(name, lines), ' | '.join(lines), completes(command))
		for name, (command, lines) in found.items()]

def described(name, lines, most=100):
	"""A slash command's description: its name, then as many of its usage lines (the arguments of each, joined by
	' | ') as fit in most characters, Discord's limit."""
	text = name
	for line in filter(None, lines):
		longer = f"{text}{' ' if text == name else ' | '}{line}"
		if len(longer) > most:
			break
		text = longer
	return text

REPORTED = (on_movers, on_performance, on_trades, on_shorts, on_calendar) # what a scheduled report runs

STORED = {'price': 'compare'} # a command whose jobs are stored under another name: .price's under compare, its
# name until it took .price over (a stored price is the movers report's old name: jobs.RENAMED)

@dataclasses.dataclass(frozen=True)
class CommandJob:
	"""A command of .help as a job's action (job_commands), standing in for a report module: ARGUMENTS is what it takes,
	from its usage; job() reads a scheduled run's words; run() answers in the job's chat as the command would."""
	command: Command
	name: str # what the job calls it, its name in .help, but buy, sell or both: on_rating reads which from the name
	ARGUMENTS: str = ''
	listed: bool = True # whether .jobs add lists it: not a command's other names, nor its typos

	@property
	def key(self):
		"""What a job of it is stored under (Job.action): its name, or the earlier one STORED keeps."""
		return STORED.get(self.name, self.name)

	@property
	def needs(self):
		"""How many words it needs (Command.words): none comes from a button."""
		return self.command.words[0]

	def job(self, argv):
		"""A scheduled run's arguments (words): (label, run's keyword arguments). Raises ValueError, with what it takes,
		for words where its usage takes none, or more or fewer words than it takes (Command.fits)."""
		args = read_args(self.command, self.name, ' '.join(argv))
		if (argv and not self.ARGUMENTS) or not self.command.fits(args):
			raise ValueError(self.ARGUMENTS or 'no arguments')
		return ' '.join([self.name.replace('&', ' & '), *argv]), {'words': list(argv)}

	def run(self, dest, *, words):
		"""Answer in the job's chat (dest) as the command would to these words, typed there (answered); any other
		failure is the job's to report."""
		answered(Request(dest), self.command, read_args(self.command, self.name, ' '.join(words)))

@functools.cache
def job_commands():
	"""The commands of .help a job may run, by each name a job may call one by: a CommandJob each. Every one but those
	that change something (job false) and those a scheduled report runs already (REPORTED): first each by the name its
	first line in .help that has one gives it (.stock's, not .SYMBOL's), with what it takes; then its other names and
	its typos, each standing for the first, but buy and sell's and peg's (.compare stands for price)."""
	found = {}
	for command in COMMANDS:
		if not (command.job and command.usage) or command.handler in REPORTED:
			continue
		for line in command.usage:
			words = line.lstrip('.').split()
			if name := next((' '.join(words[:size]).lower() for size in (2, 1) if ' '.join(words[:size]).lower() in
				command.names), None):
				first = found[name] = CommandJob(command, name, ' '.join(words[len(name.split()):]))
				break
		for name in command.names:
			found.setdefault(name, dataclasses.replace(first, listed=False, name=name if command.handler is on_rating or
				name == 'peg' else first.name)) # buy, sell and peg: the name says which
	return found

PERIOD_WORDS = ('1d', '7d', '1m', '3m', '6m', 'ytd', '1y', '5y', '10y') # suggested where a command takes a period
JOB_WORDS = ('add', 'delete', 'enable', 'disable', 'run', 'upcoming', 'system') # what /jobs suggests first
SCHEDULE_WORDS = ('daily', 'weekdays', 'weekly', 'monthly', 'quarterly', 'bi-annual', 'annual', 'hourly', 'every', 'at',
	'from', 'between', 'on') # what a schedule in English is made of, suggested after a report

def completes(command):
	"""Whether suggest has words to offer for a command's arguments: its keywords, periods, tickers, portfolios, or
	those of /jobs."""
	return bool(command.handler is on_jobs or command.keywords or command.options or command.period or command.takes)

def suggest(chat, text):
	"""What to suggest while a slash command's arguments are typed (Discord's autocomplete), from the message they make
	so far (text: /movers 5 7) in a chat (its key): up to 25 (name shown, value) pairs, each value the arguments with
	the word being typed completed. The words come from the command's entry in the table: its keywords, periods,
	portfolios and tickers (the chat's watchlist and the holdings, as cached, never a request: suggestions must come at
	once); for /jobs, its subcommands, this chat's job numbers and the reports. Never raises: the failure is logged
	instead, and nothing suggested."""
	try:
		command, _ = read(text, '')
		if command is None:
			return []
		given = (text.split(None, 1) + [''])[1]
		words = given.split()
		typing = words.pop() if words and not given[-1].isspace() else ''
		done = ' '.join(words)
		if command.handler is on_jobs:
			offered = job_words(chat, words)
		else:
			offered = argument_words(command, chat, read_args(command, '', done))
		found = [(f'{done} {shown}'.strip()[:100], f'{done} {word}'.strip()) for word, shown in offered
			if word.lower().startswith(typing.lower())]
		return [(shown, value) for shown, value in found if len(value) <= 100][:25]
	except Exception as e:
		log.warn('suggest:', text, delivery.error_line(e))
		return []

def argument_words(command, chat, given):
	"""(word, shown) pairs that a command's arguments may hold next, for suggest, after those given (Args): the
	keywords its usage shows and periods, unless it has one already; portfolios; tickers (the chat's watchlist and the
	holdings, as cached)."""
	words = [word for word in re.findall(r'[\w-]+', ' '.join(command.usage)) if word not in command.names and (
		word in command.keywords and given.keyword is None or word in command.options and given.option is None)]
	if command.period and given.days is None:
		words += PERIOD_WORDS
	if command.takes:
		names, held = sharesight.cached()
		words += names if command.takes == 'portfolio' else sorted(set(watchlist.tickers(chat)) | set(held))
	return [(word, word) for word in dict.fromkeys(words)]

def job_words(chat, words):
	"""(word, shown) pairs for /jobs, for suggest, after the words given: first its subcommands; after delete, run or
	toggle, this chat's job numbers, each shown with its name (after enable, those of the jobs off; after disable,
	those on); after add, the reports, each shown with what it takes; after a report, the words it takes, then those
	of a schedule."""
	if not words:
		return [(word, word) for word in JOB_WORDS]
	action = JOB_CHANGES.get(words[0].lower())
	if action in JOB_SCREENS and len(words) == 1:
		own = jobs.current.chat_jobs(chat) if jobs.current else []
		return [(str(number), f'{number}: {job.name}') for number, job in enumerate(own, 1)
			if {'enable': not job.on, 'disable': job.on}.get(action, True)]
	if action != 'add':
		return []
	if len(words) == 1:
		return [(name, f'{name} {jobs.takes(jobs.actions()[name])}'.strip()) for name in jobs.chat_actions()]
	module = jobs.actions().get(words[1].lower())
	if module is None or words[1].lower() not in jobs.chat_actions():
		return []
	takes = re.findall(r'[a-z][a-z-]*', jobs.takes(module)) if len(words) == 2 else []
	return [(word, word) for word in dict.fromkeys(takes + list(SCHEDULE_WORDS))]
