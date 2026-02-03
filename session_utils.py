"""
Session Utilities - Active session detection and management

Detects running Claude sessions, warns about duplicates, and provides
session exclusion for search operations.
"""

import subprocess
import re
from pathlib import Path
from typing import Set, Optional, List, Dict
from dataclasses import dataclass

from chrono_utils import RESET, BOLD, WARNING


@dataclass
class ActiveSession:
    """Information about a running Claude session."""
    session_id: str
    pid: int
    command: str
    terminal: Optional[str] = None


def get_active_sessions() -> List[ActiveSession]:
    """
    Detect all currently running Claude sessions.

    Parses `ps aux` output to find `claude --continue <session-id>` processes.

    Returns:
        List of ActiveSession objects for each running session
    """
    active = []

    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Pattern to match: claude --continue <session-id>
        # Session IDs are UUIDs: 8-4-4-4-12 hex chars
        pattern = r'claude\s+--continue\s+([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})'

        for line in result.stdout.splitlines():
            match = re.search(pattern, line)
            if match:
                session_id = match.group(1)
                # Extract PID (second column in ps aux)
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pid = int(parts[1])
                        active.append(ActiveSession(
                            session_id=session_id,
                            pid=pid,
                            command=line.strip()
                        ))
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Warning: Could not detect active sessions: {e}")

    return active


def get_active_session_ids() -> Set[str]:
    """Get just the session IDs of all active sessions."""
    return {s.session_id for s in get_active_sessions()}


def is_session_active(session_id: str) -> bool:
    """Check if a specific session is currently active."""
    # Handle both full and short IDs
    active_ids = get_active_session_ids()

    if session_id in active_ids:
        return True

    # Check for partial match (short ID)
    for active_id in active_ids:
        if active_id.startswith(session_id):
            return True

    return False


def get_duplicate_sessions() -> Dict[str, List[ActiveSession]]:
    """
    Find sessions that are open in multiple terminals.

    Returns:
        Dict mapping session_id to list of ActiveSession objects
        (only includes sessions with 2+ instances)
    """
    active = get_active_sessions()

    # Group by session ID
    by_session = {}
    for session in active:
        if session.session_id not in by_session:
            by_session[session.session_id] = []
        by_session[session.session_id].append(session)

    # Return only duplicates
    return {sid: sessions for sid, sessions in by_session.items() if len(sessions) > 1}


def warn_duplicate_sessions() -> bool:
    """
    Print warnings if any sessions are open in multiple terminals.

    Returns:
        True if duplicates were found, False otherwise
    """
    duplicates = get_duplicate_sessions()

    if not duplicates:
        return False

    print(f"\n{WARNING}⚠️  WARNING: Duplicate sessions detected!{RESET}")
    print("The following sessions are open in multiple terminals:\n")

    for session_id, sessions in duplicates.items():
        print(f"  {BOLD}#{session_id[:8]}{RESET} - {len(sessions)} instances:")
        for s in sessions:
            print(f"    PID {s.pid}")

    print(f"\n{WARNING}This can cause:")
    print("  - Session file corruption")
    print("  - Indexing failures ('no content to index')")
    print(f"  - Search returning stale results{RESET}")
    print("\nRecommendation: Close duplicate terminals before indexing.\n")

    return True


def get_current_session_id() -> Optional[str]:
    """
    Try to detect the current session ID.

    This is tricky because we're running inside a Claude session.
    We look for environment variables or session files that might indicate
    which session we're in.

    Returns:
        Session ID if detectable, None otherwise
    """
    import os

    # Check environment variable (if Claude sets one)
    session_id = os.environ.get('CLAUDE_SESSION_ID')
    if session_id:
        return session_id

    # Check for session file in current working directory's .claude
    cwd = Path.cwd()
    claude_dir = cwd / '.claude'
    if claude_dir.exists():
        # Look for recent session files
        sessions = list(claude_dir.glob('*.jsonl'))
        if sessions:
            # Return most recently modified
            most_recent = max(sessions, key=lambda p: p.stat().st_mtime)
            return most_recent.stem

    return None


def filter_active_sessions(session_ids: List[str], exclude_active: bool = True) -> List[str]:
    """
    Filter out active sessions from a list.

    Args:
        session_ids: List of session IDs to filter
        exclude_active: If True, remove active sessions from the list

    Returns:
        Filtered list of session IDs
    """
    if not exclude_active:
        return session_ids

    active = get_active_session_ids()
    return [sid for sid in session_ids if sid not in active]


# CLI for testing
if __name__ == "__main__":
    print("=== Active Session Detection ===\n")

    active = get_active_sessions()
    if active:
        print(f"Found {len(active)} active session(s):\n")
        for session in active:
            print(f"  #{session.session_id[:8]}...")
            print(f"    PID: {session.pid}")
            print()
    else:
        print("No active Claude sessions detected.\n")

    warn_duplicate_sessions()
