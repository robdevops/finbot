import sys
import os
import hashlib
import requests
import xml.etree.ElementTree as ET
from lib.config import *
from lib import webhook
from lib import util

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
			return set(json.load(f))
	return set()

def save_seen(seen, filename):
	seen = list(seen)
	seen.sort()
	with open(filename, "w") as f:
		json.dump(list(seen), f)

def fetch_and_parse_feed(url):
	resp = requests.get(url)
	resp.raise_for_status()
	return ET.fromstring(resp.content)

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

		episode_title = (item.findtext("title") or "Untitled").strip()
		full_title = f"{podcast_name}: {episode_title}"
		new_episodes.append({"podcast": podcast_name, "title": full_title, "url": media_url})
		seen.add(guid)

	return new_episodes

def main():
	if len(sys.argv) != 2:
		print("Usage: python podcast_fetcher.py <podcast_feed_url>")
		sys.exit(1)

	feed_url = sys.argv[1]
	seen_file = get_seen_filename(feed_url)
	seen = load_seen(seen_file)
	try:
		new_episodes = fetch_new_episodes(feed_url, seen)
	except Exception as e:
		print(f"Error: {e}")
		sys.exit(1)

	save_seen(seen, seen_file)

	if not webhooks:
		print("Error: no services enabled in .env", file=sys.stderr)
		sys.exit(1)
	for service, url in webhooks.items():
		payload = []
		if service == "telegram":
			url = webhooks['telegram'] + "sendMessage?chat_id=" + config_telegramChatID
		for ep in new_episodes:
			link = util.link(ep['url'], ep['title'], service)
			payload.append(f"{ep['podcast']}: {link}")
		print(service, payload)
		#webhook.payload_wrapper(service, url, payload)

if __name__ == "__main__":
	main()

