# J.A.R.V.I.S

**Just A Rather Very Intelligent System** - AI voice assistant for macOS

## Quick Start

```bash
python3 jarvis.py
```

## Telegram Control (Optional)

Run Jarvis with Telegram bot input in parallel:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
# Optional: lock to your personal chat only
export TELEGRAM_CHAT_ID="your_numeric_chat_id"
python3 jarvis.py
```

Notes:
- Telegram messages are processed through the same command pipeline as voice.
- If `TELEGRAM_CHAT_ID` is not set, Jarvis accepts messages from any chat reaching the bot.

## Features

- 🎙️ Voice activation with "Jarvis" wake word
- 🗣️ Natural text-to-speech responses
- 🛠️ System tools:
  - Open/close websites
  - Open/close applications
  - Find files
  - Create folders
  - System information (battery, time, disk, WiFi, running apps)
  - List directory contents
  - Task management (add/list/complete)
  - Reminder management (set/list)
  - Google Calendar event creation
  - Music persona + playback:
    - Save your music taste
    - Play music from your preference (Spotify/YouTube)

## Intent Architecture

Jarvis now uses a 3-stage intent architecture to prevent wrong actions:

1. Local Intent Gate (`src/jarvis_intro.py`)
- Classifies each command as `query`, `action`, or `automation`.
- Fast tools run only for `action`.
- `query` commands bypass fast execution and go to the LLM for explanation.

2. LLM Intent Policy (`src/jarvis_brain.py`)
- System prompt contains mandatory intent rules.
- Runtime computes `INTENT_HINT` plus an LLM router decision (`intent`, `should_use_tools`).
- Tool-calling mode is selected from router output:
  - `should_use_tools=true` -> `tool_choice=auto`
  - `should_use_tools=false` -> `tool_choice=none`

3. Tool Execution Layer (`src/jarvis_tools.py`)
- Executes only explicit tool calls.
- No implicit action execution from plain text responses.

### Example Behavior
- "Which command clears terminal on Mac?" -> Query -> text answer only
- "Close Terminal" -> Action -> `close_app`
- "Open YouTube and then open Spotify" -> Automation/Action -> multi-step calls

## Voice Commands

- *"Jarvis, open YouTube"*
- *"Jarvis, open CapCut"*
- *"Jarvis, close CapCut"*
- *"Jarvis, find my resume"*
- *"Jarvis, how many folders on my desktop?"*
- *"Jarvis, what's my battery level?"*
- *"Jarvis, create a folder called Projects"*
- *"Jarvis, my music taste is lofi chill beats"*
- *"Jarvis, play some good music"*
- *"Jarvis, play workout music on YouTube"*

## Requirements

- macOS
- Python 3.9+
- SuperWhisper (for voice input)
- Groq API key

## Google Calendar Setup (Reminders + Events)

1. Put your Google OAuth desktop `credentials.json` in `src/` (or set another path in `src/calendar_config.json`).
2. Configure `src/calendar_config.json`:
   - `enabled`: enable calendar integration
   - `auto_create_events_for_reminders`: when true, every Jarvis reminder also creates a Calendar event with notifications
   - `popup_minutes_before` / `email_minutes_before`: notification timing
3. Run:

```bash
python3 scripts/connect_google_calendar.py
```

This opens Google OAuth once and stores token per config (`token_file`).

## Project Structure

```
J.A.R.V.I.S./
├── jarvis.py              # Main launcher
├── src/                   # Source code
│   ├── jarvis_intro.py    # Main application
│   ├── jarvis_brain.py    # AI brain (LLM integration)
│   ├── jarvis_tools.py    # System tools
│   ├── jarvis_voice.py    # Text-to-speech
│   ├── jarvis_calendar.py # Calendar integration
│   └── memory.json        # User memory storage
```

## License

MIT
