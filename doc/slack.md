# Slack

finbot reaches Slack through a Slack app of your own. The app's incoming webhook posts the scheduled reports into a
channel; the app's bot also answers commands. The bot builds on the webhook, which carries the scheduled reports unless
the bot posts them itself, charts and all (`slackChannelID`).

## Incoming webhook, or the interactive bot?

| | Incoming webhook | Interactive bot (with the webhook) |
|---|---|---|
| Scheduled reports: trades, price alerts, earnings and dividend dates, performance and the rest | ✓, as text | ✓, as text through the webhook, or with their charts as the bot (`slackChannelID`) |
| Chat commands: `.price`, `@finbot price` and the rest ([the list](../README.md#supported-commands)) | ✗ | ✓ |
| Charts in the replies to commands | n/a | ✓, uploaded into the channel |
| A sign that finbot is working on a command | ✗ | ✓: ⏳ on the command's message, Slack having no typing notice for bots |
| Period buttons under a chart, which redraw it for that period in place | ✗ | ✓ |
| Public HTTPS server | Not needed | Not needed in Socket Mode (the default); needed in HTTP mode |
| `finbot.env` keys | `slack_webhook` | That one, plus `slackBotToken` and `slackAppToken` (Socket Mode) or `slackOutgoingWebhook` and `slackSigningSecret` (HTTP mode); and `slackChannelID`, for charts in the scheduled reports |

Start with [Incoming webhook](#incoming-webhook). For commands, go on to [Interactive bot](#interactive-bot)
afterwards, in the same app.

## Incoming webhook

1. Create the app: at https://api.slack.com/apps choose _Create New App > From scratch_, name it (finbot, say) and pick
   your workspace.
2. Under _Features > Incoming Webhooks_, turn _Activate Incoming Webhooks_ on, then _Add New Webhook to Workspace_ and
   pick the channel for the reports.
3. Copy the webhook URL into `finbot.env` as `slack_webhook`.
4. Restart finbot (`sudo systemctl restart finbot`). The scheduled reports now arrive in the channel.

```
slack_webhook=https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA
```

An incoming webhook takes text only, so the scheduled reports come without charts. The [interactive bot](#interactive-bot)
can post them with their charts.

## Interactive bot

### Socket Mode or HTTP mode?

The bot answers commands either way. What differs is how it hears from Slack:

| | Socket Mode (the default) | HTTP mode |
|---|---|---|
| How messages and button presses reach finbot | Over a socket that finbot opens to Slack | Slack posts them to your HTTPS server |
| Public HTTPS server | Not needed | Needed: a domain name with a valid certificate |
| Python module | `websocket-client` (Debian: `python3-websocket`) | `waitress` (Debian: `python3-waitress`) |
| `finbot.env` keys | `slackBotToken`, `slackAppToken` | `slackBotToken`, `slackOutgoingWebhook`, `slackSigningSecret` |

`slackOutgoingWebhook` chooses the mode: set, HTTP mode; empty, Socket Mode. The app's own _Socket Mode_ setting must
agree, as Slack sends to one or the other: to finbot's socket while it is on, to the Request URLs while it is off. To
switch, change both and restart finbot.

### Socket Mode

1. Set up the [incoming webhook](#incoming-webhook), above.
2. Under _Settings > Socket Mode_, turn _Enable Socket Mode_ on. Slack asks for an app-level token: name it (finbot,
   say) and _Generate_; it has the `connections:write` scope it needs. Copy the token, which starts with `xapp-`, into
   `finbot.env` as `slackAppToken`. It is also under _Basic Information > App-Level Tokens_.
3. Install the socket module: `sudo apt install python3-websocket` (or `pip install websocket-client`).
4. Go on with [the events, the buttons and the bot token](#the-events-the-buttons-and-the-bot-token), below. In Socket
   Mode there is no Request URL to enter.

```
slack_webhook=https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA
slackAppToken=xapp-your-app-level-token
slackBotToken=xoxb-your-bot-token
slackChannelID=C0123456789
```

### HTTP mode

Slack delivers the messages that mention the bot (or every message in a channel, as you choose) to finbot over HTTPS.
finbot listens on `http://127.0.0.1:5000` (`ip` and `port` in `finbot.env`), so it needs a web server in front of it,
on a domain name with a valid certificate.

1. Set up the [incoming webhook](#incoming-webhook), above, and leave _Settings > Socket Mode_ off.
2. Put finbot behind an HTTPS server. An nginx example, which lets in only Amazon's addresses, where Slack's requests
   come from:
   ```
   server {
   	listen 8443 ssl;
   	deny all;

   	server_name         www.example.com;
   	ssl_certificate     /etc/letsencrypt/live/www.example.com/fullchain.pem;
   	ssl_certificate_key /etc/letsencrypt/live/www.example.com/privkey.pem;
   	ssl_protocols       TLSv1.2 TLSv1.3;

   	location /slack {
   		proxy_pass http://127.0.0.1:5000/slack;
   		include /etc/nginx/aws_subnets;
   		deny all;
   	}
   }
   ```
   `util/nginx_aws_cron` writes `/etc/nginx/aws_subnets`, an `allow` line for each of Amazon's networks, and reloads
   nginx. Run it once as root before nginx loads this configuration, or put it in `/etc/cron.daily/` to keep the list
   current.
3. In the app's _Basic Information > App Credentials_, copy the _Signing Secret_ into `finbot.env` as
   `slackSigningSecret`. finbot checks Slack's signature on every request with it, and turns away a request signed more
   than five minutes earlier: a replay, or a server clock that is wrong.
   * The older _Verification Token_, set as `slackOutgoingToken`, still works in place of the signing secret, but
     Slack has deprecated it: the token travels in every request, where the signing secret never does.
4. In `finbot.env`, set `slackOutgoingWebhook` to the URL Slack should post to, and restart finbot, so that it can
   answer Slack's check of the URL in the next steps.
5. Go on with [the events, the buttons and the bot token](#the-events-the-buttons-and-the-bot-token), below, entering
   this URL as the _Request URL_ where it asks for one.

```
slack_webhook=https://hooks.slack.com/services/XXXXXXXXXXX/YYYYYYYYYYY/AAAAAAAAmockupAAAAAAAAAAAA
slackOutgoingWebhook=https://www.example.com:8443/slack
slackSigningSecret=0123456789abcdef0123456789abcdef
slackBotToken=xoxb-your-bot-token
slackChannelID=C0123456789
```

### The events, the buttons and the bot token

1. Under _Event Subscriptions_:
   * Turn _Enable Events_ on. In HTTP mode, enter the URL as the _Request URL_: Slack checks it at once, and finbot
     answers.
   * Under _Subscribe to bot events_, add `app_mention`: the bot sees messages that mention it, such as
     `@finbot price`.
     * Or add `message.channels` instead, for the bot to see every message in its channels and answer the commands
       that start with `.`. Not both: the bot would answer a mention twice.
     * For direct messages to the bot, add `message.im` (Slack adds the `im:history` scope it needs), and tick
       _App Home > Allow users to send Slash commands and messages from the messages tab_.
   * _Save Changes_.
2. Under _Interactivity & Shortcuts_, turn _Interactivity_ on (in HTTP mode, with the same URL as the _Request URL_)
   and _Save Changes_. Slack sends finbot the presses of the period buttons under a chart; without it, Slack answers a
   press with an error.
3. Under _OAuth & Permissions > Scopes > Bot Token Scopes_, add `chat:write`, `files:write`, `files:read` and
   `reactions:write`. The upload of a chart needs both `files` scopes, and the ⏳ on a command that takes a while
   `reactions:write`.
4. At the top of _OAuth & Permissions_, _Install to Workspace_ (or _Reinstall to Workspace_ when you changed scopes of
   an installed app), and copy the _Bot User OAuth Token_ into `finbot.env` as `slackBotToken`. finbot replies with it;
   without it, commands get no reply, and the log says so at startup and for each reply.
5. Restart finbot, and invite the bot to the channel: `/invite @finbot`. In Socket Mode the log says
   `slack: Socket Mode (no slackOutgoingWebhook)`.
6. Send `@finbot help` in the channel (or `.help`, with `message.channels`).
7. For charts in the scheduled reports, set `slackChannelID` to the channel's id (in Slack, click the channel's name:
   the _Channel ID_, which starts with C, is at the bottom of _About_), and restart finbot. The bot then posts the
   scheduled reports there, as it posts its replies, and `slack_webhook` is no longer used.

A chart is uploaded with Slack's file upload API (`files.getUploadURLExternal`, then `files.completeUploadExternal`).
With its period buttons, it goes in a message of blocks: the report, the chart (uploaded into no channel, and shown by
its id) and the buttons. A press shows the chart for that period in the message in place of the last one: the upload of
that period from the last 15 minutes, for this message or another, with the report that came with it, or else the chart
drawn and uploaded anew (Slack cannot replace a file). An upload that no message shows is deleted once those 15 minutes
are past, so the bot's files do not pile up. If Slack will not show a chart with its buttons, the chart is uploaded into
the channel without them; if an upload fails (a missing scope, say), the report goes out as text. The log says why.

`.jobs` lists the scheduled commands with a button for each, as on Telegram; a button from a list that has since
changed puts the current list in its place.
