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
			if year == "2026" and month_and_day == '04-28':
				payload = [webhook.bold("🤑 Super payout deadline:", service), webhook.strike("28 Jul 2025", service), webhook.strike("28 Oct 2025", service), webhook.strike("28 Jan 2026", service), "28 Apr 2026 ✅", "01 Jul 2026 commence payday super"]
			if year == "2026" and month_and_day == '07-01':
				payload.append("🤑 Commence payday super ✅")
			if month_and_day == '06-23':
				payload.append("💸 Realise capital gains/losses by EOFY June 30" + flag)
				payload.append ("")
				payload.append("💰 Finalise any deductables by EOF June 30: " + flag)
				payload.append("• donations*")
				payload.append("• Super contributions†")
				payload.append("• work expenses‡")
				payload.append("• investment subscriptions§")
				payload.append ("")
				abr_link = util.link('https://abr.business.gov.au/Tools/DgrListing', 'DGR-registered', service)
				stake_note = util.link('https://hellostake.com/au/support/stake-super/employer-and-personal-contributions/33442327233305#h_01JQAPN9A6ZM41NZKP6XZWN1KP', 'note about XX PCC in transaction description', service)
				work_link = util.link('https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/deductions-you-can-claim', 'eligible work expenses', service)
				payload.append(webhook.italics("* Organisation must be " + abr_link, service))
				payload.append(webhook.italics("† Allow transfer time for Super, as contributions can only be deducted for the year they're received. Stake users: see " + stake_note, service))
				payload.append(webhook.italics("‡ See " + work_link, service))
				payload.append(webhook.italics("§ Must relate directly to specific trades and gains/income (e.g. not general finance news)", service))
			if month_and_day == '07-07':
				payload.append("✍️ Submit 'Notice of Intent to Claim' for any post-tax Super contributions. The fund must acknowledge them before you lodge your tax return" + flag)
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
