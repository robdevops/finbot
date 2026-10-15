#!/usr/bin/env python3

import googlesearch
import json
import time
import os

def get_symbols(file):
	"""The symbols in a file, one per line."""
	symbols = []
	with open(file) as file:
		while line := file.readline():
			symbol = line.rstrip()
			symbols.append(symbol)
	return symbols

def get_sws(symbol, market):
	"""The Simply Wall St page of a stock, found with Google's I'm Feeling Lucky."""
	query = "site:simplywall.st " + market + " " + symbol + " Stock Price, News & Analysis"
	url = googlesearch.lucky(query)
	print(symbol, url)
	return url

def build_dict(symbols, market):
	"""{symbol: its Simply Wall St page}, pausing 30 minutes after every 40 searches; ASX symbols get Yahoo's .AX."""
	count=1
	mydict = {}
	for symbol in symbols:
		if count % 40 == 0:
			print("Sleeping for 30 minutes")
			time.sleep(30 * 60)
		count = count + 1
		url = get_sws(symbol, market)
		if market == 'ASX':
			symbol = symbol + '.' + 'AX'
		mydict[symbol] = url
	return mydict

def do_sws_bulk(file):
	"""Look up a file's symbols (as ASX listings if its name says asx); write finbot_sws_<name>.json in the data dir."""
	market = ''
	if 'asx' in file or 'ASX' in file:
		market = 'ASX'
	symbols = get_symbols(file)
	mydict = build_dict(symbols, market)
	cache_file = 'finbot_sws_' + file.split('.')[0] + '.json'
	write_cache(mydict, (os.getenv('DATA_DIR') or 'var') + '/' + cache_file)
	return mydict

def write_cache(mydict, cache_file):
	"""Write the dict as JSON to cache_file, mode 0640."""
	os.umask(0)
	def opener(path, flags):
		"""open() that creates the file with mode 0640."""
		return os.open(path, flags, 0o640)
	with open(cache_file, "w", opener=opener, encoding="utf-8") as f:
		f.write(json.dumps(mydict))
	os.umask(0o022)

files = ['nasdaq100', 'sp500', 'asx200'] 
for idx, file in enumerate(files):
	print("Starting", file)
	mydict = do_sws_bulk(file)
	print("Completed", file, "as finbot_sws_" + file.split('.')[0] + ".json")
	if idx + 1 < len(files):
		print("Sleeping for 15 minutes")
		time.sleep(15 * 60)

