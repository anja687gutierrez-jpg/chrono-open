#!/usr/bin/env python3
"""
Epoch - Git Time Machine for Project Epoch

In Chrono Trigger, the Epoch (Wings of Time) is a time machine that allows
free travel to any point in history. Unlike Time Gates which are fixed portals,
the Epoch gives complete control over time travel.

In Project Epoch, the Epoch commands provide git navigation:
- View commit history with Chrono theming
- Jump to specific commits
- Compare branches
- Visualize the timeline

Usage:
    epoch log                    # Pretty commit history
    epoch log -n 20              # Show 20 commits
    epoch status                 # Current position in timeline
    epoch jump abc123            # Checkout commit
    epoch compare main..feature  # Compare branches
    epoch branches               # List all branches
    epoch timeline               # ASCII timeline visualization
"""

import subprocess
import sys
import argparse
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from pathlib import Path

from chrono_utils import (
    ERAS, RESET, BOLD, DIM,
    classify_era, format_timestamp_relative,
    parse_flexible_date
)


# ============================================================
# Git Utilities
# ============================================================

def run_git(args: List[str], cwd: Optional[str] = None) -> Tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except FileNotFoundError:
        return False, "Git not found. Please install git."
    except Exception as e:
        return False, str(e)


def is_git_repo(path: Optional[str] = None) -> bool:
    """Check if current directory is a git repository."""
    success, _ = run_git(["rev-parse", "--git-dir"], cwd=path)
    return success


def get_current_branch() -> Optional[str]:
    """Get the current branch name."""
    success, output = run_git(["branch", "--show-current"])
    if success and output:
        return output
    # Might be in detached HEAD state
    success, output = run_git(["rev-parse", "--short", "HEAD"])
    return f"detached@{output}" if success else None


def get_repo_root() -> Optional[str]:
    """Get the repository root directory."""
    success, output = run_git(["rev-parse", "--show-toplevel"])
    return output if success else None


def get_repo_name() -> str:
    """Get the repository name from the root directory."""
    root = get_repo_root()
    if root:
        return Path(root).name
    return "unknown"


# ============================================================
# Epoch Commands
# ============================================================

def cmd_status() -> None:
    """Show current position in the timeline."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.")
        print(f"  {DIM}Navigate to a git repo and try again.{RESET}\n")
        return

    repo_name = get_repo_name()
    branch = get_current_branch()

    # Get current commit info
    success, commit_hash = run_git(["rev-parse", "--short", "HEAD"])
    success2, commit_msg = run_git(["log", "-1", "--format=%s"])
    success3, commit_date = run_git(["log", "-1", "--format=%ci"])
    success4, author = run_git(["log", "-1", "--format=%an"])

    # Get ahead/behind info
    success5, upstream = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"])
    ahead_behind = ""
    if success5:
        success6, ab = run_git(["rev-list", "--left-right", "--count", f"{upstream}...HEAD"])
        if success6:
            behind, ahead = ab.split()
            if int(ahead) > 0:
                ahead_behind += f" ↑{ahead}"
            if int(behind) > 0:
                ahead_behind += f" ↓{behind}"

    # Classify era based on commit date
    era = classify_era(commit_date) if success3 else ERAS[-1]
    rel_time = format_timestamp_relative(commit_date) if success3 else "unknown"

    # Get uncommitted changes status
    success7, status = run_git(["status", "--porcelain"])
    changes = ""
    if success7 and status:
        lines = status.strip().split('\n')
        staged = sum(1 for l in lines if l and l[0] in 'MADRC')
        unstaged = sum(1 for l in lines if l and l[1] in 'MADRC?')
        if staged:
            changes += f" +{staged} staged"
        if unstaged:
            changes += f" ~{unstaged} unstaged"

    print(f"\n  {BOLD}🚀 EPOCH STATUS - Current Position in Timeline{RESET}")
    print(f"  {'═' * 55}\n")

    print(f"  {BOLD}Repository:{RESET}  {repo_name}")
    print(f"  {BOLD}Branch:{RESET}      {branch}{ahead_behind}")
    print(f"  {BOLD}Commit:{RESET}      {commit_hash if success else 'unknown'}")
    print(f"  {BOLD}Message:{RESET}     {commit_msg[:50] if success2 else 'unknown'}{'...' if success2 and len(commit_msg) > 50 else ''}")
    print(f"  {BOLD}Author:{RESET}      {author if success4 else 'unknown'}")
    print(f"  {BOLD}Era:{RESET}         {era.emoji} {era.time_period} ({rel_time})")
    if changes:
        print(f"  {BOLD}Changes:{RESET}    {changes.strip()}")

    print(f"\n  {'─' * 55}")
    print(f"  {DIM}epoch log      - View commit history{RESET}")
    print(f"  {DIM}epoch branches - List all branches{RESET}")
    print(f"  {DIM}epoch timeline - Visual timeline{RESET}\n")


def cmd_log(count: int = 10, all_branches: bool = False, oneline: bool = False) -> None:
    """Show commit history with Chrono theming."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    # Get commits
    format_str = "%H|%h|%s|%an|%ci" if not oneline else "%h|%s"
    args = ["log", f"-{count}", f"--format={format_str}"]
    if all_branches:
        args.append("--all")

    success, output = run_git(args)
    if not success or not output:
        print(f"\n  {DIM}No commits found.{RESET}\n")
        return

    repo_name = get_repo_name()
    branch = get_current_branch()

    print(f"\n  {BOLD}🚀 EPOCH LOG - {repo_name} ({branch}){RESET}")
    print(f"  {'═' * 60}\n")

    commits = output.strip().split('\n')
    current_era = None

    for i, commit_line in enumerate(commits):
        parts = commit_line.split('|')

        if oneline:
            short_hash, message = parts[0], parts[1] if len(parts) > 1 else ""
            print(f"  {DIM}{short_hash}{RESET} {message[:60]}")
            continue

        if len(parts) < 5:
            continue

        full_hash, short_hash, message, author, date_str = parts

        # Classify era
        era = classify_era(date_str)
        rel_time = format_timestamp_relative(date_str)

        # Show era header if changed
        if era.code != (current_era.code if current_era else None):
            current_era = era
            if i > 0:
                print()
            print(f"  {era.color}{'─' * 56}{RESET}")
            print(f"  {era.color}{BOLD}{era.emoji} {era.name.upper()} - {era.time_period}{RESET}")
            print(f"  {era.color}{'─' * 56}{RESET}")

        # Format commit
        marker = "●" if i == 0 else "○"
        print(f"\n  {era.color}{marker}{RESET} {BOLD}{short_hash}{RESET} {message[:45]}{'...' if len(message) > 45 else ''}")
        print(f"    {DIM}{author} • {rel_time}{RESET}")

    print(f"\n  {'─' * 60}")
    print(f"  {DIM}Showing {len(commits)} commits{RESET}")
    print(f"  {DIM}epoch log -n 20   - Show more commits{RESET}")
    print(f"  {DIM}epoch log --all   - Include all branches{RESET}\n")


def cmd_jump(target: str, create_branch: Optional[str] = None) -> None:
    """Checkout a commit or branch."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    # Check for uncommitted changes
    success, status = run_git(["status", "--porcelain"])
    if success and status:
        print(f"\n  {BOLD}Warning:{RESET} You have uncommitted changes!")
        print(f"  {DIM}Stash or commit them before jumping.{RESET}")
        try:
            confirm = input(f"  Continue anyway? (y/N): ").strip().lower()
            if confirm != 'y':
                print(f"  {DIM}Jump cancelled.{RESET}\n")
                return
        except KeyboardInterrupt:
            print(f"\n  {DIM}Jump cancelled.{RESET}\n")
            return

    # Get info about target before jumping
    success, target_msg = run_git(["log", "-1", "--format=%s", target])
    success2, target_date = run_git(["log", "-1", "--format=%ci", target])

    if not success:
        print(f"\n  {BOLD}Error:{RESET} Target '{target}' not found.")
        print(f"  {DIM}Use a commit hash, branch name, or tag.{RESET}\n")
        return

    era = classify_era(target_date) if success2 else ERAS[-1]
    rel_time = format_timestamp_relative(target_date) if success2 else "unknown"

    # Perform the checkout
    if create_branch:
        success, output = run_git(["checkout", "-b", create_branch, target])
        action = f"Created branch '{create_branch}' at"
    else:
        success, output = run_git(["checkout", target])
        action = "Jumped to"

    if success:
        print(f"\n  {BOLD}🚀 EPOCH JUMP{RESET}")
        print(f"  {'─' * 50}")
        print(f"  {BOLD}{action}:{RESET}")
        print(f"  {era.emoji} {target[:12]} - {target_msg[:40]}{'...' if len(target_msg) > 40 else ''}")
        print(f"  {DIM}Era: {era.time_period} ({rel_time}){RESET}")
        print(f"  {'─' * 50}\n")
    else:
        print(f"\n  {BOLD}Error:{RESET} Jump failed.")
        print(f"  {DIM}{output}{RESET}\n")


def cmd_compare(range_str: str) -> None:
    """Compare two branches or commits."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    # Parse range (e.g., "main..feature" or "abc123..def456")
    if ".." not in range_str:
        print(f"\n  {BOLD}Error:{RESET} Invalid range format.")
        print(f"  {DIM}Use: epoch compare main..feature{RESET}\n")
        return

    base, head = range_str.split("..", 1)

    # Get commit counts
    success, ahead_count = run_git(["rev-list", "--count", f"{base}..{head}"])
    success2, behind_count = run_git(["rev-list", "--count", f"{head}..{base}"])

    if not success or not success2:
        print(f"\n  {BOLD}Error:{RESET} Could not compare '{base}' and '{head}'.")
        print(f"  {DIM}Make sure both refs exist.{RESET}\n")
        return

    # Get diff stats
    success3, diff_stat = run_git(["diff", "--stat", f"{base}..{head}"])
    success4, diff_summary = run_git(["diff", "--shortstat", f"{base}..{head}"])

    # Get file change summary
    success5, files_changed = run_git(["diff", "--name-only", f"{base}..{head}"])

    print(f"\n  {BOLD}🚀 EPOCH COMPARE{RESET}")
    print(f"  {'═' * 55}")
    print(f"  {BOLD}Comparing:{RESET} {base} → {head}")
    print(f"  {'─' * 55}\n")

    print(f"  {BOLD}Commits:{RESET}")
    print(f"    {head} is {BOLD}{ahead_count}{RESET} commits ahead of {base}")
    if int(behind_count) > 0:
        print(f"    {head} is {BOLD}{behind_count}{RESET} commits behind {base}")

    if success4 and diff_summary:
        print(f"\n  {BOLD}Changes:{RESET}")
        print(f"    {diff_summary}")

    if success5 and files_changed:
        files = files_changed.strip().split('\n')[:10]
        print(f"\n  {BOLD}Files modified:{RESET} ({len(files_changed.strip().split(chr(10)))} total)")
        for f in files:
            print(f"    {DIM}•{RESET} {f}")
        if len(files_changed.strip().split('\n')) > 10:
            print(f"    {DIM}... and {len(files_changed.strip().split(chr(10))) - 10} more{RESET}")

    print(f"\n  {'─' * 55}")
    print(f"  {DIM}Full diff: git diff {base}..{head}{RESET}")
    print(f"  {DIM}Commits:   git log {base}..{head} --oneline{RESET}\n")


def cmd_branches() -> None:
    """List all branches with era classification."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    # Get all branches with last commit date
    success, output = run_git([
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname:short)|%(committerdate:iso)|%(subject)|%(authorname)",
        "refs/heads/"
    ])

    if not success or not output:
        print(f"\n  {DIM}No branches found.{RESET}\n")
        return

    current = get_current_branch()
    repo_name = get_repo_name()

    print(f"\n  {BOLD}🚀 EPOCH BRANCHES - {repo_name}{RESET}")
    print(f"  {'═' * 60}\n")

    branches = output.strip().split('\n')
    current_era = None

    for branch_line in branches:
        parts = branch_line.split('|')
        if len(parts) < 4:
            continue

        branch_name, date_str, message, author = parts

        era = classify_era(date_str)
        rel_time = format_timestamp_relative(date_str)

        # Show era header if changed
        if era.code != (current_era.code if current_era else None):
            current_era = era
            print(f"  {era.color}{era.emoji} {era.name.upper()} - {era.time_period}{RESET}")
            print(f"  {era.color}{'─' * 56}{RESET}")

        # Mark current branch
        marker = "→" if branch_name == current else " "
        current_marker = f" {BOLD}(current){RESET}" if branch_name == current else ""

        print(f"  {marker} {BOLD}{branch_name}{RESET}{current_marker}")
        print(f"    {DIM}{message[:40]}{'...' if len(message) > 40 else ''} • {rel_time}{RESET}")

    print(f"\n  {'─' * 60}")
    print(f"  {BOLD}Total: {len(branches)} branches{RESET}")
    print(f"  {DIM}epoch jump <branch>  - Switch to branch{RESET}\n")


def cmd_timeline(count: int = 15) -> None:
    """Show ASCII timeline of commits."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    # Use git log with graph
    success, output = run_git([
        "log",
        f"-{count}",
        "--graph",
        "--abbrev-commit",
        "--decorate",
        "--format=format:%C(bold blue)%h%C(reset) - %C(white)%s%C(reset) %C(dim)(%ar)%C(reset)%C(auto)%d%C(reset)",
        "--all"
    ])

    if not success or not output:
        print(f"\n  {DIM}No commits found.{RESET}\n")
        return

    repo_name = get_repo_name()

    print(f"\n  {BOLD}🚀 EPOCH TIMELINE - {repo_name}{RESET}")
    print(f"  {'═' * 60}\n")

    # Print the graph
    for line in output.split('\n'):
        print(f"  {line}")

    print(f"\n  {'─' * 60}")
    print(f"  {DIM}epoch timeline -n 30  - Show more history{RESET}")
    print(f"  {DIM}epoch log             - Detailed commit view{RESET}\n")


def cmd_stash(action: str = "list", message: str = "") -> None:
    """Manage the stash (temporary storage for changes)."""
    if not is_git_repo():
        print(f"\n  {BOLD}Error:{RESET} Not in a git repository.\n")
        return

    if action == "list":
        success, output = run_git(["stash", "list"])
        if not success or not output:
            print(f"\n  {DIM}No stashed changes.{RESET}")
            print(f"  {DIM}Use 'epoch stash save' to stash current changes.{RESET}\n")
            return

        print(f"\n  {BOLD}🚀 EPOCH STASH - Temporal Storage{RESET}")
        print(f"  {'═' * 50}\n")

        for line in output.strip().split('\n'):
            print(f"  {line}")

        print(f"\n  {DIM}epoch stash pop   - Apply and remove latest stash{RESET}")
        print(f"  {DIM}epoch stash drop  - Discard latest stash{RESET}\n")

    elif action == "save" or action == "push":
        msg_args = ["-m", message] if message else []
        success, output = run_git(["stash", "push"] + msg_args)
        if success:
            print(f"\n  {BOLD}✓ Changes stashed{RESET}")
            if message:
                print(f"  {DIM}Message: {message}{RESET}")
            print(f"  {DIM}Use 'epoch stash pop' to restore.{RESET}\n")
        else:
            print(f"\n  {DIM}Nothing to stash (working tree clean).{RESET}\n")

    elif action == "pop":
        success, output = run_git(["stash", "pop"])
        if success:
            print(f"\n  {BOLD}✓ Stash applied and removed{RESET}\n")
        else:
            print(f"\n  {BOLD}Error:{RESET} {output}\n")

    elif action == "drop":
        success, output = run_git(["stash", "drop"])
        if success:
            print(f"\n  {BOLD}✓ Latest stash dropped{RESET}\n")
        else:
            print(f"\n  {BOLD}Error:{RESET} {output}\n")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Epoch - Git time machine with Chrono Trigger theming",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Commands:{RESET}
  status                   Current position in timeline
  log [-n COUNT]           Commit history with eras
  branches                 List all branches by era
  timeline [-n COUNT]      ASCII commit graph
  jump <target>            Checkout commit/branch
  compare <a>..<b>         Compare branches/commits
  stash [save|pop|drop]    Manage stashed changes

{BOLD}Examples:{RESET}
  epoch status                    # Where am I?
  epoch log                       # Recent commits
  epoch log -n 20                 # More commits
  epoch branches                  # All branches by era
  epoch jump feature-auth         # Switch branch
  epoch jump abc123 -b fix-bug    # Create branch at commit
  epoch compare main..feature     # Compare branches
  epoch timeline                  # Visual history
        """
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "log", "branches", "timeline", "jump", "compare", "stash"],
        help="Command to run (default: status)"
    )

    parser.add_argument(
        "args",
        nargs="*",
        help="Command arguments"
    )

    parser.add_argument(
        "-n", "--count",
        type=int,
        default=10,
        help="Number of items to show (for log, timeline)"
    )

    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Include all branches (for log)"
    )

    parser.add_argument(
        "-b", "--branch",
        type=str,
        help="Create new branch when jumping"
    )

    parser.add_argument(
        "-m", "--message",
        type=str,
        default="",
        help="Message (for stash save)"
    )

    parser.add_argument(
        "--oneline",
        action="store_true",
        help="Compact output (for log)"
    )

    args = parser.parse_args()

    # Route to command handlers
    if args.command == "status":
        cmd_status()

    elif args.command == "log":
        cmd_log(count=args.count, all_branches=args.all, oneline=args.oneline)

    elif args.command == "branches":
        cmd_branches()

    elif args.command == "timeline":
        cmd_timeline(count=args.count)

    elif args.command == "jump":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a target (commit, branch, or tag).")
            print(f"  {DIM}Usage: epoch jump <target> [-b new-branch]{RESET}\n")
            return
        cmd_jump(args.args[0], create_branch=args.branch)

    elif args.command == "compare":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please provide a range to compare.")
            print(f"  {DIM}Usage: epoch compare main..feature{RESET}\n")
            return
        cmd_compare(args.args[0])

    elif args.command == "stash":
        action = args.args[0] if args.args else "list"
        cmd_stash(action=action, message=args.message)


if __name__ == "__main__":
    main()
