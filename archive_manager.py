"""
Archive Manager (Chrono)
Tiered session archival to keep ChromaDB lean.

Sessions are classified into tiers:
  - hot:  Active project work (last 30 days) → stays in ChromaDB
  - warm: Older project work (30+ days) → stays in ChromaDB
  - cold: Non-project sessions (any age) → removed from ChromaDB, metadata kept in archive.json

Cold sessions are NOT deleted — only their vector embeddings are removed.
Original JSONL files are untouched. Archived sessions can be restored.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from chrono_config import get_data_dir, atomic_write_json, safe_load_json
from chrono_utils import BOLD, DIM, RESET, CYAN, separator

# Projects that indicate non-project (cold) sessions
COLD_PROJECTS = {
    "System-Maintenance",
    "Google-Drive",
    "General",
    "Workspace-Cleanup",
}

ARCHIVE_FILE = "archive.json"


def _get_archive_path() -> Path:
    return get_data_dir() / ARCHIVE_FILE


def load_archive() -> Dict:
    """Load the archive manifest."""
    default = {
        "archived_sessions": {},
        "stats": {
            "total_archived": 0,
            "last_archive_run": None,
            "chunks_freed": 0,
        },
    }
    return safe_load_json(_get_archive_path(), default=default) or default


def save_archive(data: Dict) -> None:
    """Save the archive manifest (atomic)."""
    atomic_write_json(_get_archive_path(), data, default=str)


def get_archived_session_ids() -> Set[str]:
    """Return the set of session IDs that have been archived."""
    archive = load_archive()
    return set(archive.get("archived_sessions", {}).keys())


def _get_gated_session_ids() -> Set[str]:
    """Return session IDs that are bookmarked (gated) — never archive these."""
    gates_path = get_data_dir() / "gates.json"
    data = safe_load_json(gates_path, default={"gates": {}})
    if not data:
        return set()
    return {g["session_id"] for g in data.get("gates", {}).values() if "session_id" in g}


class ArchiveManager:
    """Manages tiered archival of Chrono sessions."""

    def __init__(self):
        from vector_store import SessionVectorStore
        self.store = SessionVectorStore()
        self.archive = load_archive()
        self.gated_ids = _get_gated_session_ids()

    def classify_tier(
        self,
        session_id: str,
        project: str,
        timestamp: Optional[str],
        is_gated: bool = False,
    ) -> str:
        """
        Classify a session into hot/warm/cold tier.

        Rules:
          - Gated sessions → always hot
          - Non-project sessions (System-Maintenance, Google-Drive, General, Workspace-Cleanup) → cold
          - Project sessions within 30 days → hot
          - Project sessions older than 30 days → warm
        """
        if is_gated:
            return "hot"

        if project in COLD_PROJECTS:
            return "cold"

        # Parse timestamp to determine age
        if timestamp:
            try:
                if isinstance(timestamp, str):
                    ts = timestamp.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(ts)
                else:
                    dt = timestamp
                age = datetime.now(dt.tzinfo) - dt
                if age < timedelta(days=30):
                    return "hot"
                else:
                    return "warm"
            except (ValueError, TypeError):
                pass

        return "warm"  # Default to warm if we can't determine age

    def scan(self) -> Dict:
        """
        Dry-run scan: classify all indexed sessions into tiers.

        Returns:
            Dict with tier counts and lists of sessions per tier.
        """
        sessions = self.store.list_sessions(limit=10000)
        already_archived = set(self.archive.get("archived_sessions", {}).keys())

        tiers = {"hot": [], "warm": [], "cold": []}

        for s in sessions:
            sid = s.get("session_id", "")
            if sid in already_archived:
                continue  # Already archived, skip

            project = s.get("project", "General")
            timestamp = s.get("timestamp")
            is_gated = sid in self.gated_ids

            tier = self.classify_tier(sid, project, timestamp, is_gated)
            tiers[tier].append({
                "session_id": sid,
                "project": project,
                "timestamp": timestamp,
                "chunk_count": s.get("chunk_count", 0),
            })

        return {
            "hot": len(tiers["hot"]),
            "warm": len(tiers["warm"]),
            "cold": len(tiers["cold"]),
            "cold_chunks": sum(s["chunk_count"] for s in tiers["cold"]),
            "sessions": tiers,
            "already_archived": len(already_archived),
        }

    def archive_cold(self, dry_run: bool = False) -> Dict:
        """
        Archive cold sessions: remove from ChromaDB, save metadata to archive.json.

        Args:
            dry_run: If True, only report what would happen.

        Returns:
            Dict with results (sessions archived, chunks freed).
        """
        scan = self.scan()
        cold_sessions = scan["sessions"]["cold"]

        if not cold_sessions:
            return {"archived": 0, "chunks_freed": 0, "dry_run": dry_run}

        if dry_run:
            return {
                "archived": len(cold_sessions),
                "chunks_freed": scan["cold_chunks"],
                "dry_run": True,
                "sessions": cold_sessions,
            }

        # Load summaries for metadata
        from summary_store import SummaryStore
        summary_store = SummaryStore()

        archived_sessions = self.archive.get("archived_sessions", {})
        total_chunks_freed = 0

        for s in cold_sessions:
            sid = s["session_id"]
            chunk_count = s["chunk_count"]

            # Remove from ChromaDB
            removed = self.store.delete_session(sid)
            total_chunks_freed += removed

            # Save metadata to archive
            summary = summary_store.get(sid) or ""
            archived_sessions[sid] = {
                "project": s["project"],
                "summary": summary[:200] if summary else "",
                "timestamp": s["timestamp"] or "",
                "chunk_count": chunk_count,
                "archived_at": datetime.now().isoformat(),
                "reason": f"Non-project session ({s['project']})",
            }

        # Remove archived sessions from indexed_sessions.json cache
        from chrono_config import get_indexed_sessions_path
        idx_data = safe_load_json(get_indexed_sessions_path(), default={"sessions": []})
        if idx_data:
            archived_ids = {s["session_id"] for s in cold_sessions}
            remaining = [s for s in idx_data.get("sessions", []) if s not in archived_ids]
            atomic_write_json(get_indexed_sessions_path(), {
                "sessions": remaining,
                "last_updated": datetime.now().isoformat(),
                "count": len(remaining),
            })

        # Update archive stats
        self.archive["archived_sessions"] = archived_sessions
        self.archive["stats"] = {
            "total_archived": len(archived_sessions),
            "last_archive_run": datetime.now().isoformat(),
            "chunks_freed": self.archive.get("stats", {}).get("chunks_freed", 0) + total_chunks_freed,
        }
        save_archive(self.archive)

        return {
            "archived": len(cold_sessions),
            "chunks_freed": total_chunks_freed,
            "dry_run": False,
        }

    def restore(self, session_id: str) -> bool:
        """
        Restore an archived session back into ChromaDB by re-indexing from JSONL.

        Args:
            session_id: Full or partial session ID to restore.

        Returns:
            True if restored successfully.
        """
        archived = self.archive.get("archived_sessions", {})

        # Find matching session (supports partial IDs)
        match = None
        for sid in archived:
            if sid == session_id or sid.startswith(session_id):
                match = sid
                break

        if not match:
            print(f"  Session {session_id} not found in archive.")
            return False

        # Find the JSONL file
        claude_dir = Path.home() / ".claude" / "projects"
        session_path = None
        for jsonl_file in claude_dir.glob(f"**/{match}.jsonl"):
            session_path = jsonl_file
            break

        if not session_path:
            print(f"  JSONL file not found for session {match[:12]}.")
            print(f"  The original session file may have been deleted.")
            return False

        # Re-index using the existing indexer
        from indexer import SessionIndexer
        indexer = SessionIndexer()
        chunks_added = indexer.index_session(session_path, force=True)

        if chunks_added > 0:
            # Remove from archive
            del archived[match]
            self.archive["archived_sessions"] = archived
            self.archive["stats"]["total_archived"] = len(archived)
            save_archive(self.archive)

            # Add back to indexed sessions cache
            indexed = indexer.get_indexed_sessions()
            indexed.add(match)
            indexer.save_indexed_sessions(indexed)

            print(f"  Restored session {match[:12]} ({chunks_added} chunks)")
            return True
        else:
            print(f"  Failed to re-index session {match[:12]}")
            return False

    def status(self) -> Dict:
        """Get archive status with tier counts and storage info."""
        scan = self.scan()
        stats = self.archive.get("stats", {})

        return {
            "hot": scan["hot"],
            "warm": scan["warm"],
            "cold_in_chromadb": scan["cold"],
            "already_archived": scan["already_archived"],
            "total_chunks_freed": stats.get("chunks_freed", 0),
            "last_run": stats.get("last_archive_run"),
        }

    def list_archived(self) -> List[Dict]:
        """List all archived sessions with metadata."""
        archived = self.archive.get("archived_sessions", {})
        result = []
        for sid, meta in sorted(archived.items(), key=lambda x: x[1].get("archived_at", ""), reverse=True):
            result.append({
                "session_id": sid,
                "project": meta.get("project", "unknown"),
                "summary": meta.get("summary", ""),
                "timestamp": meta.get("timestamp", ""),
                "archived_at": meta.get("archived_at", ""),
                "chunk_count": meta.get("chunk_count", 0),
                "reason": meta.get("reason", ""),
            })
        return result
