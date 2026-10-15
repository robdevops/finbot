#!/usr/bin/env python3
"""./cleanup.py [arguments]: runs lib/reports/cleanup.py once, as its schedule line would."""
if __name__ == '__main__':
	from lib import reports
	reports.cli(__file__)
