import html
import json
import time
import requests
import re
import sys
import traceback

from lib import config
from lib import dialects
from lib import net
from lib import telegram

DISCORD_LIMIT = 2000 # characters in a Discord message
SUPPRESS_EMBEDS = 4 # Discord message flag: no link previews
NO_MENTIONS = {'parse': []} # Discord: text that looks like @everyone or a mention pings nobody

def discord_url(url):
	"""A Discord webhook URL that answers with the message posted (200) instead of an empty 204."""
	return url + ('&' if '?' in url else '?') + 'wait=true'

def write(service, url, payload_string, chat_id=None, reply_markup=None):
	headers = {'Content-type': 'application/json'}
	payload = {'text': payload_string}
	if service == 'discord': # the native webhook endpoint: Discord's Slack-compatible one takes no flags
		payload = {'content': payload_string, 'flags': SUPPRESS_EMBEDS, 'allowed_mentions': NO_MENTIONS}
		url = discord_url(url)
	elif 'slack.com' in url:
		payload['unfurl_links'] = False # no link previews: Slack reads these from the body, not the headers
		payload['unfurl_media'] = False
		if chat_id:
			if not config.env.slackBotToken:
				print(f"ERROR slack: a reply to channel {chat_id} needs slackBotToken in finbot.env; not sent", file=sys.stderr)
				return None
			headers['Authorization'] = 'Bearer ' + config.env.slackBotToken
			payload['channel'] = chat_id
	elif 'api.telegram.org' in url:
		payload['parse_mode'] = 'HTML'
		payload['disable_web_page_preview'] = 'true'
		payload['disable_notification'] = 'true'
		if reply_markup:
			payload['reply_markup'] = reply_markup # keyboard (Telegram only)
	try:
		r = net.post(url, headers=headers, json=payload, timeout=config.prefs.http_timeout)
	except Exception as e:
		print("Failure sending to", service + ":", net.redact(e), file=sys.stderr)
		return None
	if r.status_code == 200:
		print(r.status_code, "OK outbound to", service, file=sys.stderr)
		try:
			return r.json()
		except ValueError:
			return {}
	else:
		print(r.status_code, "error outbound to", service, file=sys.stderr)
		return None

def chat_url(service, chat_id):
	"""Outbound URL for posting to a chat."""
	if service == 'slack':
		return 'https://slack.com/api/chat.postMessage'
	if service == 'telegram':
		return config.env.webhooks['telegram'] + 'sendMessage?chat_id=' + str(chat_id)
	return config.env.webhooks.get(service)

def default_chats():
	"""Where a scheduled report goes: [(service, url, chat id)]. Telegram posts into telegramChatID (left out without one); Slack and
	Discord post through their incoming webhooks, which take no chat id. Raises RuntimeError when there is nowhere to post."""
	chats = [(dialects.TELEGRAM, chat_url(service, config.env.telegramChatID), config.env.telegramChatID) if service == 'telegram' else (dialects.of(service), url, None)
		for service, url in config.env.webhooks.items() if service != 'telegram' or config.env.telegramChatID]
	if not chats:
		raise RuntimeError('nowhere to post: finbot.env sets no telegramChatID, slack_webhook or discord_webhook')
	return chats

def destinations(interactive, service, chat_id):
	"""Where a report goes: back to the chat that asked for it (interactive), else to the default chats."""
	return [(dialects.of(service), chat_url(service, chat_id), chat_id)] if interactive else default_chats()

def send(service, url, chat_id, payload, image=None, reply_markup=None):
	"""A report: its chart with the text as caption when there is one (sendPhoto falls back to the text where a chart cannot go),
	else the text. reply_markup is the chart's buttons. Returns what payload_wrapper or sendPhoto did."""
	if image:
		return sendPhoto(chat_id, image, '\n'.join(payload), service, reply_markup=reply_markup)
	return payload_wrapper(service, url, payload, chat_id)

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

def report_error(e, service=None, chat_id=None, context=None):
	"""Send a one-line error summary to the initiating chat, else to every default channel in finbot.env. The line is escaped for
	Telegram (sent as HTML, which refuses a stray < such as the one in <redacted>) and Slack (which asks for the same escapes).
	Never raises: error reporting must not become a second failure."""
	try:
		line = error_line(e, context)
		print(line, file=sys.stderr)
		if isinstance(e, BaseException):
			print(net.redact(''.join(traceback.format_exception(e))), end='', file=sys.stderr) # request errors carry their URL
		for svc, url, chat in [(service, chat_url(service, chat_id), chat_id)] if service and chat_id else default_chats():
			if url:
				try:
					write(svc, url, line if svc == 'discord' else html.escape(line, quote=False), chat)
				except Exception as send_error:
					print("Failed to report error to", svc, ":", send_error, file=sys.stderr)
	except Exception as reporting_error:
		print("Failed to report error:", reporting_error, file=sys.stderr)

def guarded(context, func, *args, exit=True, **kwargs):
	"""Run a scheduled entry point; on failure report one line to the default channel, then exit non-zero (exit=True, for the
	command line) or just return None (exit=False, when the bot runs it in-process). A SystemExit inside counts as a failure."""
	try:
		return func(*args, **kwargs)
	except (Exception, SystemExit) as e:
		report_error(e, context=context)
		if exit:
			sys.exit(1)

def cli(script, job, handler, argv=None):
	"""Command line entry point of a report script: parse its arguments with `job(argv) -> (label, kwargs)`, print the usage on
	a bad argument, else run the handler guarded."""
	try:
		label, kwargs = job(sys.argv[1:] if argv is None else argv)
	except ValueError as e:
		print("Usage:", script, e, file=sys.stderr)
		sys.exit(1)
	guarded(label, handler, **kwargs)

def payload_wrapper(service, url, payload, chat_id=None, reply_markup=None):
	"""Returns a list with the response of each message sent (several if the payload was chunked)."""
	if not payload:
		return None
	payload = [str(line) for line in payload]
	payload_string = '\n'.join(payload)
	limit = DISCORD_LIMIT if service == 'discord' else 4096
	if len(payload_string) <= limit:
		return [write(service, url, payload_string, chat_id, reply_markup)]
	chunks = chunked(payload, limit, config.prefs.chunk_maxlines)
	results = []
	for idx, chunk in enumerate(chunks):
		if idx:
			time.sleep(0.5)
		last = idx == len(chunks) - 1
		results.append(write(service, url, '\n'.join(chunk), chat_id, reply_markup=reply_markup if last else None))
	return results

def chunked(lines, limit, max_lines):
	"""The lines in messages of at most max_lines lines and limit characters each, whichever comes first; a line longer than limit
	on its own is cut short."""
	chunks, current, size = [], [], 0
	for line in lines:
		if len(line) > limit:
			line = line[:limit - 1] + '…'
		if current and (len(current) >= max_lines or size + 1 + len(line) > limit):
			chunks.append(current)
			current, size = [], 0
		size += len(line) + (1 if current else 0)
		current.append(line)
	if current:
		chunks.append(current)
	return chunks

def fit_caption(caption, limit=1024, visible=None):
	"""Telegram rejects photo captions over 1024 visible characters; Discord takes 2,000 characters, markup included
	(visible=len). Keep whole lines that fit and say how many were left out."""
	if visible is None:
		def visible(text):
			return len(re.sub(r'<[^>]+>', '', text))
	if visible(caption) <= limit:
		return caption
	lines = caption.split('\n')
	kept = []
	for line in lines:
		more = len(lines) - len(kept) - 1
		note = f"\n…and {more} more in the chart"
		if visible('\n'.join(kept + [line])) + len(note) > limit:
			break
		kept.append(line)
	return '\n'.join(kept) + f"\n…and {len(lines) - len(kept)} more in the chart"

MAYBE_SENT = object() # a read timeout on the request that posts a chart: it may have arrived, so no text copy follows

def takes_charts(service, reply=True):
	"""Whether a report to `service` can carry a chart image: never with the graph preference off; on Telegram and Discord always;
	on Slack in a reply to a chat (`reply`), uploaded into its channel with the bot token, but not in a scheduled report, which goes
	through the incoming webhook and takes text only. Elsewhere a report goes out as text."""
	return config.prefs.graph and (service in ('telegram', 'discord') or (service == 'slack' and reply and bool(config.env.slackBotToken)))

def telegram_photo(chat_id, image_data, caption, reply_markup=None):
	"""sendPhoto, the report as its caption (trimmed to fit). Telegram's answer, MAYBE_SENT, or None if it was refused."""
	url = config.env.webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
	data = {
		'disable_notification': True,
		'chat_id': chat_id,
		'caption': fit_caption(caption),
		'parse_mode': 'HTML',
		'disable_web_page_preview': True}
	if reply_markup:
		data['reply_markup'] = json.dumps(reply_markup) # inline keyboard (Telegram only)
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	try:
		r = net.post(url, data=data, files={"photo": ('image.png', image_data)}, timeout=config.prefs.http_timeout)
	except requests.exceptions.ReadTimeout as e:
		print("Telegram sendPhoto timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
		return MAYBE_SENT
	except Exception as e:
		print("Telegram sendPhoto failed:", net.redact(e), file=sys.stderr)
		return None
	try:
		output = r.json()
	except ValueError:
		output = {}
	if r.status_code == 200 and output.get('ok'):
		return output
	print(r.status_code, "error telegram sendPhoto", output.get('error_code'), output.get('description') or r.text[:300], file=sys.stderr)
	return None

def discord_photo(image_data, caption):
	"""The chart on the Discord webhook, with the report as its message (trimmed to Discord's 2,000 characters), no link previews.
	Discord's answer, MAYBE_SENT, or None if it was refused."""
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	payload = {'content': fit_caption(caption, DISCORD_LIMIT, len), 'flags': SUPPRESS_EMBEDS, 'allowed_mentions': NO_MENTIONS,
		'attachments': [{'id': 0, 'filename': 'chart.png'}]}
	try:
		r = net.post(discord_url(config.env.webhooks['discord']), data={'payload_json': json.dumps(payload)},
			files={'files[0]': ('chart.png', image_data, 'image/png')}, timeout=config.prefs.http_timeout)
	except requests.exceptions.ReadTimeout as e:
		print("Discord chart timed out, it may still arrive:", net.redact(e), file=sys.stderr)
		return MAYBE_SENT
	except Exception as e:
		print("Discord chart failed:", net.redact(e), file=sys.stderr)
		return None
	if r.status_code == 200:
		print(r.status_code, "OK discord chart", file=sys.stderr)
		try:
			return r.json() or {}
		except ValueError:
			return {}
	print(r.status_code, "error discord chart", net.redact(r.text[:300]), file=sys.stderr)
	return None

def slack_api(method, **data):
	"""POST a Slack Web API method as the bot, form-encoded, and return its answer. Raises RuntimeError with Slack's error if not ok."""
	if not config.env.slackBotToken:
		raise RuntimeError(f"Slack {method}: needs slackBotToken in finbot.env")
	r = net.post('https://slack.com/api/' + method, headers={'Authorization': 'Bearer ' + config.env.slackBotToken}, data=data, timeout=config.prefs.http_timeout)
	try:
		output = r.json()
	except ValueError:
		output = {}
	if not output.get('ok'):
		raise RuntimeError(f"Slack {method}: {output.get('error') or r.status_code}")
	return output

def slack_photo(chat_id, image_data, caption):
	"""Upload the chart into a Slack channel with the report as its message, the way Slack takes files since it retired files.upload:
	ask for an upload URL, send the bytes there, then complete the upload into the channel (the bot needs the files:write and
	files:read scopes). Slack's answer, MAYBE_SENT, or None if a step failed."""
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	data = image_data.read() if hasattr(image_data, 'read') else bytes(image_data)
	try:
		ticket = slack_api('files.getUploadURLExternal', filename='chart.png', length=len(data))
		r = net.post(ticket['upload_url'], data=data, timeout=config.prefs.http_timeout)
		if r.status_code != 200:
			raise RuntimeError(f"Slack upload: {r.status_code} {r.text[:200]}")
		share = {'files': json.dumps([{'id': ticket['file_id']}]), 'channel_id': chat_id, 'initial_comment': caption}
		try:
			output = slack_api('files.completeUploadExternal', **share)
		except requests.exceptions.ReadTimeout as e:
			print("Slack files.completeUploadExternal timed out, the chart may still arrive:", net.redact(e), file=sys.stderr)
			return MAYBE_SENT
	except Exception as e:
		print("Slack chart upload failed:", net.redact(e), file=sys.stderr)
		return None
	print("OK slack chart upload to", chat_id, file=sys.stderr)
	return output

def sendPhoto(chat_id, image_data, caption, service, reply_markup=None):
	"""The chart, with the report as its caption: on Telegram, or uploaded into the Slack channel of a reply. Where a chart cannot go
	(takes_charts), or the service refuses it, the report is sent as text instead, without the chart's buttons, so it does not vanish
	with its chart; but not after a read timeout on the request that posts it, when the chart may have arrived after all."""
	output = None
	chartable = takes_charts(service, reply=bool(chat_id))
	if chartable and service == 'telegram':
		output = telegram_photo(chat_id, image_data, caption, reply_markup)
	elif chartable and service == 'discord':
		output = discord_photo(image_data, caption)
	elif chartable:
		output = slack_photo(chat_id, image_data, caption)
	if output is MAYBE_SENT:
		return None
	if output:
		return output
	if chartable:
		print("chart not sent, sending the report as text", file=sys.stderr)
	return payload_wrapper(service, chat_url(service, chat_id) if chat_id else config.env.webhooks.get(service), caption.split('\n'), chat_id)

def editMessageText(chat_id, message_id, text, reply_markup=None):
	"""Telegram: replace a text message's text and buttons in place. A failure is only logged."""
	payload = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
	if reply_markup is not None:
		payload['reply_markup'] = reply_markup
	telegram.try_call('editMessageText', json=payload)

def editMessageMedia(chat_id, message_id, image_data, caption, reply_markup=None):
	"""Telegram: replace a photo message's image and caption in place. Raises RuntimeError when Telegram refuses, unless the message
	is already so (pressing the active period again is harmless); a request that fails on the way is only logged."""
	media = {'type': 'photo', 'media': 'attach://photo', 'caption': fit_caption(caption), 'parse_mode': 'HTML'}
	data = {'chat_id': chat_id, 'message_id': message_id, 'media': json.dumps(media)}
	if reply_markup:
		data['reply_markup'] = json.dumps(reply_markup)
	if hasattr(image_data, 'seek'):
		image_data.seek(0)
	try:
		telegram.call('editMessageMedia', data=data, files={'photo': ('image.png', image_data)})
	except RuntimeError as e:
		if 'not modified' not in str(e):
			raise
	except Exception as e: # it may have arrived even so: no error line for something the chat may already show
		print("Telegram editMessageMedia failed:", net.redact(e), file=sys.stderr)

def pleaseHold(action, service, chat_id):
	"""Telegram's typing notice ("typing…" for a few seconds). worker.TypingIndicator repeats it every 7 seconds while a command
	works, on Telegram only: the other services have no such notice."""
	if service == 'telegram':
		telegram.try_call('sendChatAction', data={'chat_id': chat_id, 'action': action})
