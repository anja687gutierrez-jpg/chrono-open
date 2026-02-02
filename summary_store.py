"""
Summary Store - Persistent storage for AI-generated session summaries

Stores summaries in ~/.smart-forking/summaries.json
"""

import json
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime


class SummaryStore:
    """Stores and retrieves AI-generated session summaries."""

    def __init__(self, store_path: str = "~/.smart-forking/summaries.json"):
        self.store_path = Path(store_path).expanduser()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = None

    def _load(self) -> Dict:
        """Load summaries from disk."""
        if self._cache is not None:
            return self._cache

        if self.store_path.exists():
            try:
                with open(self.store_path) as f:
                    self._cache = json.load(f)
            except:
                self._cache = {"summaries": {}, "updated": None}
        else:
            self._cache = {"summaries": {}, "updated": None}

        return self._cache

    def _save(self):
        """Save summaries to disk."""
        if self._cache:
            self._cache["updated"] = datetime.now().isoformat()
            with open(self.store_path, "w") as f:
                json.dump(self._cache, f, indent=2)

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
