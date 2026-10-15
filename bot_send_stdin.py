#!/usr/bin/env python3

import sys
import os
from lib import delivery

if os.isatty(sys.stdin.fileno()):
	raise RuntimeError("No stdin input detected (not piped or redirected)")

payload = [line.strip() for line in sys.stdin if line.strip()]

for dest in delivery.default_chats():
	delivery.deliver(dest, delivery.Report(payload))

