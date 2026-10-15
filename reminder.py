#!/usr/bin/env python3
"""./reminder.py [arguments]: runs lib/reports/reminder.py once, as its schedule line would."""
if __name__ == '__main__':
	from lib import reports
	reports.cli(__file__)
