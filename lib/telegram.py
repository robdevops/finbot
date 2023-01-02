import json, time
import requests
from lib.config import *
from sys import stderr
import concurrent.futures

def setWebhook():
    telegram_url = webhooks['telegram'] + 'setWebhook'
    params = {"url": config_telegramOutgoingWebhook, "allowed_updates": "message", 'secret_token': config_telegramOutgoingToken}
    #params = {"url": ''} # unsubscribe
    response = requests.post(
        telegram_url,
        params=params
    )
    print(response.text)

def getMe():
    telegram_url = webhooks['telegram'] + 'getMe'
    response = requests.post(
        telegram_url,
    )
    return response.json()['result']

if config_telegramBotToken:
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(setWebhook)
        #executor.submit(setMyCommands)
        thread = executor.submit(getMe)
        botName = '@' + thread.result()['username']
