import concurrent.futures
import json
import requests
import sys
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

def sendPhoto(chat_id, image_data, caption, message_id=None):
    url = webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
    headers = {}
    data = {
        'disable_notification': True,
        'chat_id': chat_id,
        'caption': caption,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
        'allow_sending_without_reply': True,
        'reply_to_message_id': message_id}
    files = {"photo": ('image.png', image_data)}
    try:
        r = requests.post(url, data=data, headers=headers, files=files, timeout=config_http_timeout)
    except Exception as e:
      print("Failure executing request:", url, data, str(e))
      return False
    if r.status_code == 200:
        print(r.status_code, "OK Telegram sendPhoto", caption)
        output = r.json()
        if not output['ok']:
            print(output['error_code'], output['description'], file=sys.stderr)
    else:
        print(r.status_code, "error Telegram sendPhoto", r.reason, caption, file=sys.stderr)
        return False

if config_telegramBotToken:
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(setWebhook)
        #executor.submit(setMyCommands)
        thread = executor.submit(getMe)
        botName = '@' + thread.result()['username']
