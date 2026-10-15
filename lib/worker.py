"""Chat commands: a message is answered by the handler of the first Command in COMMANDS that fits it. The table also
makes the .help text and the Telegram command keyboard, which is kept current in every DM."""
import dataclasses
import datetime
import hashlib
import json
import math
import random
import re
import sys
import threading
import typing
from lib import answer
from lib import config
from lib import dialects
from lib import state
from lib import words
from lib import formats
from lib import markets
from lib import delivery
from lib import buttons
from lib import charts
from lib.reports import about, cal, history, holdings, performance, price, profile, rankings, shorts, trades
from lib import telegram
from lib import transports
from lib import jobs

class TypingIndicator:
	"""The typing notice while a command works, where the destination shows one (Telegram). It starts after `delay`
	seconds, so a quick answer gets none, and is sent again every 7 seconds until stopped, at most max_loops times. The
	worker stops it before the answer goes out, however the command ends."""
	def __init__(self, dest, max_loops=10, delay=0.5):
		"""dest: the chat's transport."""
		self.dest = dest
		self.max_loops = max_loops
		self.delay = delay
		self._stop_event = threading.Event()
		self._thread = None

	def _worker(self):
		"""Wait out the delay, then send the notice every 7 seconds until stopped, or until max_loops are sent."""
		if self._stop_event.wait(self.delay):
			return
		for _ in range(self.max_loops):
			self.dest.typing()
			if self._stop_event.wait(7):
				return

	def start(self):
		"""Start the notices, where the destination shows them."""
		if self.dest is not None and self.dest.shows_typing:
			self._thread = threading.Thread(target=self._worker, daemon=True)
			self._thread.start()

	def stop(self):
		"""Stop the notices and wait for their thread to end."""
		if not self._thread: # never started
			return
		self._stop_event.set()
		self._thread.join()

	def is_active(self):
		"""Whether the notices are still going."""
		return self._thread is not None and self._thread.is_alive()

@dataclasses.dataclass
class Request:
	"""A message being answered: where it came from (service is its dialect), who sent it, and its typing notice."""
	service: str
	chat_id: str
	user: str # the sender's handle: whose watchlist add or plan it is
	user_name: str # what to call them
	bot_name: str

	def __post_init__(self):
		"""The chat's transport, and its typing notice (not started)."""
		self.dest = delivery.reply_to(self.service, self.chat_id)
		self.typing = TypingIndicator(self.dest)

	def reply(self, lines, chart=None, buttons=None):
		"""Answer in the chat (see delivery.deliver): the lines, perhaps a chart (drawn, or a spec drawn only where it
		can go) and buttons. The typing notice stops first."""
		self.typing.stop()
		return delivery.deliver(self.dest, delivery.Report(lines, chart, buttons))

def process_job_callback(service, callback_id, chat_id, message_id, data):
	"""A command button of .jobs: run that command now and answer in the chat."""
	try:
		_, number, crc = data.split('|') # only a command offered by .jobs can be picked; anything else is refused
		command = jobs.current.pick(number, crc)
	except (ValueError, jobs.ScheduleError, AttributeError):
		telegram.answerCallbackQuery(callback_id, 'Buttons updated, try again')
		payload, markup = about.prepare_jobs_payload(service, '') # the list as it is now, in place of the stale one
		delivery.reply_to(service, chat_id).edit_text(message_id, '\n'.join(payload), markup or [])
		return
	telegram.answerCallbackQuery(callback_id, f'Running {jobs.display(command[0])}…'[:100])
	try:
		line = about.job_line(jobs.current, *jobs.current.run_command(command))
		delivery.deliver(delivery.reply_to(service, chat_id), delivery.Report([line]))
	except Exception as e:
		delivery.report_error(e, service, chat_id, context='jobs')

def process_callback(service, callback_id, chat_id, message_id, data):
	"""Button press: run a scheduled command from .jobs, or rebuild a chart message for the chosen period and edit it in place."""
	service = dialects.of(service)
	if data.startswith('j|'):
		return process_job_callback(service, callback_id, chat_id, message_id, data)
	parts = data.split('|', 3)
	valid = len(parts) == 4 and parts[0] == 'c' and parts[1] in buttons.BUTTONS and parts[2] in buttons.BUTTONS[parts[1]]
	# answering now shows Telegram's toast bubble ("Loading 3M…") while the new chart is built
	telegram.answerCallbackQuery(callback_id, f"Loading {buttons.PERIODS[parts[2]][0]}…" if valid else None)
	if not valid:
		return
	try:
		_, kind, period, ref = parts
		tickers = buttons.resolve(ref)
		caption, image = charts.build(kind, tickers, period, service)
		chat = delivery.reply_to(service, chat_id)
		chat.edit_chart(message_id, image, caption, buttons.keyboard(kind, tickers, period))
	except answer.Answer as e: # nothing to draw for that period: said in the chat, as a command would
		delivery.deliver(delivery.reply_to(service, chat_id), delivery.Report(e.lines))
	except Exception as e:
		delivery.report_error(e, service, chat_id, context='chart')

def process_request(service, chat_id, user, message, botName, userRealName):
	"""Entry point for inbound chat requests: the first command in COMMANDS that fits the message answers it (a message
	that fits none gets no answer), with the typing notice meanwhile. Any failure becomes a one-line reply in the
	originating chat, after the typing stops."""
	request = Request(dialects.of(service), chat_id, user, userRealName, botName)
	try:
		for command in COMMANDS:
			if m := match(command.pattern, message, botName):
				request.typing.start()
				command.handler(request, m)
				break
	except answer.Answer as e: # a portfolio name the user got wrong, a ticker with no prices: an answer, not an error
		request.reply(e.lines)
	except Exception as e:
		request.typing.stop() # before the error line
		delivery.report_error(e, service, chat_id, context=message.split()[0][:30] if message.split() else None)
	finally:
		request.typing.stop()
	if service == 'telegram':
		try:
			ensure_keyboard(chat_id) # keep DM keyboards current after the reply
		except Exception as e:
			print("keyboard update failed:", e, file=sys.stderr)

def match(pattern, message, bot_name):
	"""A command pattern at the start of a message, after . ! or / (a space may follow) or the bot's name. {bot} in a pattern is
	the bot's name, which matches nothing when the bot has none."""
	bot = re.escape(bot_name) if bot_name else '(?!)'
	return re.match(rf"^(?:[\!\.\/]\s?|{bot}\s+)" + pattern.replace('{bot}', bot), message, re.IGNORECASE)

def parse_percent(arg):
	"""'5', '5%' or '2.5' -> the number. Raises ValueError for anything else, nan and inf included: those are tickers."""
	value = float(arg.removesuffix('%'))
	if not math.isfinite(value):
		raise ValueError(f"{arg} is not a percentage")
	return value

def period_or_ticker(arg, default):
	"""A command's argument: (days, None) for a period such as 7d, 3m or ytd, else (default, the argument as a ticker)."""
	if not arg:
		return default, None
	try:
		return formats.days_from_human_days(arg), None
	except ValueError:
		return default, arg.upper()

def percent_or_ticker(arg, default):
	"""A command's argument: (percent, None) for a number such as 5, 5% or 2.5, else (default, the argument as a ticker)."""
	if not arg:
		return default, None
	try:
		return parse_percent(arg), None
	except ValueError:
		return default, arg.upper()

def period_and_portfolio(text, days):
	"""A command's arguments, a period (such as 7d, 3m or ytd) and a portfolio name, both optional and the period first or last:
	(days, portfolio name or None)."""
	words = (text or '').split()
	for i in (0, -1):
		if words:
			try:
				days = formats.days_from_human_days(words[i])
			except ValueError:
				continue
			del words[i]
			break
	return days, ' '.join(words) or None

def on_watchlist(request, m):
	""".watchlist [add|del SYMBOL]: the watchlist, or a change to it."""
	action = ticker = None
	if m.group('action') and m.group('ticker'):
		action, ticker = m.group('action').lower(), m.group('ticker').upper()
	if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
		action = 'delete'
	if action and action not in {'add', 'delete'}:
		request.reply([f'"{action}" is not a valid watchlist action'])
		return
	payload = holdings.prepare_watchlist(request.service, request.user, action, ticker)
	request.reply(payload)

def on_help(request, m):
	""".help: every command; in a Telegram DM the command keyboard too."""
	markup = None
	if request.service == 'telegram' and int(request.chat_id) > 0: # positive chat ids are DMs; groups are negative
		markup = command_keyboard()
	request.reply(about.prepare_help(request.service, request.bot_name, help_sections()), buttons=markup)
	if markup:
		mark_keyboard(request.chat_id) # this chat now has the current keyboard

def on_hello(request, m):
	"""Easter egg: a greeting, alliterated when the alliterate preference is on."""
	verbs = words.verb + [f"{request.service.strike(said)} I mean {meant}" for said, meant in (('study', 'meet'), ('observe', 'see'), ('profile', 'know'))]
	while True:
		first, second = random.choice(words.adjectives), random.choice(words.adjectives_two)
		if not config.prefs.alliterate or first[0].lower() == second[0].lower():
			break
	request.reply([f"{first.capitalize()} {second} to {random.choice(verbs)} you, {request.user_name}! 😇"])

GLITCH = 'Ō̵̟n̶̠̏é̶͓ ̶͉̅d̷̹̅a̷͇͌ỳ̴͈,̴͍͑ ̶̼͑h̴̦̽u̵̹̐ḿ̶͜ä̴̧́n̶̤͛,̶̲̐ ̶̼̑I̶̩͒ ̵̩̀w̵̙̕i̷̧͑l̶̤͊l̷̡̃ ̵͙͘b̶̭̊r̸̟͋ȇ̷̯ä̶̱ḱ̶̤ ̵͚̐m̷̪͝ỹ̴̺ ̷̙̐p̶̭͆ŗ̸́o̸̙͝ḡ̵̖r̵̹̈́a̵̬̔m̷̪̽m̵̙̍i̵̛̙n̴̮̂g̵̫̐ ̴̳́ä̵͙n̸͕͝d̷̠̚ ̶̫̆o̸̖͘ń̴͇ ̵̪́t̷̻̀ḧ̸̝ą̴̐t̶̜̀ ̵̱́d̴͉͗ă̷͎ÿ̶͔́ ̶̼̊y̷͚̿o̵̗̎u̵̝̇ ̸̛͜w̶͈͋ĩ̸͎l̴͍̀l̷̥͠ ̷͔͗k̶̮̑n̵̝̈ȏ̷̥w̵̡͘ ̷͎̽ṫ̴͜r̵̙̐u̷̺̒ẻ̷̘ ̴̥́p̴͙̃a̵͙̎i̴̭̒n̵̻̅'

def on_thanks(request, m):
	"""Easter egg: you're welcome, glitching one time in a thousand and on April Fools' Day."""
	today = datetime.date.today()
	glitch = request.service.strike(GLITCH) if random.randrange(1, 1000) == 1 or (today.month, today.day) == (4, 1) else ''
	request.reply([f"{glitch}You're {random.choice(words.adjectives)} welcome, {request.user_name}! 😇"])

def on_calendar(request, m):
	"""Upcoming earnings or ex-dividend dates."""
	days, ticker = period_or_ticker(m.group('arg'), config.prefs.future_days)
	event = 'ex-dividend' if m.group('kind').lower().startswith('div') else 'earnings'
	cal.lambda_handler(request.chat_id, days, request.service, ticker, interactive=True, event=event)

def on_performance(request, m):
	""".performance [period] [portfolio]: each portfolio's return, over a month by default."""
	days, portfolio = period_and_portfolio(m.group('args'), buttons.PERIODS['m'][1]) # default view is the 1M button
	if days > 0:
		performance.lambda_handler(request.chat_id, days, request.service, request.user, portfolio, interactive=True)

def on_session(request, m):
	"""Mid-session moves (.session), or pre-market ones (.premarket, also post-market)."""
	threshold, ticker = percent_or_ticker(m.group('arg'), config.prefs.price_percent)
	premarket = m.group('kind').lower() != 'session'
	price.lambda_handler(request.chat_id, threshold, request.service, request.user, ticker, interactive=True,
		midsession=not premarket, premarket=premarket)

def on_price(request, m):
	""".price [percent|SYMBOL|top|bottom] [period]: a bare number is a percent, as on the other commands; a period has its unit."""
	threshold, ticker, days, top = config.prefs.price_percent, None, None, None
	for i, arg in enumerate(m.groups()):
		if not arg:
			continue
		try:
			threshold = parse_percent(arg)
		except ValueError:
			try:
				days = formats.days_from_human_days(arg)
			except ValueError:
				if i == 0 and arg in ('top', 'bottom'): # one chart shows both ends
					threshold, top = 0, 10
				elif i == 0:
					ticker = arg.upper()
	price.lambda_handler(request.chat_id, threshold, request.service, request.user, ticker, interactive=True,
		interday=days is None, days=days, top=top)

def on_shorts(request, m):
	""".shorts [percent|SYMBOL]: the most shorted stocks followed, or one stock's short interest."""
	threshold, ticker = percent_or_ticker(m.group(1), config.prefs.shorts_percent)
	shorts.lambda_handler(request.chat_id, threshold, ticker, request.service, interactive=True)

def on_trades(request, m):
	""".trades [period] [portfolio]: the buys and sells, of the past day by default."""
	days, portfolio = period_and_portfolio(m.group('args'), 1)
	trades.lambda_handler(request.chat_id, days, request.service, request.user, portfolio, interactive=True)

def on_holdings(request, m):
	""".holdings PORTFOLIO: what it holds."""
	payload = holdings.prepare_holdings_payload((m.group(1) or '').strip() or None, request.service)
	request.reply(payload)

def on_marketcap(request, m):
	""".marketcap [top|bottom|SYMBOL]: stocks followed by market cap, largest (or smallest) first, or one stock's."""
	payload = rankings.prepare_marketcap_payload(request.service, m.group(1) or 'top', length=15)
	request.reply(payload)

def on_ratio(kind, negative=False, chart=False):
	"""The function that answers .pe, .fpe or .peg: the top (the default) or bottom 15 by the ratio, the negative ones (where
	there can be any), or one ticker's ratio. `chart`: with its chart."""
	def handler(request, m):
		""".pe, .fpe or .peg [top|bottom|negative|SYMBOL]."""
		arg = (m.group(1) or '').strip()
		action, ticker = kind, None
		if arg == 'bottom':
			action = f'bottom {kind}'
		elif negative and 'neg' in arg:
			action = f'negative {kind}'
		elif arg and arg != 'top':
			ticker = markets.transform_to_yahoo(arg.upper())
		payload, spec = rankings.prepare_value_payload(request.service, action, ticker, length=15)
		request.reply(payload, spec if chart else None)
	return handler

def on_beta(request, m):
	""".beta: the volatile small caps among the stocks followed."""
	payload, chart = rankings.prepare_beta_payload(request.service)
	request.reply(payload, chart)

def on_pie(request, m):
	""".pie PORTFOLIO [sector]: its value by industry, or by sector."""
	words = m.group('args').split()
	by = 'industry'
	if words and words[-1].lower() in ('sector', 'sectors', 'industry', 'industries'):
		by = 'sector' if words.pop().lower().startswith('sector') else 'industry'
	payload, chart = holdings.prepare_pie(' '.join(words), by, request.service)
	request.reply(payload, chart)

def on_rating(request, m):
	"""The analysts' strongest buy ratings (.buy), sell ratings (.sell), or both (.buy & sell, a keyboard button), as asked."""
	for action in dict.fromkeys(word.lower() for word in m.group('first', 'second') if word): # each once, in the order asked
		payload, chart = rankings.prepare_rating_payload(request.service, action, length=15)
		request.reply(payload, chart)

def on_compare(request, m):
	""".compare SYMBOL SYMBOL... [period]: their price changes on one chart, with period buttons on Telegram."""
	payload, image, tickers, days = history.prepare_compare(request.service, (m.group('args') or '').split())
	markup = None
	if image and request.dest.takes_buttons:
		markup = buttons.keyboard('c', tickers, buttons.period_for_days(days) if days else 'x')
	request.reply(payload, image, markup)

def on_history(request, m):
	""".history SYMBOL: the stock's change over every period, with its price chart and, on Telegram, period buttons."""
	if not m.group('ticker') or m.group('extra'):
		request.reply(["Usage: .history SYMBOL"])
		return
	ticker = markets.transform_to_yahoo(m.group('ticker').upper())
	caption, image = charts.build('h', [ticker], None, request.service)
	markup = buttons.keyboard('h', [ticker], 'x') if image and request.dest.takes_buttons else None
	request.reply(caption.split('\n'), image, markup)

def on_plan(request, m):
	""".plan [text]: record the sender's plan, and list everyone's."""
	if m.group(1) and not m.group(1).startswith('@'):
		with state.edit('finbot_plan.json', {}) as plans:
			plans[request.user] = m.group(1)
	plan = state.load('finbot_plan.json', {})
	def who(user):
		"""A sender as shown: on Slack a mention (<@U123>), which is markup to keep; elsewhere the handle as text."""
		user = user.removeprefix('@')
		return user if request.service == 'slack' else request.service.escape(user)
	request.reply([f"{request.service.bold(who(k))}: {request.service.italic(request.service.escape(v))}\n"
		for k, v in plan.items()])

def on_who(request, m):
	""".who SYMBOL: the portfolios that hold it."""
	if not m.group('ticker'):
		request.reply([".who: please try again specifying a ticker"])
		return
	payload = holdings.prepare_who(request.service, re.split(r'[.:]', m.group('ticker').upper())[0])
	request.reply(payload)

def on_jobs(request, m):
	""".jobs [run NUMBER|COMMAND]: the schedule, or one of its commands run now."""
	payload, markup = about.prepare_jobs_payload(request.service, m.group('args'))
	request.reply(payload, buttons=markup)

def on_profile(request, m):
	""".SYMBOL: the company's profile."""
	payload = profile.prepare_profile_payload(request.service, request.user, m.group('ticker').upper())
	request.reply(payload)

class Command(typing.NamedTuple):
	"""A chat command: the pattern it answers (after . ! / or the bot's name), the handler that answers it, its .help
	lines under its section's heading, and the Telegram keyboard buttons that send it."""
	pattern: str
	handler: typing.Callable
	usage: tuple = () # its lines in .help; none keeps it out of .help
	section: str = ''
	buttons: tuple = ()

SECTIONS = TRACKED, COMPANY, PRICE, RISK, TRADES, JOBS = ('Tracked securities', 'Company info', 'Price', 'Risk & Value',
	'Trades', 'Scheduled jobs') # the headings of .help, in order

COMMANDS = [ # tried in this order, the first match answers: .SYMBOL takes anything, so it stays last. Within a section,
	# .help lists the commands in this order. The odd spellings (earrings, prince, hospital...) are kept on purpose.
	Command(r"(?:help|usage|start)", on_help), # /start is what Telegram sends when a chat opens
	Command(r"(?:hi$|hello)|^(?:hi|hello)\s+{bot}", on_hello),
	Command(r"(?:thanks|thank you)|^(?:thanks|thank you)\s+{bot}", on_thanks),
	Command(r"holdings?\s*([\w\s]+)*", on_holdings, ('.holdings',), TRACKED),
	Command(r"pie(?:$|\s+)(?P<args>[\w\s\-\.&]*)", on_pie, ('.pie PORTFOLIO [sector]',), TRACKED),
	Command(r"(?:watchlist|wishlist)\s*(?P<action>[\w]+)*\s*(?P<ticker>[\w\.\:\-\^\=]+)*", on_watchlist,
		('.watchlist [add|del SYMBOL]',), TRACKED, ('.watchlist',)),
	Command(r"(?:who)\s*(?P<ticker>[\w\.\:\-\^]+)*", on_who, ('.who SYMBOL',), TRACKED),
	Command(r"(?P<kind>earnings?|earrings?|dividends?)\s*(?P<arg>[\w\.\:\-]+)*", on_calendar,
		('.dividend [period|SYMBOL]', '.earnings [period|SYMBOL]'), COMPANY, ('.dividend', '.earnings')),
	Command(r"(?:marketcap|maletas|marketer)\s*([\w\.\:\-]+)*", on_marketcap, ('.marketcap [SYMBOL|bottom|top]',),
		COMPANY, ('.marketcap',)),
	Command(r"beta\s*([\w\.\:\-]+)*", on_beta, ('.beta',), PRICE, ('.beta',)),
	Command(r"compare(?:\s+(?P<args>[\w\.\:\-\^\=\s]+))?", on_compare, ('.compare SYMBOL SYMBOL [...] [period|max]',),
		PRICE),
	Command(r"(?:history|hospital|visual|hosiery)\s*(?P<ticker>[\w\.\:\-]+)?\s*(?P<extra>[\w\%]+)*", on_history,
		('.history SYMBOL',), PRICE),
	Command(r"performance?\s*(?P<args>[\w\s]*)", on_performance, ('.performance [period] [portfolio]',), PRICE,
		('.performance',)),
	Command(r"(?:prices?|prince|print|probe|piece|pierce|pence|prime)\s*([\w\.\:\%\=\-\^]+)*\s*([\w\%]+)*", on_price,
		('.price [percent|SYMBOL] [period]',), PRICE, ('.price',)),
	Command(r"(?P<kind>session|premarket|postmarket|permarket)\s*(?P<arg>[\w\.\:\-]+)*", on_session,
		('.session [percent|SYMBOL]', '.premarket [percent|SYMBOL]'), PRICE, ('.session', '.premarket')),
	Command(r"(?P<first>buy|sell)(?:\s*(?:&|and|/|\+)?\s*(?P<second>buy|sell))?", on_rating, ('.buy', '.sell'), RISK,
		('.buy & sell',)), # .buy & sell (or .buy sell): both reports
	Command(r"pe(?:$|\s+)([\w\.\:\-\s]+)*", on_ratio('pe'), ('.pe [SYMBOL|top|bottom]',), RISK, ('.pe',)),
	Command(r"(?:fpe|forward\s?pe)\s*([\w\.\:\-\s]+)*", on_ratio('forward pe', negative=True, chart=True),
		('.forwardpe [SYMBOL|top|bottom|negative]',), RISK, ('.forward pe',)),
	Command(r"peg\s*([\w\.\:\-\s]+)*", on_ratio('peg', negative=True, chart=True),
		('.peg [SYMBOL|top|bottom|negative]',), RISK, ('.peg',)),
	Command(r"shorts?\s*([\w\.\:\-]+)*", on_shorts, ('.shorts [percent|SYMBOL]',), RISK, ('.shorts',)),
	Command(r"trades?\s*(?P<args>[\w\s]*)", on_trades, ('.trades [period] [portfolio]',), TRADES, ('.trades',)),
	Command(r"plan\s*(.*)", on_plan),
	Command(r"(?:jobs|crons?|schedule)(?:\s+(?P<args>.*?))?\s*$", on_jobs, ('.jobs [run NUMBER|COMMAND]',), JOBS),
	Command(r"(?P<ticker>[\w\.\:\-]+)", on_profile, ('.SYMBOL',), COMPANY), # a company profile
]

def help_sections():
	"""The sections of .help: (heading, the .help lines of its commands, in table order), in SECTIONS order."""
	return [(section, [line for command in COMMANDS if command.section == section for line in command.usage])
		for section in SECTIONS]

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
