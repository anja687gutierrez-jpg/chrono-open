"""
Session Graph - Visualize relationships between sessions

Shows connections between sessions based on:
  - Same project
  - Shared files
  - Semantic similarity
  - Time proximity

Like CADDY's assembly view - see how parts connect!
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from chrono_utils import (
    ERAS, RESET, BOLD, DIM, CYAN, GREEN, BLUE, MAGENTA, GRAY,
    classify_era, parse_timestamp, format_timestamp_relative,
    separator, truncate, box_header, box_lines
)
from summary_store import SummaryStore
from session_exploder import parse_raw_session, extract_files_and_tools, shorten_path


@dataclass
class SessionNode:
    """A session in the graph."""
    session_id: str
    project: str
    timestamp: Optional[str]
    summary: Optional[str]
    files_touched: Set[str] = field(default_factory=set)
    connections: List[Tuple[str, str, float]] = field(default_factory=list)  # (session_id, reason, strength)


def find_all_session_files() -> List[Path]:
    """Find all session files."""
    claude_dir = Path.home() / ".claude" / "projects"
    sessions = []

    if claude_dir.exists():
        for jsonl_file in claude_dir.glob("**/*.jsonl"):
            if not jsonl_file.name.startswith("agent-"):
                sessions.append(jsonl_file)

    return sessions


def extract_project_name(path: Path) -> str:
    """Extract project name from path."""
    project_dir = path.parent.name
    parts = project_dir.split("-")
    skip_words = {"Users", "username", "Desktop", "Documents", "Projects",
                  "Claude", "Code", "Library", "CloudStorage", "GoogleDrive"}
    project_parts = [p for p in parts if p and p not in skip_words]

    if project_parts:
        return "-".join(project_parts[-3:]) if len(project_parts) > 3 else "-".join(project_parts)
    return project_dir[:30] if project_dir else "unknown"


def get_session_metadata(path: Path) -> Optional[SessionNode]:
    """Get basic metadata for a session."""
    session_id = path.stem
    project = extract_project_name(path)

    messages = parse_raw_session(path)
    if not messages:
        return None

    # Get timestamp (use LAST timestamp = most recent activity)
    timestamp = None
    for msg in messages:
        ts = msg.get("timestamp")
        if ts:
            timestamp = ts
            # Don't break - keep going to find the MOST RECENT timestamp

    # Get files touched
    files_touched, _ = extract_files_and_tools(messages)
    all_files = set()
    for action_files in files_touched.values():
        all_files.update(action_files)

    # Get summary
    summary_store = SummaryStore()
    summary = summary_store.get(session_id)

    return SessionNode(
        session_id=session_id,
        project=project,
        timestamp=timestamp,
        summary=summary,
        files_touched=all_files
    )


def find_related_sessions(
    target_session_id: str,
    max_related: int = 10
) -> Tuple[Optional[SessionNode], List[Tuple[SessionNode, str, float]]]:
    """
    Find sessions related to the target session.

    Returns:
        (target_node, list of (related_node, reason, strength))
    """
    session_files = find_all_session_files()

    # Find target session
    target_path = None
    for path in session_files:
        if path.stem.startswith(target_session_id) or target_session_id in path.stem:
            target_path = path
            break

    if not target_path:
        return None, []

    target_node = get_session_metadata(target_path)
    if not target_node:
        return None, []

    # Analyze all sessions for connections
    related = []

    for path in session_files:
        if path == target_path:
            continue

        node = get_session_metadata(path)
        if not node:
            continue

        # Calculate connection strength
        strength = 0.0
        reasons = []

        # Same project (strong connection)
        if node.project == target_node.project and node.project != "unknown":
            strength += 0.5
            reasons.append("same project")

        # Shared files (strong connection)
        shared_files = target_node.files_touched & node.files_touched
        if shared_files:
            file_strength = min(len(shared_files) * 0.15, 0.4)
            strength += file_strength
            reasons.append(f"{len(shared_files)} shared files")

        # Time proximity (weaker connection)
        if target_node.timestamp and node.timestamp:
            target_dt = parse_timestamp(target_node.timestamp)
            node_dt = parse_timestamp(node.timestamp)

            if target_dt and node_dt:
                days_apart = abs((target_dt - node_dt).days)
                if days_apart <= 1:
                    strength += 0.2
                    reasons.append("same day")
                elif days_apart <= 7:
                    strength += 0.1
                    reasons.append("same week")

        if strength > 0 and reasons:
            related.append((node, " + ".join(reasons), strength))

    # Sort by strength and limit
    related.sort(key=lambda x: x[2], reverse=True)

    return target_node, related[:max_related]


def format_session_graph(
    target: SessionNode,
    related: List[Tuple[SessionNode, str, float]],
    use_color: bool = True
) -> str:
    """
    Format a session graph as ASCII art.

    Shows the target session with its connections radiating out.
    """
    if use_color:
        from chrono_utils import CYAN, GREEN, BLUE, MAGENTA, GRAY
        YELLOW = BLUE    # "Yellow" is actually blue for light-bg visibility
        WHITE = GRAY     # "White" is actually dark gray for light-bg visibility
    else:
        CYAN = GREEN = YELLOW = MAGENTA = WHITE = ""

    lines = []

    # Header
    short_id = target.session_id[:8]
    era = classify_era(target.timestamp)

    lines.append(box_header(f"🌳 SESSION GRAPH: #{short_id}", color=CYAN))
    lines.append("")

    # Target session (center of graph)
    top_box, bottom_box = box_lines(color=GREEN)
    lines.append(top_box)
    lines.append(f"  {BOLD}{GREEN}│  🎯 TARGET: #{short_id}{RESET}")
    lines.append(f"  {GREEN}│  {DIM}📁 {target.project}{RESET}")

    if target.summary:
        lines.append(f"  {GREEN}│  {DIM}📝 {truncate(target.summary)}{RESET}")

    time_str = format_timestamp_relative(target.timestamp)
    lines.append(f"  {GREEN}│  {DIM}{era.emoji} {time_str}{RESET}")
    lines.append(bottom_box)
    lines.append("")

    if not related:
        lines.append(f"  {DIM}No related sessions found.{RESET}")
        lines.append(f"  {DIM}This session appears to be standalone.{RESET}")
        lines.append("")
        return "\n".join(lines)

    # Group by connection type
    same_project = [(n, r, s) for n, r, s in related if "same project" in r]
    shared_files = [(n, r, s) for n, r, s in related if "shared files" in r and "same project" not in r]
    same_time = [(n, r, s) for n, r, s in related if "same project" not in r and "shared files" not in r]

    lines.append(f"  {BOLD}📡 CONNECTIONS ({len(related)} related sessions){RESET}")
    lines.append(separator("─", 2))
    lines.append("")

    # Same project sessions
    if same_project:
        lines.append(f"  {BOLD}{YELLOW}📁 Same Project ({target.project}):{RESET}")
        for node, reason, strength in same_project[:5]:
            node_era = classify_era(node.timestamp)
            node_time = format_timestamp_relative(node.timestamp)
            strength_bar = "█" * int(strength * 10) + "░" * (10 - int(strength * 10))

            summary = truncate(node.summary or "", max_len=40)

            lines.append(f"     ├── #{node.session_id[:8]} {strength_bar}")
            lines.append(f"     │   {DIM}{summary}{RESET}")
            lines.append(f"     │   {node_era.emoji} {node_time}")
            lines.append(f"     │")

    # Shared files sessions
    if shared_files:
        lines.append(f"  {BOLD}{MAGENTA}📄 Shared Files:{RESET}")
        for node, reason, strength in shared_files[:3]:
            node_era = classify_era(node.timestamp)
            node_time = format_timestamp_relative(node.timestamp)
            strength_bar = "█" * int(strength * 10) + "░" * (10 - int(strength * 10))

            # Extract file count from reason
            file_info = reason.split(" + ")[0] if " + " in reason else reason

            lines.append(f"     ├── #{node.session_id[:8]} {strength_bar}")
            lines.append(f"     │   {DIM}{file_info} • {node.project}{RESET}")
            lines.append(f"     │   {node_era.emoji} {node_time}")
            lines.append(f"     │")

    # Time proximity sessions
    if same_time:
        lines.append(f"  {BOLD}{WHITE}⏰ Same Time Period:{RESET}")
        for node, reason, strength in same_time[:3]:
            node_era = classify_era(node.timestamp)
            node_time = format_timestamp_relative(node.timestamp)
            strength_bar = "█" * int(strength * 10) + "░" * (10 - int(strength * 10))

            lines.append(f"     ├── #{node.session_id[:8]} {strength_bar}")
            lines.append(f"     │   {DIM}{node.project}{RESET}")
            lines.append(f"     │   {node_era.emoji} {node_time}")
            lines.append(f"     │")

    lines.append("")

    # Commands section
    lines.append(separator("═", 2, BOLD))
    lines.append(f"  {BOLD}⏰ QUICK COMMANDS{RESET}")
    lines.append(separator("─", 2))

    for i, (node, reason, strength) in enumerate(related[:5], 1):
        node_era = classify_era(node.timestamp)
        lines.append(f"  {node_era.emoji} #{i}: claude --continue {node.session_id}")

    lines.append("")
    lines.append(f"  {DIM}💡 chrono explode <id> - See detailed session anatomy{RESET}")
    lines.append("")

    return "\n".join(lines)


def graph_command(session_arg: str) -> bool:
    """
    Show a graph of related sessions.

    Args:
        session_arg: Full or partial session ID

    Returns:
        True if session was found
    """
    print(f"\n  {DIM}Building session graph for: {session_arg}...{RESET}\n")

    target, related = find_related_sessions(session_arg)

    if not target:
        print(f"\n  {BOLD}⚠ Session not found:{RESET} {session_arg}")
        print(f"  {DIM}Try using the first 8 characters of the session ID{RESET}")
        print(f"  {DIM}Example: chrono graph bf695425{RESET}\n")
        return False

    print(format_session_graph(target, related))
    return True


def graph_project_command(project_name: str, limit: int = 15) -> bool:
    """
    Show a graph of all sessions for a project.

    Args:
        project_name: Project name to search for
        limit: Max sessions to show

    Returns:
        True if sessions were found
    """
    session_files = find_all_session_files()

    # Find sessions matching project
    project_sessions = []
    project_name_lower = project_name.lower()

    for path in session_files:
        node = get_session_metadata(path)
        if node and project_name_lower in node.project.lower():
            project_sessions.append(node)

    if not project_sessions:
        print(f"\n  {BOLD}⚠ No sessions found for project:{RESET} {project_name}")
        return False

    # Sort by timestamp (newest first)
    project_sessions.sort(
        key=lambda n: parse_timestamp(n.timestamp) if n.timestamp else datetime.min,
        reverse=True
    )

    project_sessions = project_sessions[:limit]

    lines = []
    lines.append("\n" + box_header(f"🌳 PROJECT GRAPH: {truncate(project_name, 40)}", color=CYAN))
    lines.append("")
    lines.append(f"  {BOLD}{len(project_sessions)} sessions found{RESET}")
    lines.append(separator("─", 2))
    lines.append("")

    # Group by era
    era_groups = defaultdict(list)
    for node in project_sessions:
        era = classify_era(node.timestamp)
        era_groups[era.code].append(node)

    # Display by era
    for era in ERAS:
        sessions = era_groups.get(era.code, [])
        if not sessions:
            continue

        lines.append(f"  {era.color}{BOLD}{era.emoji} {era.name.upper()} - {era.time_period} ({len(sessions)}){RESET}")
        lines.append(separator("─", 2, era.color))

        for node in sessions:
            time_str = format_timestamp_relative(node.timestamp)
            summary = truncate(node.summary or "No summary", max_len=45)

            lines.append(f"     │ #{node.session_id[:8]} │ {time_str:10} │ {summary}")

        lines.append("")

    # Commands
    lines.append(separator("═", 2, BOLD))
    lines.append(f"  {BOLD}⏰ QUICK COMMANDS{RESET}")
    lines.append(separator("─", 2))

    for i, node in enumerate(project_sessions[:5], 1):
        era = classify_era(node.timestamp)
        lines.append(f"  {era.emoji} #{i}: claude --continue {node.session_id}")

    lines.append("")

    print("\n".join(lines))
    return True


# ============================================================
# CLI Testing
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "--project" and len(sys.argv) > 2:
            graph_project_command(sys.argv[2])
        else:
            graph_command(arg)
    else:
        print("Usage:")
        print("  python session_graph.py <session_id>      # Show related sessions")
        print("  python session_graph.py --project <name>  # Show project timeline")
        print()
        print("Example:")
        print("  python session_graph.py bf695425")
        print("  python session_graph.py --project magnusview")
