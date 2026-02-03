"""
Chrono Welcome - Interactive menu and smart predictions

When you run `chrono` with no arguments, this creates an engaging
experience that asks what you want to do and suggests actions.

Now with SMART PROJECT DETECTION that properly classifies sessions!
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from chrono_utils import (
    ERAS, RESET, BOLD, DIM, CYAN,
    classify_era, format_timestamp_relative, parse_timestamp,
    separator, truncate, box_header
)
from summary_store import SummaryStore
from vector_store import SessionVectorStore
from project_classifier import (
    get_top_projects, ProjectInfo,
    pin_project, earmark_session, get_earmarked_sessions
)


# ============================================================
# Smart Predictions
# ============================================================

def get_recent_sessions(limit: int = 5) -> List[Dict]:
    """Get the most recently accessed sessions."""
    store = SessionVectorStore()
    summary_store = SummaryStore()

    all_sessions = store.list_sessions(limit=100)

    # Sort by timestamp (newest first)
    sessions_with_time = []
    for session in all_sessions:
        ts = session.get("timestamp")
        if ts:
            dt = parse_timestamp(ts)
            if dt:
                session["_dt"] = dt
                session["summary"] = summary_store.get(session["session_id"])
                session["era"] = classify_era(ts)
                session["relative_time"] = format_timestamp_relative(ts)
                sessions_with_time.append(session)

    sessions_with_time.sort(key=lambda s: s.get("_dt", datetime.min), reverse=True)

    return sessions_with_time[:limit]


def get_active_projects(sessions: List[Dict]) -> List[Tuple[str, int]]:
    """Get projects with recent activity - DEPRECATED, use get_top_projects instead."""
    project_counts = {}

    for session in sessions:
        project = session.get("project", "unknown")
        if project and project != "unknown" and not project.startswith("-Users"):
            project_counts[project] = project_counts.get(project, 0) + 1

    # Sort by count
    sorted_projects = sorted(project_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_projects[:3]


def get_time_greeting() -> str:
    """Get a time-appropriate greeting."""
    hour = datetime.now().hour

    if hour < 6:
        return "🌙 Late night coding session?"
    elif hour < 12:
        return "☀️ Good morning!"
    elif hour < 17:
        return "🌤️ Good afternoon!"
    elif hour < 21:
        return "🌆 Good evening!"
    else:
        return "🌙 Burning the midnight oil?"


def generate_predictions(recent_sessions: List[Dict]) -> List[Dict]:
    """
    Generate smart predictions for what the user might want to do.

    Returns list of prediction dicts with:
        - type: "continue", "explore", "search", "new"
        - label: Short description
        - command: Command to run
        - reason: Why this is suggested
    """
    predictions = []

    if not recent_sessions:
        return [{
            "type": "new",
            "label": "Start a new session",
            "command": "claude",
            "reason": "No recent sessions found"
        }]

    # 1. Continue most recent session
    most_recent = recent_sessions[0]
    era = most_recent.get("era", ERAS[0])
    summary = truncate(most_recent.get("summary", ""), max_len=50)

    predictions.append({
        "type": "continue",
        "label": f"Continue: {summary}..." if summary else "Continue where you left off",
        "command": f"claude --continue {most_recent['session_id']}",
        "reason": f"Your most recent session ({most_recent.get('relative_time', 'recently')})",
        "era": era
    })

    # 2. If there's a second recent session on a different project
    if len(recent_sessions) > 1:
        second = recent_sessions[1]
        if second.get("project") != most_recent.get("project"):
            s_era = second.get("era", ERAS[0])
            s_summary = truncate(second.get("summary", ""), max_len=45)
            predictions.append({
                "type": "continue",
                "label": f"Switch to: {s_summary}..." if s_summary else f"Switch to {second.get('project')}",
                "command": f"claude --continue {second['session_id']}",
                "reason": f"Different project you worked on {second.get('relative_time', 'recently')}",
                "era": s_era
            })

    # 3. Explore recent work
    predictions.append({
        "type": "explore",
        "label": "See what you've been working on",
        "command": "chrono eras",
        "reason": "Browse all your sessions by time era"
    })

    # 4. Search for something
    predictions.append({
        "type": "search",
        "label": "Search past sessions",
        "command": "chrono \"<your query>\"",
        "reason": "Find specific work from your history"
    })

    # 5. Visual exploration
    predictions.append({
        "type": "explore",
        "label": "Open visual explorer",
        "command": "chrono export && open ~/Desktop/session_explorer.html",
        "reason": "Interactive HTML view of all sessions"
    })

    # 6. Start fresh
    predictions.append({
        "type": "new",
        "label": "Start something new",
        "command": "claude",
        "reason": "Begin a fresh session"
    })

    return predictions


# ============================================================
# Interactive Menu
# ============================================================

def _welcome_banner() -> str:
    return "\n" + box_header(
        "⏰ CHRONO - Project Epoch",
        subtitle="Time-Travel Through Your Code History",
        indent=3, color=CYAN
    ) + "\n"


def show_welcome_menu() -> Optional[str]:
    """
    Show interactive welcome menu with smart project detection.

    Returns:
        Command to execute, or None if cancelled
    """
    print(_welcome_banner())

    # Get greeting
    greeting = get_time_greeting()
    print(f"  {greeting} What would you like to do?\n")

    # ============================================================
    # SMART PROJECT DETECTION - Show your active projects
    # ============================================================
    print(f"  {BOLD}📁 YOUR PROJECTS{RESET}")
    print(separator("─", 2) + "\n")

    top_projects = get_top_projects(4)
    project_commands = []

    for i, proj in enumerate(top_projects, 1):
        # Status indicators
        indicators = []
        if proj.is_pinned:
            indicators.append("📌")
        if proj.has_unfinished_work:
            indicators.append("⚠️ WIP")

        indicator_str = f" {' '.join(indicators)}" if indicators else ""

        # Time info
        if proj.last_activity:
            time_str = format_timestamp_relative(proj.last_activity.isoformat())
        else:
            time_str = "unknown"

        print(f"  {BOLD}{i}.{RESET} {proj.emoji} {proj.name}{indicator_str}")
        print(f"     {proj.session_count} sessions │ last: {time_str}")

        if proj.last_session_summary:
            preview = truncate(proj.last_session_summary, max_len=45)
            print(f"     {DIM}\"{preview}\"{RESET}")

        print()

        # Store command for this project
        if proj.last_session_id:
            project_commands.append({
                "type": "project",
                "label": f"Continue {proj.name}",
                "command": f"claude --continue {proj.last_session_id}",
                "project": proj
            })

    # Quick actions section
    print(f"  {BOLD}⚡ QUICK ACTIONS{RESET}")
    print(separator("─", 2))
    print(f"  {DIM}s{RESET} │ Search       │ Find sessions by keyword")
    print(f"  {DIM}e{RESET} │ Eras         │ Browse by time period")
    print()
    print(f"  {BOLD}🔬 CADDY-STYLE{RESET}")
    print(separator("─", 2))
    print(f"  {DIM}x{RESET} │ Explode      │ Break apart a session")
    print(f"  {DIM}t{RESET} │ Tree         │ Visual relationship tree")
    print(f"  {DIM}m{RESET} │ Similar      │ Find semantically related sessions")
    print(f"  {DIM}g{RESET} │ Graph        │ Session connections")
    print(f"  {DIM}h{RESET} │ HTML         │ Open project dashboard")
    print()
    print(f"  {BOLD}🛠️ TOOLS{RESET}")
    print(separator("─", 2))
    print(f"  {DIM}l{RESET} │ Lavos        │ Project health scan 🔥")
    print(f"  {DIM}k{RESET} │ Tech         │ Run workflow automation")
    print(f"  {DIM}w{RESET} │ Gate         │ Time gate bookmarks")
    print(f"  {DIM}i{RESET} │ Epoch        │ Git time machine")
    print(f"  {DIM}r{RESET} │ Reindex      │ Force re-index all sessions 🔄")
    print()
    print(f"  {BOLD}📍 OTHER{RESET}")
    print(separator("─", 2))
    print(f"  {DIM}n{RESET} │ New          │ Start fresh session")
    print(f"  {DIM}p{RESET} │ Pin          │ Pin/unpin a project")
    print(f"  {DIM}q{RESET} │ Quit         │ Exit chrono")
    print()

    # Get user choice
    try:
        choice = input(f"  {BOLD}Select project (1-{len(project_commands)}) or action >{RESET} ").strip().lower()

        if not choice or choice == "q":
            print(f"\n  {DIM}Until next time, time traveler! ⏰{RESET}\n")
            return None

        # Handle numbered PROJECT selections
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(project_commands):
                proj_cmd = project_commands[idx]
                proj = proj_cmd["project"]
                print(f"\n  {BOLD}✓ Opening {proj.emoji} {proj.name}{RESET}")
                print(f"  {DIM}{proj_cmd['command']}{RESET}\n")
                return proj_cmd["command"]
            else:
                print(f"  {DIM}Select 1-{len(project_commands)} for projects{RESET}")
                return None

        # Handle letter shortcuts
        if choice == "s":
            query = input(f"  {BOLD}Search for:{RESET} ").strip()
            if query:
                return f'chrono "{query}"'
            return None

        if choice == "e":
            return "chrono eras"

        if choice == "x":
            session_id = input(f"  {BOLD}Session ID to explode:{RESET} ").strip()
            if session_id:
                return f"chrono explode {session_id}"
            return None

        if choice == "t":
            session_id = input(f"  {BOLD}Session ID for tree:{RESET} ").strip()
            if session_id:
                return f"chrono tree {session_id}"
            return None

        if choice == "m":
            session_id = input(f"  {BOLD}Session ID to find similar:{RESET} ").strip()
            if session_id:
                return f"chrono similar {session_id}"
            return None

        if choice == "g":
            target = input(f"  {BOLD}Session ID or project name:{RESET} ").strip()
            if target:
                # If it looks like a session ID (hex), use it directly
                if len(target) >= 6 and all(c in '0123456789abcdef-' for c in target.lower()):
                    return f"chrono graph {target}"
                else:
                    return f"chrono graph --project {target}"
            return None

        if choice == "h":
            return "chrono export"

        if choice == "l":
            print(f"\n  {BOLD}🔥 Scanning for Lavos...{RESET}\n")
            return "lavos"

        if choice == "k":
            print(f"\n  {BOLD}⚔️ Available Techs:{RESET}")
            print(f"  {DIM}fire (build), ice (test), slash (lint), cure (fix){RESET}")
            print(f"  {DIM}antipode (build+test), luminaire (full CI){RESET}\n")
            tech_name = input(f"  {BOLD}Tech to run (or 'list'):{RESET} ").strip()
            if tech_name:
                return f"tech {tech_name}"
            return None

        if choice == "w":
            print(f"\n  {BOLD}⏰ Time Gates:{RESET}")
            print(f"  {DIM}save <name>, list, jump <name>, delete <name>{RESET}\n")
            gate_cmd = input(f"  {BOLD}Gate command:{RESET} ").strip()
            if gate_cmd:
                return f"gate {gate_cmd}"
            return "gate list"

        if choice == "i":
            print(f"\n  {BOLD}🕰️ Epoch Git Commands:{RESET}")
            print(f"  {DIM}log, branches, timeline, jump <branch>{RESET}\n")
            epoch_cmd = input(f"  {BOLD}Epoch command (or Enter for status):{RESET} ").strip()
            if epoch_cmd:
                return f"egit {epoch_cmd}"
            return "egit"

        if choice == "r":
            print(f"\n  {BOLD}🔄 FORCE RE-INDEX{RESET}")
            print(f"  {DIM}This will re-index ALL sessions with fresh timestamps.{RESET}")
            print(f"  {DIM}Use this when sessions show wrong 'When' times.{RESET}\n")
            confirm = input(f"  {BOLD}Re-index all sessions? (y/N):{RESET} ").strip().lower()
            if confirm == "y":
                print(f"\n  {BOLD}⏳ Starting re-index... (runs in background){RESET}")
                print(f"  {DIM}Run 'chrono export' when done to refresh dashboard{RESET}\n")
                return "cd ~/Desktop/smart-forking && source venv/bin/activate && python indexer.py --reindex"
            return None

        if choice == "n":
            print(f"\n  {BOLD}✓ Starting fresh timeline{RESET}")
            print(f"  Run: claude\n")
            return "claude"

        if choice == "p":
            proj_name = input(f"  {BOLD}Project to pin/unpin:{RESET} ").strip()
            if proj_name:
                pin_project(proj_name)
                print(f"  {BOLD}✅ Pinned: {proj_name}{RESET}\n")
            return None

        # Maybe they typed a session ID directly
        if len(choice) >= 6:
            return f"claude --continue {choice}"

        print(f"  {DIM}Unknown option. Try number (1-{len(project_commands)}) or letter{RESET}")
        return None

    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Time travel cancelled{RESET}\n")
        return None
    except EOFError:
        return None


def format_quick_status() -> str:
    """Format a quick status line showing recent activity."""
    recent = get_recent_sessions(3)
    store = SessionVectorStore()
    stats = store.get_stats()

    total = stats.get("total_sessions", 0)
    projects = get_active_projects(recent)

    lines = [
        f"\n  {DIM}📊 {total} sessions indexed{RESET}",
    ]

    if projects:
        proj_str = ", ".join([p[0] for p in projects[:2]])
        lines.append(f"  {DIM}📁 Recent: {proj_str}{RESET}")

    if recent:
        last = recent[0]
        lines.append(f"  {DIM}🕐 Last: {last.get('relative_time', 'unknown')}{RESET}")

    return "\n".join(lines)


# ============================================================
# CLI Testing
# ============================================================

if __name__ == "__main__":
    result = show_welcome_menu()
    if result:
        print(f"\n  Would run: {result}")
