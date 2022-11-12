#!/usr/bin/python3

import json, os, time, re
import datetime
import pytz

from lib.config import *
import lib.sharesight as sharesight
import lib.webhook as webhook
import lib.util as util

def lambda_handler(event,context):
    time_now = datetime.datetime.today()
    today = str(time_now.strftime('%Y-%m-%d')) # 2022-09-20
    
    def prepare_finance_calendar_payload(service):
        payload = []
        if service == 'telegram':
            payload.append("<b>Finance event reminders:</b>")
        elif service == 'slack':
            payload.append("*Finance event reminders:*")
        elif service == 'discord':
            payload.append("**Finance event reminders:**")
        else:
            payload.append("Finance event reminders:")
        tz = pytz.timezone(config_timezone)
        localtime = datetime.datetime.now(tz)
        month_and_day = str(localtime.strftime('%m-%d')) # 09-20
        if config_country_code == 'AU':
            flag = "🇦🇺"
            if month_and_day in {'01-28', '04-28', '07-28', '10-28'}:
                payload.append("🤑 Quarterly Superannuation payout is due today" + flag)
            if month_and_day == '06-23':
                payload.append("💰 Finalise deductable donations, work expenses & investment subscriptions by EOFY June 30" + flag)
                payload.append("💸 Realise capital gains/losses by EOFY June 30" + flag)
                payload.append("✍️  Submit superannuation 'Notice of Intent to Claim' by EOFY June 30" + flag)
            if month_and_day == '10-24':
                payload.append("😓 Self-service individual tax returns are due Oct 31" + flag)
            if month_and_day == '10-31':
                payload.append("😰 Self-service individual tax returns are due today" + flag)
        if config_country_code in {'AU', 'NZ'}:
            if month_and_day == '06-30':
                payload.append("🥳 Happy EOFY 🇦🇺 🇳🇿")
        elif config_country_code in {'CA', 'HK', 'GB', 'IN', 'JP', 'ZA'}:
            if month_and_day == '03-31':
                payload.append("🥳 Happy EOFY 🇨🇦 🇭🇰 🇬🇧 🇯🇵 🇮🇳 🇿🇦")
        elif config_country_code == 'US':
            if month_and_day == '09-30':
                payload.append("🥳 Happy EOFY 🇺🇸")
        # deliberately ommited countries where EOFY aligns with calendar year
        return payload


    # MAIN #

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env")
        exit(1)
    for service in webhooks:
        url = webhooks[service]
        payload = prepare_finance_calendar_payload(service)
        if len(payload) > 1: # ignore header
            payload_string = '\n'.join(payload)
            print(payload_string)
            chunks = util.chunker(payload, 20)
            webhook.payload_wrapper(service, url, chunks)

    # make google cloud happy
    return True

lambda_handler(1,2)
