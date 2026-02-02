"""
Project Classifier - Smart project detection from session content

Fixes the "70 sessions filed under -Users-anjacarrillo" problem by
analyzing session content to detect the REAL project being worked on.

Also handles:
- Pinned/earmarked projects
- Unfinished work detection
- Project importance scoring
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from chrono_utils import parse_timestamp, format_timestamp_relative
from summary_store import SummaryStore


# ============================================================
# Project Definitions
# ============================================================

# Known projects with detection keywords and file patterns
KNOWN_PROJECTS = {
    "MagnusView": {
        "keywords": ["magnus", "magnusview", "milestone", "campaign", "stap", "availability.js"],
        "file_patterns": ["MagnusView"],
        "emoji": "📊",
        "description": "Dashboard application for operations management"
    },
    "Ops-Portal": {
        "keywords": ["ops portal", "ops hub", "ops-portal", "ops_portal", "operations portal", "ops-hub-portal"],
        "file_patterns": ["Ops Hub Portal", "Ops-Hub-Portal", "ops-portal"],
        "emoji": "🏢",
        "description": "Operations management portal (sandbox)"
    },
    "Smart-Forking": {
        "keywords": ["smart-forking", "chrono", "fork", "embedding", "vector", "session", "epoch", "lavos", "techs.py"],
        "file_patterns": ["smart-forking", "chrono", "fork_detect"],
        "emoji": "🔀",
        "description": "Session search and time-travel toolkit"
    },
    "Tour-Planner": {
        "keywords": ["pathfinding", "tour", "route", "trip", "iconic", "pathways", "ralph", "abenteuer"],
        "file_patterns": ["App-V.01", "iconic-pathways", "abenteuer"],
        "emoji": "🗺️",
        "description": "Tour route planning application"
    },
    "Firebase-Work": {
        "keywords": ["firebase", "firestore", "auth", "security rules", "deploy"],
        "file_patterns": ["firebase", ".rules"],
        "emoji": "🔥",
        "description": "Firebase configuration and deployment"
    },
    "System-Maintenance": {
        "keywords": ["icloud", "mail app", "backup", "zip", "organize", "cleanup", "archive", "sync", "shortcuts"],
        "file_patterns": ["Library", "CloudStorage", "iCloud"],
        "emoji": "🔧",
        "description": "System maintenance and file organization"
    },
    "Google-Drive": {
        "keywords": ["google drive", "gdrive", "engel687", "anja687", "drive sync", "cloud storage"],
        "file_patterns": ["GoogleDrive", "Google Drive"],
        "emoji": "☁️",
        "description": "Google Drive file management"
    },
}


@dataclass
class ProjectInfo:
    """Information about a detected project."""
    name: str
    emoji: str
    description: str
    session_count: int = 0
    recent_session_count: int = 0  # Last 2 weeks
    last_session_id: Optional[str] = None
    last_session_summary: Optional[str] = None
    last_activity: Optional[datetime] = None
    is_pinned: bool = False
    has_unfinished_work: bool = False
    importance_score: float = 0.0


@dataclass
class SessionProject:
    """Project classification for a single session."""
    session_id: str
    detected_project: str
    confidence: float  # 0.0 to 1.0
    original_project: str  # What it was filed under
    reasons: List[str] = field(default_factory=list)


# ============================================================
# Pinned Projects Storage
# ============================================================

PINS_FILE = Path.home() / ".smart-forking" / "pinned_projects.json"


def load_pinned_projects() -> Dict:
    """Load pinned projects from storage."""
    if PINS_FILE.exists():
        try:
            with open(PINS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"pinned": [], "earmarked_sessions": {}}


def save_pinned_projects(data: Dict):
    """Save pinned projects to storage."""
    PINS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PINS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def pin_project(project_name: str):
    """Pin a project as favorite."""
    data = load_pinned_projects()
    if project_name not in data["pinned"]:
        data["pinned"].append(project_name)
        save_pinned_projects(data)


def unpin_project(project_name: str):
    """Unpin a project."""
    data = load_pinned_projects()
    if project_name in data["pinned"]:
        data["pinned"].remove(project_name)
        save_pinned_projects(data)


def earmark_session(session_id: str, project_name: str, note: str = ""):
    """Earmark a session for a specific project."""
    data = load_pinned_projects()
    data["earmarked_sessions"][session_id] = {
        "project": project_name,
        "note": note,
        "earmarked_at": datetime.now().isoformat()
    }
    save_pinned_projects(data)


def get_earmarked_sessions() -> Dict[str, Dict]:
    """Get all earmarked sessions."""
    data = load_pinned_projects()
    return data.get("earmarked_sessions", {})


# ============================================================
# Project Detection
# ============================================================

def classify_session(
    session_id: str,
    summary: str,
    files_touched: Set[str],
    original_project: str
) -> SessionProject:
    """
    Classify a session into a project based on its content.

    Args:
        session_id: The session ID
        summary: AI-generated summary of the session
        files_touched: Set of file paths touched
        original_project: Original project classification

    Returns:
        SessionProject with detected project and confidence
    """
    # Check if earmarked
    earmarked = get_earmarked_sessions()
    if session_id in earmarked:
        return SessionProject(
            session_id=session_id,
            detected_project=earmarked[session_id]["project"],
            confidence=1.0,
            original_project=original_project,
            reasons=["Manually earmarked"]
        )

    # If original project is meaningful, use it
    if original_project and not original_project.startswith("-Users") and original_project != "unknown":
        # Try to map to known project
        for proj_name, proj_info in KNOWN_PROJECTS.items():
            for pattern in proj_info["file_patterns"]:
                if pattern.lower() in original_project.lower():
                    return SessionProject(
                        session_id=session_id,
                        detected_project=proj_name,
                        confidence=0.95,
                        original_project=original_project,
                        reasons=[f"File path matches '{pattern}'"]
                    )

        # Use original if it's specific enough
        return SessionProject(
            session_id=session_id,
            detected_project=original_project,
            confidence=0.8,
            original_project=original_project,
            reasons=["Original project path is specific"]
        )

    # Analyze content to detect project
    summary_lower = (summary or "").lower()
    files_str = " ".join(files_touched).lower()
    combined = summary_lower + " " + files_str

    best_match = None
    best_score = 0
    best_reasons = []

    for proj_name, proj_info in KNOWN_PROJECTS.items():
        score = 0
        reasons = []

        # Check keywords in summary/content
        for kw in proj_info["keywords"]:
            if kw.lower() in combined:
                score += 2
                reasons.append(f"Keyword '{kw}' found")

        # Check file patterns
        for pattern in proj_info["file_patterns"]:
            if pattern.lower() in files_str:
                score += 3
                reasons.append(f"File pattern '{pattern}' matched")

        if score > best_score:
            best_score = score
            best_match = proj_name
            best_reasons = reasons

    if best_match and best_score >= 2:
        confidence = min(best_score / 10, 0.9)
        return SessionProject(
            session_id=session_id,
            detected_project=best_match,
            confidence=confidence,
            original_project=original_project,
            reasons=best_reasons
        )

    # Fallback to "General" for truly unclassified
    return SessionProject(
        session_id=session_id,
        detected_project="General",
        confidence=0.3,
        original_project=original_project,
        reasons=["No specific project detected"]
    )


def detect_unfinished_work(summary: str) -> bool:
    """Detect if a session has unfinished work based on summary."""
    if not summary:
        return False

    summary_lower = summary.lower()
    unfinished_indicators = [
        "todo", "to-do", "to do",
        "wip", "work in progress",
        "incomplete", "unfinished",
        "need to", "needs to",
        "still need", "remaining",
        "interrupted", "paused",
        "continue", "continuing"
    ]

    return any(ind in summary_lower for ind in unfinished_indicators)


# ============================================================
# Project Analysis
# ============================================================

def analyze_all_projects() -> Dict[str, ProjectInfo]:
    """
    Analyze all sessions and build project information.

    Returns:
        Dict mapping project name to ProjectInfo
    """
    from session_graph import find_all_session_files, get_session_metadata

    summary_store = SummaryStore()
    session_files = find_all_session_files()
    pinned_data = load_pinned_projects()
    pinned_projects = set(pinned_data.get("pinned", []))

    now = datetime.now()
    two_weeks_ago = now - timedelta(days=14)

    # Initialize known projects
    projects = {}
    for proj_name, proj_info in KNOWN_PROJECTS.items():
        projects[proj_name] = ProjectInfo(
            name=proj_name,
            emoji=proj_info["emoji"],
            description=proj_info["description"],
            is_pinned=proj_name in pinned_projects
        )

    # Add "General" for unclassified
    projects["General"] = ProjectInfo(
        name="General",
        emoji="📁",
        description="General work and miscellaneous sessions"
    )

    # Classify all sessions
    for path in session_files:
        node = get_session_metadata(path)
        if not node:
            continue

        summary = summary_store.get(node.session_id)

        # Classify the session
        classification = classify_session(
            session_id=node.session_id,
            summary=summary or "",
            files_touched=node.files_touched,
            original_project=node.project
        )

        proj_name = classification.detected_project

        # Create project if new
        if proj_name not in projects:
            projects[proj_name] = ProjectInfo(
                name=proj_name,
                emoji="📂",
                description=f"Project: {proj_name}",
                is_pinned=proj_name in pinned_projects
            )

        proj = projects[proj_name]
        proj.session_count += 1

        # Check if recent
        if node.timestamp:
            dt = parse_timestamp(node.timestamp)
            if dt:
                if dt > two_weeks_ago:
                    proj.recent_session_count += 1

                # Track most recent
                if proj.last_activity is None or dt > proj.last_activity:
                    proj.last_activity = dt
                    proj.last_session_id = node.session_id
                    proj.last_session_summary = summary

        # Check for unfinished work
        if detect_unfinished_work(summary or ""):
            proj.has_unfinished_work = True

    # Calculate importance scores
    for proj in projects.values():
        # Score based on: pinned (high), recent activity, total sessions
        score = 0
        if proj.is_pinned:
            score += 100
        if proj.has_unfinished_work:
            score += 50
        score += proj.recent_session_count * 10
        score += proj.session_count

        # Recency bonus
        if proj.last_activity:
            days_ago = (now - proj.last_activity).days
            if days_ago < 1:
                score += 30
            elif days_ago < 7:
                score += 15

        proj.importance_score = score

    return projects


def get_top_projects(limit: int = 5) -> List[ProjectInfo]:
    """Get the most important projects, sorted by importance score."""
    projects = analyze_all_projects()

    # Filter out empty projects and General if there are better options
    active_projects = [p for p in projects.values() if p.session_count > 0]

    # Sort by importance score
    active_projects.sort(key=lambda p: p.importance_score, reverse=True)

    return active_projects[:limit]


def format_project_summary() -> str:
    """Format a summary of active projects for the welcome screen."""
    projects = get_top_projects(5)

    if not projects:
        return "  No projects found yet. Start working and they'll appear here!\n"

    lines = []

    for i, proj in enumerate(projects, 1):
        # Status indicators
        indicators = []
        if proj.is_pinned:
            indicators.append("📌")
        if proj.has_unfinished_work:
            indicators.append("⚠️")

        indicator_str = " ".join(indicators)
        if indicator_str:
            indicator_str = f" {indicator_str}"

        # Time info
        if proj.last_activity:
            time_str = format_timestamp_relative(proj.last_activity.isoformat())
        else:
            time_str = "unknown"

        # Summary preview
        summary_preview = ""
        if proj.last_session_summary:
            summary_preview = proj.last_session_summary[:40] + "..."

        lines.append(f"  {i}. {proj.emoji} {proj.name}{indicator_str}")
        lines.append(f"     {proj.session_count} sessions │ last: {time_str}")
        if summary_preview:
            lines.append(f"     \033[2m\"{summary_preview}\"\033[0m")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "pin" and len(sys.argv) > 2:
            pin_project(sys.argv[2])
            print(f"✅ Pinned project: {sys.argv[2]}")

        elif cmd == "unpin" and len(sys.argv) > 2:
            unpin_project(sys.argv[2])
            print(f"✅ Unpinned project: {sys.argv[2]}")

        elif cmd == "earmark" and len(sys.argv) > 3:
            session_id = sys.argv[2]
            project = sys.argv[3]
            note = sys.argv[4] if len(sys.argv) > 4 else ""
            earmark_session(session_id, project, note)
            print(f"✅ Earmarked session {session_id[:8]} → {project}")

        elif cmd == "analyze":
            print("\n📊 PROJECT ANALYSIS")
            print("=" * 60)
            print(format_project_summary())

        else:
            print("Usage:")
            print("  python project_classifier.py analyze")
            print("  python project_classifier.py pin <project>")
            print("  python project_classifier.py unpin <project>")
            print("  python project_classifier.py earmark <session_id> <project> [note]")
    else:
        print("\n📊 PROJECT ANALYSIS")
        print("=" * 60)
        print(format_project_summary())
