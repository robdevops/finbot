# Discord

finbot talks to Discord as the bot user of a Discord application that you create in the Developer Portal. The bot
posts each channel's scheduled reports there and answers commands: slash commands (`/price`) in both modes, and
messages (`.price`, `@finbot price`) over the gateway API.

## Gateway API mode or push mode?

The bot does the same either way. What differs is how it hears from Discord:

| | Gateway API mode (the default) | Push mode |
|---|---|---|
| How commands and button presses reach finbot | Over Discord's gateway API, a connection finbot keeps open to Discord | Discord posts them to your HTTPS server |
| Listens on the internet | No: finbot opens the connection to Discord | Yes, behind your HTTPS server: a domain name with a valid certificate |
| Commands | Slash commands (`/price`), and messages (`.price`, `@finbot price`) | Slash commands (`/price`): Discord posts no messages |
| Python modules | `discord.py` (Debian: `python3-discord`) | `PyNaCl` and `waitress` (Debian: `python3-nacl`, `python3-waitress`) |
| `finbot.env` keys | `discordBotToken` | `discordBotToken`, `discordOutgoingWebhook` and `discordPublicKey` |

In both: the scheduled reports with their charts; period buttons under charts and the buttons of the `/jobs` menu,
which redraw their message in place; linked tickers, without link previews and without pinging anyone;
and direct messages with the bot. A command in a message shows "finbot is typing…" while it works; a slash command
shows Discord's "finbot is thinking…" until its answer takes its place.

`discordOutgoingWebhook` chooses the mode: set, push mode; empty, gateway API mode. Discord sends the slash commands
and button presses to the app's _Interactions Endpoint URL_ while it is set, and over the gateway API while it is
empty, so change both, and restart finbot, to switch.

## Gateway API mode

1. In the [Developer Portal](https://discord.com/developers/applications), choose _New Application_ and name it
   (finbot, say).
2. Under _Bot_:
   * _Reset Token_, and copy the token into `finbot.env` as `discordBotToken`.
   * Turn _Message Content Intent_ on, for the bot to read `.price` and `@finbot price` in your channels. Without it,
     Discord refuses the connection, and the log says so.
   * Turn _Public Bot_ off, so that only you can add the bot to servers.
3. Under _OAuth2 > URL Generator_, tick the scopes `bot` and `applications.commands`, then the bot permissions _View
   Channels_, _Send Messages_, _Attach Files_ and _Read Message History_. Open the URL it makes, and add the bot to your
   server.
4. Install discord.py: `sudo apt install python3-discord` (or `pip install discord.py`; Docker and the Python quick
   start have it).
5. Restart finbot (`sudo systemctl restart finbot`). As it starts, it registers the slash commands, which can take a
   few minutes to show in Discord the first time, and the log says `discord: gateway (no discordOutgoingWebhook)`.
6. Send `/help` (or `.help`) in the channel, or in a direct message to the bot. Each channel has the default scheduled
   jobs, which `/jobs` changes ([Scheduling](scheduling.md)).

```
discordBotToken=your-bot-token
```

## Push mode

Discord posts the slash commands and button presses to finbot over HTTPS, each signed with the app's key. finbot
listens on `http://127.0.0.1:5000` (`ip` and `port` in `finbot.env`), so it needs a web server in front of it, on a
domain name with a valid certificate. The bot shows as offline in Discord, as it keeps no connection to the gateway
API.

1. Set up the bot as for [gateway API mode](#gateway-api-mode), steps 1 to 3. The _Message Content Intent_ is not
   needed.
2. Install PyNaCl, which checks the signatures, and waitress, the web server: `sudo apt install python3-nacl
   python3-waitress` (or `pip install PyNaCl waitress`).
3. Put finbot behind an HTTPS server. An nginx example:
   ```
   server {
   	listen 8443 ssl;

   	server_name         www.example.com;
   	ssl_certificate     /etc/letsencrypt/live/www.example.com/fullchain.pem;
   	ssl_certificate_key /etc/letsencrypt/live/www.example.com/privkey.pem;
   	ssl_protocols       TLSv1.2 TLSv1.3;

   	location /discord {
   		proxy_pass http://127.0.0.1:5000/discord;
   	}
   }
   ```
   Discord publishes no list of its addresses, so the signature on each request is what keeps strangers out: finbot
   refuses a request without a good one.
4. In `finbot.env`, set `discordOutgoingWebhook` to the URL Discord should post to, and `discordPublicKey` to the app's
   _General Information > Public Key_. Restart finbot, so that it can answer Discord's check in the next step.
5. In the Developer Portal, set _General Information > Interactions Endpoint URL_ to the same URL, and _Save Changes_.
   Discord checks it at once, sending a signed request and one with a bad signature, which finbot refuses as Discord
   expects.
6. Send `/help` in the channel, or in a direct message to the bot.

```
discordBotToken=your-bot-token
discordOutgoingWebhook=https://www.example.com:8443/discord
discordPublicKey=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

## Slash commands

finbot registers a slash command for each line of `/help`, as it starts, and again only when the list has changed:
`/price`, `/dividend` and `/earnings`, `/buy` and `/sell`, `/forwardpe`, `/stock` (or `/profile`), `/jobs` (or `/job`),
and the rest. Each takes its arguments, if any, as one text option, as a message would: `/price` with `5 7d` is the
message `.price 5 7d`. They work in the server's channels and in a direct message with the bot.

While the arguments are typed, Discord shows finbot's suggestions, in both modes, for the word being typed:
* the command's keywords (`top`, `bottom`, `negative`, `sector`, `add`, `del`) and periods (`7d`, `3m`, `ytd`), until
  it has one;
* the portfolios, for the commands that take one;
* tickers, for the commands that take one: the channel's watchlist and the holdings. They come from the cache, never
  from Sharesight or Yahoo, so the suggestions come at once; the holdings are there once `sharesight_warm` has run;
* for `/jobs`: `add`, `run`, `toggle`, `del`, `next` and `system`; after `run` or `toggle` the channel's job numbers,
  each with its name (after `del`, those of the jobs it added); after `add` the reports, each with what it takes, then
  what the report takes and the words of a schedule.

A message holds up to 2,000 characters, so a long report arrives as several messages. A chart goes as an attachment of
the message that carries its report, with its period buttons under it.
