#!/usr/bin/env python3

import sys
import hashlib
import string
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from lib import net
from lib import webhook
from lib import util

NAMESPACES = {
	"media": "http://search.yahoo.com/mrss/",
	"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"
}
NEWEST = 5 # episodes posted per run at most: the other new ones (on a first run, say) are only recorded as seen

def get_seen_filename(url):
	"""The state file, in the data directory, of the episodes of this feed already seen."""
	return f"finbot_podcast_seen_{hashlib.md5(url.encode()).hexdigest()}.json"

def fetch_and_parse_feed(url):
	resp = net.get(url, timeout=30)
	resp.raise_for_status()
	return ET.fromstring(resp.content)

def format_duration(duration_str):
	"""'3725' (seconds), '1:02:05' or '62:05' -> '01:02' (hours and minutes); '' for anything else."""
	try:
		parts = [int(part) for part in (duration_str or '').split(':')]
	except ValueError:
		return ""
	if len(parts) > 3:
		return ""
	total_seconds = sum(part * 60 ** i for i, part in enumerate(reversed(parts)))
	return f"{total_seconds // 3600:02d}:{total_seconds % 3600 // 60:02d}"

def published(pub_raw):
	"""An episode's publication time (in UTC where the feed gives no zone), or None where it gives none or garbles it."""
	try:
		when = parsedate_to_datetime(pub_raw)
	except (TypeError, ValueError):
		return None
	return when if when.tzinfo else when.replace(tzinfo=timezone.utc)

def how_long_ago(when):
	"""'3d ago', '5h ago', '12m ago' or '40s ago'; '' without a time."""
	if when is None:
		return ""
	delta = datetime.now(timezone.utc) - when
	if delta.days > 0:
		return f"{delta.days}d ago"
	if delta.seconds > 3600:
		return f"{delta.seconds // 3600}h ago"
	if delta.seconds > 60:
		return f"{delta.seconds // 60}m ago"
	return f"{delta.seconds}s ago"

def media_link(item):
	"""An episode's media: <media:content><media:player url>, else <media:content url>, else <enclosure url>; None without any."""
	for element in (item.find(".//media:content/media:player", NAMESPACES), item.find("media:content", NAMESPACES), item.find("enclosure")):
		if element is not None and element.attrib.get("url"):
			return element.attrib["url"]
	return None

def fetch_new_episodes(feed_url, seen):
	"""(the NEWEST newest episodes whose guid is not in `seen`, newest first; the guids of all the new ones)."""
	channel = fetch_and_parse_feed(feed_url).find("channel")
	if channel is None:
		raise RuntimeError("No <channel> element found")
	podcast_name = (channel.findtext("title") or "Podcast").strip()
	episodes, guids = [], set()
	for item in channel.findall("item"):
		guid = item.findtext("guid") or item.findtext("link")
		media_url = media_link(item)
		if not guid or guid in seen or not media_url:
			continue
		when = published(item.findtext("pubDate"))
		episodes.append({"podcast": podcast_name, "title": (item.findtext("title") or "Untitled").strip(), "url": media_url,
			"ago": how_long_ago(when), "duration": format_duration(item.findtext("itunes:duration", namespaces=NAMESPACES)),
			"published": when or datetime.min.replace(tzinfo=timezone.utc)})
		guids.add(guid)
	episodes.sort(key=lambda episode: episode["published"], reverse=True)
	return episodes[:NEWEST], guids

def lambda_handler(feed_url):
	"""Post the feed's newest episodes not posted before, then record every new one as seen."""
	seen_file = get_seen_filename(feed_url)
	seen = set(util.json_load(seen_file, persist=True) or [])
	try:
		episodes, guids = fetch_new_episodes(feed_url, seen)
	except Exception as e:
		raise RuntimeError(f"fetching feed {feed_url}: {e}")
	if not guids:
		print("no new episodes found")
		return
	for service, url, chat in webhook.default_chats():
		payload = []
		for episode in episodes:
			podcast_name = episode['podcast']
			title = episode['title'].removeprefix(podcast_name).lstrip(string.punctuation + " ")
			duration = f" {episode['duration']}" if episode['duration'] else ""
			payload.append(f"📣 {podcast_name}: {util.link(episode['url'], title, service)}{duration} ({episode['ago']})")
		webhook.send(service, url, chat, payload)
	util.json_write(seen_file, sorted(seen | guids), persist=True) # last, so that a failure above leaves these episodes for next run

def job(argv):
	"""Arguments of a scheduled run: (label, lambda_handler kwargs). Raises ValueError with the usage on a bad argument."""
	match argv:
		case [feed_url]:
			return 'podcasts.py ' + hashlib.md5(feed_url.encode()).hexdigest()[:8], {'feed_url': feed_url} # the label matches the seen file's name
		case _:
			raise ValueError('"<podcast_feed_url>"')

if __name__ == "__main__":
	webhook.cli(sys.argv[0], job, lambda_handler)
