"""
Session Indexer (Chrono)
Indexes all Claude Code sessions into the vector database.

Run this to build your initial semantic search index:
    chrono index

Run with --reindex to rebuild from scratch:
    chrono index --reindex

Features:
- Skips active sessions (being written to)
- Warns about duplicate sessions in multiple terminals
- Classifies projects based on content, not just path
- Verifies chunks before marking as indexed
"""

import json
import argparse
import warnings
from pathlib import Path
from datetime import datetime
from typing import Set, Optional

# Suppress urllib3 NotOpenSSLWarning (noisy on macOS with LibreSSL)
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

from session_parser import find_all_sessions, chunk_session, get_session_info
from embedding_service import EmbeddingService
from vector_store import SessionVectorStore
from session_utils import (
    get_active_session_ids,
    warn_duplicate_sessions,
    is_session_active
)
from project_classifier import classify_session, KNOWN_PROJECTS
from session_exploder import extract_files_and_tools, parse_raw_session
from chrono_config import atomic_write_json, safe_load_json, IndexLock
from chrono_utils import separator


class SessionIndexer:
    """Indexes Claude Code sessions for semantic search."""

    def __init__(self, claude_dir: Optional[Path] = None):
        self.claude_dir = claude_dir or (Path.home() / ".claude")

        # Support both old and new config dirs (migration)
        new_config = Path.home() / ".chrono"
        old_config = Path.home() / ".smart-forking"

        # Use new dir if it exists, or old dir if it exists, otherwise create new
        if new_config.exists():
            self.config_dir = new_config
        elif old_config.exists():
            self.config_dir = old_config
        else:
            self.config_dir = new_config

        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.indexed_file = self.config_dir / "indexed_sessions.json"
        self.verified_file = self.config_dir / "verified_sessions.json"  # NEW: tracks verified indexing

        self.embedder = EmbeddingService()
        self.store = SessionVectorStore()

        # Track active sessions
        self.active_sessions = get_active_session_ids()

    def get_indexed_sessions(self) -> Set[str]:
        """
        Get set of already indexed session IDs.

        Merges ChromaDB (has chunks) with JSON cache (also tracks empty sessions).
        Both sources are valid — ChromaDB tracks sessions with content,
        the cache also remembers sessions that were scanned but had no content
        (e.g. file-history-snapshot-only sessions).
        """
        # Get from ChromaDB (sessions with actual chunks)
        chromadb_sessions = self.store.get_indexed_session_ids()

        # Get from cache file (includes empty sessions too)
        cache_sessions = set()
        cache_dirty = False
        data = safe_load_json(self.indexed_file, default={"sessions": []})
        if data:
            # Filter out invalid entries (non-strings, empty strings)
            raw = data.get("sessions", [])
            cache_sessions = {s for s in raw if isinstance(s, str) and s.strip()}
            if len(cache_sessions) != len(raw):
                cache_dirty = True  # Had invalid entries

        # Union: a session is indexed if it's in either source
        merged = chromadb_sessions | cache_sessions

        # Sync cache if drifted or had invalid entries
        if merged != cache_sessions or cache_dirty:
            if merged != cache_sessions:
                print(f"  ℹ Syncing index cache (cache: {len(cache_sessions)}, ChromaDB: {len(chromadb_sessions)}, merged: {len(merged)})")
            self.save_indexed_sessions(merged)

        return merged

    def verify_cache_integrity(self, verbose: bool = True) -> dict:
        """
        Compare ChromaDB session count vs JSON cache and report/heal drift.

        Returns a dict with integrity status:
          - chromadb_count: sessions with chunks in ChromaDB
          - cache_count: sessions tracked in JSON cache
          - only_in_chromadb: sessions in ChromaDB but missing from cache (drift)
          - only_in_cache: sessions in cache but not ChromaDB (expected — empty sessions)
          - healed: True if drift was detected and auto-healed
        """
        chromadb_sessions = self.store.get_indexed_session_ids()

        cache_sessions = set()
        data = safe_load_json(self.indexed_file, default={"sessions": []})
        if data:
            raw = data.get("sessions", [])
            cache_sessions = {s for s in raw if isinstance(s, str) and s.strip()}

        only_in_chromadb = chromadb_sessions - cache_sessions
        only_in_cache = cache_sessions - chromadb_sessions

        result = {
            "chromadb_count": len(chromadb_sessions),
            "cache_count": len(cache_sessions),
            "only_in_chromadb": len(only_in_chromadb),
            "only_in_cache": len(only_in_cache),
            "healed": False,
        }

        if verbose and (only_in_chromadb or only_in_cache):
            print(f"\n  Cache integrity check:")
            print(f"    ChromaDB sessions: {len(chromadb_sessions)}")
            print(f"    JSON cache sessions: {len(cache_sessions)}")
            if only_in_cache:
                print(f"    Only in cache (empty sessions): {len(only_in_cache)}")
            if only_in_chromadb:
                print(f"    ⚠ Only in ChromaDB (drift): {len(only_in_chromadb)}")

        # Auto-heal: merge ChromaDB sessions into cache
        if only_in_chromadb:
            merged = chromadb_sessions | cache_sessions
            self.save_indexed_sessions(merged)
            result["healed"] = True
            if verbose:
                print(f"    ✓ Cache healed — synced {len(only_in_chromadb)} missing session(s)")

        return result

    def save_indexed_sessions(self, sessions: Set[str]):
        """Save the set of indexed session IDs (atomic write)."""
        # Sanitize: only save non-empty string IDs
        clean = sorted(s for s in sessions if isinstance(s, str) and s.strip())
        atomic_write_json(self.indexed_file, {
            "sessions": clean,
            "last_updated": datetime.now().isoformat(),
            "count": len(clean)
        })

    def check_dependencies(self) -> bool:
        """Verify all dependencies are available."""
        print("Checking dependencies...")

        # Check Ollama model
        if not self.embedder.check_model_available():
            print(f"  ⚠ Model {self.embedder.model} not found")
            print(f"  Pulling model (this may take a minute)...")
            if not self.embedder.pull_model():
                print("  ❌ Failed to pull model. Is Ollama running?")
                print("     Run: ollama serve")
                return False

        print(f"  ✓ Embedding model: {self.embedder.model}")
        print(f"  ✓ Vector store: {self.store.persist_path}")
        return True

    def index_session(self, session_path: Path, force: bool = False) -> int:
        """
        Index a single session with proper project classification.

        Args:
            session_path: Path to the session JSONL file
            force: If True, reindex even if already indexed

        Returns:
            Number of chunks indexed (0 if skipped or failed)
        """
        session_id = session_path.stem

        # Skip active sessions (being written to)
        if session_id in self.active_sessions:
            print(f"    ⏭ Skipping active session (detected via process list)")
            return -1  # Special code for "skipped"

        # Additional safety: skip files modified very recently (likely being written)
        try:
            import time
            mtime = session_path.stat().st_mtime
            age_seconds = time.time() - mtime
            if age_seconds < 30:
                print(f"    ⏭ Skipping recently modified session ({age_seconds:.0f}s ago)")
                return -1  # Treat same as active
        except OSError:
            pass

        # Log file size
        try:
            file_size_mb = session_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 50:
                print(f"    📏 File size: {file_size_mb:.1f}MB")
        except OSError:
            pass

        # Parse into chunks (size-aware: chunk_session handles large files)
        try:
            chunks = chunk_session(session_path)
        except MemoryError:
            print(f"    ⚠ MemoryError - session too large, skipping")
            return 0

        if not chunks:
            return 0

        # Classify project based on content, not just path
        original_project = chunks[0].project if chunks else "unknown"

        # Get files touched for better classification
        messages = parse_raw_session(session_path)
        files_touched, _ = extract_files_and_tools(messages)
        all_files = set()
        for action_files in files_touched.values():
            all_files.update(action_files)

        # Get or generate summary
        from summary_store import SummaryStore
        summary_store = SummaryStore()
        summary = summary_store.get(session_id) or ""

        # Classify the session
        classification = classify_session(
            session_id=session_id,
            summary=summary,
            files_touched=all_files,
            original_project=original_project
        )

        # Update chunks with correct project name
        detected_project = classification.detected_project
        for chunk in chunks:
            chunk.project = detected_project

        # Generate embeddings
        texts = [c.content for c in chunks]
        embeddings = self.embedder.embed_batch(texts, show_progress=False)

        # Store in vector database
        added = self.store.add_chunks(chunks, embeddings)

        # Verify chunks were actually added
        if added > 0:
            # Quick verification: check if session exists in store
            stored_count = self.store.count_session_chunks(session_id)
            if stored_count < added:
                print(f"    ⚠ Verification failed: expected {added}, found {stored_count}")
                return 0  # Don't mark as indexed

        return added

    def index_all(
        self,
        reindex: bool = False,
        limit: Optional[int] = None,
        skip_active: bool = True,
        single_session: Optional[str] = None
    ) -> dict:
        """
        Index all Claude Code sessions.

        Args:
            reindex: If True, reindex everything from scratch
            limit: Maximum number of sessions to index (for testing)
            skip_active: If True, skip sessions currently being written (default)
            single_session: If set, only index the session matching this ID prefix

        Returns:
            Statistics about the indexing run
        """
        # Acquire index lock to prevent concurrent indexing
        lock = IndexLock()
        if not lock.acquire():
            holder = lock.holder_pid()
            print(f"\n⚠ Another indexer is already running (PID {holder}).")
            print(f"  Wait for it to finish, or remove the lock file:")
            print(f"  rm {lock.lock_path}")
            return {"error": "Another indexer is running"}

        try:
            return self._index_all_inner(
                reindex=reindex,
                limit=limit,
                skip_active=skip_active,
                single_session=single_session,
            )
        finally:
            lock.release()

    def _index_all_inner(
        self,
        reindex: bool = False,
        limit: Optional[int] = None,
        skip_active: bool = True,
        single_session: Optional[str] = None
    ) -> dict:
        """Inner implementation of index_all (called with lock held)."""
        start_time = datetime.now()

        # Find all sessions first to check if there's work to do
        all_sessions = find_all_sessions(self.claude_dir)

        # Single-session mode: filter to matching session and force re-index
        if single_session:
            matched = [s for s in all_sessions if s.stem.startswith(single_session) or single_session in s.stem]
            if not matched:
                print(f"\n⚠ No session found matching: {single_session}")
                print(f"  Try using the first 8 characters of the session ID")
                return {"error": f"No session matching '{single_session}'"}
            all_sessions = matched
            print(f"\n🎯 Single-session mode: found {len(matched)} match(es)")
            # Force re-index for single session
            reindex = True

        if limit:
            all_sessions = all_sessions[:limit]

        # Get already indexed
        if reindex:
            if not single_session:
                # Safe reindex: delete each session's chunks as we re-index it
                # (instead of bulk-deleting upfront, which loses all data if interrupted)
                print("Reindexing all sessions (safe mode — old data preserved until replaced)...")
                indexed = set()  # Treat all as unindexed
            else:
                # For single session, just remove that session's chunks
                for s in all_sessions:
                    self.store.delete_session(s.stem)
                indexed = self.get_indexed_sessions()
                # Remove the target session(s) from indexed set
                for s in all_sessions:
                    indexed.discard(s.stem)
        else:
            indexed = self.get_indexed_sessions()

        # Filter out archived sessions (intentionally removed from ChromaDB)
        from archive_manager import get_archived_session_ids
        archived_ids = get_archived_session_ids()
        if archived_ids and not reindex:
            indexed = indexed | archived_ids

        # Filter to new sessions
        new_sessions = [s for s in all_sessions if s.stem not in indexed]

        # Early exit if nothing to do (skip dependency checks entirely)
        if not new_sessions:
            print(f"✅ All {len(all_sessions)} sessions indexed. Nothing to do.")
            return {
                "sessions_found": len(all_sessions),
                "sessions_indexed": 0,
                "chunks_added": 0,
                "duration_seconds": 0
            }

        # Only check dependencies when there's actual work to do
        print(f"\nFound {len(new_sessions)} new session(s) to index")

        if not self.check_dependencies():
            return {"error": "Dependency check failed"}

        # Warn about duplicate sessions
        warn_duplicate_sessions()

        # Refresh active session list
        self.active_sessions = get_active_session_ids()
        if self.active_sessions and skip_active:
            print(f"⏭ Will skip {len(self.active_sessions)} active session(s)")

        # Index each session
        print("\n" + separator("=", 0))
        print("Indexing Sessions")
        print(separator("=", 0))

        total_chunks = 0
        successful = 0
        failed = 0
        skipped = 0

        for i, session_path in enumerate(new_sessions, 1):
            session_id = session_path.stem
            info = get_session_info(session_path)
            project_name = info.project if info else "unknown"

            print(f"\n[{i}/{len(new_sessions)}] {session_id[:12]}...")
            print(f"    Project: {project_name}")

            try:
                # For reindex: delete old chunks before re-indexing this session
                # (safe: only loses one session's data if interrupted, not all)
                if reindex and not single_session:
                    self.store.delete_session(session_id)

                chunks_added = self.index_session(session_path)

                if chunks_added == -1:
                    # Skipped (active session)
                    skipped += 1
                elif chunks_added > 0:
                    indexed.add(session_id)
                    total_chunks += chunks_added
                    successful += 1
                    print(f"    ✓ Indexed {chunks_added} chunks")
                else:
                    # Mark empty sessions as indexed so they aren't
                    # re-scanned on every run (snapshot-only, empty, etc.)
                    indexed.add(session_id)
                    print(f"    - No content to index")

            except Exception as e:
                failed += 1
                print(f"    ✗ Error: {e}")

        # For full reindex: clean up any sessions in ChromaDB that
        # weren't in the new scan (deleted session files)
        if reindex and not single_session:
            all_session_ids = {s.stem for s in all_sessions}
            orphaned = self.store.get_indexed_session_ids() - all_session_ids - indexed
            for orphan_id in orphaned:
                self.store.delete_session(orphan_id)
            if orphaned:
                print(f"\n  Cleaned {len(orphaned)} orphaned session(s) from ChromaDB")

        # Save progress
        self.save_indexed_sessions(indexed)

        duration = (datetime.now() - start_time).total_seconds()

        # Print summary
        print("\n" + separator("=", 0))
        print("Indexing Complete")
        print(separator("=", 0))

        stats = self.store.get_stats()

        print(f"\n  {'Sessions indexed:':<26} {successful}")
        if skipped > 0:
            print(f"  {'Sessions skipped:':<26} {skipped} (active)")
        print(f"  {'Sessions failed:':<26} {failed}")
        print(f"  {'Chunks added:':<26} {total_chunks}")
        print(f"  {'Total in database:':<26} {stats.get('total_chunks', 0)} chunks")
        print(f"  {'Time elapsed:':<26} {duration:.1f}s")

        # Verify ChromaDB/JSON cache are in sync
        integrity = self.verify_cache_integrity(verbose=True)

        summary = {
            "sessions_found": len(all_sessions),
            "sessions_indexed": successful,
            "sessions_skipped": skipped,
            "sessions_failed": failed,
            "chunks_added": total_chunks,
            "total_chunks_in_db": stats.get("total_chunks", 0),
            "total_sessions_in_db": stats.get("unique_sessions", 0),
            "duration_seconds": round(duration, 1),
            "cache_healed": integrity.get("healed", False),
        }

        return summary


def main():
    parser = argparse.ArgumentParser(
        description="Index Claude Code sessions for semantic search"
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Reindex all sessions from scratch"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of sessions to index (for testing)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Just show current stats, don't index"
    )

    args = parser.parse_args()

    try:
        indexer = SessionIndexer()
    except Exception as e:
        err_str = str(e).lower()
        if "connection refused" in err_str or "connect call failed" in err_str:
            print(f"\n⚠ Cannot connect to Ollama")
            print(f"  Start it with: ollama serve")
            exit(1)
        raise

    if args.stats:
        stats = indexer.store.get_stats()
        print("\n  Current Index Stats:")
        print(separator("═", 2))
        for key, value in stats.items():
            label = key.replace("_", " ").title()
            print(f"  {label + ':':<22} {value}")

        indexed = indexer.get_indexed_sessions()
        print(f"  {'Indexed Sessions:':<22} {len(indexed)}")

        # Run integrity check
        integrity = indexer.verify_cache_integrity(verbose=True)
        if not integrity.get("only_in_chromadb") and not integrity.get("only_in_cache"):
            print(f"\n  ✓ Cache integrity: OK")
        return

    result = indexer.index_all(reindex=args.reindex, limit=args.limit)

    if "error" in result:
        print(f"\n❌ {result['error']}")
        exit(1)

    print("\n✅ Indexing complete!")


if __name__ == "__main__":
    main()
