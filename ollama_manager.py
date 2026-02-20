"""
Ollama lifecycle manager for Chrono.

Auto-starts Ollama when needed for embeddings/summaries, and stops it
when Chrono exits (only if we started it ourselves).
"""

import subprocess
import time
import urllib.request

# Track whether this process started Ollama
_we_started_it = False

OLLAMA_URL = "http://localhost:11434/api/tags"
STARTUP_TIMEOUT = 15  # seconds


def is_running() -> bool:
    """Check if Ollama is responding on localhost:11434."""
    try:
        req = urllib.request.Request(OLLAMA_URL, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def start() -> None:
    """Start Ollama serve as a detached background process.

    Raises RuntimeError if Ollama doesn't come up within STARTUP_TIMEOUT.
    """
    global _we_started_it

    # Launch detached — stdout/stderr to /dev/null
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for health check
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_running():
            _we_started_it = True
            return
        time.sleep(0.5)

    raise RuntimeError(
        f"Ollama did not start within {STARTUP_TIMEOUT}s. "
        "Is it installed? Try running 'ollama serve' manually."
    )


def ensure_running() -> None:
    """Start Ollama if it's not already running."""
    if is_running():
        return
    print("  Starting Ollama...")
    start()
    print("  Ollama ready.")


def stop() -> None:
    """Stop Ollama if we started it this session."""
    if not _we_started_it:
        return
    try:
        subprocess.run(
            ["pkill", "-f", "ollama serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
