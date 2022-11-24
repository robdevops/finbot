#!/usr/bin/python3

import json, re

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util
import lib.yahoo as yahoo
import lib.finviz as finviz

tickers_us = ["ACMR"]
print(tickers_us)
finviz_output = finviz.wrapper(tickers_us)
print(finviz_output)
