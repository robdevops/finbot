# Slack

finbot reaches Slack through a Slack app of your own, whose bot posts each channel's scheduled reports there, charts
and all, and answers commands: `/price` and the rest ([the list](commands.md#supported-commands)), or as messages,
`@finbot price` (and `.price` in a direct message), with charts in its replies, ⏳ on a command's message while it
works (Slack has no typing notice for bots), and period buttons under a chart that redraw it in place.

## The bot

### Socket Mode or push mode?

The bot does the same either way. What differs is how it hears from Slack:

| | Socket Mode (the default) | Push mode |
|---|---|---|
| How messages, slash commands and button presses reach finbot | Over a socket that finbot opens to Slack | Slack posts them to your HTTPS server |
| Listens on the internet | No: finbot opens the socket to Slack | Yes, behind your HTTPS server: a domain name with a valid certificate |
| Python module | `websocket-client` (Debian: `python3-websocket`) | `waitress` (Debian: `python3-waitress`) |
| `finbot.env` keys | `slackBotToken`, `slackAppToken` | `slackBotToken`, `slackOutgoingWebhook`, `slackSigningSecret` |

`slackOutgoingWebhook` chooses the mode: set, push mode; empty, Socket Mode. The app's own _Socket Mode_ setting must
agree, as Slack sends to one or the other: to finbot's socket while it is on, to the Request URLs while it is off. To
switch, change both (paste the manifest for the other mode, which sets the app's side) and restart finbot.

### Socket Mode

1. Print the app's manifest, which sets up the whole app at once (the slash commands, the scopes, the events, the
   buttons, direct messages and Socket Mode): `util/slack_manifest.py`. The bot then hears the messages that mention it
   (`@finbot price`), its slash commands and direct messages. With `--every-message`, it hears every message in its
   channels instead of the mentions, so that `.price` works there without mentioning it; not both, or it would answer a
   mention twice.
2. At https://api.slack.com/apps choose _Create New App > From an app manifest_, pick your workspace, paste the
   manifest into the JSON tab, and _Create_.
3. Under _Basic Information > App-Level Tokens_, choose _Generate Token and Scopes_: name it (finbot, say), add the
   `connections:write` scope and _Generate_. Copy the token, which starts with `xapp-`, into `finbot.env` as
   `slackAppToken`.
4. Install the socket module: `sudo apt install python3-websocket` (or `pip install websocket-client`).
5. Go on with [installing the app](#installing-the-app), below.

```
slackAppToken=xapp-your-app-level-token
slackBotToken=xoxb-your-bot-token
```

### Push mode

Slack delivers the messages, the button presses and the slash commands to finbot over HTTPS. finbot listens on
`http://127.0.0.1:5000` (`ip` and `port` in `finbot.env`), so it needs a web server in front of it, on a domain name
with a valid certificate.

1. Put finbot behind an HTTPS server. An nginx example, which lets in only Amazon's addresses, where Slack's requests
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
2. In `finbot.env`, set `slackOutgoingWebhook` to the URL Slack should post to, and restart finbot, so that it can
   answer Slack's check of the URL in step 4.
3. Print the app's manifest with that URL, which Slack then posts everything to:
   `util/slack_manifest.py --url https://www.example.com:8443/slack` (and `--every-message`, as for
   [Socket Mode](#socket-mode)).
4. At https://api.slack.com/apps choose _Create New App > From an app manifest_, pick your workspace, paste the
   manifest into the JSON tab, and _Create_. Slack checks the URL, and finbot answers.
5. In the app's _Basic Information > App Credentials_, copy the _Signing Secret_ into `finbot.env` as
   `slackSigningSecret`. finbot checks Slack's signature on every request with it, and turns away a request signed more
   than five minutes earlier: a replay, or a server clock that is wrong.
   * The older _Verification Token_, set as `slackOutgoingToken`, still works in place of the signing secret, but
     Slack has deprecated it: the token travels in every request, where the signing secret never does.
6. Go on with [installing the app](#installing-the-app), below.

```
slackOutgoingWebhook=https://www.example.com:8443/slack
slackSigningSecret=0123456789abcdef0123456789abcdef
slackBotToken=xoxb-your-bot-token
```

### Installing the app

1. Under _Install App_ (or _OAuth & Permissions_), _Install to Workspace_, and copy the _Bot User OAuth Token_ into
   `finbot.env` as `slackBotToken`. finbot replies with it; without it, commands get no reply, and the log says so at
   startup and for each reply.
2. Restart finbot, and invite the bot to the channel: `/invite @finbot`. In Socket Mode the log says
   `slack: Socket Mode (no slackOutgoingWebhook)`.
3. Send `/help` (or `@finbot help`) in the channel, or in a direct message to the bot in its _Messages_ tab, where
   `.help` works too (and in the channels, with `--every-message`). Each channel has the default scheduled jobs,
   which `/jobs` changes ([Scheduling](scheduling.md)).

An app set up by hand before takes the manifest too: paste it into _Features > App Manifest_ and _Save Changes_;
Slack shows what changes, and asks to reinstall the app when its scopes do.

### Slash commands

Each command is a slash command, with its usage as Slack's hint: `/price`, `/dividend` and `/earnings`, `/buy` and
`/sell`, `/forwardpe`, `/stock` (or `/profile`), `/jobs` (or `/job`), and the rest.
Slack makes slash commands only from the app's settings, so they come in the manifest: when finbot's commands change,
print it again and paste it into _App Manifest_.

A slash command's answer goes to the channel or direct message it was sent in, as a message's does; the bot must be in
the channel (`/invite @finbot`). Slack shows no ⏳ while it works: there is no message of a slash command to put it
on.

A chart is uploaded with Slack's file upload API (`files.getUploadURLExternal`, then `files.completeUploadExternal`).
With its period buttons, it goes in a message of blocks: the report, the chart (uploaded into no channel, and shown by
its id) and the buttons. A press shows the chart for that period in the message in place of the last one: the upload of
that period from the last 15 minutes, for this message or another, with the report that came with it, or else the chart
drawn and uploaded anew (Slack cannot replace a file). An upload that no message shows is deleted once those 15 minutes
are past, so the bot's files do not pile up. If Slack will not show a chart with its buttons, the chart is uploaded into
the channel without them. If an upload fails, it is tried once more with the report's heading alone as its message, the
report following as text; if that fails too (a missing scope, say), the report goes out as text alone. The log says why.

`/jobs` lists the channel's jobs with the menu's buttons, as on Telegram; a button from a list that has since changed
puts the current list in its place.
