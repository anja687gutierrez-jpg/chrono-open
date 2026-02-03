"""
Chrono Trigger Time Utilities for Smart Forking
Era classification, date parsing, and time-travel helpers.

Eras based on Chrono Trigger time periods:
  - PRESENT (1000 AD)    -> This week (where we "live" - current work)
  - MIDDLE_AGES (600 AD) -> 1-4 weeks ago (recent past)
  - ANTIQUITY (12000 BC) -> 1-3 months ago (older sessions)
  - PREHISTORY (65M BC)  -> 3+ months ago (ancient history)

Special eras (Phase 2 - Time Gates):
  - FUTURE (2300 AD)     -> Planned/anticipated work (bookmarked for later)
  - END_OF_TIME          -> Pinned important sessions (the hub between eras)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple, List
import re


@dataclass
class Era:
    """A Chrono Trigger-inspired time era."""
    name: str
    code: str
    emoji: str
    game_year: str
    time_period: str  # Human-readable time period (e.g., "This Week")
    description: str
    color: str  # ANSI color code
    min_days_ago: int  # Inclusive
    max_days_ago: Optional[int]  # Exclusive, None = infinity


# Era definitions (ordered from newest to oldest)
# Note: "Future" is reserved for Phase 2 (planned/bookmarked work)
ERAS = [
    Era(
        name="Present",
        code="present",
        emoji="🏠",
        game_year="1000 AD",
        time_period="This Week",
        description="Current active work - where you 'live' in the timeline",
        color="\033[92m",  # Green
        min_days_ago=0,
        max_days_ago=7
    ),
    Era(
        name="Middle Ages",
        code="middle_ages",
        emoji="⚔️",
        game_year="600 AD",
        time_period="1-4 Weeks Ago",
        description="Recent sessions from the past few weeks",
        color="\033[94m",  # Blue (visible on light backgrounds)
        min_days_ago=7,
        max_days_ago=30
    ),
    Era(
        name="Antiquity",
        code="antiquity",
        emoji="🏛️",
        game_year="12000 BC",
        time_period="1-3 Months Ago",
        description="Older sessions from past months",
        color="\033[95m",  # Magenta
        min_days_ago=30,
        max_days_ago=90
    ),
    Era(
        name="Prehistory",
        code="prehistory",
        emoji="🦕",
        game_year="65M BC",
        time_period="3+ Months Ago",
        description="Ancient history - your earliest sessions",
        color="\033[91m",  # Red
        min_days_ago=90,
        max_days_ago=None
    ),
]

# Special eras for Phase 2+ features
# Future (2300 AD) - In Chrono Trigger, this is the ruined world destroyed by Lavos.
# The heroes travel here, see the catastrophe, and go back to PREVENT it.
# In Project Epoch, this represents predicted issues/problems to prevent!
FUTURE = Era(
    name="Future",
    code="future",
    emoji="🚀",
    game_year="2300 AD",
    time_period="Predicted Issues",
    description="Problems to prevent - tech debt, security issues, deprecations (Lavos Detection)",
    color="\033[91m",  # Red (warning color - danger ahead!)
    min_days_ago=0,
    max_days_ago=None
)

# End of Time - In Chrono Trigger, this is the hub between all eras where
# the party can rest, save, and access any time period.
# In Project Epoch, this is for pinned/bookmarked important sessions.
END_OF_TIME = Era(
    name="End of Time",
    code="end_of_time",
    emoji="⏳",
    game_year="???",
    time_period="Pinned",
    description="Important bookmarked sessions - your hub between all eras",
    color="\033[90m",  # Dark gray (neutral, visible on both light/dark)
    min_days_ago=0,
    max_days_ago=None
)

# ============================================================
# ANSI Color Palette (works on both light and dark backgrounds)
# ============================================================
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Primary colors - chosen for visibility on white/light backgrounds
GREEN = "\033[92m"       # Success, Present era
BLUE = "\033[94m"        # Info, Middle Ages era (replaces yellow)
MAGENTA = "\033[95m"     # Accent, Antiquity era
RED = "\033[91m"         # Error/warning, Prehistory era
CYAN = "\033[96m"        # Highlight, interactive elements
GRAY = "\033[90m"        # Neutral, End of Time (dark gray, visible on both)

# Semantic colors
SUCCESS = GREEN
INFO = BLUE
WARNING = "\033[38;5;208m"  # Orange (visible on both light/dark)
ERROR = RED
ACCENT = MAGENTA
HIGHLIGHT = CYAN


def get_era_by_code(code: str) -> Optional[Era]:
    """Get an era by its code name."""
    code_lower = code.lower().replace("-", "_").replace(" ", "_")
    for era in ERAS:
        if era.code == code_lower:
            return era
    if code_lower == "end_of_time":
        return END_OF_TIME
    return None


def parse_timestamp(timestamp: str) -> Optional[datetime]:
    """
    Parse a timestamp string in various formats.

    Handles:
        - ISO format: "2025-01-18T14:32:00"
        - ISO with Z: "2026-02-01T23:06:19.101Z"
        - Git format: "2026-01-26 10:03:43 -0800"
        - Date only: "2026-01-26"

    Returns:
        datetime object (timezone-naive in LOCAL time) or None if unparseable
    """
    try:
        # Try dateutil first (handles most formats including git dates)
        try:
            from dateutil import parser as dateutil_parser
            from dateutil import tz as dateutil_tz
            session_date = dateutil_parser.parse(timestamp)

            # Convert to local time if timezone-aware
            if session_date.tzinfo:
                local_tz = dateutil_tz.tzlocal()
                session_date = session_date.astimezone(local_tz).replace(tzinfo=None)

        except ImportError:
            # Fallback to manual parsing if dateutil not available
            if "T" in timestamp:
                session_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                # Handle git format: "2026-01-26 10:03:43 -0800"
                clean = timestamp.strip()
                if len(clean) > 19 and clean[10] == ' ':
                    date_part = clean[:19].replace(' ', 'T')
                    tz_part = clean[19:].strip().replace(' ', '')
                    if len(tz_part) == 5:
                        tz_part = tz_part[:3] + ':' + tz_part[3:]
                    session_date = datetime.fromisoformat(date_part + tz_part)
                else:
                    session_date = datetime.fromisoformat(clean.replace(' ', 'T'))

            # Make timezone-naive for comparison
            if session_date.tzinfo:
                session_date = session_date.replace(tzinfo=None)

        return session_date

    except (ValueError, TypeError):
        return None


def classify_era(timestamp: Optional[str]) -> Era:
    """
    Classify a session into an era based on its timestamp.

    Args:
        timestamp: Timestamp string in various formats:
            - ISO format: "2025-01-18T14:32:00"
            - Git format: "2026-01-26 10:03:43 -0800"
            - Date only: "2026-01-26"

    Returns:
        The Era the session belongs to
    """
    if not timestamp:
        return ERAS[-1]  # Prehistory for unknown dates

    session_date = parse_timestamp(timestamp)
    if not session_date:
        return ERAS[-1]  # Prehistory for unparseable dates

    now = datetime.now()
    days_ago = (now - session_date).days

    for era in ERAS:
        if days_ago >= era.min_days_ago:
            if era.max_days_ago is None or days_ago < era.max_days_ago:
                return era

    return ERAS[-1]  # Prehistory as fallback


def parse_flexible_date(date_str: str) -> Optional[datetime]:
    """
    Parse a flexible date string into a datetime object.

    Supports:
        - ISO dates: "2024-01-15", "2024-01"
        - Relative: "3 months ago", "last week", "yesterday"
        - Named: "today", "now"

    Args:
        date_str: The date string to parse

    Returns:
        datetime object or None if unparseable
    """
    date_str = date_str.strip().lower()
    now = datetime.now()

    # Handle special keywords
    if date_str in ("now", "today"):
        return now
    if date_str == "yesterday":
        return now - timedelta(days=1)

    # Handle relative dates: "X days/weeks/months ago"
    relative_pattern = r"(\d+)\s*(day|week|month|year)s?\s*ago"
    match = re.match(relative_pattern, date_str)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)

        if unit == "day":
            return now - timedelta(days=amount)
        elif unit == "week":
            return now - timedelta(weeks=amount)
        elif unit == "month":
            return now - timedelta(days=amount * 30)  # Approximate
        elif unit == "year":
            return now - timedelta(days=amount * 365)  # Approximate

    # Handle "last X"
    last_pattern = r"last\s*(week|month|year)"
    match = re.match(last_pattern, date_str)
    if match:
        unit = match.group(1)
        if unit == "week":
            return now - timedelta(weeks=1)
        elif unit == "month":
            return now - timedelta(days=30)
        elif unit == "year":
            return now - timedelta(days=365)

    # Try ISO format parsing
    try:
        # Full ISO date
        if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
            return datetime.fromisoformat(date_str[:10])

        # Year-month only (e.g., "2024-01")
        if re.match(r"\d{4}-\d{2}$", date_str):
            return datetime.strptime(date_str, "%Y-%m")

        # Year only (e.g., "2024")
        if re.match(r"\d{4}$", date_str):
            return datetime.strptime(date_str, "%Y")

    except ValueError:
        pass

    # Try dateutil if available (more flexible parsing)
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(date_str)
    except (ImportError, ValueError):
        pass

    return None


def is_within_date_range(
    timestamp: Optional[str],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None
) -> bool:
    """
    Check if a timestamp falls within a date range.

    Args:
        timestamp: ISO format timestamp string
        since: Start of range (inclusive), None = no lower bound
        until: End of range (inclusive), None = no upper bound

    Returns:
        True if timestamp is within range
    """
    if not timestamp:
        return since is None  # Include unknown dates only if no since filter

    try:
        if "T" in timestamp:
            session_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            session_date = datetime.fromisoformat(timestamp)

        # Make timezone-naive for comparison
        if session_date.tzinfo:
            session_date = session_date.replace(tzinfo=None)

        if since and session_date < since:
            return False
        if until and session_date > until:
            return False

        return True

    except (ValueError, TypeError):
        return since is None


def is_within_era(timestamp: Optional[str], era: Era) -> bool:
    """
    Check if a timestamp falls within a specific era.

    Args:
        timestamp: ISO format timestamp string
        era: The Era to check against

    Returns:
        True if timestamp is within the era
    """
    classified = classify_era(timestamp)
    return classified.code == era.code


def get_era_date_range(era: Era) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Get the date range for an era.

    Args:
        era: The Era to get range for

    Returns:
        Tuple of (since, until) datetimes
    """
    now = datetime.now()

    # Calculate 'until' (more recent boundary)
    if era.min_days_ago == 0:
        until = now
    else:
        until = now - timedelta(days=era.min_days_ago)

    # Calculate 'since' (older boundary)
    if era.max_days_ago is None:
        since = None  # No lower bound
    else:
        since = now - timedelta(days=era.max_days_ago)

    return (since, until)


def format_era_header(era: Era, count: int = 0, show_game_year: bool = False) -> str:
    """Format an era as a styled header with time period (game year optional)."""
    count_str = f" ({count} sessions)" if count > 0 else ""
    if show_game_year:
        return f"{era.color}{BOLD}{era.emoji} {era.name.upper()} ({era.game_year}) - {era.time_period}{RESET}{count_str}"
    return f"{era.color}{BOLD}{era.emoji} {era.name.upper()} - {era.time_period}{RESET}{count_str}"


def format_era_badge(era: Era) -> str:
    """Format an era as a small badge with time period."""
    return f"{era.color}{era.emoji} {era.name} ({era.time_period}){RESET}"


def format_era_compact(era: Era) -> str:
    """Format an era compactly for inline display."""
    return f"{era.emoji} {era.time_period}"


def format_timestamp_relative(timestamp: Optional[str]) -> str:
    """Format a timestamp as relative time (e.g., '3 days ago')."""
    if not timestamp:
        return "unknown"

    session_date = parse_timestamp(timestamp)
    if not session_date:
        return "unknown"

    now = datetime.now()
    delta = now - session_date

    if delta.days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            minutes = delta.seconds // 60
            return f"{minutes}m ago" if minutes > 0 else "just now"
        return f"{hours}h ago"
    elif delta.days == 1:
        return "yesterday"
    elif delta.days < 7:
        return f"{delta.days}d ago"
    elif delta.days < 30:
        weeks = delta.days // 7
        return f"{weeks}w ago"
    elif delta.days < 365:
        months = delta.days // 30
        return f"{months}mo ago"
    else:
        years = delta.days // 365
        return f"{years}y ago"


def get_era_summary() -> List[dict]:
    """Get a summary of all eras with their date ranges."""
    summaries = []

    for era in ERAS:
        since, until = get_era_date_range(era)
        summaries.append({
            "era": era,
            "since": since,
            "until": until,
            "since_str": since.strftime("%Y-%m-%d") if since else "beginning",
            "until_str": until.strftime("%Y-%m-%d") if until else "now"
        })

    return summaries


# ============================================================
# CLI for testing
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print(f"{BOLD}Chrono Trigger Time Utilities - Test{RESET}")
    print("=" * 70)

    print(f"\n{BOLD}Available Eras (for session classification):{RESET}\n")

    for era in ERAS:
        since, until = get_era_date_range(era)
        since_str = since.strftime("%Y-%m-%d") if since else "ancient"
        until_str = until.strftime("%Y-%m-%d") if until else "now"

        print(f"  {era.color}{era.emoji} {era.name:15}{RESET} │ {era.game_year:10} │ {era.time_period:15} │ {since_str} to {until_str}")
        print(f"     {DIM}{era.description}{RESET}")
        print()

    print(f"  {DIM}─── Special Eras (Phase 2: Time Gates) ───{RESET}\n")
    print(f"  {FUTURE.color}{FUTURE.emoji} {FUTURE.name:15}{RESET} │ {FUTURE.game_year:10} │ {FUTURE.time_period:15} │ Bookmarked planned work")
    print(f"  {END_OF_TIME.color}{END_OF_TIME.emoji} {END_OF_TIME.name:15}{RESET} │ {END_OF_TIME.game_year:10} │ {END_OF_TIME.time_period:15} │ Pinned important sessions")

    print(f"\n{BOLD}Date Parsing Tests:{RESET}\n")

    test_dates = [
        "2024-06-15",
        "2025-01",
        "3 months ago",
        "last week",
        "yesterday",
        "today",
        "6 weeks ago",
        "1 year ago"
    ]

    for date_str in test_dates:
        parsed = parse_flexible_date(date_str)
        if parsed:
            print(f"  '{date_str}' -> {parsed.strftime('%Y-%m-%d')}")
        else:
            print(f"  '{date_str}' -> [could not parse]")

    print(f"\n{BOLD}Era Classification Tests:{RESET}\n")

    test_timestamps = [
        datetime.now().isoformat(),  # Today
        (datetime.now() - timedelta(days=3)).isoformat(),  # 3 days ago
        (datetime.now() - timedelta(days=15)).isoformat(),  # 15 days ago
        (datetime.now() - timedelta(days=60)).isoformat(),  # 2 months ago
        (datetime.now() - timedelta(days=120)).isoformat(),  # 4 months ago
    ]

    for ts in test_timestamps:
        era = classify_era(ts)
        rel = format_timestamp_relative(ts)
        print(f"  {rel:12} -> {era.emoji} {era.name:15} ({era.time_period})")

    print(f"\n{BOLD}✅ Chrono utilities working!{RESET}\n")
