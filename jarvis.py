#!/usr/bin/env python3
"""
J.A.R.V.I.S. - Just A Rather Very Intelligent System
Launcher with optional auto-restart on source changes.
"""

import os
import signal
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL 1.1.1+.*",
)

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

# Use the user's default Hugging Face cache unless explicitly overridden.
# This avoids duplicate caches and unnecessary re-download attempts.
os.environ.setdefault("PYTHONWARNINGS", "ignore:urllib3 v2 only supports OpenSSL 1.1.1+")

WATCH_EXTENSIONS = {".py", ".json", ".md", ".env"}
WATCH_FILENAMES = {"jarvis.py", ".env"}
IGNORED_DIRS = {".git", ".cache", "__pycache__", ".venv", "venv"}
IGNORED_FILES = {
    str(SRC_DIR / "memory.json"),
    str(SRC_DIR / "tasks.json"),
    str(SRC_DIR / "reminders.json"),
}


def should_watch(path: Path) -> bool:
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    if str(path) in IGNORED_FILES:
        return False
    return path.suffix in WATCH_EXTENSIONS or path.name in WATCH_FILENAMES


def build_snapshot() -> dict:
    snapshot = {}
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or not should_watch(path):
            continue
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def start_child() -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    env.setdefault("PYTHONWARNINGS", "ignore:urllib3 v2 only supports OpenSSL 1.1.1+")
    return subprocess.Popen([sys.executable, "jarvis_intro.py"], cwd=str(SRC_DIR), env=env)


def stop_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=8)
    except subprocess.TimeoutExpired:
        child.kill()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def run_with_watch() -> None:
    print("[launcher] Watch mode enabled. Editing files will auto-restart Jarvis.")
    print("[launcher] Press Ctrl+C to stop.")
    snapshot = build_snapshot()
    child = start_child()

    try:
        while True:
            time.sleep(1.0)
            if child.poll() is not None:
                print(f"[launcher] Jarvis exited with code {child.returncode}. Restarting...")
                child = start_child()
                snapshot = build_snapshot()
                continue

            current = build_snapshot()
            if current != snapshot:
                print("[launcher] File change detected. Restarting Jarvis...")
                stop_child(child)
                child = start_child()
                snapshot = current
    except KeyboardInterrupt:
        print("\n[launcher] Shutting down...")
        stop_child(child)


def run_once() -> None:
    sys.path.insert(0, str(SRC_DIR))
    os.chdir(str(SRC_DIR))
    from jarvis_intro import system_boot

    system_boot()


if __name__ == "__main__":
    if "--no-watch" in sys.argv:
        run_once()
    else:
        run_with_watch()
