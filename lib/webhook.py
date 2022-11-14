#!/usr/bin/python3

import json, os, time, re
import datetime
#from dotenv import load_dotenv
import pytz
import requests
from bs4 import BeautifulSoup

from lib.config import *
import lib.sharesight as sharesight
import lib.util as util

time_now = datetime.datetime.today()
today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
start_date = time_now - datetime.timedelta(days=config_trade_updates_past_days)
start_date = str(start_date.strftime('%Y-%m-%d')) # 2022-08-20

def write(service, url, payload):
    headers = {'Content-type': 'application/json'}
    payload = {'text': payload}
    if 'hooks.slack.com' in url:
        headers = {**headers, **{'unfurl_links': 'false', 'unfurl_media': 'false'}} # FIX python 3.9
    elif 'api.telegram.org' in url:
        payload = {**payload, **{'parse_mode': 'HTML', 'disable_web_page_preview': 'true', 'disable_notification': 'true'}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=config_http_timeout)
    except:
        print("Failure executing request:", url, headers, payload)
        return False
    if r.status_code == 200:
        print(r.status_code, "success", service)
    else:
        print(r.status_code, "error", service)
        return False

def webhook_wrapper(service, url, chunks):
    count=0
    for payload_chunk in chunks: # workaround potential max length
        count=count+1
        payload_chunk = '\n'.join(payload_chunk)
        write(service, url, payload_chunk)
        if count < len(list(chunks)):
            time.sleep(1) # workaround potential API throttling

def payload_wrapper(service, url, payload):
    if len(payload) > 1: # ignore header
        print('\n'.join(payload))
        chunks = util.chunker(payload, 20)
        webhook_wrapper(service, url, chunks)
