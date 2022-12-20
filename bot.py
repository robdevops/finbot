#!/usr/bin/python3

from gevent import pywsgi
from itertools import groupby
import datetime
import json, re, time
import threading
#from itertools import pairwise # python 3.10

from lib.config import *
import lib.telegram as telegram
import lib.worker as worker

def main(environ, start_response):
    def print_body():
        try:
            print(f"[{timestamp}]: inbound {uri}", json.dumps(inbound, indent=4))
        except Exception as e:
            print(e, "raw body: ", inbound)
    def print_headers():
        for item in sorted(environ.items()):
            print(item)
    request_body = environ['wsgi.input'].read()
    timestamp = datetime.datetime.today()
    timestamp = str(timestamp.strftime('%H:%M:%S')) # 2022-09-20
    user=''
    userRealName=''
    # prepare response
    status = '200 OK'
    headers = [('Content-type', 'application/json')]
    start_response(status, headers)
    # process request
    uri = environ['PATH_INFO']
    inbound = json.loads(request_body)
    if debug:
        print_headers()
        print_body()
    if uri == '/telegram':
        service = 'telegram'
        if 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' not in environ:
            print_headers()
            print("Fatal:", service, "authorisation header not present")
            return [b'<h1>Unauthorized</h1>']
        elif environ['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] == config_telegramOutgoingToken:
            print("Incoming request authenticated")
        else: 
            print_headers()
            print("Fatal: Telegram authorisation header is present but incorrect. Expected:", config_telegramOutgoingToken)
            return [b'<h1>Unauthorized</h1>']
        botName = '@' + telegram.getBotName()
        if "message" in inbound:
            if "text" in inbound["message"]:
                message = inbound["message"]["text"]
                chat_id = inbound["message"]["chat"]
                chat_id = str(chat_id["id"])
                if "username" in inbound["message"]["from"]:
                    user = '@' + inbound["message"]["from"]["username"]
                    userRealName = inbound["message"]["from"]["first_name"]
                else:
                    user = '@' + inbound["message"]["from"]["first_name"]
                print(f"[{timestamp} {service} {user}]:", message)
                # this condition spawns a worker before returning
            else:
                print(f"[{timestamp} {service}]: unhandled: 'message' without 'text'")
                return [b'<h1>Unhandled</h1>']
        elif "edited_message" in inbound:
            if "text" in inbound["edited_message"]:
                message = inbound["edited_message"]["text"]
                chat_id = inbound["edited_message"]["chat"]
                chat_id = str(chat_id["id"])
                if "username" in inbound["edited_message"]["from"]:
                    user = inbound["edited_message"]["from"]["username"]
                else:
                    user = inbound["edited_message"]["from"]["first_name"]
                print(f"[{timestamp} {service} {user} [edit]:", message)
                # this condition spawns a worker before returning
            else:
                print(f"[{timestamp} {service}]: unhandled: 'edited_message' without 'text'")
                return [b'<h1>Unhandled</h1>']
        elif "channel_post" in inbound:
            message = inbound["channel_post"]["text"]
            chat_id = inbound["channel_post"]["chat"]["id"]
            user = ''
            print(f"[{timestamp} {service}]:", message)
            # this condition spawns a worker before returning
        else:
            print(f"[{timestamp} {service}]: unhandled: not 'message' nor 'channel_post'")
            return [b'<h1>Unhandled</h1>']
    elif uri == '/slack':
        service = 'slack'
        if 'token' not in inbound:
            print("warning: Slack authorisation field not present")
            print_body()
            return [b'<h1>Unauthorized</h1>']
        if inbound['token'] == config_slackOutgoingToken:
            print("Incoming request authenticated")
        else:
            print("warning: Slack authorisation field is present but incorrect")
            print("expected:", config_slackOutgoingToken)
            print_body()
            return [b'<h1>Unauthorized</h1>']
        if 'type' in inbound:
            if inbound['type'] == 'url_verification':
                response = json.dumps({"challenge": inbound["challenge"]})
                print("replying with", response)
                response = bytes(response, "utf-8")
                return [response]
            if inbound['type'] == 'event_callback':
                message = inbound['event']['text']
                message = re.sub(r'<http://.*\|([\w\.]+)>', '\g<1>', message) # <http://dub.ax|dub.ax> becomes dub.ax
                message = re.sub(r'<(@[\w\.]+)>', '\g<1>', message) # <@QWERTY> becomes @QWERTY
                user = '<@' + inbound['event']['user'] + '>' # ZXCVBN becomes <@ZXCVBN>
                botName = '@' + inbound['authorizations'][0]['user_id'] # QWERTY becomes @QWERTY
                chat_id = inbound['event']['channel']
                print(f"[{timestamp} {service}]:", user, message)
                # this condition spawns a worker before returning
            else:
                print(f"[{timestamp} {service}]: unhandled 'type'")
                return [b'<h1>Unhandled</h1>']
        else:
            print(f"[{timestamp} {service}]: unhandled: no 'type'")
            return [b'Unhandled']
    else:
        print(timestamp, "Unknown URI", uri)
        status = "404 Not Found"
        start_response(status, headers)
        return [b'<h1>404</h1>']

    def runWorker():
        worker.process_request(service, chat_id, user, message, botName, userRealName)

    # process in a background thread so we don't keep the requesting client waiting
    t = threading.Thread(target=runWorker)
    t.start()

    # Return an empty response to the client
    print(status, "closing inbound from", service)
    return [b'']

if __name__ == '__main__':
    server = pywsgi.WSGIServer((config_ip, config_port), main)
    print(f'Listening on http://{config_ip}:{config_port}')
    # to start the server asynchronously, call server.start()
    # we use blocking serve_forever() here because we have no other jobs
    server.serve_forever()
