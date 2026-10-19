#!/usr/bin/env python3
"""Print the manifest of finbot's Slack app, to paste into the app's settings (_App Manifest_, the JSON tab), which sets
it all up at once: the slash commands, from finbot's own command table; the bot's scopes and events; interactivity, for
the buttons; the messages tab of App Home, for direct messages; and Socket Mode, on or off.

  util/slack_manifest.py                                  Socket Mode: finbot opens a socket to Slack (slackAppToken)
  util/slack_manifest.py --url https://example.com/slack  HTTP mode: Slack posts to slackOutgoingWebhook, this URL
  util/slack_manifest.py --every-message                  the bot sees every message in its channels, not only the
                                                          ones that mention it, so that .price works there

Slack makes slash commands only in an app's settings (there is no API for them without a configuration token), so this
is the way they get there: run it again, and paste what it prints, when finbot's commands change."""

import argparse
import json
import os
import sys
from pathlib import Path

if __name__ == '__main__':
	os.environ['FINBOT_CHECK_ONLY'] = '1' # importing lib.config must not create the data directories
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import worker

SCOPES = ('chat:write', 'commands', 'files:read', 'files:write', 'reactions:write', 'users:read')
# replies, slash commands, charts, ⏳, who the workspace's admins are
RESERVED = ('help',) # slash commands Slack keeps for itself: a manifest that names one is refused ("invalid name")
EVENT_SCOPES = {'app_mention': 'app_mentions:read', 'message.channels': 'channels:history',
	'message.groups': 'groups:history', 'message.im': 'im:history'} # what each event needs


def manifest(name='finbot', url='', every_message=False):
	"""The manifest, as a dict: for Socket Mode without url; for HTTP mode with it, the Request URL of the events, the
	buttons and each slash command. The bot hears the messages that mention it, or with every_message each message in
	the channels it is in, and its direct messages either way. Every slash command of .help but /help, which Slack's
	own is (.help and @finbot help work)."""
	events = ['message.channels', 'message.groups'] if every_message else ['app_mention']
	events.append('message.im')
	posted = {'url': url} if url else {}
	commands = [{'command': '/' + command.name, 'description': command.description, 'should_escape': False,
		**({'usage_hint': command.arguments} if command.arguments else {}), **posted}
		for command in worker.slash_commands() if command.name not in RESERVED]
	return {
		'display_information': {'name': name, 'description': 'Stock prices, charts and Sharesight reports',
			'background_color': '#14181f'},
		'features': {
			'app_home': {'home_tab_enabled': False, 'messages_tab_enabled': True,
				'messages_tab_read_only_enabled': False},
			'bot_user': {'display_name': name, 'always_online': True},
			'slash_commands': commands,
		},
		'oauth_config': {'scopes': {'bot': sorted({*SCOPES, *(EVENT_SCOPES[event] for event in events)})}},
		'settings': {
			'event_subscriptions': {'bot_events': events, **({'request_url': url} if url else {})},
			'interactivity': {'is_enabled': True, **({'request_url': url} if url else {})},
			'org_deploy_enabled': False,
			'socket_mode_enabled': not url,
			'token_rotation_enabled': False,
		},
	}


def main(argv=None):
	"""Print the manifest the arguments ask for; 2 for a URL that is not HTTPS, which Slack takes no other."""
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
	parser.add_argument('--url', default='', help='HTTP mode: slackOutgoingWebhook, which Slack posts to')
	parser.add_argument('--name', default='finbot', help="the app's and the bot's name (default finbot)")
	parser.add_argument('--every-message', action='store_true', help='the bot sees every message in its channels')
	args = parser.parse_args(argv)
	if args.url and not args.url.startswith('https://'):
		print('slack_manifest: --url must be https://: Slack posts to no other', file=sys.stderr)
		return 2
	print(json.dumps(manifest(args.name, args.url, args.every_message), indent=2, ensure_ascii=False))
	return 0


if __name__ == '__main__':
	sys.exit(main())
