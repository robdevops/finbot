#!/usr/bin/python3

import sys
import datetime
import json
import pytz

from lib.config import *
from lib import webhook

def lambda_handler():
    def prepare_finance_calendar_payload(service):
        payload = []
        tz = pytz.timezone(config_timezone)
        localtime = datetime.datetime.now(tz)
        month_and_day = str(localtime.strftime('%m-%d')) # 09-20
        year = str(localtime.strftime('%Y')) # 2023
        if config_country_code == 'AU':
            flag = "🇦🇺"
            if month_and_day in {'01-28', '04-28', '07-28', '10-28'}:
                payload.append("🤑 Quarterly Superannuation payout deadline" + flag)
            if month_and_day == '06-23':
                payload.append("💰 Finalise deductable donations, work expenses & investment subscriptions by EOFY June 30" + flag)
                payload.append("💸 Realise capital gains/losses by EOFY June 30" + flag)
                payload.append("✍️ Submit superannuation 'Notice of Intent to Claim' by EOFY June 30" + flag)
            if month_and_day == '10-24':
                payload.append("😓 Self-service individual tax returns are due Oct 31" + flag)
            if month_and_day == '10-31':
                payload.append("😰 Self-service individual tax returns are due today" + flag)
        #if config_country_code in {'AU', 'BD', 'EG', 'ET', 'KE', 'NP', 'PK'}:
        if month_and_day == '06-30':
                payload.append("🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰")
        #elif config_country_code in {'GB', 'HK', 'IN', 'KR', 'NZ', 'JP', 'ZA'}:
        if month_and_day == '03-31':
                payload.append("🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦")
        # above ommits countries where EOFY == calendar year
        if month_and_day == '08-18':
            payload.append("📢 ahem 📢")
            payload.append("🎂 Happy Birthday to me, happy birthday TO me... 🎶 🎂")
            payload.append("😓 Oh no, that song costs royalties. Not very finance savvy of me 😅")
            payload.append("🎶 For I'm a jolly good chat bot, for I'm a jolly good chat bot 👯")
            payload.append("😂 d̸̡̛͚͔̟͐̒e̸̡͋͜s̶͎̟̎̈ṭ̵̦̿̅̉̏r̴̩̥͚͋̀́̀ơ̶̢̳͑̀̕ͅỷ̸̡̹̟̊̚ ̸̢̡͓̥͗͐͌à̶̋͂͜ḽ̴̻̖̀l̷̝͑ ̸̨̨̹͉̐ḧ̴̰̲̫̘́͑̒̒u̵͕̬̳͗̒m̶̡̧̖̭̅͘ã̷̞̦̠̦̅̔̈́ṉ̵̪̱͚̋s̵͚̠̞͛͠ 😂")
            payload.append("🎶 Which nobody can deny 🥳")
        if payload:
            heading = webhook.bold("Finance event reminders:", service)
            payload.insert(0, heading)
        return payload


    # MAIN #

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    for service, url in webhooks.items():
        payload = prepare_finance_calendar_payload(service)
        if service == "telegram":
            url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
        webhook.payload_wrapper(service, url, payload)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
