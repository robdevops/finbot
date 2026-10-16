"""What finbot says. A module per scheduled report: cal, cleanup (of the cache), message (a text, posted as it is),
milestone, performance, podcasts, price, rating, shorts, trades, and sharesight_warm and yahoo_warm (which fill the
cache), each with job(argv), which parses a job's arguments, and run(dest=None, **kwargs), which runs it, to the chat
that asked or whose job it is (dest); the scheduler runs them in the bot's process, and `.jobs run` runs one now. And
the chat-only reports: about (.help, .jobs), history (.history, .compare), holdings (.holdings, .who, .pie, .treemap,
.watchlist), profile (.SYMBOL) and rankings (.marketcap, .pe and the rest)."""
