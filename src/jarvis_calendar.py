import os
import json
import datetime
import pickle
import os.path
import warnings
from typing import Dict, Any, Optional

warnings.filterwarnings("ignore", category=FutureWarning, module=r"google\..*")

# Constants
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, 'calendar_config.json')
DEFAULT_CONFIG = {
    "enabled": True,
    "calendar_id": "primary",
    "credentials_file": "credentials.json",
    "token_file": "token.pickle",
    "oauth_host": "localhost",
    "oauth_port": 8080,
    "auto_create_events_for_reminders": True,
    "require_calendar_sync_for_reminders": True,
    "use_default_notifications_for_reminders": True,
    "popup_minutes_before": 0,
    "email_minutes_before": 10,
}

# Global service cache
_service = None


def _get_local_tzinfo():
    """Get local timezone info from the running system."""
    return datetime.datetime.now().astimezone().tzinfo


def _resolve_path(path_value: str) -> str:
    value = str(path_value or "").strip()
    if not value:
        return ""
    if os.path.isabs(value):
        return value
    return os.path.join(BASE_DIR, value)


def load_calendar_config() -> Dict[str, Any]:
    """Load and normalize calendar configuration."""
    config = dict(DEFAULT_CONFIG)
    existing_raw = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                existing_raw = json.load(f)
                data = existing_raw
            if isinstance(data, dict):
                config.update(data)
        except Exception:
            pass

    # Persist only when file is missing or structure actually changed.
    if not os.path.exists(CONFIG_FILE):
        save_calendar_config(config)
    elif not isinstance(existing_raw, dict) or existing_raw != config:
        save_calendar_config(config)
    return config


def save_calendar_config(config: Dict[str, Any]) -> None:
    normalized = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        normalized.update(config)
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(normalized, f, indent=2)
    except Exception:
        pass


def get_calendar_service():
    """Authenticate and return the Google Calendar service."""
    global _service
    if _service:
        return _service

    config = load_calendar_config()
    if not config.get("enabled", True):
        return None

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        print("Error: Google API libraries not installed.")
        return None

    credentials_file = _resolve_path(config.get("credentials_file", "credentials.json"))
    token_file = _resolve_path(config.get("token_file", "token.pickle"))

    creds = None
    if token_file and os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_file or not os.path.exists(credentials_file):
                print(f"Error: {credentials_file} not found.")
                return None

            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            oauth_host = str(config.get("oauth_host", "localhost") or "localhost").strip()
            oauth_port = int(config.get("oauth_port", 8080) or 8080)
            creds = flow.run_local_server(
                host=oauth_host,
                port=oauth_port,
                redirect_uri_trailing_slash=True,
            )

        if token_file:
            with open(token_file, 'wb') as token:
                pickle.dump(creds, token)

    try:
        _service = build('calendar', 'v3', credentials=creds)
        return _service
    except Exception as e:
        print(f"Error building service: {e}")
        return None


def connect_calendar() -> Dict[str, Any]:
    """Run Google OAuth flow and persist token according to config."""
    service = get_calendar_service()
    if not service:
        return {"success": False, "message": "Google Calendar connection failed. Check config and credentials."}
    return {"success": True, "message": "Google Calendar connected successfully."}


def parse_time(time_str: str) -> Optional[datetime.datetime]:
    """Parse a natural language time string into a datetime object."""
    try:
        import dateparser
        local_tz = _get_local_tzinfo()
        settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": datetime.datetime.now(tz=local_tz),
        }
        dt = dateparser.parse(time_str, settings=settings)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=local_tz)
            if dt < datetime.datetime.now(tz=local_tz):
                dt = dt + datetime.timedelta(days=1)
            return dt
        return None
    except ImportError:
        print("Error: dateparser not installed.")
        return None


def create_event(summary: str, time_str: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """Create a calendar event."""
    service = get_calendar_service()
    if not service:
        return {"success": False, "message": "Google Calendar service not available. Check credentials and libraries."}

    start_dt = parse_time(time_str)
    if not start_dt:
        return {"success": False, "message": f"Could not understand the time: '{time_str}'"}

    end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
    local_tz = _get_local_tzinfo()
    tz_name = start_dt.tzname() or str(local_tz)
    config = load_calendar_config()
    calendar_id = str(config.get("calendar_id", "primary") or "primary")

    event = {
        'summary': summary,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': tz_name,
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': tz_name,
        },
    }

    try:
        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        return {
            "success": True,
            "message": f"Event created: {summary} at {start_dt.strftime('%I:%M %p, %b %d')}",
            "link": event.get('htmlLink'),
            "event_id": event.get('id'),
        }
    except Exception as e:
        return {"success": False, "message": f"Error creating event: {str(e)}"}


def create_reminder_event(summary: str, remind_at: datetime.datetime, duration_minutes: int = 5) -> Dict[str, Any]:
    """Create a Google Calendar event that triggers notification at reminder time."""
    service = get_calendar_service()
    if not service:
        return {"success": False, "message": "Google Calendar service not available."}

    config = load_calendar_config()
    calendar_id = str(config.get("calendar_id", "primary") or "primary")

    start_dt = remind_at
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=_get_local_tzinfo())
    end_dt = start_dt + datetime.timedelta(minutes=max(1, int(duration_minutes)))

    use_default_notifications = bool(config.get("use_default_notifications_for_reminders", True))
    popup_minutes = int(config.get("popup_minutes_before", 0) or 0)
    email_minutes = int(config.get("email_minutes_before", 10) or 10)
    overrides = [{"method": "popup", "minutes": max(0, popup_minutes)}]
    if email_minutes >= 0:
        overrides.append({"method": "email", "minutes": email_minutes})

    tz_name = start_dt.tzname() or str(_get_local_tzinfo())
    event = {
        "summary": f"Jarvis Reminder: {summary}",
        "description": "Created automatically by Jarvis reminders.",
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": tz_name,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": tz_name,
        },
        "reminders": (
            {"useDefault": True}
            if use_default_notifications
            else {"useDefault": False, "overrides": overrides}
        ),
    }

    try:
        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        return {
            "success": True,
            "message": "Google Calendar reminder event created.",
            "link": created.get("htmlLink"),
            "event_id": created.get("id"),
        }
    except Exception as e:
        return {"success": False, "message": f"Could not create Google Calendar reminder event: {e}"}
