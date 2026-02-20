#!/usr/bin/env python3
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import jarvis_calendar


def main():
    cfg = jarvis_calendar.load_calendar_config()
    cred = cfg.get("credentials_file", "credentials.json")
    if not os.path.isabs(cred):
        cred = os.path.join(SRC, cred)

    if not os.path.exists(cred):
        print("Google Calendar credentials file is missing.")
        print(f"Expected at: {cred}")
        print("Create OAuth Desktop credentials in Google Cloud and place credentials.json there.")
        return 1

    result = jarvis_calendar.connect_calendar()
    print(result.get("message", "Done."))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
