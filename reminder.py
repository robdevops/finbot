#!/usr/bin/env python3

import sys
import json
import datetime
import pytz
from pathlib import Path
from dateutil.relativedelta import relativedelta
from lib.config import *
from lib import util
from lib import webhook

REMINDERS_FILE = Path(__file__).parent / "var/reminder.json"


def load_reminders():
	with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
		return json.load(f)


def lambda_handler():
	def prepare_finance_calendar_payload(service):
		payload = []
		tz = pytz.timezone(config_timezone)
		localtime = datetime.datetime.now(tz)

		month_and_day = str(localtime.strftime('%m-%d')) # 09-20
		year = str(localtime.strftime('%Y')) # 2023

		# --- Simple, static one-line reminders loaded from reminders.json ---
		for reminder in load_reminders():
			if reminder.get("month_day") != month_and_day:
				continue
			if reminder.get("year") and reminder["year"] != year:
				continue
			gate_country = reminder.get("gate_country")
			if gate_country and config_country_code != gate_country:
				continue
			message = reminder["message"]
			if "{flag}" in message:
				# Flag only ever applies to the AU-gated set today;
				# extend this mapping if other gated countries are added.
				flag = "🇦🇺" if gate_country == "AU" else ""
				message = message.replace("{flag}", flag)
			payload.append(message)

		# --- Complex, dynamically-computed reminders (kept in code) ---
		if config_country_code == 'AU':
			flag = "🇦🇺"
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
