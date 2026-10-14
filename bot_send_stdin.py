#!/usr/bin/env python3

import sys
import os
from lib import webhook

if os.isatty(sys.stdin.fileno()):
	raise RuntimeError("No stdin input detected (not piped or redirected)")

payload = [line.strip() for line in sys.stdin if line.strip()]

for service, url, chat in webhook.default_chats():
	webhook.send(service, url, chat, payload)

