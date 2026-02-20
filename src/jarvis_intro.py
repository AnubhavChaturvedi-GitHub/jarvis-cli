import json
import os
import re
import queue
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request

try:
    from jarvis_brain import JarvisBrain
    BRAIN_AVAILABLE = True
except ImportError:
    BRAIN_AVAILABLE = False
    print("Warning: jarvis_brain.py not found or groq package not installed")

try:
    from jarvis_voice import JarvisVoice
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    print("Warning: jarvis_voice.py not found or kokoro package not installed")

try:
    from jarvis_tools import APP_ALIASES, WEBSITE_MAP, check_due_reminders, execute_tool, make_natural_response
    TOOLS_AVAILABLE = True
except ImportError:
    TOOLS_AVAILABLE = False
    APP_ALIASES = {}
    WEBSITE_MAP = {}

    def check_due_reminders(now_ts=None):
        return {"success": True, "count": 0, "due": []}

    def make_natural_response(tool_name, result):
        return result.get("message", "Done.")

    print("Warning: jarvis_tools.py not found")

RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
DIM = "\033[2m"
ORANGE = "\033[38;5;208m"

RECORDINGS_DIR = os.path.expanduser("~/Documents/superwhisper/recordings")
WAKE_WORDS = ["jarvis", "jervis", "javis", "jarviss", "jarv is", "jar viz", "jarves"]
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

VOICE_OPTIONS = [
    ("Lewis", "bm_lewis"),
    ("Adam", "am_adam"),
    ("Michael", "am_michael"),
    ("Bella", "af_bella"),
    ("Sarah", "af_sarah"),
]
DEFAULT_VOICE_CODE = "bm_lewis"
VOICE_NAME_TO_CODE = {name.lower(): code for name, code in VOICE_OPTIONS}
VOICE_CODE_SET = {code for _, code in VOICE_OPTIONS}
VOICE_ALIAS_TO_CODE = {
    "lewis": "bm_lewis",
    "adam": "am_adam",
    "michael": "am_michael",
    "bella": "af_bella",
    "sarah": "af_sarah",
    "male british": "bm_lewis",
    "british": "bm_lewis",
    "male 1": "am_adam",
    "male 2": "am_michael",
    "female 1": "af_bella",
    "female 2": "af_sarah",
}
GENERIC_APP_WORDS = {"app", "application", "it", "this", "that"}
LOCATION_WORDS = ("desktop", "downloads", "documents", "home")
CLI_COMMAND_QUEUE = queue.Queue()
TELEGRAM_COMMAND_QUEUE = queue.Queue()
CLI_INPUT_STARTED = False
CLI_AUTOCOMPLETE_MODE = "none"
QUERY_PREFIXES = (
    "what", "which", "how", "why", "when", "where", "can you explain",
    "tell me", "help me understand", "what command", "which command",
)
QUERY_CUES = (
    "what command", "which command", "how do i", "how to", "can you tell me",
    "could you tell me", "what should i", "what is", "which is", "explain",
)
AUTOMATION_CUES = ("and then", "after that", "then", "workflow", "routine", "sequence")
ACTION_VERBS = ("open", "close", "quit", "launch", "start", "create", "list", "add", "set", "complete", "remind", "schedule", "play")
POLITE_ACTION_PREFIXES = ("can you ", "could you ", "would you ", "please ")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def clear_live_line():
    width = shutil.get_terminal_size((120, 30)).columns
    sys.stdout.write("\r" + (" " * max(1, width - 1)) + "\r")
    sys.stdout.flush()


def now_clock():
    return time.strftime("%H:%M:%S")


def event_line(margin, level, message):
    styles = {
        "info": (CYAN, "●"),
        "ok": (GREEN, "✓"),
        "warn": (YELLOW, "▲"),
        "error": (RED, "✗"),
        "brain": (MAGENTA, "◆"),
        "voice": (BLUE, "◉"),
        "listen": (CYAN, "◍"),
        "ignore": (DIM, "•"),
    }
    color, icon = styles.get(level, (WHITE, "•"))
    print(f"{margin}{DIM}[{now_clock()}]{RESET} {color}{icon}{RESET} {message}")


def print_divider(margin, char="─"):
    width = min(110, shutil.get_terminal_size((120, 30)).columns - len(margin) - 1)
    print(f"{margin}{DIM}{char * max(10, width)}{RESET}")


def get_latest_recording_dir():
    if not os.path.exists(RECORDINGS_DIR):
        return None

    dirs = [
        os.path.join(RECORDINGS_DIR, d)
        for d in os.listdir(RECORDINGS_DIR)
        if os.path.isdir(os.path.join(RECORDINGS_DIR, d))
    ]
    if not dirs:
        return None

    return max(dirs, key=os.path.getctime)


def process_recording(recording_dir, margin):
    meta_path = os.path.join(recording_dir, "meta.json")
    if not os.path.exists(meta_path):
        return "__PENDING__"
    if os.path.getsize(meta_path) == 0:
        return "__PENDING__"

    try:
        with open(meta_path, "r") as f:
            data = json.load(f)
        text = data.get("result", "") or data.get("rawResult", "")
        if not text:
            # Transcript exists but final text may not be flushed yet.
            return "__PENDING__"
        return text
    except json.JSONDecodeError:
        # meta.json may be mid-write; retry on next loop.
        return "__PENDING__"
    except Exception as e:
        event_line(margin, "error", f"Failed to parse transcript: {e}")
        return None


def extract_wake_command(text):
    """
    Detect wake word as a standalone token and return cleaned command text.
    Falls back to full text if wake word exists but nothing follows it.
    """
    if not text:
        return False, ""
    lowered = text.lower()
    for wake in WAKE_WORDS:
        pattern = r"\b" + re.escape(wake) + r"\b"
        match = re.search(pattern, lowered)
        if not match:
            continue
        command = text[match.end():].strip(" ,:.-")
        return True, (command if command else text.strip())
    return False, ""


def get_recording_state():
    """
    Return (latest_dir, meta_mtime_ns). This catches both new folders and
    updates to meta.json in the current folder.
    """
    latest_dir = get_latest_recording_dir()
    if not latest_dir:
        return None, None
    meta_path = os.path.join(latest_dir, "meta.json")
    try:
        return latest_dir, os.path.getmtime(meta_path)
    except OSError:
        return latest_dir, None


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_telegram_config():
    """
    Resolve Telegram runtime config from env or settings.json.
    Env takes precedence.
    """
    settings = load_settings()

    def _read_key_from_dotenv(key_name):
        candidate_files = [
            os.path.join(os.getcwd(), ".env"),
            os.path.join(os.path.dirname(__file__), "..", ".env"),
            os.path.join(os.path.dirname(__file__), ".env"),
        ]
        for env_path in candidate_files:
            try:
                if not os.path.exists(env_path) or not os.path.isfile(env_path):
                    continue
                with open(env_path, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        if k.strip() != key_name:
                            continue
                        value = v.strip().strip('"').strip("'")
                        if value:
                            return value
            except Exception:
                continue
        return ""

    token = (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or _read_key_from_dotenv("TELEGRAM_BOT_TOKEN")
        or str(settings.get("telegram_bot_token", "")).strip()
    )
    chat_id_raw = (
        os.getenv("TELEGRAM_CHAT_ID", "").strip()
        or _read_key_from_dotenv("TELEGRAM_CHAT_ID")
        or str(settings.get("telegram_chat_id", "")).strip()
    )

    chat_id = None
    if chat_id_raw:
        try:
            chat_id = int(chat_id_raw)
        except Exception:
            chat_id = None

    return token, chat_id


def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or chat_id is None:
        return False
    try:
        payload = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "text": str(text or ""),
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return bool(data.get("ok"))
    except Exception:
        return False


def start_telegram_input_reader(bot_token, allowed_chat_id=None):
    if not bot_token:
        return

    def _poll():
        offset = None
        while True:
            try:
                params = {"timeout": 25}
                if offset is not None:
                    params["offset"] = offset
                query = urllib.parse.urlencode(params)
                url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{query}"
                req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="ignore"))

                if not payload.get("ok"):
                    time.sleep(1.5)
                    continue

                for upd in payload.get("result", []):
                    try:
                        upd_id = int(upd.get("update_id"))
                        offset = upd_id + 1
                    except Exception:
                        pass

                    msg = upd.get("message") or upd.get("edited_message") or {}
                    text = str(msg.get("text", "")).strip()
                    chat = msg.get("chat", {}) if isinstance(msg, dict) else {}
                    chat_id = chat.get("id")
                    if not text or chat_id is None:
                        continue
                    try:
                        chat_id = int(chat_id)
                    except Exception:
                        continue
                    if (allowed_chat_id is not None) and (chat_id != allowed_chat_id):
                        continue
                    TELEGRAM_COMMAND_QUEUE.put({"chat_id": chat_id, "text": text})
            except Exception:
                time.sleep(2.0)

    threading.Thread(target=_poll, daemon=True).start()


def get_saved_voice_code():
    settings = load_settings()
    voice_code = str(settings.get("voice_code", DEFAULT_VOICE_CODE)).strip()
    return voice_code if voice_code in VOICE_CODE_SET else DEFAULT_VOICE_CODE


def persist_voice_code(voice_code):
    settings = load_settings()
    settings["voice_code"] = voice_code
    save_settings(settings)


def format_voice_list():
    return "Available voices: " + ", ".join([f"{name} ({code})" for name, code in VOICE_OPTIONS]) + "."


def is_voice_list_command(command_text):
    c = command_text.lower()
    return (
        ("voice" in c and "available" in c)
        or ("voice" in c and "list" in c)
        or ("change your voice" in c)
        or ("change voice" in c)
        or ("what voices" in c)
    )


def extract_voice_code(command_text):
    c = command_text.lower().strip()
    for _, code in VOICE_OPTIONS:
        if code in c:
            return code

    for alias, code in VOICE_ALIAS_TO_CODE.items():
        if alias in c:
            return code

    for name, code in VOICE_OPTIONS:
        if name.lower() in c:
            return code
    return None


def handle_voice_command(command_text, voice):
    if is_voice_list_command(command_text):
        return True, format_voice_list()

    lowered = command_text.lower()
    wants_switch = (
        "switch to" in lowered
        or "set voice to" in lowered
        or "change to" in lowered
        or "use voice" in lowered
    )
    if not wants_switch:
        return False, ""

    selected_code = extract_voice_code(command_text)
    if not selected_code:
        return True, "Please choose one of these voices. " + format_voice_list()

    persist_voice_code(selected_code)
    if voice:
        try:
            voice.set_voice(selected_code)
        except Exception:
            pass

    selected_name = next((n for n, c in VOICE_OPTIONS if c == selected_code), selected_code)
    return True, f"Voice switched to {selected_name}. I will use this voice from now on."


def handle_cli_command(raw_line, voice):
    line = (raw_line or "").strip()
    if not line.startswith("/"):
        return False, ""
    if line in {"/v", "/vo", "/voi", "/voic"}:
        line = "/voice"

    if line.startswith("/voice"):
        arg = line[len("/voice"):].strip()
        if not arg or arg.lower() in {"list", "show"}:
            return True, format_voice_list() + ' Use "/voice <name or code>" to switch.'

        selected_code = extract_voice_code(arg)
        if not selected_code:
            return True, "Unknown voice. " + format_voice_list()

        persist_voice_code(selected_code)
        if voice:
            try:
                voice.set_voice(selected_code)
            except Exception:
                pass
        selected_name = next((n for n, c in VOICE_OPTIONS if c == selected_code), selected_code)
        return True, f"Yes, voice is set to {selected_name}. Now I am speaking in that voice."

    if line == "/help":
        return True, 'Commands: /voice, /voice list, /voice <name or code>'

    return True, "Unknown command. Type /help"


def start_cli_input_reader():
    global CLI_AUTOCOMPLETE_MODE, CLI_INPUT_STARTED
    if CLI_INPUT_STARTED:
        return
    CLI_INPUT_STARTED = True

    def _build_prompt_completer():
        try:
            from prompt_toolkit.completion import FuzzyCompleter, WordCompleter
        except Exception:
            return None, None

        commands = ["/help", "/voice", "/voice list", "/voice show"]
        for name, code in VOICE_OPTIONS:
            commands.append(f"/voice {name.lower()}")
            commands.append(f"/voice {code}")
        base = WordCompleter(sorted(set(commands)), ignore_case=True, sentence=True, match_middle=True)
        return FuzzyCompleter(base), sorted(set(commands))

    completer, _ = _build_prompt_completer()
    readline_ready = False

    def _box_parts():
        cols = shutil.get_terminal_size((120, 30)).columns
        inner = max(48, min(108, cols - 12))
        title = " Command Palette "
        title_len = len(title)
        rail = max(0, inner - title_len)
        top = f"\n  ┌{title}{'─' * rail}┐"
        prompt = "  │ > "
        bottom = f"  └{'─' * inner}┘"
        return top, prompt, bottom

    if completer is not None:
        CLI_AUTOCOMPLETE_MODE = "menu"
    else:
        try:
            import readline

            voice_items = ["list", "show"] + [name.lower() for name, _ in VOICE_OPTIONS] + [code for _, code in VOICE_OPTIONS]
            voice_items = sorted(set(voice_items))
            command_items = ["/voice", "/help"]

            def _readline_complete(text, state):
                buffer = readline.get_line_buffer() or ""
                line = buffer.lstrip()

                if line.startswith("/voice"):
                    after = line[len("/voice"):].lstrip()
                    if not after:
                        candidates = ["/voice"] + [f"/voice {v}" for v in voice_items]
                    else:
                        prefix = after.lower()
                        candidates = [f"/voice {v}" for v in voice_items if v.startswith(prefix)]
                else:
                    typed = line or text
                    candidates = [c for c in command_items if c.startswith(typed)]

                if state < len(candidates):
                    return candidates[state]
                return None

            readline.set_completer(_readline_complete)
            try:
                readline.parse_and_bind("tab: complete")
            except Exception:
                readline.parse_and_bind("bind ^I rl_complete")
            readline_ready = True
        except Exception:
            readline_ready = False

        CLI_AUTOCOMPLETE_MODE = "tab" if readline_ready else "basic"

    def _reader():
        if completer is not None:
            try:
                from prompt_toolkit import PromptSession
                from prompt_toolkit.enums import EditingMode
                from prompt_toolkit.formatted_text import ANSI
                from prompt_toolkit.key_binding import KeyBindings
                from prompt_toolkit.patch_stdout import patch_stdout
                from prompt_toolkit.shortcuts import CompleteStyle

                session = PromptSession()
                kb = KeyBindings()

                @kb.add("/")
                def _(event):
                    buf = event.app.current_buffer
                    buf.insert_text("/")
                    buf.start_completion(select_first=False)

                @kb.add("up")
                def _(event):
                    buf = event.app.current_buffer
                    if buf.complete_state:
                        buf.complete_previous()
                    else:
                        buf.auto_up()

                @kb.add("down")
                def _(event):
                    buf = event.app.current_buffer
                    if buf.complete_state:
                        buf.complete_next()
                    else:
                        buf.auto_down()

                @kb.add("tab")
                def _(event):
                    buf = event.app.current_buffer
                    if not buf.complete_state:
                        buf.start_completion(select_first=False)
                    else:
                        buf.complete_next()

                while True:
                    try:
                        top, prompt_line, bottom = _box_parts()
                        with patch_stdout():
                            print(top)
                            line = session.prompt(
                                prompt_line,
                                completer=completer,
                                complete_while_typing=True,
                                complete_style=CompleteStyle.MULTI_COLUMN,
                                key_bindings=kb,
                                editing_mode=EditingMode.EMACS,
                                bottom_toolbar=ANSI(f" {DIM}Slash Menu: /voice, /help | Use ↑ ↓ to select, Enter to apply{RESET} "),
                            )
                            print(bottom)
                    except (EOFError, KeyboardInterrupt):
                        break
                    except Exception:
                        break

                    text = (line or "").strip()
                    if text:
                        CLI_COMMAND_QUEUE.put(text)
                return
            except Exception:
                pass

        # Fallback input mode if prompt_toolkit is not installed.
        while True:
            try:
                if sys.stdin and sys.stdin.isatty():
                    top, prompt_line, _ = _box_parts()
                    line = input(f"{top}\n{BOLD}{CYAN}{prompt_line}{RESET}")
                else:
                    line = input()
            except Exception:
                time.sleep(0.2)
                continue

            if line is None:
                time.sleep(0.2)
                continue

            if sys.stdin and sys.stdin.isatty():
                _, _, bottom = _box_parts()
                print(bottom)

            text = line.strip()
            if text:
                CLI_COMMAND_QUEUE.put(text)

    threading.Thread(target=_reader, daemon=True).start()


def _clean_target(value):
    cleaned = re.sub(r"^[\s,.:;]+|[\s,.:;]+$", "", value or "")
    cleaned = re.sub(r"^(the|my|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(app|application|website|site)\b", "", cleaned, flags=re.IGNORECASE).strip()
    return re.sub(r"\s{2,}", " ", cleaned)


def _extract_after_first(command_text, keywords):
    lowered = command_text.lower()
    for key in keywords:
        idx = lowered.find(key)
        if idx >= 0:
            return command_text[idx + len(key):].strip()
    return ""


def _detect_location(command_text):
    lowered = command_text.lower()
    for loc in LOCATION_WORDS:
        if loc in lowered:
            return loc
    return "desktop"


def _extract_task_description(command_text):
    text = (command_text or "").strip()
    patterns = [
        r"(?i)\b(?:add|create|set)\s+(?:a\s+)?(?:new\s+)?(?:task|todo|to-do)\s*(?:to|as)?\s*(.+)$",
        r"(?i)\b(?:task|todo|to-do)\s*[:\-]\s*(.+)$",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            desc = re.sub(r"\s{2,}", " ", m.group(1)).strip(" .")
            if desc:
                return desc
    return ""


def _extract_reminder_payload(command_text):
    """
    Extract (description, time_str) from free-form reminder phrasing.
    Handles forms like:
    - remind me to submit report tomorrow at 6 pm
    - set reminder to submit report on monday at 9 am
    """
    text = (command_text or "").strip()
    lower = text.lower()
    if ("remind me" not in lower) and ("reminder" not in lower):
        return "", ""

    body = text
    body = re.sub(r"(?i)^jarvis[, ]*", "", body).strip()
    body = re.sub(r"(?i)\b(set|create|add)\s+(a\s+)?reminder\b", "", body).strip()
    body = re.sub(r"(?i)\bremind me\b", "", body).strip()
    body = re.sub(r"(?i)^to\s+", "", body).strip()
    if not body:
        return "", ""

    time_markers = re.compile(
        r"(?i)\b("
        r"in\s+\d+\s+(?:minute|minutes|hour|hours|day|days)|"
        r"today|tomorrow|tonight|"
        r"next\s+\w+|"
        r"on\s+\w+|"
        r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
        r"\d{4}-\d{2}-\d{2}|"
        r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"
        r")\b"
    )
    match = time_markers.search(body)
    if not match:
        return "", ""

    description = body[:match.start()].strip(" ,.-")
    time_str = body[match.start():].strip(" ,.-")
    if not description or not time_str:
        return "", ""
    return description, time_str


def classify_intent(command_text):
    """
    Intent classes:
    - query: user asks for explanation/information and does not want immediate execution.
    - action: user requests immediate execution of one concrete task.
    - automation: user requests a multi-step flow/routine.
    """
    text = (command_text or "").strip().lower()
    if not text:
        return "query"

    if any(cue in text for cue in AUTOMATION_CUES):
        return "automation"

    polite_action = any(text.startswith(p) for p in POLITE_ACTION_PREFIXES) and any(
        re.search(rf"\b{re.escape(v)}\b", text) for v in ACTION_VERBS
    )
    if polite_action:
        return "action"

    if text.endswith("?"):
        if any(re.search(rf"\b{re.escape(v)}\b", text) for v in ACTION_VERBS):
            return "action"
        return "query"

    if any(text.startswith(prefix) for prefix in QUERY_PREFIXES):
        return "query"

    if any(cue in text for cue in QUERY_CUES):
        return "query"

    return "action"


def route_fast_command(command_text):
    """Fast deterministic routing for high-frequency commands."""
    text = (command_text or "").strip()
    lowered = text.lower()
    if not text:
        return False, []

    intent = classify_intent(text)
    if intent != "action":
        return False, []

    if any(p in lowered for p in ("close tab", "close website", "close this website", "close this site", "close browser tab")):
        return True, [{"tool_name": "close_website", "arguments": {}}]

    if "battery" in lowered:
        return True, [{"tool_name": "system_info", "arguments": {"info_type": "battery"}}]
    if ("what time" in lowered) or ("current time" in lowered) or lowered.strip() == "time":
        return True, [{"tool_name": "system_info", "arguments": {"info_type": "time"}}]
    if "wifi" in lowered or "wi-fi" in lowered:
        return True, [{"tool_name": "system_info", "arguments": {"info_type": "wifi"}}]
    if "disk" in lowered or "storage" in lowered or "space left" in lowered:
        return True, [{"tool_name": "system_info", "arguments": {"info_type": "disk"}}]
    if "running apps" in lowered or "what apps are running" in lowered:
        return True, [{"tool_name": "system_info", "arguments": {"info_type": "running_apps"}}]

    if re.search(r"\b(show|list|view|check)\b.*\b(tasks?|todo|to-do)\b", lowered) or "what are my tasks" in lowered:
        return True, [{"tool_name": "list_tasks", "arguments": {}}]

    if re.search(r"\b(complete|finish|done|remove|delete)\b.*\b(task)\b", lowered):
        m = re.search(r"\btask\s*#?\s*(\d+)\b", lowered)
        if m:
            return True, [{"tool_name": "complete_task", "arguments": {"task_id": int(m.group(1))}}]

    if re.search(r"\b(add|create|set)\b.*\b(task|todo|to-do)\b", lowered):
        description = _extract_task_description(text)
        if description:
            return True, [{"tool_name": "add_task", "arguments": {"description": description}}]

    if re.search(r"\b(show|list|view|check)\b.*\b(reminders?)\b", lowered):
        return True, [{"tool_name": "list_reminders", "arguments": {}}]

    if ("remind me" in lowered) or ("set reminder" in lowered) or ("create reminder" in lowered) or ("add reminder" in lowered):
        description, time_str = _extract_reminder_payload(text)
        if description and time_str:
            return True, [{"tool_name": "add_reminder", "arguments": {"description": description, "time_str": time_str}}]

    if any(p in lowered for p in ("what's on my", "what is on my", "list my", "how many folders", "how many files")):
        location = _detect_location(lowered)
        return True, [{"tool_name": "list_contents", "arguments": {"location": location}}]

    music_pref_cues = ("my music taste is", "remember my music", "save my music preference")
    likes_music = (("i like " in lowered) or ("i love " in lowered)) and any(k in lowered for k in ("music", "songs", "playlist", "genre", "artist", "lofi", "edm", "jazz", "rock", "pop"))
    if any(p in lowered for p in music_pref_cues) or likes_music:
        pref = text
        pref = re.sub(r"^(jarvis[, ]*)?", "", pref, flags=re.IGNORECASE).strip()
        pref = re.sub(r"^(my music taste is|remember my music taste is|remember my music|save my music preference|i like|i love)\s*", "", pref, flags=re.IGNORECASE).strip(" .")
        if pref:
            return True, [{"tool_name": "set_music_preference", "arguments": {"preference": pref}}]

    if "play" in lowered and "music" in lowered:
        query = text
        query = re.sub(r"^(jarvis[, ]*)?", "", query, flags=re.IGNORECASE).strip()
        query = re.sub(r"^play\s*", "", query, flags=re.IGNORECASE).strip()
        query = re.sub(r"\bmusic\b", "", query, flags=re.IGNORECASE).strip(" .")
        query = re.sub(r"\bon\s+(youtube|spotify)\b", "", query, flags=re.IGNORECASE).strip(" .")
        query = re.sub(r"\s{2,}", " ", query).strip()
        args = {"platform": "spotify"}
        if query and query.lower() not in {"some", "good", "my", "some good", "good music", "some good music", "my music"}:
            args["query"] = query
        if "youtube" in lowered:
            args["platform"] = "youtube"
        return True, [{"tool_name": "play_music", "arguments": args}]

    if re.search(r"\b(open|launch|start)\b", lowered):
        # Let the LLM handle file/folder-specific requests.
        if any(x in lowered for x in (" folder", " file", " document", "directory")):
            return False, []
        target = _clean_target(_extract_after_first(text, ("open ", "launch ", "start ")))
        if target:
            target_lower = target.lower()
            looks_like_url = any(x in target_lower for x in ("http://", "https://", "www.", ".com", ".org", ".net", ".io", ".co", ".ai"))
            known_website = target_lower in WEBSITE_MAP
            website_hint = ("website" in lowered or "site" in lowered or "tab" in lowered)
            known_app = target_lower in APP_ALIASES
            if (looks_like_url or known_website or website_hint) and not known_app:
                return True, [{"tool_name": "open_website", "arguments": {"sites": [target]}}]
            return True, [{"tool_name": "open_app", "arguments": {"app_name": target}}]

    if re.search(r"\b(close|quit|exit)\b", lowered):
        if any(w in lowered for w in ("tab", "website", "site", "browser")):
            return True, [{"tool_name": "close_website", "arguments": {}}]
        target = _clean_target(_extract_after_first(text, ("close ", "quit ", "exit ")))
        if target and target.lower() not in GENERIC_APP_WORDS:
            return True, [{"tool_name": "close_app", "arguments": {"app_name": target}}]

    return False, []


def run_tool_calls(tool_calls, margin, brain, full_command):
    final_responses = []
    for call in tool_calls:
        tool_name = call["tool_name"]
        arguments = call.get("arguments", {})
        message = call.get("message", "")

        print()
        event_line(margin, "info", f"Executing tool: {tool_name}")
        tool_result = execute_tool(tool_name, arguments)

        if tool_result.get("success"):
            event_line(margin, "ok", tool_result["message"])
            if tool_name in ["find_file", "list_contents", "system_info", "list_tasks", "list_reminders", "add_reminder"]:
                spoken = make_natural_response(tool_name, tool_result)
            elif message:
                spoken = message
            else:
                spoken = tool_result["message"]
        else:
            event_line(margin, "error", tool_result["message"])
            spoken = f"I apologize, but {tool_result['message']}"

        final_responses.append(spoken)

        if brain and hasattr(brain, "record_tool_outcome"):
            try:
                brain.record_tool_outcome(
                    user_command=full_command,
                    tool_name=tool_name,
                    arguments=arguments,
                    tool_result=tool_result,
                    spoken_response=spoken,
                )
            except Exception:
                pass

    return " ".join(final_responses) if final_responses else "Done."


def execute_command_pipeline(full_command, brain, voice, margin, speak=True):
    """
    Execute one command through voice-command handling, fast router, then LLM.
    Returns final response text.
    """
    if not full_command:
        return ""

    handled_voice, voice_response = handle_voice_command(full_command, voice)
    if handled_voice:
        final_response = voice_response
        print()
        event_line(margin, "brain", f"Jarvis: {final_response}")
        print()
        if speak and voice:
            voice.speak_async(final_response)
        return final_response

    handled_fast = False
    if TOOLS_AVAILABLE:
        handled_fast, fast_calls = route_fast_command(full_command)
        if handled_fast and fast_calls:
            final_response = run_tool_calls(fast_calls, margin, brain, full_command)
            print()
            event_line(margin, "brain", f"Jarvis: {final_response}")
            print()
            if speak and voice:
                voice.speak_async(final_response)
            return final_response
        if handled_fast:
            return ""

    if brain:
        response = brain.process_command(full_command)
        if isinstance(response, dict) and response.get("type") in ("tool_call", "tool_calls"):
            if response.get("type") == "tool_call":
                tool_calls = [{
                    "tool_name": response.get("tool_name"),
                    "arguments": response.get("arguments", {}),
                    "message": response.get("message", ""),
                }]
            else:
                tool_calls = [
                    {
                        "tool_name": c.get("tool_name"),
                        "arguments": c.get("arguments", {}),
                        "message": "",
                    }
                    for c in response.get("calls", [])
                ]

            deduped_calls = []
            seen = set()
            for c in tool_calls:
                key = (c.get("tool_name"), json.dumps(c.get("arguments", {}), sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                deduped_calls.append(c)
            tool_calls = deduped_calls

            if TOOLS_AVAILABLE:
                final_response = run_tool_calls(tool_calls, margin, brain, full_command)
            else:
                final_response = "Tool execution is not available."
        else:
            final_response = str(response)

        print()
        event_line(margin, "brain", f"Jarvis: {final_response}")
        print()
        if speak and voice:
            voice.speak_async(final_response)
        return final_response

    msg = "AI responses unavailable. Set GROQ_API_KEY and install groq."
    event_line(margin, "warn", msg)
    print()
    return msg


def print_boot_banner(margin):
    raw_logo_lines = [
        "   ██╗   █████╗   ██████╗   ██╗   ██╗  ██╗  ███████╗",
        "   ██║  ██╔══██╗  ██╔══██╗  ██║   ██║  ██║  ██╔════╝",
        "   ██║  ███████║  ██████╔╝  ██║   ██║  ██║  ███████╗",
        "   ██║  ██╔══██║  ██╔══██╗  ╚██╗ ██╔╝  ██║  ╚════██║",
        "██╗██║  ██║  ██║  ██║  ██║   ╚████╔╝   ██║  ███████║",
        "╚════╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝    ╚═══╝    ╚═╝  ╚══════╝",
    ]

    cols = shutil.get_terminal_size((120, 30)).columns
    panel_w = max(92, min(124, cols - 4))
    inner_w = panel_w - 2
    split = max(44, int(inner_w * 0.52))
    right_w = inner_w - split - 1

    def line_lr(left, right):
        left = left[:split].ljust(split)
        right = right[:right_w].ljust(right_w)
        return f"{margin}│{left}│{right}│"

    title = f" J.A.R.V.I.S Console v1.0 "
    title_fill = max(0, panel_w - len(title) - 2)
    top = f"{margin}┌{title}{'─' * title_fill}┐"
    bottom = f"{margin}└{'─' * (panel_w - 2)}┘"
    center_sep = f"{margin}├{'─' * split}┼{'─' * right_w}┤"

    left_header = f"{ORANGE}{BOLD}Welcome back, Sir.{RESET}"
    left_mode = f"{DIM}Operational mode:{RESET} {BOLD}Voice Command Runtime{RESET}"
    right_header = f"{ORANGE}{BOLD}System Overview{RESET}"
    right_tip_1 = f"{DIM}Use wake word \"Jarvis\" for voice commands{RESET}"
    right_tip_2 = f"{DIM}Use /voice in Command Palette to switch voices{RESET}"

    for line in raw_logo_lines:
        print(margin + BOLD + ORANGE + line + RESET)
    print()

    print(top)
    print(line_lr(left_header, right_header))
    print(line_lr(f"{DIM}J.A.R.V.I.S CONSOLE{RESET}  {BOLD}{GREEN}ONLINE{RESET}", right_tip_1))
    print(line_lr(left_mode, right_tip_2))
    print(center_sep)
    print(line_lr(f"{DIM}Fast Tools:{RESET} app, website, battery, time", f"{DIM}Input:{RESET} Command Palette + Autocomplete"))
    print(line_lr(f"{DIM}Profile:{RESET} Executive assistant voice runtime", f"{DIM}Theme:{RESET} Neon Console"))
    print(bottom)
    print()


def system_boot():
    clear_screen()
    margin = "  "
    print_boot_banner(margin)

    brain = None
    if BRAIN_AVAILABLE:
        try:
            brain = JarvisBrain()
            event_line(margin, "brain", f"AI Brain            {GREEN}READY{RESET}")
        except ValueError:
            event_line(margin, "error", "AI Brain            NOT CONFIGURED")
            event_line(margin, "warn", "Set GROQ_API_KEY to enable AI responses.")
        except Exception as e:
            event_line(margin, "error", f"AI Brain            ERROR: {str(e)}")

    voice = None
    selected_voice_code = get_saved_voice_code()
    if VOICE_AVAILABLE:
        try:
            voice = JarvisVoice(voice=selected_voice_code, speed=1.1)
            event_line(margin, "voice", f"Voice Engine        {GREEN}READY{RESET}")
            selected_name = next((n for n, c in VOICE_OPTIONS if c == selected_voice_code), selected_voice_code)
            event_line(margin, "info", f"Active voice: {selected_name} ({selected_voice_code})")
        except Exception as e:
            event_line(margin, "error", f"Voice Engine        ERROR: {str(e)}")

    telegram_token, telegram_chat_id = get_telegram_config()
    telegram_enabled = bool(telegram_token)
    if telegram_enabled:
        start_telegram_input_reader(telegram_token, telegram_chat_id)
        if telegram_chat_id is not None:
            event_line(margin, "ok", f"Telegram Input      READY (chat {telegram_chat_id})")
        else:
            event_line(margin, "ok", "Telegram Input      READY (all chats)")

    print_divider(margin)
    event_line(margin, "ok", "Status: Listening")
    event_line(margin, "info", f"Source: {RECORDINGS_DIR}")
    if sys.stdin and sys.stdin.isatty():
        start_cli_input_reader()
        if CLI_AUTOCOMPLETE_MODE == "menu":
            event_line(margin, "info", "Palette ready: / (arrow keys + enter)")
        elif CLI_AUTOCOMPLETE_MODE == "tab":
            event_line(margin, "info", "Palette ready: / (Tab completion)")
        else:
            event_line(margin, "warn", "Palette ready: type /voice")
    print_divider(margin)

    last_processed_dir, last_processed_meta_mtime = get_recording_state()
    last_executed_command = ""
    last_executed_at = 0.0
    last_executed_source_dir = None
    last_detected_text = ""
    last_detected_at = 0.0
    last_reminder_check = 0.0

    try:
        while True:
            while True:
                try:
                    tg_item = TELEGRAM_COMMAND_QUEUE.get_nowait()
                except queue.Empty:
                    break

                chat_id = tg_item.get("chat_id")
                tg_text = str(tg_item.get("text", "")).strip()
                if not tg_text:
                    continue
                event_line(margin, "info", f"Telegram: {tg_text}")
                event_line(margin, "brain", "Processing command...")
                final_response = execute_command_pipeline(
                    full_command=tg_text,
                    brain=brain,
                    voice=voice,
                    margin=margin,
                    speak=False,
                )
                if final_response and telegram_enabled:
                    send_telegram_message(telegram_token, chat_id, final_response)

            while True:
                try:
                    cli_line = CLI_COMMAND_QUEUE.get_nowait()
                except queue.Empty:
                    break

                handled_cli, cli_response = handle_cli_command(cli_line, voice)
                if handled_cli:
                    print()
                    event_line(margin, "info", f"Console: {cli_line}")
                    event_line(margin, "brain", f"Jarvis: {cli_response}")
                    print()
                    if voice:
                        voice.speak_async(cli_response)

            current_latest_dir, current_meta_mtime = get_recording_state()
            current_text_detected = None
            current_command_text = None

            changed = (
                current_latest_dir
                and (
                    current_latest_dir != last_processed_dir
                    or current_meta_mtime != last_processed_meta_mtime
                )
            )

            if changed:
                text = process_recording(current_latest_dir, margin)
                if text == "__PENDING__":
                    time.sleep(0.1)
                    continue
                if text is not None:
                    last_processed_dir = current_latest_dir
                    last_processed_meta_mtime = current_meta_mtime
                if text:
                    clean_text = text.strip()
                    wake_hit, extracted_command = extract_wake_command(clean_text)
                    if wake_hit:
                        current_text_detected = clean_text
                        current_command_text = extracted_command
                    else:
                        clear_live_line()
                        event_line(margin, "ignore", f"Ignored transcript: {clean_text}")

            if current_text_detected:
                # SuperWhisper can emit the same utterance twice (intermediate + final).
                # Drop only very short identical transcript bursts.
                now_ts = time.time()
                normalized_detected = " ".join(current_text_detected.lower().split())
                if (
                    normalized_detected
                    and normalized_detected == last_detected_text
                    and (now_ts - last_detected_at) < 2.2
                ):
                    continue

                clear_live_line()
                print()
                event_line(margin, "listen", "Wake word detected")
                event_line(margin, "info", f"Transcript: {current_text_detected}")

                full_command = (current_command_text or current_text_detected).strip()
                if full_command:
                    now_ts = time.time()
                    normalized_cmd = " ".join(full_command.lower().split())
                    # Ignore duplicate command bursts from repeated transcription writes.
                    if (
                        normalized_cmd == last_executed_command
                        and current_latest_dir == last_executed_source_dir
                        and (now_ts - last_executed_at) < 0.8
                    ):
                        event_line(margin, "warn", "Skipped duplicate command burst.")
                        print()
                        continue

                    event_line(margin, "brain", "Processing command...")
                    final_response = execute_command_pipeline(
                        full_command=full_command,
                        brain=brain,
                        voice=voice,
                        margin=margin,
                        speak=True,
                    )
                    if final_response is None:
                        final_response = ""
                    last_executed_command = normalized_cmd
                    last_executed_at = now_ts
                    last_executed_source_dir = current_latest_dir
                    last_detected_text = normalized_detected
                    last_detected_at = now_ts

                print()
            else:
                pass

            now_ts = time.time()
            if TOOLS_AVAILABLE and (now_ts - last_reminder_check) >= 1.0:
                try:
                    due = check_due_reminders(now_ts)
                    for item in due.get("due", []):
                        reminder_text = f"Reminder: {item.get('description', 'You have a scheduled item now.')}"
                        event_line(margin, "warn", reminder_text)
                        if voice:
                            try:
                                voice.speak_async(reminder_text)
                            except Exception:
                                pass
                        if telegram_enabled and telegram_chat_id is not None:
                            send_telegram_message(telegram_token, telegram_chat_id, reminder_text)
                except Exception as e:
                    event_line(margin, "error", f"Reminder loop error (ignored): {e}")
                last_reminder_check = now_ts

            time.sleep(0.5)

    except KeyboardInterrupt:
        clear_live_line()
        print()
        print_divider(margin)
        event_line(margin, "error", "System Offline.")


if __name__ == "__main__":
    system_boot()
