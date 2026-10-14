"""Chat commands: a message is answered by the function of the first pattern in COMMANDS that fits it."""
import dataclasses
import datetime
import math
import random
import re
import sys
import threading
from lib.config import *
from lib import util
from lib import webhook
from lib import reports
from lib import charts
from lib import telegram
from lib import sharesight
from lib import jobs
import cal
import performance
import price
import shorts
import trades

class TypingIndicator:
	"""Telegram's "typing…" while a with block runs, sent again every 7 seconds, at most max_loops times. It stops however the block
	ends, so a command that fails stops it before its error line goes out. Only Telegram has one: elsewhere it does nothing."""
	def __init__(self, service, chat_id, max_loops=3):
		self.service = service
		self.chat_id = chat_id
		self.max_loops = max_loops
		self._stop_event = threading.Event()
		self._thread = None

	def _worker(self):
		loop_count = 0
		while not self._stop_event.is_set() and loop_count < self.max_loops:
			webhook.pleaseHold('typing', self.service, self.chat_id)
			loop_count += 1
			if self._stop_event.wait(7):
				print("Stopping typing indicator", file=sys.stderr)
				break

	def start(self):
		if self.service != 'telegram':
			return
		self._thread = threading.Thread(target=self._worker, daemon=True)
		self._thread.start()

	def stop(self):
		if not self._thread: # never started: only Telegram has a typing indicator
			return
		self._stop_event.set()
		self._thread.join()

	def is_active(self):
		return self._thread is not None and self._thread.is_alive()

	def __enter__(self):
		self.start()
		return self

	def __exit__(self, *exc):
		self.stop()

@dataclasses.dataclass
class Request:
	"""A chat message being answered: where it came from and who sent it."""
	service: str
	chat_id: str
	user: str # the sender's handle: whose watchlist add or plan it is
	user_name: str # what to call them
	bot_name: str

	@property
	def url(self):
		return webhook.chat_url(self.service, self.chat_id)

	def typing(self, max_loops=3):
		return TypingIndicator(self.service, self.chat_id, max_loops)

	def say(self, payload, reply_markup=None):
		webhook.payload_wrapper(self.service, self.url, payload, self.chat_id, reply_markup=reply_markup)

	def send(self, payload, image=None, reply_markup=None):
		"""A report: its image, when there is one, with the text as caption (reply_markup is the image's buttons), else the text."""
		webhook.send(self.service, self.url, self.chat_id, payload, image, reply_markup)

	def deliver(self, payload, chart=None):
		"""A report and its chart spec: the chart drawn, with the text as caption, where the service can take an image
		(webhook.takes_charts), else the text."""
		if not (chart and chart.get('rows') and webhook.takes_charts(self.service)):
			self.say(payload)
			return
		spec = dict(chart)
		rows, title, subtitle = spec.pop('rows'), spec.pop('title'), spec.pop('subtitle', '')
		image = util.pie_chart(rows, title, subtitle) if spec.pop('pie', False) else util.rows_chart(rows, title, subtitle, **spec)
		webhook.sendPhoto(self.chat_id, image, '\n'.join(payload) if payload else title, self.service)

def process_job_callback(service, callback_id, chat_id, message_id, data):
	"""A command button of .jobs: run that command now and answer in the chat."""
	try:
		_, number, crc = data.split('|') # only a command offered by .jobs can be picked; anything else is refused
		command = jobs.current.pick(number, crc)
	except (ValueError, jobs.ScheduleError, AttributeError):
		telegram.answerCallbackQuery(callback_id, 'Buttons updated, try again')
		payload, markup = reports.prepare_jobs_payload(service, '') # the list as it is now, in place of the stale one
		webhook.editMessageText(chat_id, message_id, '\n'.join(payload), markup or {'inline_keyboard': []})
		return
	telegram.answerCallbackQuery(callback_id, f'Running {jobs.display(command[0])}…'[:100])
	try:
		webhook.payload_wrapper(service, webhook.chat_url(service, chat_id), [reports.job_line(jobs.current, *jobs.current.run_command(command))], chat_id)
	except Exception as e:
		webhook.report_error(e, service, chat_id, context='jobs')

def process_callback(service, callback_id, chat_id, message_id, data):
	"""Button press: run a scheduled command from .jobs, or rebuild a chart message for the chosen period and edit it in place."""
	if data.startswith('j|'):
		return process_job_callback(service, callback_id, chat_id, message_id, data)
	parts = data.split('|', 3)
	valid = len(parts) == 4 and parts[0] == 'c' and parts[1] in charts.BUTTONS and parts[2] in charts.BUTTONS[parts[1]]
	# answering now shows Telegram's toast bubble ("Loading 3M…") while the new chart is built
	telegram.answerCallbackQuery(callback_id, f"Loading {charts.PERIODS[parts[2]][0]}…" if valid else None)
	if not valid:
		return
	try:
		_, kind, period, ref = parts
		tickers = charts.resolve(ref)
		caption, image = charts.build(kind, tickers, period, service)
		webhook.editMessageMedia(chat_id, message_id, image, caption, charts.keyboard(kind, tickers, period))
	except Exception as e:
		webhook.report_error(e, service, chat_id, context='chart')

def process_request(service, chat_id, user, message, botName, userRealName, message_id):
	"""Entry point for inbound chat requests: the first command in COMMANDS that fits the message answers it (a message that fits
	none gets no answer). Any failure becomes a one-line reply in the originating chat, after the typing stops."""
	request = Request(service, chat_id, user, userRealName, botName)
	try:
		for pattern, handler in COMMANDS:
			if m := match(pattern, message, botName):
				handler(request, m)
				break
	except sharesight.PortfolioNotFound as e: # a name the user got wrong: an answer, not an error
		request.say(e.lines)
	except Exception as e:
		webhook.report_error(e, service, chat_id, context=message.split()[0][:30] if message.split() else None)
	if service == 'telegram':
		try:
			charts.ensure_keyboard(chat_id) # keep DM keyboards current after the reply
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
		return util.days_from_human_days(arg), None
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
				days = util.days_from_human_days(words[i])
			except ValueError:
				continue
			del words[i]
			break
	return days, ' '.join(words) or None

def on_watchlist(request, m):
	action = ticker = None
	if m.group('action') and m.group('ticker'):
		action, ticker = m.group('action').lower(), m.group('ticker').upper()
	if action in {'del', 'rem', 'rm', 'delete', 'remove'}:
		action = 'delete'
	if action and action not in {'add', 'delete'}:
		request.say([f'"{action}" is not a valid watchlist action'])
		return
	with request.typing():
		payload = reports.prepare_watchlist(request.service, request.user, action, ticker)
	request.say(payload)

def on_help(request, m):
	markup = None
	if request.service == 'telegram' and int(request.chat_id) > 0: # positive chat ids are DMs; groups are negative
		markup = charts.command_keyboard()
	request.say(reports.prepare_help(request.service, request.bot_name), reply_markup=markup)
	if markup:
		charts.mark_keyboard(request.chat_id) # this chat now has the current keyboard

def on_hello(request, m):
	"""Easter egg: a greeting, alliterated when config_alliterate is on."""
	verbs = verb + [f"{webhook.strike(said, request.service)} I mean {meant}" for said, meant in (('study', 'meet'), ('observe', 'see'), ('profile', 'know'))]
	while True:
		first, second = random.choice(adjectives), random.choice(adjectives_two)
		if not config_alliterate or first[0].lower() == second[0].lower():
			break
	request.say([f"{first.capitalize()} {second} to {random.choice(verbs)} you, {request.user_name}! 😇"])

GLITCH = 'Ō̵̟n̶̠̏é̶͓ ̶͉̅d̷̹̅a̷͇͌ỳ̴͈,̴͍͑ ̶̼͑h̴̦̽u̵̹̐ḿ̶͜ä̴̧́n̶̤͛,̶̲̐ ̶̼̑I̶̩͒ ̵̩̀w̵̙̕i̷̧͑l̶̤͊l̷̡̃ ̵͙͘b̶̭̊r̸̟͋ȇ̷̯ä̶̱ḱ̶̤ ̵͚̐m̷̪͝ỹ̴̺ ̷̙̐p̶̭͆ŗ̸́o̸̙͝ḡ̵̖r̵̹̈́a̵̬̔m̷̪̽m̵̙̍i̵̛̙n̴̮̂g̵̫̐ ̴̳́ä̵͙n̸͕͝d̷̠̚ ̶̫̆o̸̖͘ń̴͇ ̵̪́t̷̻̀ḧ̸̝ą̴̐t̶̜̀ ̵̱́d̴͉͗ă̷͎ÿ̶͔́ ̶̼̊y̷͚̿o̵̗̎u̵̝̇ ̸̛͜w̶͈͋ĩ̸͎l̴͍̀l̷̥͠ ̷͔͗k̶̮̑n̵̝̈ȏ̷̥w̵̡͘ ̷͎̽ṫ̴͜r̵̙̐u̷̺̒ẻ̷̘ ̴̥́p̴͙̃a̵͙̎i̴̭̒n̵̻̅'

def on_thanks(request, m):
	"""Easter egg: you're welcome, glitching one time in a thousand and on April Fools' Day."""
	today = datetime.date.today()
	glitch = webhook.strike(GLITCH, request.service) if random.randrange(1, 1000) == 1 or (today.month, today.day) == (4, 1) else ''
	request.say([f"{glitch}You're {random.choice(adjectives)} welcome, {request.user_name}! 😇"])

def on_calendar(request, m):
	"""Upcoming earnings or ex-dividend dates."""
	days, ticker = period_or_ticker(m.group('arg'), config_future_days)
	event = 'ex-dividend' if m.group('kind').lower().startswith('div') else 'earnings'
	with request.typing():
		cal.lambda_handler(request.chat_id, days, request.service, ticker, interactive=True, event=event)

def on_performance(request, m):
	days, portfolio = period_and_portfolio(m.group('args'), charts.PERIODS['m'][1]) # default view is the 1M button
	if days > 0:
		with request.typing():
			performance.lambda_handler(request.chat_id, days, request.service, request.user, portfolio, interactive=True)

def on_session(request, m):
	"""Mid-session moves (.session), or pre-market ones (.premarket, also post-market)."""
	threshold, ticker = percent_or_ticker(m.group('arg'), config_price_percent)
	premarket = m.group('kind').lower() != 'session'
	with request.typing():
		price.lambda_handler(request.chat_id, threshold, request.service, request.user, ticker, interactive=True, midsession=not premarket, premarket=premarket)

def on_price(request, m):
	""".price [percent|SYMBOL|top|bottom] [period]: a bare number is a percent, as on the other commands; a period has its unit."""
	threshold, ticker, days, top = config_price_percent, None, None, None
	for i, arg in enumerate(m.groups()):
		if not arg:
			continue
		try:
			threshold = parse_percent(arg)
		except ValueError:
			try:
				days = util.days_from_human_days(arg)
			except ValueError:
				if i == 0 and arg in ('top', 'bottom'): # one chart shows both ends
					threshold, top = 0, 10
				elif i == 0:
					ticker = arg.upper()
	with request.typing():
		price.lambda_handler(request.chat_id, threshold, request.service, request.user, ticker, interactive=True, interday=days is None, days=days, top=top)

def on_shorts(request, m):
	threshold, ticker = percent_or_ticker(m.group(1), config_shorts_percent)
	with request.typing():
		shorts.lambda_handler(request.chat_id, threshold, ticker, request.service, interactive=True)

def on_trades(request, m):
	days, portfolio = period_and_portfolio(m.group('args'), 1)
	with request.typing():
		trades.lambda_handler(request.chat_id, days, request.service, request.user, portfolio, interactive=True)

def on_holdings(request, m):
	with request.typing():
		payload = reports.prepare_holdings_payload((m.group(1) or '').strip() or None, request.service)
	request.say(payload)

def on_marketcap(request, m):
	with request.typing():
		payload = reports.prepare_marketcap_payload(request.service, m.group(1) or 'top', length=15)
	request.say(payload)

def on_ratio(kind, negative=False, chart=False):
	"""The function that answers .pe, .fpe or .peg: the top (the default) or bottom 15 by the ratio, the negative ones (where
	there can be any), or one ticker's ratio. `chart`: with its chart."""
	def handler(request, m):
		arg = (m.group(1) or '').strip()
		action, ticker = kind, None
		if arg == 'bottom':
			action = f'bottom {kind}'
		elif negative and 'neg' in arg:
			action = f'negative {kind}'
		elif arg and arg != 'top':
			ticker = util.transform_to_yahoo(arg.upper())
		with request.typing():
			payload, spec = reports.prepare_value_payload(request.service, action, ticker, length=15)
		request.deliver(payload, spec if chart else None)
	return handler

def on_beta(request, m):
	with request.typing():
		payload, chart = reports.prepare_beta_payload(request.service)
	request.deliver(payload, chart)

def on_pie(request, m):
	words = m.group('args').split()
	by = 'industry'
	if words and words[-1].lower() in ('sector', 'sectors', 'industry', 'industries'):
		by = 'sector' if words.pop().lower().startswith('sector') else 'industry'
	with request.typing():
		payload, chart = reports.prepare_pie(' '.join(words), by, request.service)
	request.deliver(payload, chart)

def on_rating(request, m):
	action = m.group(1).lower()
	with request.typing():
		payload, chart = reports.prepare_rating_payload(request.service, action, length=15)
	request.deliver(payload or [f"No stocks meet {action} criteria"], chart)

def on_compare(request, m):
	with request.typing():
		payload, image, tickers, days = reports.prepare_compare(request.service, (m.group('args') or '').split())
	markup = None
	if image and request.service == 'telegram':
		markup = charts.keyboard('c', tickers, charts.period_for_days(days) if days else 'x')
	request.send(payload, image, markup)

def on_history(request, m):
	if not m.group('ticker') or m.group('extra'):
		request.say(["Usage: .history SYMBOL"])
		return
	ticker = util.transform_to_yahoo(m.group('ticker').upper())
	with request.typing():
		caption, image = charts.build('h', [ticker], None, request.service)
	request.send(caption.split('\n'), image, charts.keyboard('h', [ticker], 'x') if image and request.service == 'telegram' else None)

def on_plan(request, m):
	plan = util.json_load('finbot_plan.json', persist=True) or {}
	if m.group(1) and not m.group(1).startswith('@'):
		plan[request.user] = m.group(1)
		util.json_write('finbot_plan.json', plan, persist=True)
	request.say([f"{webhook.bold(k.removeprefix('@'), request.service)}: {webhook.italic(v, request.service)}\n" for k, v in plan.items()])

def on_who(request, m):
	if not m.group('ticker'):
		request.say([".who: please try again specifying a ticker"])
		return
	with request.typing():
		payload = reports.prepare_who(request.service, re.split(r'[.:]', m.group('ticker').upper())[0])
	request.say(payload)

def on_jobs(request, m):
	with request.typing(max_loops=10):
		payload, markup = reports.prepare_jobs_payload(request.service, m.group('args'))
	request.say(payload, reply_markup=markup)

def on_profile(request, m):
	with request.typing():
		payload = reports.prepare_profile_payload(request.service, request.user, m.group('ticker').upper())
	request.say(payload)

COMMANDS = [ # (pattern, function): tried in this order, the first match answers. .SYMBOL takes anything, so it stays last
	(r"(?:watchlist|wishlist)\s*(?P<action>[\w]+)*\s*(?P<ticker>[\w\.\:\-\^\=]+)*", on_watchlist),
	(r"(?:help|usage|start)", on_help), # /start is what Telegram sends when a chat opens
	(r"(?:hi$|hello)|^(?:hi|hello)\s+{bot}", on_hello),
	(r"(?:thanks|thank you)|^(?:thanks|thank you)\s+{bot}", on_thanks),
	(r"(?P<kind>earnings?|earrings?|dividends?)\s*(?P<arg>[\w\.\:\-]+)*", on_calendar),
	(r"performance?\s*(?P<args>[\w\s]*)", on_performance),
	(r"(?P<kind>session|premarket|postmarket|permarket)\s*(?P<arg>[\w\.\:\-]+)*", on_session),
	(r"(?:prices?|prince|print|probe|piece|pierce|pence|prime)\s*([\w\.\:\%\=\-\^]+)*\s*([\w\%]+)*", on_price),
	(r"shorts?\s*([\w\.\:\-]+)*", on_shorts),
	(r"trades?\s*(?P<args>[\w\s]*)", on_trades),
	(r"holdings?\s*([\w\s]+)*", on_holdings),
	(r"(?:marketcap|maletas|marketer)\s*([\w\.\:\-]+)*", on_marketcap),
	(r"peg\s*([\w\.\:\-\s]+)*", on_ratio('peg', negative=True, chart=True)),
	(r"pe(?:$|\s+)([\w\.\:\-\s]+)*", on_ratio('pe')),
	(r"(?:fpe|forward\s?pe)\s*([\w\.\:\-\s]+)*", on_ratio('forward pe', negative=True)),
	(r"beta\s*([\w\.\:\-]+)*", on_beta),
	(r"pie(?:$|\s+)(?P<args>[\w\s\-\.&]*)", on_pie),
	(r"(buy|sell)", on_rating),
	(r"compare(?:\s+(?P<args>[\w\.\:\-\^\=\s]+))?", on_compare),
	(r"(?:history|hospital|visual|hosiery)\s*(?P<ticker>[\w\.\:\-]+)?\s*(?P<extra>[\w\%]+)*", on_history),
	(r"plan\s*(.*)", on_plan),
	(r"(?:who)\s*(?P<ticker>[\w\.\:\-\^]+)*", on_who),
	(r"(?:jobs|crons?|schedule)(?:\s+(?P<args>.*?))?\s*$", on_jobs),
	(r"(?P<ticker>[\w\.\:\-]+)", on_profile), # .SYMBOL: a company profile
]
