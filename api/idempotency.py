"""Idempotency store and middleware.

Integration Standard 4:
An Idempotency-Key header on every POST: sending the same request twice
with the same key returns the same job and never does the work twice.
"""

from __future__ import annotations
import time
from typing import Dict, Any, Optional


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = 86400):
        self._store: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._store.get(key)
        if not entry:
            return None
        # Check TTL
        if time.time() - entry["created_at"] > self.ttl:
            del self._store[key]
            return None
        return entry["response"]

    def set(self, key: str, response_payload: Dict[str, Any]) -> None:
        self._store[key] = {
            "created_at": time.time(),
            "response": response_payload
        }


idempotency_store = IdempotencyStore()

