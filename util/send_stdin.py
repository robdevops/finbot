#!/usr/bin/env python3
"""Post the lines piped in to a chat, named by its key (its network and id), as a scheduled report goes:
`echo hello | util/send_stdin.py telegram:-1001234567890`."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import delivery

USAGE = 'send_stdin: pipe the lines to post into it, naming the chat: echo hello | util/send_stdin.py telegram:-100123'


if __name__ == '__main__':
	if len(sys.argv) != 2 or not sys.argv[1].partition(':')[2] or os.isatty(sys.stdin.fileno()):
		sys.exit(USAGE)
	try:
		dest = delivery.chat(sys.argv[1], scheduled=True)
	except ValueError as e:
		sys.exit(f'send_stdin: {e}')
	lines = [line.strip() for line in sys.stdin if line.strip()]
	delivery.deliver(dest, delivery.Report(lines))
