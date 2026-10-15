"""Reminders for the day: those in reminder.json, and the Australian end of financial year (scheduled: reminder.py)."""
import datetime
import zoneinfo
from dateutil.relativedelta import relativedelta
from lib import config
from lib import formats
from lib import webhook


def lambda_handler():
	def prepare_finance_calendar_payload(service):
		payload = []
		tz = zoneinfo.ZoneInfo(config.prefs.timezone)
		localtime = datetime.datetime.now(tz)

		month_and_day = str(localtime.strftime('%m-%d')) # 09-20
		year = str(localtime.strftime('%Y')) # 2023

		# --- Simple, static one-line reminders loaded from reminders.json ---
		for reminder in config.data_json("reminder.json", []):
			if reminder.get("month_day") != month_and_day:
				continue
			if reminder.get("year") and reminder["year"] != year:
				continue
			gate_country = reminder.get("gate_country")
			if gate_country and config.prefs.country_code != gate_country:
				continue
			message = reminder["message"]
			if "{flag}" in message:
				# Flag only ever applies to the AU-gated set today;
				# extend this mapping if other gated countries are added.
				flag = "🇦🇺" if gate_country == "AU" else ""
				message = message.replace("{flag}", flag)
			payload.append(message)

		# --- Complex, dynamically-computed reminders (kept in code) ---
		if config.prefs.country_code == 'AU':
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
				abr_link = service.link('https://abr.business.gov.au/Tools/DgrListing', 'DGR-registered')
				stake_note = service.link('https://hellostake.com/au/support/stake-super/employer-and-personal-contributions/33442327233305#h_01JQAPN9A6ZM41NZKP6XZWN1KP', 'note about XX PCC in transaction description')
				work_link = service.link('https://www.ato.gov.au/individuals-and-families/income-deductions-offsets-and-records/deductions-you-can-claim', 'eligible work expenses')
				payload.append(service.italic("* Organisation must be " + abr_link))
				payload.append(service.italic("† Allow transfer time for Super, as contributions can only be deducted for the year they're received. Stake users: see " + stake_note))
				payload.append(service.italic("‡ See " + work_link))
				payload.append(service.italic("§ Must relate directly to specific trades and gains/income (e.g. not general finance news)"))

		if month_and_day == '08-18':
			myBirthday = datetime.datetime(2022,8,18,0,0,0,0, tzinfo=tz)
			difference = relativedelta(localtime, myBirthday)
			payload.append("It's my " + str(difference.years) + formats.ordinal(difference.years) + " birthday! 🥳")

		if payload:
			heading = service.bold("Finance event reminders:")
			payload.insert(0, heading)
		return payload


	# MAIN #

	for service, url, chat in webhook.default_chats():
		webhook.send(service, url, chat, prepare_finance_calendar_payload(service))

def job(argv):
	return 'reminder.py', {}
