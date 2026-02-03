#!/usr/bin/env python3
"""
Project Epoch - Chrono Trigger Time Machine for Smart Forking

A time-traveling session navigator inspired by Chrono Trigger.
Find and fork past Claude Code sessions across the eras of your development history.

Usage:
    chrono "firebase authentication"           # Search all eras
    chrono "dashboard" --era future            # Search this week only
    chrono "API" --since "3 months ago"        # Date range filter
    chrono eras                                # Show all eras with session counts
    chrono --help                              # Full help

Time Gates, Epoch navigation, and Techs coming in future phases!
"""

import sys
import argparse
import json
import warnings
from typing import List, Dict, Optional
from datetime import datetime

# Suppress urllib3 NotOpenSSLWarning (noisy on macOS with LibreSSL)
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

from embedding_service import EmbeddingService
from vector_store import SessionVectorStore
from summary_store import SummaryStore
from chrono_utils import (
    ERAS, Era, FUTURE, END_OF_TIME, RESET, BOLD, DIM, CYAN,
    classify_era, get_era_by_code, get_era_date_range,
    parse_flexible_date, is_within_date_range, is_within_era,
    format_era_header, format_era_badge, format_era_compact,
    format_timestamp_relative, get_era_summary,
    term_width, separator, truncate, status_line, box_header
)
from session_exploder import explode_session, format_exploded_view
from session_graph import graph_command, graph_project_command, find_related_sessions
from session_similarity import find_similar_sessions, format_similar_sessions
from ascii_tree import create_session_tree_view
from html_export import generate_html_explorer
from chrono_welcome import show_welcome_menu
from pathlib import Path
import subprocess


# ============================================================
# Chrono Trigger ASCII Art & Theming
# ============================================================

CHRONO_BANNER = f"""
{BOLD}{CYAN}
   ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗ ██████╗
  ██╔════╝██║  ██║██╔══██╗██╔═══██╗████╗  ██║██╔═══██╗
  ██║     ███████║██████╔╝██║   ██║██╔██╗ ██║██║   ██║
  ██║     ██╔══██║██╔══██╗██║   ██║██║╚██╗██║██║   ██║
  ╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
   ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
{RESET}
{DIM}  Project Epoch - Time-Travel Through Your Code History{RESET}
"""

CHRONO_MINI = f"{BOLD}{CYAN}⏰ CHRONO{RESET}"


# ============================================================
# Core Search Functions
# ============================================================

def find_sessions_chrono(
    query: str,
    top_k: int = 5,
    project_filter: Optional[str] = None,
    era_filter: Optional[Era] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    sort_by: str = "relevance",
    exclude_active: bool = True
) -> List[Dict]:
    """
    Find relevant past sessions with Chrono-style filtering.

    Args:
        query: Natural language description of what you want to do
        top_k: Number of sessions to return
        project_filter: Optional project name to filter results
        era_filter: Optional Era to filter by
        since: Optional start date (inclusive)
        until: Optional end date (inclusive)
        sort_by: "relevance" (default) or "date" (newest first)
        exclude_active: If True, exclude sessions currently open in terminals

    Returns:
        List of session dicts with scores, metadata, and era classification
    """
    from session_utils import get_active_session_ids

    embedder = EmbeddingService()
    store = SessionVectorStore()

    # Check if we have any indexed sessions
    stats = store.get_stats()
    if stats.get("total_chunks", 0) == 0:
        print(f"\n  {BOLD}⚠ No sessions indexed yet!{RESET}")
        print(f"  {DIM}Your search index is empty. Let's fix that:{RESET}\n")
        print(f"  {BOLD}1.{RESET} chrono index          {DIM}← Index all Claude sessions{RESET}")
        print(f"  {BOLD}2.{RESET} chrono index --stats   {DIM}← Check index health{RESET}")
        print(f"\n  {DIM}Chrono needs Ollama running for embeddings:{RESET}")
        print(f"     ollama serve")
        print()
        return []

    # Get active sessions to exclude
    active_sessions = get_active_session_ids() if exclude_active else set()

    # Cap query length for embedding (nomic-embed-text context is 8192 tokens,
    # ~2000 chars is a safe limit to avoid degraded embeddings)
    embed_query = query[:2000] if len(query) > 2000 else query

    # Search with progress indicator
    with status_line("Searching the timestream"):
        # Embed the query
        query_embedding = embedder.embed(embed_query)

        # 1. Vector (semantic) search
        sessions = store.search_sessions(query_embedding, n_sessions=top_k * 5)

        # 2. Full-text search fallback (finds exact string matches)
        text_results = store.search_text(query, n_results=top_k * 5, project_filter=project_filter)

    # Aggregate text results by session (same as search_sessions logic)
    text_session_map = {}
    for r in text_results:
        sid = r.session_id
        if sid not in text_session_map or r.score > text_session_map[sid]["score"]:
            text_session_map[sid] = {
                "session_id": sid,
                "project": r.project,
                "score": r.score,
                "preview": r.preview,
                "timestamp": r.timestamp,
                "best_chunk": r.chunk_index
            }

    # 3. Merge: deduplicate by session_id, keeping highest score
    session_map = {s["session_id"]: s for s in sessions}
    for sid, text_session in text_session_map.items():
        if sid not in session_map or text_session["score"] > session_map[sid].get("score", 0):
            session_map[sid] = text_session

    sessions = sorted(session_map.values(), key=lambda x: x.get("score", 0), reverse=True)

    # Filter out active sessions first
    if active_sessions:
        sessions = [s for s in sessions if s.get("session_id") not in active_sessions]

    # Apply filters
    filtered_sessions = []

    for session in sessions:
        timestamp = session.get("timestamp")

        # Project filter
        if project_filter:
            project_lower = project_filter.lower()
            if project_lower not in session.get("project", "").lower():
                continue

        # Era filter
        if era_filter:
            if not is_within_era(timestamp, era_filter):
                continue

        # Date range filter
        if since or until:
            if not is_within_date_range(timestamp, since, until):
                continue

        # Classify era and add to session
        era = classify_era(timestamp)
        session["era"] = era
        session["relative_time"] = format_timestamp_relative(timestamp)

        filtered_sessions.append(session)

    # Sort
    if sort_by == "date":
        filtered_sessions = sorted(
            filtered_sessions,
            key=lambda s: s.get("timestamp", ""),
            reverse=True  # Newest first
        )
    # else: already sorted by relevance from vector search

    return filtered_sessions[:top_k]


def show_eras_command(store: SessionVectorStore) -> None:
    """Show all eras with session counts."""
    print(CHRONO_BANNER)
    print(separator("═", 0, BOLD))
    print(f"{BOLD}  TIME ERAS - Navigate Your Development History{RESET}")
    print(separator("═", 0, BOLD))
    print()

    # Get all sessions to count by era
    all_sessions = store.list_sessions(limit=10000)

    era_counts = {era.code: 0 for era in ERAS}
    total_sessions = len(all_sessions)

    for session in all_sessions:
        era = classify_era(session.get("timestamp"))
        era_counts[era.code] += 1

    # Display eras - clean format without game years
    for era in ERAS:
        count = era_counts.get(era.code, 0)
        since, until = get_era_date_range(era)
        since_str = since.strftime("%Y-%m-%d") if since else "ancient"
        until_str = until.strftime("%Y-%m-%d") if until else "now"

        # Progress bar
        if total_sessions > 0:
            bar_width = 20
            filled = int((count / total_sessions) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
        else:
            bar = "░" * 20

        # Clean display: emoji + name + time period + count + bar
        print(f"  {era.color}{era.emoji} {era.name:15}{RESET} │ {era.time_period:15} │ {count:3} sessions │ {bar}")
        print(f"     {DIM}{since_str} to {until_str}{RESET}")
        print()

    # Show special eras (Phase 2+)
    print(separator("─", 2, DIM))
    print(f"  {BOLD}  Coming Soon:{RESET}\n")

    # Future - Lavos Detection (predicted issues to prevent)
    print(f"  {FUTURE.color}{FUTURE.emoji} {FUTURE.name:15}{RESET} │ {FUTURE.time_period:15} │ {DIM}Lavos Detection (Phase 5){RESET}")
    print(f"     {DIM}Problems to prevent - tech debt, security issues, deprecations{RESET}")
    print()

    # End of Time - Bookmarks
    print(f"  {END_OF_TIME.color}{END_OF_TIME.emoji} {END_OF_TIME.name:15}{RESET} │ {END_OF_TIME.time_period:15} │ {DIM}Time Gates (Phase 2){RESET}")
    print(f"     {DIM}Bookmarked important sessions - your hub between all eras{RESET}")
    print()

    print(separator("─", 2, DIM))
    print(f"  {BOLD}Total: {total_sessions} sessions indexed{RESET}\n")

    # Usage hints
    print(f"  {DIM}Search an era:{RESET}    chrono \"query\" --era present")
    print(f"  {DIM}Date range:{RESET}       chrono \"query\" --since \"3 months ago\"")
    print(f"  {DIM}Combine filters:{RESET}  chrono \"query\" --era middle_ages --project magnusview\n")


def extract_summary(preview: str, max_len: int = 60) -> str:
    """Extract a clean summary from session preview text."""
    if not preview:
        return "No preview available"

    import re
    text = preview.strip()

    # Remove USER:/ASSISTANT: prefixes
    text = re.sub(r'^(USER|ASSISTANT|A|U):\s*', '', text)

    # Extract content from thinking blocks - keep the actual thought
    thinking_match = re.search(r'\[Thinking:\s*(.+?)(?:\]|$)', text, re.DOTALL)
    if thinking_match:
        thought = thinking_match.group(1).strip()
        # Get first meaningful sentence from thought
        sentences = re.split(r'[.!?]\s+', thought)
        if sentences and len(sentences[0]) > 10:
            text = sentences[0]
        else:
            text = re.sub(r'\[Thinking:\s*', '', text)

    # Filter out low-value generic responses
    noise_patterns = [
        r"^The assistant responded with a generic message",
        r"^I'll help you",
        r"^Sure,? I",
        r"^Let me ",
        r"^I can help",
        r"^Here's ",
    ]
    for pattern in noise_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            # Try to find a more useful part after the noise
            rest = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
            if rest and len(rest) > 15:
                text = rest
            break

    # Remove markdown artifacts
    text = text.replace("**", "").replace("##", "").replace("```", "")
    text = text.replace("#", "").replace("`", "")

    # Remove file path noise at the start (common in tool output previews)
    text = re.sub(r'^/[^\s]+\s*', '', text)

    # Remove newlines and extra whitespace
    text = " ".join(text.split())

    # Truncate intelligently (at word boundary)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."

    return text.strip() if text.strip() else "Session content"


def format_results_chrono(query: str, sessions: List[Dict], show_banner: bool = True) -> str:
    """Format search results with Chrono Trigger theming."""
    lines = []

    # Load AI summaries
    summary_store = SummaryStore()

    if show_banner:
        lines.append(CHRONO_BANNER)

    lines.append(separator("═", 0, BOLD))
    lines.append(f"{BOLD}  🔍 TIME GATE SEARCH{RESET}")
    lines.append(separator("═", 0, BOLD))
    lines.append("")

    # Truncate very long queries for display (full query still used for search)
    display_query = query
    if len(display_query) > 80:
        display_query = display_query[:77] + "..."
    lines.append(f"  Searching the timestream for: \"{display_query}\"")
    lines.append("")

    if not sessions:
        lines.append(f"  {DIM}No matching sessions found.{RESET}")
        lines.append("")
        lines.append(f"  {BOLD}Suggestions:{RESET}")
        lines.append(f"    • Try broader or different search terms")
        lines.append(f"    • Remove --era filter to search all time periods")
        lines.append(f"    • Check your index: chrono index --stats")
        lines.append(f"    • Update index with new sessions: chrono index")
        lines.append("")
        return "\n".join(lines)

    # Group by era for display
    current_era = None

    for i, session in enumerate(sessions, 1):
        session_id = session.get("session_id", "unknown")
        score = session.get("score", 0)
        project = session.get("project", "unknown")
        preview = session.get("preview", "")
        era = session.get("era", ERAS[-1])
        relative_time = session.get("relative_time", "unknown")

        # Use AI summary if available, otherwise extract from preview
        # Truncate to fit terminal: 5-char indent + "📝 " prefix = ~9 chars overhead
        summary_max = term_width() - 10
        ai_summary = summary_store.get(session_id)
        if ai_summary:
            summary = ai_summary[:summary_max] + "..." if len(ai_summary) > summary_max else ai_summary
        else:
            summary = extract_summary(preview, max_len=summary_max)

        # Show era header if changed (includes both game year AND time period)
        if era.code != (current_era.code if current_era else None):
            current_era = era
            lines.append(separator("─", 2, era.color))
            lines.append(f"  {format_era_header(era)}")
            lines.append(separator("─", 2, era.color))
            lines.append("")

        # Recommended badge
        recommended = f" {BOLD}★ RECOMMENDED{RESET}" if i == 1 else ""

        lines.append(f"  {BOLD}› {i}. #{session_id[:8]}{RESET}{recommended}")
        lines.append(f"     {DIM}📝 {summary}{RESET}")
        # Pad era and truncate project for aligned columns
        proj_display = project[:20] if len(project) > 20 else project
        lines.append(f"     {era.color}{era.emoji} {era.time_period:<15}{RESET} │ {proj_display:<20} │ {score}% │ {relative_time}")
        lines.append("")

    # Fork commands section
    lines.append(separator("═", 2, BOLD))
    lines.append(f"  {BOLD}⏰ TIME GATE COMMANDS{RESET} (copy to terminal)")
    lines.append(separator("═", 2, BOLD))
    lines.append("")

    for i, session in enumerate(sessions, 1):
        session_id = session.get("session_id", "unknown")
        era = session.get("era", ERAS[-1])
        lines.append(f"  {era.emoji} #{i}: claude --continue {session_id}")

    lines.append(f"\n  🆕 #0: claude  {DIM}(start fresh - new timeline){RESET}")
    lines.append("")

    # Footer hints
    lines.append(separator("─", 2, DIM))
    lines.append(f"  {DIM}💡 chrono eras        - Browse all time periods{RESET}")
    lines.append(f"  {DIM}💡 chrono --help      - Full command reference{RESET}")
    lines.append("")

    return "\n".join(lines)


def explode_command(session_arg: str) -> bool:
    """
    Explode a session to show its components (like CADDY's exploded view).

    Args:
        session_arg: Full or partial session ID

    Returns:
        True if session was found and exploded
    """
    # Find session file
    claude_dir = Path.home() / ".claude" / "projects"
    session_path = None

    for jsonl_file in claude_dir.glob("**/*.jsonl"):
        if jsonl_file.stem.startswith(session_arg) or session_arg in jsonl_file.stem:
            session_path = jsonl_file
            break

    if not session_path:
        print(f"\n  {BOLD}⚠ Session not found:{RESET} {session_arg}")
        print(f"  {DIM}Try using the first 8 characters of the session ID{RESET}")
        print(f"  {DIM}Example: chrono explode bf695425{RESET}\n")
        return False

    with status_line(f"Exploding session #{session_path.stem[:12]}"):
        exploded = explode_session(session_path)
    if exploded:
        print(format_exploded_view(exploded))
        return True
    else:
        print(f"  {BOLD}⚠ Could not explode session{RESET}")
        print(f"  {DIM}The session file may be empty or corrupted.{RESET}")
        print(f"  {DIM}Try: chrono explode <different-session-id>{RESET}\n")
        return False


def similar_command(session_arg: str) -> bool:
    """
    Find semantically similar sessions.

    Args:
        session_arg: Full or partial session ID

    Returns:
        True if session was found
    """
    with status_line(f"Finding sessions similar to #{session_arg[:12]}"):
        similar = find_similar_sessions(session_arg)
    print(format_similar_sessions(session_arg, similar))

    if similar:
        print(f"\n{BOLD}Quick Commands:{RESET}")
        for i, s in enumerate(similar[:5], 1):
            era = s.get("era", ERAS[-1])
            print(f"  {era.emoji} #{i}: claude --continue {s['session_id']}")
        print()

    return bool(similar)


def tree_command(session_arg: str) -> bool:
    """
    Show a visual tree of session relationships.

    Args:
        session_arg: Full or partial session ID

    Returns:
        True if session was found
    """
    with status_line(f"Building session tree for #{session_arg[:12]}"):
        # Get related sessions
        target, related = find_related_sessions(session_arg)
    if not target:
        print(f"\n  {BOLD}⚠ Session not found:{RESET} {session_arg}")
        return False

    # Get similar sessions
    similar = find_similar_sessions(session_arg, top_k=4)

    # Build root session dict
    root_session = {
        "session_id": target.session_id,
        "project": target.project,
        "timestamp": target.timestamp,
        "summary": target.summary
    }

    # Convert related to the format expected by tree
    related_dicts = [
        ({"session_id": n.session_id, "project": n.project, "timestamp": n.timestamp, "summary": n.summary}, r, s)
        for n, r, s in related
    ]

    print(create_session_tree_view(root_session, related_dicts, similar))
    return True


def export_command(output_path: str = None) -> bool:
    """
    Export sessions to interactive HTML.

    Args:
        output_path: Where to save the HTML file

    Returns:
        True if export succeeded
    """
    if not output_path:
        output_path = "~/Desktop/session_explorer.html"

    print(f"\n  {BOLD}🎨 Generating interactive HTML explorer...{RESET}\n")

    try:
        path = generate_html_explorer(output_path, include_relationships=True)
        print(f"\n  {BOLD}✅ Export complete!{RESET}")
        print(f"  {DIM}Open in browser:{RESET} open {path}\n")
        return True
    except Exception as e:
        print(f"\n  {BOLD}⚠ Export failed:{RESET} {e}")
        return False


def interactive_mode_chrono(query: str, sessions: List[Dict]):
    """Interactive selection with Chrono theming."""
    if not sessions:
        return

    print(f"\n  {BOLD}Select a time gate, or:{RESET}")
    print(f"  {DIM}  x<n> = explode session (e.g., x1){RESET}")
    print(f"  {DIM}  0   = start fresh timeline{RESET}")

    try:
        choice = input(f"  {BOLD}>{RESET} ").strip().lower()

        if choice == "0" or choice in ("fresh", "new"):
            print(f"\n  {BOLD}✓ Starting new timeline.{RESET} Run: claude")
            return

        # Handle explode command (x1, x2, etc.)
        if choice.startswith("x"):
            try:
                idx = int(choice[1:]) - 1
                if 0 <= idx < len(sessions):
                    session_id = sessions[idx]["session_id"]
                    print()
                    explode_command(session_id)
                else:
                    print(f"  {DIM}Invalid selection - choose x1-x{len(sessions)}{RESET}")
            except ValueError:
                print(f"  {DIM}Use x1, x2, etc. to explode a session{RESET}")
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                session_id = sessions[idx]["session_id"]
                era = sessions[idx].get("era", ERAS[-1])
                print(f"\n  {BOLD}✓ Time gate activated!{RESET}")
                print(f"  {era.emoji} claude --continue {session_id}")
            else:
                print(f"  {DIM}Invalid selection - choose 1-{len(sessions)} or 0{RESET}")
        except ValueError:
            print(f"  {DIM}Enter a number or x<n> to explode{RESET}")

    except KeyboardInterrupt:
        print(f"\n  {DIM}Time travel cancelled{RESET}")


# ============================================================
# Error Handling Helpers
# ============================================================

def _is_ollama_connection_error(exc: Exception) -> bool:
    """Check if an exception is caused by Ollama not running."""
    err_str = str(exc).lower()
    if isinstance(exc, ConnectionError) or isinstance(exc, ConnectionRefusedError):
        return True
    if "connection refused" in err_str or "connect call failed" in err_str:
        return True
    if "ollama" in err_str and ("refused" in err_str or "failed" in err_str or "unavailable" in err_str):
        return True
    # RuntimeError wrapping ConnectionError from embedding_service
    if isinstance(exc, RuntimeError) and "embedding failed" in err_str:
        return True
    return False


# ============================================================
# Main CLI
# ============================================================

def main():
    try:
        _main_inner()
    except KeyboardInterrupt:
        print(f"\n  {DIM}Time travel cancelled{RESET}")
        sys.exit(0)
    except ImportError as e:
        pkg = str(e).replace("No module named ", "").strip("'\"")
        print(f"\n{BOLD}⚠ Missing dependency:{RESET} {pkg}")
        print(f"  Run: pip install {pkg}")
        sys.exit(1)
    except Exception as e:
        if _is_ollama_connection_error(e):
            print(f"\n{BOLD}⚠ Cannot connect to Ollama{RESET}")
            print(f"  Ollama is required for semantic search embeddings.")
            print(f"  Start it with: ollama serve")
            print(f"  Then retry your command.\n")
            sys.exit(1)
        # Unexpected error — show one-line message, not full traceback
        print(f"\n{BOLD}⚠ Error:{RESET} {e}")
        print(f"  {DIM}Run 'chrono --help' for usage info{RESET}\n")
        sys.exit(1)


def _check_first_run() -> bool:
    """Check if Chrono has been set up. Returns True if ready, False if first run."""
    from chrono_config import get_data_dir
    data_dir = get_data_dir()
    chroma_dir = data_dir / "chroma"

    if not data_dir.exists() or not chroma_dir.exists():
        print(box_header(
            "⏰ Welcome to CHRONO!",
            subtitle="Time-Travel Through Your Code History",
            color=CYAN
        ))
        print()
        print(f"  {BOLD}First time here? Let's get you set up:{RESET}\n")
        print(f"  {BOLD}1.{RESET} Make sure Ollama is running:")
        print(f"     ollama serve\n")
        print(f"  {BOLD}2.{RESET} Build your search index:")
        print(f"     chrono index\n")
        print(f"  {BOLD}3.{RESET} Then search your sessions:")
        print(f"     chrono \"firebase auth\"")
        print(f"     chrono eras")
        print()
        print(f"  {DIM}Data will be stored in: {data_dir}{RESET}")
        print(f"  {DIM}Indexing scans: ~/.claude/projects/ for session files{RESET}\n")
        return False
    return True


def _main_inner():
    parser = argparse.ArgumentParser(
        description="Project Epoch - Time-travel through your Claude Code sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Examples:{RESET}
  %(prog)s "add authentication to my app"
  %(prog)s "dashboard" --era present             # This week only
  %(prog)s "firebase" --era middle_ages          # 1-4 weeks ago
  %(prog)s "API" --since "3 months ago"          # Date range
  %(prog)s "react" --since 2024-06 --until 2025-01
  %(prog)s eras                                   # Show all eras
  %(prog)s --project magnusview "real-time"      # Filter by project

{BOLD}Eras (newest to oldest):{RESET}
  🏠 present      - This Week
  ⚔️  middle_ages  - 1-4 Weeks Ago
  🏛️  antiquity    - 1-3 Months Ago
  🦕 prehistory   - 3+ Months Ago

{BOLD}Exploded View (like CADDY!):{RESET}
  %(prog)s explode <session_id>              # Break session into components

{BOLD}Session Graph:{RESET}
  %(prog)s graph <session_id>                # Show related sessions
  %(prog)s graph --project <name>            # Show project timeline

{BOLD}Visual Tree:{RESET}
  %(prog)s tree <session_id>                 # ASCII tree with all connections

{BOLD}Semantic Similarity:{RESET}
  %(prog)s similar <session_id>              # Find sessions about similar topics

{BOLD}HTML Export:{RESET}
  %(prog)s export                            # Generate interactive HTML explorer
  %(prog)s export ~/my_sessions.html         # Custom output path

{BOLD}Indexing:{RESET}
  %(prog)s index                             # Index new sessions
  %(prog)s index --reindex                   # Rebuild entire index

{BOLD}Time Gates (Bookmarks):{RESET}
  %(prog)s gate save my-project              # Bookmark current session
  %(prog)s gate list                         # Show all bookmarks
  %(prog)s gate jump my-project              # Get continue command

{BOLD}Techs (Workflow Automation):{RESET}
  %(prog)s tech list                         # Show available workflows
  %(prog)s tech fire                         # Build project
  %(prog)s tech antipode                     # Build + Test

{BOLD}Lavos (Project Health):{RESET}
  %(prog)s lavos                             # Full project scan
  %(prog)s lavos quick                       # Critical issues only

{BOLD}Git Time Machine:{RESET}
  %(prog)s git                               # Git status with era info
  %(prog)s git log                           # Commit history by era
        """
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="What you want to find (natural language) or 'eras' to show time periods"
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
        "--era", "-e",
        type=str,
        choices=["present", "middle_ages", "antiquity", "prehistory"],
        help="Filter to a specific time era (present=this week, middle_ages=1-4 weeks, antiquity=1-3 months, prehistory=3+ months)"
    )

    parser.add_argument(
        "--since",
        type=str,
        help="Start date filter (e.g., '2024-01', '3 months ago', 'last week')"
    )

    parser.add_argument(
        "--until",
        type=str,
        help="End date filter (e.g., '2025-12', 'yesterday', '2 weeks ago')"
    )

    parser.add_argument(
        "--sort", "-s",
        choices=["relevance", "date"],
        default="relevance",
        help="Sort by 'relevance' (default) or 'date' (newest first)"
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

    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Hide the ASCII banner"
    )

    args = parser.parse_args()

    # Handle 'eras' subcommand
    query_str = " ".join(args.query) if args.query else ""

    if query_str.lower() == "eras" or query_str.lower() == "era":
        store = SessionVectorStore()
        show_eras_command(store)
        return

    # Handle 'explode' subcommand
    if query_str.lower().startswith("explode"):
        parts = query_str.split(None, 1)  # Split into ["explode", "<session_id>"]
        if len(parts) < 2:
            print(f"\n  {BOLD}Usage:{RESET} chrono explode <session_id>")
            print(f"  {DIM}Example: chrono explode bf695425{RESET}\n")
            sys.exit(1)
        session_arg = parts[1].strip()
        explode_command(session_arg)
        return

    # Handle 'graph' subcommand
    # Note: "chrono graph --project X" has --project consumed by argparse
    # So we detect: query="graph X" with args.project=X -> project graph
    #               query="graph <id>" with no args.project -> session graph
    if query_str.lower().startswith("graph"):
        parts = query_str.split()

        # If --project was used, argparse consumed it and set args.project
        # query would be "graph <project_name>" where project_name == args.project
        if args.project:
            graph_project_command(args.project)
            return

        if len(parts) < 2:
            print(f"\n  {BOLD}Usage:{RESET}")
            print(f"    chrono graph <session_id>        # Show related sessions")
            print(f"    chrono graph --project <name>    # Show project timeline")
            print(f"\n  {DIM}Examples:{RESET}")
            print(f"    chrono graph bf695425")
            print(f"    chrono graph --project magnusview\n")
            sys.exit(1)

        # Session ID is the second word
        graph_command(parts[1])
        return

    # Handle 'tree' subcommand - visual ASCII tree
    if query_str.lower().startswith("tree"):
        parts = query_str.split()
        if len(parts) < 2:
            print(f"\n  {BOLD}Usage:{RESET} chrono tree <session_id>")
            print(f"  {DIM}Example: chrono tree bf695425{RESET}\n")
            sys.exit(1)
        tree_command(parts[1])
        return

    # Handle 'similar' subcommand - semantic similarity
    if query_str.lower().startswith("similar"):
        parts = query_str.split()
        if len(parts) < 2:
            print(f"\n  {BOLD}Usage:{RESET} chrono similar <session_id>")
            print(f"  {DIM}Example: chrono similar bf695425{RESET}\n")
            sys.exit(1)
        similar_command(parts[1])
        return

    # Handle 'export' subcommand - HTML export
    if query_str.lower().startswith("export"):
        parts = query_str.split()
        output_path = parts[1] if len(parts) > 1 else None
        export_command(output_path)
        return

    # Handle 'index' subcommand - Run indexer
    if query_str.lower().startswith("index"):
        parts = query_str.split()
        if "--help" in parts or "-h" in parts:
            print(f"\n  {BOLD}⏰ chrono index{RESET} — Build and manage your session index\n")
            print(f"  {BOLD}Usage:{RESET}")
            print(f"    chrono index                  {DIM}Index new sessions only{RESET}")
            print(f"    chrono index --reindex        {DIM}Rebuild entire index from scratch{RESET}")
            print(f"    chrono index <session-id>     {DIM}Index/re-index a single session{RESET}")
            print(f"\n  {DIM}Requires Ollama running (ollama serve){RESET}\n")
            return
        reindex = "--reindex" in parts or "-r" in parts
        # Check for single session ID (e.g., "chrono index 4717c89a")
        single_session = None
        for part in parts[1:]:
            if part not in ("--reindex", "-r") and not part.startswith("-"):
                single_session = part
                break
        from indexer import SessionIndexer
        indexer = SessionIndexer()
        indexer.index_all(reindex=reindex, single_session=single_session)
        return

    # Handle 'gate' subcommand - Time gates (forward to gates.py)
    if query_str.lower().startswith("gate"):
        parts = query_str.split()
        if "--help" in parts or "-h" in parts:
            print(f"\n  {BOLD}⏰ chrono gate{RESET} — Bookmark sessions (End of Time)\n")
            print(f"  {BOLD}Usage:{RESET}")
            print(f"    chrono gate list                    {DIM}Show all bookmarks{RESET}")
            print(f"    chrono gate save <name>             {DIM}Bookmark latest session{RESET}")
            print(f"    chrono gate save <name> <id>        {DIM}Bookmark specific session{RESET}")
            print(f"    chrono gate save <name> --notes \"x\" {DIM}Add notes{RESET}")
            print(f"    chrono gate jump <name>             {DIM}Get continue command{RESET}")
            print(f"    chrono gate info <name>             {DIM}Detailed info{RESET}")
            print(f"    chrono gate delete <name>           {DIM}Remove bookmark{RESET}")
            print()
            return
        import gates
        parts = query_str.split(None, 1)
        gate_args = parts[1] if len(parts) > 1 else ""
        sys.argv = ["gate"] + gate_args.split()
        gates.main()
        return

    # Handle 'tech' subcommand - Workflow automation (forward to techs.py)
    if query_str.lower().startswith("tech"):
        parts = query_str.split()
        if "--help" in parts or "-h" in parts:
            print(f"\n  {BOLD}⏰ chrono tech{RESET} — Workflow automation (Techs)\n")
            print(f"  {BOLD}Usage:{RESET}")
            print(f"    chrono tech list                    {DIM}Show all available techs{RESET}")
            print(f"    chrono tech fire                    {DIM}Build (Lucca's fire){RESET}")
            print(f"    chrono tech ice                     {DIM}Run tests (Marle's ice){RESET}")
            print(f"    chrono tech slash                   {DIM}Lint (Crono's slash){RESET}")
            print(f"    chrono tech antipode                {DIM}Build + Test (Dual Tech){RESET}")
            print(f"    chrono tech luminaire               {DIM}Build + Test + Deploy (Triple!){RESET}")
            print(f"    chrono tech <name> --dry-run        {DIM}Preview without running{RESET}")
            print(f"    chrono tech custom <name> \"<cmd>\"   {DIM}Create custom tech{RESET}")
            print()
            return
        import techs
        parts = query_str.split(None, 1)
        tech_args = parts[1] if len(parts) > 1 else ""
        sys.argv = ["tech"] + tech_args.split()
        techs.main()
        return

    # Handle 'lavos' subcommand - Project health
    if query_str.lower().startswith("lavos"):
        import lavos
        parts = query_str.split(None, 1)
        lavos_args = parts[1] if len(parts) > 1 else ""
        sys.argv = ["lavos"] + lavos_args.split()
        lavos.main()
        return

    # Handle 'cleanup' subcommand - Remove stale sessions from ChromaDB
    if query_str.lower().startswith("cleanup"):
        print(f"\n{BOLD}🧹 Chrono Cleanup - Removing Stale Sessions{RESET}\n")
        store = SessionVectorStore()
        indexed_ids = store.get_all_session_ids()
        print(f"  Sessions in ChromaDB: {len(indexed_ids)}")

        # Find all actual session files
        claude_dir = Path.home() / ".claude"
        from session_parser import find_all_sessions
        existing_files = find_all_sessions(claude_dir)
        existing_ids = {p.stem for p in existing_files}
        print(f"  Session files on disk: {len(existing_ids)}")

        # Find orphans (in ChromaDB but no file on disk)
        orphans = indexed_ids - existing_ids
        if not orphans:
            print(f"\n  {BOLD}✅ No stale entries found. Index is clean.{RESET}\n")
            return

        print(f"\n  Found {len(orphans)} stale session(s):")
        for oid in sorted(orphans):
            print(f"    - {oid[:12]}...")

        # Remove orphans
        total_removed = 0
        for oid in orphans:
            removed = store.remove_session(oid)
            total_removed += removed
            print(f"    🗑 Removed {oid[:12]}... ({removed} chunks)")

        # Update index cache
        from indexer import SessionIndexer
        indexer = SessionIndexer()
        current_indexed = indexer.get_indexed_sessions()
        current_indexed -= orphans
        indexer.save_indexed_sessions(current_indexed)

        print(f"\n  {BOLD}✅ Cleanup complete: removed {len(orphans)} sessions ({total_removed} chunks){RESET}\n")
        return

    # Handle 'git' subcommand - Git time machine (forward to epoch.py)
    if query_str.lower().startswith("git"):
        import epoch
        parts = query_str.split(None, 1)
        git_args = parts[1] if len(parts) > 1 else ""
        sys.argv = ["egit"] + git_args.split()
        epoch.main()
        return

    # If no query, show interactive welcome menu
    if not args.query or not query_str.strip():
        command = show_welcome_menu()
        if command:
            # Execute the selected command
            if command.startswith("claude"):
                # Print the command for the user to run
                print(f"\n  {BOLD}Run this command:{RESET}")
                print(f"  {command}\n")
            elif command.startswith("chrono"):
                # Re-run chrono with the new arguments
                parts = command.split(None, 1)
                if len(parts) > 1:
                    new_args = parts[1]
                    # Execute as subprocess with proper path quoting
                    import os
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    subprocess.run(
                        f'cd "{script_dir}" && python chrono.py {new_args}',
                        shell=True,
                        executable="/bin/zsh"
                    )
            else:
                print(f"\n  {BOLD}Run:{RESET} {command}\n")
        sys.exit(0)

    # First-run check (only for search — subcommands like 'index' are already handled above)
    if not _check_first_run():
        sys.exit(0)

    # Parse era filter
    era_filter = None
    if args.era:
        era_filter = get_era_by_code(args.era)

    # Parse date filters
    since_date = None
    until_date = None

    if args.since:
        since_date = parse_flexible_date(args.since)
        if since_date is None:
            print(f"{BOLD}⚠ Could not parse --since date: '{args.since}'{RESET}")
            print(f"  Try formats like: 2024-01-15, '3 months ago', 'last week'")
            sys.exit(1)

    if args.until:
        until_date = parse_flexible_date(args.until)
        if until_date is None:
            print(f"{BOLD}⚠ Could not parse --until date: '{args.until}'{RESET}")
            print(f"  Try formats like: 2025-12-31, 'yesterday', '2 weeks ago'")
            sys.exit(1)

    # Search
    sessions = find_sessions_chrono(
        query=query_str,
        top_k=args.top,
        project_filter=args.project,
        era_filter=era_filter,
        since=since_date,
        until=until_date,
        sort_by=args.sort
    )

    # Output
    if args.json:
        # Convert Era objects to dicts for JSON serialization
        for session in sessions:
            if "era" in session:
                era = session["era"]
                session["era"] = {
                    "name": era.name,
                    "code": era.code,
                    "emoji": era.emoji,
                    "game_year": era.game_year
                }

        print(json.dumps({
            "query": query_str,
            "era_filter": args.era,
            "since": args.since,
            "until": args.until,
            "results": sessions
        }, indent=2, default=str))
    else:
        print(format_results_chrono(query_str, sessions, show_banner=not args.no_banner))

        if args.interactive and sessions:
            interactive_mode_chrono(query_str, sessions)


if __name__ == "__main__":
    main()
