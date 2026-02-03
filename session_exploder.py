"""
Session Exploder - Break down sessions into component parts

Like CADDY's exploded view for CAD models, this extracts the "parts"
of a Claude Code session:
  - Goals (what was asked)
  - Files touched (what changed)
  - Tools used (how it was done)
  - Decisions (choices made)
  - Outcome (AI summary)
  - Duration (time invested)
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Set
from datetime import datetime

from chrono_utils import parse_timestamp, format_timestamp_relative
from summary_store import SummaryStore


@dataclass
class ExplodedSession:
    """A session broken into its component parts."""
    session_id: str
    project: str

    # Core components
    goals: List[str] = field(default_factory=list)
    files_touched: Dict[str, Set[str]] = field(default_factory=dict)  # {action: set(files)}
    tools_used: Dict[str, int] = field(default_factory=dict)  # {tool: count}
    decisions: List[str] = field(default_factory=list)

    # Metadata
    outcome: Optional[str] = None
    duration_minutes: Optional[int] = None
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    message_count: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0


def parse_raw_session(path: Path) -> List[dict]:
    """Parse raw JSONL session file."""
    messages = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error reading {path}: {e}")
    return messages


def extract_goals(messages: List[dict], max_goals: int = 5) -> List[str]:
    """
    Extract user goals from the session.

    Focuses on early user messages and questions that indicate intent.
    """
    goals = []

    for msg in messages[:20]:  # Focus on first 20 messages
        msg_type = msg.get("type", "")

        if msg_type == "user":
            message_obj = msg.get("message", {})
            content = message_obj.get("content", "")

            # Handle content as list or string
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                text = " ".join(text_parts)
            else:
                text = str(content)

            text = text.strip()
            if not text or len(text) < 10:
                continue

            # Clean and truncate
            text = re.sub(r'\s+', ' ', text)

            # Skip system-like messages
            if text.startswith("Result of") or text.startswith("<system"):
                continue

            # Extract the core request (first sentence or up to 120 chars)
            if ". " in text[:150]:
                goal = text.split(". ")[0] + "."
            else:
                goal = text[:120] + ("..." if len(text) > 120 else "")

            if goal and goal not in goals:
                goals.append(goal)

            if len(goals) >= max_goals:
                break

    return goals


def extract_files_and_tools(messages: List[dict]) -> tuple:
    """
    Extract files touched and tools used from session.

    Returns:
        (files_touched, tools_used) tuple
    """
    files_touched = {
        "read": set(),
        "edited": set(),
        "created": set(),
    }
    tools_used = {}

    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "assistant":
            message_obj = msg.get("message", {})
            content = message_obj.get("content", [])

            if not isinstance(content, list):
                continue

            for item in content:
                if not isinstance(item, dict):
                    continue

                if item.get("type") == "tool_use":
                    tool_name = item.get("name", "unknown")
                    tool_input = item.get("input", {})

                    # Count tool usage
                    tools_used[tool_name] = tools_used.get(tool_name, 0) + 1

                    # Extract file paths
                    file_path = tool_input.get("file_path") or tool_input.get("path", "")

                    if file_path:
                        # Shorten path for display
                        short_path = shorten_path(file_path)

                        if tool_name == "Read":
                            files_touched["read"].add(short_path)
                        elif tool_name == "Edit":
                            files_touched["edited"].add(short_path)
                        elif tool_name == "Write":
                            files_touched["created"].add(short_path)

    return files_touched, tools_used


def shorten_path(path: str, max_parts: int = 3) -> str:
    """Shorten a file path for display."""
    if not path:
        return ""

    parts = Path(path).parts

    # Skip common prefixes
    skip = {"Users", "Library", "CloudStorage", "home"}
    filtered = [p for p in parts if p not in skip and not p.startswith("GoogleDrive-")]

    if len(filtered) > max_parts:
        return ".../" + "/".join(filtered[-max_parts:])

    return "/".join(filtered) if filtered else path


def extract_decisions(messages: List[dict], max_decisions: int = 3) -> List[str]:
    """
    Extract key decisions made during the session.

    Looks for patterns like "I'll use...", "Let's go with...", "choosing..."
    """
    decisions = []
    decision_patterns = [
        r"I'll use ([^.]+)",
        r"I'll ([^.]+) instead",
        r"Let's go with ([^.]+)",
        r"[Cc]hoosing ([^.]+)",
        r"[Dd]ecided to ([^.]+)",
        r"[Bb]etter to ([^.]+)",
        r"[Rr]ecommend ([^.]+)",
    ]

    for msg in messages:
        msg_type = msg.get("type", "")

        if msg_type == "assistant":
            message_obj = msg.get("message", {})
            content = message_obj.get("content", [])

            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                text = " ".join(text_parts)
            else:
                text = str(content)

            for pattern in decision_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    decision = match.strip()[:80]
                    if decision and len(decision) > 10 and decision not in decisions:
                        decisions.append(decision)
                        if len(decisions) >= max_decisions:
                            return decisions

    return decisions


def calculate_duration(messages: List[dict]) -> tuple:
    """
    Calculate session duration from timestamps.

    Returns:
        (duration_minutes, first_ts, last_ts)
    """
    timestamps = []

    for msg in messages:
        ts = msg.get("timestamp")
        if ts:
            timestamps.append(ts)

    if not timestamps:
        return None, None, None

    first_ts = timestamps[0]
    last_ts = timestamps[-1]

    first_dt = parse_timestamp(first_ts)
    last_dt = parse_timestamp(last_ts)

    if first_dt and last_dt:
        delta = last_dt - first_dt
        duration_minutes = int(delta.total_seconds() / 60)
        return duration_minutes, first_ts, last_ts

    return None, first_ts, last_ts


def explode_session(path: Path) -> Optional[ExplodedSession]:
    """
    Explode a session into its component parts.

    Like CADDY's exploded CAD view - shows all the "parts" of a session.
    """
    session_id = path.stem

    # Extract project name
    project_dir = path.parent.name
    parts = project_dir.split("-")
    skip_words = {"Users", "anjacarrillo", "Desktop", "Documents", "Projects",
                  "Claude", "Code", "Library", "CloudStorage", "GoogleDrive"}
    project_parts = [p for p in parts if p and p not in skip_words]
    project = "-".join(project_parts[-3:]) if len(project_parts) > 3 else "-".join(project_parts)

    # Parse raw messages
    messages = parse_raw_session(path)
    if not messages:
        return None

    # Count messages by type
    user_count = 0
    assistant_count = 0
    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type == "user":
            user_count += 1
        elif msg_type == "assistant":
            assistant_count += 1

    # Extract components
    goals = extract_goals(messages)
    files_touched, tools_used = extract_files_and_tools(messages)
    decisions = extract_decisions(messages)
    duration, first_ts, last_ts = calculate_duration(messages)

    # Get AI summary if available
    summary_store = SummaryStore()
    outcome = summary_store.get(session_id)

    return ExplodedSession(
        session_id=session_id,
        project=project if project else "unknown",
        goals=goals,
        files_touched=files_touched,
        tools_used=tools_used,
        decisions=decisions,
        outcome=outcome,
        duration_minutes=duration,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        message_count=len(messages),
        user_message_count=user_count,
        assistant_message_count=assistant_count,
    )


def format_exploded_view(exploded: ExplodedSession, use_color: bool = True) -> str:
    """
    Format an exploded session as a visual display.

    Like CADDY showing CAD components laid out.
    """
    # Colors
    if use_color:
        RESET = "\033[0m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        YELLOW = "\033[94m"  # Blue (visible on light backgrounds)
        MAGENTA = "\033[95m"
        WHITE = "\033[90m"  # Dark gray (visible on light backgrounds)
    else:
        RESET = BOLD = DIM = CYAN = GREEN = YELLOW = MAGENTA = WHITE = ""

    lines = []

    # Header
    short_id = exploded.session_id[:8]
    lines.append(f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗{RESET}")
    lines.append(f"{BOLD}{CYAN}║  🔬 EXPLODED VIEW: #{short_id}  {RESET}")
    lines.append(f"{BOLD}{CYAN}║  📁 Project: {exploded.project[:45]:<45}{RESET}")
    lines.append(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════════╝{RESET}")

    # Duration & Stats
    if exploded.duration_minutes is not None:
        if exploded.duration_minutes < 60:
            duration_str = f"{exploded.duration_minutes} min"
        else:
            hours = exploded.duration_minutes // 60
            mins = exploded.duration_minutes % 60
            duration_str = f"{hours}h {mins}m"
    else:
        duration_str = "unknown"

    time_ago = format_timestamp_relative(exploded.first_timestamp)

    lines.append(f"\n{DIM}⏱️  Duration: {duration_str} │ When: {time_ago} │ Messages: {exploded.message_count}{RESET}")

    # Goals
    lines.append(f"\n{BOLD}{GREEN}🎯 GOALS (What was asked){RESET}")
    lines.append(f"{GREEN}{'─' * 50}{RESET}")
    if exploded.goals:
        for i, goal in enumerate(exploded.goals, 1):
            lines.append(f"   {i}. {goal}")
    else:
        lines.append(f"   {DIM}(no clear goals extracted){RESET}")

    # Files Touched
    lines.append(f"\n{BOLD}{YELLOW}📁 FILES TOUCHED{RESET}")
    lines.append(f"{YELLOW}{'─' * 50}{RESET}")

    has_files = False

    if exploded.files_touched.get("edited"):
        has_files = True
        lines.append(f"   {BOLD}✏️  Edited:{RESET}")
        for f in sorted(exploded.files_touched["edited"])[:8]:
            lines.append(f"      • {f}")

    if exploded.files_touched.get("created"):
        has_files = True
        lines.append(f"   {BOLD}➕ Created:{RESET}")
        for f in sorted(exploded.files_touched["created"])[:5]:
            lines.append(f"      • {f}")

    if exploded.files_touched.get("read"):
        has_files = True
        read_count = len(exploded.files_touched["read"])
        sample = sorted(exploded.files_touched["read"])[:5]
        lines.append(f"   {BOLD}👁️  Read:{RESET} ({read_count} files)")
        for f in sample:
            lines.append(f"      • {f}")
        if read_count > 5:
            lines.append(f"      {DIM}... and {read_count - 5} more{RESET}")

    if not has_files:
        lines.append(f"   {DIM}(no file operations detected){RESET}")

    # Tools Used
    lines.append(f"\n{BOLD}{MAGENTA}🔧 TOOLS USED{RESET}")
    lines.append(f"{MAGENTA}{'─' * 50}{RESET}")
    if exploded.tools_used:
        # Sort by usage count
        sorted_tools = sorted(exploded.tools_used.items(), key=lambda x: x[1], reverse=True)
        tool_strs = [f"{name} ({count}x)" for name, count in sorted_tools[:10]]
        lines.append(f"   {', '.join(tool_strs)}")
    else:
        lines.append(f"   {DIM}(no tool usage detected){RESET}")

    # Decisions
    if exploded.decisions:
        lines.append(f"\n{BOLD}{WHITE}💡 DECISIONS MADE{RESET}")
        lines.append(f"{WHITE}{'─' * 50}{RESET}")
        for decision in exploded.decisions:
            lines.append(f"   • {decision}")

    # Outcome
    lines.append(f"\n{BOLD}{CYAN}🏁 OUTCOME{RESET}")
    lines.append(f"{CYAN}{'─' * 50}{RESET}")
    if exploded.outcome:
        lines.append(f"   {exploded.outcome}")
    else:
        lines.append(f"   {DIM}(no AI summary available - run generate_summaries.py){RESET}")

    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI Testing
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Explode specific session
        session_arg = sys.argv[1]

        # Find session file
        claude_dir = Path.home() / ".claude" / "projects"
        session_path = None

        for jsonl_file in claude_dir.glob("**/*.jsonl"):
            if jsonl_file.stem.startswith(session_arg) or session_arg in jsonl_file.stem:
                session_path = jsonl_file
                break

        if session_path:
            print(f"\nExploding session: {session_path.stem[:20]}...")
            exploded = explode_session(session_path)
            if exploded:
                print(format_exploded_view(exploded))
            else:
                print("Could not explode session")
        else:
            print(f"Session not found: {session_arg}")
    else:
        print("Usage: python session_exploder.py <session_id>")
        print("\nExample: python session_exploder.py bf695425")
