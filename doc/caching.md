# Caching

Many objects are cached for 6 hours by default (`cache_seconds`). Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache=True
cache_seconds=21600
performance_cache_seconds=2400
```

`performance_cache_seconds` (default 40 minutes) is the cache lifetime of Sharesight performance reports.

Charts are cached by what they show (with `cache=True`): the same chart, for another chat, a later run or a period button, is drawn once, and a chart of new figures is a new chart, so a cached one is never stale. The weekly system job `cleanup` removes cache files after 30 days. The charts were drawn with matplotlib before 17 Oct 2026, and an install from then may delete the `matplotlib` folder it left in `DATA_DIR/cache`.

A chart is uploaded once where the network lets finbot show it again by its id: on Telegram the file id of each chart sent is kept 30 days (`finbot_telegram_photo_*` files, by chart and bot), and on Slack an upload is shown again for 30 minutes (see [Slack](slack.md)). A period or portfolio pressed again then shows without an upload; a period pressed again within 30 minutes of being shown in the chat, on Telegram (`finbot_telegram_view_*` files) and Slack, is not even built or drawn: the chart shown then comes back with its report. With `telegram_preload_chat` or `slack_preload_chat` set, the other periods and portfolios of a chart that goes out are uploaded to that private chat ahead of any press (see [Telegram](telegram.md#preloading-charts)). A file id Telegram no longer takes gives way to an upload; with `cache=False` every chart is uploaded.

Each Sharesight holdings report also leaves `finbot_sharesight_largest.json`, what the portfolio's holdings are worth in US dollars, which `/price` with no symbol reads to start on your biggest holding (see [Commands](commands.md#price)). It is rewritten as the reports are fetched, so the `sharesight_warm` job keeps it current, and it survives a restart (a start only fills it, from the holdings reports the cache already holds, when it is missing, so the first run after an update need not wait for the job); with `cache=False` there is none, and `/price` starts on the first ticker.

Short Man's CSV of ASX short interest, which `/shorts` reads, is cached for `cache_seconds` too (`finbot_shortman.json`). Yahoo's cookie and crumb (for 14 days) and Sharesight's access token (until it expires) are kept whatever `cache` says, and each is renewed at once when its service refuses it.

To flush the cache, so that what it holds is fetched afresh, run `util/flush.py` with the files to delete, by when they were written. With no argument it prints its help:
```
util/flush.py --before 180s     # the files written more than 180 seconds ago
util/flush.py --after 24h       # the files written in the last 24 hours
util/flush.py --after 7d        # ... in the last 7 days (3m: 3 months, 1y: a year)
util/flush.py all               # every file
sudo docker compose exec finbot util/flush.py all    # in Docker
```
A time is a number and `s` (seconds), `h` (hours), `d` (days), `w` (weeks), `m` (months) or `y` (years). It deletes only finbot's files in `DATA_DIR/cache` (Yahoo's and Sharesight's answers, the charts, the Yahoo cookie), never the state in `DATA_DIR` (the watchlists, jobs, plans, seen trades and ratings), and the bot can keep running: it fetches a file that is gone afresh. Run it as the user finbot runs as, or as root, with finbot's data dir: `DATA_DIR` as `finbot.env` sets it (`sudo DATA_DIR=/var/lib/finbot util/flush.py all`), `--data-dir /var/lib/finbot`, or else `var/` in the checkout.

Signalling the bot flushes every file too, and then runs both warm jobs (`sharesight_warm`, `yahoo_warm`) at once to fill the cache again: `sudo systemctl kill -s USR1 finbot`, or `sudo docker compose kill -s USR1 finbot`. The log says `cache: flushed N files`, then `cache: warm jobs done`.

Two system jobs keep the caches full, each on a fixed interval shorter than the cache lifetime, so that chat requests do not wait on Sharesight or Yahoo (see [Scheduling](scheduling.md)): `sharesight_warm` fetches the Sharesight portfolio list and each portfolio's holdings report afresh every 30 minutes (`performance_cache_seconds`: 40 minutes), and `yahoo_warm` the price history of every stock followed every 4 hours (`cache_seconds`: 6 hours). Neither fetches anything with `cache=False`, and `sharesight_warm` nothing without Sharesight configured. A refresh that fails is logged, the previous cache keeps being served while fresh, and the next run tries again. A flush runs both at once (see above).
