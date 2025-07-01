#!/usr/bin/env python3

import sys
import datetime
import json
import pytz
from dateutil.relativedelta import relativedelta
from lib.config import *
from lib import util
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
				payload.append("💰 Finalise any deductable donations, Super contributions, work expenses, or investment subscriptions by EOFY June 30" + flag)
				payload.append(f"😐 Allow for transfer time with Super, as contributions can only be deducted for the year the fund {webhook.italics('receives', service)} them" + flag)
				payload.append("💸 Realise capital gains/losses by EOFY June 30" + flag)
			if month_and_day == '10-24':
				payload.append("😓 Self-service individual tax returns are due Oct 31" + flag)
			if month_and_day == '10-31':
				payload.append("😰 Self-service individual tax returns are due today" + flag)
			if month_and_day == '07-07':
				payload.append("✍️ Submit 'Notice of Intent to Claim' for any post-tax Super contributions. The fund must acknowledge them before you lodge your tax return" + flag)
		#if config_country_code in {'AU', 'BD', 'EG', 'ET', 'KE', 'NP', 'PK'}:
		if month_and_day == '06-30':
				payload.append("🥳 Happy EOFY 🇦🇺 🇧🇩 🇪🇬 🇪🇹 🇰🇪 🇳🇵 🇵🇰")
		#elif config_country_code in {'GB', 'HK', 'IN', 'KR', 'NZ', 'JP', 'ZA'}:
		if month_and_day == '03-31':
				payload.append("🥳 Happy EOFY 🇬🇧 🇭🇰 🇮🇳 🇰🇷 🇳🇿 🇯🇵 🇿🇦")
		# above ommits countries where EOFY == calendar year
		if month_and_day == '08-18':
			myBirthday = datetime.datetime(2022,8,18,0,0,0,0, tzinfo=tz)
			difference = relativedelta(localtime, myBirthday)
			payload.append("It's my " + str(difference.years) + util.ordinal(difference.years) + " birthday! 🥳")
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
