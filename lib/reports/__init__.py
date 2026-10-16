"""What finbot says. A module per scheduled report: cal, cleanup (of the cache), milestone, performance, podcasts,
price, rating, reminder, shorts, trades, and sharesight_warm and yahoo_warm (which fill the cache), each with
job(argv), which parses its schedule line, and run(dest=None, **kwargs), which runs it, to the chat that asked or
whose job it is (dest); the scheduler runs them in the bot's process, and `.jobs run` runs one now. And the
chat-only reports: about (.help, .jobs), history (.history, .compare), holdings (.holdings, .who, .pie, .watchlist),
profile (.SYMBOL) and rankings (.marketcap, .pe and the rest)."""
