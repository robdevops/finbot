import concurrent.futures
import json
import requests
import sys
from lib.config import *

def setWebhook():
    telegram_url = webhooks['telegram'] + 'setWebhook'
    print("registering", config_telegramOutgoingWebhook, file=sys.stderr)
    params = {"url": config_telegramOutgoingWebhook, "allowed_updates": "message", 'secret_token': config_telegramOutgoingToken}
    response = requests.post(
        telegram_url,
        params=params,
        timeout=config_http_timeout
    )
    print(response.text)

def delWebhook():
    telegram_url = webhooks['telegram'] + 'setWebhook'
    print("deregistering", config_telegramOutgoingWebhook, file=sys.stderr)
    params = {"url": ''} # unsubscribe
    response = requests.post(
        telegram_url,
        params=params,
        timeout=config_http_timeout
    )
    print(response.text)

def getMe():
    telegram_url = webhooks['telegram'] + 'getMe'
    response = requests.post(
        telegram_url,
        timeout=config_http_timeout
    )
    return response.json()['result']

if config_telegramBotToken:
    delWebhook()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(setWebhook)
        #executor.submit(setMyCommands)
        thread = executor.submit(getMe)
        botName = '@' + thread.result()['username']
