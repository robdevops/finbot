#!/usr/bin/env python3
"""./performance.py [arguments]: runs lib/reports/performance.py once, as its schedule line would."""
if __name__ == '__main__':
	from lib import reports
	reports.cli(__file__)
