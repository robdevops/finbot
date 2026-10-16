"""Once, as an upgraded finbot starts: what the bot kept for all chats at once becomes each old home chat's, the chats
that the retired telegramChatID, slackChannelID and discordChannelID name (read from the environment for this alone).
Each home chat becomes a chat finbot knows, with the default jobs (lib/catalog.py); the watchlist and the plans are
copied to each; and so are the reports' records of what they told the chats (trades, ratings, record highs, podcast
episodes), so that nothing old is told again.

This module goes once every install has started with it: it is its only user."""
import copy
import glob
import os

from lib import log
from lib import config
from lib import jobs
from lib import state
from lib import watchlist
from lib import worker
from lib.reports import milestone, podcasts, rating, trades

# kept for all chats, each now one record per chat; and each podcast feed's seen file
RECORDS = (watchlist.FILE, worker.PLANS, trades.STATE_FILE, rating.STATE_FILE, milestone.STATE_FILE)
# the home chats of older versions: (network, the retired finbot.env key of its chat, the key of its bot token)
HOMES = (('telegram', 'telegramChatID', 'telegramBotToken'), ('slack', 'slackChannelID', 'slackBotToken'),
	('discord', 'discordChannelID', 'discordBotToken'))


def old_homes():
	"""The keys of the chats that the retired home chat keys still name in the environment, each with its bot token."""
	return [f'{network}:{os.environ[key]}' for network, key, token in HOMES
		if os.environ.get(key) and getattr(config.env, token)]


def run():
	"""Make the old home chats' own what was kept for all chats, where that has not been done yet. Without any (a new
	install, or the retired keys deleted), there is nowhere to put it, so it waits."""
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
