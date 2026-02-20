#!/usr/bin/env python3
"""
Prefetch Kokoro model artifacts into the local Hugging Face cache.
Run once before launching Jarvis to eliminate first-use download latency.
"""

import os
import time
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO_ID = "hexgrad/Kokoro-82M"
FILES = [
    "config.json",
    "kokoro-v1_0.pth",
    "voices/bm_lewis.pt",
]


def main():
    project_root = Path(__file__).resolve().parents[1]
    hf_home = Path(os.getenv("HF_HOME", project_root / ".cache" / "huggingface"))
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(hf_home)

    print(f"Using HF cache: {hf_home}")
    print(f"Repo: {REPO_ID}")

    for filename in FILES:
        print(f"\nDownloading: {filename}")
        success = False
        for attempt in range(1, 9):
            try:
                local_path = hf_hub_download(
                    repo_id=REPO_ID,
                    filename=filename,
                    cache_dir=str(hf_home),
                )
                print(f"Cached at: {local_path}")
                success = True
                break
            except Exception as exc:
                wait_s = min(2 ** attempt, 20)
                print(f"Attempt {attempt}/8 failed: {exc}")
                if attempt < 8:
                    print(f"Retrying in {wait_s}s...")
                    time.sleep(wait_s)
        if not success:
            raise SystemExit(f"Failed to download required file: {filename}")

    print("\nKokoro prefetch complete. You can now run Jarvis with warm cache.")


if __name__ == "__main__":
    main()
