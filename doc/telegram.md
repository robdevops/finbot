# Telegram

finbot talks to Telegram as a bot user that you create with BotFather.

## Pull mode or push mode?

The bot posts the scheduled reports and answers commands in your chats either way. What differs is how it hears from
Telegram:

| | Pull mode (the default) | Push mode |
|---|---|---|
| How messages and button presses reach finbot | finbot asks Telegram for them (long polling) | Telegram posts them to your HTTPS server |
| Listens on the internet | No: finbot only makes outgoing requests | Yes, behind your HTTPS server: a domain name with a valid certificate, on port 443, 80, 88 or 8443 |
| `finbot.env` keys | `telegramBotToken` | `telegramBotToken`, `telegramOutgoingWebhook` and `telegramOutgoingToken` |

Everything else is the same in both: the scheduled reports with their charts, the chat commands (`/price`, `/movers`,
`/performance` and the rest, [the list](commands.md#supported-commands), or as messages, `.price`), period buttons
under charts and the buttons of the `/jobs` menu, "typing…" while a command works, and a keyboard of the
common commands in a direct chat with the bot.

A chart is uploaded once: Telegram gives it a file id, which finbot keeps (in `DATA_DIR/cache`, 30 days) and sends the
next time the same chart goes out, instead of the image. A period or portfolio pressed again, or the same scheduled chart
for several chats, then shows without an upload. A period pressed again within 30 minutes of being shown in the chat
shows that chart again with the report it came with: nothing is fetched or drawn either.

As finbot starts, it sets the bot's command menu, which Telegram shows when `/` is typed: each command with its usage
(`/price`, `/pe`, `/stock` and the rest). `/profile` and `/job`, the second names of `/stock` and `/jobs`, are
left out of the menu (as on Slack and Discord), and work when typed, as every name of a command does. In a group, `/price@finbot_bot` is the same
as `/price`.

`telegramOutgoingWebhook` chooses the mode: set, push mode; empty, pull mode. A restart switches. As finbot starts in
pull mode it deletes the webhook, and in push mode it sets it; the updates sent meanwhile are kept by Telegram and
arrive after the switch.

## Pull mode

1. Create the bot: message [@BotFather](https://telegram.me/BotFather), send `/newbot` and answer its questions. It
   replies with the bot's token: put it in `finbot.env` as `telegramBotToken`.
2. Add the bot to the groups or channels it should work in, or message it directly. In a channel, make it an
   administrator, so that it can post.
3. Optionally, for commands as plain messages (`.price`) in a group: let the bot read the chat, by making it an
   administrator of the group, or by sending BotFather `/setprivacy` and choosing `Disable`. Without that, the bot sees
   only the commands that start with `/`, which is all that the slash commands need.
4. Stop strangers adding your bot to their groups: send BotFather `/setjoingroups`, pick the bot and choose `Disable`.
   Do this after step 2, as it stops you adding the bot to groups too.
5. Start finbot (`sudo systemctl restart finbot`). The log says `telegram: long polling for updates`.
6. Send `/help` in the chat. In a direct chat with the bot, the reply also brings a keyboard of the common commands.
   Each chat has the default scheduled jobs, which `/jobs` changes ([Scheduling](scheduling.md)).

```
telegramBotToken=0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA
```

## Push mode

Telegram delivers the messages in your chats, and each button press, to finbot over HTTPS. finbot listens on
`http://127.0.0.1:5000` (`ip` and `port` in `finbot.env`), so it needs a web server in front of it, on a domain name
with a valid certificate. Telegram posts only to ports 443, 80, 88 and 8443.

1. Set up the bot as for [pull mode](#pull-mode), above.
2. Put finbot behind an HTTPS server. An nginx example, which lets in only Telegram's addresses:
   ```
   server {
   	listen 8443 ssl;
   	deny all;

   	server_name         www.example.com;
   	ssl_certificate     /etc/letsencrypt/live/www.example.com/fullchain.pem;
   	ssl_certificate_key /etc/letsencrypt/live/www.example.com/privkey.pem;
   	ssl_protocols       TLSv1.2 TLSv1.3;

   	location /telegram {
   		proxy_pass http://127.0.0.1:5000/telegram;
   		include /etc/nginx/telegram_subnets;
   		deny all;
   	}
   }
   ```
   `util/nginx_telegram_cron` writes `/etc/nginx/telegram_subnets`, an `allow` line for each of Telegram's networks,
   and reloads nginx. Run it once as root before nginx loads this configuration, or put it in `/etc/cron.daily/` to
   keep the list current. `util/iptables_telegram_cron` goes further, in the firewall: of the traffic to ports 443 and
   8443 it lets in only Telegram's networks on 8443 and drops the rest, so nothing else can be served on those ports.
3. In `finbot.env`, set `telegramOutgoingWebhook` to the URL Telegram should post to, and `telegramOutgoingToken` to a
   password of your choosing: 1 to 256 characters, of letters, digits, `_` and `-`. Telegram sends the password with
   every update, and finbot turns away a request without it.
4. Restart finbot. As it starts, it sets the webhook again, deleting it first, which also wakes up a stale connection.
   If Telegram refuses, finbot does not start, and the log says why.
5. Send `/help` in the chat. In a direct chat with the bot, the reply also brings a keyboard of the common commands.

```
telegramBotToken=0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA
telegramOutgoingWebhook=https://www.example.com:8443/telegram
telegramOutgoingToken=a-long-random-password
```

## Preloading charts

A press on a chart's period or portfolio buttons shows the new chart at once when Telegram has it (a file id finbot
kept), and otherwise uploads it first. finbot can upload those charts before anyone presses: as a chart with period or
portfolio buttons goes out, it draws the chart's other periods and portfolios in the background, and with
`telegram_preload_chat` set it also sends each one to a private chat of yours, keeping its file id.

1. Make a private channel and add the bot as an administrator that may post, or a private group with the bot in it.
2. Find its id: send `/help` in the group, and the log line shows it (`Telegram -1001234567890 @you /help`). A
   channel's id starts with `-100`: Telegram Web (`web.telegram.org/a/`) shows it at the end of the address while the
   channel is open.
3. Set `telegram_preload_chat=-1001234567890` in `settings.conf` and reload.

The posts are silent, with no caption, and stay. Every chart finbot preloads goes there, whichever chat it was drawn
for, so keep the chat private. Preloads go one at a time, `preload_gap` seconds apart: 3 by default, which keeps within the 20 messages a
minute that Telegram takes in a group or channel. A private chat with the bot takes about one a second, so set
`preload_gap=1` if that is your preload chat. If Telegram answers "too many requests", finbot waits the time it asks
and sends the chart once more. A preload that fails is a warning in the log, and that chart's others are not
preloaded; the next chart that goes out tries again.
