"""
HTML Export - Project Health Dashboard

A modern dashboard view of all your projects with:
- Health status indicators
- Projects as primary navigation
- Eras within each project
- Visual activity tracking
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

from session_graph import find_all_session_files, get_session_metadata
from summary_store import SummaryStore
from chrono_utils import classify_era, format_timestamp_relative, parse_timestamp, ERAS
from project_classifier import (
    classify_session, detect_unfinished_work,
    KNOWN_PROJECTS, load_pinned_projects
)


def get_all_sessions_with_projects(limit: int = 200) -> List[Dict]:
    """Get metadata for all sessions with proper project classification."""
    session_files = find_all_session_files()
    summary_store = SummaryStore()

    sessions = []
    for path in session_files[:limit]:
        node = get_session_metadata(path)
        if not node:
            continue

        # Get summary
        summary = summary_store.get(node.session_id) or node.summary or ""

        # Classify the project properly
        classification = classify_session(
            session_id=node.session_id,
            summary=summary,
            files_touched=node.files_touched,
            original_project=node.project
        )

        era = classify_era(node.timestamp)
        dt = parse_timestamp(node.timestamp)

        sessions.append({
            "id": node.session_id,
            "short_id": node.session_id[:8],
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
            "has_wip": detect_unfinished_work(summary)
        })

    return sessions


def calculate_project_health(sessions: List[Dict]) -> Dict:
    """Calculate health metrics for each project."""
    now = datetime.now()
    projects = defaultdict(lambda: {
        "sessions": [],
        "total_count": 0,
        "recent_count": 0,  # Last 7 days
        "wip_count": 0,
        "last_activity": None,
        "first_activity": None,
        "eras": defaultdict(list),
        "health_status": "dormant",
        "health_color": "#666",
        "emoji": "📁",
        "description": ""
    })

    for session in sessions:
        proj_name = session["project"]
        proj = projects[proj_name]

        proj["sessions"].append(session)
        proj["total_count"] += 1
        proj["eras"][session["era_code"]].append(session)

        if session["has_wip"]:
            proj["wip_count"] += 1

        # Parse timestamp for activity tracking
        if session["datetime"]:
            dt = datetime.fromisoformat(session["datetime"])

            if proj["last_activity"] is None or dt > proj["last_activity"]:
                proj["last_activity"] = dt
            if proj["first_activity"] is None or dt < proj["first_activity"]:
                proj["first_activity"] = dt

            # Count recent sessions
            if (now - dt).days <= 7:
                proj["recent_count"] += 1

    # Calculate health status for each project
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

        # Determine health status
        if proj["last_activity"]:
            days_since = (now - proj["last_activity"]).days

            if days_since <= 1:
                proj["health_status"] = "🟢 Active"
                proj["health_color"] = "#00ff88"
            elif days_since <= 7:
                proj["health_status"] = "🟡 Recent"
                proj["health_color"] = "#ffd700"
            elif days_since <= 30:
                proj["health_status"] = "🟠 Cooling"
                proj["health_color"] = "#ff8800"
            else:
                proj["health_status"] = "🔴 Dormant"
                proj["health_color"] = "#ff4444"

        # Add WIP warning
        if proj["wip_count"] > 0:
            proj["health_status"] += f" ⚠️ {proj['wip_count']} WIP"

    return dict(projects)


def generate_html_dashboard(
    output_path: str = "project_dashboard.html"
) -> str:
    """
    Generate a project-centric health dashboard.

    Args:
        output_path: Where to save the HTML file

    Returns:
        Path to the generated file
    """
    print("📊 Gathering session data...")
    sessions = get_all_sessions_with_projects()

    print("🏥 Calculating project health...")
    projects = calculate_project_health(sessions)

    # Sort projects by importance (recent activity + session count)
    sorted_projects = sorted(
        projects.items(),
        key=lambda x: (
            x[1]["last_activity"] or datetime.min,
            x[1]["total_count"]
        ),
        reverse=True
    )

    # Load pinned projects
    pinned_data = load_pinned_projects()
    pinned_set = set(pinned_data.get("pinned", []))

    print("🎨 Generating dashboard...")

    # Calculate totals
    total_sessions = len(sessions)
    total_projects = len(projects)
    active_projects = sum(1 for _, p in sorted_projects if "Active" in p["health_status"] or "Recent" in p["health_status"])
    wip_sessions = sum(p["wip_count"] for _, p in sorted_projects)

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Project Health Dashboard - Project Epoch</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            min-height: 100vh;
        }}

        /* Layout */
        .dashboard {{
            display: grid;
            grid-template-columns: 280px 1fr;
            min-height: 100vh;
        }}

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
            font-size: 1.4em;
            background: linear-gradient(90deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 5px;
        }}

        .sidebar-header p {{
            color: #8b949e;
            font-size: 0.85em;
        }}

        /* Project List in Sidebar */
        .project-nav {{
            list-style: none;
        }}

        .project-nav-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 15px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-bottom: 4px;
        }}

        .project-nav-item:hover {{
            background: #21262d;
        }}

        .project-nav-item.active {{
            background: #388bfd20;
            border: 1px solid #388bfd50;
        }}

        .project-nav-item .emoji {{
            font-size: 1.2em;
        }}

        .project-nav-item .name {{
            flex: 1;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .project-nav-item .count {{
            background: #30363d;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.8em;
            color: #8b949e;
        }}

        .project-nav-item .health-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}

        /* Main Content */
        .main-content {{
            padding: 30px;
            overflow-y: auto;
        }}

        /* Stats Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .stat-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
        }}

        .stat-card .value {{
            font-size: 2.5em;
            font-weight: bold;
            background: linear-gradient(90deg, #58a6ff, #3fb950);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .stat-card .label {{
            color: #8b949e;
            font-size: 0.9em;
            margin-top: 5px;
        }}

        .stat-card.warning .value {{
            background: linear-gradient(90deg, #d29922, #f85149);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        /* Search */
        .search-container {{
            margin-bottom: 30px;
        }}

        .search-input {{
            width: 100%;
            padding: 15px 20px;
            font-size: 1em;
            border: 1px solid #30363d;
            border-radius: 10px;
            background: #0d1117;
            color: #c9d1d9;
            outline: none;
            transition: all 0.2s ease;
        }}

        .search-input:focus {{
            border-color: #58a6ff;
            box-shadow: 0 0 0 3px #58a6ff20;
        }}

        .search-input::placeholder {{
            color: #484f58;
        }}

        /* Project Cards */
        .project-section {{
            margin-bottom: 40px;
            display: none;
        }}

        .project-section.active {{
            display: block;
        }}

        .project-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #30363d;
        }}

        .project-header .emoji {{
            font-size: 2em;
        }}

        .project-header .info {{
            flex: 1;
        }}

        .project-header .info h2 {{
            font-size: 1.5em;
            color: #f0f6fc;
            margin-bottom: 5px;
        }}

        .project-header .info p {{
            color: #8b949e;
        }}

        .project-header .health-badge {{
            padding: 8px 16px;
            border-radius: 20px;
            font-weight: 500;
            font-size: 0.9em;
        }}

        /* Era Groups */
        .era-group {{
            margin-bottom: 25px;
        }}

        .era-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1em;
            color: #8b949e;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #21262d;
        }}

        .era-title .era-emoji {{
            font-size: 1.2em;
        }}

        .era-title .era-count {{
            margin-left: auto;
            background: #21262d;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 0.85em;
        }}

        /* Session Cards */
        .sessions-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}

        .session-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 15px 20px;
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 15px;
            align-items: center;
            cursor: pointer;
            transition: all 0.2s ease;
        }}

        .session-card:hover {{
            border-color: #58a6ff;
            background: #1c2128;
        }}

        .session-card .session-id {{
            font-family: monospace;
            color: #58a6ff;
            font-size: 0.9em;
            background: #58a6ff15;
            padding: 4px 10px;
            border-radius: 6px;
        }}

        .session-card .session-summary {{
            color: #c9d1d9;
            font-size: 0.95em;
            line-height: 1.4;
        }}

        .session-card .session-meta {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 5px;
            font-size: 0.8em;
            color: #8b949e;
        }}

        .session-card .wip-badge {{
            background: #d2992220;
            color: #d29922;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
        }}

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

        .modal.active {{
            display: flex;
        }}

        .modal-content {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 16px;
            padding: 30px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
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

        .modal-header h2 {{
            color: #58a6ff;
            font-family: monospace;
        }}

        .modal-close {{
            background: none;
            border: none;
            color: #8b949e;
            font-size: 1.5em;
            cursor: pointer;
            padding: 5px 10px;
            border-radius: 6px;
        }}

        .modal-close:hover {{
            background: #21262d;
            color: #f0f6fc;
        }}

        .modal-body p {{
            margin-bottom: 12px;
            line-height: 1.5;
        }}

        .modal-body strong {{
            color: #8b949e;
        }}

        .command-box {{
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 15px;
            margin-top: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .command-box code {{
            flex: 1;
            color: #3fb950;
            font-family: monospace;
            font-size: 0.95em;
        }}

        .copy-btn {{
            background: #238636;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.2s ease;
        }}

        .copy-btn:hover {{
            background: #2ea043;
        }}

        /* Footer */
        .footer {{
            text-align: center;
            padding: 30px;
            color: #484f58;
            font-size: 0.85em;
            border-top: 1px solid #21262d;
            margin-top: 40px;
        }}

        /* Responsive */
        @media (max-width: 900px) {{
            .dashboard {{
                grid-template-columns: 1fr;
            }}

            .sidebar {{
                position: relative;
                height: auto;
                border-right: none;
                border-bottom: 1px solid #30363d;
            }}

            .project-nav {{
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
            }}

            .project-nav-item {{
                padding: 8px 12px;
            }}

            .session-card {{
                grid-template-columns: 1fr;
                gap: 10px;
            }}

            .session-card .session-meta {{
                flex-direction: row;
                align-items: center;
            }}
        }}

        /* All Projects View */
        .all-projects-view {{
            display: none;
        }}

        .all-projects-view.active {{
            display: block;
        }}

        .project-cards-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }}

        .project-overview-card {{
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.2s ease;
        }}

        .project-overview-card:hover {{
            border-color: #58a6ff;
            transform: translateY(-2px);
        }}

        .project-overview-card .header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 15px;
        }}

        .project-overview-card .header .emoji {{
            font-size: 1.8em;
        }}

        .project-overview-card .header .name {{
            font-size: 1.2em;
            font-weight: 600;
            color: #f0f6fc;
        }}

        .project-overview-card .metrics {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 15px;
        }}

        .project-overview-card .metric {{
            text-align: center;
            padding: 10px;
            background: #0d1117;
            border-radius: 8px;
        }}

        .project-overview-card .metric .num {{
            font-size: 1.3em;
            font-weight: bold;
            color: #58a6ff;
        }}

        .project-overview-card .metric .lbl {{
            font-size: 0.75em;
            color: #8b949e;
        }}

        .project-overview-card .health {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-top: 15px;
            border-top: 1px solid #21262d;
        }}

        .project-overview-card .last-activity {{
            color: #8b949e;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
    <div class="dashboard">
        <!-- Sidebar -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>⏰ Project Epoch</h1>
                <p>Health Dashboard</p>
            </div>

            <nav>
                <ul class="project-nav">
                    <li class="project-nav-item active" onclick="showAllProjects()" data-project="all">
                        <span class="emoji">📊</span>
                        <span class="name">All Projects</span>
                        <span class="count">{total_projects}</span>
                    </li>
'''

    # Add project navigation items
    for proj_name, proj in sorted_projects:
        is_pinned = "📌 " if proj_name in pinned_set else ""
        html_content += f'''
                    <li class="project-nav-item" onclick="showProject('{proj_name}')" data-project="{proj_name}">
                        <span class="emoji">{proj["emoji"]}</span>
                        <span class="name">{is_pinned}{proj_name}</span>
                        <span class="count">{proj["total_count"]}</span>
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
                <div class="stat-card">
                    <div class="value">{active_projects}</div>
                    <div class="label">Active This Week</div>
                </div>
                <div class="stat-card warning">
                    <div class="value">{wip_sessions}</div>
                    <div class="label">WIP Sessions</div>
                </div>
            </div>

            <!-- Search -->
            <div class="search-container">
                <input type="text" class="search-input" id="search" placeholder="🔍 Search sessions by summary, project, or ID..." onkeyup="filterSessions()">
            </div>

            <!-- All Projects Overview -->
            <div class="all-projects-view active" id="all-projects">
                <h2 style="margin-bottom: 20px; color: #f0f6fc;">📊 Project Overview</h2>
                <div class="project-cards-grid">
'''

    # Add project overview cards
    for proj_name, proj in sorted_projects:
        last_activity_str = ""
        if proj["last_activity"]:
            days = (datetime.now() - proj["last_activity"]).days
            if days == 0:
                last_activity_str = "Today"
            elif days == 1:
                last_activity_str = "Yesterday"
            else:
                last_activity_str = f"{days} days ago"

        html_content += f'''
                    <div class="project-overview-card" onclick="showProject('{proj_name}')">
                        <div class="header">
                            <span class="emoji">{proj["emoji"]}</span>
                            <span class="name">{proj_name}</span>
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
                        </div>
                        <div class="health">
                            <span style="color: {proj["health_color"]}">{proj["health_status"]}</span>
                            <span class="last-activity">{last_activity_str}</span>
                        </div>
                    </div>
'''

    html_content += '''
                </div>
            </div>
'''

    # Add individual project sections
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

        html_content += f'''
            <!-- Project: {proj_name} -->
            <div class="project-section" id="project-{proj_name.replace(' ', '-').replace('/', '-')}">
                <div class="project-header">
                    <span class="emoji">{proj["emoji"]}</span>
                    <div class="info">
                        <h2>{proj_name}</h2>
                        <p>{proj["description"]} • {proj["total_count"]} sessions • Last: {last_activity_str}</p>
                    </div>
                    <span class="health-badge" style="background: {proj["health_color"]}20; color: {proj["health_color"]}">{proj["health_status"]}</span>
                </div>
'''

        # Add sessions grouped by era
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
                        <span class="era-count">{len(era_sessions)} sessions</span>
                    </div>
                    <div class="sessions-list">
'''

            for session in era_sessions:
                wip_badge = '<span class="wip-badge">⚠️ WIP</span>' if session["has_wip"] else ""
                summary = session["summary"][:120] + "..." if len(session["summary"]) > 120 else session["summary"]

                html_content += f'''
                        <div class="session-card" onclick="showSession('{session["id"]}')" data-search="{session['summary'].lower()} {session['project'].lower()} {session['short_id'].lower()}">
                            <span class="session-id">#{session["short_id"]}</span>
                            <span class="session-summary">{summary}</span>
                            <div class="session-meta">
                                <span>{session["relative_time"]}</span>
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

    # Add modal and footer
    html_content += f'''
            <div class="footer">
                <p>Generated by Project Epoch • {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
                <p>Your code history, organized by project health 🏥</p>
            </div>
        </main>
    </div>

    <!-- Session Detail Modal -->
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

        function showAllProjects() {{
            // Update nav
            document.querySelectorAll('.project-nav-item').forEach(el => el.classList.remove('active'));
            document.querySelector('[data-project="all"]').classList.add('active');

            // Show all projects view
            document.querySelectorAll('.project-section').forEach(el => el.classList.remove('active'));
            document.getElementById('all-projects').classList.add('active');
        }}

        function showProject(projectName) {{
            // Update nav
            document.querySelectorAll('.project-nav-item').forEach(el => el.classList.remove('active'));
            const navItem = document.querySelector(`[data-project="${{projectName}}"]`);
            if (navItem) navItem.classList.add('active');

            // Hide all, show selected
            document.getElementById('all-projects').classList.remove('active');
            document.querySelectorAll('.project-section').forEach(el => el.classList.remove('active'));

            const projectId = 'project-' + projectName.replace(/ /g, '-').replace(/\\//g, '-');
            const section = document.getElementById(projectId);
            if (section) section.classList.add('active');
        }}

        function filterSessions() {{
            const query = document.getElementById('search').value.toLowerCase();
            document.querySelectorAll('.session-card').forEach(card => {{
                const searchText = card.dataset.search || '';
                card.style.display = searchText.includes(query) ? 'grid' : 'none';
            }});

            // Also filter project overview cards
            document.querySelectorAll('.project-overview-card').forEach(card => {{
                const name = card.querySelector('.name').textContent.toLowerCase();
                card.style.display = name.includes(query) ? 'block' : 'none';
            }});
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

        // Close modal on outside click or Escape
        document.getElementById('session-modal').addEventListener('click', (e) => {{
            if (e.target.id === 'session-modal') closeModal();
        }});

        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeModal();
        }});
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


# Keep old function for backwards compatibility
def generate_html_explorer(output_path: str = "session_explorer.html", include_relationships: bool = True) -> str:
    """Deprecated: Use generate_html_dashboard instead."""
    return generate_html_dashboard(output_path)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    output = "~/Desktop/project_dashboard.html"
    if len(sys.argv) > 1:
        output = sys.argv[1]

    path = generate_html_dashboard(output)
    print(f"\n🌐 Open in browser: file://{path}")
    print(f"   Or run: open {path}")
