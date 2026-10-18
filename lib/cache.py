"""Cache files in DATA_DIR/cache: copies of Yahoo and Sharesight answers and of drawn charts, each good for so many
seconds. Anything here may be deleted at any time (cleanup.py, a flush); what must last lives in lib/state.py."""
import io
import json
import math
import os
import tempfile
import threading
import time
from pathlib import Path

from lib import config
from lib import log


_locks = {} # file path -> the lock held while that file is fetched or edited (lock)
_locks_lock = threading.Lock()


def path(name):
	"""Where a cache file lives."""
	return config.env.cache_dir + '/' + name


def lock(where):
	"""The lock of a file by its path, the same one each time: whoever holds it fetches or edits that file alone."""
	with _locks_lock:
		return _locks.setdefault(where, threading.Lock())


def age(name):
	"""Seconds since the cache file was written, or None when it does not exist."""
	try:
		return time.time() - os.path.getmtime(path(name))
	except OSError:
		return None


def _within(name, seconds):
	"""(whether the cache file was written less than `seconds` ago, cache_seconds when None; the seconds it has left,
	or None when there is no such file)."""
	written = age(name)
	limit = config.settings.cache_seconds if seconds is None else seconds
	return written is not None and written < limit, None if written is None else limit - written


def _fresh(name, seconds):
	"""The cache file's path if written less than `seconds` ago (cache_seconds when None), else None."""
	fresh, left = _within(name, seconds)
	where = path(name)
	if not fresh:
		log.debug("cache miss:", where)
		return None
	log.debug(f"cache hit: {where} TTL: {left:.0f}s")
	return where


def _read_fresh(name, seconds, read):
	"""read(path) of the cache file if fresh, else None; also None if it goes (cleanup, a flush) after the check, or
	does not parse (empty, or cut short): the next fetch replaces it."""
	where = _fresh(name, seconds)
	if not where:
		return None
	try:
		return read(Path(where))
	except FileNotFoundError:
		return None
	except ValueError as e:
		log.warn(f"cache: {where} does not parse, taking it for a miss:", e)
		return None


def read(name, seconds=None):
	"""A cache file's JSON, or None when it is missing or older than `seconds` (cache_seconds when None)."""
	return _read_fresh(name, seconds, lambda where: json.loads(where.read_text(encoding="utf-8")))


def read_bytes(name, seconds=None):
	"""A cache file's bytes (as a file object), or None when it is missing or older than `seconds`."""
	return _read_fresh(name, seconds, lambda where: io.BytesIO(where.read_bytes()))


def load(name):
	"""A cache file's JSON whatever its age, or None: for an answer with its own expiry (the Sharesight token)."""
	return read(name, math.inf)


def cached(name, seconds, fetch):
	"""fetch()'s answer (JSON), as sent: from the cache file `name` while it is under `seconds` old (cache_seconds when
	None) and the cache setting is on, else fetched and written there unless empty. Answers are cached as sent, not
	parsed, so that a parser fix needs no flush. Callers that miss the same file at once (every chat's job at the same
	minute) wait for the first one's fetch and read what it wrote."""
	if not config.settings.cache:
		return fetch()
	if data := read(name, seconds):
		return data
	with lock(path(name)):
		if _within(name, seconds)[0] and (data := read(name, seconds)): # fetched meanwhile, by whoever held the lock
			return data
		data = fetch()
		if data:
			write(name, data)
	return data


def write(name, data):
	"""Write a cache file's JSON, compact: nobody reads it but finbot (a 10-year chart takes a third of the space, and
	parses faster). See write_file."""
	where = path(name)
	log.debug("cache write:", where)
	write_file(where, json.dumps(data, separators=(',', ':')).encode('utf-8'))


def write_bytes(name, data):
	"""Write a cache file's bytes from a file object (a drawn chart)."""
	data.seek(0)
	write_file(path(name), data.getvalue())


def write_file(where, data, sync=False):
	"""Write `data` (bytes) to `where` whole or not at all, mode 0640: it goes to a temp file beside it, which then
	replaces the file, so a failure part way (a full disk, a kill) leaves the old file as it was. sync=True also flushes
	it to disk, for state that must survive a power cut. The process umask is left alone."""
	where = os.path.realpath(where) # through a symlink, as an in-place write would
	fd, tmp = tempfile.mkstemp(dir=os.path.dirname(where), prefix=os.path.basename(where) + '.', suffix='.tmp')
	try:
		with os.fdopen(fd, 'wb') as f:
			f.write(data)
			if sync:
				f.flush()
				os.fsync(f.fileno())
		os.chmod(tmp, 0o640)
		os.replace(tmp, where)
	except BaseException:
		try:
			os.unlink(tmp)
		except OSError:
			pass
		raise
