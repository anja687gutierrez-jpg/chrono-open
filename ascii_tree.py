"""
ASCII Tree Visualization for Session Graphs

Creates beautiful tree visualizations showing session relationships.
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

from chrono_utils import (
    classify_era, format_timestamp_relative, separator, truncate, box_header, term_width,
    RESET, BOLD, DIM, CYAN, GREEN, BLUE, MAGENTA, GRAY
)


@dataclass
class TreeNode:
    """A node in the ASCII tree."""
    id: str
    label: str
    era_emoji: str
    time_str: str
    score: float = 0.0
    children: List['TreeNode'] = None
    connection_type: str = ""  # "project", "files", "similar", "time"

    def __post_init__(self):
        if self.children is None:
            self.children = []


def build_session_tree(
    root_session: Dict,
    related_sessions: List[Tuple[Dict, str, float]],
    similar_sessions: List[Dict] = None
) -> TreeNode:
    """
    Build a tree structure from session relationships.

    Args:
        root_session: The central session
        related_sessions: List of (session, reason, strength) tuples
        similar_sessions: Optional list of semantically similar sessions

    Returns:
        TreeNode representing the root
    """
    era = classify_era(root_session.get("timestamp"))
    time_str = format_timestamp_relative(root_session.get("timestamp"))

    root = TreeNode(
        id=root_session.get("session_id", "unknown")[:8],
        label=truncate(root_session.get("summary", root_session.get("project", "Session")), max_len=40),
        era_emoji=era.emoji,
        time_str=time_str
    )

    # Group related by connection type
    by_project = []
    by_files = []
    by_time = []

    for session, reason, strength in related_sessions:
        s_era = classify_era(session.get("timestamp"))
        s_time = format_timestamp_relative(session.get("timestamp"))

        node = TreeNode(
            id=session.get("session_id", "")[:8],
            label=session.get("summary", session.get("project", ""))[:35],
            era_emoji=s_era.emoji,
            time_str=s_time,
            score=strength
        )

        if "same project" in reason:
            node.connection_type = "project"
            by_project.append(node)
        elif "shared files" in reason:
            node.connection_type = "files"
            by_files.append(node)
        else:
            node.connection_type = "time"
            by_time.append(node)

    # Add similar sessions as a branch
    similar_nodes = []
    if similar_sessions:
        for session in similar_sessions[:4]:
            s_era = session.get("era") or classify_era(session.get("timestamp"))
            s_time = session.get("relative_time") or format_timestamp_relative(session.get("timestamp"))

            node = TreeNode(
                id=session.get("session_id", "")[:8],
                label=session.get("summary", "")[:35],
                era_emoji=s_era.emoji,
                time_str=s_time,
                score=session.get("score", 0) / 100,
                connection_type="similar"
            )
            similar_nodes.append(node)

    # Build tree structure
    if by_project:
        branch = TreeNode(
            id="",
            label=f"📁 Same Project ({len(by_project)})",
            era_emoji="",
            time_str="",
            children=by_project[:4]
        )
        root.children.append(branch)

    if by_files:
        branch = TreeNode(
            id="",
            label=f"📄 Shared Files ({len(by_files)})",
            era_emoji="",
            time_str="",
            children=by_files[:3]
        )
        root.children.append(branch)

    if similar_nodes:
        branch = TreeNode(
            id="",
            label=f"🧠 Similar Topics ({len(similar_nodes)})",
            era_emoji="",
            time_str="",
            children=similar_nodes
        )
        root.children.append(branch)

    if by_time and not by_project and not by_files:
        branch = TreeNode(
            id="",
            label=f"⏰ Same Time ({len(by_time)})",
            era_emoji="",
            time_str="",
            children=by_time[:3]
        )
        root.children.append(branch)

    return root


def render_tree(
    node: TreeNode,
    prefix: str = "",
    is_last: bool = True,
    is_root: bool = True,
    use_color: bool = True
) -> str:
    """
    Render a tree as ASCII art.

    Args:
        node: The tree node to render
        prefix: Current line prefix for indentation
        is_last: Whether this is the last sibling
        is_root: Whether this is the root node
        use_color: Whether to use ANSI colors

    Returns:
        ASCII tree string
    """
    if use_color:
        from chrono_utils import CYAN, GREEN, BLUE, MAGENTA, GRAY
        YELLOW = BLUE    # "Yellow" is actually blue for light-bg visibility
        WHITE = GRAY     # "White" is actually dark gray for light-bg visibility
    else:
        CYAN = GREEN = YELLOW = MAGENTA = WHITE = ""

    lines = []

    # Connection characters
    if is_root:
        connector = ""
        new_prefix = ""
    else:
        connector = "└── " if is_last else "├── "
        new_prefix = prefix + ("    " if is_last else "│   ")

    # Build the node line
    if is_root:
        # Root node - special formatting
        bw = min(58, term_width() - 4)
        lines.append(f"{BOLD}{GREEN}╭{'─' * bw}╮{RESET}")
        lines.append(f"{BOLD}{GREEN}│  🎯 #{node.id}  {RESET}")
        lines.append(f"{GREEN}│  {DIM}{node.label}{RESET}")
        lines.append(f"{GREEN}│  {node.era_emoji} {node.time_str}{RESET}")
        lines.append(f"{BOLD}{GREEN}╰{'─' * bw}╯{RESET}")
        lines.append(f"{GREEN}          │{RESET}")
    elif node.id:
        # Regular session node
        score_bar = ""
        if node.score > 0:
            filled = int(node.score * 5)
            score_bar = f" {'█' * filled}{'░' * (5 - filled)}"

        color = {
            "project": YELLOW,
            "files": MAGENTA,
            "similar": CYAN,
            "time": WHITE
        }.get(node.connection_type, "")

        lines.append(f"{prefix}{connector}{color}#{node.id}{RESET}{score_bar}")
        lines.append(f"{new_prefix}{DIM}{node.label}{RESET}")
        lines.append(f"{new_prefix}{node.era_emoji} {node.time_str}")
    else:
        # Branch header (no ID)
        lines.append(f"{prefix}{connector}{BOLD}{node.label}{RESET}")

    # Render children
    for i, child in enumerate(node.children):
        is_last_child = (i == len(node.children) - 1)
        child_lines = render_tree(
            child,
            prefix=new_prefix,
            is_last=is_last_child,
            is_root=False,
            use_color=use_color
        )
        lines.append(child_lines)

    return "\n".join(lines)


def format_tree_header(use_color: bool = True) -> str:
    """Format the tree visualization header."""
    _cyan = CYAN if use_color else ""
    _bold = BOLD if use_color else ""
    _reset = RESET if use_color else ""

    return "\n" + box_header("🌳 SESSION TREE - Visual Relationship Map", color=_cyan, use_color=use_color) + "\n"


def create_session_tree_view(
    root_session: Dict,
    related: List[Tuple[Dict, str, float]],
    similar: List[Dict] = None,
    use_color: bool = True
) -> str:
    """
    Create a complete tree visualization.

    Args:
        root_session: Central session dict
        related: Related sessions from graph
        similar: Similar sessions from embeddings

    Returns:
        Complete ASCII tree visualization
    """
    lines = [format_tree_header(use_color)]

    tree = build_session_tree(root_session, related, similar)
    lines.append(render_tree(tree, use_color=use_color))

    # Legend
    lines.append("\n" + separator("─", 0, DIM))
    lines.append(f"{DIM}Legend: 📁 Same Project │ 📄 Shared Files │ 🧠 Similar Topics{RESET}")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI Testing
# ============================================================

if __name__ == "__main__":
    # Demo with fake data
    root = {
        "session_id": "bf695425-test",
        "project": "MagnusView",
        "timestamp": "2026-01-15T10:00:00",
        "summary": "Set up Firebase authentication for dashboard"
    }

    related = [
        ({"session_id": "abc12345", "project": "MagnusView", "timestamp": "2026-01-14T10:00:00", "summary": "Added login page UI"}, "same project", 0.8),
        ({"session_id": "def67890", "project": "MagnusView", "timestamp": "2026-01-13T10:00:00", "summary": "Created user database schema"}, "same project + 2 shared files", 0.9),
        ({"session_id": "ghi11111", "project": "OpsPortal", "timestamp": "2026-01-12T10:00:00", "summary": "Fixed auth redirect bug"}, "2 shared files", 0.5),
    ]

    similar = [
        {"session_id": "sim11111", "timestamp": "2025-12-01T10:00:00", "summary": "Implemented OAuth for API", "score": 85},
        {"session_id": "sim22222", "timestamp": "2025-11-15T10:00:00", "summary": "Added JWT token handling", "score": 78},
    ]

    print(create_session_tree_view(root, related, similar))
