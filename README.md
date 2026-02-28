# Jarvis CLI

<p align="center">
  <a href="https://github.com/AnubhavChaturvedi-GitHub/jarvis-cli">
    <img src="https://img.shields.io/badge/GitHub-Jarvis%20CLI-blue?style=for-the-badge&logo=github" alt="GitHub">
  </a>
  <a href="https://pypi.org/project/jarvis-cli/">
    <img src="https://img.shields.io/badge/PyPI-jarvis--cli-orange?style=for-the-badge&logo=pypi" alt="PyPI">
  </a>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  </a>
  <a href="https://github.com/AnubhavChaturvedi-GitHub/jarvis-cli/stargazers">
    <img src="https://img.shields.io/github/stars/AnubhavChaturvedi-GitHub/jarvis-cli?style=for-the-badge" alt="Stars">
  </a>
</p>

> A powerful AI assistant CLI powered by Groq LLM for terminal-based interactions. Control your Mac with natural language commands.

## Features

- **Natural Language Processing** - Control your Mac using everyday language
- **Voice Input Support** - Talk to Jarvis for hands-free control
- **App Management** - Open/close applications with simple commands
- **Web Automation** - Open websites and manage browser tabs
- **File Management** - Search, create, and organize files and folders
- **Task Management** - Add, list, and complete tasks
- **Calendar Integration** - Schedule events on Google Calendar
- **Reminders** - Set voice-activated reminders
- **Music Control** - Play music via Spotify
- **Memory System** - Jarvis learns your preferences over time
- **Live Reload** - Auto-restart on code changes during development

## Installation

### Prerequisites

- Python 3.8+
- Groq API Key ([Get one free](https://console.groq.com/))

### Via pip

```bash
pip install jarvis-cli
```

### Manual Installation

```bash
git clone https://github.com/AnubhavChaturvedi-GitHub/jarvis-cli.git
cd jarvis-cli
pip install -r requirements.txt
```

## Configuration

Set your Groq API key:

```bash
export GROQ_API_KEY=your_api_key_here
```

Or create a `.env` file in the project root:

```
GROQ_API_KEY=your_api_key_here
```

## Usage

### Basic Usage

```bash
jarvis
```

### Watch Mode (Default)

Edit files and Jarvis auto-restarts:

```bash
jarvis
```

### Single Run Mode

```bash
jarvis --no-watch
```

## Commands

Jarvis understands natural language. Here are examples:

### Opening Apps & Websites

| Command | Action |
|---------|--------|
| `open YouTube` | Open YouTube in browser |
| `open Spotify` | Launch Spotify app |
| `open VS Code` | Launch VS Code |

### File Management

| Command | Action |
|---------|--------|
| `find resume.pdf` | Search for a file |
| `create folder Projects` | Create a new folder |
| `open Downloads folder` | Open folder in Finder |
| `what's on my desktop` | List desktop contents |

### Task Management

| Command | Action |
|---------|--------|
| `add task buy milk` | Add a new task |
| `show my tasks` | List all tasks |
| `complete task 1` | Mark task as done |

### Calendar & Reminders

| Command | Action |
|---------|--------|
| `remind me to call mom tomorrow at 6 PM` | Set a reminder |
| `add to calendar meeting with John tomorrow at 2pm` | Add calendar event |
| `show my reminders` | List upcoming reminders |

### System Info

| Command | Action |
|---------|--------|
| `what's my battery status` | Check battery |
| `what time is it` | Get current time |
| `show disk usage` | Check disk space |

### Music

| Command | Action |
|---------|--------|
| `play lofi` | Play music on Spotify |
| `remember I like EDM` | Save music preference |

## Project Structure

```
jarvis-cli/
├── jarvis.py              # Main launcher with watch mode
├── src/
│   ├── jarvis_brain.py    # AI brain using Groq LLM
│   ├── jarvis_tools.py    # System control tools
│   ├── jarvis_voice.py    # Voice input processing
│   ├── jarvis_calendar.py # Google Calendar integration
│   ├── jarvis_intro.py    # Boot sequence
│   ├── memory.json        # User preferences storage
│   ├── tasks.json         # Task list storage
│   └── reminders.json     # Reminders storage
├── scripts/               # Utility scripts
└── README.md
```

## Supported Models

Default: `llama-3.1-8b-instant` (fast and efficient)

Other compatible models:
- llama-3.1-70b-versatile
- llama-3.3-70b-versatile
- mixtral-8x7b-32768

## Technology Stack

- **Language**: Python 3.8+
- **LLM**: Groq API (Llama 3.1)
- **Voice**: Speech Recognition
- **macOS Integration**: AppleScript, subprocess

## Contributing

Contributions are welcome! Please read our contributing guidelines first.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature'`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Inspired by J.A.R.V.I.S. from Iron Man
- Powered by Groq LLM API

## Keywords

artificial intelligence, CLI, assistant, voice assistant, macOS, automation, productivity, ChatGPT, Groq, Python, openai, terminal, command line, smart assistant, AI assistant, home automation, task automation
