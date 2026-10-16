"""Once, as an upgraded finbot starts. The jobs of the direct message chats finbot knows are switched off, as a direct
message now starts with its default jobs off (dm_jobs_off, recorded in UPGRADES so that it runs at one start only).
And what the bot kept for all chats at once becomes each old home chat's, the chats that the retired telegramChatID,
slackChannelID and discordChannelID name (read from the environment for this alone): each becomes a chat finbot knows,
with the default jobs (lib/catalog.py); the watchlist and the plans are copied to each; and so are the reports' records
of what they told the chats (trades, ratings, record highs, podcast episodes), so that nothing old is told again.

This module goes once every install has started with it: it is its only user."""
import copy
import datetime
import glob
import os

from lib import log
from lib import config
from lib import delivery
from lib import discord_common
from lib import jobs
from lib import state
from lib import watchlist
from lib import worker
from lib.reports import milestone, podcasts, rating, trades

# kept for all chats, each now one record per chat; and each podcast feed's seen file
RECORDS = (watchlist.FILE, worker.PLANS, trades.STATE_FILE, rating.STATE_FILE, milestone.STATE_FILE)
UPGRADES = 'finbot_upgrades.json' # {name: when}: the one-off upgrades done, each at one start only
# the home chats of older versions: (network, the retired finbot.env key of its chat, the key of its bot token)
HOMES = (('telegram', 'telegramChatID', 'telegramBotToken'), ('slack', 'slackChannelID', 'slackBotToken'),
	('discord', 'discordChannelID', 'discordBotToken'))


def old_homes():
	"""The keys of the chats that the retired home chat keys still name in the environment, each with its bot token."""
	return [f'{network}:{os.environ[key]}' for network, key, token in HOMES
		if os.environ.get(key) and getattr(config.env, token)]


def run():
	"""Switch off the jobs of the direct message chats finbot knows, once (dm_jobs_off). Make the old home chats' own
	what was kept for all chats, where that has not been done yet; without any (a new install, or the retired keys
	deleted), there is nowhere to put it, so it waits."""
	once('dm jobs off', dm_jobs_off)
	homes = old_homes()
	if not homes:
		return
	try:
		added = jobs.know(homes)
	except (OSError, ValueError) as e:
		log.warn(f'schedule: {jobs.JOBS_FILE} left as it is, unreadable: {e}')
		added = 0
	if added:
		log.info(f"schedule: {added} old home chat{'' if added == 1 else 's'} start with the default jobs")
	feeds = sorted(os.path.basename(path) for path in glob.glob(state.path(podcasts.SEEN_FILES)))
	for name in RECORDS + tuple(feeds):
		record(name, homes)


def once(name, upgrade):
	"""Run an upgrade unless it has run at an earlier start (UPGRADES). One that fails is logged, and tried again at
	the next start."""
	try:
		done = state.load(UPGRADES, {})
	except (OSError, ValueError) as e:
		log.warn(f'upgrade: {name} waits, {UPGRADES} is unreadable: {e}')
		return
	done = done if isinstance(done, dict) else {}
	if name in done:
		return
	try:
		upgrade()
	except Exception as e:
		log.warn(f'upgrade: {name} failed, and is tried again at the next start:', delivery.error_line(e))
		return
	state.save(UPGRADES, {**done, name: datetime.datetime.now(datetime.timezone.utc).isoformat()})


def dm_jobs_off():
	"""Switch off every job of each direct message chat finbot knows, now that one starts with its default jobs off:
	Telegram's and Slack's as their keys tell (jobs.is_dm), Discord's as Discord says. The chats of the old schedule
	file (jobs.OLD_FILE) that are direct messages become known first, with their jobs off."""
	chats = state.load(jobs.JOBS_FILE, {})
	old = state.load(jobs.OLD_FILE, {}) if os.path.exists(state.path(jobs.OLD_FILE)) else {}
	chats, old = (data if isinstance(data, dict) else {} for data in (chats, old))
	keys = [key for key in dict.fromkeys([*chats, *old]) if isinstance(key, str)]
	dms = [key for key in keys if jobs.is_dm(key)]
	if config.env.discordBotToken:
		dms += [key for key in keys if key.startswith('discord:') and discord_dm(key.partition(':')[2])]
	jobs.know([key for key in dms if key not in chats], dm=True)
	with state.edit(jobs.JOBS_FILE, {}) as stored:
		for key in dms:
			if isinstance(stored.get(key), dict):
				jobs.switch_record(stored[key], False)
	if dms:
		log.info(f"schedule: every job switched off in {len(dms)} direct message chat{'' if len(dms) == 1 else 's'}"
			f" ({', '.join(dms)}), as a direct message now starts with its jobs off")


def discord_dm(channel):
	"""Whether a Discord channel (by id) is a direct message with the bot, as Discord says; one it says nothing of (a
	channel the bot has left, an id that is none) is not."""
	if not (channel.isascii() and channel.isdigit()):
		return False
	try:
		answer = discord_common.call('GET', f'/channels/{channel}')
	except RuntimeError as e: # refused: the channel is gone, or the bot may not see it
		log.warn(f'upgrade: what Discord channel {channel} is, Discord will not say:', delivery.error_line(e))
		return False
	return isinstance(answer, dict) and answer.get('type') in (1, 3) # a direct message, or a group one


def record(name, homes):
	"""A file's record kept for all chats at once (anything but {'chats': ...}) becomes each home chat's."""
	try:
		data = state.load(name)
	except (OSError, ValueError) as e:
		log.warn(f'state: {name} left as it is, unreadable: {e}')
		return
	if data is None or (isinstance(data, dict) and 'chats' in data):
		return
	state.save(name, {'chats': {key: copy.deepcopy(data) for key in homes}})
	log.info(f"state: {name} is kept per chat now, its record copied to {', '.join(homes)}")
