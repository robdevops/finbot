#!/usr/bin/python3

import json, os, time, re
import datetime
#from dotenv import load_dotenv
import pytz
import requests
from bs4 import BeautifulSoup

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook

time_now = datetime.datetime.today()
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20

def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def transform_title(title):
        # shorten long names to reduce line wrap on mobile
        title = title.replace('First Trust NASDAQ Clean Edge Green Energy Index Fund', 'Clean Energy ETF')
        title = title.replace('Atlantica Sustainable Infrastructure', 'Atlantica Sustainable')
        title = title.replace('Advanced Micro Devices', 'AMD')
        title = title.replace('Flight Centre Travel', 'Flight Centre')
        title = title.replace('Global X ', '')
        title = title.replace('The ', '')
        title = title.replace(' Australian', ' Aus')
        title = title.replace(' Australia', ' Aus')
        title = title.replace(' Infrastructure', 'Infra')
        title = title.replace(' Manufacturing Company', ' ')
        title = title.replace(' Limited', ' ')
        title = title.replace(' Ltd', ' ')
        title = title.replace(' Holdings', ' ')
        title = title.replace(' Corporation', ' ')
        title = title.replace(' Incorporated', ' ')
        title = title.replace(' incorporated', ' ')
        title = title.replace(' Technologies', ' ')
        title = title.replace(' Technology', ' ')
        title = title.replace(' Enterprises', ' ')
        title = title.replace(' Ventures', ' ')
        title = title.replace(' Co.', ' ')
        title = title.replace(' Tech ', ' ')
        title = title.replace(' Company', ' ')
        title = title.replace(' Tech ', ' ')
        title = title.replace(' Group', ' ')
        title = title.replace(', Inc', ' ')
        title = title.replace(' Inc', ' ')
        title = title.replace(' Plc', ' ')
        title = title.replace(' plc', ' ')
        title = title.replace(' Index', ' ')
        title = title.replace(' .', ' ')
        title = title.replace(' ,', ' ')
        title = title.replace('  ', ' ')
        title = title.rstrip()
        return title

