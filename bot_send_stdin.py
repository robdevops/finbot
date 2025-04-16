#!/usr/bin/env python3

import sys
import os
from lib.config import *
from lib import util
from lib import webhook

if os.isatty(sys.stdin.fileno()):
	raise RuntimeError("No stdin input detected (not piped or redirected)")

payload = [line.strip() for line in sys.stdin if line.strip()]

if not webhooks:
	print("Error: no services enabled in .env", file=sys.stderr)
	sys.exit(1)
for service, url in webhooks.items():
	if service == "telegram":
		url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
	webhook.payload_wrapper(service, url, payload)

