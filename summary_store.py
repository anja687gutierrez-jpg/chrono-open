"""
Summary Store - Persistent storage for AI-generated session summaries

Stores summaries in ~/.chrono/summaries.json
(Legacy: ~/.smart-forking/summaries.json also supported)
"""

import json
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime

from chrono_config import get_summaries_path, atomic_write_json, safe_load_json


class SummaryStore:
    """Stores and retrieves AI-generated session summaries."""

    def __init__(self, store_path: str = None):
        if store_path:
            self.store_path = Path(store_path).expanduser()
        else:
            self.store_path = get_summaries_path()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = None

    def _load(self) -> Dict:
        """Load summaries from disk (corruption-safe)."""
        if self._cache is not None:
            return self._cache

        default = {"summaries": {}, "updated": None}
        self._cache = safe_load_json(self.store_path, default=default)
        if self._cache is None:
            self._cache = default

        # Ensure structure
        if "summaries" not in self._cache:
            self._cache = default

        return self._cache

    def _save(self):
        """Save summaries to disk (atomic write)."""
        if self._cache:
            self._cache["updated"] = datetime.now().isoformat()
            atomic_write_json(self.store_path, self._cache)

    def get(self, session_id: str) -> Optional[str]:
        """Get summary for a session."""
        data = self._load()
        return data["summaries"].get(session_id)

    def set(self, session_id: str, summary: str):
        """Set summary for a session."""
        data = self._load()
        data["summaries"][session_id] = summary
        self._save()

    def set_batch(self, summaries: Dict[str, str]):
        """Set multiple summaries at once."""
        data = self._load()
        data["summaries"].update(summaries)
        self._save()

    def has(self, session_id: str) -> bool:
        """Check if session has a summary."""
        data = self._load()
        return session_id in data["summaries"]

    def get_all(self) -> Dict[str, str]:
        """Get all summaries."""
        data = self._load()
        return data["summaries"]

    def count(self) -> int:
        """Get number of stored summaries."""
        data = self._load()
        return len(data["summaries"])

    def clear(self):
        """Clear all summaries."""
        self._cache = {"summaries": {}, "updated": None}
        self._save()
