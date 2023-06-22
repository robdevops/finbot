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

def sendPhoto(chat_id, image_data, caption, message_id=None):
    url = webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
    #headers = {'Content-type': 'application/json'}
    headers = {'Content-type': 'multipart/form-data'}
    data = {
    'disable_notification': True,
    'chat_id': chat_id,
    'caption': caption,
    'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    "allow_sending_without_reply": True,
    "reply_to_message_id": message_id
    }
    files = {"photo": ('image.png', image_data)}
    #data = json.dumps(data).encode('utf-8')
    try:
        r = requests.post(url, data=data, files=files, timeout=config_http_timeout)
    #except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout) as e:
    except Exception as e:
      print("Failure executing request:", url, data, str(e))
      return False
    if r.status_code == 200:
        print(r.status_code, "OK Telegram sendPhoto", caption)
    else:
        print(r.status_code, "error Telegram sendPhoto", r.reason, caption)
        return False

if config_telegramBotToken:
    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.submit(setWebhook)
        #executor.submit(setMyCommands)
        thread = executor.submit(getMe)
        botName = '@' + thread.result()['username']
