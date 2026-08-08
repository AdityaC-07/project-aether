from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple


class ResponseCache:
    """Thread-safe LRU cache with per-entry TTL.

    Serves repeated LLM queries (same model + prompt + config) without
    hitting the API again. Oldest entries are evicted first when the cache
    is at capacity.
    """

    def __init__(self, max_size: int = 512, ttl_seconds: float = 3600.0) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, Tuple[float, str]] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @staticmethod
    def make_key(
        model: str,
        prompt: str,
        system: Optional[str],
        config: Optional[Dict[str, Any]],
    ) -> str:
        """Deterministic key covering everything that affects the response."""
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "config": {
                key: value for key, value in (config or {}).items() if key != "use_cache"
            },
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self.evictions += 1
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: str, ttl_seconds: Optional[float] = None) -> None:
        with self._lock:
            ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
            expires_at = time.monotonic() + ttl
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (expires_at, value)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self.evictions += 1

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._store),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else 0.0,
                "evictions": self.evictions,
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0
