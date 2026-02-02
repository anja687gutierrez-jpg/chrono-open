"""
HTML Export - Smart Project Health Dashboard

A comprehensive dashboard integrating ALL Project Epoch tools:
- Project classifier: Project health, session counts
- Session exploder: Tool usage patterns, file activity
- Gates: Bookmarked sessions (Time Gates)
- Session similarity: Relationship data
- Lavos-style metrics: Health scores, WIP tracking
- Tech status: Available workflows
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from collections import defaultdict

from session_graph import find_all_session_files, get_session_metadata
from summary_store import SummaryStore
from chrono_utils import classify_era, format_timestamp_relative, parse_timestamp, ERAS
from project_classifier import (
    classify_session, detect_unfinished_work,
    KNOWN_PROJECTS, load_pinned_projects
)

# Import gates data
GATES_FILE = Path.home() / ".smart-forking" / "gates.json"


def load_gates() -> Dict:
    """Load time gates (bookmarked sessions)."""
    if not GATES_FILE.exists():
        return {}
    try:
        with open(GATES_FILE, "r") as f:
            data = json.load(f)
            return data.get("gates", {})
    except:
        return {}


def get_all_sessions_with_full_data(limit: int = 200) -> List[Dict]:
    """Get metadata for all sessions with data from all tools."""
    session_files = find_all_session_files()
    summary_store = SummaryStore()
    gates = load_gates()
    gated_session_ids = {g.get("session_id", "")[:8]: name for name, g in gates.items()}

    sessions = []
    for path in session_files[:limit]:
        node = get_session_metadata(path)
        if not node:
            continue

        # Get summary
        summary = summary_store.get(node.session_id) or node.summary or ""

        # Classify the project
        classification = classify_session(
            session_id=node.session_id,
            summary=summary,
            files_touched=node.files_touched,
            original_project=node.project
        )

        era = classify_era(node.timestamp)
        dt = parse_timestamp(node.timestamp)

        # Check if bookmarked (gated)
        short_id = node.session_id[:8]
        gate_name = gated_session_ids.get(short_id)

        # Extract tools from session if available
        tools_used = getattr(node, 'tools_used', {}) or {}

        sessions.append({
            "id": node.session_id,
            "short_id": short_id,
            "project": classification.detected_project,
            "original_project": node.project,
            "confidence": classification.confidence,
            "timestamp": node.timestamp,
            "datetime": dt.isoformat() if dt else None,
            "era": era.name,
            "era_emoji": era.emoji,
            "era_code": era.code,
            "time_period": era.time_period,
            "relative_time": format_timestamp_relative(node.timestamp),
            "summary": summary[:200] if summary else "No summary available",
            "files_count": len(node.files_touched),
            "files_touched": list(node.files_touched)[:10],  # First 10 files
            "has_wip": detect_unfinished_work(summary),
            "gate_name": gate_name,
            "tools_used": tools_used
        })

    return sessions


def calculate_enhanced_project_health(sessions: List[Dict]) -> Dict:
    """Calculate comprehensive health metrics for each project."""
    now = datetime.now()
    projects = defaultdict(lambda: {
        "sessions": [],
        "total_count": 0,
        "recent_count": 0,  # Last 7 days
        "wip_count": 0,
        "gated_count": 0,  # Bookmarked sessions
        "last_activity": None,
        "first_activity": None,
        "eras": defaultdict(list),
        "health_status": "dormant",
        "health_color": "#666",
        "health_score": 0,  # 0-100
        "emoji": "📁",
        "description": "",
        # Tool usage tracking
        "tools_used": defaultdict(int),
        "files_touched": defaultdict(int),  # file extension counts
        # Activity tracking
        "activity_by_day": defaultdict(int),  # last 30 days
        "momentum": "stable",  # increasing, stable, decreasing
    })

    # Sort sessions by date (newest first) before grouping
    sorted_sessions = sorted(
        sessions,
        key=lambda s: s.get("datetime") or "1900-01-01",
        reverse=True
    )

    for session in sorted_sessions:
        proj_name = session["project"]
        proj = projects[proj_name]

        proj["sessions"].append(session)
        proj["total_count"] += 1
        proj["eras"][session["era_code"]].append(session)

        if session["has_wip"]:
            proj["wip_count"] += 1

        if session["gate_name"]:
            proj["gated_count"] += 1

        # Aggregate tool usage
        for tool, count in session.get("tools_used", {}).items():
            proj["tools_used"][tool] += count

        # Track file extensions
        for file in session.get("files_touched", []):
            ext = Path(file).suffix.lower() or "other"
            proj["files_touched"][ext] += 1

        # Parse timestamp for activity tracking
        if session["datetime"]:
            dt = datetime.fromisoformat(session["datetime"])

            if proj["last_activity"] is None or dt > proj["last_activity"]:
                proj["last_activity"] = dt
            if proj["first_activity"] is None or dt < proj["first_activity"]:
                proj["first_activity"] = dt

            # Count recent sessions
            days_ago = (now - dt).days
            if days_ago <= 7:
                proj["recent_count"] += 1

            # Activity by day (last 30 days)
            if days_ago <= 30:
                proj["activity_by_day"][days_ago] += 1

    # Calculate health scores and status for each project
    for proj_name, proj in projects.items():
        # Get emoji from known projects
        if proj_name in KNOWN_PROJECTS:
            proj["emoji"] = KNOWN_PROJECTS[proj_name].get("emoji", "📁")
            proj["description"] = KNOWN_PROJECTS[proj_name].get("description", "")
        elif proj_name == "General":
            proj["emoji"] = "📁"
            proj["description"] = "General work and miscellaneous"
        else:
            proj["emoji"] = "📂"
            proj["description"] = f"Project: {proj_name}"

        # Calculate health score (0-100)
        health_score = 50  # Base score

        if proj["last_activity"]:
            days_since = (now - proj["last_activity"]).days

            # Recency bonus/penalty
            if days_since <= 1:
                health_score += 30
                proj["health_status"] = "🟢 Active"
                proj["health_color"] = "#00ff88"
            elif days_since <= 7:
                health_score += 15
                proj["health_status"] = "🟡 Recent"
                proj["health_color"] = "#ffd700"
            elif days_since <= 30:
                health_score -= 10
                proj["health_status"] = "🟠 Cooling"
                proj["health_color"] = "#ff8800"
            else:
                health_score -= 25
                proj["health_status"] = "🔴 Dormant"
                proj["health_color"] = "#ff4444"

        # WIP penalty
        if proj["wip_count"] > 0:
            health_score -= min(proj["wip_count"] * 5, 20)
            proj["health_status"] += f" ⚠️ {proj['wip_count']} WIP"

        # Bookmarks bonus
        if proj["gated_count"] > 0:
            health_score += min(proj["gated_count"] * 3, 10)

        # Calculate momentum (comparing recent vs older activity)
        recent_activity = sum(proj["activity_by_day"].get(d, 0) for d in range(7))
        older_activity = sum(proj["activity_by_day"].get(d, 0) for d in range(7, 21))

        if recent_activity > older_activity * 1.5:
            proj["momentum"] = "🚀 increasing"
            health_score += 10
        elif recent_activity < older_activity * 0.5:
            proj["momentum"] = "📉 decreasing"
            health_score -= 10
        else:
            proj["momentum"] = "➡️ stable"

        proj["health_score"] = max(0, min(100, health_score))

        # Convert defaultdicts to regular dicts for JSON serialization
        proj["tools_used"] = dict(proj["tools_used"])
        proj["files_touched"] = dict(proj["files_touched"])
        proj["activity_by_day"] = dict(proj["activity_by_day"])

    return dict(projects)


def generate_html_dashboard(
    output_path: str = "project_dashboard.html"
) -> str:
    """Generate a comprehensive project health dashboard."""
    print("📊 Gathering session data from all tools...")
    sessions = get_all_sessions_with_full_data()

    print("🏥 Calculating enhanced project health...")
    projects = calculate_enhanced_project_health(sessions)

    print("📌 Loading time gates...")
    gates = load_gates()

    print("🎨 Generating smart dashboard...")

    # Sort projects by health score and activity
    sorted_projects = sorted(
        projects.items(),
        key=lambda x: (
            x[1]["health_score"],
            x[1]["last_activity"] or datetime.min
        ),
        reverse=True
    )

    # Load pinned projects
    pinned_data = load_pinned_projects()
    pinned_set = set(pinned_data.get("pinned", []))

    # Calculate totals
    total_sessions = len(sessions)
    total_projects = len(projects)
    active_projects = sum(1 for _, p in sorted_projects if "Active" in p["health_status"] or "Recent" in p["health_status"])
    wip_sessions = sum(p["wip_count"] for _, p in sorted_projects)
    gated_sessions = len(gates)
    avg_health = sum(p["health_score"] for _, p in sorted_projects) / max(len(sorted_projects), 1)

    # Aggregate tool usage across all projects
    all_tools_used = defaultdict(int)
    all_file_types = defaultdict(int)
    for _, proj in sorted_projects:
        for tool, count in proj["tools_used"].items():
            all_tools_used[tool] += count
        for ext, count in proj["files_touched"].items():
            all_file_types[ext] += count

    top_tools = sorted(all_tools_used.items(), key=lambda x: x[1], reverse=True)[:8]
    top_file_types = sorted(all_file_types.items(), key=lambda x: x[1], reverse=True)[:8]

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Project Epoch - Smart Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
        }}

        .dashboard {{ display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }}

        /* Sidebar */
        .sidebar {{
            background: #161b22;
            border-right: 1px solid #30363d;
            padding: 20px;
            position: sticky;
            top: 0;
            height: 100vh;
            overflow-y: auto;
        }}

        .sidebar-header {{
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid #30363d;
            margin-bottom: 20px;
        }}

        .sidebar-header h1 {{
            font-size: 1.3em;
            background: linear-gradient(90deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 5px;
        }}

        .sidebar-header p {{ color: #8b949e; font-size: 0.85em; }}

        /* Health Score Ring */
        .health-ring {{
            width: 120px;
            height: 120px;
            margin: 20px auto;
            position: relative;
        }}

        .health-ring svg {{ transform: rotate(-90deg); }}

        .health-ring-bg {{ fill: none; stroke: #21262d; stroke-width: 10; }}

        .health-ring-progress {{
            fill: none;
            stroke-width: 10;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.5s ease;
        }}

        .health-ring-text {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
        }}

        .health-ring-text .score {{ font-size: 2em; font-weight: bold; }}
        .health-ring-text .label {{ font-size: 0.75em; color: #8b949e; }}

        /* Navigation Tabs */
        .nav-tabs {{
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
        }}

        .nav-tab {{
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
            color: #8b949e;
            transition: all 0.2s;
        }}

        .nav-tab:hover {{ background: #21262d; color: #c9d1d9; }}
        .nav-tab.active {{ background: #388bfd; color: #fff; }}

        /* Project List */
        .project-nav {{ list-style: none; }}

        .project-nav-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 4px;
        }}

        .project-nav-item:hover {{ background: #21262d; }}
        .project-nav-item.active {{ background: #388bfd20; border: 1px solid #388bfd50; }}

        .project-nav-item .emoji {{ font-size: 1.1em; }}
        .project-nav-item .name {{ flex: 1; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .project-nav-item .score {{ font-size: 0.75em; padding: 2px 6px; border-radius: 4px; font-weight: bold; }}
        .project-nav-item .health-dot {{ width: 8px; height: 8px; border-radius: 50%; }}

        /* Main Content */
        .main-content {{ padding: 25px; overflow-y: auto; }}

        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}

        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
        }}

        .stat-card .value {{
            font-size: 2em;
            font-weight: bold;
            background: linear-gradient(90deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .stat-card .label {{ color: #8b949e; font-size: 0.8em; margin-top: 5px; }}
        .stat-card.warning .value {{ background: linear-gradient(90deg, #d29922, #f85149); -webkit-background-clip: text; }}
        .stat-card.success .value {{ background: linear-gradient(90deg, #3fb950, #58a6ff); -webkit-background-clip: text; }}

        /* Insights Panel */
        .insights-panel {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 25px;
        }}

        .insights-panel h3 {{ margin-bottom: 15px; color: #f0f6fc; font-size: 1em; }}

        .insight-row {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 0;
            border-bottom: 1px solid #21262d;
        }}

        .insight-row:last-child {{ border-bottom: none; }}
        .insight-row .icon {{ font-size: 1.3em; }}
        .insight-row .text {{ flex: 1; font-size: 0.9em; }}
        .insight-row .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 0.75em; font-weight: 500; }}

        /* Tool Usage Chart */
        .tool-chart {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 10px;
        }}

        .tool-bar {{
            display: flex;
            align-items: center;
            gap: 6px;
            background: #21262d;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 0.8em;
        }}

        .tool-bar .count {{ color: #58a6ff; font-weight: bold; }}

        /* Time Gates Section */
        .gates-section {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 25px;
        }}

        .gates-section h3 {{ color: #00d9ff; margin-bottom: 15px; }}

        .gate-card {{
            display: flex;
            align-items: center;
            gap: 12px;
            background: rgba(0, 217, 255, 0.1);
            border: 1px solid rgba(0, 217, 255, 0.3);
            border-radius: 8px;
            padding: 12px 15px;
            margin-bottom: 10px;
        }}

        .gate-card .gate-icon {{ font-size: 1.5em; }}
        .gate-card .gate-info {{ flex: 1; }}
        .gate-card .gate-name {{ font-weight: bold; color: #00d9ff; }}
        .gate-card .gate-session {{ font-size: 0.8em; color: #8b949e; font-family: monospace; }}

        /* Search & Sort Controls */
        .controls-bar {{
            display: flex;
            gap: 15px;
            margin-bottom: 25px;
            flex-wrap: wrap;
            align-items: center;
        }}

        .search-container {{ flex: 1; min-width: 250px; }}

        .search-input {{
            width: 100%;
            padding: 12px 18px;
            font-size: 0.95em;
            border: 1px solid #30363d;
            border-radius: 10px;
            background: #0d1117;
            color: #c9d1d9;
            outline: none;
            transition: all 0.2s;
        }}

        .search-input:focus {{ border-color: #58a6ff; box-shadow: 0 0 0 3px #58a6ff20; }}
        .search-input::placeholder {{ color: #484f58; }}

        .sort-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}

        .sort-label {{ color: #8b949e; font-size: 0.85em; }}

        .sort-btn {{
            padding: 8px 14px;
            border-radius: 8px;
            border: 1px solid #30363d;
            background: #161b22;
            color: #c9d1d9;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.2s;
        }}

        .sort-btn:hover {{ background: #21262d; border-color: #58a6ff; }}
        .sort-btn.active {{ background: #388bfd; border-color: #388bfd; color: #fff; }}

        /* Project Detail View */
        .project-section {{ display: none; margin-bottom: 40px; }}
        .project-section.active {{ display: block; }}

        .project-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #30363d;
        }}

        .project-header .emoji {{ font-size: 2.2em; }}
        .project-header .info {{ flex: 1; }}
        .project-header .info h2 {{ font-size: 1.4em; color: #f0f6fc; margin-bottom: 5px; }}
        .project-header .info p {{ color: #8b949e; font-size: 0.9em; }}

        .project-header .health-badge {{
            padding: 10px 20px;
            border-radius: 25px;
            font-weight: 600;
            font-size: 1em;
        }}

        /* Project Metrics Row */
        .project-metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }}

        .metric-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 15px;
        }}

        .metric-card h4 {{ color: #8b949e; font-size: 0.8em; margin-bottom: 10px; text-transform: uppercase; }}
        .metric-card .value {{ font-size: 1.5em; font-weight: bold; color: #f0f6fc; }}
        .metric-card .sub {{ font-size: 0.8em; color: #8b949e; margin-top: 5px; }}

        /* Activity Sparkline */
        .sparkline {{
            display: flex;
            align-items: flex-end;
            gap: 2px;
            height: 40px;
            margin-top: 10px;
        }}

        .sparkline-bar {{
            flex: 1;
            background: #58a6ff;
            border-radius: 2px;
            min-height: 2px;
        }}

        /* Era Groups */
        .era-group {{ margin-bottom: 25px; }}

        .era-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.95em;
            color: #8b949e;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #21262d;
        }}

        .era-title .era-emoji {{ font-size: 1.2em; }}
        .era-title .era-count {{ margin-left: auto; background: #21262d; padding: 2px 10px; border-radius: 10px; font-size: 0.85em; }}

        /* Session Cards */
        .sessions-list {{ display: flex; flex-direction: column; gap: 8px; }}

        .session-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px 16px;
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 12px;
            align-items: center;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .session-card:hover {{ border-color: #58a6ff; background: #1c2128; }}
        .session-card.gated {{ border-color: #00d9ff; background: rgba(0, 217, 255, 0.05); }}

        .session-card .session-id {{
            font-family: monospace;
            color: #58a6ff;
            font-size: 0.85em;
            background: #58a6ff15;
            padding: 4px 8px;
            border-radius: 5px;
        }}

        .session-card .session-summary {{ color: #c9d1d9; font-size: 0.9em; line-height: 1.4; }}

        .session-card .session-meta {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 4px;
            font-size: 0.75em;
            color: #8b949e;
        }}

        .session-card .session-date {{ color: #58a6ff; font-weight: 600; font-size: 1.1em; }}
        .session-card .session-relative {{ color: #6e7681; font-size: 0.9em; }}

        .session-card .bookmark-icon {{ color: #ffd700; margin-right: 4px; font-size: 1em; }}
        .session-card.gated {{ border-left: 3px solid #ffd700; }}

        .session-card .wip-badge {{ background: #d2992220; color: #d29922; padding: 2px 6px; border-radius: 4px; font-size: 0.7em; }}
        .session-card .gate-badge {{ background: #00d9ff20; color: #00d9ff; padding: 2px 6px; border-radius: 4px; font-size: 0.7em; }}

        /* All Projects Grid View */
        .all-projects-view {{ display: none; }}
        .all-projects-view.active {{ display: block; }}

        .project-cards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 20px;
        }}

        .project-overview-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .project-overview-card:hover {{ border-color: #58a6ff; transform: translateY(-2px); }}

        .project-overview-card .header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 15px;
        }}

        .project-overview-card .header .emoji {{ font-size: 1.8em; }}
        .project-overview-card .header .name {{ font-size: 1.15em; font-weight: 600; color: #f0f6fc; }}
        .project-overview-card .header .score {{ margin-left: auto; font-size: 1.1em; font-weight: bold; }}

        .project-overview-card .metrics {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin-bottom: 15px;
        }}

        .project-overview-card .metric {{
            text-align: center;
            padding: 8px;
            background: #0d1117;
            border-radius: 6px;
        }}

        .project-overview-card .metric .num {{ font-size: 1.1em; font-weight: bold; color: #58a6ff; }}
        .project-overview-card .metric .lbl {{ font-size: 0.65em; color: #8b949e; }}

        .project-overview-card .health {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-top: 12px;
            border-top: 1px solid #21262d;
        }}

        .project-overview-card .momentum {{ font-size: 0.85em; }}
        .project-overview-card .last-activity {{ color: #8b949e; font-size: 0.8em; }}

        /* Modal */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }}

        .modal.active {{ display: flex; }}

        .modal-content {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 16px;
            padding: 25px;
            max-width: 600px;
            width: 90%;
            max-height: 85vh;
            overflow-y: auto;
        }}

        .modal-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #30363d;
        }}

        .modal-header h2 {{ color: #58a6ff; font-family: monospace; }}

        .modal-close {{
            background: none;
            border: none;
            color: #8b949e;
            font-size: 1.5em;
            cursor: pointer;
            padding: 5px 10px;
            border-radius: 6px;
        }}

        .modal-close:hover {{ background: #21262d; color: #f0f6fc; }}

        .modal-body p {{ margin-bottom: 10px; line-height: 1.5; }}
        .modal-body strong {{ color: #8b949e; }}

        .command-box {{
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
            margin-top: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .command-box code {{ flex: 1; color: #3fb950; font-family: monospace; font-size: 0.9em; }}

        .copy-btn {{
            background: #238636;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.2s;
        }}

        .copy-btn:hover {{ background: #2ea043; }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 25px;
            color: #484f58;
            font-size: 0.8em;
            border-top: 1px solid #21262d;
            margin-top: 40px;
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .dashboard {{ grid-template-columns: 1fr; }}
            .sidebar {{ position: relative; height: auto; border-right: none; border-bottom: 1px solid #30363d; }}
            .project-nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
            .project-nav-item {{ padding: 8px 12px; }}
            .session-card {{ grid-template-columns: 1fr; gap: 8px; }}
        }}
    </style>
</head>
<body>
    <div class="dashboard">
        <!-- Sidebar -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>⏰ Project Epoch</h1>
                <p>Smart Dashboard</p>

                <!-- Overall Health Ring -->
                <div class="health-ring">
                    <svg width="120" height="120">
                        <circle class="health-ring-bg" cx="60" cy="60" r="50"></circle>
                        <circle class="health-ring-progress" cx="60" cy="60" r="50"
                                stroke="{get_health_color(avg_health)}"
                                stroke-dasharray="{avg_health * 3.14} 314"
                                stroke-dashoffset="0"></circle>
                    </svg>
                    <div class="health-ring-text">
                        <div class="score" style="color: {get_health_color(avg_health)}">{int(avg_health)}</div>
                        <div class="label">Health</div>
                    </div>
                </div>
            </div>

            <!-- Navigation Tabs -->
            <div class="nav-tabs">
                <div class="nav-tab active" onclick="showView('overview')">📊 Overview</div>
                <div class="nav-tab" onclick="showView('gates')">⏰ Gates</div>
            </div>

            <!-- Project Navigation -->
            <nav>
                <ul class="project-nav">
                    <li class="project-nav-item active" onclick="showAllProjects()" data-project="all">
                        <span class="emoji">📊</span>
                        <span class="name">All Projects</span>
                        <span class="score" style="background: #21262d">{total_projects}</span>
                    </li>
'''

    # Add project navigation items sorted by health score
    for proj_name, proj in sorted_projects:
        is_pinned = "📌" if proj_name in pinned_set else ""
        score_color = get_health_color(proj["health_score"])
        html_content += f'''
                    <li class="project-nav-item" onclick="showProject('{proj_name}')" data-project="{proj_name}">
                        <span class="emoji">{proj["emoji"]}</span>
                        <span class="name">{is_pinned}{proj_name}</span>
                        <span class="score" style="background: {score_color}20; color: {score_color}">{proj["health_score"]}</span>
                        <span class="health-dot" style="background: {proj["health_color"]}"></span>
                    </li>
'''

    html_content += f'''
                </ul>
            </nav>
        </aside>

        <!-- Main Content -->
        <main class="main-content">
            <!-- Stats Overview -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="value">{total_sessions}</div>
                    <div class="label">Total Sessions</div>
                </div>
                <div class="stat-card">
                    <div class="value">{total_projects}</div>
                    <div class="label">Projects</div>
                </div>
                <div class="stat-card success">
                    <div class="value">{active_projects}</div>
                    <div class="label">Active This Week</div>
                </div>
                <div class="stat-card warning">
                    <div class="value">{wip_sessions}</div>
                    <div class="label">WIP Sessions</div>
                </div>
                <div class="stat-card">
                    <div class="value">{gated_sessions}</div>
                    <div class="label">Time Gates</div>
                </div>
                <div class="stat-card">
                    <div class="value">{int(avg_health)}</div>
                    <div class="label">Avg Health</div>
                </div>
            </div>

            <!-- Insights Panel -->
            <div class="insights-panel">
                <h3>🔮 Insights</h3>
'''

    # Generate insights
    insights = generate_insights(sorted_projects, gates)
    for insight in insights[:5]:
        html_content += f'''
                <div class="insight-row">
                    <span class="icon">{insight["icon"]}</span>
                    <span class="text">{insight["text"]}</span>
                    <span class="badge" style="background: {insight["color"]}20; color: {insight["color"]}">{insight["badge"]}</span>
                </div>
'''

    # Add tool usage chart if we have data
    if top_tools:
        html_content += '''
                <h3 style="margin-top: 20px;">🔧 Most Used Tools</h3>
                <div class="tool-chart">
'''
        for tool, count in top_tools:
            html_content += f'''
                    <div class="tool-bar">
                        <span>{tool}</span>
                        <span class="count">{count}</span>
                    </div>
'''
        html_content += '''
                </div>
'''

    html_content += '''
            </div>

            <!-- Search & Sort Controls -->
            <div class="controls-bar">
                <div class="search-container">
                    <input type="text" class="search-input" id="search" placeholder="🔍 Search by ID (e.g. #e46b9a78), project, or keyword..." onkeyup="filterSessions()">
                </div>
                <div class="sort-controls">
                    <span class="sort-label">Sort by:</span>
                    <button class="sort-btn active" onclick="sortProjects('health')" data-sort="health">🏆 Health</button>
                    <button class="sort-btn" onclick="sortProjects('recent')" data-sort="recent">🕐 Recent</button>
                    <button class="sort-btn" onclick="sortProjects('name')" data-sort="name">🔤 Name</button>
                    <button class="sort-btn" onclick="sortProjects('sessions')" data-sort="sessions">📊 Sessions</button>
                </div>
            </div>
'''

    # Time Gates Section
    if gates:
        html_content += '''
            <div class="gates-section" id="gates-view" style="display: none;">
                <h3>⏰ Time Gates (Bookmarked Sessions)</h3>
'''
        for gate_name, gate_data in gates.items():
            session_id = gate_data.get("session_id", "")[:8]
            notes = gate_data.get("notes", "")
            html_content += f'''
                <div class="gate-card" onclick="showSession('{gate_data.get("session_id", "")}')">
                    <span class="gate-icon">🌀</span>
                    <div class="gate-info">
                        <div class="gate-name">{gate_name}</div>
                        <div class="gate-session">#{session_id} {f"• {notes}" if notes else ""}</div>
                    </div>
                </div>
'''
        html_content += '''
            </div>
'''

    # All Projects Overview
    html_content += '''
            <div class="all-projects-view active" id="all-projects">
                <h2 style="margin-bottom: 20px; color: #f0f6fc;">📊 Project Overview</h2>
                <div class="project-cards-grid">
'''

    for proj_name, proj in sorted_projects:
        last_activity_str = ""
        if proj["last_activity"]:
            days = (datetime.now() - proj["last_activity"]).days
            if days == 0:
                last_activity_str = "Today"
            elif days == 1:
                last_activity_str = "Yesterday"
            else:
                last_activity_str = f"{days}d ago"

        score_color = get_health_color(proj["health_score"])

        html_content += f'''
                    <div class="project-overview-card" onclick="showProject('{proj_name}')">
                        <div class="header">
                            <span class="emoji">{proj["emoji"]}</span>
                            <span class="name">{proj_name}</span>
                            <span class="score" style="color: {score_color}">{proj["health_score"]}</span>
                        </div>
                        <div class="metrics">
                            <div class="metric">
                                <div class="num">{proj["total_count"]}</div>
                                <div class="lbl">Sessions</div>
                            </div>
                            <div class="metric">
                                <div class="num">{proj["recent_count"]}</div>
                                <div class="lbl">This Week</div>
                            </div>
                            <div class="metric">
                                <div class="num">{proj["wip_count"]}</div>
                                <div class="lbl">WIP</div>
                            </div>
                            <div class="metric">
                                <div class="num">{proj["gated_count"]}</div>
                                <div class="lbl">Gated</div>
                            </div>
                        </div>
                        <div class="health">
                            <span style="color: {proj["health_color"]}">{proj["health_status"].split(" ⚠️")[0]}</span>
                            <span class="momentum">{proj["momentum"]}</span>
                            <span class="last-activity">{last_activity_str}</span>
                        </div>
                    </div>
'''

    html_content += '''
                </div>
            </div>
'''

    # Individual Project Sections
    era_order = ["present", "middle_ages", "antiquity", "prehistory"]
    era_names = {
        "present": ("🏠", "Present (This Week)"),
        "middle_ages": ("⚔️", "Middle Ages (1-4 Weeks)"),
        "antiquity": ("🏛️", "Antiquity (1-3 Months)"),
        "prehistory": ("🦕", "Prehistory (3+ Months)")
    }

    for proj_name, proj in sorted_projects:
        last_activity_str = ""
        if proj["last_activity"]:
            last_activity_str = format_timestamp_relative(proj["last_activity"].isoformat())

        score_color = get_health_color(proj["health_score"])

        html_content += f'''
            <div class="project-section" id="project-{proj_name.replace(' ', '-').replace('/', '-')}">
                <div class="project-header">
                    <span class="emoji">{proj["emoji"]}</span>
                    <div class="info">
                        <h2>{proj_name}</h2>
                        <p>{proj["description"]} • Last active: {last_activity_str}</p>
                    </div>
                    <span class="health-badge" style="background: {score_color}20; color: {score_color}">
                        {proj["health_score"]} Health
                    </span>
                </div>

                <!-- Project Metrics -->
                <div class="project-metrics">
                    <div class="metric-card">
                        <h4>Sessions</h4>
                        <div class="value">{proj["total_count"]}</div>
                        <div class="sub">{proj["recent_count"]} this week</div>
                    </div>
                    <div class="metric-card">
                        <h4>Status</h4>
                        <div class="value" style="font-size: 1.2em; color: {proj["health_color"]}">{proj["health_status"].split(" ⚠️")[0]}</div>
                        <div class="sub">{proj["momentum"]}</div>
                    </div>
                    <div class="metric-card">
                        <h4>WIP</h4>
                        <div class="value" style="color: {"#d29922" if proj["wip_count"] > 0 else "#3fb950"}">{proj["wip_count"]}</div>
                        <div class="sub">unfinished</div>
                    </div>
                    <div class="metric-card">
                        <h4>Bookmarked</h4>
                        <div class="value" style="color: #00d9ff">{proj["gated_count"]}</div>
                        <div class="sub">time gates</div>
                    </div>
                </div>
'''

        # Add activity sparkline
        if proj["activity_by_day"]:
            html_content += '''
                <div class="metric-card" style="margin-bottom: 25px;">
                    <h4>Activity (Last 30 Days)</h4>
                    <div class="sparkline">
'''
            max_activity = max(proj["activity_by_day"].values()) if proj["activity_by_day"] else 1
            for day in range(29, -1, -1):
                count = proj["activity_by_day"].get(day, 0)
                height = max(2, (count / max(max_activity, 1)) * 100)
                html_content += f'<div class="sparkline-bar" style="height: {height}%" title="Day -{day}: {count}"></div>'

            html_content += '''
                    </div>
                </div>
'''

        # Add sessions by era
        for era_code in era_order:
            era_sessions = proj["eras"].get(era_code, [])
            if not era_sessions:
                continue

            era_emoji, era_label = era_names.get(era_code, ("📁", era_code))

            html_content += f'''
                <div class="era-group">
                    <div class="era-title">
                        <span class="era-emoji">{era_emoji}</span>
                        <span>{era_label}</span>
                        <span class="era-count">{len(era_sessions)}</span>
                    </div>
                    <div class="sessions-list">
'''

            # Sort sessions within era by date (newest first)
            sorted_era_sessions = sorted(
                era_sessions,
                key=lambda s: s.get("datetime") or "1900-01-01",
                reverse=True
            )

            for session in sorted_era_sessions:
                wip_badge = '<span class="wip-badge">⚠️ WIP</span>' if session["has_wip"] else ""
                bookmark_icon = '<span class="bookmark-icon" title="Bookmarked">⭐</span>' if session["gate_name"] else ""
                gated_class = "gated" if session["gate_name"] else ""
                summary = session["summary"][:100] + "..." if len(session["summary"]) > 100 else session["summary"]

                # Format actual date (e.g., "Jan 26, 2026")
                actual_date = ""
                if session.get("datetime"):
                    try:
                        dt = datetime.fromisoformat(session["datetime"])
                        actual_date = dt.strftime("%b %d, %Y")
                    except:
                        actual_date = ""

                html_content += f'''
                        <div class="session-card {gated_class}" onclick="showSession('{session["id"]}')" data-search="{session['summary'].lower()} {session['project'].lower()} {session['short_id'].lower()}">
                            <span class="session-id">{bookmark_icon}#{session["short_id"]}</span>
                            <span class="session-summary">{summary}</span>
                            <div class="session-meta">
                                <span class="session-date">{actual_date}</span>
                                <span class="session-relative">({session["relative_time"]})</span>
                                {wip_badge}
                            </div>
                        </div>
'''

            html_content += '''
                    </div>
                </div>
'''

        html_content += '''
            </div>
'''

    # Modal and Scripts
    html_content += f'''
            <div class="footer">
                <p>Generated by Project Epoch • {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
                <p>Smart dashboard powered by all Project Epoch tools 🛠️</p>
            </div>
        </main>
    </div>

    <div class="modal" id="session-modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modal-title">Session Details</h2>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>

    <script>
        const sessions = {json.dumps(sessions)};

        function showView(view) {{
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');

            if (view === 'gates') {{
                document.getElementById('all-projects').classList.remove('active');
                document.querySelectorAll('.project-section').forEach(el => el.classList.remove('active'));
                document.getElementById('gates-view').style.display = 'block';
            }} else {{
                document.getElementById('gates-view').style.display = 'none';
                showAllProjects();
            }}
        }}

        function showAllProjects() {{
            document.querySelectorAll('.project-nav-item').forEach(el => el.classList.remove('active'));
            document.querySelector('[data-project="all"]').classList.add('active');
            document.querySelectorAll('.project-section').forEach(el => el.classList.remove('active'));
            document.getElementById('all-projects').classList.add('active');
            document.getElementById('gates-view').style.display = 'none';
        }}

        function showProject(projectName) {{
            document.querySelectorAll('.project-nav-item').forEach(el => el.classList.remove('active'));
            const navItem = document.querySelector(`[data-project="${{projectName}}"]`);
            if (navItem) navItem.classList.add('active');

            document.getElementById('all-projects').classList.remove('active');
            document.getElementById('gates-view').style.display = 'none';
            document.querySelectorAll('.project-section').forEach(el => el.classList.remove('active'));

            const projectId = 'project-' + projectName.replace(/ /g, '-').replace(/\\//g, '-');
            const section = document.getElementById(projectId);
            if (section) section.classList.add('active');
        }}

        function filterSessions() {{
            const query = document.getElementById('search').value.toLowerCase().replace('#', '');
            document.querySelectorAll('.session-card').forEach(card => {{
                const searchText = card.dataset.search || '';
                const sessionId = card.querySelector('.session-id')?.textContent.toLowerCase().replace('#', '') || '';
                const matches = searchText.includes(query) || sessionId.includes(query);
                card.style.display = matches ? 'grid' : 'none';
                // Highlight matching ID
                if (query.length >= 4 && sessionId.includes(query)) {{
                    card.style.borderColor = '#00d9ff';
                }} else {{
                    card.style.borderColor = '';
                }}
            }});
            document.querySelectorAll('.project-overview-card').forEach(card => {{
                const name = card.querySelector('.name').textContent.toLowerCase();
                card.style.display = name.includes(query) ? 'block' : 'none';
            }});
        }}

        // Project sorting
        const projectData = {{}};
        document.querySelectorAll('.project-overview-card').forEach(card => {{
            const name = card.querySelector('.name').textContent;
            const score = parseInt(card.querySelector('.score')?.textContent) || 0;
            const sessions = parseInt(card.querySelector('.metric .num')?.textContent) || 0;
            const lastActivity = card.querySelector('.last-activity')?.textContent || '';
            projectData[name] = {{ card, name, score, sessions, lastActivity }};
        }});

        function sortProjects(sortBy) {{
            // Update button states
            document.querySelectorAll('.sort-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelector(`[data-sort="${{sortBy}}"]`).classList.add('active');

            const grid = document.querySelector('.project-cards-grid');
            if (!grid) return;

            const cards = Array.from(grid.querySelectorAll('.project-overview-card'));

            cards.sort((a, b) => {{
                const aName = a.querySelector('.name').textContent;
                const bName = b.querySelector('.name').textContent;
                const aScore = parseInt(a.querySelector('.score')?.textContent) || 0;
                const bScore = parseInt(b.querySelector('.score')?.textContent) || 0;
                const aSessions = parseInt(a.querySelector('.metric .num')?.textContent) || 0;
                const bSessions = parseInt(b.querySelector('.metric .num')?.textContent) || 0;
                const aActivity = a.querySelector('.last-activity')?.textContent || 'zzz';
                const bActivity = b.querySelector('.last-activity')?.textContent || 'zzz';

                switch(sortBy) {{
                    case 'health':
                        return bScore - aScore;
                    case 'recent':
                        // Parse "Today", "Yesterday", "Xd ago"
                        const parseActivity = (str) => {{
                            if (str === 'Today') return 0;
                            if (str === 'Yesterday') return 1;
                            const match = str.match(/(\d+)d ago/);
                            return match ? parseInt(match[1]) : 999;
                        }};
                        return parseActivity(aActivity) - parseActivity(bActivity);
                    case 'name':
                        return aName.localeCompare(bName);
                    case 'sessions':
                        return bSessions - aSessions;
                    default:
                        return 0;
                }}
            }});

            // Re-append in sorted order
            cards.forEach(card => grid.appendChild(card));
        }}

        function showSession(sessionId) {{
            const session = sessions.find(s => s.id === sessionId);
            if (!session) return;

            document.getElementById('modal-title').textContent = '#' + session.short_id;
            document.getElementById('modal-body').innerHTML = `
                <p><strong>Project:</strong> ${{session.project}}</p>
                <p><strong>Era:</strong> ${{session.era_emoji}} ${{session.era}} (${{session.time_period}})</p>
                <p><strong>When:</strong> ${{session.relative_time}}</p>
                <p><strong>Files touched:</strong> ${{session.files_count}}</p>
                ${{session.has_wip ? '<p><strong>Status:</strong> ⚠️ Has unfinished work</p>' : ''}}
                ${{session.gate_name ? '<p><strong>Time Gate:</strong> 🌀 ' + session.gate_name + '</p>' : ''}}
                <p><strong>Summary:</strong></p>
                <p style="background: #0d1117; padding: 15px; border-radius: 8px; margin-top: 10px;">${{session.summary}}</p>
                <div class="command-box">
                    <code id="cmd">claude --continue ${{session.id}}</code>
                    <button class="copy-btn" onclick="copyCommand()">Copy</button>
                </div>
            `;
            document.getElementById('session-modal').classList.add('active');
        }}

        function closeModal() {{
            document.getElementById('session-modal').classList.remove('active');
        }}

        function copyCommand() {{
            const cmd = document.getElementById('cmd').textContent;
            navigator.clipboard.writeText(cmd);
            const btn = document.querySelector('.copy-btn');
            btn.textContent = 'Copied!';
            setTimeout(() => btn.textContent = 'Copy', 2000);
        }}

        document.getElementById('session-modal').addEventListener('click', (e) => {{
            if (e.target.id === 'session-modal') closeModal();
        }});
        document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape') closeModal(); }});
    </script>
</body>
</html>
'''

    # Write the file
    output = Path(output_path).expanduser()
    with open(output, 'w') as f:
        f.write(html_content)

    print(f"✅ Generated: {output}")
    return str(output)


def get_health_color(score: float) -> str:
    """Get color based on health score."""
    if score >= 75:
        return "#3fb950"
    elif score >= 50:
        return "#ffd700"
    elif score >= 25:
        return "#ff8800"
    else:
        return "#ff4444"


def generate_insights(sorted_projects: List, gates: Dict) -> List[Dict]:
    """Generate smart insights from the data."""
    insights = []

    # Most active project
    if sorted_projects:
        top_proj_name, top_proj = sorted_projects[0]
        insights.append({
            "icon": "🏆",
            "text": f"{top_proj['emoji']} {top_proj_name} is your healthiest project",
            "badge": f"{top_proj['health_score']} health",
            "color": "#3fb950"
        })

    # WIP warning
    total_wip = sum(p["wip_count"] for _, p in sorted_projects)
    if total_wip > 0:
        insights.append({
            "icon": "⚠️",
            "text": f"You have {total_wip} sessions with unfinished work",
            "badge": "WIP",
            "color": "#d29922"
        })

    # Dormant projects
    dormant = [name for name, p in sorted_projects if "Dormant" in p["health_status"]]
    if dormant:
        insights.append({
            "icon": "😴",
            "text": f"{len(dormant)} projects haven't been touched in 30+ days",
            "badge": "Dormant",
            "color": "#ff4444"
        })

    # Time gates
    if gates:
        insights.append({
            "icon": "🌀",
            "text": f"You have {len(gates)} bookmarked sessions (Time Gates)",
            "badge": "Quick access",
            "color": "#00d9ff"
        })

    # Momentum insight
    increasing = [name for name, p in sorted_projects if "increasing" in p.get("momentum", "")]
    if increasing:
        insights.append({
            "icon": "🚀",
            "text": f"{len(increasing)} projects have increasing momentum",
            "badge": "Growing",
            "color": "#58a6ff"
        })

    return insights


# Backwards compatibility
def generate_html_explorer(output_path: str = "session_explorer.html", include_relationships: bool = True) -> str:
    """Deprecated: Use generate_html_dashboard instead."""
    return generate_html_dashboard(output_path)


if __name__ == "__main__":
    import sys
    output = "~/Desktop/project_dashboard.html"
    if len(sys.argv) > 1:
        output = sys.argv[1]
    path = generate_html_dashboard(output)
    print(f"\n🌐 Open in browser: file://{path}")
    print(f"   Or run: open {path}")
