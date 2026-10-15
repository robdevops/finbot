"""Chat commands: a message is answered by the Command in COMMANDS whose name it starts with (read), or .SYMBOL. The
table also makes the .help text and the Telegram command keyboard, which is kept current in every DM."""
import dataclasses
import hashlib
import json
import math
import re
import sys
import typing
from lib import answer
from lib import dialects
from lib import state
from lib import formats
from lib import delivery
from lib import render
from lib import buttons
from lib import charts
from lib.reports import about, cal, holdings, performance, price, profile, rankings, shorts, trades
from lib import sharesight
from lib import transports
from lib import jobs
from lib import watchlist
from lib import yahoo

@dataclasses.dataclass
class Request:
	"""A message being answered: where it came from (service is its dialect) and who sent it."""
	service: str
	chat_id: str
	user: str # the sender's handle: whose watchlist add or plan it is
	user_name: str # what to call them
	bot_name: str
	message_id: str = None # the message being answered
	interaction: str = '' # what the network answers through, where it has one (Discord's slash command)

	def __post_init__(self):
		"""The chat's transport, which also keeps the typing notice going."""
		self.dest = delivery.reply_to(self.service, self.chat_id, self.message_id, self.interaction)

	def reply(self, lines, chart=None, buttons=None):
		"""Answer in the chat (see delivery.deliver): the lines, perhaps a chart (drawn, or a spec drawn only where it
		can go) and buttons."""
		return delivery.deliver(self.dest, delivery.Report(lines, chart, buttons))

def process_job_callback(press, pressed):
	"""A job's button (an inbound.Press; pressed, what its data says): run the job now and say how it went, or switch
	it on or off and redraw the list in place. A button from an older list does neither: the list is redrawn as it is
	now."""
	service = dialects.of(press.service)
	chat = delivery.reply_to(service, press.chat_id, interaction=press.interaction, pressed=True)
	def redraw():
		"""Put the chat's list, as it is now, in place of the pressed one, with the same kind of buttons."""
		payload, markup = about.prepare_jobs_payload(service, chat.key, pressed.action, chat.takes_buttons)
		chat.edit_text(press.message_id, '\n'.join(payload), markup or [])
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
			delivery.deliver(chat, delivery.Report([about.job_line(pressed.number, job, jobs.current.run(job))]))
	except Exception as e:
		delivery.report_error(e, chat, context='jobs')

def process_callback(press):
	"""A button pressed (an inbound.Press, which bot.take acknowledged as it arrived): run a scheduled command from
	.jobs, or rebuild a chart message for the chosen period and edit it in place. Data of neither is ignored."""
	pressed = buttons.parse(press.data)
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
		caption, chart = charts.build(pressed.kind, args, service, period=pressed.period)
		if chart is None: # too few prices in that period to draw a line
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
			print("keyboard update failed:", e, file=sys.stderr)

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
	""".watchlist [add|del SYMBOL]: the watchlist, or a change to it."""
	if args.keyword and len(args.words) == 1: # what is removed is what is watched: Yahoo may know it no longer
		symbol = ticker(args) if args.keyword == 'add' else watchlist.watched(args.words[0])
		request.reply(holdings.prepare_watchlist(request.service, request.user, args.keyword, symbol))
	elif args.keyword or args.words:
		raise Usage
	else:
		request.reply(holdings.prepare_watchlist(request.service, request.user))

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
	event = 'ex-dividend' if args.word.startswith('div') else 'earnings'
	cal.run(request.dest, days=args.days, specific_stock=ticker(args), event=event)

def on_performance(request, args):
	""".performance [period] [portfolio]: each portfolio's return, over a month by default."""
	days = buttons.PERIODS['m'][1] if args.days is None else args.days # the default view is the 1M button
	if days < 1: # 0d, or ytd on 1 January
		raise answer.Answer("The period must cover a day or more, such as 7d, 3m or ytd")
	performance.run(request.dest, past_days=days, user=request.user, portfolio_select=args.rest or None)

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

def on_shorts(request, args):
	""".shorts [percent|SYMBOL]: the most shorted stocks followed, or one stock's short interest."""
	shorts.run(request.dest, threshold=args.percent, specific_stock=ticker(args))

def on_trades(request, args):
	""".trades [period] [portfolio]: the buys and sells, of the past day by default."""
	trades.run(request.dest, days=1 if args.days is None else args.days, user=request.user,
		portfolio_select=args.rest or None)

def on_holdings(request, args):
	""".holdings PORTFOLIO: what it holds."""
	if not args.words:
		raise Usage(portfolios())
	request.reply(holdings.prepare_holdings_payload(args.rest, request.service))

def on_marketcap(request, args):
	""".marketcap [SYMBOL|top|bottom]: stocks followed by market cap, largest (or smallest) first, or one stock's."""
	if args.words:
		request.reply([rankings.marketcap_line(request.service, ticker(args))])
	else:
		request.reply(rankings.marketcap_list(request.service, bottom=args.keyword == 'bottom', length=15))

def on_ratio(kind):
	"""The handler of .pe, .forward pe or .peg (kind: pe, forward pe or peg): the top (by default) or bottom 15 by the
	ratio and its chart, the negative ones (where there can be any), or one ticker's ratio."""
	def handler(request, args):
		""".pe, .forward pe or .peg [SYMBOL|top|bottom|negative]."""
		if args.words:
			request.reply([rankings.ratio_line(request.service, ticker(args), kind)])
		else:
			request.reply(*rankings.ratio_list(request.service, kind, args.keyword or 'top', length=15))
	return handler

def on_beta(request, args):
	""".beta: the volatile small caps among the stocks followed."""
	payload, chart = rankings.prepare_beta_payload(request.service)
	request.reply(payload, chart)

def on_pie(request, args):
	""".pie PORTFOLIO [sector]: its value by industry, or by sector."""
	if not args.words:
		raise Usage(portfolios())
	payload, chart = holdings.prepare_pie(args.rest, args.keyword or 'industry', request.service)
	request.reply(payload, chart)

def on_rating(request, args):
	""".buy, .sell or both (.buy & sell, a keyboard button): the analysts' strongest buy or sell ratings, as asked."""
	for action in dict.fromkeys(re.findall('buy|sell', f'{args.word} {args.text}'.lower())): # each once, as asked
		payload, chart = rankings.prepare_rating_payload(request.service, action, length=15)
		request.reply(payload, chart)

def on_compare(request, args):
	""".compare SYMBOL SYMBOL... [period]: their price changes on one chart, with period buttons where they work."""
	if not 2 <= len(args.words) <= 6:
		raise Usage
	tickers = list(dict.fromkeys(yahoo.symbols(args.words))) # each once, in the order asked
	if len(tickers) < 2:
		raise Usage
	chart_reply(request, 'c', tickers, args.days)

def on_history(request, args):
	""".history SYMBOL: the stock's change over every period, with its price chart, and period buttons where they go."""
	if len(args.words) != 1:
		raise Usage
	chart_reply(request, 'h', [ticker(args)])

def chart_reply(request, kind, args, days=None):
	"""The first view of a chart with period buttons, built as a button press builds it (charts.build): its caption,
	chart and buttons where they go, the period shown marked (Max when days is None)."""
	caption, chart = charts.build(kind, args, request.service, days=days)
	markup = None
	if chart and request.dest.takes_buttons:
		markup = buttons.keyboard(kind, args, buttons.period_for_days(days) if days else 'x')
	request.reply(caption.split('\n'), chart, markup)

def on_plan(request, args):
	""".plan [text]: record the sender's plan, and list everyone's."""
	if args.text and not args.text.startswith('@'):
		with state.edit('finbot_plan.json', {}) as plans:
			plans[request.user] = args.text
	plan = state.load('finbot_plan.json', {})
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
	""".jobs: this chat's jobs; .jobs run or toggle [NUMBER]: one run now or switched on or off (without a number, the
	list with a button per job that does it); .jobs add [CRON_TZ=ZONE] TIME REPORT: one more (alone, the reports it can
	run); .jobs del NUMBER: one fewer."""
	scheduler, chat, service = jobs.current, request.dest.key, request.service
	if scheduler is None:
		raise answer.Answer('No schedule is running')
	try:
		if args.keyword is None and not args.words:
			request.reply(about.prepare_jobs_payload(service, chat)[0])
		elif args.keyword == 'add':
			first, line = (args.text.split(None, 1) + [''])[:2]
			if first.lower() != 'add': # the job's line follows add
				raise Usage
			if not line:
				return request.reply(about.prepare_reports(service))
			number = scheduler.add(chat, line)
			request.reply([about.job_entry(service, scheduler, number, scheduler.chat_jobs(chat)[number - 1]),
				'Added: .jobs lists them all'])
		elif args.keyword in ('run', 'toggle') and not args.words:
			payload, markup = about.prepare_jobs_payload(service, chat, args.keyword, request.dest.takes_buttons)
			request.reply(payload, buttons=markup)
		elif args.keyword in ('run', 'toggle', 'del') and len(args.words) == 1:
			number = args.words[0]
			job = scheduler.job(chat, number)
			if args.keyword == 'run':
				request.reply([about.job_line(number, job, scheduler.run(job))])
			elif args.keyword == 'toggle':
				scheduler.toggle(job)
				request.reply([about.job_entry(service, scheduler, number, scheduler.job(chat, number))])
			else:
				scheduler.delete(job)
				request.reply([f"Deleted {number}. {job.line}"])
		else:
			raise Usage
	except jobs.ScheduleError as e: # a job that cannot be, or a number that is none: said, as an answer
		raise answer.Answer(str(e))

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

SECTIONS = TRACKED, COMPANY, PRICE, RISK, TRADES, JOBS = ('Tracked securities', 'Company info', 'Price', 'Risk & Value',
	'Trades', 'Scheduled jobs') # the headings of .help, in order

TOP = {'top': 'top', 'bottom': 'bottom'} # the ends of a ranked list
NEGATIVE = TOP | dict.fromkeys(('neg', 'negative', 'negatives'), 'negative') # the ratios that can be negative
CHANGE = {'add': 'add'} | dict.fromkeys(('del', 'delete', 'rem', 'remove', 'rm'), 'delete') # of the watchlist
BY = dict.fromkeys(('sector', 'sectors'), 'sector') | dict.fromkeys(('industry', 'industries'), 'industry') # .pie's
JOB_CHANGES = {'run': 'run', 'toggle': 'toggle', 'add': 'add'} | dict.fromkeys(('del', 'delete', 'rem', 'remove', 'rm'),
	'del') # what .jobs does to a chat's jobs
BUY_SELL = ('buy', 'sell', *(a + sep + b for a, b in (('buy', 'sell'), ('sell', 'buy')) for sep in ('', '&', '/', '+')))
PROFILE = Command(('stock', 'profile'), on_profile, ('.SYMBOL', '.stock SYMBOL'), COMPANY) # any first word that is no
# command's name but may be a ticker calls it too

COMMANDS = [ # .help lists a section's commands in this order. The odd spellings (earrings, prince, hospital...) are
	# kept on purpose.
	Command(('help', 'usage', 'start'), on_help), # /start is what Telegram sends when a chat opens
	Command(('holdings', 'holding'), on_holdings, ('.holdings PORTFOLIO',), TRACKED),
	Command(('pie',), on_pie, ('.pie PORTFOLIO [sector]',), TRACKED, keywords=BY),
	Command(('watchlist', 'wishlist'), on_watchlist, ('.watchlist [add|del SYMBOL]',), TRACKED, ('.watchlist',),
		keywords=CHANGE),
	Command(('who',), on_who, ('.who SYMBOL',), TRACKED),
	Command(('earnings', 'earning', 'earrings', 'earring', 'dividends', 'dividend'), on_calendar,
		('.dividend [period|SYMBOL]', '.earnings [period|SYMBOL]'), COMPANY, ('.dividend', '.earnings'), period=True),
	Command(('marketcap', 'maletas', 'marketer'), on_marketcap, ('.marketcap [SYMBOL|top|bottom]',), COMPANY,
		('.marketcap',), keywords=TOP),
	Command(('beta',), on_beta, ('.beta',), PRICE, ('.beta',)),
	Command(('compare',), on_compare, ('.compare SYMBOL SYMBOL [... up to 6] [period]',), PRICE, period=True,
		keywords={'max': 'max', 'all': 'max'}), # max: as the default, 10 years
	Command(('history', 'hospital', 'visual', 'hosiery'), on_history, ('.history SYMBOL',), PRICE),
	Command(('performance', 'performanc'), on_performance, ('.performance [period] [portfolio]',), PRICE,
		('.performance',), period=True),
	Command(('price', 'prices', 'prince', 'print', 'probe', 'piece', 'pierce', 'pence', 'prime'), on_price,
		('.price [percent|SYMBOL|top|bottom] [period]',), PRICE, ('.price',), percent=True, period=True, keywords=TOP),
	Command(('session', 'premarket', 'postmarket', 'permarket'), on_session,
		('.session [percent|SYMBOL]', '.premarket [percent|SYMBOL]'), PRICE, ('.session', '.premarket'), percent=True),
	Command(BUY_SELL, on_rating, ('.buy', '.sell'), RISK, ('.buy & sell',)), # .buy & sell (or .buy sell): both
	Command(('pe',), on_ratio('pe'), ('.pe [SYMBOL|top|bottom]',), RISK, ('.pe',), keywords=TOP),
	Command(('forward pe', 'forwardpe', 'fpe'), on_ratio('forward pe'), ('.forward pe [SYMBOL|top|bottom|negative]',),
		RISK, ('.forward pe',), keywords=NEGATIVE),
	Command(('peg',), on_ratio('peg'), ('.peg [SYMBOL|top|bottom|negative]',), RISK, ('.peg',), keywords=NEGATIVE),
	Command(('shorts', 'short'), on_shorts, ('.shorts [percent|SYMBOL]',), RISK, ('.shorts',), percent=True),
	Command(('trades', 'trade'), on_trades, ('.trades [period] [portfolio]',), TRADES, ('.trades',), period=True),
	Command(('plan',), on_plan, ('.plan [your plan]',), TRADES),
	Command(('jobs', 'job', 'cron', 'crons', 'schedule'), on_jobs, ('.jobs [run|toggle] [NUMBER]',
		'.jobs add [CRON_TZ=ZONE] TIME REPORT', '.jobs del NUMBER'), JOBS, keywords=JOB_CHANGES),
	PROFILE,
]

def help_sections(slash=False):
	"""The sections of .help: (heading, the .help lines of its commands, in table order), in SECTIONS order; with slash,
	each line as its slash command (/forwardpe for .forward pe, /stock SYMBOL for .SYMBOL)."""
	def shown(command, line):
		"""The line, or its first slash command."""
		forms = slash_forms(command, line) if slash else []
		return f'/{forms[0][0]} {forms[0][1]}'.strip() if forms else line
	return [(section, list(dict.fromkeys(shown(command, line) for command in COMMANDS if command.section == section
		for line in command.usage))) for section in SECTIONS]

SLASH_NAME = re.compile(r'[a-z0-9_-]{1,32}') # what a slash command may be named, on every network

def slash_forms(command, line):
	"""The slash commands of one of a command's .help lines: [(name, the arguments it shows)]. One, named by the
	command's name the line starts with where a slash command may be so named, else by the command's first name that it
	may (.forward pe is /forwardpe); a line that starts with no name (.SYMBOL) has one under each of them."""
	valid = [name for name in command.names if SLASH_NAME.fullmatch(name)]
	words = line.removeprefix('.').split()
	named = next((name for name in command.names if [w.lower() for w in words[:len(name.split())]] == name.split()),
		None)
	if named is None:
		return [(name, ' '.join(words)) for name in valid]
	return [(named if named in valid else valid[0], ' '.join(words[len(named.split()):]))] if valid else []

def slash_commands():
	"""The slash commands to register, each with its description and the arguments it shows: [(name, description,
	arguments)], from the .help lines (slash_forms), and /help."""
	found = {'help': ('help', 'every command, and what it takes', '')}
	for command in COMMANDS:
		for line in command.usage:
			for name, arguments in slash_forms(command, line):
				found.setdefault(name, (name, f'{name} {arguments}'.strip(), arguments))
	return list(found.values())

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
	result = transports.TelegramBot(chat_id).post_text('⌨️ Keyboard updated', command_keyboard())
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
				print("keyboard refresh failed for", chat_id, e, file=sys.stderr)
