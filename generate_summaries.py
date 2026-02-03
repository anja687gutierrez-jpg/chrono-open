#!/usr/bin/env python3
"""
Generate AI Summaries - Create executive summaries for indexed sessions

Usage:
    python generate_summaries.py           # Generate for sessions without summaries
    python generate_summaries.py --all     # Regenerate all summaries
    python generate_summaries.py --test 5  # Test with 5 sessions
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

from summary_service import SummaryService, SessionChunk
from summary_store import SummaryStore
from session_parser import chunk_session, find_all_sessions


def generate_summaries(
    regenerate_all: bool = False,
    limit: int = None,
    verbose: bool = True
):
    """Generate AI summaries for sessions."""
    from chrono_config import get_data_dir, get_indexed_sessions_path

    config_dir = get_data_dir()
    indexed_file = get_indexed_sessions_path()

    # Get indexed sessions
    if indexed_file.exists():
        with open(indexed_file) as f:
            indexed_data = json.load(f)
            indexed_sessions = set(indexed_data.get("sessions", []))
    else:
        print("No indexed sessions found. Run indexer.py first.")
        return

    print(f"Found {len(indexed_sessions)} indexed sessions")

    # Initialize services
    summary_service = SummaryService()
    summary_store = SummaryStore()

    if not summary_service.check_model_available():
        print(f"❌ Model {summary_service.model} not available")
        print("   Run: ollama pull llama3.2")
        return

    print(f"✓ Model {summary_service.model} ready")
    print(f"✓ Existing summaries: {summary_store.count()}")

    # Find sessions needing summaries
    claude_dir = Path.home() / ".claude"
    all_session_files = find_all_sessions(claude_dir)

    sessions_to_process = []
    for session_path in all_session_files:
        session_id = session_path.stem
        if session_id in indexed_sessions:
            if regenerate_all or not summary_store.has(session_id):
                sessions_to_process.append(session_path)

    if limit:
        sessions_to_process = sessions_to_process[:limit]

    print(f"Sessions to process: {len(sessions_to_process)}")

    if not sessions_to_process:
        print("\n✓ All sessions already have summaries!")
        return

    print("\nGenerating summaries...\n")

    generated = 0
    failed = 0

    for i, session_path in enumerate(sessions_to_process, 1):
        session_id = session_path.stem
        short_id = session_id[:8]

        if verbose:
            print(f"  [{i}/{len(sessions_to_process)}] {short_id}...", end=" ")

        try:
            # Parse session chunks
            chunks = chunk_session(session_path)
            if not chunks:
                if verbose:
                    print("⚠ empty")
                continue

            # Convert to SessionChunks (use first 10 chunks for summary)
            session_chunks = [
                SessionChunk(c.content, getattr(c, 'role', 'unknown'))
                for c in chunks[:10]
            ]

            # Generate summary
            summary = summary_service.generate_summary(session_chunks)

            if summary:
                summary_store.set(session_id, summary)
                generated += 1
                if verbose:
                    # Truncate for display
                    display = summary[:50] + "..." if len(summary) > 50 else summary
                    print(f"✓ {display}")
            else:
                failed += 1
                if verbose:
                    print("⚠ no summary generated")

        except Exception as e:
            failed += 1
            if verbose:
                print(f"✗ error: {e}")

    print(f"\n{'═' * 50}")
    print(f"Summary generation complete!")
    print(f"  Generated: {generated}")
    print(f"  Failed: {failed}")
    print(f"  Total stored: {summary_store.count()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate AI summaries for sessions")
    parser.add_argument("--all", action="store_true", help="Regenerate all summaries")
    parser.add_argument("--test", type=int, metavar="N", help="Test with N sessions")
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

    args = parser.parse_args()

    generate_summaries(
        regenerate_all=args.all,
        limit=args.test,
        verbose=not args.quiet
    )
