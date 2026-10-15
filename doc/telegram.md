# Telegram

finbot talks to Telegram as a bot user that you create with BotFather. The same bot can post the scheduled reports
only, or also answer commands in your chats: the second builds on the first.

## Reports only, or the interactive bot?

| | Reports only | Interactive bot |
|---|---|---|
| Scheduled reports: trades, price alerts, earnings and dividend dates, performance and the rest | ✓ | ✓ |
| Charts with the reports | ✓ | ✓ |
| Chat commands: `.price`, `.history`, `.performance` and the rest ([the list](../README.md#supported-commands)) | ✗ | ✓ |
| Period buttons under charts, and `.jobs` buttons | ✗ | ✓ |
| "typing…" while a command works | ✗ | ✓ |
| A keyboard of the common commands in a direct chat with the bot | ✗ | ✓ |
| Public HTTPS server | Not needed | Needed: a domain name with a valid certificate |
| `finbot.env` keys | `telegramBotToken`, `telegramChatID` | Those two, plus `telegramOutgoingWebhook` and `telegramOutgoingToken` |

Start with [Reports only](#reports-only). For commands, go on to [Interactive bot](#interactive-bot) afterwards.

## Reports only

1. Create the bot: message [@BotFather](https://telegram.me/BotFather), send `/newbot` and answer its questions. It
   replies with the bot's token: put it in `finbot.env` as `telegramBotToken`.
2. Add the bot to the group or channel the reports should go to. In a channel, make it an administrator, so that it can
   post.
3. Stop strangers adding your bot to their groups: send BotFather `/setjoingroups`, pick the bot and choose `Disable`.
   Do this after step 2, as it stops you adding the bot to groups too.
4. Put the chat's id in `finbot.env` as `telegramChatID`.
   * A group's id is negative. A channel's or a supergroup's is negative and 13 characters long: prepend `-100` if
     yours is shorter.
   * To find it, send `/start@<your bot's username>` in the chat, then open
     `https://api.telegram.org/bot<telegramBotToken>/getUpdates` in a browser and look for `"chat":{"id":`. This works
     only while the bot has no webhook, so before you set up the interactive bot.
   * A group's id changes when Telegram turns it into a supergroup, which some changes to its settings do. Update
     `telegramChatID` then: finbot does not follow the change.
5. Restart finbot (`sudo systemctl restart finbot`). The scheduled reports now arrive in the chat.

```
telegramBotToken=0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA
telegramChatID=-1001000000000
```

## Interactive bot

Telegram delivers the messages in your chats, and each button press, to finbot over HTTPS. finbot listens on
`http://127.0.0.1:5000` (`ip` and `port` in `finbot.env`), so it needs a web server in front of it, on a domain name
with a valid certificate. Telegram posts only to ports 443, 80, 88 and 8443.

1. Set up the bot for [reports only](#reports-only), above.
2. Let the bot read the chat: make it an administrator of the group. A bot that is not an administrator sees only the
   commands that start with `/`, and finbot's start with `.`. Alternatively, send BotFather `/setprivacy` and choose
   `Disable`.
3. Put finbot behind an HTTPS server. An nginx example, which lets in only Telegram's addresses:
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
4. In `finbot.env`, set `telegramOutgoingWebhook` to the URL Telegram should post to, and `telegramOutgoingToken` to a
   password of your choosing: 1 to 256 characters, of letters, digits, `_` and `-`. Telegram sends the password with
   every update, and finbot turns away a request without it.
5. Restart finbot. As it starts, it registers the URL with Telegram, unregistering it first, which also wakes up a stale
   connection. If Telegram refuses, finbot does not start, and the log says why.
6. Send `.help` in the chat. In a direct chat with the bot, the reply also brings a keyboard of the common commands.

```
telegramBotToken=0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAA
telegramChatID=-1001000000000
telegramOutgoingWebhook=https://www.example.com:8443/telegram
telegramOutgoingToken=a-long-random-password
```
