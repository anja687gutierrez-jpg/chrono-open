"""
Chrono Configuration
Central configuration for all Chrono components.

Handles migration from legacy ~/.smart-forking to ~/.chrono
"""

from pathlib import Path
import os
import tempfile
import shutil
import json
from typing import Optional, Any


# ============================================================
# Data Directory Configuration
# ============================================================

def get_data_dir() -> Path:
    """
    Get the Chrono data directory.

    Supports migration from legacy ~/.smart-forking to ~/.chrono
    Uses ~/.chrono for new installations.
    """
    new_path = Path.home() / ".chrono"
    old_path = Path.home() / ".smart-forking"

    # If new path exists, use it
    if new_path.exists():
        return new_path

    # If old path exists but new doesn't, use old (pre-migration)
    if old_path.exists():
        return old_path

    # Fresh install: create new path
    new_path.mkdir(parents=True, exist_ok=True)
    return new_path


def migrate_data_dir() -> bool:
    """
    Migrate from ~/.smart-forking to ~/.chrono

    Returns:
        True if migration was performed, False if not needed
    """
    old_path = Path.home() / ".smart-forking"
    new_path = Path.home() / ".chrono"

    if not old_path.exists():
        print("No legacy data to migrate.")
        return False

    if new_path.exists():
        print("New data directory already exists. Skipping migration.")
        return False

    print(f"Migrating data from {old_path} to {new_path}...")

    try:
        # Copy all contents
        shutil.copytree(old_path, new_path)

        # Rename old directory to backup
        backup_path = old_path.with_suffix(".backup")
        old_path.rename(backup_path)

        print(f"Migration complete!")
        print(f"Old data backed up to: {backup_path}")
        print(f"New data directory: {new_path}")

        return True

    except Exception as e:
        print(f"Migration failed: {e}")
        return False


# ============================================================
# Path Helpers
# ============================================================

def get_chroma_path() -> Path:
    """Get path to ChromaDB storage."""
    return get_data_dir() / "chroma"


def get_summaries_path() -> Path:
    """Get path to session summaries file."""
    return get_data_dir() / "summaries.json"


def get_gates_path() -> Path:
    """Get path to Time Gates file."""
    return get_data_dir() / "gates.json"


def get_techs_path() -> Path:
    """Get path to custom Techs file."""
    return get_data_dir() / "techs.json"


def get_indexed_sessions_path() -> Path:
    """Get path to indexed sessions tracking file."""
    return get_data_dir() / "indexed_sessions.json"


def get_pinned_projects_path() -> Path:
    """Get path to pinned projects file."""
    return get_data_dir() / "pinned_projects.json"


# ============================================================
# Safe File I/O
# ============================================================

def atomic_write_json(path: Path, data: Any, **kwargs) -> None:
    """
    Atomically write JSON data to a file.

    Writes to a temporary file in the same directory first, then renames
    to the target path. This prevents half-written/corrupt files if the
    process is killed mid-write (e.g., terminal close during auto-index).

    os.rename() is atomic on POSIX systems when source and destination
    are on the same filesystem — which is guaranteed because we create
    the temp file in the same directory.

    Args:
        path: Target file path
        data: JSON-serializable data
        **kwargs: Extra keyword arguments passed to json.dump
                  (e.g., indent=2, default=str)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Default to pretty-printed JSON
    kwargs.setdefault("indent", 2)

    # Write to temp file in the same directory (ensures same filesystem)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".tmp_",
        suffix=".json"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        # Atomic rename (POSIX guarantees this won't leave a partial file)
        os.rename(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any failure (including KeyboardInterrupt)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def safe_load_json(path: Path, default: Any = None) -> Any:
    """
    Safely load a JSON file, returning a default on any error.

    Handles: missing file, empty file, corrupted JSON, permission errors.
    Prints a warning if the file exists but can't be parsed.

    Args:
        path: Path to JSON file
        default: Value to return on failure (default: None)

    Returns:
        Parsed JSON data, or default on any error
    """
    path = Path(path)
    if not path.exists():
        return default

    try:
        with open(path) as f:
            content = f.read()
            if not content.strip():
                return default
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"  ⚠ Warning: {path.name} is corrupted — treating as empty")
        return default
    except (IOError, OSError) as e:
        print(f"  ⚠ Warning: Cannot read {path.name}: {e}")
        return default


# ============================================================
# Index Lock File
# ============================================================

class IndexLock:
    """
    File-based lock to prevent concurrent indexing.

    Uses a PID-based lock file (~/.chrono/.index.lock) to detect
    if another indexer is already running. Stale locks (from crashed
    processes) are automatically cleaned up by checking if the PID
    is still alive.
    """

    def __init__(self):
        self.lock_path = get_data_dir() / ".index.lock"
        self._held = False

    def _is_pid_alive(self, pid: int) -> bool:
        """Check if a process with the given PID is still running."""
        try:
            os.kill(pid, 0)  # Signal 0 = check existence, don't kill
            return True
        except ProcessLookupError:
            return False  # Process doesn't exist
        except PermissionError:
            return True  # Process exists but we can't signal it

    def acquire(self) -> bool:
        """
        Attempt to acquire the index lock.

        Returns:
            True if lock acquired, False if another indexer is running.
        """
        if self.lock_path.exists():
            try:
                content = self.lock_path.read_text().strip()
                old_pid = int(content)
                if self._is_pid_alive(old_pid):
                    return False  # Another indexer is genuinely running
                # Stale lock — process is dead, clean up
            except (ValueError, IOError, OSError):
                pass  # Corrupt lock file, remove it
            try:
                self.lock_path.unlink()
            except OSError:
                pass

        # Write our PID
        try:
            self.lock_path.write_text(str(os.getpid()))
            self._held = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the index lock."""
        if self._held:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
            self._held = False

    def holder_pid(self) -> int:
        """Get the PID of the current lock holder, or 0 if no lock."""
        if not self.lock_path.exists():
            return 0
        try:
            return int(self.lock_path.read_text().strip())
        except (ValueError, IOError, OSError):
            return 0

    def __enter__(self):
        if not self.acquire():
            holder = self.holder_pid()
            raise RuntimeError(
                f"Another indexer is running (PID {holder}). "
                f"Wait for it to finish or remove {self.lock_path}"
            )
        return self

    def __exit__(self, *args):
        self.release()


# ============================================================
# Custom Error Types
# ============================================================

class ChronoError(Exception):
    """Base exception for all Chrono errors."""
    pass


class OllamaError(ChronoError):
    """Ollama is not running or unreachable."""
    pass


class IndexError_(ChronoError):
    """Indexing failure (named with underscore to avoid shadowing builtin)."""
    pass


class ParseError(ChronoError):
    """Session file parsing failure."""
    pass


class DatabaseError(ChronoError):
    """ChromaDB corruption or access failure."""
    pass


# ============================================================
# Version Info
# ============================================================

VERSION = "2.0.0"
NAME = "Chrono"
DESCRIPTION = "Time-Travel Through Your Code History"


# ============================================================
# CLI for testing/migration
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_data_dir()
    else:
        print(f"{NAME} v{VERSION}")
        print(f"Data directory: {get_data_dir()}")
        print(f"\nPaths:")
        print(f"  ChromaDB: {get_chroma_path()}")
        print(f"  Summaries: {get_summaries_path()}")
        print(f"  Gates: {get_gates_path()}")
        print(f"  Techs: {get_techs_path()}")
        print(f"\nRun 'python chrono_config.py migrate' to migrate from legacy path.")
