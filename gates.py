#!/usr/bin/env python3
"""
Time Gates - Session Bookmarking for Project Epoch

In Chrono Trigger, Time Gates are portals connecting different eras.
The "End of Time" is a hub where you can access any time period.

In Project Epoch, Time Gates let you bookmark important sessions
for instant access - your personal hub between all your work.

Usage:
    gate save my-auth-work              # Bookmark current/recent session
    gate save dashboard-v2 abc123       # Bookmark specific session
    gate list                           # Show all bookmarks (End of Time)
    gate jump my-auth-work              # Get command to continue session
    gate delete my-auth-work            # Remove bookmark
    gate rename old-name new-name       # Rename a bookmark
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

from chrono_utils import (
    END_OF_TIME, RESET, BOLD, DIM,
    classify_era, format_timestamp_relative,
    separator
)
from chrono_config import get_gates_path, atomic_write_json, safe_load_json

# Storage location (uses chrono_config for path)
GATES_FILE = get_gates_path()


def load_gates() -> Dict[str, Any]:
    """Load gates from storage (corruption-safe)."""
    default = {"gates": {}, "last_session": None}
    data = safe_load_json(GATES_FILE, default=default)
    if data is None:
        return default
    # Ensure structure
    if "gates" not in data:
        data["gates"] = {}
    return data


def save_gates(data: Dict[str, Any]) -> None:
    """Save gates to storage (atomic write)."""
    atomic_write_json(GATES_FILE, data, default=str)


def get_recent_session_id() -> Optional[str]:
    """Get the most recent session ID from Claude's projects directory."""
    claude_dir = Path.home() / ".claude" / "projects"

    if not claude_dir.exists():
        return None

    # Find all session files, sorted by modification time
    sessions = []
    for jsonl_file in claude_dir.glob("**/*.jsonl"):
        if not jsonl_file.name.startswith("agent-"):
            sessions.append((jsonl_file.stat().st_mtime, jsonl_file.stem))

    if not sessions:
        return None

    # Return most recently modified
    sessions.sort(reverse=True)
    return sessions[0][1]


def get_session_info(session_id: str) -> Optional[Dict[str, Any]]:
    """Get info about a session from the vector store, with filesystem fallback."""
    # Try vector store first (indexed sessions)
    try:
        from vector_store import SessionVectorStore
        store = SessionVectorStore()

        sessions = store.list_sessions(limit=10000)
        for session in sessions:
            if session.get("session_id", "").startswith(session_id):
                return session
    except Exception:
        pass

    # Fallback: extract project from session file on disk (active/unindexed sessions)
    try:
        from session_parser import extract_project_name
        claude_dir = Path.home() / ".claude" / "projects"
        for jsonl_file in claude_dir.glob(f"**/{session_id}*.jsonl"):
            project = extract_project_name(jsonl_file)
            timestamp = datetime.fromtimestamp(jsonl_file.stat().st_mtime).isoformat()

            # If path-based project is generic, scan content for a better match
            if project.startswith("-Users") or project == "unknown":
                project = _detect_project_from_content(jsonl_file) or project

            return {
                "session_id": session_id,
                "project": project,
                "timestamp": timestamp,
            }
    except Exception:
        pass

    return None


def _detect_project_from_content(session_path: Path) -> Optional[str]:
    """Lightweight project detection by scanning session file for known project keywords."""
    try:
        from project_classifier import KNOWN_PROJECTS

        # Read a sample of the file (first 200 lines) for speed
        sample = []
        with open(session_path, "r", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 200:
                    break
                sample.append(line)

        combined = " ".join(sample).lower()

        best_match = None
        best_score = 0

        for proj_name, proj_info in KNOWN_PROJECTS.items():
            score = 0
            for kw in proj_info["keywords"]:
                if kw.lower() in combined:
                    score += 2
            for pattern in proj_info["file_patterns"]:
                if pattern.lower() in combined:
                    score += 3

            if score > best_score:
                best_score = score
                best_match = proj_name

        return best_match if best_match and best_score >= 4 else None
    except Exception:
        return None


def _get_project_emoji(project: str) -> str:
    """Get the emoji for a known project, or a default."""
    try:
        from project_classifier import KNOWN_PROJECTS
        proj_lower = project.lower().replace("-", "").replace("_", "")
        for proj_name, proj_info in KNOWN_PROJECTS.items():
            key_lower = proj_name.lower().replace("-", "").replace("_", "")
            # Match exact, substring, or keyword overlap
            if key_lower == proj_lower or key_lower in proj_lower or proj_lower in key_lower:
                return proj_info["emoji"]
    except Exception:
        pass
    return "📂"


def validate_gate_name(name: str) -> bool:
    """Validate a gate name (alphanumeric, hyphens, underscores)."""
    import re
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))


# ============================================================
# Gate Commands
# ============================================================

def cmd_save(name: str, session_id: Optional[str] = None, notes: str = "") -> None:
    """Save a session as a named Time Gate."""

    # Validate name
    if not name or not name.strip():
        print(f"\n  {BOLD}Error:{RESET} Gate name cannot be empty.")
        print(f"  {DIM}Usage: gate save <name> [session-id]{RESET}")
        print(f"  {DIM}Example: gate save my-auth-session{RESET}")
        return

    if not validate_gate_name(name):
        print(f"\n  {BOLD}Error:{RESET} Gate name can only contain letters, numbers, hyphens, and underscores.")
        print(f"  {DIM}Example: my-auth-session, dashboard_v2, feature123{RESET}")
        return

    # Get session ID
    if not session_id:
        session_id = get_recent_session_id()
        if not session_id:
            print(f"\n  {BOLD}Error:{RESET} No recent session found.")
            print(f"  {DIM}Specify a session ID: gate save {name} <session-id>{RESET}")
            return

    # Load existing gates
    data = load_gates()

    # Check if name already exists
    if name in data["gates"]:
        existing = data["gates"][name]
        print(f"\n  {BOLD}Warning:{RESET} Gate '{name}' already exists!")
        print(f"  {DIM}Current: {existing['session_id'][:8]}... ({existing.get('created', 'unknown')}){RESET}")
        try:
            confirm = input(f"  Overwrite? (y/N): ").strip().lower()
            if confirm != 'y':
                print(f"  {DIM}Cancelled.{RESET}")
                return
        except KeyboardInterrupt:
            print(f"\n  {DIM}Cancelled.{RESET}")
            return

    # Get session info for display
    session_info = get_session_info(session_id)
    project = session_info.get("project", "unknown") if session_info else "unknown"
    timestamp = session_info.get("timestamp") if session_info else None

    # Save the gate
    data["gates"][name] = {
        "session_id": session_id,
        "project": project,
        "created": datetime.now().isoformat(),
        "timestamp": timestamp,
        "notes": notes
    }
    save_gates(data)

    # Display confirmation
    era = classify_era(timestamp)
    rel_time = format_timestamp_relative(timestamp)
    proj_emoji = _get_project_emoji(project)

    print(f"\n  {END_OF_TIME.color}{END_OF_TIME.emoji} TIME GATE SAVED{RESET}")
    print(separator("─", 2))
    print(f"  {BOLD}{name}{RESET}")
    print(f"  {proj_emoji} {project}  {DIM}│{RESET}  {era.emoji} {era.time_period} ({rel_time})")
    if notes:
        print(f"  {DIM}📝 {notes}{RESET}")
    print(separator("─", 2))
    print(f"\n  {DIM}Jump back:{RESET} chrono gate jump {name}\n")


def cmd_list() -> None:
    """List all Time Gates (End of Time view)."""
    data = load_gates()
    gates = data.get("gates", {})

    print(f"\n  {END_OF_TIME.color}{BOLD}")
    print(f"  ⏳ END OF TIME - Your Bookmarked Sessions")
    print(separator("═", 2) + "\n")

    if not gates:
        print(f"  {BOLD}⏳ No Time Gates saved yet{RESET}\n")
        print(f"  {DIM}Gates are bookmarks to important sessions.{RESET}")
        print(f"  {DIM}Save one and jump back anytime.{RESET}\n")
        print(f"  {BOLD}Quick start:{RESET}")
        print(f"    gate save my-project            {DIM}← Bookmark latest session{RESET}")
        print(f"    gate save auth-work abc12345     {DIM}← Bookmark specific session{RESET}")
        print(f"    gate save feature --notes \"WIP\"  {DIM}← Add notes{RESET}")
        print()
        return

    # Sort by creation date (newest first)
    sorted_gates = sorted(
        gates.items(),
        key=lambda x: x[1].get("created", ""),
        reverse=True
    )

    # Refresh gates with missing/generic project or timestamp from vector store
    dirty = False
    for name, gate in gates.items():
        project = gate.get("project", "unknown")
        needs_refresh = (
            not gate.get("timestamp")
            or project == "unknown"
            or project.startswith("-Users")
        )
        if needs_refresh:
            info = get_session_info(gate.get("session_id", ""))
            if info:
                if not gate.get("timestamp") and info.get("timestamp"):
                    gate["timestamp"] = info["timestamp"]
                    dirty = True
                if info.get("project") and info["project"] != project:
                    # Only update if the new project is more specific
                    new_proj = info["project"]
                    if new_proj != "unknown" and not new_proj.startswith("-Users"):
                        gate["project"] = new_proj
                        dirty = True
    if dirty:
        save_gates(data)

    for i, (name, gate) in enumerate(sorted_gates, 1):
        project = gate.get("project", "unknown")
        timestamp = gate.get("timestamp")
        notes = gate.get("notes", "")

        era = classify_era(timestamp)
        rel_time = format_timestamp_relative(timestamp)
        proj_emoji = _get_project_emoji(project)

        print(f"  {BOLD}› {name}{RESET}")
        print(f"    {proj_emoji} {project}  {DIM}│{RESET}  {era.color}{era.emoji} {era.time_period}{RESET}  {DIM}│{RESET}  {rel_time}")
        if notes:
            print(f"    {DIM}📝 {notes}{RESET}")
        print()

    print(separator("─", 2, DIM))
    print(f"  {BOLD}Total: {len(gates)} gates{RESET}\n")

    # Quick reference
    print(f"  {DIM}Jump:{RESET}   gate jump <name>")
    print(f"  {DIM}Delete:{RESET} gate delete <name>")
    print(f"  {DIM}Rename:{RESET} gate rename <old> <new>\n")


def cmd_jump(name: str) -> None:
    """Get the command to jump to a Time Gate."""
    data = load_gates()
    gates = data.get("gates", {})

    if name not in gates:
        print(f"\n  {BOLD}Error:{RESET} Gate '{name}' not found.")

        # Suggest similar names (substring match)
        similar = [n for n in gates.keys() if name.lower() in n.lower()]
        if similar:
            print(f"  {DIM}Did you mean: {', '.join(similar)}?{RESET}")
        elif gates:
            # Show all available gates as suggestions
            gate_names = sorted(gates.keys())
            print(f"  {DIM}Available gates: {', '.join(gate_names)}{RESET}")
        else:
            print(f"  {DIM}No gates saved yet. Create one: gate save <name>{RESET}")
        return

    gate = gates[name]
    session_id = gate.get("session_id")
    project = gate.get("project", "unknown")
    timestamp = gate.get("timestamp")

    era = classify_era(timestamp)
    rel_time = format_timestamp_relative(timestamp)

    print(f"\n  {END_OF_TIME.color}{END_OF_TIME.emoji} ACTIVATING TIME GATE: {name}{RESET}")
    print(separator("─", 2))
    print(f"  {BOLD}Destination:{RESET} {era.emoji} {era.time_period} ({rel_time})")
    print(f"  {BOLD}Project:{RESET}     {project}")
    print(f"  {BOLD}Session:{RESET}     #{session_id[:8]}...")
    print(separator("─", 2))
    print(f"\n  {BOLD}⚡ Jump command:{RESET}")
    print(f"  claude --continue {session_id}\n")


def cmd_delete(name: str) -> None:
    """Delete a Time Gate."""
    data = load_gates()
    gates = data.get("gates", {})

    if name not in gates:
        print(f"\n  {BOLD}Error:{RESET} Gate '{name}' not found.")
        print(f"  {DIM}Use 'gate list' to see all gates.{RESET}")
        return

    gate = gates[name]

    # Confirm deletion
    print(f"\n  {BOLD}Delete gate '{name}'?{RESET}")
    print(f"  {DIM}Session: #{gate.get('session_id', 'unknown')[:8]}...{RESET}")

    try:
        confirm = input(f"  Confirm (y/N): ").strip().lower()
        if confirm != 'y':
            print(f"  {DIM}Cancelled.{RESET}")
            return
    except KeyboardInterrupt:
        print(f"\n  {DIM}Cancelled.{RESET}")
        return

    del data["gates"][name]
    save_gates(data)

    print(f"\n  {END_OF_TIME.emoji} Gate '{name}' deleted.\n")


def cmd_rename(old_name: str, new_name: str) -> None:
    """Rename a Time Gate."""

    # Validate new name
    if not validate_gate_name(new_name):
        print(f"\n  {BOLD}Error:{RESET} New name can only contain letters, numbers, hyphens, and underscores.")
        return

    data = load_gates()
    gates = data.get("gates", {})

    if old_name not in gates:
        print(f"\n  {BOLD}Error:{RESET} Gate '{old_name}' not found.")
        return

    if new_name in gates:
        print(f"\n  {BOLD}Error:{RESET} Gate '{new_name}' already exists.")
        return

    # Rename
    data["gates"][new_name] = data["gates"].pop(old_name)
    save_gates(data)

    print(f"\n  {END_OF_TIME.emoji} Gate renamed: {old_name} → {new_name}\n")


def cmd_info(name: str) -> None:
    """Show detailed info about a Time Gate."""
    data = load_gates()
    gates = data.get("gates", {})

    if name not in gates:
        print(f"\n  {BOLD}Error:{RESET} Gate '{name}' not found.")
        return

    gate = gates[name]
    session_id = gate.get("session_id", "unknown")
    project = gate.get("project", "unknown")
    timestamp = gate.get("timestamp")
    created = gate.get("created", "unknown")
    notes = gate.get("notes", "")

    era = classify_era(timestamp)
    rel_time = format_timestamp_relative(timestamp)

    print(f"\n  {END_OF_TIME.color}{END_OF_TIME.emoji} TIME GATE: {name}{RESET}")
    print(separator("═", 2))
    print(f"  {BOLD}Session ID:{RESET}    {session_id}")
    print(f"  {BOLD}Project:{RESET}       {project}")
    print(f"  {BOLD}Era:{RESET}           {era.emoji} {era.name} ({era.time_period})")
    print(f"  {BOLD}Session Time:{RESET}  {timestamp or 'unknown'} ({rel_time})")
    print(f"  {BOLD}Gate Created:{RESET}  {created}")
    if notes:
        print(f"  {BOLD}Notes:{RESET}         {notes}")
    print(separator("═", 2))
    print(f"\n  {DIM}Jump command:{RESET} claude --continue {session_id}\n")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Time Gates - Bookmark important sessions for instant access",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Commands:{RESET}
  save <name> [session-id]   Save a session as a named gate
  list                       Show all gates (End of Time)
  jump <name>                Get command to continue from gate
  delete <name>              Delete a gate
  rename <old> <new>         Rename a gate
  info <name>                Show detailed gate info

{BOLD}Examples:{RESET}
  gate save auth-work                    # Bookmark most recent session
  gate save dashboard-v2 abc12345        # Bookmark specific session
  gate save my-feature --notes "WIP"     # Add notes
  gate list                              # View all bookmarks
  gate jump auth-work                    # Get continue command
        """
    )

    parser.add_argument(
        "command",
        choices=["save", "list", "jump", "delete", "rename", "info"],
        help="Command to run"
    )

    parser.add_argument(
        "args",
        nargs="*",
        help="Command arguments"
    )

    parser.add_argument(
        "--notes", "-n",
        type=str,
        default="",
        help="Notes to attach to the gate (for save command)"
    )

    args = parser.parse_args()

    # Route to command handlers
    if args.command == "save":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a gate name.")
            print(f"  {DIM}Usage: gate save <name> [session-id]{RESET}")
            return
        name = args.args[0]
        session_id = args.args[1] if len(args.args) > 1 else None
        cmd_save(name, session_id, args.notes)

    elif args.command == "list":
        cmd_list()

    elif args.command == "jump":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a gate name.")
            print(f"  {DIM}Usage: gate jump <name>{RESET}")
            return
        cmd_jump(args.args[0])

    elif args.command == "delete":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a gate name.")
            print(f"  {DIM}Usage: gate delete <name>{RESET}")
            return
        cmd_delete(args.args[0])

    elif args.command == "rename":
        if len(args.args) < 2:
            print(f"\n  {BOLD}Error:{RESET} Please provide old and new names.")
            print(f"  {DIM}Usage: gate rename <old-name> <new-name>{RESET}")
            return
        cmd_rename(args.args[0], args.args[1])

    elif args.command == "info":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a gate name.")
            print(f"  {DIM}Usage: gate info <name>{RESET}")
            return
        cmd_info(args.args[0])


if __name__ == "__main__":
    main()
