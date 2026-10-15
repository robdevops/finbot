#!/usr/bin/env python3
"""./yahoo_warm.py [arguments]: runs lib/reports/yahoo_warm.py once, as its schedule line would."""
if __name__ == '__main__':
	from lib import reports
	reports.cli(__file__)
