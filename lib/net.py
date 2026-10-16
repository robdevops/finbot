"""Outbound HTTP. Every request goes through one session, so repeated calls to a host reuse its connection instead of
paying a new TCP and TLS handshake each time: each typing notice and reply, each Yahoo ticker, each Sharesight report.

The session keeps no cookies, so requests stay as stateless as they were without it. Yahoo's cookie travels in an
explicit Cookie header; and the request that asks fc.yahoo.com for a new cookie must not carry the old one, or Yahoo
would not set a new one."""
import http.cookiejar
import re
import requests

from lib import config
from lib import log

session = requests.Session()
# no domain may set or receive a cookie
session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
CONNECT_TIMEOUT = 5 # seconds to wait for a host to answer the connection: one that is down costs this, not http_timeout
SHOWN = 73 # bytes of a request's log line, at most: the method and URL, cut with an ellipsis (3 bytes in UTF-8)

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
	"""The request's arguments without `logged`; the request noted at INFO first, unless logged=False (Telegram's long
	polling, asked again and again): its method and URL, without secrets or the scheme, cut to SHOWN bytes."""
	if kwargs.pop('logged', True):
		line = f"{method} {redact(url).split('://', 1)[-1]}".encode()
		log.info(line.decode() if len(line) <= SHOWN else line[:SHOWN - 3].decode(errors='ignore') + '…')
	return kwargs

def timeouts(kwargs):
	"""The request's arguments with a timeout, unless it has its own: CONNECT_TIMEOUT to connect, then http_timeout for
	the answer."""
	return {'timeout': (CONNECT_TIMEOUT, config.prefs.http_timeout), **kwargs}

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
