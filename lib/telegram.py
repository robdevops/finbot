import concurrent.futures
import json
import requests
from lib.config import *

def setWebhook():
    telegram_url = webhooks['telegram'] + 'setWebhook'
    print("registering", config_telegramOutgoingWebhook)
    params = {"url": config_telegramOutgoingWebhook, "allowed_updates": "message", 'secret_token': config_telegramOutgoingToken}
    #params = {"url": ''} # unsubscribe
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
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(setWebhook)
        #executor.submit(setMyCommands)
        thread = executor.submit(getMe)
        botName = '@' + thread.result()['username']
