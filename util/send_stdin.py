#!/usr/bin/env python3
"""Post the lines piped in to the home chats, as the scheduled reports go: `echo hello | util/send_stdin.py`."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import delivery


if __name__ == '__main__':
	if os.isatty(sys.stdin.fileno()):
		sys.exit('send_stdin: pipe the lines to post into it, e.g. echo hello | util/send_stdin.py')
	lines = [line.strip() for line in sys.stdin if line.strip()]
	for dest in delivery.default_chats():
		delivery.deliver(dest, delivery.Report(lines))
