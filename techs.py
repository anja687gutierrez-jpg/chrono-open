#!/usr/bin/env python3
"""
Techs - Workflow Automation for Project Epoch

In Chrono Trigger, Techs are special abilities that can be combined:
- Single Techs: Individual character moves
- Dual Techs: Two characters combine powers
- Triple Techs: Three characters unite for devastating attacks

In Project Epoch, Techs are command combos for development workflows:
- Single Techs: Quick single commands (build, test, lint)
- Dual Techs: Combined actions (test + commit)
- Triple Techs: Full workflows (build + test + deploy)

Usage:
    tech list                    # Show available techs
    tech fire                    # Run build (Lucca's fire = compilation)
    tech ice                     # Run tests (Marle's ice = freeze bugs)
    tech luminaire               # Full deploy workflow (Crono's ultimate)
    tech custom my-flow "npm run build && npm test"
"""

import subprocess
import sys
import os
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime

from chrono_utils import RESET, BOLD, DIM


# ============================================================
# Tech Definitions (Chrono Trigger themed!)
# ============================================================

# Single Techs - Named after character abilities
SINGLE_TECHS = {
    # Crono's Techs (Lightning/Speed - quick actions)
    "cyclone": {
        "name": "Cyclone",
        "character": "Crono",
        "element": "⚡",
        "description": "Quick format check",
        "commands": {
            "npm": "npm run format:check",
            "python": "black --check .",
            "default": "echo 'No format checker configured'"
        }
    },
    "slash": {
        "name": "Slash",
        "character": "Crono",
        "element": "⚡",
        "description": "Run linter",
        "commands": {
            "npm": "npm run lint",
            "python": "ruff check .",
            "default": "echo 'No linter configured'"
        }
    },
    "lightning": {
        "name": "Lightning",
        "character": "Crono",
        "element": "⚡",
        "description": "Quick type check",
        "commands": {
            "npm": "npx tsc --noEmit",
            "python": "mypy .",
            "default": "echo 'No type checker configured'"
        }
    },

    # Lucca's Techs (Fire - building/compilation)
    "fire": {
        "name": "Flame Toss",
        "character": "Lucca",
        "element": "🔥",
        "description": "Build the project",
        "commands": {
            "npm": "npm run build",
            "python": "python -m build",
            "default": "echo 'No build command configured'"
        }
    },
    "napalm": {
        "name": "Napalm",
        "character": "Lucca",
        "element": "🔥",
        "description": "Clean and rebuild",
        "commands": {
            "npm": "rm -rf dist node_modules/.cache && npm run build",
            "python": "rm -rf dist build *.egg-info && python -m build",
            "default": "echo 'No clean build configured'"
        }
    },
    "flare": {
        "name": "Flare",
        "character": "Lucca",
        "element": "🔥",
        "description": "Production build",
        "commands": {
            "npm": "NODE_ENV=production npm run build",
            "python": "python -m build --wheel",
            "default": "echo 'No production build configured'"
        }
    },

    # Marle's Techs (Ice/Healing - testing/fixing)
    "ice": {
        "name": "Ice",
        "character": "Marle",
        "element": "❄️",
        "description": "Run tests",
        "commands": {
            "npm": "npm test",
            "python": "pytest",
            "default": "echo 'No test command configured'"
        }
    },
    "cure": {
        "name": "Cure",
        "character": "Marle",
        "element": "💚",
        "description": "Auto-fix issues",
        "commands": {
            "npm": "npm run lint:fix",
            "python": "ruff check --fix . && black .",
            "default": "echo 'No auto-fix configured'"
        }
    },
    "haste": {
        "name": "Haste",
        "character": "Marle",
        "element": "💚",
        "description": "Run fast/watch tests",
        "commands": {
            "npm": "npm test -- --watch",
            "python": "pytest -x --ff",
            "default": "echo 'No watch tests configured'"
        }
    },

    # Frog's Techs (Water/Honor - git operations)
    "leap": {
        "name": "Leap Slash",
        "character": "Frog",
        "element": "💧",
        "description": "Git status",
        "commands": {
            "default": "git status -sb"
        }
    },
    "water": {
        "name": "Water",
        "character": "Frog",
        "element": "💧",
        "description": "Git pull",
        "commands": {
            "default": "git pull --rebase"
        }
    },

    # Robo's Techs (Mechanical - automation)
    "laser": {
        "name": "Laser Spin",
        "character": "Robo",
        "element": "🤖",
        "description": "Install dependencies",
        "commands": {
            "npm": "npm install",
            "python": "pip install -e .",
            "default": "echo 'No install command configured'"
        }
    },
    "heal-beam": {
        "name": "Heal Beam",
        "character": "Robo",
        "element": "🤖",
        "description": "Update dependencies",
        "commands": {
            "npm": "npm update",
            "python": "pip install --upgrade -e .",
            "default": "echo 'No update command configured'"
        }
    },

    # Ayla's Techs (Primal - raw power)
    "rock": {
        "name": "Rock Throw",
        "character": "Ayla",
        "element": "💪",
        "description": "Start dev server",
        "commands": {
            "npm": "npm run dev",
            "python": "python -m flask run",
            "default": "echo 'No dev server configured'"
        }
    },

    # Magus's Techs (Shadow/Dark - dangerous operations)
    "dark": {
        "name": "Dark Matter",
        "character": "Magus",
        "element": "🌑",
        "description": "Reset to clean state",
        "commands": {
            "default": "git checkout . && git clean -fd"
        }
    },
}

# Dual Techs - Combinations of two characters
DUAL_TECHS = {
    "fire-sword": {
        "name": "Fire Sword",
        "characters": ["Crono", "Lucca"],
        "element": "🔥⚡",
        "description": "Build + Lint",
        "techs": ["fire", "slash"]
    },
    "ice-sword": {
        "name": "Ice Sword",
        "characters": ["Crono", "Marle"],
        "element": "❄️⚡",
        "description": "Test + Type check",
        "techs": ["ice", "lightning"]
    },
    "antipode": {
        "name": "Antipode",
        "characters": ["Lucca", "Marle"],
        "element": "🔥❄️",
        "description": "Build + Test",
        "techs": ["fire", "ice"]
    },
    "x-strike": {
        "name": "X-Strike",
        "characters": ["Crono", "Frog"],
        "element": "⚡💧",
        "description": "Lint + Git status",
        "techs": ["slash", "leap"]
    },
    "fire-whirl": {
        "name": "Fire Whirl",
        "characters": ["Crono", "Lucca"],
        "element": "🔥⚡",
        "description": "Format + Build",
        "techs": ["cyclone", "fire"]
    },
    "cure-wave": {
        "name": "Cure Wave",
        "characters": ["Marle", "Robo"],
        "element": "💚🤖",
        "description": "Fix issues + Update deps",
        "techs": ["cure", "heal-beam"]
    },
    "blade-toss": {
        "name": "Blade Toss",
        "characters": ["Crono", "Ayla"],
        "element": "⚡💪",
        "description": "Lint + Dev server",
        "techs": ["slash", "rock"]
    },
}

# Triple Techs - Ultimate combinations
TRIPLE_TECHS = {
    "luminaire": {
        "name": "Luminaire",
        "characters": ["Crono", "Lucca", "Marle"],
        "element": "⭐",
        "description": "Build + Test + Deploy (Ultimate)",
        "commands": {
            "npm": "npm run build && npm test && npm run deploy",
            "python": "python -m build && pytest && twine upload dist/*",
            "default": "echo 'Build + Test + Deploy'"
        }
    },
    "delta-force": {
        "name": "Delta Force",
        "characters": ["Crono", "Lucca", "Marle"],
        "element": "🔺",
        "description": "Lint + Test + Commit",
        "commands": {
            "npm": "npm run lint && npm test && git add -A && git commit",
            "python": "ruff check . && pytest && git add -A && git commit",
            "default": "echo 'Lint + Test + Commit'"
        }
    },
    "omega-flare": {
        "name": "Omega Flare",
        "characters": ["Lucca", "Robo", "Magus"],
        "element": "🔥🤖🌑",
        "description": "Clean + Install + Build",
        "commands": {
            "npm": "rm -rf node_modules && npm install && npm run build",
            "python": "rm -rf venv && python -m venv venv && pip install -e . && python -m build",
            "default": "echo 'Clean + Install + Build'"
        }
    },
    "triple-raid": {
        "name": "Triple Raid",
        "characters": ["Crono", "Frog", "Robo"],
        "element": "⚡💧🤖",
        "description": "Pull + Install + Test",
        "commands": {
            "npm": "git pull --rebase && npm install && npm test",
            "python": "git pull --rebase && pip install -e . && pytest",
            "default": "echo 'Pull + Install + Test'"
        }
    },
    "dark-eternal": {
        "name": "Dark Eternal",
        "characters": ["Magus", "Marle", "Lucca"],
        "element": "🌑❄️🔥",
        "description": "Reset + Fresh install + Build",
        "commands": {
            "npm": "git checkout . && git clean -fd && npm install && npm run build",
            "python": "git checkout . && git clean -fd && pip install -e . && python -m build",
            "default": "echo 'Reset + Fresh install + Build'"
        }
    },
}

# Custom techs storage
CUSTOM_TECHS_FILE = Path.home() / ".smart-forking" / "techs.json"


# ============================================================
# Project Detection
# ============================================================

def detect_project_type() -> str:
    """Detect the project type based on files present."""
    cwd = Path.cwd()

    if (cwd / "package.json").exists():
        return "npm"
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        return "python"
    if (cwd / "Cargo.toml").exists():
        return "rust"
    if (cwd / "go.mod").exists():
        return "go"

    return "default"


def get_command_for_project(tech: Dict, project_type: str) -> Tuple[str, bool]:
    """Get the appropriate command for the project type.

    Returns:
        (command, is_fallback) - command string and whether it's a fallback
    """
    commands = tech.get("commands", {})
    # "default" project type means no project was detected
    is_fallback = (project_type == "default")
    if project_type in commands:
        return commands[project_type], is_fallback
    return commands.get("default", "echo 'No command'"), True


# ============================================================
# Tech Execution
# ============================================================

def run_command(command: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    if dry_run:
        return True, f"[DRY RUN] Would execute: {command}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=os.getcwd()
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


def execute_tech(tech_id: str, dry_run: bool = False, verbose: bool = False) -> bool:
    """Execute a tech by ID."""
    project_type = detect_project_type()

    # Check single techs
    if tech_id in SINGLE_TECHS:
        tech = SINGLE_TECHS[tech_id]
        command, is_fallback = get_command_for_project(tech, project_type)

        print(f"\n  {tech['element']} {BOLD}{tech['name']}{RESET} ({tech['character']})")
        print(f"  {DIM}{tech['description']}{RESET}")
        print(f"  {'─' * 50}")

        # Warn if no project detected
        if is_fallback and project_type == "default":
            print(f"  \033[93m⚠ No project detected in this directory{RESET}")
            print(f"  {DIM}Looking for: package.json, pyproject.toml, Cargo.toml, go.mod{RESET}")

        if verbose or dry_run:
            print(f"  {DIM}Command: {command}{RESET}")

        success, output = run_command(command, dry_run)

        if output and (verbose or not success):
            for line in output.split('\n')[:20]:
                print(f"  {line}")
            if len(output.split('\n')) > 20:
                print(f"  {DIM}... (output truncated){RESET}")

        # Show appropriate status
        if is_fallback:
            status = "⚠ Skipped (no project)"
        else:
            status = "✓ Success" if success else "✗ Failed"
        print(f"\n  {BOLD}{status}{RESET}\n")
        return success and not is_fallback

    # Check dual techs
    if tech_id in DUAL_TECHS:
        tech = DUAL_TECHS[tech_id]
        print(f"\n  {tech['element']} {BOLD}{tech['name']}{RESET}")
        print(f"  {DIM}Dual Tech: {' + '.join(tech['characters'])}{RESET}")
        print(f"  {DIM}{tech['description']}{RESET}")
        print(f"  {'═' * 50}")

        all_success = True
        for sub_tech_id in tech["techs"]:
            if not execute_tech(sub_tech_id, dry_run, verbose):
                all_success = False
                if not dry_run:
                    print(f"  {BOLD}✗ Dual Tech failed at {sub_tech_id}{RESET}\n")
                    return False

        print(f"  {'═' * 50}")
        print(f"  {BOLD}✓ Dual Tech Complete!{RESET}\n")
        return all_success

    # Check triple techs
    if tech_id in TRIPLE_TECHS:
        tech = TRIPLE_TECHS[tech_id]
        command = get_command_for_project(tech, project_type)

        print(f"\n  {tech['element']} {BOLD}{tech['name']}{RESET} ⭐ TRIPLE TECH ⭐")
        print(f"  {DIM}Characters: {' + '.join(tech['characters'])}{RESET}")
        print(f"  {DIM}{tech['description']}{RESET}")
        print(f"  {'═' * 50}")

        if verbose or dry_run:
            print(f"  {DIM}Command: {command}{RESET}")

        success, output = run_command(command, dry_run)

        if output and (verbose or not success):
            for line in output.split('\n')[:30]:
                print(f"  {line}")
            if len(output.split('\n')) > 30:
                print(f"  {DIM}... (output truncated){RESET}")

        print(f"  {'═' * 50}")
        status = "✓ TRIPLE TECH COMPLETE!" if success else "✗ Triple Tech Failed"
        print(f"  {BOLD}{status}{RESET}\n")
        return success

    # Check custom techs
    custom_techs = load_custom_techs()
    if tech_id in custom_techs:
        tech = custom_techs[tech_id]
        command = tech.get("command", "echo 'No command'")

        print(f"\n  🎮 {BOLD}{tech.get('name', tech_id)}{RESET} (Custom Tech)")
        print(f"  {DIM}{tech.get('description', 'Custom workflow')}{RESET}")
        print(f"  {'─' * 50}")

        if verbose or dry_run:
            print(f"  {DIM}Command: {command}{RESET}")

        success, output = run_command(command, dry_run)

        if output and (verbose or not success):
            for line in output.split('\n')[:20]:
                print(f"  {line}")

        status = "✓ Success" if success else "✗ Failed"
        print(f"\n  {BOLD}{status}{RESET}\n")
        return success

    print(f"\n  {BOLD}Error:{RESET} Unknown tech '{tech_id}'")
    print(f"  {DIM}Use 'tech list' to see available techs.{RESET}\n")
    return False


# ============================================================
# Custom Techs
# ============================================================

def load_custom_techs() -> Dict[str, Any]:
    """Load custom techs from storage."""
    if not CUSTOM_TECHS_FILE.exists():
        return {}
    try:
        with open(CUSTOM_TECHS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_custom_techs(techs: Dict[str, Any]) -> None:
    """Save custom techs to storage."""
    CUSTOM_TECHS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CUSTOM_TECHS_FILE, "w") as f:
        json.dump(techs, f, indent=2)


def add_custom_tech(name: str, command: str, description: str = "") -> None:
    """Add a custom tech."""
    techs = load_custom_techs()
    techs[name] = {
        "name": name,
        "command": command,
        "description": description or f"Custom: {command[:30]}...",
        "created": datetime.now().isoformat()
    }
    save_custom_techs(techs)
    print(f"\n  {BOLD}✓ Custom tech '{name}' created!{RESET}")
    print(f"  {DIM}Run with: tech {name}{RESET}\n")


def remove_custom_tech(name: str) -> None:
    """Remove a custom tech."""
    techs = load_custom_techs()
    if name in techs:
        del techs[name]
        save_custom_techs(techs)
        print(f"\n  {BOLD}✓ Custom tech '{name}' removed.{RESET}\n")
    else:
        print(f"\n  {BOLD}Error:{RESET} Custom tech '{name}' not found.\n")


# ============================================================
# List Commands
# ============================================================

def list_techs(category: Optional[str] = None) -> None:
    """List available techs."""
    project_type = detect_project_type()

    print(f"\n  {BOLD}⚔️ AVAILABLE TECHS{RESET}")
    print(f"  {DIM}Project type: {project_type}{RESET}")
    print(f"  {'═' * 55}\n")

    # Single Techs
    if not category or category == "single":
        print(f"  {BOLD}SINGLE TECHS{RESET} (Individual abilities)\n")

        # Group by character
        by_character: Dict[str, List] = {}
        for tech_id, tech in SINGLE_TECHS.items():
            char = tech["character"]
            if char not in by_character:
                by_character[char] = []
            by_character[char].append((tech_id, tech))

        for char, techs in by_character.items():
            print(f"  {DIM}── {char} ──{RESET}")
            for tech_id, tech in techs:
                print(f"  {tech['element']} {BOLD}{tech_id:12}{RESET} {tech['name']:15} {DIM}{tech['description']}{RESET}")
            print()

    # Dual Techs
    if not category or category == "dual":
        print(f"  {BOLD}DUAL TECHS{RESET} (Two-character combos)\n")
        for tech_id, tech in DUAL_TECHS.items():
            chars = " + ".join(tech["characters"])
            print(f"  {tech['element']} {BOLD}{tech_id:15}{RESET} {tech['name']:15} {DIM}{tech['description']}{RESET}")
            print(f"     {DIM}({chars}){RESET}")
        print()

    # Triple Techs
    if not category or category == "triple":
        print(f"  {BOLD}⭐ TRIPLE TECHS{RESET} (Ultimate abilities)\n")
        for tech_id, tech in TRIPLE_TECHS.items():
            chars = " + ".join(tech["characters"])
            print(f"  {tech['element']} {BOLD}{tech_id:15}{RESET} {tech['name']:15} {DIM}{tech['description']}{RESET}")
            print(f"     {DIM}({chars}){RESET}")
        print()

    # Custom Techs
    custom = load_custom_techs()
    if custom and (not category or category == "custom"):
        print(f"  {BOLD}🎮 CUSTOM TECHS{RESET}\n")
        for tech_id, tech in custom.items():
            print(f"  🎮 {BOLD}{tech_id:15}{RESET} {DIM}{tech.get('description', '')}{RESET}")
        print()

    print(f"  {'─' * 55}")
    print(f"  {DIM}Usage: tech <name>           - Execute a tech{RESET}")
    print(f"  {DIM}       tech <name> --dry-run - Preview without running{RESET}")
    print(f"  {DIM}       tech custom <name> \"<command>\" - Create custom{RESET}\n")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Techs - Workflow automation with Chrono Trigger theming",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Examples:{RESET}
  tech list                         # Show all techs
  tech fire                         # Build project (Lucca's fire)
  tech ice                          # Run tests (Marle's ice)
  tech antipode                     # Build + Test (Dual Tech)
  tech luminaire                    # Full deploy (Triple Tech)
  tech fire --dry-run               # Preview without running
  tech custom my-flow "npm run build && npm test"

{BOLD}Popular Techs:{RESET}
  ⚡ slash      - Lint
  🔥 fire       - Build
  ❄️  ice        - Test
  💚 cure       - Auto-fix
  🔥❄️ antipode  - Build + Test
  ⭐ luminaire  - Build + Test + Deploy
        """
    )

    parser.add_argument(
        "tech",
        nargs="?",
        help="Tech to execute (or 'list' to show all)"
    )

    parser.add_argument(
        "args",
        nargs="*",
        help="Additional arguments"
    )

    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Preview commands without executing"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )

    parser.add_argument(
        "--category", "-c",
        choices=["single", "dual", "triple", "custom"],
        help="Filter list by category"
    )

    args = parser.parse_args()

    if not args.tech or args.tech == "list":
        list_techs(args.category)
        return

    if args.tech == "custom":
        if len(args.args) < 2:
            print(f"\n  {BOLD}Error:{RESET} Custom tech requires name and command.")
            print(f"  {DIM}Usage: tech custom my-flow \"npm run build && npm test\"{RESET}\n")
            return
        name = args.args[0]
        command = args.args[1]
        description = args.args[2] if len(args.args) > 2 else ""
        add_custom_tech(name, command, description)
        return

    if args.tech == "remove":
        if not args.args:
            print(f"\n  {BOLD}Error:{RESET} Please specify tech to remove.")
            return
        remove_custom_tech(args.args[0])
        return

    # Execute the tech
    execute_tech(args.tech, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
