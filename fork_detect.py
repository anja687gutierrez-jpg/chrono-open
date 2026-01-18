#!/usr/bin/env python3
"""
Smart Fork Detection
Find relevant past Claude Code sessions to fork from.

Usage:
    python fork_detect.py "add real-time token usage cards to dashboard"
    python fork_detect.py --project "STAP" "authentication flow"
    
This searches your indexed sessions and returns the most relevant ones
to help you build on prior context.
"""

import sys
import argparse
from typing import List, Dict, Optional

from embedding_service import EmbeddingService
from vector_store import SessionVectorStore


def find_relevant_sessions(
    query: str,
    top_k: int = 5,
    project_filter: Optional[str] = None
) -> List[Dict]:
    """
    Find the most relevant past sessions for a given query.
    
    Args:
        query: Natural language description of what you want to do
        top_k: Number of sessions to return
        project_filter: Optional project name to filter results
        
    Returns:
        List of session dicts with scores and metadata
    """
    embedder = EmbeddingService()
    store = SessionVectorStore()
    
    # Check if we have any indexed sessions
    stats = store.get_stats()
    if stats.get("total_chunks", 0) == 0:
        print("\n⚠ No sessions indexed yet!")
        print("Run 'python indexer.py' first to build your search index.")
        return []
    
    # Embed the query
    query_embedding = embedder.embed(query)
    
    # Search for similar sessions
    sessions = store.search_sessions(query_embedding, n_sessions=top_k * 2)
    
    # Filter by project if specified
    if project_filter:
        project_lower = project_filter.lower()
        sessions = [
            s for s in sessions 
            if project_lower in s.get("project", "").lower()
        ]
    
    return sessions[:top_k]


def format_results(query: str, sessions: List[Dict]) -> str:
    """Format search results for display."""
    lines = []
    
    lines.append("")
    lines.append("=" * 65)
    lines.append("🔍 Fork Session")
    lines.append("=" * 65)
    lines.append("")
    lines.append(f"Which session would you like to fork for: \"{query}\"?")
    lines.append("")
    
    if not sessions:
        lines.append("No relevant sessions found.")
        lines.append("")
        lines.append("Tips:")
        lines.append("  • Make sure you've run 'python indexer.py' to index your sessions")
        lines.append("  • Try a different search query")
        lines.append("  • Remove project filter if using one")
        return "\n".join(lines)
    
    for i, session in enumerate(sessions, 1):
        session_id = session.get("session_id", "unknown")
        score = session.get("score", 0)
        project = session.get("project", "unknown")
        preview = session.get("preview", "")[:80]
        
        # Mark recommended
        recommended = " (Recommended)" if i == 1 else ""
        
        lines.append(f"› {i}. #{session_id[:8]}{recommended}")
        lines.append(f"     {preview}...")
        lines.append(f"     Project: {project} | Score: {score}%")
        lines.append("")
    
    # Add options
    lines.append(f"  {len(sessions) + 1}. None - start fresh")
    lines.append("     Don't fork any session, start with no prior context.")
    lines.append("")
    lines.append(f"  {len(sessions) + 2}. Type something.")
    lines.append("")
    lines.append("-" * 65)
    lines.append("Chat about this")
    lines.append("")
    lines.append("Enter to select • ↑/↓ to navigate • Esc to cancel")
    lines.append("")
    
    # Fork commands
    lines.append("=" * 65)
    lines.append("Fork Commands (copy to new terminal):")
    lines.append("=" * 65)
    lines.append("")
    
    for i, session in enumerate(sessions, 1):
        session_id = session.get("session_id", "unknown")
        lines.append(f"  #{i}: claude --continue {session_id}")
    
    lines.append(f"\n  #0: claude  (start fresh)")
    lines.append("")
    
    return "\n".join(lines)


def interactive_mode(query: str, sessions: List[Dict]):
    """Interactive selection mode."""
    if not sessions:
        return
    
    print("\n" + "-" * 40)
    print("Select a session number (or 0 for fresh start):")
    
    try:
        choice = input("> ").strip()
        
        if choice == "0" or choice.lower() == "fresh":
            print("\n✓ Starting fresh. Run: claude")
            return
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx]["session_id"]
                print(f"\n✓ Fork command:")
                print(f"  claude --continue {session_id}")
            else:
                print("Invalid selection")
        except ValueError:
            print("Enter a number")
            
    except KeyboardInterrupt:
        print("\nCancelled")


def main():
    parser = argparse.ArgumentParser(
        description="Find relevant Claude Code sessions to fork from",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "add authentication to my app"
  %(prog)s --top 3 "dashboard real-time updates"
  %(prog)s --project STAP "PDF export feature"
        """
    )
    
    parser.add_argument(
        "query",
        nargs="*",
        help="What you want to implement (natural language)"
    )
    
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=5,
        help="Number of results to show (default: 5)"
    )
    
    parser.add_argument(
        "--project", "-p",
        type=str,
        help="Filter results to a specific project"
    )
    
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Enable interactive selection mode"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    # Get query
    if not args.query:
        print("Usage: python fork_detect.py \"your feature description\"")
        print("\nExample: python fork_detect.py \"add real-time updates to dashboard\"")
        sys.exit(1)
    
    query = " ".join(args.query)
    
    # Search
    sessions = find_relevant_sessions(
        query=query,
        top_k=args.top,
        project_filter=args.project
    )
    
    # Output
    if args.json:
        import json
        print(json.dumps({
            "query": query,
            "results": sessions
        }, indent=2))
    else:
        print(format_results(query, sessions))
        
        if args.interactive and sessions:
            interactive_mode(query, sessions)


if __name__ == "__main__":
    main()
