#!/usr/bin/env python3

import sys
import os
import hashlib
import string
import requests
import xml.etree.ElementTree as ET
from lib.config import *
from lib import webhook
from lib import util
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

NAMESPACES = {
		"media": "http://search.yahoo.com/mrss/",
		"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"
}

def get_seen_filename(url):
		hashed = hashlib.md5(url.encode()).hexdigest()
		return config_var_dir + "/" + f"finbot_podcast_seen_{hashed}.json"

def load_seen(filename):
		if os.path.exists(filename):
				with open(filename, "r") as f:
						return json.load(f)
		return []

def save_seen(seen, filename):
		with open(filename, "w") as f:
				json.dump(list(seen), f, indent=4)

def fetch_and_parse_feed(url):
		resp = requests.get(url)
		resp.raise_for_status()
		return ET.fromstring(resp.content)

def format_duration(duration_str):
		"""Convert duration string to human-readable format"""
		if not duration_str:
				return ""

		try:
				# Try parsing as seconds (integer)
				total_seconds = int(duration_str)
		except ValueError:
				# Try parsing as HH:MM:SS or MM:SS format
				try:
						parts = duration_str.split(':')
						if len(parts) == 3:  # HH:MM:SS
								total_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
						elif len(parts) == 2:  # MM:SS
								total_seconds = int(parts[0]) * 60 + int(parts[1])
						else:
								return ""
				except:
						return ""

		hours = total_seconds // 3600
		minutes = (total_seconds % 3600) // 60

		#if hours > 0:
		#		return f"{hours}h {minutes}m"
		#else:
		#		return f"{minutes}m"
		return f"{hours:02d}:{minutes:02d}"


def how_long_ago(pub_raw):
		try:
				pub_date = parsedate_to_datetime(pub_raw)
				if pub_date.tzinfo is None:
						pub_date = pub_date.replace(tzinfo=timezone.utc)
				now = datetime.now(timezone.utc)
				delta = now - pub_date

				days = delta.days
				seconds = delta.seconds
				if days > 0:
						return f"{days}d ago"
				elif seconds > 3600:
						hours = seconds // 3600
						return f"{hours}h ago"
				elif seconds > 60:
						minutes = seconds // 60
						return f"{minutes}m ago"
				else:
						return f"{seconds}s ago"
		except Exception as e:
				print(f"Error in how_long_ago: {e}")
				return ""

def fetch_new_episodes(feed_url, seen):
		root = fetch_and_parse_feed(feed_url)
		channel = root.find("channel")
		if channel is None:
				raise RuntimeError("No <channel> element found")

		podcast_name = (channel.findtext("title") or "Podcast").strip()
		new_episodes = []

		for item in channel.findall("item"):
				guid = item.findtext("guid") or item.findtext("link")
				if not guid or guid in seen:
						continue

				# Try <media:content><media:player>
				player_el = item.find(".//media:content/media:player", NAMESPACES)
				if player_el is not None and "url" in player_el.attrib:
						media_url = player_el.attrib["url"]
				else:
						# Fallback: <media:content url=...>
						content_el = item.find("media:content", NAMESPACES)
						media_url = content_el.attrib["url"] if content_el is not None and "url" in content_el.attrib else None

				if not media_url:
						# Final fallback: <enclosure>
						enclosure = item.find("enclosure")
						media_url = enclosure.attrib["url"] if enclosure is not None and "url" in enclosure.attrib else None

				if not media_url:
						continue

				# Get duration from itunes:duration tag
				duration_raw = item.findtext("itunes:duration", namespaces=NAMESPACES)
				duration = format_duration(duration_raw) if duration_raw else ""

				pub_raw = item.findtext("pubDate")
				published_dt = parsedate_to_datetime(pub_raw) if pub_raw else datetime.min
				ago = how_long_ago(pub_raw) if pub_raw else ""

				episode_title = (item.findtext("title") or "Untitled").strip()
				new_episodes.append({
						"podcast": podcast_name,
						"title": episode_title,
						"url": media_url,
						"ago": ago,
						"duration": duration,
						"published_dt": published_dt
				})
				new_episodes.sort(key=lambda ep: ep["published_dt"], reverse=True)
				new_episodes = new_episodes[:5]

				seen.append(guid)

		return new_episodes

def main():
		if len(sys.argv) != 2:
				print("Usage:", sys.argv[0], "\"<podcast_feed_url>\"")
				sys.exit(1)

		feed_url = sys.argv[1]
		seen_file = get_seen_filename(feed_url)
		seen = load_seen(seen_file)
		seen_earlier = seen.copy()

		try:
				new_episodes = fetch_new_episodes(feed_url, seen)
		except Exception as e:
				print(f"Error: {e}")
				sys.exit(1)

		seen = sorted(set(seen))
		if seen != seen_earlier:
				if not webhooks:
						raise KeyError("no services enabled in .env")
				for service, url in webhooks.items():
						payload = []
						if service == "telegram":
								url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
						for ep in new_episodes:
								podcast_name = ep['podcast']
								title = ep['title'].removeprefix(podcast_name).lstrip(string.punctuation + " ")
								link = util.link(ep['url'], title, service)
								emoji = "📣"
								duration_str = f"{ep['duration']}" if ep['duration'] else ""
								payload.append(f"{emoji} {podcast_name}: {link} {duration_str} ({ep['ago']})")
						webhook.payload_wrapper(service, url, payload)
						#print(service, json.dumps(payload, indent=4))
				save_seen(seen, seen_file) # do this last so we pick up these episodes next run if we error
		else:
				print("no new episodes found")

if __name__ == "__main__":
		main()
