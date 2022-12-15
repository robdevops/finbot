#!/usr/bin/python3

import json, time
import requests

from lib.config import *
import lib.sharesight as sharesight
import lib.util as util

def write(service, url, payload, slackchannel=False):
    headers = {'Content-type': 'application/json'}
    payload = {'text': payload}
    if 'slack.com' in url:
        headers = {**headers, **{'unfurl_links': 'false', 'unfurl_media': 'false'}} # FIX python 3.9
        if slackchannel:
            headers = {**headers, **{'Authorization': 'Bearer ' + config_slackToken}} # FIX python 3.9
            payload = {**payload, **{'channel': slackchannel}} # FIX python 3.9
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

def payload_wrapper(service, url, payload, slackchannel=False):
    if len(payload) > 1: # ignore header
        payload_string = ('\n'.join(payload))
        #print("Service: "+ service + ". Bytes: " + str(len(payload_string)) + ". Payload: " + payload_string)
        print("Service: "+ service + ". Bytes: " + str(len(payload_string)))
        if service == 'discord' and len(payload_string) > 2000:
            print(service, "payload is over 2,000 bytes. Splitting.")
            chunks = util.chunker(payload, config_chunk_maxlines)
            for payload_chunk in chunks:
                payload_chunk = '\n'.join(payload_chunk)
                write(service, url, payload_chunk)
                time.sleep(1) # workaround potential API throttling
        if service != 'discord' and len(payload_string) > 4000:
            print(service, "payload is over 4,000 bytes. Splitting.")
            chunks = util.chunker(payload, config_chunk_maxlines)
            for payload_chunk in chunks:
                payload_chunk = '\n'.join(payload_chunk)
                write(service, url, payload_chunk)
                time.sleep(1) # workaround potential API throttling
        else:
            write(service, url, payload_string, slackchannel)
    else:
        print("Nothing to send")

def bold(message, service):
    if service == 'telegram':
        message = '<b>' + message + '</b>'
    elif service == 'slack':
        message = '*' + message + '*'
    elif service == 'discord':
        message = '**' + message + '**'
    return message

