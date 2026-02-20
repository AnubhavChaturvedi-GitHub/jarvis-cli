"""
Jarvis Tools - Tool Calling System for J.A.R.V.I.S.

Provides system control tools that work reliably on macOS:
- Website opening (webbrowser module)
- Website closing (browser-specific AppleScript) 
- App launching (open -a command)
- File search (mdfind / Spotlight)
- Folder creation (mkdir)
- System info (pmset, df, etc.)
"""

import webbrowser
import subprocess
import platform
import os
import json
import time
import shutil
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path

# Try to import calendar module
try:
    import jarvis_calendar
    CALENDAR_AVAILABLE = True
except ImportError:
    CALENDAR_AVAILABLE = False


# ===== STATE =====
opened_tabs = []
TASKS_FILE = os.path.join(os.path.dirname(__file__), "tasks.json")
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")
REMINDERS_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")


def _run_osascript(script: str, *args: str, timeout: int = 5) -> subprocess.CompletedProcess:
    """Execute osascript safely with argv arguments (no string interpolation)."""
    return subprocess.run(
        ['osascript', '-e', script, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _app_process_candidates(*names: str) -> List[str]:
    """Return likely process name patterns for an app."""
    candidates = set()
    for name in names:
        if not name:
            continue
        value = str(name).strip()
        if not value:
            continue
        candidates.add(value)
        compact = value.replace(" ", "")
        if compact:
            candidates.add(compact)
        for token in value.split():
            if len(token) >= 3:
                candidates.add(token)
    return sorted(candidates, key=len, reverse=True)


def _is_app_running(*names: str) -> bool:
    """Best-effort app running check using process match patterns."""
    for pattern in _app_process_candidates(*names):
        try:
            result = subprocess.run(
                ["pgrep", "-if", pattern],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except Exception:
            continue
    return False

# ===== WEBSITE MAP =====
WEBSITE_MAP = {
    "youtube": "https://youtube.com",
    "instagram": "https://instagram.com",
    "facebook": "https://facebook.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "reddit": "https://reddit.com",
    "github": "https://github.com",
    "gmail": "https://gmail.com",
    "google": "https://google.com",
    "linkedin": "https://linkedin.com",
    "netflix": "https://netflix.com",
    "spotify": "https://spotify.com",
    "amazon": "https://amazon.com",
    "whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "chat gbt": "https://chatgpt.com", # Common typo
    "notion": "https://notion.so",
    "figma": "https://figma.com",
    "pinterest": "https://pinterest.com",
    "pin": "https://pinterest.com",
}

# ===== APP ALIASES =====
APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "finder": "Finder",
    "safari": "Safari",
    "notes": "Notes",
    "calculator": "Calculator",
    "terminal": "Terminal",
    "spotify": "Spotify",
    "slack": "Slack",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "messages": "Messages",
    "mail": "Mail",
    "music": "Music",
    "photos": "Photos",
    "preview": "Preview",
    "pages": "Pages",
    "numbers": "Numbers",
    "keynote": "Keynote",
    "xcode": "Xcode",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "brave": "Brave Browser",
    "firefox": "Firefox",
    "arc": "Arc",
    "notion": "Notion",
    "figma": "Figma",
    "zoom": "zoom.us",
    "teams": "Microsoft Teams",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "calendar": "Calendar",
    "reminders": "Reminders",
    "maps": "Maps",
    "weather": "Weather",
    "settings": "System Settings",
    "system preferences": "System Settings",
    "system settings": "System Settings",
    "activity monitor": "Activity Monitor",
    "app store": "App Store",
    "capcut": "CapCut",
    "cap cut": "CapCut",
}

# ===== PATH SHORTCUTS =====
PATH_SHORTCUTS = {
    "desktop": os.path.expanduser("~/Desktop"),
    "downloads": os.path.expanduser("~/Downloads"),
    "documents": os.path.expanduser("~/Documents"),
    "home": os.path.expanduser("~"),
    "pictures": os.path.expanduser("~/Pictures"),
    "movies": os.path.expanduser("~/Movies"),
    "music": os.path.expanduser("~/Music"),
}


def _resolve_location_path(location: str, default: str = "desktop") -> str:
    """Resolve user-supplied location text into an absolute path."""
    raw = (location or default).strip()
    mapped = PATH_SHORTCUTS.get(raw.lower(), raw)
    mapped = os.path.expanduser(mapped)
    if not os.path.isabs(mapped):
        mapped = os.path.expanduser(f"~/{mapped}")

    if os.path.exists(mapped):
        return mapped

    # Model sometimes hallucinates another username path like /Users/Name/Desktop/Folder.
    desktop_marker = "/Desktop"
    if desktop_marker in mapped:
        tail = mapped.split(desktop_marker, 1)[1].lstrip("/")
        candidate = os.path.join(os.path.expanduser("~/Desktop"), tail)
        if os.path.exists(candidate):
            return candidate

    return mapped


def _find_case_insensitive_dir(parent_dir: str, target_name: str) -> Optional[str]:
    """Find a directory by name under parent_dir using robust fuzzy matching."""
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    target_norm = _norm(target_name)
    if not target_norm:
        return None

    try:
        exact_ci = None
        normalized_eq = None
        contains_match = None

        for entry in os.listdir(parent_dir):
            full = os.path.join(parent_dir, entry)
            if not os.path.isdir(full):
                continue

            entry_lower = entry.lower()
            if entry_lower == target_name.lower():
                exact_ci = full
                break

            entry_norm = _norm(entry)
            if entry_norm == target_norm and normalized_eq is None:
                normalized_eq = full
            elif target_norm in entry_norm or entry_norm in target_norm:
                if contains_match is None:
                    contains_match = full

        if exact_ci:
            return exact_ci
        if normalized_eq:
            return normalized_eq
        if contains_match:
            return contains_match
    except Exception:
        return None
    return None


# ====================================================================
# TOOL DEFINITIONS FOR LLM
# ====================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Opens one or more websites in the default browser. Can handle multiple sites at once. Accepts website names or full URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sites": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of website names or URLs to open, e.g. ['YouTube', 'Instagram']"
                    }
                },
                "required": ["sites"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_website",
            "description": "Closes the most recently opened browser tab or the current active browser tab",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Opens/launches an application on the Mac. Works with any installed app. Examples: Safari, Chrome, Notes, Calculator, Spotify, VS Code, Slack, Discord",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the application to open, e.g. 'Spotify', 'Notes', 'Calculator'"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Closes/quits a running application on the Mac. Use when user says 'close CapCut' or 'quit Spotify' or 'close the app'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the application to close/quit, e.g. 'CapCut', 'Spotify', 'Notes'"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_file",
            "description": "Search for a file or folder anywhere on the computer by name. Returns the file locations. Use when user asks 'where is my file' or 'find this file' or 'locate file'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name or partial name of the file to search for, e.g. 'resume.pdf' or 'project'"
                    },
                    "search_path": {
                        "type": "string",
                        "description": "Optional. Where to search: 'desktop', 'downloads', 'documents', 'home', or a full path"
                    }
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Creates a new folder/directory. Default location is Desktop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Name of the folder to create"
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional. Where to create: 'desktop' (default), 'documents', 'downloads', or full path"
                    }
                },
                "required": ["folder_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_folder",
            "description": "Open a folder in Finder. Use for requests like 'open the Jarvis folder on desktop'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Folder name or path to open, e.g. 'Jarvis'"
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional base location, e.g. 'desktop', 'documents', or full path"
                    }
                },
                "required": ["folder_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Get system information. Use when user asks about battery, time, disk space, running apps, or WiFi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "info_type": {
                        "type": "string",
                        "enum": ["battery", "disk", "time", "running_apps", "wifi", "all"],
                        "description": "What info to get: battery, disk, time, running_apps, wifi, or all"
                    }
                },
                "required": ["info_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_calendar_event",
            "description": "Add an event to Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title/Description of the event, e.g. 'Meeting with Tony'"
                    },
                    "time_str": {
                        "type": "string",
                        "description": "Natural language time, e.g. 'tomorrow at 5pm' or 'next monday at 10am'"
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration in minutes. Default is 60."
                    }
                },
                "required": ["summary", "time_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_contents",
            "description": "List all files and folders inside a directory. Use when user asks 'how many folders are on my desktop' or 'what files are in downloads' or 'show me whats on my desktop' or 'list my desktop'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Which folder to list: 'desktop', 'downloads', 'documents', 'home', or a full path. Default is 'desktop'."
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a new task to the user's to-do list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "The task description, e.g. 'Buy milk' or 'Call mom'"
                    }
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List all tasks in the to-do list.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed and remove it from the list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "The ID of the task to complete (1-based index)"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "Create a reminder with a title/description and a date-time expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What to remind about, e.g. 'submit assignment'"
                    },
                    "time_str": {
                        "type": "string",
                        "description": "Natural language date/time, e.g. 'tomorrow at 6 PM' or 'March 2 at 9:30 AM'"
                    }
                },
                "required": ["description", "time_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List upcoming reminders.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_music_preference",
            "description": "Save the user's music preference/persona (favorite genre, artist, or vibe).",
            "parameters": {
                "type": "object",
                "properties": {
                    "preference": {
                        "type": "string",
                        "description": "Music taste text, e.g. 'lofi and chillhop', 'Arijit Singh', 'EDM gym mix'"
                    }
                },
                "required": ["preference"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Play music using user's saved preference or a requested vibe/artist/song.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional song/artist/genre or vibe, e.g. 'lofi', 'Arijit Singh', 'workout'."
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["spotify", "youtube"],
                        "description": "Where to play music from. Default is spotify."
                    }
                }
            }
        }
    }
]


# ====================================================================
# URL UTILITIES
# ====================================================================

def normalize_url(site: str) -> str:
    """Normalize a website name or URL to a full URL."""
    site_lower = site.lower().strip()
    
    if site_lower.startswith(('http://', 'https://', 'www.')):
        if site_lower.startswith('www.'):
            return f"https://{site_lower}"
        return site
    
    if site_lower in WEBSITE_MAP:
        return WEBSITE_MAP[site_lower]
    
    for key, url in WEBSITE_MAP.items():
        if key in site_lower or site_lower in key:
            return url
    
    if '.' in site:
        return f"https://{site}"
    else:
        return f"https://www.google.com/search?q={site}"


# ====================================================================
# TOOL: OPEN WEBSITE
# ====================================================================

def open_website(sites: list) -> Dict[str, Any]:
    """Open one or more websites in the default browser."""
    try:
        if isinstance(sites, str):
            sites = [sites]
        
        opened_urls = []
        failed_sites = []
        
        for site in sites:
            try:
                url = normalize_url(site)
                webbrowser.open(url)
                opened_tabs.append(url)
                opened_urls.append(url)
                time.sleep(0.3)
            except Exception as e:
                failed_sites.append({"site": site, "error": str(e)})
        
        if opened_urls and not failed_sites:
            if len(opened_urls) == 1:
                return {"success": True, "message": f"Opened {opened_urls[0]}", "urls": opened_urls}
            else:
                return {"success": True, "message": f"Opened {len(opened_urls)} websites", "urls": opened_urls}
        elif opened_urls:
            return {"success": True, "message": f"Opened {len(opened_urls)} sites, {len(failed_sites)} failed"}
        else:
            return {"success": False, "message": "Failed to open websites"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: CLOSE WEBSITE
# Uses 'open -a' to activate browser + AppleScript for Cmd+W
# ====================================================================

def _get_running_browser():
    """Detect which browser is currently running using pgrep."""
    browsers = [
        ("Google Chrome", "Google Chrome"),
        ("Safari", "Safari"),
        ("Brave Browser", "Brave Browser"),
        ("Firefox", "firefox"),
        ("Arc", "Arc"),
    ]
    
    for app_name, process_name in browsers:
        try:
            r = subprocess.run(
                ['pgrep', '-x', process_name],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                return app_name
        except:
            pass
    
    return None


def close_website() -> Dict[str, Any]:
    """Close the most recently opened browser tab."""
    try:
        if not opened_tabs:
            return {"success": False, "message": "No websites have been opened by Jarvis yet"}
        
        last_url = opened_tabs.pop()
        
        if platform.system() != "Darwin":
            opened_tabs.append(last_url)
            return {"success": False, "message": "Only supported on macOS"}
        
        # Step 1: Find running browser
        browser = _get_running_browser()
        if not browser:
            opened_tabs.append(last_url)
            return {"success": False, "message": "No browser is currently running"}
        
        # Step 2: Activate browser using 'open -a' (this WORKS without permissions)
        subprocess.run(['open', '-a', browser], capture_output=True, text=True, timeout=3)
        time.sleep(0.5)  # Wait for browser to come to front
        
        # Step 3: Use Cmd+W via osascript
        # This sends the keystroke to the now-frontmost app
        close_script = 'tell application "System Events" to keystroke "w" using command down'
        result = subprocess.run(
            ['osascript', '-e', close_script],
            capture_output=True, text=True, timeout=3
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "message": f"Closed tab in {browser}",
                "url": last_url,
                "browser": browser
            }
        else:
            # AppleScript failed - need Automation permission
            # Try alternative: use keyboard simulation via Python
            try:
                # Use osascript with specific app targeting (doesn't need System Events)
                if "Chrome" in browser:
                    alt_script = 'tell application "Google Chrome" to close active tab of front window'
                elif "Safari" in browser:
                    alt_script = 'tell application "Safari" to close current tab of front window'
                else:
                    alt_script = None
                
                if alt_script:
                    r2 = subprocess.run(
                        ['osascript', '-e', alt_script],
                        capture_output=True, text=True, timeout=3
                    )
                    if r2.returncode == 0:
                        return {
                            "success": True,
                            "message": f"Closed tab in {browser}",
                            "url": last_url
                        }
            except:
                pass
            
            opened_tabs.append(last_url)
            return {
                "success": False,
                "message": f"Could not close tab. Please grant Terminal automation permission.",
                "help": "System Settings → Privacy & Security → Automation → Enable Terminal to control your browser. Also check Accessibility."
            }
        
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: OPEN APP (uses 'open -a' - confirmed working)
# ====================================================================

def open_app(app_name: str) -> Dict[str, Any]:
    """Open an application on macOS using 'open -a' command."""
    try:
        # Resolve alias
        resolved = APP_ALIASES.get(app_name.lower().strip(), app_name.strip())
        
        if platform.system() != "Darwin":
            return {"success": False, "message": "Only supported on macOS"}
        
        # 'open -a' is the most reliable way to launch apps on macOS
        result = subprocess.run(
            ['open', '-a', resolved],
            capture_output=True, text=True, timeout=5
        )
        
        if result.returncode == 0:
            return {"success": True, "message": f"Opened {resolved}", "app": resolved}
        
        # If alias didn't work, try original name
        if resolved != app_name:
            r2 = subprocess.run(
                ['open', '-a', app_name],
                capture_output=True, text=True, timeout=5
            )
            if r2.returncode == 0:
                return {"success": True, "message": f"Opened {app_name}", "app": app_name}
        
        # Try finding the app using mdfind
        try:
            search = subprocess.run(
                ['mdfind', 'kMDItemKind == "Application"', '-name', app_name],
                capture_output=True, text=True, timeout=5
            )
            if search.returncode == 0 and search.stdout.strip():
                app_path = search.stdout.strip().split('\n')[0]
                r3 = subprocess.run(
                    ['open', app_path],
                    capture_output=True, text=True, timeout=5
                )
                if r3.returncode == 0:
                    return {"success": True, "message": f"Opened {app_name}", "app": app_name}
        except:
            pass
        
        return {
            "success": False,
            "message": f"Could not find '{app_name}'. Make sure it's installed.",
            "error": result.stderr.strip()
        }
        
    except subprocess.TimeoutExpired:
        return {"success": True, "message": f"Opening {app_name} (may take a moment)"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: CLOSE APP (quit running applications)
# ====================================================================

def close_app(app_name: str) -> Dict[str, Any]:
    """Close/quit a running application on macOS."""
    try:
        # Resolve alias
        resolved = APP_ALIASES.get(app_name.lower().strip(), app_name.strip())
        
        if platform.system() != "Darwin":
            return {"success": False, "message": "Only supported on macOS"}

        if not _is_app_running(resolved, app_name):
            return {"success": True, "message": f"{resolved} is already closed", "app": resolved}
        
        # Use osascript with argv to avoid script injection.
        script = """
        on run argv
            set appName to item 1 of argv
            tell application appName to quit
        end run
        """
        result = _run_osascript(script, resolved, timeout=5)
        
        if result.returncode == 0:
            time.sleep(0.5)
            if not _is_app_running(resolved, app_name):
                return {"success": True, "message": f"Closed {resolved}", "app": resolved}
        
        # If alias didn't work, try original name
        if resolved != app_name:
            r2 = _run_osascript(script, app_name, timeout=5)
            if r2.returncode == 0:
                time.sleep(0.5)
                if not _is_app_running(resolved, app_name):
                    return {"success": True, "message": f"Closed {app_name}", "app": app_name}

        # Fallback: terminate by process pattern if AppleScript route fails.
        for pattern in _app_process_candidates(resolved, app_name):
            try:
                subprocess.run(
                    ["pkill", "-if", pattern],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except Exception:
                pass

        time.sleep(0.5)
        if not _is_app_running(resolved, app_name):
            return {"success": True, "message": f"Closed {resolved}", "app": resolved}
        
        # App might not be running
        return {
            "success": False,
            "message": f"Could not close {app_name}. It may not be running.",
            "error": result.stderr.strip()
        }
        
    except subprocess.TimeoutExpired:
        return {"success": True, "message": f"Closing {app_name}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: FIND FILE (uses mdfind/Spotlight - confirmed working)
# ====================================================================

def find_file(filename: str, search_path: str = None) -> Dict[str, Any]:
    """Search for files by name using Spotlight (mdfind)."""
    try:
        # Handle empty filename
        if not filename or not filename.strip():
            return {"success": False, "message": "Please specify a file name to search for."}
        # Resolve search path
        if search_path:
            search_path = PATH_SHORTCUTS.get(search_path.lower().strip(), search_path)
        else:
            search_path = os.path.expanduser("~")
        
        if not os.path.exists(search_path):
            search_path = os.path.expanduser("~")
        
        home = os.path.expanduser("~")
        results = []
        
        if platform.system() == "Darwin":
            # Use Spotlight (mdfind) — fast and reliable
            cmd = ['mdfind', '-name', filename]
            if search_path != home:
                cmd = ['mdfind', '-onlyin', search_path, '-name', filename]
            
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    results = r.stdout.strip().split('\n')[:10]
            except subprocess.TimeoutExpired:
                pass
        
        # Fallback: Python glob
        if not results:
            try:
                found = list(Path(search_path).glob(f"**/*{filename}*"))[:10]
                results = [str(f) for f in found]
            except:
                pass
        
        if results:
            # Make paths readable
            formatted = [p.replace(home, "~") for p in results]
            
            if len(formatted) == 1:
                msg = f"Found '{filename}' at: {formatted[0]}"
            else:
                locations = ", ".join(formatted[:5])
                msg = f"Found {len(formatted)} matches for '{filename}': {locations}"
                if len(formatted) > 5:
                    msg += f" and {len(formatted) - 5} more"
            
            return {"success": True, "message": msg, "paths": formatted, "count": len(formatted)}
        else:
            search_display = search_path.replace(home, "~")
            return {"success": False, "message": f"Could not find '{filename}' in {search_display}"}
        
    except Exception as e:
        return {"success": False, "message": f"Error searching: {str(e)}"}


# ====================================================================
# TOOL: CREATE FOLDER
# ====================================================================

def create_folder(folder_name: str, location: str = "desktop") -> Dict[str, Any]:
    """Create a new folder. Uses Python os.makedirs with fallback to open -a Finder."""
    try:
        base_path = PATH_SHORTCUTS.get(location.lower().strip(), location)
        
        if not os.path.isabs(base_path):
            base_path = os.path.join(os.path.expanduser("~/Desktop"), base_path)
        
        full_path = os.path.join(base_path, folder_name)
        home = os.path.expanduser("~")
        display_path = full_path.replace(home, "~")
        
        if os.path.exists(full_path):
            return {"success": False, "message": f"Folder '{folder_name}' already exists at {display_path}"}
        
        # Try method 1: Python os.makedirs
        try:
            os.makedirs(full_path, exist_ok=True)
            if os.path.exists(full_path):
                return {"success": True, "message": f"Created folder '{folder_name}' at {display_path}", "path": display_path}
        except (PermissionError, OSError):
            pass
        
        # Try method 2: subprocess mkdir  
        try:
            r = subprocess.run(['mkdir', '-p', full_path], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return {"success": True, "message": f"Created folder '{folder_name}' at {display_path}", "path": display_path}
        except:
            pass
        
        # Try method 3: AppleScript using quoted POSIX path (no shell interpolation)
        if platform.system() == "Darwin":
            try:
                script = """
                on run argv
                    set targetPath to item 1 of argv
                    do shell script "mkdir -p " & quoted form of targetPath
                end run
                """
                r = _run_osascript(script, full_path, timeout=5)
                if r.returncode == 0:
                    return {"success": True, "message": f"Created folder '{folder_name}' at {display_path}", "path": display_path}
            except:
                pass
        
        return {
            "success": False,
            "message": f"Could not create folder. Try running Jarvis from your regular Terminal app (not from an IDE).",
            "note": "The current terminal may have sandbox restrictions."
        }
        
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: OPEN FOLDER
# ====================================================================

def open_folder(folder_name: str, location: str = "desktop") -> Dict[str, Any]:
    """Open a folder in Finder."""
    try:
        if platform.system() != "Darwin":
            return {"success": False, "message": "Only supported on macOS"}

        folder_name = (folder_name or "").strip()
        if not folder_name:
            return {"success": False, "message": "Please specify a folder name to open."}
        if folder_name.lower().endswith(" folder"):
            folder_name = folder_name[:-7].strip()

        # If user/model passed a full path as folder_name, honor it.
        if os.path.isabs(folder_name) or folder_name.startswith("~"):
            target = os.path.expanduser(folder_name)
        else:
            base_path = _resolve_location_path(location, default="desktop")
            target = os.path.join(base_path, folder_name)

        if not os.path.isdir(target):
            parent = os.path.dirname(target)
            name = os.path.basename(target)
            ci_match = _find_case_insensitive_dir(parent, name)
            if ci_match:
                target = ci_match

        if not os.path.isdir(target):
            home = os.path.expanduser("~")
            display = target.replace(home, "~")
            return {"success": False, "message": f"Directory '{display}' not found"}

        result = subprocess.run(['open', target], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return {"success": False, "message": f"Could not open folder: {result.stderr.strip() or 'unknown error'}"}

        home = os.path.expanduser("~")
        display = target.replace(home, "~")
        return {"success": True, "message": f"Opened folder {display}", "path": display}
    except subprocess.TimeoutExpired:
        return {"success": True, "message": f"Opening folder {folder_name}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: SYSTEM INFO
# ====================================================================

def system_info(info_type: str = "all") -> Dict[str, Any]:
    """Get system information."""
    try:
        info = {}
        requested = info_type if info_type in {"battery", "disk", "time", "running_apps", "wifi", "all"} else "all"
        
        if requested in ("battery", "all"):
            info["battery"] = "Unavailable"
            try:
                r = subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    for line in r.stdout.split('\n'):
                        if '%' in line:
                            # Extract percentage and status
                            parts = line.strip()
                            # Find the percentage
                            pct_idx = parts.find('%')
                            if pct_idx > 0:
                                # Walk back to find the number
                                start = pct_idx - 1
                                while start >= 0 and (parts[start].isdigit() or parts[start] == ' '):
                                    start -= 1
                                pct = parts[start+1:pct_idx+1].strip()
                                
                                # Get charging status
                                if 'charging' in parts.lower() and 'discharging' not in parts.lower():
                                    status = "charging"
                                elif 'discharging' in parts.lower():
                                    status = "on battery"
                                elif 'charged' in parts.lower():
                                    status = "fully charged"
                                else:
                                    status = ""
                                
                                info["battery"] = f"{pct} ({status})" if status else pct
                            break
            except Exception:
                info["battery"] = "Unable to get battery info"
        
        if requested in ("disk", "all"):
            info["disk"] = "Unavailable"
            try:
                r = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    lines = r.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if len(parts) >= 5:
                            info["disk"] = f"{parts[3]} free of {parts[1]} total ({parts[4]} used)"
                        else:
                            info["disk"] = "Unable to parse disk usage"
                else:
                    info["disk"] = "Unable to get disk info"
            except Exception:
                info["disk"] = "Unable to get disk info"
        
        if requested in ("time", "all"):
            from datetime import datetime
            now = datetime.now()
            info["time"] = now.strftime("%I:%M %p, %A, %B %d, %Y")
        
        if requested in ("running_apps", "all"):
            info["running_apps"] = "Unavailable"
            try:
                # Use lsappinfo which works in sandboxed terminals
                r = subprocess.run(
                    ['lsappinfo', 'list'],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0:
                    apps = []
                    for line in r.stdout.split('\n'):
                        # Lines with app names look like: N) "AppName" ASN:...
                        line = line.strip()
                        if ') "' in line and 'ASN:' in line:
                            try:
                                name = line.split('"')[1]
                                # Skip system processes
                                if name not in ('universalaccessd', 'loginwindow', 'backgroundtaskmanagementagent'):
                                    apps.append(name)
                            except:
                                pass
                    info["running_apps"] = apps if apps else "No apps detected"
                else:
                    info["running_apps"] = "Unable to get running apps"
            except Exception:
                info["running_apps"] = "Unable to get running apps"
        
        if requested in ("wifi", "all"):
            info["wifi"] = "Unavailable"
            try:
                # Resolve active Wi-Fi interface first.
                iface = None
                list_ifaces = subprocess.run(
                    ['networksetup', '-listallhardwareports'],
                    capture_output=True, text=True, timeout=3
                )
                if list_ifaces.returncode == 0:
                    blocks = list_ifaces.stdout.split("Hardware Port:")
                    for block in blocks:
                        if "Wi-Fi" in block and "Device:" in block:
                            for ln in block.splitlines():
                                ln = ln.strip()
                                if ln.startswith("Device:"):
                                    iface = ln.split(":", 1)[1].strip()
                                    break
                        if iface:
                            break
                if not iface:
                    iface = "en0"

                r = subprocess.run(
                    ['networksetup', '-getairportnetwork', iface],
                    capture_output=True, text=True, timeout=3
                )
                out = (r.stdout or "").strip()
                if r.returncode == 0 and 'Current Wi-Fi Network:' in out:
                    info["wifi"] = out.split(':', 1)[1].strip()
                elif "You are not associated with an AirPort network" in out:
                    info["wifi"] = "Not connected"
                else:
                    info["wifi"] = "Unable to detect"
            except Exception:
                info["wifi"] = "Unable to detect"
        
        # Format message
        if requested == "all":
            parts = []
            for key, val in info.items():
                if key == "running_apps" and isinstance(val, list):
                    parts.append(f"Running apps: {len(val)} apps active")
                else:
                    parts.append(f"{key.replace('_', ' ').title()}: {val}")
            message = ". ".join(parts)
        elif requested == "running_apps":
            apps = info.get("running_apps", [])
            if isinstance(apps, list):
                message = f"Running apps: {', '.join(apps[:20])}"
            else:
                message = str(apps)
        else:
            val = info.get(requested, "Unavailable")
            message = f"{requested.replace('_', ' ').title()}: {val}"
        
        return {"success": True, "message": message, "data": info}
        
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: LIST CONTENTS (list files/folders in a directory)
# ====================================================================

def list_contents(location: str = "desktop") -> Dict[str, Any]:
    """List all files and folders in a given directory."""
    try:
        # Resolve location
        dir_path = _resolve_location_path(location, default="desktop")
        
        if not os.path.exists(dir_path):
            return {"success": False, "message": f"Directory '{location}' not found"}
        
        home = os.path.expanduser("~")
        display_dir = dir_path.replace(home, "~")
        
        # List all items
        try:
            items = os.listdir(dir_path)
        except PermissionError:
            # Fallback: use ls command
            r = subprocess.run(['ls', dir_path], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                items = r.stdout.strip().split('\n')
            else:
                return {"success": False, "message": f"Cannot access {display_dir}"}
        
        # Separate files and folders
        folders = []
        files = []
        for item in items:
            if item.startswith('.'):
                continue
            
            full_path = os.path.join(dir_path, item)
            if os.path.isdir(full_path):
                folders.append(item)
            else:
                files.append(item)
        
        folders.sort()
        files.sort()
        
        # Format output
        count_msg = f"Found {len(folders)} folders and {len(files)} files in {display_dir}"
        
        content_list = []
        if folders:
            content_list.append("Folders:\n" + "\n".join([f"  📂 {f}" for f in folders]))
        if files:
            content_list.append("Files:\n" + "\n".join([f"  📄 {f}" for f in files]))
            
        details = "\n\n".join(content_list)
        
        return {
            "success": True, 
            "message": count_msg, 
            "details": details,
            "folders": folders, 
            "files": files
        }
        
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ====================================================================
# TOOL: TASK MANAGEMENT
# ====================================================================

def _load_tasks() -> List[Dict[str, Any]]:
    """Load tasks from JSON file."""
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, 'r') as f:
            tasks = json.load(f)
            if not isinstance(tasks, list):
                return []
            normalized = []
            next_id = 1
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_id = task.get("id")
                if not isinstance(task_id, int):
                    task_id = next_id
                next_id = max(next_id, task_id + 1)
                normalized.append({
                    "id": task_id,
                    "description": str(task.get("description", "")).strip(),
                    "created_at": task.get("created_at", time.time()),
                    "status": task.get("status", "pending"),
                })
            return normalized
    except:
        ts = int(time.time())
        corrupt_path = f"{TASKS_FILE}.corrupt.{ts}"
        try:
            shutil.copy2(TASKS_FILE, corrupt_path)
            print(f"Warning: tasks file is corrupted. Backup saved to {corrupt_path}")
        except Exception:
            pass
        return []

def _save_tasks(tasks: List[Dict[str, Any]]):
    """Save tasks to JSON file."""
    try:
        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)
    except Exception as e:
        print(f"Error saving tasks: {e}")

def add_task(description: str) -> Dict[str, Any]:
    """Add a new task."""
    try:
        tasks = _load_tasks()
        clean_description = str(description or "").strip()
        if not clean_description:
            return {"success": False, "message": "Task description cannot be empty."}
        next_id = max([t.get("id", 0) for t in tasks], default=0) + 1
        
        # Create new task
        new_task = {
            "id": next_id,
            "description": clean_description,
            "created_at": time.time(),
            "status": "pending"
        }
        
        tasks.append(new_task)
        _save_tasks(tasks)
        
        return {
            "success": True,
            "message": f"Added task: {clean_description}",
            "task": new_task
        }
    except Exception as e:
        return {"success": False, "message": f"Error adding task: {str(e)}"}

def list_tasks() -> Dict[str, Any]:
    """List all pending tasks."""
    try:
        tasks = sorted(_load_tasks(), key=lambda t: t.get("id", 0))
        
        if not tasks:
            return {"success": True, "message": "You have no tasks in your list."}
        
        # Format the list
        task_list_str = "Here are your tasks:\n"
        for task in sorted(tasks, key=lambda t: t.get("id", 0)):
            task_list_str += f"{task['id']}. {task['description']}\n"
        
        return {
            "success": True, 
            "message": f"You have {len(tasks)} tasks.", 
            "details": task_list_str,
            "count": len(tasks),
            "tasks": tasks
        }
    except Exception as e:
        return {"success": False, "message": f"Error listing tasks: {str(e)}"}

def complete_task(task_id: int) -> Dict[str, Any]:
    """Complete/delete a task by its 1-based index."""
    try:
        if not isinstance(task_id, int) or task_id <= 0:
            return {"success": False, "message": "Task ID must be a positive integer."}
        tasks = _load_tasks()
        
        if not tasks:
            return {"success": False, "message": "Task list is empty."}
        
        matched_index = None
        for i, task in enumerate(tasks):
            if task.get("id") == task_id:
                matched_index = i
                break
        if matched_index is None:
            return {"success": False, "message": f"Task #{task_id} not found."}
        
        # Remove task
        removed = tasks.pop(matched_index)
        _save_tasks(tasks)
        
        return {
            "success": True,
            "message": f"Completed task: {removed['description']}",
            "task": removed
        }
    except Exception as e:
        return {"success": False, "message": f"Error completing task: {str(e)}"}


# ====================================================================
# TOOL: REMINDERS
# ====================================================================

def _load_reminders() -> List[Dict[str, Any]]:
    if not os.path.exists(REMINDERS_FILE):
        return []
    try:
        with open(REMINDERS_FILE, "r") as f:
            items = json.load(f)
        if not isinstance(items, list):
            return []
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            reminder_id = item.get("id")
            remind_at = item.get("remind_at")
            if not isinstance(reminder_id, int) or not isinstance(remind_at, (int, float)):
                continue
            normalized.append({
                "id": reminder_id,
                "description": str(item.get("description", "")).strip(),
                "created_at": float(item.get("created_at", time.time())),
                "remind_at": float(remind_at),
                "status": str(item.get("status", "pending")),
                "reminded": bool(item.get("reminded", False)),
                "reminded_at": item.get("reminded_at"),
                "calendar_event_id": item.get("calendar_event_id"),
                "calendar_event_link": item.get("calendar_event_link"),
            })
        return normalized
    except Exception:
        ts = int(time.time())
        corrupt_path = f"{REMINDERS_FILE}.corrupt.{ts}"
        try:
            shutil.copy2(REMINDERS_FILE, corrupt_path)
            print(f"Warning: reminders file is corrupted. Backup saved to {corrupt_path}")
        except Exception:
            pass
        return []


def _save_reminders(reminders: List[Dict[str, Any]]) -> None:
    try:
        with open(REMINDERS_FILE, "w") as f:
            json.dump(reminders, f, indent=2)
    except Exception as e:
        print(f"Error saving reminders: {e}")


def _format_epoch_local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%I:%M %p on %b %d, %Y")


def _parse_time_fallback(time_str: str) -> Optional[datetime]:
    raw = str(time_str or "").strip()
    if not raw:
        return None

    text = raw.lower()
    now = datetime.now().astimezone()

    rel_match = re.search(r"\bin\s+(\d+)\s*(minute|minutes|hour|hours|day|days)\b", text)
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2)
        if "minute" in unit:
            return now + timedelta(minutes=amount)
        if "hour" in unit:
            return now + timedelta(hours=amount)
        return now + timedelta(days=amount)

    date_part = None
    if "tomorrow" in text:
        date_part = (now + timedelta(days=1)).date()
    elif "today" in text:
        date_part = now.date()

    clock_patterns = [
        ("%I:%M %p", r"\b\d{1,2}:\d{2}\s*(am|pm)\b"),
        ("%I %p", r"\b\d{1,2}\s*(am|pm)\b"),
        ("%H:%M", r"\b\d{1,2}:\d{2}\b"),
    ]
    parsed_time = None
    for fmt, pattern in clock_patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = m.group(0).upper().replace("  ", " ").strip()
        try:
            parsed_time = datetime.strptime(candidate, fmt).time()
            break
        except Exception:
            continue

    if date_part and parsed_time:
        dt = datetime.combine(date_part, parsed_time, tzinfo=now.tzinfo)
        if dt < now:
            dt = dt + timedelta(days=1)
        return dt

    # ISO-like support: 2026-03-01 18:30
    cleaned = re.sub(r"\s+", " ", raw).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I %p"):
        try:
            dt = datetime.strptime(cleaned, fmt).replace(tzinfo=now.tzinfo)
            if dt < now:
                return None
            return dt
        except Exception:
            continue

    if parsed_time:
        dt = datetime.combine(now.date(), parsed_time, tzinfo=now.tzinfo)
        if dt < now:
            dt = dt + timedelta(days=1)
        return dt

    return None


def _parse_reminder_time(time_str: str) -> Optional[datetime]:
    text = str(time_str or "").strip()
    if not text:
        return None

    # Prefer dateparser if available.
    try:
        import dateparser
        local_tz = datetime.now().astimezone().tzinfo
        dt = dateparser.parse(
            text,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": datetime.now(tz=local_tz),
            },
        )
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
            return dt
    except Exception:
        pass

    return _parse_time_fallback(text)


def add_reminder(description: str, time_str: str) -> Dict[str, Any]:
    clean_description = str(description or "").strip()
    clean_time = str(time_str or "").strip()
    if not clean_description:
        return {"success": False, "message": "Reminder description cannot be empty."}
    if not clean_time:
        return {"success": False, "message": "Reminder time cannot be empty."}

    dt = _parse_reminder_time(clean_time)
    if not dt:
        return {"success": False, "message": f"Could not understand reminder time: '{clean_time}'"}

    now_ts = time.time()
    remind_ts = dt.timestamp()
    if remind_ts <= now_ts:
        return {"success": False, "message": "Reminder time must be in the future."}

    reminders = _load_reminders()
    next_id = max([r.get("id", 0) for r in reminders], default=0) + 1
    item = {
        "id": next_id,
        "description": clean_description,
        "created_at": now_ts,
        "remind_at": remind_ts,
        "status": "pending",
        "reminded": False,
        "reminded_at": None,
        "calendar_event_id": None,
        "calendar_event_link": None,
    }

    calendar_note = ""
    require_calendar_sync = True
    auto_create_calendar = False
    if CALENDAR_AVAILABLE and hasattr(jarvis_calendar, "load_calendar_config"):
        try:
            cfg = jarvis_calendar.load_calendar_config()
            auto_create_calendar = bool(cfg.get("enabled", True)) and bool(cfg.get("auto_create_events_for_reminders", True))
            require_calendar_sync = bool(cfg.get("require_calendar_sync_for_reminders", True))
            if auto_create_calendar:
                cal_result = jarvis_calendar.create_reminder_event(clean_description, dt)
                if cal_result.get("success"):
                    item["calendar_event_id"] = cal_result.get("event_id")
                    item["calendar_event_link"] = cal_result.get("link")
                    calendar_note = " Google Calendar notification configured."
                else:
                    err = cal_result.get("message", "unknown error")
                    if require_calendar_sync:
                        return {
                            "success": False,
                            "message": f"Reminder was not saved because Google Calendar sync failed: {err}",
                        }
                    calendar_note = f" Calendar sync skipped: {err}."
        except Exception as e:
            if require_calendar_sync:
                return {
                    "success": False,
                    "message": f"Reminder was not saved because Google Calendar sync failed: {e}",
                }
            calendar_note = f" Calendar sync skipped: {e}."
    elif require_calendar_sync:
        return {
            "success": False,
            "message": "Reminder was not saved because Google Calendar integration is unavailable.",
        }

    if require_calendar_sync and not auto_create_calendar:
        return {
            "success": False,
            "message": "Reminder was not saved because calendar sync is required but disabled in calendar_config.json.",
        }

    reminders.append(item)
    _save_reminders(reminders)
    base_message = f"Reminder set for {_format_epoch_local(remind_ts)}: {clean_description}."
    final_message = (base_message + calendar_note).strip()
    return {
        "success": True,
        "message": final_message,
        "reminder": item,
    }


def list_reminders() -> Dict[str, Any]:
    reminders = [r for r in _load_reminders() if r.get("status") == "pending" and not r.get("reminded")]
    reminders.sort(key=lambda r: r.get("remind_at", 0))
    if not reminders:
        return {"success": True, "message": "You have no upcoming reminders.", "count": 0, "reminders": []}

    lines = []
    for item in reminders:
        when = _format_epoch_local(item.get("remind_at", 0))
        lines.append(f"{item.get('id')}. {item.get('description')} ({when})")

    return {
        "success": True,
        "message": f"You have {len(reminders)} upcoming reminders.",
        "count": len(reminders),
        "details": "Upcoming reminders:\n" + "\n".join(lines),
        "reminders": reminders,
    }


def check_due_reminders(now_ts: Optional[float] = None) -> Dict[str, Any]:
    """
    Returns newly due reminders and marks them as delivered.
    This is meant to be called by the runtime loop.
    """
    current = float(now_ts if now_ts is not None else time.time())
    reminders = _load_reminders()
    due = []
    changed = False
    for item in reminders:
        if item.get("status") != "pending":
            continue
        if item.get("reminded"):
            continue
        remind_at = float(item.get("remind_at", 0))
        if remind_at <= current:
            item["reminded"] = True
            item["status"] = "done"
            item["reminded_at"] = current
            due.append(item)
            changed = True

    if changed:
        _save_reminders(reminders)

    return {"success": True, "count": len(due), "due": due}


# ====================================================================
# TOOL: MUSIC PERSONA + PLAYBACK
# ====================================================================

def _load_memory_data() -> Dict[str, Any]:
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_memory_data(data: Dict[str, Any]) -> None:
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def set_music_preference(preference: str) -> Dict[str, Any]:
    """Persist user's music taste in memory.json."""
    value = str(preference or "").strip()
    if not value:
        return {"success": False, "message": "Please provide a music preference to save."}

    memory = _load_memory_data()
    prefs = memory.get("preferences", {})
    if not isinstance(prefs, dict):
        prefs = {}
    prefs["music"] = value
    memory["preferences"] = prefs
    memory["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_memory_data(memory)
    return {"success": True, "message": f"Saved your music preference: {value}", "preference": value}


def _get_music_preference() -> str:
    memory = _load_memory_data()
    prefs = memory.get("preferences", {})
    if isinstance(prefs, dict):
        value = str(prefs.get("music", "")).strip()
        if value:
            return value
    return ""


def _find_first_youtube_video_url(query: str) -> Optional[str]:
    """
    Best-effort resolver: fetch YouTube search page and extract first video id.
    Returns a direct watch URL when possible.
    """
    try:
        q = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={q}"
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Common marker in YouTube response payload.
        ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        if not ids:
            return None
        video_id = ids[0]
        return f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
    except Exception:
        return None


def play_music(query: str = "", platform: str = "spotify") -> Dict[str, Any]:
    """
    Play music via Spotify/YouTube search.
    If query is empty, fallback to saved music preference.
    """
    source = str(platform or "spotify").strip().lower()
    if source not in {"spotify", "youtube"}:
        source = "spotify"

    requested = str(query or "").strip()
    chosen = requested or _get_music_preference() or "top hits"

    if source == "youtube":
        target = f"{chosen} music".strip()
        url = _find_first_youtube_video_url(target)
        if not url:
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(target)}"
    else:
        url = f"https://open.spotify.com/search/{chosen.replace(' ', '%20')}"

    try:
        webbrowser.open(url)
        opened_tabs.append(url)
        msg_pref = "using your saved preference" if (not requested and _get_music_preference()) else "for your request"
        return {
            "success": True,
            "message": f"Playing music {msg_pref}: {chosen}",
            "query": chosen,
            "platform": source,
            "url": url,
        }
    except Exception as e:
        return {"success": False, "message": f"Could not play music: {e}"}

# ====================================================================
# TOOL: CALENDAR
# ====================================================================

def add_calendar_event(summary: str, time_str: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """Add an event to Google Calendar."""
    if not CALENDAR_AVAILABLE:
        return {"success": False, "message": "Calendar module not loaded. Check dependencies."}
    
    return jarvis_calendar.create_event(summary, time_str, duration_minutes)


# ====================================================================
# TOOL REGISTRY & EXECUTOR
# ====================================================================

TOOL_REGISTRY = {
    "open_website": open_website,
    "close_website": close_website,
    "open_app": open_app,
    "close_app": close_app,
    "find_file": find_file,
    "create_folder": create_folder,
    "open_folder": open_folder,
    "system_info": system_info,
    "list_contents": list_contents,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "complete_task": complete_task,
    "add_reminder": add_reminder,
    "list_reminders": list_reminders,
    "set_music_preference": set_music_preference,
    "play_music": play_music,
    "add_calendar_event": add_calendar_event,
}


def make_natural_response(tool_name: str, result: Dict[str, Any]) -> str:
    """Convert technical tool results into natural, conversational JARVIS-style responses."""
    if not result.get("success"):
        return result["message"]
    
    if tool_name == "list_contents":
        folders = result.get("folders", [])
        files = result.get("files", [])
        folder_count = len(folders)
        file_count = len(files)
        location = "the folder"
        msg = result.get("message", "")
        if " in " in msg:
            location = msg.split(" in ", 1)[1]
        
        if folder_count == 0 and file_count == 0:
            return f"{location} is currently empty."
        elif folder_count > 0 and file_count == 0:
            preview = ", ".join(folders[:8])
            if folder_count <= 8:
                return f"There are {folder_count} folders in {location}: {preview}."
            return f"There are {folder_count} folders in {location}. The first few are: {preview}."
        elif file_count > 0 and folder_count == 0:
            preview = ", ".join(files[:8])
            if file_count <= 8:
                return f"There are {file_count} files in {location}: {preview}."
            return f"There are {file_count} files in {location}. The first few are: {preview}."
        else:
            folder_preview = ", ".join(folders[:5]) if folders else "none"
            file_preview = ", ".join(files[:5]) if files else "none"
            return (
                f"{location} contains {folder_count} folders and {file_count} files. "
                f"Folders: {folder_preview}. Files: {file_preview}."
            )
    
    elif tool_name == "find_file":
        # Make file search results conversational
        paths = result.get("paths", [])
        count = result.get("count", 0)
        if count == 1:
            return f"I found it at {paths[0]}."
        elif count > 1:
            return f"I found {count} matches. The first one is at {paths[0]}."
    
    elif tool_name == "system_info":
        data = result.get("data", {})
        if "battery" in data and len(data) == 1:
            return f"Your battery is at {data['battery']}."
        if "time" in data and len(data) == 1:
            return f"The current time is {data['time']}."
        if "disk" in data and len(data) == 1:
            return f"Disk status: {data['disk']}."
        return result.get("message", "System information retrieved.")
    
    elif tool_name == "list_tasks":
        # Make task list conversational
        count = result.get("count", 0)
        tasks = result.get("tasks", [])
        
        if count == 0:
            return "You currently have no pending tasks."
        lines = [f"You have {count} pending task{'s' if count != 1 else ''}:"]
        for i, task in enumerate(tasks, start=1):
            lines.append(f"{i}. [Task {task.get('id', i)}] {task.get('description', '').strip()}")
        return "\n".join(lines)

    elif tool_name == "list_reminders":
        count = result.get("count", 0)
        reminders = result.get("reminders", [])
        if count == 0:
            return "You currently have no upcoming reminders."
        lines = [f"You have {count} upcoming reminder{'s' if count != 1 else ''}:"]
        for i, item in enumerate(reminders, start=1):
            when = _format_epoch_local(item.get("remind_at", 0))
            lines.append(f"{i}. [Reminder {item.get('id', i)}] {item.get('description', '').strip()} at {when}")
        return "\n".join(lines)

    elif tool_name == "add_reminder":
        item = result.get("reminder", {})
        when = _format_epoch_local(item.get("remind_at", 0)) if item else ""
        desc = item.get("description", "") if item else ""
        link = item.get("calendar_event_link", "") if item else ""
        if when and desc:
            if link:
                return f"Reminder saved and synced to Google Calendar. I will remind you to {desc} at {when}. Calendar link: {link}"
            return f"Reminder saved. I will remind you to {desc} at {when}."
        return result.get("message", "Reminder saved.")

    elif tool_name == "play_music":
        q = result.get("query", "music")
        return f"Now playing {q}."

    elif tool_name == "set_music_preference":
        pref = result.get("preference", "your music preference")
        return f"Done. I saved your music taste as {pref}."
    
    return result.get("message", "Done.")


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool by name with given arguments."""
    if tool_name not in TOOL_REGISTRY:
        return {"success": False, "message": f"Unknown tool: {tool_name}"}
    
    try:
        tool_func = TOOL_REGISTRY[tool_name]
        if arguments is None:
            arguments = {}
        return tool_func(**arguments)
    except Exception as e:
        return {"success": False, "message": f"Error executing {tool_name}: {str(e)}"}


# ====================================================================
# SELF-TEST
# ====================================================================

if __name__ == "__main__":
    import json
    
    print("=== Jarvis Tools Self-Test ===\n")
    
    print(f"Available Tools ({len(TOOLS)}):")
    for t in TOOLS:
        print(f"  • {t['function']['name']}: {t['function']['description'][:50]}...")
    
    print("\n--- Quick Tests ---\n")
    
    # Test file search
    r = execute_tool("find_file", {"filename": "jarvis_brain.py"})
    print(f"find_file: {r['message']}")
    
    # Test system info
    r = execute_tool("system_info", {"info_type": "battery"})
    print(f"system_info(battery): {r['message']}")
    
    r = execute_tool("system_info", {"info_type": "time"})
    print(f"system_info(time): {r['message']}")
