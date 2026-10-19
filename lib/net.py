"""Outbound HTTP. Every request goes through one session, so repeated calls to a host reuse its connection instead of
paying a new TCP and TLS handshake each time: each typing notice and reply, each Yahoo ticker, each Sharesight report.

The session keeps no cookies, so requests stay as stateless as they were without it. Yahoo's cookie travels in an
explicit Cookie header; and the request that asks fc.yahoo.com for a new cookie must not carry the old one, or Yahoo
would not set a new one."""
import http.cookiejar
import re
import time

import requests

from lib import config
from lib import log

session = requests.Session()
# no domain may set or receive a cookie
session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
CONNECT_TIMEOUT = 5 # seconds to wait for a host to answer the connection: one that is down costs this, not http_timeout
RATE_LIMIT_WAIT = 30 # the longest a rate limit is waited out, in seconds: one that asks for longer is tried then


class RateLimited(RuntimeError):
	"""A refusal for a rate limit (a 429), and the seconds it asks to wait (retry_after)."""

	def __init__(self, message, wait):
		"""The refusal, as RuntimeError says it, and the wait it asks for."""
		super().__init__(message)
		self.wait = wait


def get(url, **kwargs):
	"""requests.get through the shared session, which reuses connections; timed out as timeouts() says; logged."""
	return session.get(url, **timeouts(logged('GET', url, kwargs)))

def post(url, **kwargs):
	"""requests.post through the shared session, which reuses connections; timed out as timeouts() says; logged."""
	return session.post(url, **timeouts(logged('POST', url, kwargs)))

def request(method, url, **kwargs):
	"""A request of any method through the shared session, which reuses connections; timed out as timeouts() says;
	logged."""
	return session.request(method, url, **timeouts(logged(method, url, kwargs)))

def logged(method, url, kwargs):
	"""The request's arguments without `logged`; the request noted first, its method and URL without secrets or the
	scheme, cut to the log_width setting (log.cut): at INFO; at DEBUG with logged='debug' (the routine of a press:
	its acknowledgement, the message edited in place); not at all with logged=False (Telegram's long polling, asked
	again and again)."""
	shown = kwargs.pop('logged', True)
	if shown:
		(log.debug if shown == 'debug' else log.info)(log.cut(f"{method} {redact(url).split('://', 1)[-1]}"))
	return kwargs

def timeouts(kwargs):
	"""The request's arguments with a timeout, unless it has its own: CONNECT_TIMEOUT to connect, then http_timeout for
	the answer."""
	return {'timeout': (CONNECT_TIMEOUT, config.settings.http_timeout), **kwargs}

def redact(text):
	"""text (or an exception) without the secrets that request URLs, headers and error messages carry: Telegram and
	Slack tokens, Slack and Discord webhook paths, Discord's bot and interaction tokens, bearer tokens, and token,
	crumb, key, secret and auth parameters."""
	text = re.sub(r'bot\d+:[\w-]+', 'bot<redacted>', str(text))
	text = re.sub(r'\bx(?:ox[a-z]|app)-[\w-]+', '<redacted>', text) # Slack's tokens
	text = re.sub(r'(/services/|/api/webhooks/)[^\s\'"?&]+', r'\1<redacted>', text)
	text = re.sub(r'(/(?:webhooks|interactions)/\d+/)[^\s\'"?&/]+', r'\1<redacted>', text) # Discord's API
	text = re.sub(r'\b[\w-]{23,28}\.[\w-]{6,7}\.[\w-]{27,}', '<redacted>', text) # a Discord bot token
	text = re.sub(r'(?i)(bearer\s+)[\w.~+/=-]+', r'\1<redacted>', text)
	return re.sub(r'(?i)(token|crumb|auth\w*|key|secret)=[^&\s\'"]+', r'\1=<redacted>', text)

def twice(send):
	"""send(), sent once more at once where its connection fails (requests.RequestException): a host closes a
	connection left idle, which fails the first request on it. For a question only: a post could arrive twice."""
	try:
		return send()
	except requests.RequestException:
		return send()

def patiently(send):
	"""send(), tried once more after the wait that a rate limit asks for (RateLimited; RATE_LIMIT_WAIT at most)."""
	try:
		return send()
	except RateLimited as e:
		wait = min(e.wait, RATE_LIMIT_WAIT)
		log.warn(f"{redact(e)}: rate limited, trying again in {wait:g} s")
		time.sleep(wait)
		return send()

def retry_after(response):
	"""The seconds a rate-limited answer asks to wait: its JSON's retry_after (Discord's; Telegram's in its
	parameters), else its Retry-After header (Slack's); one when it says none."""
	answer = json_of(response)
	for wait in (answer.get('retry_after'), (answer.get('parameters') or {}).get('retry_after'),
			getattr(response, 'headers', {}).get('Retry-After')):
		try:
			return float(wait)
		except (TypeError, ValueError):
			pass
	return 1.0

def ok_answer(response, what, reason):
	"""The answer of an API that says in it whether it is ok (Telegram's Bot API, Slack's Web API), as JSON. Raises
	RuntimeError naming what failed and the API's reason (the answer's `reason` field, else the HTTP status) when it
	is not ok: RateLimited for a 429, with the wait it asks for."""
	answer = json_of(response)
	if answer.get('ok'):
		return answer
	said = f"{what}: {answer.get(reason) or response.status_code}"
	if response.status_code == 429:
		raise RateLimited(said, retry_after(response))
	raise RuntimeError(said)

def answer(source, what, url, **kwargs):
	"""A data source's response (source: its name, Yahoo) to a request for `what`: a GET, or a POST where kwargs have
	data. A rate limit (a 429) that says how long to wait (Retry-After) is waited out once; any other answer is given
	back as it is, for the source to read. Raises RuntimeError, its secrets redacted and its cause chained, when the
	host cannot be reached (requests.RequestException: any other exception is a bug, raised as it is), or keeps up its
	rate limit."""
	send = post if 'data' in kwargs else get
	def sent():
		"""The response, or RateLimited for a 429 that asks for a wait."""
		try:
			response = send(url, **kwargs)
		except requests.RequestException as e:
			raise RuntimeError(f"{source} unreachable for {what}: {redact(e)}") from e
		if response.status_code == 429 and 'Retry-After' in response.headers:
			raise RateLimited(f"{source} {what}: rate limited", retry_after(response))
		return response
	return patiently(sent)

def json_answer(response, source, what):
	"""A data source's answer (source: its name) as JSON, whatever its status. Raises RuntimeError naming the source,
	`what` and the status for a body that is not JSON (an HTML error page)."""
	try:
		return response.json()
	except ValueError as e:
		raise RuntimeError(f"{source} {what}: a {response.status_code} answer that is not JSON") from e

def json_of(response):
	"""A response's JSON object, or {} for a body that is none."""
	try:
		answer = response.json()
	except ValueError:
		return {}
	return answer if isinstance(answer, dict) else {}
