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
from pathlib import Path
from datetime import datetime
from typing import Set, Optional

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
        """Load the set of already indexed session IDs."""
        if self.indexed_file.exists():
            try:
                with open(self.indexed_file) as f:
                    data = json.load(f)
                return set(data.get("sessions", []))
            except:
                pass
        return set()
    
    def save_indexed_sessions(self, sessions: Set[str]):
        """Save the set of indexed session IDs."""
        with open(self.indexed_file, "w") as f:
            json.dump({
                "sessions": list(sessions),
                "last_updated": datetime.now().isoformat(),
                "count": len(sessions)
            }, f, indent=2)
    
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
            print(f"    ⏭ Skipping active session")
            return -1  # Special code for "skipped"

        # Parse into chunks
        chunks = chunk_session(session_path)

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
        skip_active: bool = True
    ) -> dict:
        """
        Index all Claude Code sessions.

        Args:
            reindex: If True, reindex everything from scratch
            limit: Maximum number of sessions to index (for testing)
            skip_active: If True, skip sessions currently being written (default)

        Returns:
            Statistics about the indexing run
        """
        start_time = datetime.now()

        if not self.check_dependencies():
            return {"error": "Dependency check failed"}

        # Warn about duplicate sessions
        warn_duplicate_sessions()

        # Refresh active session list
        self.active_sessions = get_active_session_ids()
        if self.active_sessions and skip_active:
            print(f"\n⏭ Will skip {len(self.active_sessions)} active session(s)")

        # Find all sessions
        all_sessions = find_all_sessions(self.claude_dir)

        if limit:
            all_sessions = all_sessions[:limit]

        print(f"\nFound {len(all_sessions)} session files")
        
        # Get already indexed
        if reindex:
            indexed = set()
            print("Reindexing all sessions from scratch...")
            self.store.reset()
        else:
            indexed = self.get_indexed_sessions()
            print(f"Already indexed: {len(indexed)} sessions")
        
        # Filter to new sessions
        new_sessions = [s for s in all_sessions if s.stem not in indexed]
        print(f"New sessions to index: {len(new_sessions)}")
        
        if not new_sessions:
            print("\nNo new sessions to index.")
            return {
                "sessions_found": len(all_sessions),
                "sessions_indexed": 0,
                "chunks_added": 0,
                "duration_seconds": 0
            }
        
        # Index each session
        print("\n" + "=" * 60)
        print("Indexing Sessions")
        print("=" * 60)

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
                    print(f"    - No content to index")

            except Exception as e:
                failed += 1
                print(f"    ✗ Error: {e}")
        
        # Save progress
        self.save_indexed_sessions(indexed)
        
        duration = (datetime.now() - start_time).total_seconds()
        
        # Print summary
        print("\n" + "=" * 60)
        print("Indexing Complete")
        print("=" * 60)

        stats = self.store.get_stats()

        summary = {
            "sessions_found": len(all_sessions),
            "sessions_indexed": successful,
            "sessions_skipped": skipped,
            "sessions_failed": failed,
            "chunks_added": total_chunks,
            "total_chunks_in_db": stats.get("total_chunks", 0),
            "total_sessions_in_db": stats.get("unique_sessions", 0),
            "duration_seconds": round(duration, 1)
        }

        print(f"\nSessions indexed: {successful}")
        if skipped > 0:
            print(f"Sessions skipped (active): {skipped}")
        print(f"Sessions failed: {failed}")
        print(f"Chunks added: {total_chunks}")
        print(f"Total in database: {stats.get('total_chunks', 0)} chunks")
        print(f"Time elapsed: {duration:.1f} seconds")

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
    
    indexer = SessionIndexer()
    
    if args.stats:
        stats = indexer.store.get_stats()
        print("\nCurrent Index Stats:")
        print("=" * 40)
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        indexed = indexer.get_indexed_sessions()
        print(f"  indexed_sessions: {len(indexed)}")
        return
    
    result = indexer.index_all(reindex=args.reindex, limit=args.limit)
    
    if "error" in result:
        print(f"\n❌ {result['error']}")
        exit(1)
    
    print("\n✅ Indexing complete!")


if __name__ == "__main__":
    main()
