import json
import requests
import sys
from lib.config import *

def getUser(user_id):
    url = 'https://slack.com/api/users.info'
    headers = {'Content-type': 'application/x-www-form-urlencoded', 'Authorization': 'Bearer ' + config_slackBotToken, 'user': user_id}
    response = requests.get(url, headers=headers, timeout=config_http_timeout)
    print(response.json())
    return response.json()

def sendPhoto(chat_id, image_data, caption, message_id=None):
    #url = webhooks['telegram'] + "sendPhoto?chat_id=" + str(chat_id)
    url = 'https://slack.com/api/files.upload'
    headers = {'Authorization': 'Bearer ' + config_slackBotToken}
    data = {
        'channels': chat_id,
        'initial_comment': caption }
    if message_id:
        data['thread_ts'] = message_id
        data['reply_broadcast'] = 'true'
    files = {
        "file":("image.png",
        image_data) }
    #data = json.dumps(data).encode('utf-8')
    if debug:
        print(url, headers, data)
    try:
        r = requests.post(url, headers=headers, data=data, files=files, timeout=config_http_timeout)
    except Exception as e:
      print("Failure executing request:", url, data, str(e), file=sys.stderr)
      return False
    if r.status_code == 200:
        print(r.status_code, "OK Slack sendPhoto", caption)
        output = r.json
        print(json.dumps(output, indent=4))
        print(str(output))
        if 'false' in output:
            print(json.dumps(output, indent=4))
    else:
        print(r.status_code, "error Slack sendPhoto", r.reason, caption, file=sys.stderr)
        return False

