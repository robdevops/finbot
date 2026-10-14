"""Outbound HTTP. Every request goes through one session, so repeated calls to a host reuse its connection instead of paying a
new TCP and TLS handshake each time: each typing notice and reply, each Yahoo ticker, each Sharesight report.

The session keeps no cookies, so requests stay as stateless as they were without it. Yahoo's cookie travels in an explicit Cookie
header; and the request that asks fc.yahoo.com for a new cookie must not carry the old one, or Yahoo would not set a new one."""
import http.cookiejar
import re
import requests

session = requests.Session()
session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[])) # no domain may set or receive a cookie

def get(url, **kwargs):
	return session.get(url, **kwargs)

def post(url, **kwargs):
	return session.post(url, **kwargs)

def redact(text):
	"""text (or an exception) without the secrets that request URLs, headers and error messages carry: Telegram bot tokens,
	Slack and Discord webhook paths, bearer tokens, and token, crumb, key, secret and auth parameters."""
	text = re.sub(r'bot\d+:[\w-]+', 'bot<redacted>', str(text))
	text = re.sub(r'(/services/|/api/webhooks/)[^\s\'"?&]+', r'\1<redacted>', text)
	text = re.sub(r'(?i)(bearer\s+)[\w.~+/=-]+', r'\1<redacted>', text)
	return re.sub(r'(?i)(token|crumb|auth\w*|key|secret)=[^&\s\'"]+', r'\1=<redacted>', text)
