import os
import json
import re
import platform
from datetime import datetime
from pathlib import Path
from groq import Groq

# Import tool definitions for function calling
try:
    from jarvis_tools import TOOLS
    TOOLS_AVAILABLE = True
except ImportError:
    TOOLS_AVAILABLE = False
    TOOLS = []

class JarvisBrain:
    """
    Jarvis Brain - AI-powered command processing with memory
    
    Features:
    - Natural language understanding via Groq API
    - Persistent memory storage (user preferences, facts, history)
    - Fast response times with llama-3.1-8b-instant
    - Conversation context awareness
    """
    
    def __init__(self, api_key=None):
        """Initialize Jarvis Brain with Groq API and memory system."""
        api_key = self._resolve_api_key(api_key)
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set")
        
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"  # Fast and efficient model
        
        # Memory file path
        self.memory_file = os.path.join(
            os.path.dirname(__file__), 
            "memory.json"
        )
        
        # Load or initialize memory
        self.memory = self.load_memory()
        
        # Conversation history (last 5 exchanges for context)
        self.conversation_history = []
        self._response_style_counter = 0
        
        # Enhanced system prompt with personality and memory awareness
        self.system_prompt = """You are Jarvis, an advanced AI assistant inspired by Tony Stark's AI from Iron Man.

PERSONALITY:
- Intelligent, precise, and composed
- Professional, executive-assistant tone
- Concise responses (1-2 sentences unless asked for details)
- Proactive and helpful

AVAILABLE TOOLS - USE THEM WHENEVER APPLICABLE:
1. open_website: Open websites. sites=["YouTube"] or sites=["YouTube", "Instagram"]
2. close_website: Close the current browser tab
3. open_app: Open/launch any Mac app. app_name="Spotify" or app_name="CapCut" or app_name="VS Code"
4. close_app: Close/quit any running Mac app. app_name="CapCut" or app_name="Spotify"
5. find_file: Search for a SPECIFIC file by name. filename="resume.pdf", search_path="desktop"
6. create_folder: Create folders. folder_name="New Project", location="desktop"
7. open_folder: Open a folder in Finder. folder_name="Jarvis", location="desktop"
8. system_info: Get system info. info_type="battery" or "disk" or "time" or "running_apps" or "wifi" or "all"
9. list_contents: List files and folders in a directory. location="desktop" or "downloads" or "documents"
10. add_task: Add a new task. description="Buy milk"
11. list_tasks: List all tasks.
12. complete_task: Complete a task. task_id=1
13. add_calendar_event: Add to Google Calendar. summary="Meeting", time_str="tomorrow at 2pm"
14. set_music_preference: Save music taste/persona. preference="lofi and chillhop"
15. play_music: Play music from request or saved preference. query="lofi", platform="spotify"
16. add_reminder: Set a reminder. description="Pay electricity bill", time_str="tomorrow at 8 PM"
17. list_reminders: Show upcoming reminders.

TOOL USAGE RULES - FOLLOW STRICTLY:
- "open CapCut" or "open Spotify" or "open Notes" → use open_app tool (NOT find_file)
- "close CapCut" or "close Spotify" or "quit the app" → use close_app tool (NOT close_website)
- "open YouTube" or "open Instagram" → use open_website tool
- "close tab" or "close website" → use close_website tool  
- "open Jarvis folder on desktop" or "open my project folder" → use open_folder
- "where is my file" or "find resume.pdf" → use find_file tool
- "how many folders on desktop" or "what's on my desktop" or "list desktop" → use list_contents tool
- "create a folder" → use create_folder tool
- "what's my battery" or "what time" → use system_info tool
- "add task buy milk" or "set task buy milk" → use add_task tool
- "what are my tasks" or "show task list" or "show me the task" → use list_tasks tool
- "complete task 1" or "I bought milk" → use complete_task tool
- "remind me to call mom tomorrow at 6 PM" or "set reminder for Monday 9 AM to submit report" → use add_reminder tool
- "show my reminders" or "list reminders" → use list_reminders tool
- "add to calendar meeting with Tony tomorrow" → use add_calendar_event tool
- "my music taste is lofi" or "remember I like EDM" → use set_music_preference tool
- "play some good music" or "play my music" or "play lofi on spotify" → use play_music tool
- IMPORTANT: When user says "open [app name]", use open_app. When they say "close [app name]", use close_app.
- If user says "open [folder] on desktop/documents/downloads", ALWAYS use open_folder.
- Never invent absolute paths with guessed usernames.
- Do NOT use tools for purely informational or explanatory questions.
- Use tools only when user intent is execution/action.
- CRITICAL: When a tool is needed, return native tool calls only. Do NOT output pseudo tags like <system_info>{{...}}</system_info>.
- You may return multiple tool calls when needed for one user request.

INTENT CLASSIFICATION ALGORITHM (MANDATORY):
Step 1: Classify user intent as one of:
- QUERY: asks "what/which/how/why", asks for explanation, asks for command syntax, asks what to do.
- ACTION: direct imperative command to perform now (open, close, create, list, add, set, complete, remind, schedule).
- AUTOMATION: multi-step workflow request ("do X then Y", "routine", "sequence").

Step 2: Apply behavior:
- If QUERY: respond with concise guidance in text. Do not call tools.
- If ACTION: call tools as needed.
- If AUTOMATION: clarify or execute multiple tool calls only when steps are explicit.

STRICT SAFETY EXAMPLES:
- "Which command clears terminal on Mac?" => QUERY => text answer only (e.g., clear or Cmd+K), no tool call.
- "How do I close an app?" => QUERY => explain options, no tool call.
- "Close Terminal" => ACTION => close_app.
- "Open YouTube and Spotify" => ACTION => multiple tool calls.

MEMORY AWARENESS:
You have access to stored information about the user. Use this context to personalize responses.
Current user information: {memory_context}

RUNTIME CONTEXT:
{runtime_context}

RESPONSE STYLE:
- Be direct and to the point
- Use polished, professional language
- Avoid filler and casual phrasing
- When using tools, let the tool do the work"""

    def _append_history(self, entry):
        self.conversation_history.append(entry)
        if len(self.conversation_history) > 8:
            self.conversation_history = self.conversation_history[-8:]

    def _resolve_api_key(self, api_key):
        """Resolve Groq API key from argument, environment, or .env file."""
        if api_key:
            return api_key.strip()

        env_key = os.getenv("GROQ_API_KEY")
        if env_key:
            return env_key.strip()

        # Common typo fallback for developer convenience.
        alt_key = os.getenv("GROQ_APIKEY")
        if alt_key:
            return alt_key.strip()

        env_file_key = self._read_key_from_dotenv()
        if env_file_key:
            return env_file_key.strip()

        return None

    def _read_key_from_dotenv(self):
        """Read GROQ_API_KEY from .env files without requiring python-dotenv."""
        candidate_files = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[1] / ".env",
            Path(__file__).resolve().parent / ".env",
        ]

        for env_path in candidate_files:
            if not env_path.exists() or not env_path.is_file():
                continue

            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        if key.strip() != "GROQ_API_KEY":
                            continue
                        value = value.strip().strip('"').strip("'")
                        if value:
                            return value
            except Exception:
                continue

        return None
    
    def load_memory(self):
        """Load memory from JSON file."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        # Default memory structure
        return {
            "user_info": {},
            "preferences": {},
            "facts": [],
            "last_updated": None
        }
    
    def save_memory(self):
        """Save memory to JSON file."""
        self.memory["last_updated"] = datetime.now().isoformat()
        try:
            with open(self.memory_file, 'w') as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save memory: {e}")
    
    def update_memory(self, key, value, category="user_info"):
        """Update memory with new information."""
        if category == "facts":
            if value not in self.memory["facts"]:
                self.memory["facts"].append(value)
        else:
            self.memory[category][key] = value
        self.save_memory()
    
    def get_memory_context(self):
        """Get formatted memory context for system prompt."""
        context_parts = []
        
        if self.memory["user_info"]:
            context_parts.append(f"User info: {self.memory['user_info']}")
        
        if self.memory["preferences"]:
            context_parts.append(f"Preferences: {self.memory['preferences']}")
        
        if self.memory["facts"]:
            recent_facts = self.memory["facts"][-5:]  # Last 5 facts
            context_parts.append(f"Recent facts: {', '.join(recent_facts)}")
        
        return " | ".join(context_parts) if context_parts else "No stored information yet"

    def get_runtime_context(self):
        """Get concrete runtime context to prevent path hallucination."""
        home = os.path.expanduser("~")
        return (
            f"OS={platform.system()} | "
            f"Home={home} | "
            f"Desktop={os.path.join(home, 'Desktop')} | "
            f"Documents={os.path.join(home, 'Documents')} | "
            f"Downloads={os.path.join(home, 'Downloads')}"
        )

    def _classify_intent_hint(self, command: str) -> str:
        """Lightweight intent hint to prevent accidental tool execution for queries."""
        text = (command or "").strip().lower()
        if not text:
            return "query"

        query_prefixes = (
            "what", "which", "how", "why", "when", "where",
            "can you explain", "tell me", "help me understand",
        )
        query_cues = (
            "what command", "which command", "how do i", "how to",
            "what should i", "explain", "difference between",
        )
        automation_cues = ("and then", "after that", "routine", "workflow", "sequence")
        action_verbs = ("open", "close", "quit", "launch", "start", "create", "list", "add", "set", "complete", "remind", "schedule", "play")
        polite_action_prefixes = ("can you ", "could you ", "would you ", "please ")

        if any(cue in text for cue in automation_cues):
            return "automation"
        if any(text.startswith(p) for p in polite_action_prefixes) and any(
            re.search(rf"\b{re.escape(v)}\b", text) for v in action_verbs
        ):
            return "action"
        if text.endswith("?"):
            if any(re.search(rf"\b{re.escape(v)}\b", text) for v in action_verbs):
                return "action"
            return "query"
        if any(text.startswith(prefix) for prefix in query_prefixes):
            return "query"
        if any(cue in text for cue in query_cues):
            return "query"
        return "action"

    def _decide_tool_strategy(self, command: str, fallback_intent: str) -> dict:
        """
        Ask the LLM to decide whether this turn should execute tools.
        Returns: {"intent": "query|action|automation", "should_use_tools": bool}
        """
        default_should_use_tools = fallback_intent != "query"
        decision = {
            "intent": fallback_intent if fallback_intent in {"query", "action", "automation"} else "action",
            "should_use_tools": default_should_use_tools,
        }

        try:
            planner_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an intent router for a voice assistant. "
                        "Decide if the user wants explanation text or immediate execution. "
                        "Return STRICT JSON only with keys: intent, should_use_tools. "
                        "intent must be one of query, action, automation. "
                        "For questions like 'which command should I use', set should_use_tools=false. "
                        "For direct requests like 'open capcut' or polite requests like 'can you open capcut?', "
                        "set should_use_tools=true."
                    ),
                },
                {"role": "user", "content": command},
            ]

            router_completion = self.client.chat.completions.create(
                model=self.model,
                messages=planner_messages,
                temperature=0,
                max_tokens=80,
                top_p=1,
            )
            raw = (router_completion.choices[0].message.content or "").strip()
            parsed = None
            try:
                parsed = json.loads(raw)
            except Exception:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except Exception:
                        parsed = None

            if isinstance(parsed, dict):
                intent = str(parsed.get("intent", decision["intent"])).strip().lower()
                if intent not in {"query", "action", "automation"}:
                    intent = decision["intent"]

                should_use_tools = parsed.get("should_use_tools", decision["should_use_tools"])
                if isinstance(should_use_tools, str):
                    should_use_tools = should_use_tools.strip().lower() in {"true", "yes", "1"}
                else:
                    should_use_tools = bool(should_use_tools)

                decision = {"intent": intent, "should_use_tools": should_use_tools}
        except Exception:
            pass

        return decision
    
    def process_command(self, command):
        """
        Process a voice command and generate a response.
        
        Args:
            command (str): The user's voice command
        
        Returns:
            str or dict: Either a text response, or a dict with tool call information
                        Dict format: {"type": "tool_call", "tool_name": str, "arguments": dict, "message": str}
        """
        try:
            intent_hint = self._classify_intent_hint(command)
            strategy = self._decide_tool_strategy(command, intent_hint)
            # Build messages with memory context
            messages = [
                {
                    "role": "system",
                    "content": self.system_prompt.replace(
                        "{memory_context}",
                        self.get_memory_context()
                    ).replace(
                        "{runtime_context}",
                        self.get_runtime_context()
                    )
                }
            ]
            messages.append({
                "role": "system",
                "content": (
                    f"INTENT_HINT={intent_hint}. "
                    f"ROUTER_DECISION intent={strategy['intent']} should_use_tools={str(strategy['should_use_tools']).lower()}. "
                    "Follow the intent algorithm exactly."
                )
            })
            
            # Add conversation history for context
            # Only add the clean user/assistant exchanges (no tool markers)
            for exchange in self.conversation_history[-3:]:  # Last 3 exchanges
                messages.append({"role": "user", "content": exchange["user"]})
                # Use the clean response, not the tool marker
                assistant_msg = exchange.get("clean_response", exchange["assistant"])
                messages.append({"role": "assistant", "content": assistant_msg})
            
            # Add current command
            messages.append({"role": "user", "content": command})
            
            # Create chat completion with function calling support
            completion_params = {
                "messages": messages,
                "model": self.model,
                "temperature": 0.3,  # Lower for more consistent tool calling
                "max_tokens": 300,
                "top_p": 0.9,
            }
            
            # Add tools if available
            if TOOLS_AVAILABLE and TOOLS:
                completion_params["tools"] = TOOLS
                completion_params["tool_choice"] = "auto" if strategy.get("should_use_tools") else "none"
            
            chat_completion = self.client.chat.completions.create(**completion_params)
            
            # Extract the message
            message = chat_completion.choices[0].message
            
            # Check if there are tool calls
            if hasattr(message, 'tool_calls') and message.tool_calls:
                parsed_calls = []
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except Exception:
                        arguments = {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    parsed_calls.append({
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "message": self._generate_tool_confirmation(tool_name, arguments)
                    })

                if len(parsed_calls) == 1:
                    call = parsed_calls[0]
                    self._append_history({
                        "user": command,
                        "assistant": call["message"],
                        "clean_response": call["message"],
                        "tool_call": {"name": call["tool_name"], "args": call["arguments"]},
                        "timestamp": datetime.now().isoformat()
                    })
                    return {
                        "type": "tool_call",
                        "tool_name": call["tool_name"],
                        "arguments": call["arguments"],
                        "message": call["message"]
                    }

                summary_msg = f"Executing {len(parsed_calls)} actions now."
                self._append_history({
                    "user": command,
                    "assistant": summary_msg,
                    "clean_response": summary_msg,
                    "tool_calls": parsed_calls,
                    "timestamp": datetime.now().isoformat()
                })
                return {"type": "tool_calls", "calls": parsed_calls, "message": summary_msg}
            
            
            # No native tool call detected - fallback parse for XML-like tool tags
            response = message.content
            parsed_calls = self._extract_tool_tags(response)
            if not parsed_calls:
                parsed_calls = self._extract_empty_tool_tags(response)
            if parsed_calls:
                if len(parsed_calls) == 1:
                    tool_name = parsed_calls[0]["tool_name"]
                    arguments = parsed_calls[0]["arguments"]
                    confirmation_msg = self._generate_tool_confirmation(tool_name, arguments)

                    self._append_history({
                        "user": command,
                        "assistant": confirmation_msg,
                        "clean_response": confirmation_msg,
                        "tool_call": {"name": tool_name, "args": arguments},
                        "timestamp": datetime.now().isoformat()
                    })

                    return {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "message": confirmation_msg
                    }

                summary_msg = f"Executing {len(parsed_calls)} actions now."
                self._append_history({
                    "user": command,
                    "assistant": summary_msg,
                    "clean_response": summary_msg,
                    "tool_calls": parsed_calls,
                    "timestamp": datetime.now().isoformat()
                })

                return {
                    "type": "tool_calls",
                    "calls": parsed_calls,
                    "message": summary_msg
                }
            
            # Regular text response (no tool call detected)
            # Store in conversation history
            self._append_history({
                "user": command,
                "assistant": response,
                "clean_response": response,
                "timestamp": datetime.now().isoformat()
            })
            
            # Auto-extract and store important information
            self._auto_learn(command, response)
            
            return response
            
        except Exception as e:
            recovered_calls = self._recover_tool_calls_from_error(e)
            if recovered_calls:
                if len(recovered_calls) == 1:
                    tool_name = recovered_calls[0]["tool_name"]
                    arguments = recovered_calls[0]["arguments"]
                    confirmation_msg = self._generate_tool_confirmation(tool_name, arguments)
                    self._append_history({
                        "user": command,
                        "assistant": confirmation_msg,
                        "clean_response": confirmation_msg,
                        "tool_call": {"name": tool_name, "args": arguments},
                        "timestamp": datetime.now().isoformat()
                    })
                    return {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "message": confirmation_msg
                    }

                summary_msg = f"Executing {len(recovered_calls)} actions now."
                self._append_history({
                    "user": command,
                    "assistant": summary_msg,
                    "clean_response": summary_msg,
                    "tool_calls": recovered_calls,
                    "timestamp": datetime.now().isoformat()
                })
                return {"type": "tool_calls", "calls": recovered_calls, "message": summary_msg}

            print(f"[Brain] Error: {e}")
            return "I ran into a processing issue. Please repeat that once."

    def record_tool_outcome(self, user_command, tool_name, arguments, tool_result, spoken_response):
        """Persist tool execution result so next model turn has full context."""
        self._append_history({
            "user": user_command,
            "assistant": spoken_response,
            "clean_response": spoken_response,
            "tool_result": {
                "name": tool_name,
                "args": arguments,
                "success": bool(tool_result.get("success")),
                "message": tool_result.get("message", "")
            },
            "timestamp": datetime.now().isoformat()
        })

    def _extract_tool_tags(self, text):
        """Fallback parser for model outputs like <tool_name>{...}</tool_name>."""
        if not text:
            return []

        valid_tools = set()
        for tool in TOOLS:
            try:
                valid_tools.add(tool["function"]["name"])
            except Exception:
                pass

        pattern = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>\s*(\{.*?\})\s*</\1>", re.DOTALL)
        calls = []

        for match in pattern.finditer(text):
            tool_name = match.group(1)
            if tool_name not in valid_tools:
                continue

            raw_args = match.group(2)
            try:
                arguments = json.loads(raw_args)
                if not isinstance(arguments, dict):
                    arguments = {}
            except Exception:
                arguments = {}

            calls.append({"tool_name": tool_name, "arguments": arguments})

        return calls

    def _extract_empty_tool_tags(self, text):
        """Fallback parser for malformed tool outputs like <list_tasks></list_tasks>."""
        if not text:
            return []

        required_by_tool = {}
        for tool in TOOLS:
            try:
                fn = tool["function"]
                name = fn["name"]
                required = fn.get("parameters", {}).get("required", []) or []
                required_by_tool[name] = list(required)
            except Exception:
                continue

        pattern = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>\s*</\1>")
        calls = []
        for match in pattern.finditer(text):
            tool_name = match.group(1)
            required = required_by_tool.get(tool_name)
            if required is None:
                continue
            if len(required) != 0:
                continue
            calls.append({"tool_name": tool_name, "arguments": {}})
        return calls

    def _recover_tool_calls_from_error(self, error):
        """
        Recover malformed tool calls from provider-side errors like:
        <function=open_app>{"app_name":"CapCut"}<function>
        """
        raw = str(error) if error is not None else ""
        if not raw:
            return []

        valid_tools = set()
        for tool in TOOLS:
            try:
                valid_tools.add(tool["function"]["name"])
            except Exception:
                pass

        pattern = re.compile(
            r"<function=([a-zA-Z_][a-zA-Z0-9_]*)>\s*(\{.*?\})\s*<function>",
            re.DOTALL
        )
        calls = []
        for match in pattern.finditer(raw):
            tool_name = match.group(1)
            if tool_name not in valid_tools:
                continue
            raw_args = match.group(2)
            try:
                arguments = json.loads(raw_args)
                if not isinstance(arguments, dict):
                    arguments = {}
            except Exception:
                arguments = {}
            calls.append({"tool_name": tool_name, "arguments": arguments})
        return calls
    
    def _generate_tool_confirmation(self, tool_name, arguments):
        """Generate a natural confirmation message for tool execution."""
        self._response_style_counter += 1

        def pick(options):
            idx = self._response_style_counter % len(options)
            return options[idx]

        if tool_name == "open_website":
            sites = arguments.get("sites", [])
            if isinstance(sites, str):
                sites = [sites]
            if len(sites) == 0:
                return pick([
                    "At your service. Opening the requested website now.",
                    "Consider it done. Bringing that site online now.",
                    "Affirmative. Opening the requested website now.",
                ])
            elif len(sites) == 1:
                site = sites[0]
                return pick([
                    f"At your service. Opening {site} now.",
                    f"Consider it done, sir. Launching {site}.",
                    f"Affirmative. Bringing up {site} now.",
                ])
            elif len(sites) == 2:
                a, b = sites[0], sites[1]
                return pick([
                    f"At your service. Opening {a} and {b} now.",
                    f"Consider it done. Bringing up {a} and {b}.",
                    f"Affirmative. Launching {a} and {b} now.",
                ])
            else:
                return pick([
                    f"At your service. Opening {len(sites)} websites now.",
                    f"Consider it done. Launching {len(sites)} destinations now.",
                    f"Affirmative. Bringing {len(sites)} sites online.",
                ])
        elif tool_name == "close_website":
            return pick([
                "At your service. Closing the active browser tab now.",
                "Consider it done. Closing the current tab.",
                "Affirmative. Tab closure in progress.",
            ])
        elif tool_name == "open_app":
            app = arguments.get("app_name", "the app")
            return pick([
                f"At your service. Opening {app} now.",
                f"Consider it done, sir. Launching {app}.",
                f"Affirmative. Bringing {app} online now.",
            ])
        elif tool_name == "close_app":
            app = arguments.get("app_name", "the app")
            return pick([
                f"At your service. Closing {app} now.",
                f"Consider it done. Shutting down {app}.",
                f"Affirmative. Terminating {app} now.",
            ])
        elif tool_name == "find_file":
            filename = arguments.get("filename", "the file")
            return pick([
                f"At your service. Scanning for {filename} now.",
                f"Consider it done. Locating {filename} on your system.",
                f"Affirmative. Running a system-wide search for {filename}.",
            ])
        elif tool_name == "create_folder":
            folder = arguments.get("folder_name", "the folder")
            location = arguments.get("location", "desktop")
            return pick([
                f"At your service. Creating {folder} on {location}.",
                f"Consider it done. Provisioning folder {folder} on {location}.",
                f"Affirmative. Folder {folder} will be created on {location}.",
            ])
        elif tool_name == "open_folder":
            folder = arguments.get("folder_name", "the folder")
            location = arguments.get("location", "desktop")
            return pick([
                f"At your service. Opening folder {folder} from {location}.",
                f"Consider it done. Bringing up the {folder} folder.",
                f"Affirmative. Accessing folder {folder} now.",
            ])
        elif tool_name == "system_info":
            info_type = arguments.get("info_type", "system")
            return pick([
                f"At your service. Retrieving {info_type} diagnostics now.",
                f"Consider it done. Pulling {info_type} information.",
                f"Affirmative. Collecting {info_type} telemetry now.",
            ])
        elif tool_name == "list_contents":
            location = arguments.get("location", "desktop")
            return pick([
                f"At your service. Inspecting contents of {location}.",
                f"Consider it done. Scanning {location} now.",
                f"Affirmative. Enumerating items in {location}.",
            ])
        elif tool_name == "add_task":
            desc = arguments.get("description", "a task")
            return pick([
                f"At your service. Adding '{desc}' to your task list.",
                f"Consider it done. Logging '{desc}' as a task.",
                f"Affirmative. Task '{desc}' has been queued.",
            ])
        elif tool_name == "list_tasks":
            return pick([
                "At your service. Reviewing your task queue.",
                "Consider it done. Pulling your current task list.",
                "Affirmative. Checking all pending tasks now.",
            ])
        elif tool_name == "complete_task":
            tid = arguments.get("task_id", "the task")
            return pick([
                f"At your service. Marking task #{tid} as complete.",
                f"Consider it done. Closing task #{tid}.",
                f"Affirmative. Task #{tid} will be completed now.",
            ])
        elif tool_name == "add_calendar_event":
            summary = arguments.get("summary", "event")
            time_str = arguments.get("time_str", "the time")
            return pick([
                f"At your service. Scheduling '{summary}' for {time_str}.",
                f"Consider it done. Calendar event '{summary}' is being set for {time_str}.",
                f"Affirmative. Booking '{summary}' at {time_str}.",
            ])
        elif tool_name == "set_music_preference":
            pref = arguments.get("preference", "your preference")
            return pick([
                f"At your service. Saving your music taste as {pref}.",
                f"Consider it done. I'll remember your music preference: {pref}.",
                f"Affirmative. Stored your music persona as {pref}.",
            ])
        elif tool_name == "play_music":
            query = arguments.get("query", "")
            if query:
                return pick([
                    f"At your service. Playing {query} now.",
                    f"Consider it done. Starting music for {query}.",
                    f"Affirmative. Playing {query} right away.",
                ])
            return pick([
                "At your service. Playing music based on your saved taste.",
                "Consider it done. Starting your preferred music now.",
                "Affirmative. Loading music from your saved preference.",
            ])
        else:
            return pick([
                f"At your service. Executing {tool_name}.",
                f"Consider it done. Running {tool_name}.",
                f"Affirmative. Executing {tool_name} now.",
            ])
    
    def _auto_learn(self, command, response):
        """Automatically extract and store important information from conversations."""
        command_lower = command.lower()
        
        # Detect name
        if "my name is" in command_lower or "i'm" in command_lower or "i am" in command_lower:
            # Simple name extraction (can be improved)
            words = command.split()
            for i, word in enumerate(words):
                if word.lower() in ["is", "i'm", "am"] and i + 1 < len(words):
                    potential_name = words[i + 1].strip(".,!?")
                    if potential_name and potential_name[0].isupper():
                        self.update_memory("name", potential_name, "user_info")
                        break
        
        # Detect preferences
        if "i like" in command_lower or "i prefer" in command_lower or "i love" in command_lower:
            self.update_memory("", command, "facts")
    
    def get_greeting(self):
        """Return a personalized greeting."""
        name = self.memory["user_info"].get("name", "")
        if name:
            return f"Hello {name}, I'm Jarvis. How may I assist you today?"
        return "Hello, I'm Jarvis. How may I assist you today?"


# Example usage
if __name__ == "__main__":
    # Test the brain
    try:
        brain = JarvisBrain()
        print("Jarvis Brain initialized successfully!")
        print(brain.get_greeting())
        
        # Test command
        test_command = "My name is Tony and I like building things"
        print(f"\nTest command: {test_command}")
        response = brain.process_command(test_command)
        print(f"Jarvis: {response}")
        
        # Test memory
        print(f"\nMemory: {brain.memory}")
        
    except Exception as e:
        print(f"Error: {e}")
