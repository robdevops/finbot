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
        print(r.status_code, "OK outbound to", service)
    else:
        print(r.status_code, "error outbound to", service)
        return False

def payload_wrapper(service, url, payload, slackchannel=False):
    if not len(payload):
        print(service + ": Nothing to send")
    else:
        payload_string = ('\n'.join(payload))
        print("Preparing outbound to", service, str(len(payload_string)), "bytes")
        if debug:
            print("Payload: " + payload_string)
        def chunkLooper():
            chunks = util.chunker(payload, config_chunk_maxlines)
            for idx, chunk in enumerate(chunks):
                idx > 0 and time.sleep(1)
                payload_chunk = '\n'.join(chunk)
                write(service, url, payload_chunk)
        if service == 'discord' and len(payload_string) > 2000:
            print(service, "payload is over 2,000 bytes. Splitting.")
            chunkLooper()
        elif service != 'discord' and len(payload_string) > 4000:
            print(service, "payload is over 4,000 bytes. Splitting.")
            chunkLooper()
        else:
            write(service, url, payload_string, slackchannel)

def bold(message, service):
    if service == 'telegram':
        message = '<b>' + message + '</b>'
    elif service == 'slack':
        message = '*' + message + '*'
    elif service == 'discord':
        message = '**' + message + '**'
    return message

def italic(message, service):
    if service == 'telegram':
        message = '<i>' + message + '</i>'
    elif service == 'slack':
        message = '_' + message + '_'
    elif service == 'discord':
        message = '_' + message + '_'
    return message

def strike(message, service):
    if service == 'telegram':
        message = '<s>' + message + '</s>'
    elif service == 'slack':
        message = '~' + message + '~'
    elif service == 'discord':
        message = '~~' + message + '~~'
    return message

