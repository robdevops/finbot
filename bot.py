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

def print_body(inbound):
    try:
        print(f"inbound {uri} ", json.dumps(inbound, indent=4))
    except Exception as e:
        print(e, "raw body: ", inbound)
def print_headers(environ):
    for item in sorted(environ.items()):
        print(item)

def main(environ, start_response):
    request_body = environ['wsgi.input'].read()
    current_time = datetime.datetime.today()
    current_time = str(current_time.strftime('%H:%M:%S')) # 2022-09-20
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
        print_headers(environ)
        print_body(inbound)
    if uri == '/telegram':
        service = 'telegram'
        botName = '@' + telegram.getBotName()
        if 'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN' not in environ:
            print_headers()
            print("Fatal:", service, "authorisation header not present")
            return [b'<h1>Unauthorized</h1>']
        elif environ['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] != config_telegramOutgoingToken:
            print_headers()
            print("Fatal: Telegram authorisation header is present but incorrect. Expected:", config_telegramOutgoingToken)
            return [b'<h1>Unauthorized</h1>']
        if "message" not in inbound:
            return [b'Unsupported']
        else:
            message_id = str(inbound["message"]["message_id"])
            chat_id = str(inbound["message"]["chat"]["id"])
            user_id = str(inbound["message"]["from"]["id"])
            chat_type = inbound["message"]["chat"]["type"]
            if "username" in inbound["message"]["from"]:
                user = '@' + inbound["message"]["from"]["username"]
                userRealName = inbound["message"]["from"]["first_name"]
            else:
                user = userRealName = '@' + inbound["message"]["from"]["first_name"]
            if chat_type == "private": # Anyone can find and PM the bot so we need to be careful
                if user_id in config_telegram_allowed_userids:
                    print(user_id, user, userRealName, "is whitelisted for private message")
                else:
                    print(user_id, user, userRealName, "is not whitelisted. Ignoring.")
                    return [b'<h1>Unauthorized</h1>']
            file_id=False
            if "text" in inbound["message"]:
                message = inbound["message"]["text"]
                print(f"[Telegram]:", user, message)
            elif "photo" in inbound["message"]:
                message = ''
                if "caption" in inbound["message"]:
                    message = inbound["message"]["caption"]
                photo = inbound["message"]["photo"][-1]
                file_id = photo["file_id"]
                print(f"[Telegram photo]:", user, file_id, message)
            else:
                print(f"[{service}]: unhandled: 'message' without 'text'")
                return [b'<h1>Unhandled</h1>']
    elif uri == '/slack':
        service = 'slack'
        if 'token' not in inbound:
            print("warning: Slack authorisation field not present")
            print_body(inbound)
            return [b'<h1>Unauthorized</h1>']
        if inbound['token'] == config_slackOutgoingToken:
            print("Incoming request authenticated")
        else:
            print("warning: Slack authorisation field is present but incorrect")
            print("expected:", config_slackOutgoingToken)
            print_body(inbound)
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
                print(f"[{current_time} {service}]:", user, message)
                # this condition spawns a worker before returning
            else:
                print(f"[{current_time} {service}]: unhandled 'type'")
                return [b'<h1>Unhandled</h1>']
        else:
            print(f"[{current_time} {service}]: unhandled: no 'type'")
            return [b'Unhandled']
    else:
        print(current_time, "Unknown URI", uri)
        status = "404 Not Found"
        start_response(status, headers)
        return [b'<h1>404</h1>']

    def runWorker():
        worker.process_request(service, chat_id, user, message, botName, userRealName, message_id)

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
