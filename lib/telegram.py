import json, time
import requests
from lib.config import *
from sys import stderr
import threading

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
    try:
        threading.Thread(target=setWebhook).start()
        #threading.Thread(target=setMyCommands).start()
        botName = ''
        botName = '@' + getMe()['username']
    except Exception as e:
        print("Telegram error", str(e), file=stderr)
