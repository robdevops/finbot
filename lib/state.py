"""State files in DATA_DIR: what must last from one run to the next (each chat's jobs, the watchlist, plans, seen
trades, ratings, record highs, the schedule's last runs, chart button refs, keyboard versions, seen podcast episodes).
Written whole or not at all, and flushed. A report's record of what it told each chat is a file of its own, holding one
record per chat ({'chats': {chat key: record}}): see load_for and edit_for."""
import contextlib
import copy
import json
import threading
from pathlib import Path

from lib import cache
from lib import config

_locks = {} # file name -> the lock edit() holds while it changes the file
_locks_lock = threading.Lock()


def path(name):
	"""Where a state file lives."""
	return config.env.data_dir + '/' + name


def load(name, default=None):
	"""A state file's JSON, or `default` when there is none yet."""
	where = Path(path(name))
	return json.loads(where.read_text(encoding="utf-8")) if where.is_file() else default


def save(name, data):
	"""Write a state file's JSON, whole or not at all, flushed to disk (cache.write_file)."""
	cache.write_file(path(name), json.dumps(data, indent=4).encode('utf-8'), sync=True)


def _lock(name):
	"""The lock edit() holds while it changes the file `name`."""
	with _locks_lock:
		return _locks.setdefault(name, threading.Lock())


def load_for(chat, name, default):
	"""A chat's record (by its key) in a state file that holds one per chat, or `default` when it has none yet."""
	return copy.deepcopy(load(name, {}).get('chats', {}).get(chat, default))


@contextlib.contextmanager
def edit_for(chat, name, default):
	"""Change a chat's record (by its key) in a state file that holds one per chat, as edit() changes a file."""
	with edit(name, {}) as data:
		yield data.setdefault('chats', {}).setdefault(chat, copy.deepcopy(default))


@contextlib.contextmanager
def edit(name, default):
	"""Change a state file in place: `with state.edit(name, {}) as data: data[key] = value`. The file is read as the
	block starts (a copy of `default` when there is none yet) and written as the block ends without an error, if the
	block changed it. Meanwhile no other edit of the same file runs in this process, so two chats changing it at once
	both count. Keep slow work, a network call say, outside the block."""
	with _lock(name):
		data = load(name, copy.deepcopy(default))
		before = copy.deepcopy(data)
		yield data
		if data != before:
			save(name, data)
