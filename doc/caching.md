# Caching

Many objects are cached for 12 hours by default (`cache_seconds`). Cache is controlled by the settings below. Trades IDs are stored on disk, but trade queries generally don't result in a cache hit for functional reasons.
```
cache=True
cache_seconds=43200
performance_cache_seconds=2400
```

`performance_cache_seconds` (default 40 minutes) is the cache lifetime of Sharesight performance reports.

Charts are cached by what they show (with `cache=True`): the same chart, for another chat, a later run or a period button, is drawn once, and a chart of new figures is a new chart, so a cached one is never stale. The weekly system job `cleanup` removes cache files after 30 days.

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

Two system jobs keep the caches full, each on a fixed interval shorter than the cache lifetime, so that chat requests do not wait on Sharesight or Yahoo (see [Scheduling](scheduling.md)): `sharesight_warm` fetches the Sharesight portfolio list and each portfolio's holdings report afresh every 30 minutes (`performance_cache_seconds`: 40 minutes), and `yahoo_warm` the price history of every stock followed every 8 hours (`cache_seconds`: 12 hours). Neither fetches anything with `cache=False`, and `sharesight_warm` nothing without Sharesight configured. A refresh that fails is logged, the previous cache keeps being served while fresh, and the next run tries again. A flush runs both at once (see above).
