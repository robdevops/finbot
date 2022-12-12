#!/usr/bin/python3

import json, time
import requests
from lib.config import *

def subscribe():
    telegram_url = webhooks['telegram'] + 'setWebhook'
    params = {"url": config_telegram_outgoing_webhook, "allowed_updates": ["message"]}
    response = requests.post(
        #url="https://api.telegram.org/botTOKEN/setWebhook",
        telegram_url,
        params=params
    )
    print(response.text)

def getBotName():
    telegram_url = webhooks['telegram'] + 'getMe'
    params = {"url": config_telegram_outgoing_webhook}
    response = requests.post(
        telegram_url,
        params=params
    )
    return response.json()['result']['username']

subscribe()
