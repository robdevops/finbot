import feedparser
import hashlib
import json
import os
import sys
from lib.config import *
from lib import webhook
from lib import util

def get_seen_file(url):
	hashed = hashlib.md5(url.encode()).hexdigest()
	return config_var_dir + "/" + f"finbot_podcast_seen_{hashed}.json"

def load_seen(filename):
	if os.path.exists(filename):
		with open(filename, "r") as f:
			return set(json.load(f))
	return set()

def save_seen(seen, filename):
	with open(filename, "w") as f:
		json.dump(list(seen), f)

def fetch_new_episodes(feed_url, seen):
	feed = feedparser.parse(feed_url)
	if feed.bozo:
		raise RuntimeError(f"Failed to parse feed: {feed.bozo_exception}")
	podcast_name = feed.feed.get("title", "Podcast").strip()

	new_episodes = []

	for entry in feed.entries:
		guid = entry.get("guid") or entry.get("link")
		if not guid or guid in seen:
			continue

		media_url = next(
			(link.href for link in entry.get("links", []) if link.get("type", "").startswith("audio/")),
			None
		)
		if not media_url:
			continue

		episode_title = entry.get("title", "Untitled").strip()
		full_title = f"{podcast_name}: {episode_title}"

		new_episodes.append({"podcast": podcast_name, "title": episode_title, "url": media_url})

		seen.add(guid)

	return new_episodes

def main():
	if len(sys.argv) != 2:
		print("Usage: python script.py <podcast_feed_url>")
		sys.exit(1)

	feed_url = sys.argv[1]
	seen_file = get_seen_file(feed_url)

	seen = load_seen(seen_file)
	new_episodes = fetch_new_episodes(feed_url, seen)
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
		#print(service, payload)
		webhook.payload_wrapper(service, url, payload)

if __name__ == "__main__":
	main()

