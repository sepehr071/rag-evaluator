"""In-memory cache for parsed JSON results with file mtime invalidation."""

import os
import threading
from collections import OrderedDict


class ResultsCache:
    """In-memory cache for parsed JSON results with file mtime invalidation."""

    def __init__(self, max_size=50):
        self._cache = OrderedDict()  # {filepath: (mtime, data)}
        self._lock = threading.Lock()
        self.max_size = max_size

    def get(self, filepath):
        """Get cached data if file hasn't changed, else return None."""
        with self._lock:
            if filepath in self._cache:
                cached_mtime, cached_data = self._cache[filepath]
                current_mtime = os.path.getmtime(filepath)
                if cached_mtime == current_mtime:
                    self._cache.move_to_end(filepath)
                    return cached_data
                else:
                    del self._cache[filepath]
            return None

    def set(self, filepath, data):
        """Cache parsed data with current file mtime."""
        with self._lock:
            mtime = os.path.getmtime(filepath)
            self._cache[filepath] = (mtime, data)
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def invalidate(self, filepath):
        """Remove a specific entry from cache."""
        with self._lock:
            self._cache.pop(filepath, None)
