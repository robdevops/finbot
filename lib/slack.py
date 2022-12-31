import json, time
import requests
from lib.config import *

def getUser(user_id):
    url = 'https://slack.com/api/users.info'
    headers = {'Content-type': 'application/x-www-form-urlencoded', 'Authorization': 'Bearer ' + config_slackBotToken, 'user': user_id}
    response = requests.get(url, headers=headers)
    print(response.json())
    return response.json()

