"""
Session Similarity - Find semantically related sessions

Uses embeddings to find sessions that are about similar topics,
even if they don't share files or projects.
"""

from typing import List, Dict, Tuple, Optional
from pathlib import Path

from embedding_service import EmbeddingService
from vector_store import SessionVectorStore
from summary_store import SummaryStore
from chrono_utils import (
    classify_era, format_timestamp_relative,
    RESET, BOLD, DIM, CYAN, GREEN, BLUE
)


def find_similar_sessions(
    session_id: str,
    top_k: int = 8,
    min_similarity: float = 0.6
) -> List[Dict]:
    """
    Find sessions semantically similar to the given session.

    Uses the session's content embedding to find related sessions
    about similar topics.

    Args:
        session_id: The session to find similar sessions for
        top_k: Max number of similar sessions to return
        min_similarity: Minimum similarity score (0-1)

    Returns:
        List of similar sessions with scores
    """
    store = SessionVectorStore()
    summary_store = SummaryStore()

    # Get the target session's data
    all_sessions = store.list_sessions(limit=1000)
    target_session = None

    for session in all_sessions:
        if session.get("session_id", "").startswith(session_id):
            target_session = session
            break

    if not target_session:
        return []

    # Get embedding for the target session's content
    embedder = EmbeddingService()

    # Use summary if available, otherwise use preview
    target_summary = summary_store.get(target_session["session_id"])
    target_text = target_summary or target_session.get("preview", "")

    if not target_text:
        return []

    # Embed and search
    query_embedding = embedder.embed(target_text)
    similar = store.search_sessions(query_embedding, n_sessions=top_k + 5)

    # Filter out the target session and apply min similarity
    results = []
    for session in similar:
        if session["session_id"] == target_session["session_id"]:
            continue

        score = session.get("score", 0)
        if score >= min_similarity * 100:  # scores are 0-100
            # Add era and summary
            session["era"] = classify_era(session.get("timestamp"))
            session["relative_time"] = format_timestamp_relative(session.get("timestamp"))
            session["summary"] = summary_store.get(session["session_id"])
            results.append(session)

    return results[:top_k]


def find_sessions_like_query(
    query: str,
    exclude_session_id: Optional[str] = None,
    top_k: int = 5
) -> List[Dict]:
    """
    Find sessions similar to a natural language query.

    Args:
        query: Natural language description
        exclude_session_id: Optional session to exclude from results
        top_k: Max results

    Returns:
        List of similar sessions
    """
    embedder = EmbeddingService()
    store = SessionVectorStore()
    summary_store = SummaryStore()

    query_embedding = embedder.embed(query)
    sessions = store.search_sessions(query_embedding, n_sessions=top_k + 2)

    results = []
    for session in sessions:
        if exclude_session_id and session["session_id"].startswith(exclude_session_id):
            continue

        session["era"] = classify_era(session.get("timestamp"))
        session["relative_time"] = format_timestamp_relative(session.get("timestamp"))
        session["summary"] = summary_store.get(session["session_id"])
        results.append(session)

    return results[:top_k]


def format_similar_sessions(
    target_id: str,
    similar: List[Dict],
    use_color: bool = True
) -> str:
    """Format similar sessions for display."""
    if use_color:
        # Local alias: "Yellow" is actually blue for light-bg visibility
        YELLOW = BLUE
    else:
        CYAN = GREEN = YELLOW = ""

    lines = []

    lines.append(f"\n{BOLD}{CYAN}🧠 SEMANTICALLY SIMILAR SESSIONS{RESET}")
    lines.append(f"{CYAN}{'─' * 55}{RESET}")
    lines.append(f"{DIM}Sessions about similar topics to #{target_id[:8]}{RESET}\n")

    if not similar:
        lines.append(f"  {DIM}No similar sessions found.{RESET}")
        return "\n".join(lines)

    for i, session in enumerate(similar, 1):
        era = session.get("era")
        score = session.get("score", 0)
        summary = session.get("summary", "")
        project = session.get("project", "unknown")
        relative_time = session.get("relative_time", "")

        # Similarity bar
        bar_filled = int(score / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        summary_display = summary[:45] + "..." if summary and len(summary) > 45 else (summary or "No summary")

        lines.append(f"  {BOLD}{i}. #{session['session_id'][:8]}{RESET} {bar} {score}%")
        lines.append(f"     {DIM}📝 {summary_display}{RESET}")
        lines.append(f"     {era.emoji} {era.time_period} │ {project} │ {relative_time}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI Testing
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        session_id = sys.argv[1]
        print(f"\nFinding sessions similar to: {session_id}")

        similar = find_similar_sessions(session_id)
        print(format_similar_sessions(session_id, similar))

        if similar:
            print(f"\n{BOLD}Quick Commands:{RESET}")
            for i, s in enumerate(similar[:5], 1):
                era = s.get("era")
                print(f"  {era.emoji} #{i}: claude --continue {s['session_id']}")
    else:
        print("Usage: python session_similarity.py <session_id>")
        print("Example: python session_similarity.py bf695425")
