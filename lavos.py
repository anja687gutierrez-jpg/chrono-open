#!/usr/bin/env python3
"""
Lavos Detection - Project Health Monitoring for Project Epoch

In Chrono Trigger, Lavos is a parasitic alien that has been dormant inside
Earth for 65 million years. In 1999 AD (the "Day of Lavos"), it emerges and
destroys civilization. The heroes travel to the ruined Future (2300 AD),
witness the devastation, and go back to prevent it.

In Project Epoch, Lavos Detection finds the "dormant threats" in your codebase:
- Security vulnerabilities (the parasites)
- Outdated dependencies (ticking time bombs)
- Code quality issues (the corruption spreading)
- Configuration problems (weak defenses)

Usage:
    lavos scan                  # Full project health scan
    lavos quick                 # Fast critical-issues-only scan
    lavos deps                  # Dependency health check
    lavos security              # Security-focused scan
    lavos report                # Generate detailed report
"""

import subprocess
import sys
import os
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from chrono_utils import FUTURE, RESET, BOLD, DIM, RED, WARNING, MAGENTA, CYAN, separator


# ============================================================
# Issue Severity (Lavos Power Levels)
# ============================================================

@dataclass
class Issue:
    """A detected issue (dormant threat)."""
    category: str  # security, deps, quality, config, git
    severity: str  # critical, high, medium, low
    title: str
    description: str
    file: Optional[str] = None
    line: Optional[int] = None
    fix: Optional[str] = None


SEVERITY_COLORS = {
    "critical": RED,
    "high": WARNING,
    "medium": MAGENTA,
    "low": CYAN,
}

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
}

CATEGORY_EMOJI = {
    "security": "🔒",
    "deps": "📦",
    "quality": "✨",
    "config": "⚙️",
    "git": "📂",
}


# ============================================================
# Detection Utilities
# ============================================================

def run_command(command: str, timeout: int = 60) -> Tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def detect_project_type() -> str:
    """Detect the project type based on files present."""
    cwd = Path.cwd()

    if (cwd / "package.json").exists():
        return "npm"
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists() or (cwd / "requirements.txt").exists():
        return "python"
    if (cwd / "Cargo.toml").exists():
        return "rust"
    if (cwd / "go.mod").exists():
        return "go"

    return "unknown"


def is_git_repo() -> bool:
    """Check if current directory is a git repository."""
    success, _ = run_command("git rev-parse --git-dir")
    return success


# ============================================================
# Scanners
# ============================================================

def scan_npm_security() -> List[Issue]:
    """Scan npm project for security vulnerabilities."""
    issues = []

    if not Path("package.json").exists():
        return issues

    # Run npm audit
    success, output = run_command("npm audit --json 2>/dev/null")

    if output:
        try:
            audit_data = json.loads(output)
            vulnerabilities = audit_data.get("vulnerabilities", {})

            for pkg_name, vuln_info in vulnerabilities.items():
                severity = vuln_info.get("severity", "medium")
                via = vuln_info.get("via", [])

                # Get the first vulnerability description
                desc = "Vulnerability detected"
                if via and isinstance(via[0], dict):
                    desc = via[0].get("title", desc)
                elif via and isinstance(via[0], str):
                    desc = f"Dependency of vulnerable package: {via[0]}"

                issues.append(Issue(
                    category="security",
                    severity=severity if severity in SEVERITY_EMOJI else "medium",
                    title=f"Vulnerable package: {pkg_name}",
                    description=desc,
                    fix=f"npm audit fix or update {pkg_name}"
                ))
        except json.JSONDecodeError:
            pass

    return issues


def scan_python_security() -> List[Issue]:
    """Scan Python project for security vulnerabilities."""
    issues = []

    # Check if pip-audit is available
    success, _ = run_command("pip-audit --version")
    if not success:
        # Try safety instead
        success, output = run_command("safety check --json 2>/dev/null")
        if success and output:
            try:
                data = json.loads(output)
                for vuln in data:
                    issues.append(Issue(
                        category="security",
                        severity="high",
                        title=f"Vulnerable package: {vuln.get('package', 'unknown')}",
                        description=vuln.get('advisory', 'Security vulnerability detected'),
                        fix=f"Update to version {vuln.get('fixed_versions', 'latest')}"
                    ))
            except:
                pass
        return issues

    # Run pip-audit
    success, output = run_command("pip-audit --format json 2>/dev/null")
    if output:
        try:
            vulns = json.loads(output)
            for vuln in vulns:
                issues.append(Issue(
                    category="security",
                    severity="high",
                    title=f"Vulnerable package: {vuln.get('name', 'unknown')}",
                    description=vuln.get('description', 'Security vulnerability detected')[:100],
                    fix=f"Update to {vuln.get('fix_versions', ['latest'])[0] if vuln.get('fix_versions') else 'latest'}"
                ))
        except:
            pass

    return issues


def scan_npm_deps() -> List[Issue]:
    """Scan npm dependencies for outdated packages."""
    issues = []

    if not Path("package.json").exists():
        return issues

    # Run npm outdated
    success, output = run_command("npm outdated --json 2>/dev/null")

    if output:
        try:
            outdated = json.loads(output)

            for pkg_name, info in outdated.items():
                current = info.get("current", "?")
                wanted = info.get("wanted", "?")
                latest = info.get("latest", "?")

                # Determine severity based on version gap
                if current != latest:
                    major_diff = False
                    try:
                        current_major = int(current.split('.')[0])
                        latest_major = int(latest.split('.')[0])
                        major_diff = latest_major > current_major
                    except:
                        pass

                    severity = "high" if major_diff else "medium"

                    issues.append(Issue(
                        category="deps",
                        severity=severity,
                        title=f"Outdated: {pkg_name}",
                        description=f"Current: {current} → Latest: {latest}",
                        fix=f"npm update {pkg_name}"
                    ))
        except json.JSONDecodeError:
            pass

    return issues


def scan_python_deps() -> List[Issue]:
    """Scan Python dependencies for outdated packages."""
    issues = []

    # Run pip list --outdated
    success, output = run_command("pip list --outdated --format json 2>/dev/null")

    if success and output:
        try:
            outdated = json.loads(output)

            for pkg in outdated:
                name = pkg.get("name", "unknown")
                current = pkg.get("version", "?")
                latest = pkg.get("latest_version", "?")

                issues.append(Issue(
                    category="deps",
                    severity="medium",
                    title=f"Outdated: {name}",
                    description=f"Current: {current} → Latest: {latest}",
                    fix=f"pip install --upgrade {name}"
                ))
        except:
            pass

    return issues


def scan_code_quality() -> List[Issue]:
    """Scan for code quality issues."""
    issues = []
    project_type = detect_project_type()

    if project_type == "npm":
        # Try to run ESLint
        success, output = run_command("npx eslint . --format json 2>/dev/null", timeout=120)
        if success and output:
            try:
                results = json.loads(output)
                error_count = sum(r.get("errorCount", 0) for r in results)
                warning_count = sum(r.get("warningCount", 0) for r in results)

                if error_count > 0:
                    issues.append(Issue(
                        category="quality",
                        severity="high" if error_count > 10 else "medium",
                        title=f"ESLint: {error_count} errors",
                        description=f"Plus {warning_count} warnings across {len(results)} files",
                        fix="npm run lint:fix"
                    ))
                elif warning_count > 20:
                    issues.append(Issue(
                        category="quality",
                        severity="low",
                        title=f"ESLint: {warning_count} warnings",
                        description=f"No errors, but many warnings to address",
                        fix="npm run lint:fix"
                    ))
            except:
                pass

    elif project_type == "python":
        # Try to run ruff
        success, output = run_command("ruff check . --output-format json 2>/dev/null", timeout=120)
        if success and output:
            try:
                results = json.loads(output)
                if len(results) > 0:
                    issues.append(Issue(
                        category="quality",
                        severity="medium" if len(results) > 20 else "low",
                        title=f"Ruff: {len(results)} issues",
                        description=f"Code quality issues detected",
                        fix="ruff check --fix ."
                    ))
            except:
                pass

    return issues


def scan_config() -> List[Issue]:
    """Scan for configuration issues."""
    issues = []
    cwd = Path.cwd()

    # Check for .env files committed
    if (cwd / ".env").exists():
        # Check if it's in .gitignore
        gitignore = cwd / ".gitignore"
        env_ignored = False
        if gitignore.exists():
            content = gitignore.read_text()
            env_ignored = ".env" in content

        if not env_ignored:
            issues.append(Issue(
                category="config",
                severity="critical",
                title=".env file may be committed",
                description=".env file exists but may not be in .gitignore",
                fix="Add '.env' to .gitignore"
            ))

    # Check for common sensitive files
    sensitive_files = [
        ("credentials.json", "Google credentials file"),
        ("serviceAccountKey.json", "Firebase service account"),
        (".npmrc", "NPM config (may contain tokens)"),
        ("id_rsa", "SSH private key"),
        ("*.pem", "Private key file"),
    ]

    for pattern, desc in sensitive_files:
        matches = list(cwd.glob(pattern))
        for match in matches:
            if match.is_file():
                issues.append(Issue(
                    category="config",
                    severity="critical",
                    title=f"Sensitive file: {match.name}",
                    description=desc,
                    file=str(match),
                    fix=f"Add to .gitignore and remove from repo"
                ))

    # Check for TODO/FIXME comments (potential tech debt)
    success, output = run_command("grep -r 'TODO\\|FIXME\\|HACK\\|XXX' --include='*.js' --include='*.ts' --include='*.py' --include='*.jsx' --include='*.tsx' . 2>/dev/null | head -20")
    if success and output:
        count = len(output.strip().split('\n'))
        if count >= 10:
            issues.append(Issue(
                category="quality",
                severity="low",
                title=f"Technical debt: {count}+ TODO/FIXME comments",
                description="Code contains unresolved TODO/FIXME/HACK markers",
                fix="Address or track these items"
            ))

    return issues


def scan_git() -> List[Issue]:
    """Scan for git-related issues."""
    issues = []

    if not is_git_repo():
        return issues

    # Check for large files
    success, output = run_command("git ls-files | xargs -I{} du -b {} 2>/dev/null | sort -rn | head -5")
    if success and output:
        for line in output.strip().split('\n'):
            if line:
                try:
                    size, filename = line.split(None, 1)
                    size_mb = int(size) / (1024 * 1024)
                    if size_mb > 10:  # Files larger than 10MB
                        issues.append(Issue(
                            category="git",
                            severity="medium",
                            title=f"Large file: {filename}",
                            description=f"File is {size_mb:.1f}MB - consider using Git LFS",
                            file=filename,
                            fix="Consider using Git LFS for large files"
                        ))
                except:
                    pass

    # Check for untracked important files
    success, output = run_command("git status --porcelain 2>/dev/null")
    if success and output:
        untracked = [l[3:] for l in output.split('\n') if l.startswith('??')]
        important_untracked = [f for f in untracked if f.endswith(('.js', '.ts', '.py', '.json'))]
        if len(important_untracked) > 10:
            issues.append(Issue(
                category="git",
                severity="low",
                title=f"{len(important_untracked)} untracked source files",
                description="Many source files are not tracked by git",
                fix="git add <files> or update .gitignore"
            ))

    return issues


# ============================================================
# Main Scan Functions
# ============================================================

def run_full_scan(verbose: bool = False) -> List[Issue]:
    """Run all scanners."""
    all_issues = []
    project_type = detect_project_type()

    print(f"\n  {FUTURE.emoji} {BOLD}LAVOS DETECTION - Scanning for Dormant Threats{RESET}")
    print(f"  {DIM}Project type: {project_type}{RESET}")
    print(separator("═", 2))
    print()

    scanners = [
        ("Security vulnerabilities", scan_npm_security if project_type == "npm" else scan_python_security),
        ("Outdated dependencies", scan_npm_deps if project_type == "npm" else scan_python_deps),
        ("Code quality", scan_code_quality),
        ("Configuration", scan_config),
        ("Git health", scan_git),
    ]

    for name, scanner in scanners:
        print(f"  {DIM}Scanning: {name}...{RESET}", end="", flush=True)
        try:
            issues = scanner()
            all_issues.extend(issues)
            count = len(issues)
            if count > 0:
                print(f" {SEVERITY_COLORS['high']}{count} issues{RESET}")
            else:
                print(f" {BOLD}✓{RESET}")
        except Exception as e:
            print(f" {DIM}(skipped){RESET}")
            if verbose:
                print(f"    {DIM}Error: {e}{RESET}")

    return all_issues


def run_quick_scan() -> List[Issue]:
    """Run quick scan for critical issues only."""
    all_issues = []
    project_type = detect_project_type()

    print(f"\n  {FUTURE.emoji} {BOLD}LAVOS QUICK SCAN - Critical Threats Only{RESET}")
    print(separator("═", 2))
    print()

    # Only run security and config scans
    print(f"  {DIM}Scanning security...{RESET}", end="", flush=True)
    if project_type == "npm":
        all_issues.extend(scan_npm_security())
    else:
        all_issues.extend(scan_python_security())
    print(f" done")

    print(f"  {DIM}Scanning config...{RESET}", end="", flush=True)
    all_issues.extend(scan_config())
    print(f" done")

    # Filter to critical/high only
    all_issues = [i for i in all_issues if i.severity in ("critical", "high")]

    return all_issues


def display_results(issues: List[Issue]) -> None:
    """Display scan results."""
    print("\n" + separator("═", 2))

    if not issues:
        print(f"\n  {BOLD}✓ No threats detected!{RESET}")
        print(f"  {DIM}Your timeline is safe... for now.{RESET}\n")
        return

    # Group by severity
    by_severity = {"critical": [], "high": [], "medium": [], "low": []}
    for issue in issues:
        by_severity[issue.severity].append(issue)

    # Count totals
    total = len(issues)
    critical = len(by_severity["critical"])
    high = len(by_severity["high"])

    # Threat level assessment
    if critical > 0:
        threat_level = "CRITICAL - Day of Lavos imminent!"
        threat_color = SEVERITY_COLORS["critical"]
    elif high > 5:
        threat_level = "HIGH - Lavos stirs beneath the surface"
        threat_color = SEVERITY_COLORS["high"]
    elif high > 0:
        threat_level = "ELEVATED - Minor disturbances detected"
        threat_color = SEVERITY_COLORS["medium"]
    else:
        threat_level = "LOW - Timeline relatively stable"
        threat_color = SEVERITY_COLORS["low"]

    print(f"\n  {threat_color}{BOLD}⚠ THREAT LEVEL: {threat_level}{RESET}\n")

    # Display issues by severity
    for severity in ["critical", "high", "medium", "low"]:
        severity_issues = by_severity[severity]
        if not severity_issues:
            continue

        color = SEVERITY_COLORS[severity]
        emoji = SEVERITY_EMOJI[severity]

        print(f"  {color}{emoji} {severity.upper()} ({len(severity_issues)}){RESET}")
        print(separator("─", 2, color))

        for issue in severity_issues[:10]:  # Limit display
            cat_emoji = CATEGORY_EMOJI.get(issue.category, "•")
            print(f"  {cat_emoji} {BOLD}{issue.title}{RESET}")
            print(f"    {DIM}{issue.description}{RESET}")
            if issue.fix:
                print(f"    {DIM}Fix: {issue.fix}{RESET}")

        if len(severity_issues) > 10:
            print(f"  {DIM}... and {len(severity_issues) - 10} more{RESET}")
        print()

    # Summary
    print(separator("─", 2))
    print(f"  {BOLD}SUMMARY:{RESET} {total} threats detected")
    print(f"  {SEVERITY_EMOJI['critical']} Critical: {critical}  {SEVERITY_EMOJI['high']} High: {high}  {SEVERITY_EMOJI['medium']} Medium: {len(by_severity['medium'])}  {SEVERITY_EMOJI['low']} Low: {len(by_severity['low'])}")

    if critical > 0:
        print(f"\n  {SEVERITY_COLORS['critical']}{BOLD}⚡ Address critical issues immediately!{RESET}")
    print()


def generate_report(issues: List[Issue]) -> None:
    """Generate a detailed report."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = Path.cwd() / f"lavos_report_{timestamp}.json"

    report = {
        "generated": datetime.now().isoformat(),
        "project": Path.cwd().name,
        "project_type": detect_project_type(),
        "summary": {
            "total": len(issues),
            "critical": len([i for i in issues if i.severity == "critical"]),
            "high": len([i for i in issues if i.severity == "high"]),
            "medium": len([i for i in issues if i.severity == "medium"]),
            "low": len([i for i in issues if i.severity == "low"]),
        },
        "issues": [
            {
                "category": i.category,
                "severity": i.severity,
                "title": i.title,
                "description": i.description,
                "file": i.file,
                "line": i.line,
                "fix": i.fix,
            }
            for i in issues
        ]
    }

    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n  {BOLD}📋 Report saved:{RESET} {report_file}\n")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Lavos Detection - Find dormant threats in your codebase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Scan Types:{RESET}
  scan      Full project health scan (default)
  quick     Critical issues only (faster)
  deps      Dependency health check
  security  Security-focused scan

{BOLD}Threat Levels:{RESET}
  🔴 CRITICAL  - Day of Lavos imminent! Fix immediately
  🟠 HIGH      - Lavos stirs... address soon
  🟡 MEDIUM    - Minor disturbances detected
  🔵 LOW       - Timeline relatively stable

{BOLD}Examples:{RESET}
  lavos                    # Full scan
  lavos quick              # Critical issues only
  lavos scan --report      # Full scan + save report
  lavos deps               # Check dependencies only
        """
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="scan",
        choices=["scan", "quick", "deps", "security", "report"],
        help="Scan type (default: scan)"
    )

    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="Generate JSON report"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    issues = []

    if args.command == "scan":
        issues = run_full_scan(args.verbose)
    elif args.command == "quick":
        issues = run_quick_scan()
    elif args.command == "deps":
        print(f"\n  {FUTURE.emoji} {BOLD}LAVOS - Dependency Scan{RESET}")
        print(separator("═", 2))
        print()
        project_type = detect_project_type()
        if project_type == "npm":
            issues = scan_npm_deps()
        else:
            issues = scan_python_deps()
    elif args.command == "security":
        print(f"\n  {FUTURE.emoji} {BOLD}LAVOS - Security Scan{RESET}")
        print(separator("═", 2))
        print()
        project_type = detect_project_type()
        if project_type == "npm":
            issues = scan_npm_security()
        else:
            issues = scan_python_security()
        issues.extend(scan_config())
    elif args.command == "report":
        issues = run_full_scan(args.verbose)
        generate_report(issues)

    display_results(issues)

    if args.report and args.command != "report":
        generate_report(issues)

    # Exit with error code if critical issues found
    critical_count = len([i for i in issues if i.severity == "critical"])
    if critical_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
