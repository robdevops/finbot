"""Chat commands: a message is answered by the Command in COMMANDS whose name it starts with (read), or .SYMBOL. The
table also makes the .help text and the Telegram command keyboard, which is kept current in every DM."""
import dataclasses
import functools
import hashlib
import json
import math
import re
import threading
import typing
from lib import log
from lib import answer
from lib import config
from lib import dialects
from lib import state
from lib import formats
from lib import delivery
from lib import render
from lib import buttons
from lib import charts
from lib import transports
from lib.reports import about, cal, holdings, performance, pick, price, profile, rankings, shorts, trades
from lib import sharesight
from lib import telegram_common
from lib import jobs
from lib import watchlist
from lib import yahoo

@dataclasses.dataclass
class Request:
	"""A message being answered: where it came from (service is its dialect) and who sent it; or a job running a
	command (CommandJob), its chat's transport given as dest."""
	service: str
	chat_id: str
	user: str # the sender's handle: whose watchlist add or plan it is
	user_name: str # what to call them
	bot_name: str
	message_id: str = None # the message being answered
	interaction: str = '' # what the network answers through, where it has one (Discord's slash command)
	dest: object = None # the chat's transport, where it is given

	def __post_init__(self):
		"""The chat's transport, which also keeps the typing notice going, unless one is given."""
		if self.dest is None:
			self.dest = delivery.reply_to(self.service, self.chat_id, self.message_id, self.interaction)

	def reply(self, lines, chart=None, buttons=None):
		"""Answer in the chat (see delivery.deliver): the lines, perhaps a chart (drawn, or a spec drawn only where it
		can go) and buttons."""
		return delivery.deliver(self.dest, delivery.Report(lines, chart, buttons))

def process_job_callback(press, pressed):
	"""An older job button (an inbound.Press; pressed, what its data says): run the job now and say how it went, or
	switch it on or off and redraw the list in place, as the menu's screen that does the same. A button from an older
	list does neither: the screen is drawn as the list is now."""
	service = dialects.of(press.service)
	chat = delivery.reply_to(service, press.chat_id, interaction=press.interaction, pressed=True)
	def redraw():
		"""Put the menu's screen that does the same, as the list is now, in place of the pressed one."""
		lines, markup = about.jobs_screen(service, chat.key, 'top' if pressed.action == 'toggle' else 'run')
		chat.edit_text(press.message_id, '\n'.join(lines), markup or [])
	try:
		if jobs.current is None:
			raise jobs.ScheduleError('no schedule is running')
		job = jobs.current.pick(chat.key, pressed.number, pressed.checksum) # only this chat's job, as listed
	except jobs.ScheduleError:
		return redraw()
	try:
		if pressed.action == 'toggle':
			jobs.current.toggle(job)
			redraw()
		else:
			delivery.deliver(chat, delivery.Report([about.job_line(service, pressed.number, job,
				jobs.current.run(job))]))
	except Exception as e:
		delivery.report_error(e, chat, context='jobs')

def process_menu_callback(press, pressed):
	"""A press in the .jobs menu (an inbound.Press; pressed, the buttons.MenuPress its data says): a screen to show; or
	first a job to switch, delete or run, as long as the list is the one the button was drawn for (its checksum), else
	the screen is drawn as the list is now, saying so; or a step of Add, the last adding the job. The pressed message
	then shows the screen; a run's outcome is a message of its own."""
	service = dialects.of(press.service)
	chat = delivery.reply_to(service, press.chat_id, interaction=press.interaction, pressed=True)
	try:
		lines, markup = menu_screen(service, chat, pressed)
		chat.edit_text(press.message_id, '\n'.join(lines), markup or [])
	except Exception as e:
		delivery.report_error(e, chat, context='jobs')

def menu_screen(service, chat, pressed):
	"""The screen that a press in the .jobs menu shows, once what it asks for is done (see process_menu_callback)."""
	scheduler, key, screen, args = jobs.current, chat.key, pressed.screen, pressed.args
	if scheduler is None:
		return ['No schedule is running'], None
	if screen == 'next':
		return about.next_screen(service, key)
	if screen == 'add':
		return add_step(service, chat, args)
	page = int(args[0]) if args and args[0].isdigit() and len(args[0]) < 4 else 0
	note = None
	if len(args) == 2 and screen in ('on', 'off', 'del', 'run'):
		own, number = scheduler.chat_jobs(key), args[1]
		every = number == 'all' and screen != 'run' or number == 'allyes' and screen == 'del' # every job at once
		if not (jobs.list_checksum(own) == pressed.checksum and (every or number.isdigit() and
				1 <= int(number) <= len(own))):
			note = 'The jobs have changed: here they are now'
		elif number == 'all' and screen == 'del': # Delete all asks first
			return about.delete_all_screen(service, key, page)
		elif every and screen == 'del':
			scheduler.delete_all(key)
			return about.jobs_screen(service, key, 'top', 0, 'Every job here is deleted')
		elif every:
			scheduler.switch_all(key, screen == 'on')
			note = f'Every job is {screen} now'
		else:
			job = own[int(number) - 1]
			try:
				if screen in ('on', 'off'):
					scheduler.switch(job, screen == 'on')
					note = f"{'Enabled' if screen == 'on' else 'Disabled'} {number}. {service.escape(job.name)}"
				elif screen == 'del':
					scheduler.delete(job)
					note = f'Deleted {number}. {service.escape(job.name)}'
				else:
					delivery.deliver(chat, delivery.Report([about.job_line(service, number, job, scheduler.run(job))]))
			except jobs.ScheduleError as e:
				note = service.escape(str(e))
	return about.jobs_screen(service, key, screen, page, note)

def add_step(service, chat, steps):
	"""A step of Add pressed: the next choice's screen; once every choice is made, the job added, or why it is not."""
	try:
		lines, made = about.add_screen(service, chat.key, steps)
	except ValueError: # data that is no step of Add: forged, or from an older finbot
		return about.jobs_screen(service, chat.key, 'top', 0, 'That is no step of Add')
	if lines is not None:
		return lines, made
	try:
		number = jobs.current.add(chat.key, *made)
	except jobs.ScheduleError as e:
		return about.add_failed(service, chat.key, steps, str(e))
	return about.added_screen(service, chat.key, number)

def process_pick_callback(press, pressed):
	"""A press in a picker (an inbound.Press; pressed, the buttons.PickPress its data says): the message shows the
	answer for what it shows now (`shown`), or for the item or Compare pressed, with the screen the press asks for
	under it. Buttons drawn for another list of items start the picker again at its first answer, saying so."""
	service = dialects.of(press.service)
	chat = delivery.reply_to(service, press.chat_id, interaction=press.interaction, pressed=True)
	cmd, group, period, shown, mask = pressed.cmd, pressed.group, pressed.period, pressed.shown, pressed.mask
	try:
		found = pick.items(cmd, chat.key)
		stale = buttons.checksum(found) != pressed.checksum
		kind, number = (pressed.act[0], int(pressed.act[1:])) if not stale else ('p', 0)
		if stale:
			shown, mask = pick.default(cmd, found)
		per_page = pick.layout(service, cmd)[0]
		view = 'm' if kind in 'mf' else 'p' # picking a ticker, or Compare, goes back to the top
		page = number if kind in 'pmfg' else number // per_page if kind == 'r' else 0
		note = 'The list has changed: here it is now' if stale else buttons.TOO_MANY if kind == 'f' else None
		if kind == 'r' and number < len(found):
			shown = number + 1
		elif kind in 'gh' and bin(mask).count('1') >= 2:
			shown = pick.pack([i for i in range(len(found)) if mask >> i & 1])
		names = pick.shown_names(cmd, found, shown)
		lines, rows = pick.screen(service, cmd, found, group, period, shown, mask, view, page, note)
		if names:
			pick_answer(service, chat, press.message_id, cmd, group, period, names, rows, note)
			if cmd in 'yc' and (stale or kind in 'rgh'): # a new ticker or set
				prime_periods(chat, 'c' if cmd == 'c' else 'h', names, period)
			return
		chat.edit_text(press.message_id, '\n'.join(lines), rows) # the picker alone: no answer yet, so text
	except answer.Answer as e:
		delivery.deliver(chat, delivery.Report(e.lines))
	except Exception as e:
		delivery.report_error(e, chat, context='pick')

def pick_content(service, chat, cmd, group, period, names):
	"""A picker's answer for the portfolio (pie, treemap) or tickers (history, compare) `names`: (caption, chart or
	None)."""
	if cmd in 'pt':
		prepare = holdings.prepare_pie if cmd == 'p' else holdings.prepare_treemap
		lines, chart = prepare(names[0], 'sector' if group == 's' else 'industry', service)
		return '\n'.join(lines), chart
	return charts.build('c' if cmd == 'c' else 'h', names, service, chat.key, period=period if period != '0' else 'x')

def pick_answer(service, chat, message, cmd, group, period, names, rows, note=None):
	"""The pressed picker message turned into the answer of its command for the item (history, a portfolio's) or items
	(compare), the picker's button rows left under it, after a note if there is one: a chart, or text (the holdings)."""
	if cmd == 'h':
		lines = holdings.prepare_holdings_payload(names[0], service) or [f"{names[0]} holds nothing"]
		parts = transports.chunked(([note] if note else []) + lines, chat.dialect.text_limit)
		chat.edit_text(message, '\n'.join(parts[0]), rows if len(parts) == 1 else [])
		for i, part in enumerate(parts[1:], 1):
			chat.text(part, rows if i == len(parts) - 1 else None)
		return
	caption, chart = pick_content(service, chat, cmd, group, period, names)
	caption = f"{note}\n{caption}" if note else caption
	if pick.as_photo(chat, cmd):
		chat.edit_chart(message, render.draw(chart) if chart and chart.rows else render.blank(), caption, rows)
	else:
		chat.edit_text(message, caption, rows)

def process_callback(press):
	"""A button pressed (an inbound.Press, which bot.take acknowledged as it arrived): the .jobs menu's, an older job
	button (run it, or switch it), or a chart's, whose message is rebuilt for the chosen period and edited in place.
	Data of none of them is ignored."""
	pressed = buttons.parse(press.data)
	if isinstance(pressed, buttons.PickPress):
		return process_pick_callback(press, pressed)
	if isinstance(pressed, buttons.MenuPress):
		return process_menu_callback(press, pressed)
	if isinstance(pressed, buttons.JobPress):
		return process_job_callback(press, pressed)
	if not pressed:
		return
	service = dialects.of(press.service)
	chat = delivery.reply_to(service, press.chat_id, interaction=press.interaction, pressed=True)
	try:
		args = buttons.resolve(pressed.ref)
		markup = buttons.keyboard(pressed.kind, args, pressed.period)
		if chat.reshow(press.message_id, markup): # that period as posted lately, where the network keeps it (Slack)
			return
		caption, chart = charts.build(pressed.kind, args, service, chat.key, period=pressed.period)
		if not (chart and chart.rows): # too few prices in that period to draw a line
			raise answer.Answer(f"Too few prices to draw {buttons.PERIODS[pressed.period][0]}")
		chat.edit_chart(press.message_id, render.draw(chart), caption, markup)
	except answer.Answer as e: # nothing to draw for that period: said in the chat, as a command would
		delivery.deliver(chat, delivery.Report(e.lines))
	except Exception as e:
		delivery.report_error(e, chat, context='chart')

def process_request(message):
	"""A chat message (an inbound.Message): the command it calls (see read) answers it, with the typing notice
	meanwhile, which the first message of the answer stops and the end of the command takes off; a message that calls
	none gets no answer. Arguments the command cannot take get its usage, and any failure a one-line reply in the
	chat."""
	request = Request(dialects.of(message.service), message.chat_id, message.user, message.user_name, message.bot_name,
		message.message_id, message.interaction)
	command, args = read(message.text, message.bot_name)
	if command and jobs.current: # a chat finbot does not know yet starts with the default jobs (off in a DM)
		try:
			jobs.current.see(request.dest.key, message.dm)
		except Exception as e:
			log.warn('schedule: cannot take on', request.dest.key, delivery.error_line(e))
	if command:
		try:
			request.dest.start_typing()
			command.handler(request, args)
		except Usage as e:
			request.reply([f"Usage: {line}" for line in command.usage] + list(e.lines))
		except answer.Answer as e: # a portfolio the user got wrong, a ticker with no prices: an answer, not an error
			request.reply(e.lines)
		except Exception as e:
			delivery.report_error(e, request.dest, context=message.text.split()[0][:30])
		finally:
			request.dest.end_typing()
	elif message.interaction: # a slash command that reads as none: its notice taken off (Discord's "thinking…")
		request.dest.end_typing()
	if message.service == 'telegram':
		try:
			ensure_keyboard(message.chat_id) # keep DM keyboards current after the reply
		except Exception as e:
			log.warn("keyboard update failed:", e)

@dataclasses.dataclass
class Args:
	"""What a command was given (read_args): its name as written, a percent and a period where it takes them, one of its
	keywords, and the words left between, which say what it is about: tickers, a portfolio's name, a plan."""
	word: str
	text: str = '' # the arguments as written
	percent: float = None
	days: int = None
	keyword: str = None
	words: list = dataclasses.field(default_factory=list)

	@property
	def rest(self):
		"""The words left between, as one string: a portfolio's name, say."""
		return ' '.join(self.words)

class Usage(Exception):
	"""Raised by a handler for arguments it cannot take: the chat gets the command's usage, then these lines."""
	def __init__(self, *lines):
		"""lines: more to say after the usage, such as the portfolios there are."""
		super().__init__('usage')
		self.lines = lines

TICKER = re.compile(r'[\w^][\w.:\-^=]*') # a word that may be a ticker: .SYMBOL's

def read(message, bot_name):
	"""(the Command a message calls, its Args), or (None, None) when it calls none. A command starts with . ! or / (a
	space may follow) or the bot's name, then one of the command's names as whole words, in any case: .price 7d,
	/price@bot 7d (Telegram's form in groups) and @bot price 7d are the same. The bot's name among the arguments is left
	out. A first word that is no command's name but may be a ticker calls .SYMBOL."""
	bot = re.escape(bot_name) if bot_name else '(?!)'
	m = re.match(rf"(?:[!./]\s?|{bot}\s+)(\S+?)(?:{bot})?(?=\s|$)", message, re.IGNORECASE)
	if not m:
		return None, None
	rest = re.sub(rf"(?<!\S){bot}(?!\S)", '', message[m.end():], flags=re.IGNORECASE)
	words = [m.group(1).lower()] + rest.split()
	for command in COMMANDS:
		for name in command.names:
			parts = name.split()
			if [word.lower() for word in words[:len(parts)]] == parts:
				return command, read_args(command, words[0], re.sub(r'^\s*(?:\S+\s*){%d}' % (len(parts) - 1), '', rest))
	if TICKER.fullmatch(m.group(1)):
		return PROFILE, Args(m.group(1))
	return None, None

def read_args(command, word, text):
	"""The Args of a command called by `word`: from either end of its arguments, a percent where it takes one (5, 5% or
	2.5), a period where it takes one (7d, 3m, ytd; a bare number where it takes no percent) and one of its keywords, in
	any case; the words left between are what it is about."""
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

def portfolios():
	"""'Portfolios: A, B': the names a portfolio command takes."""
	return 'Portfolios: ' + ', '.join(portfolio.name for portfolio in sharesight.portfolios())

def on_watchlist(request, args):
	""".watchlist [add|del SYMBOL]: this chat's watchlist, or a change to it."""
	chat = request.dest.key
	if args.keyword and len(args.words) == 1: # what is removed is what is watched: Yahoo may know it no longer
		symbol = ticker(args) if args.keyword == 'add' else watchlist.watched(chat, args.words[0])
		request.reply(holdings.prepare_watchlist(request.service, chat, request.user, args.keyword, symbol))
	elif args.keyword or args.words:
		raise Usage
	else:
		request.reply(holdings.prepare_watchlist(request.service, chat, request.user))

def on_help(request, args):
	""".help: every command (on Discord as its slash command, which works in both modes); in a Telegram DM the command
	keyboard too."""
	markup = None
	if request.service == 'telegram' and int(request.chat_id) > 0: # positive chat ids are DMs; groups are negative
		markup = command_keyboard()
	sections = help_sections(slash=request.service == 'discord')
	request.reply(about.prepare_help(request.service, request.bot_name, sections), buttons=markup)
	if markup:
		mark_keyboard(request.chat_id) # this chat now has the current keyboard

def on_calendar(request, args):
	""".earnings or .dividend [period|SYMBOL]: the coming earnings or ex-dividend dates."""
	event = 'ex-dividend' if 'div' in args.word else 'earnings'
	cal.run(request.dest, days=args.days, specific_stock=ticker(args), event=event)

def on_performance(request, args):
	""".performance [period] [portfolio]: each portfolio's return, over a month by default."""
	days = buttons.PERIODS['m'][1] if args.days is None else args.days # the default view is the 1M button
	if days < 1: # 0d, or ytd on 1 January
		raise answer.Answer("The period must cover a day or more, such as 7d, 3m or ytd")
	performance.run(request.dest, past_days=days, user=request.user, portfolio_select=args.rest or None)
	prime_periods(request.dest, 'f', [args.rest or ''], buttons.period_for_days(days))

def on_session(request, args):
	""".session or .premarket (.postmarket) [percent|SYMBOL]: the moves mid-session, or pre-market (and post-market)."""
	mode = 'midsession' if args.word == 'session' else 'premarket'
	price.run(request.dest, mode=mode, threshold=args.percent, user=request.user, specific_stock=ticker(args))

def on_price(request, args):
	""".price [percent|SYMBOL|top|bottom] [period]: a bare number is a percent, as on the other commands; a period has
	its unit. One stock over a period is its chart, as its period buttons draw it, from the history that the lists
	take their figures from too."""
	symbol = None if args.keyword else ticker(args)
	if symbol and args.days:
		return chart_reply(request, 'p', [symbol], args.days)
	top = 10 if args.keyword else None # top or bottom: one chart shows both ends
	price.run(request.dest, mode='period' if args.days else 'interday', threshold=0 if top else args.percent,
		days=args.days, top=top, user=request.user, specific_stock=symbol)
	if symbol is None: # the list's chart and period buttons; one stock's line has neither
		prime_periods(request.dest, 'l', *price.list_buttons(0 if top else args.percent, top, args.days))

def on_shorts(request, args):
	""".shorts [percent|SYMBOL]: the most shorted stocks followed, or one stock's short interest."""
	shorts.run(request.dest, threshold=args.percent, specific_stock=ticker(args))

def on_trades(request, args):
	""".trades [period] [portfolio]: the buys and sells, of the past day by default."""
	trades.run(request.dest, days=1 if args.days is None else args.days, user=request.user,
		portfolio_select=args.rest or None)

def on_holdings(request, args):
	""".holdings PORTFOLIO: what it holds; with no portfolio, buttons for them."""
	if not args.words:
		return picker(request, 'h', args)
	request.reply(holdings.prepare_holdings_payload(args.rest, request.service))

def on_marketcap(request, args):
	""".marketcap [SYMBOL|top|bottom]: stocks followed by market cap, largest (or smallest) first, or one stock's."""
	if args.words:
		request.reply([rankings.marketcap_line(request.service, ticker(args))])
	else:
		request.reply(rankings.marketcap_list(request.service, request.dest.key, bottom=args.keyword == 'bottom',
			length=15))

def on_ratio(kind):
	"""The handler of .pe, .forward pe or .peg (kind: pe, forward pe or peg): the top (by default) or bottom 15 by the
	ratio and its chart, the negative ones (where there can be any), or one ticker's ratio."""
	def handler(request, args):
		""".pe, .forward pe or .peg [SYMBOL|top|bottom|negative]."""
		if args.words:
			request.reply([rankings.ratio_line(request.service, ticker(args), kind)])
		else:
			mode = args.keyword or 'top'
			request.reply(*rankings.ratio_list(request.service, request.dest.key, kind, mode, length=15))
	return handler

def on_beta(request, args):
	""".beta: the volatile small caps among the stocks followed."""
	payload, chart = rankings.prepare_beta_payload(request.service, request.dest.key)
	request.reply(payload, chart)

def on_pie(request, args):
	""".pie PORTFOLIO [sector]: its value by industry, or by sector; with no portfolio, buttons for them."""
	if not args.words:
		return picker(request, 'p', args)
	payload, chart = holdings.prepare_pie(args.rest, args.keyword or 'industry', request.service)
	request.reply(payload, chart)

def on_treemap(request, args):
	""".treemap PORTFOLIO [sector]: its holdings as tiles, grouped by industry or by sector; with no portfolio, buttons
	for them."""
	if not args.words:
		return picker(request, 't', args)
	payload, chart = holdings.prepare_treemap(args.rest, args.keyword or 'industry', request.service)
	request.reply(payload, chart)

def on_rating(request, args):
	""".buy, .sell or both (.buy & sell, a keyboard button): the analysts' strongest buy or sell ratings, as asked."""
	for action in dict.fromkeys(re.findall('buy|sell', f'{args.word} {args.text}'.lower())): # each once, as asked
		payload, chart = rankings.prepare_rating_payload(request.service, request.dest.key, action, length=15)
		request.reply(payload, chart)

def on_compare(request, args):
	""".compare SYMBOL SYMBOL... [period]: their price changes on one chart, with period buttons where they work; with
	no symbols, buttons to pick them."""
	if not args.words:
		return picker(request, 'c', args)
	if not 2 <= len(args.words) <= buttons.MAX_PICKED:
		raise Usage
	tickers = list(dict.fromkeys(yahoo.symbols(args.words))) # each once, in the order asked
	if len(tickers) < 2:
		raise Usage
	if not compare_picker(request, tickers, args.days):
		chart_reply(request, 'c', tickers, args.days)

def compare_picker(request, tickers, days):
	"""Compare of the tickers typed, with the picker's buttons under the chart (the period row and the tickers' menu),
	where the chat has buttons and the tickers are among those it offers (held, else watched) and the period is one
	of the buttons: True when it did; else False, and the chart has its period buttons alone."""
	dest = request.dest
	period = buttons.period_for_days(days, 'x' if days is None else None)
	if not (dest.takes_buttons and delivery.interactive(dest)) or period is None:
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

def on_history(request, args):
	""".history SYMBOL: the stock's change over every period, with its price chart, and period buttons where they go;
	with no symbol, buttons to pick one."""
	if not args.words:
		return picker(request, 'y', args)
	if len(args.words) != 1:
		raise Usage
	chart_reply(request, 'h', [ticker(args)])

def picker(request, cmd, args):
	"""A command typed with nothing to say what it is about (cmd, a key of buttons.PICKERS): where there are buttons,
	its answer for the first portfolio or ticker (the first two to compare), alphabetically, with the picker's buttons
	under it, one message that a press then edits (holdings, which has no first answer, is the picker alone); a pie or
	treemap's other charts are then drawn in the background to fill the cache. Else the command's usage."""
	dest = request.dest
	if not (dest.takes_buttons and delivery.interactive(dest)):
		raise Usage(portfolios()) if pick.noun(cmd) == 'portfolio' else Usage
	group = {'sector': 's', 'industry': 'i'}.get(args.keyword, '0')
	first = 'w' if cmd == 'c' and args.keyword != 'max' else 'x' # compare starts on 7D, unless asked for max
	period = buttons.period_for_days(args.days, first) if cmd in 'cy' else '0'
	found = pick.items(cmd, dest.key)
	shown, mask = pick.default(cmd, found)
	send_picker(request, cmd, found, group, period, shown, mask)

def send_picker(request, cmd, found, group, period, shown, mask):
	"""The first message of a picker of the items `found`: the answer for what `shown` says (or the picker alone, for
	0), the buttons under it, and the answer's other charts drawn in the background to fill the cache."""
	dest = request.dest
	lines, rows = pick.screen(request.service, cmd, found, group, period, shown, mask, 'p')
	if not shown:
		return dest.text(lines, rows)
	caption, chart = pick_content(request.service, dest, cmd, group, period, pick.shown_names(cmd, found, shown))
	if not pick.as_photo(dest, cmd):
		dest.text(caption.split('\n'), rows) # no chart goes: the answer as text, its buttons kept
	elif chart and chart.rows:
		request.reply(caption.split('\n'), chart, rows)
	else: # nothing to draw (no holdings, too few prices): a photo all the same, which a press can turn into a chart
		dest.chart(render.blank(), caption, rows)
	if cmd in 'pt' and pick.as_photo(dest, cmd):
		prime_in_background(request.service, cmd, group, found, 0)
	elif cmd in 'yc' and chart:
		prime_periods(dest, 'c' if cmd == 'c' else 'h', pick.shown_names(cmd, found, shown), period)

def prime_in_background(service, cmd, group, found, index):
	"""Start drawing a picker's other charts, to fill the cache, in a thread of its own (see pick.prime)."""
	threading.Thread(target=pick.prime, args=(service, cmd, group, found, index), daemon=True).start()

def chart_reply(request, kind, args, days=None):
	"""The first view of a chart with period buttons, built as a button press builds it (charts.build): its caption,
	chart and buttons where they go, the period shown marked (Max when days is None)."""
	caption, chart = charts.build(kind, args, request.service, request.dest.key, days=days)
	markup = None
	if chart and request.dest.takes_buttons:
		markup = buttons.keyboard(kind, args, buttons.period_for_days(days) if days else 'x')
	request.reply(caption.split('\n'), chart, markup)
	if chart:
		prime_periods(request.dest, kind, args, buttons.period_for_days(days) if days else 'x')

def prime_periods(dest, kind, args, shown):
	"""After a chart with period buttons is sent to a chat (dest; kind, args and the period `shown`: charts.build), its
	other periods are drawn in the background to fill the cache, where the chat can use them: a command asked for, or a
	picker's press, with charts and buttons."""
	if dest.takes_buttons and dest.takes_charts and config.settings.graph and delivery.interactive(dest):
		charts.prime_in_background(kind, args, dest.dialect, dest.key, shown)

def on_plan(request, args):
	""".plan [text]: record the sender's plan in this chat, and list everyone's here."""
	if args.text and not args.text.startswith('@'):
		with state.edit_for(request.dest.key, PLANS, {}) as plans:
			plans[request.user] = args.text
	plan = state.load_for(request.dest.key, PLANS, {})
	if not plan:
		raise answer.Answer("No plans yet: .plan TEXT records yours")
	def who(user):
		"""A sender as shown: on Slack a mention (<@U123>), which is markup to keep; elsewhere the handle as text."""
		user = user.removeprefix('@')
		return user if request.service == 'slack' else request.service.escape(user)
	service = request.service
	request.reply(formats.sections(*([f"{service.bold(who(k))}: {service.italic(service.escape(v))}"]
		for k, v in plan.items())))

def on_who(request, args):
	""".who SYMBOL: the portfolios that hold it."""
	if not args.words:
		raise Usage
	request.reply(holdings.prepare_who(request.service, re.split(r'[.:]', args.words[0].upper())[0]))

def on_jobs(request, args):
	""".jobs: this chat's jobs, with the menu's buttons; .jobs upcoming: the next runs; .jobs system: the system's;
	.jobs enable, disable, delete, run or toggle NUMBER: one switched on or off, deleted, run now, or switched the
	other way, and without a number the list with a button per job that does it; .jobs add REPORT SCHEDULE, or .jobs
	add message SCHEDULE "TEXT": one more (alone, the reports a job can run)."""
	scheduler, chat, service = jobs.current, request.dest.key, request.service
	tappable = request.dest.takes_buttons
	if scheduler is None:
		raise answer.Answer('No schedule is running')
	try:
		if args.keyword is None and not args.words:
			lines, markup = about.jobs_screen(service, chat, tappable=tappable)
			request.reply(lines, buttons=markup)
		elif args.keyword == 'upcoming' and not args.words:
			lines, markup = about.next_screen(service, chat)
			request.reply(lines, buttons=markup if tappable else None)
		elif args.keyword == 'system' and not args.words:
			request.reply(about.prepare_system(service))
		elif args.keyword == 'add':
			first, text = (args.text.split(None, 1) + [''])[:2]
			if first.lower() != 'add': # the job follows add
				raise Usage
			if not text.strip():
				return request.reply(about.prepare_reports(service))
			number = scheduler.add(chat, *jobs.parse_add(text, formats.zone().key))
			request.reply([about.job_entry(service, scheduler, number, scheduler.chat_jobs(chat)[number - 1]),
				'Added: .jobs lists them all'])
		elif args.keyword in JOB_SCREENS and not args.words:
			lines, markup = about.jobs_screen(service, chat, JOB_SCREENS[args.keyword], tappable=tappable)
			request.reply(lines, buttons=markup)
		elif args.keyword in JOB_SCREENS and len(args.words) == 1:
			number = args.words[0]
			job = scheduler.job(chat, number)
			if args.keyword == 'run':
				request.reply([about.job_line(service, number, job, scheduler.run(job))])
			elif args.keyword == 'del':
				scheduler.delete(job)
				request.reply([f"Deleted {number}. {service.escape(job.name)} · "
					f"{job.schedule.describe(formats.zone().key)}"])
			else:
				if args.keyword == 'toggle':
					scheduler.toggle(job)
				else:
					scheduler.switch(job, args.keyword == 'enable')
				request.reply([about.job_entry(service, scheduler, number, scheduler.job(chat, number))])
		else:
			raise Usage
	except jobs.ScheduleError as e: # a job that cannot be, or a number that is none: said, as an answer
		raise answer.Answer(service.escape(str(e))) # escaped: it may quote what was typed

def on_profile(request, args):
	""".SYMBOL, or .stock (.profile) SYMBOL: the company's profile."""
	if args.word.lower() in PROFILE.names:
		if len(args.words) != 1:
			raise Usage
		symbol = ticker(args)
	else:
		symbol = yahoo.symbol(args.word)
	request.reply(profile.prepare_profile_payload(request.service, request.user, symbol))

@dataclasses.dataclass(frozen=True)
class Command:
	"""A chat command: its names (typos too; a name may be two words, as 'forward pe'), the handler that answers it,
	its .help lines under its section's heading, the Telegram keyboard buttons that send it, and what its arguments may
	hold besides words (read_args): a percent, a period, its keywords ({spelling: keyword})."""
	names: tuple
	handler: typing.Callable
	usage: tuple = () # its lines in .help; none keeps it out of .help
	section: str = ''
	buttons: tuple = ()
	percent: bool = False
	period: bool = False
	keywords: dict = dataclasses.field(default_factory=dict)
	job: bool = True # whether a job may run it (job_commands): not one that changes something

SECTIONS = TRACKED, COMPANY, PRICE, RISK, TRADES, JOBS = ('Tracked securities', 'Company info', 'Price', 'Risk & Value',
	'Trades', 'Scheduled jobs') # the headings of .help, in order

TOP = {'top': 'top', 'bottom': 'bottom'} # the ends of a ranked list
NEGATIVE = TOP | dict.fromkeys(('neg', 'negative', 'negatives'), 'negative') # the ratios that can be negative
CHANGE = {'add': 'add'} | dict.fromkeys(('del', 'delete', 'rem', 'remove', 'rm'), 'delete') # of the watchlist
PLANS = 'finbot_plan.json' # each chat's plans, {user: plan}, as state.load_for keeps them
BY = dict.fromkeys(('sector', 'sectors'), 'sector') | dict.fromkeys(('industry', 'industries'), 'industry') # .pie's
# what .jobs does to a chat's jobs, and shows; next is what upcoming was called before
JOB_CHANGES = {'run': 'run', 'toggle': 'toggle', 'enable': 'enable', 'disable': 'disable', 'add': 'add',
	'system': 'system'} | dict.fromkeys(('upcoming', 'next'), 'upcoming') | dict.fromkeys(('del', 'delete', 'rem',
	'remove', 'rm'), 'del')
JOB_SCREENS = {'enable': 'on', 'disable': 'off', 'del': 'del', 'run': 'run', 'toggle': 'top'} # each word's screen
BUY_SELL = ('buy', 'sell', *(a + sep + b for a, b in (('buy', 'sell'), ('sell', 'buy')) for sep in ('', '&', '/', '+')))
PROFILE = Command(('stock', 'profile'), on_profile, ('.SYMBOL', '.stock SYMBOL'), COMPANY) # any first word that is no
# command's name but may be a ticker calls it too

COMMANDS = [ # .help lists a section's commands in this order. The odd spellings (earrings, prince, hospital...) are
	# kept on purpose.
	Command(('help', 'usage', 'start'), on_help, job=False), # /start is what Telegram sends when a chat opens
	Command(('holdings', 'holding'), on_holdings, ('.holdings PORTFOLIO',), TRACKED),
	Command(('pie',), on_pie, ('.pie PORTFOLIO [sector]',), TRACKED, ('.pie',), keywords=BY),
	Command(('treemap',), on_treemap, ('.treemap PORTFOLIO [sector]',), TRACKED, ('.treemap',), keywords=BY),
	Command(('watchlist', 'wishlist'), on_watchlist, ('.watchlist [add|del SYMBOL]',), TRACKED, ('.watchlist',),
		keywords=CHANGE, job=False),
	Command(('who',), on_who, ('.who SYMBOL',), TRACKED),
	Command(('earnings', 'earning', 'earrings', 'earring', 'dividends', 'dividend', 'exdividend', 'ex-dividend'),
		on_calendar, ('.dividend [period|SYMBOL]', '.earnings [period|SYMBOL]'), COMPANY, ('.earnings',),
		period=True),
	Command(('marketcap', 'maletas', 'marketer'), on_marketcap, ('.marketcap [SYMBOL|top|bottom]',), COMPANY,
		keywords=TOP),
	Command(('beta',), on_beta, ('.beta',), PRICE),
	Command(('compare',), on_compare, ('.compare SYMBOL SYMBOL [... up to 8] [period]',), PRICE, ('.compare',),
		period=True, keywords={'max': 'max', 'all': 'max'}), # max: as the default, 10 years
	Command(('history', 'hospital', 'visual', 'hosiery'), on_history, ('.history SYMBOL',), PRICE),
	Command(('performance', 'performanc'), on_performance, ('.performance [period] [portfolio]',), PRICE,
		('.performance',), period=True),
	Command(('price', 'prices', 'prince', 'print', 'probe', 'piece', 'pierce', 'pence', 'prime'), on_price,
		('.price [percent|SYMBOL|top|bottom] [period]',), PRICE, ('.price',), percent=True, period=True, keywords=TOP),
	Command(('session', 'premarket', 'postmarket', 'permarket'), on_session,
		('.session [percent|SYMBOL]', '.premarket [percent|SYMBOL]'), PRICE, ('.session', '.premarket'), percent=True),
	Command(BUY_SELL, on_rating, ('.buy', '.sell'), RISK, ('.buy & sell',)), # .buy & sell (or .buy sell): both
	Command(('pe',), on_ratio('pe'), ('.pe [SYMBOL|top|bottom]',), RISK, keywords=TOP),
	Command(('forward pe', 'forwardpe', 'fpe'), on_ratio('forward pe'), ('.forward pe [SYMBOL|top|bottom|negative]',),
		RISK, ('.forward pe',), keywords=NEGATIVE),
	Command(('peg',), on_ratio('peg'), ('.peg [SYMBOL|top|bottom|negative]',), RISK, ('.peg',), keywords=NEGATIVE),
	Command(('shorts', 'short'), on_shorts, ('.shorts [percent|SYMBOL]',), RISK, ('.shorts',), percent=True),
	Command(('trades', 'trade'), on_trades, ('.trades [period] [portfolio]',), TRADES, ('.trades',), period=True),
	Command(('plan',), on_plan, ('.plan [your plan]',), TRADES, job=False),
	Command(('jobs', 'job', 'cron', 'crons', 'schedule'), on_jobs, ('.jobs [upcoming|system]',
		'.jobs enable|disable|delete|run [NUMBER]', '.jobs add REPORT SCHEDULE', '.jobs add message SCHEDULE "TEXT"'),
		JOBS, ('.schedule',), keywords=JOB_CHANGES, job=False),
	PROFILE,
]

def help_sections(slash=False):
	"""The sections of .help: (heading, the .help lines of its commands, in table order), in SECTIONS order; with slash,
	each line as its slash command (/forwardpe for .forward pe, /stock SYMBOL for .SYMBOL)."""
	def shown(command, line):
		"""The line, or its slash command."""
		form = slash_form(command, line) if slash else None
		return f'/{form[0]} {form[1]}'.strip() if form else line
	return [(section, list(dict.fromkeys(shown(command, line) for command in COMMANDS if command.section == section
		for line in command.usage))) for section in SECTIONS]

SLASH_NAME = re.compile(r'[a-z0-9_]{1,32}') # what a slash command may be named, on every network
SLASH_ALIASES = {'stock': 'profile', 'jobs': 'job'} # slash commands with a second name, which the networks that list
# every slash command list too (Discord, Slack); typed, the second name works on Telegram too, as every name does

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

def slash_commands(aliases=True):
	"""The slash commands to register (Slash), from the .help lines (slash_form), and /help; the arguments of a
	command's several lines joined by " | ". With aliases, the second names of SLASH_ALIASES too, each after its
	first."""
	found = {'help': (None, [])} # name -> (its command, the arguments of its lines)
	for command in COMMANDS:
		for line in command.usage:
			if form := slash_form(command, line):
				name, arguments = form
				for each in (name, SLASH_ALIASES.get(name) if aliases else None):
					if each and arguments not in found.setdefault(each, (command, []))[1]:
						found[each][1].append(arguments)
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

REPORTED = (on_price, on_performance, on_trades, on_shorts, on_calendar, on_session) # what a scheduled report runs

@dataclasses.dataclass(frozen=True)
class CommandJob:
	"""A command of .help as a job's action (job_commands), standing in for a report module: ARGUMENTS is what it takes,
	from its usage; job() reads a scheduled run's words; run() answers in the job's chat as the command would."""
	command: Command
	name: str # what the job calls it, its name in .help, but buy, sell or both: on_rating reads which from the name
	ARGUMENTS: str = ''
	listed: bool = True # whether .jobs add lists it: not a command's other names, nor its typos

	@property
	def needs(self):
		"""How many words it needs, each SYMBOL or PORTFOLIO of its usage outside brackets: none comes from a button."""
		return len(re.findall(r'\b[A-Z]{2,}\b', re.sub(r'\[[^\]]*\]', '', self.ARGUMENTS)))

	def job(self, argv):
		"""A scheduled run's arguments (words): (label, run's keyword arguments). Raises ValueError, with what it takes,
		for words where its usage takes none, or fewer than it needs."""
		args = read_args(self.command, self.name, ' '.join(argv))
		if (argv and not self.ARGUMENTS) or len(args.words) < self.needs:
			raise ValueError(self.ARGUMENTS or 'no arguments')
		return ' '.join([self.name.replace('&', ' & '), *argv]), {'words': list(argv)}

	def run(self, dest, *, words):
		"""Answer in the job's chat (dest) as the command would to these words, typed there: its usage where it cannot
		take them, an answer as an answer; any other failure is the job's to report."""
		request = Request(dest.dialect, dest.where, '', '', '', dest=dest)
		try:
			self.command.handler(request, read_args(self.command, self.name, ' '.join(words)))
		except Usage as e:
			request.reply([f"Usage: {line}" for line in self.command.usage] + list(e.lines))
		except answer.Answer as e:
			request.reply(e.lines)

@functools.cache
def job_commands():
	"""The commands of .help a job may run, by each name a job may call one by: a CommandJob each. Every one but those
	that change something (job false) and those a scheduled report runs already (REPORTED): first each by its name in
	.help, with what it takes; then its other names (typos too), each standing for the first, but buy and sell's."""
	found = {}
	for command in COMMANDS:
		if not (command.job and command.usage) or command.handler in REPORTED:
			continue
		listed = []
		for line in command.usage:
			words = line.lstrip('.').split()
			name = next((' '.join(words[:size]).lower() for size in (2, 1) if ' '.join(words[:size]).lower() in
				command.names), None)
			if name:
				found[name] = CommandJob(command, name, ' '.join(words[len(name.split()):]))
				listed.append(name)
		first = found[listed[0]]
		for name in command.names:
			found.setdefault(name, dataclasses.replace(first, name=name if command.handler is on_rating else first.name,
				listed=False))
	return found

PERIOD_WORDS = ('1d', '7d', '1m', '3m', '6m', 'ytd', '1y', '5y', '10y') # suggested where a command takes a period
JOB_WORDS = ('add', 'delete', 'enable', 'disable', 'run', 'upcoming', 'system') # what /jobs suggests first
SCHEDULE_WORDS = ('daily', 'weekdays', 'weekly', 'monthly', 'quarterly', 'bi-annual', 'annual', 'hourly', 'every', 'at',
	'from', 'between', 'on') # what a schedule in English is made of, suggested after a report

def completes(command):
	"""Whether suggest has words to offer for a command's arguments: its keywords, periods, tickers, portfolios, or
	those of /jobs."""
	usage = ' '.join(command.usage)
	return bool(command.handler is on_jobs or command.keywords or command.period or 'SYMBOL' in usage or
		'portfolio' in usage.lower())

def suggest(chat, text):
	"""What to suggest while a slash command's arguments are typed (Discord's autocomplete), from the message they make
	so far (text: /price 5 7) in a chat (its key): up to 25 (name shown, value) pairs, each value the arguments with the
	word being typed completed. The words come from the command's entry in the table: its keywords, periods, portfolios
	and tickers (the chat's watchlist and the holdings, as cached, never a request: suggestions must come at once); for
	/jobs, its subcommands, this chat's job numbers and the reports. Never raises: the failure is logged instead, and
	nothing suggested."""
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
	usage = ' '.join(command.usage)
	words = [word for word in re.findall(r'[\w-]+', usage)
		if word in command.keywords and word not in command.names and given.keyword is None]
	if command.period and given.days is None:
		words += PERIOD_WORDS
	if 'SYMBOL' in usage or 'portfolio' in usage.lower():
		names, held = sharesight.cached()
		if 'portfolio' in usage.lower():
			words += names
		if 'SYMBOL' in usage:
			words += sorted(set(watchlist.tickers(chat)) | set(held))
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
		return [(name, f'{name} {jobs.actions()[name].ARGUMENTS}'.strip()) for name in jobs.chat_actions()]
	module = jobs.actions().get(words[1].lower())
	if module is None or words[1].lower() not in jobs.chat_actions():
		return []
	takes = re.findall(r'[a-z][a-z-]*', module.ARGUMENTS) if len(words) == 2 else []
	return [(word, word) for word in dict.fromkeys(takes + list(SCHEDULE_WORDS))]

def command_keyboard(per_row=3):
	"""Persistent reply keyboard of the commands that have buttons (Telegram DMs), alphabetical, row by row; a press
	sends the button's text as a message."""
	texts = sorted(text for command in COMMANDS for text in command.buttons)
	rows = [[{'text': text} for text in texts[i:i + per_row]] for i in range(0, len(texts), per_row)]
	return {'keyboard': rows, 'resize_keyboard': True, 'is_persistent': True}

KEYBOARD_FILE = 'finbot_keyboards.json' # chat id -> version of the command keyboard that chat last received

def keyboard_version():
	"""A short hash of the command keyboard, which changes whenever its buttons do."""
	return hashlib.sha1(json.dumps(command_keyboard(), sort_keys=True).encode()).hexdigest()[:8]

def mark_keyboard(chat_id):
	"""Record that this chat now has the current command keyboard."""
	with state.edit(KEYBOARD_FILE, {}) as versions:
		versions[str(chat_id)] = keyboard_version()

def push_keyboard(chat_id):
	"""Telegram can only change a reply keyboard by sending a message, so send a short one carrying it."""
	result = telegram_common.TelegramBot(chat_id).post_text('⌨️ Keyboard updated', command_keyboard())
	if result is not None:
		mark_keyboard(chat_id)
	return result

def ensure_keyboard(chat_id):
	"""DMs only (positive chat ids): update a chat's keyboard if its buttons changed or it never had them."""
	if int(chat_id) <= 0:
		return
	if state.load(KEYBOARD_FILE, {}).get(str(chat_id)) != keyboard_version():
		push_keyboard(chat_id)

def refresh_keyboards():
	"""At startup: update every chat we know of whose keyboard is out of date."""
	for chat_id, version in state.load(KEYBOARD_FILE, {}).items():
		if version != keyboard_version():
			try:
				push_keyboard(chat_id)
			except Exception as e:
				log.warn("keyboard refresh failed for", chat_id, e)
