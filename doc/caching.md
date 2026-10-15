# Caching

Many objects are cached for 12 hours by default (`cache_seconds`). Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache=True
cache_seconds=43200
performance_cache_seconds=2400
```

`performance_cache_seconds` (default 40 minutes) is the cache lifetime of Sharesight performance reports.

Charts are cached by what they show (with `cache=True`): the same chart, for another chat, a later run or a period button, is drawn once, and a chart of new figures is a new chart, so a cached one is never stale. The weekly system job `cleanup` removes cache files after 30 days.

To flush the cache, so that everything is fetched afresh, signal the running bot: it deletes its cache files (Yahoo and Sharesight
answers, charts, the Yahoo cookie) and keeps its state (watchlist, jobs, seen trades, ratings), then runs both warm jobs
(`sharesight_warm`, `yahoo_warm`) straight away to fill the cache again. There is no `systemctl flush`, since systemctl takes no custom verbs; any of these does it:
```
sudo systemctl kill -s USR1 finbot          # systemd
sudo systemctl start finbot-flush           # the same, once finbot-flush.service is installed (see below)
sudo docker compose kill -s USR1 finbot     # Docker
kill -USR1 <pid of bot.py>                  # anything else
```
The log says `cache: flushed N files`, then `cache: warm jobs done` once the cache is full again. To install the `finbot-flush` shortcut: `sudo cp -v finbot-flush.service /etc/systemd/system/ &&
sudo systemctl daemon-reload`. `finbot.service` itself needs no change. With the bot stopped, deleting the files in `DATA_DIR/cache` does the same.

Two system jobs keep the caches full, each on a fixed interval shorter than the cache lifetime, so that chat requests do not wait on Sharesight or Yahoo (see [Scheduling](scheduling.md)): `sharesight_warm` fetches the Sharesight portfolio list and each portfolio's holdings report afresh every 30 minutes (`performance_cache_seconds`: 40 minutes), and `yahoo_warm` the price history of every stock followed every 8 hours (`cache_seconds`: 12 hours). Neither fetches anything with `cache=False`, and `sharesight_warm` nothing without Sharesight configured. A refresh that fails is logged, the previous cache keeps being served while fresh, and the next run tries again. A flush runs both at once (see above).
