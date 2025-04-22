import os
import json

def get_url(symbol, name, exchange):
	sws = {}
	files = ['finbot_sws_custom.json', 'finbot_sws_asx200.json', 'finbot_sws_sp500.json', 'finbot_sws_nasdaq100.json']
	for file in files:
		file = 'var/' + file
		sws = sws | read_cache(file)
	if symbol in sws:
		return sws[symbol]
	else:
		return 'https://www.google.com/search?q=site:simplywall.st+(' + name + '+' + exchange + ':' + symbol.split('.')[0] + ')+Stock&btnI'

def read_cache(cacheFile):
	if os.path.isfile(cacheFile):
		with open(cacheFile, "r", encoding="utf-8") as f:
			cacheDict = json.load(f)
		return cacheDict
	else:
		print("can't find", cacheFile)
		return {}

