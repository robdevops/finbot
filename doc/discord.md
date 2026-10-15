# Discord

finbot reaches Discord through a webhook, which posts the scheduled reports into a channel. A webhook only posts, so
there is no choice to make: on Discord, finbot does not answer commands. For commands, set up finbot on
[Telegram](telegram.md) or [Slack](slack.md) as well.

What the webhook carries:
* the scheduled reports: trades, price alerts, earnings and dividend dates, performance and the rest;
* their charts, attached to the messages;
* linked tickers, without link previews, and without pinging anyone.

## Webhook

1. In Discord, open _Server Settings > Integrations > Webhooks_ and choose _New Webhook_.
2. Name it (finbot, say), pick the channel for the reports, and _Copy Webhook URL_.
3. Put the URL in `finbot.env` as `discord_webhook`.
4. Restart finbot (`sudo systemctl restart finbot`). The scheduled reports now arrive in the channel.

```
discord_webhook=https://discord.com/api/webhooks/1009998000000000000/aaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbb
```

A URL ending in `/slack`, from older setups, works as it is: finbot uses Discord's own endpoint either way. A message
holds up to 2,000 characters, so a long report arrives as several messages.
