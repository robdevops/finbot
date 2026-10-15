"""Outbound HTTP. Every request goes through one session, so repeated calls to a host reuse its connection instead of
paying a new TCP and TLS handshake each time: each typing notice and reply, each Yahoo ticker, each Sharesight report.

The session keeps no cookies, so requests stay as stateless as they were without it. Yahoo's cookie travels in an
explicit Cookie header; and the request that asks fc.yahoo.com for a new cookie must not carry the old one, or Yahoo
would not set a new one."""
import http.cookiejar
import re
import requests

from lib import config

session = requests.Session()
# no domain may set or receive a cookie
session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
CONNECT_TIMEOUT = 5 # seconds to wait for a host to answer the connection: one that is down costs this, not http_timeout

def get(url, **kwargs):
	"""requests.get through the shared session, which reuses connections; timed out as timeouts() says."""
	return session.get(url, **timeouts(kwargs))

def post(url, **kwargs):
	"""requests.post through the shared session, which reuses connections; timed out as timeouts() says."""
	return session.post(url, **timeouts(kwargs))

def timeouts(kwargs):
	"""The request's arguments with a timeout, unless it has its own: CONNECT_TIMEOUT to connect, then http_timeout for
	the answer."""
	return {'timeout': (CONNECT_TIMEOUT, config.prefs.http_timeout), **kwargs}

def redact(text):
	"""text (or an exception) without the secrets that request URLs, headers and error messages carry: Telegram bot
	tokens, Slack and Discord webhook paths, bearer tokens, and token, crumb, key, secret and auth parameters."""
	text = re.sub(r'bot\d+:[\w-]+', 'bot<redacted>', str(text))
	text = re.sub(r'(/services/|/api/webhooks/)[^\s\'"?&]+', r'\1<redacted>', text)
	text = re.sub(r'(?i)(bearer\s+)[\w.~+/=-]+', r'\1<redacted>', text)
	return re.sub(r'(?i)(token|crumb|auth\w*|key|secret)=[^&\s\'"]+', r'\1=<redacted>', text)
