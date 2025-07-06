import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import json
import time
import os
import base64
from PIL import Image, ImageDraw
import imagehash
import io
import numpy as np
import cv2
import traceback
import signal
import threading
from concurrent.futures import ThreadPoolExecutor  # Add proper import
from fastapi.middleware.cors import CORSMiddleware  # Import CORS middleware
from typing import Optional, List, Dict, Tuple, Any
import hashlib

# Import Rich for beautiful console output
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback
from rich.pretty import Pretty
from rich.syntax import Syntax
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import print as rprint
from rich.theme import Theme

### needs tesseract-ocr installed

# Install rich traceback handler for beautiful exception formatting
install_rich_traceback()

# Create a custom theme for our logging
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "critical": "bold white on red",
    "debug": "dim cyan",
    "success": "bold green",
    "api_call": "magenta",
    "json": "blue",
    "timestamp": "dim white",
})

# Create console with custom theme
console = Console(theme=custom_theme)

# --- Logging Configuration with Rich ---
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

# Configure logging with RichHandler
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(
            console=console,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            show_path=True,
            show_level=True,
            markup=True
        )
    ]
)

# Create custom logger class for enhanced logging
class RichLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.console = console

    def _format_json(self, data: dict) -> Syntax:
        """Format JSON data with syntax highlighting"""
        json_str = json.dumps(data, indent=2, default=str)
        return Syntax(json_str, "json", theme="monokai", line_numbers=False)

    def _log_with_style(self, level: str, message: str, data: dict = None, style: str = None):
        """Log with enhanced formatting"""
        if data and isinstance(data, dict):
            # Pretty print JSON data
            self.console.print(f"[{style or level}]{message}[/{style or level}]")
            self.console.print(self._format_json(data))
        else:
            getattr(self.logger, level)(f"[{style or level}]{message}[/{style or level}]")

    def info(self, message: str, data: dict = None):
        if data:
            self._log_with_style("info", message, data)
        else:
            self.logger.info(f"[info]{message}[/info]")

    def warning(self, message: str, data: dict = None):
        if data:
            self._log_with_style("warning", message, data)
        else:
            self.logger.warning(f"[warning]{message}[/warning]")

    def error(self, message: str, data: dict = None, exc_info: bool = False):
        if exc_info:
            self.logger.error(f"[error]{message}[/error]", exc_info=True)
        elif data:
            self._log_with_style("error", message, data)
        else:
            self.logger.error(f"[error]{message}[/error]")

    def debug(self, message: str, data: dict = None):
        if data:
            self._log_with_style("debug", message, data)
        else:
            self.logger.debug(f"[debug]{message}[/debug]")

    def critical(self, message: str, data: dict = None):
        if data:
            self._log_with_style("critical", message, data)
        else:
            self.logger.critical(f"[critical]{message}[/critical]")

    def success(self, message: str, data: dict = None):
        """Custom success level logging"""
        if data:
            self._log_with_style("info", message, data, style="success")
        else:
            self.logger.info(f"[success]{message}[/success]")

    def api_call(self, message: str, endpoint: str = None, payload: dict = None, response: dict = None):
        """Special logging for API calls"""
        self.console.print(f"[api_call]🌐 API Call: {message}[/api_call]")
        if endpoint:
            self.console.print(f"  [dim]Endpoint:[/dim] {endpoint}")
        if payload:
            self.console.print("  [dim]Payload:[/dim]")
            self.console.print(self._format_json(payload))
        if response:
            self.console.print("  [dim]Response:[/dim]")
            self.console.print(self._format_json(response))

# Create the enhanced logger
logger = RichLogger("Recon")
logger.success(f"Starting Recon service with log level: {log_level}")

# Try to import pytesseract, but provide fallback if not available
try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    logging.warning("pytesseract not found. OCR functionality will be disabled.")
    HAS_TESSERACT = False

# --- Firebase Integration ---
import firebase_admin
from firebase_admin import credentials, db
import tempfile
from google.cloud import storage

# Initialize Firebase and GCS
firebase_initialized = False
gcs_initialized = False
gcs_client = None
GCS_BUCKET_NAME = "rabbitize.firebasestorage.app"

try:
    # Check if we have credentials in environment variables
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS")
    google_creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    firebase_db_url = os.getenv("FIREBASE_DATABASE_URL", "https://rabbitize-default-rtdb.firebaseio.com")

    if firebase_creds_json:
        # Write credentials to a temporary file
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as temp:
            temp.write(firebase_creds_json.encode())
            temp_path = temp.name

        # Initialize Firebase with the temporary credentials file
        cred = credentials.Certificate(temp_path)
        firebase_admin.initialize_app(cred, {
            'databaseURL': firebase_db_url
        })

        # Also initialize GCS with same credentials
        try:
            gcs_client = storage.Client.from_service_account_json(temp_path)
            gcs_initialized = True
            logger.success("✅ Google Cloud Storage initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud Storage: {e}")

        # Clean up the temporary file
        os.unlink(temp_path)
        firebase_initialized = True
    elif google_creds_json:
        # Use GOOGLE_APPLICATION_CREDENTIALS as backup
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as temp:
            temp.write(google_creds_json.encode())
            temp_path = temp.name

        # Initialize Firebase with the temporary credentials file
        cred = credentials.Certificate(temp_path)
        firebase_admin.initialize_app(cred, {
            'databaseURL': firebase_db_url
        })

        # Also initialize GCS with same credentials
        try:
            gcs_client = storage.Client.from_service_account_json(temp_path)
            gcs_initialized = True
            logger.success("✅ Google Cloud Storage initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud Storage: {e}")

        # Clean up the temporary file
        os.unlink(temp_path)
        firebase_initialized = True
    else:
        logger.warning("⚠️ No Firebase credentials found. Firebase integration disabled.")
except Exception as e:
    logger.error(f"Failed to initialize Firebase: {e}", exc_info=True)
    firebase_initialized = False

def generate_timeout_summary(objective: str, history: list, client_id: str, test_id: str, session_id: str = None, rabbitize_url: str = None) -> str:
    """
    Generate a summary of the session when it times out.
    """
    if not history:
        return "No actions were taken during the session before it timed out."

    summary_prompt_parts = [
        {"text": f"The browser automation session had the objective: '{objective}'"},
        {"text": "The session ended because it reached the maximum step limit without the agent reporting completion."},
        {"text": "Please provide a concise summary of the session based on the actions taken and observations recorded."},
        {"text": "Your summary should cover:"},
        {"text": "- What was attempted in relation to the objective."},
        {"text": "- Any notable progress made or significant findings."},
        {"text": "- What was the state of the browser or task when it timed out."},
        {"text": "- Potential reasons or obstacles that might have prevented achieving the objective within the allowed steps."},
        {"text": "Here is a condensed history of the agent's actions and observations:"}
    ]

    simplified_history_entries = []
    # Limit the number of history entries to avoid overly long prompts
    max_history_entries_for_summary = 15
    start_index = max(0, len(history) - max_history_entries_for_summary)

    for i, turn in enumerate(history[start_index:], start=start_index):
        action_args = turn.get('args', {})
        action_details = ", ".join([f"{k}={v}" for k, v in action_args.items()]) if action_args else ""
        action = f"{turn.get('tool_name', 'unknown_action')}({action_details})"
        explanation = turn.get('agent_explanation', 'No explanation provided.')
        # 'changes_description' is the LLM's interpretation of screenshot changes
        outcome = turn.get('changes_description', 'No specific outcome recorded for this step.')
        entry_text = f'Step {i+1}: Agent planned: "{explanation}". Action: {action}. Observed: "{outcome}".'
        simplified_history_entries.append(entry_text)

    history_for_prompt = "\n".join(simplified_history_entries)
    if not simplified_history_entries:
        history_for_prompt = "No actions were recorded in the relevant history segment."

    summary_prompt_parts.append({"text": history_for_prompt})

    system_instruction_text = """You are an expert analyst tasked with summarizing an automated browser interaction session.
The session has timed out. Your summary should be objective, based on the provided history, and highlight key events,
progress, and potential reasons for the timeout. Be clear and concise."""

    system_instruction = {"parts": [{"text": system_instruction_text}]}
    contents = [{"role": "user", "parts": summary_prompt_parts}]

    payload = {
        "systemInstruction": system_instruction,
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,  # Slightly higher for more descriptive summary
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 10150, # Allow a decent length for the summary
            "stopSequences": []
        }
    }

    try:
        logger.api_call(f"Requesting timeout summary for {client_id}/{test_id}",
                       endpoint="Gemini API",
                       payload={"objective": objective, "history_length": len(history)})
        # Log thinking event before API call
        log_agent_thinking_event(
            event_type="llm_request",
            caller_id="generate_timeout_summary",
            client_id=client_id,
            test_id=test_id,
            prompt_data=payload,
            metadata={"objective": objective},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="summarizer"
        )

        # This uses the globally defined GEMINI_API_URL and api_key
        response = call_gemini_api(payload, timeout=25) # Increased timeout for summary

        if response and "candidates" in response and len(response["candidates"]) > 0:
            candidate = response["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                summary_text = "".join(part.get("text", "") for part in candidate["content"]["parts"]).strip()
                if summary_text:
                    logger.success(f"✅ Successfully generated timeout summary for {client_id}/{test_id}")
                    # Log thinking event after API call (success)
                    log_agent_thinking_event(
                        event_type="llm_response_success",
                        caller_id="generate_timeout_summary",
                        client_id=client_id,
                        test_id=test_id,
                        response_data=response, # Log the full successful response
                        metadata={"objective": objective, "summary_generated": summary_text},
                        session_id=session_id,
                        rabbitize_url=rabbitize_url,
                        operator="summarizer"
                    )
                    return summary_text
        logger.warning(f"⚠️ Failed to generate a valid summary from Gemini API for {client_id}/{test_id}",
                      {"response": response})
        # Log thinking event after API call (failure to generate summary)
        log_agent_thinking_event(
            event_type="llm_response_error",
            caller_id="generate_timeout_summary",
            client_id=client_id,
            test_id=test_id,
            response_data=response, # Log the problematic response
            metadata={"objective": objective, "reason": "Failed to extract valid summary text"},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="summarizer"
        )
        return "Automated summary generation failed. The session ended due to reaching the step limit. Please review the raw history if available."
    except Exception as e:
        logger.error(f"❌ Error generating timeout summary for {client_id}/{test_id}: {e}", exc_info=True)
        # Log thinking event after API call (exception)
        log_agent_thinking_event(
            event_type="llm_response_error",
            caller_id="generate_timeout_summary",
            client_id=client_id,
            test_id=test_id,
            response_data={"error": str(e), "traceback": traceback.format_exc()},
            metadata={"objective": objective},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="summarizer"
        )
        return f"Error during automated summary generation: {str(e)}. The session ended due to the step limit."

# --- FastAPI App Initialization ---
app = FastAPI()

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8280",
        "https://silflay.rabbitize.ai",
        "https://thumper.rabbitize.ai",
        "https://dev.rabbitize.ai",
        "http://silflay.rabbitize.ai",
        "http://thumper.rabbitize.ai",
        "http://dev.rabbitize.ai"
    ],
    allow_origin_regex=r"https://.*\.rabbitize\.ai|http://.*\.rabbitize\.ai",  # Allow all subdomains
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"]   # Allow all headers
)

# --- Tool Definitions (Function Calling) ---
TOOLS = [
    {
        "functionDeclarations": [
            {"name": "click", "description": "Left click at the current mouse position"},
            {"name": "right_click", "description": "Right click at the current mouse position"},
            {"name": "middle_click", "description": "Middle click at the current mouse position"},
            {
                "name": "move_mouse",
                "description": "Move mouse to pixel coordinates",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                    },
                    "required": ["x", "y"],
                },
            },
            {"name": "click_hold", "description": "Click and hold at the current mouse position"},
            {"name": "click_release", "description": "Release the mouse at the current position"},
            {
                "name": "scroll_wheel_up",
                "description": "Scroll up by 200 pixels",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "integer", "description": "Number of scroll clicks * 200px"}},
                    "required": ["x"],
                },
            },
            {
                "name": "keypress",
                "description": "Type text into focused element (works best one key at a time)",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "string", "description": "character(s) to enter into focused element"}},
                    "required": ["x"],
                },
            },
            {
                "name": "scroll_wheel_down",
                "description": "Scroll down by 200 pixels",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "integer", "description": "Number of scroll clicks * 200px"}},
                    "required": ["x"],
                },
            },
            {
                "name": "report_done",
                "description": "Signal objective complete with feedback",
                "parameters": {
                    "type": "object",
                    "properties": {"feedback": {"type": "string", "description": "Explanation of what was achieved"}},
                    "required": ["feedback"],
                },
            },
        ]
    }
]

# --- API Configuration ---
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    logger.critical("❌ GEMINI_API_KEY environment variable is not set")
    raise RuntimeError("GEMINI_API_KEY is required")
logger.success(f"✅ API key loaded (partial): {api_key[:4]}...{api_key[-4:]}")
#GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro-preview-06-05:generateContent?key={api_key}"
GEMINI_API_FLASH_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
#GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

# --- Pydantic Model for Task Request ---
class TaskRequest(BaseModel):
    rabbitize_url: str
    target_url: str
    objective: str
    client_id: str
    test_id: str
    rabbitize_runs_dir: str
    max_steps: int = 20

# --- Helper Functions ---
# Configure timeouts using simpler approach without threads
def with_timeout(func, args=(), kwargs=None, timeout_duration=10, default=None):
    """Run a function with a timeout, returning default value if it times out"""
    if kwargs is None:
        kwargs = {}

    result = [default]

    def target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in function {func.__name__}: {e}", exc_info=True)

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_duration)

    if thread.is_alive():
        logger.warning(f"Function {func.__name__} timed out after {timeout_duration} seconds")
        return default

    return result[0]

def process_payload_for_size_limits(log_payload: Dict, client_id: str = None, test_id: str = None, session_id: str = None) -> Dict:
    """
    Process a log payload to extract and save large base64 images to local files,
    replacing them with file references to reduce payload size.

    Args:
        log_payload: The original payload dictionary
        client_id: Client ID for organizing saved files
        test_id: Test ID for organizing saved files
        session_id: Session ID for organizing saved files

    Returns:
        Dict: Processed payload with base64 images replaced by file references
    """
    import os
    import base64
    import hashlib
    import re
    import json
    from copy import deepcopy

    # Create a deep copy to avoid modifying the original payload
    processed_payload = deepcopy(log_payload)

    # Create the image_payloads directory if it doesn't exist
    image_dir = "image_payloads"
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
        logger.info(f"Created directory: {image_dir}")

    # Track statistics
    images_processed = 0
    bytes_saved = 0

    def is_base64_image(value: str) -> bool:
        """Check if a string looks like base64 encoded image data."""
        if not isinstance(value, str):
            return False

        # Much more aggressive - catch any moderately large string
        if len(value) < 200:  # Much lower threshold
            return False

        # Check for common base64 image prefixes (most reliable method)
        image_prefixes = [
            '/9j/',  # JPEG
            'iVBORw0KGgoAAAANSUhEUgAA',  # PNG
            'R0lGODlhAQABAIAAAAAAAP',  # GIF
            'UklGRg==',  # WebP
            'data:image/',  # Data URL prefix
        ]

        # If it starts with a known image prefix, it's definitely an image
        for prefix in image_prefixes:
            if value.startswith(prefix):
                logger.info(f"🎯 Detected base64 image by prefix: {prefix}")
                return True

        # VERY aggressive base64 detection for any substantial string
        try:
            # Remove any whitespace
            clean_value = value.replace(' ', '').replace('\n', '').replace('\r', '').replace('\t', '')

                        # If it's a reasonably long string, check if it might be base64
            if len(clean_value) > 1000:  # Increased threshold to reduce false positives
                # Check if it contains mostly base64 characters (allow some flexibility)
                base64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
                value_chars = set(clean_value)
                base64_ratio = len(value_chars.intersection(base64_chars)) / len(value_chars) if value_chars else 0

                # More strict requirements to avoid false positives
                if base64_ratio > 0.95 and len(clean_value) > 5000:  # 95% base64 chars and substantial length
                    # Additional checks to avoid text being detected as base64
                    # Check if it looks like readable text (lots of spaces, common words)
                    if ' ' in value and any(word in value.lower() for word in ['the', 'and', 'you', 'that', 'with', 'this', 'screen', 'click', 'move']):
                        logger.info(f"🚫 Skipping text-like string: {len(value)} chars, ratio: {base64_ratio:.2f}")
                        return False

                    # Try to decode a portion to verify it's valid base64
                    try:
                        # Clean and pad the test chunk
                        test_chunk = clean_value[:min(1000, len(clean_value))]
                        missing_padding = len(test_chunk) % 4
                        if missing_padding:
                            test_chunk += '=' * (4 - missing_padding)

                        decoded = base64.b64decode(test_chunk)
                        # If we can decode it and it's substantial, treat as base64
                        if len(decoded) > 100:  # Reasonable threshold
                            logger.info(f"🎯 Detected base64 by pattern analysis: {len(value)} chars, {base64_ratio:.2f} ratio")
                            return True
                    except Exception:
                        pass

                # Last resort: if it's very long and looks base64-ish, treat it as such
                # But be more conservative to avoid false positives with JSON
                if len(clean_value) > 20000:  # Only very long strings
                    base64_pattern = re.compile(r'^[A-Za-z0-9+/]*={0,2}$')
                    if base64_pattern.match(clean_value[:1000]):  # Test first 1000 chars
                        # Additional check: make sure it doesn't look like JSON
                        if not (value.lstrip().startswith(('[', '{')) and value.rstrip().endswith((']', '}'))):
                            logger.info(f"🎯 Detected large base64-like string: {len(value)} chars")
                            return True

        except Exception:
            pass

        return False

    def process_json_for_base64(obj, path: str = "") -> any:
        """Recursively process parsed JSON to find and replace base64 images."""
        nonlocal images_processed, bytes_saved

        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key

                # Look for common base64 image locations
                if key == "data" and isinstance(value, str) and len(value) > 200:
                    # This is likely base64 image data in inlineData.data
                    if is_base64_image(value):
                        logger.info(f"🖼️  Found base64 image in JSON at {current_path} ({len(value)} chars)")
                        result[key] = save_base64_image(value, f"json_{key}")
                        continue

                # Recursively process nested structures
                if isinstance(value, (dict, list)):
                    result[key] = process_json_for_base64(value, current_path)
                elif isinstance(value, str) and is_base64_image(value):
                    logger.info(f"🖼️  Found base64 image in JSON at {current_path} ({len(value)} chars)")
                    result[key] = save_base64_image(value, f"json_{key}")
                else:
                    result[key] = value
            return result

        elif isinstance(obj, list):
            result = []
            for i, value in enumerate(obj):
                current_path = f"{path}[{i}]"

                if isinstance(value, (dict, list)):
                    result.append(process_json_for_base64(value, current_path))
                elif isinstance(value, str) and is_base64_image(value):
                    logger.info(f"🖼️  Found base64 image in JSON at {current_path} ({len(value)} chars)")
                    result.append(save_base64_image(value, f"json_list_{i}"))
                else:
                    result.append(value)
            return result

        else:
            # Primitive value, return as-is
            return obj

    def save_base64_image(base64_data: str, context_key: str = "unknown") -> str:
        """Save base64 image data to a file and return the file reference."""
        nonlocal images_processed, bytes_saved

        try:
            # Handle data URLs (e.g., data:image/jpeg;base64,...)
            actual_base64_data = base64_data
            if base64_data.startswith('data:'):
                try:
                    # Split data URL to get just the base64 part
                    parts = base64_data.split(',', 1)
                    if len(parts) == 2:
                        actual_base64_data = parts[1]
                        logger.info(f"Extracted base64 from data URL: {parts[0]}")
                except Exception:
                    logger.warning("Failed to parse data URL, using original data")

            # Clean and validate base64 data
            clean_base64 = actual_base64_data.strip()

            # Remove any whitespace or newlines
            clean_base64 = ''.join(clean_base64.split())

            # Add proper padding if needed
            missing_padding = len(clean_base64) % 4
            if missing_padding:
                clean_base64 += '=' * (4 - missing_padding)
                logger.info(f"Added {4 - missing_padding} padding characters to base64")

            # Validate it looks like base64 before attempting decode
            if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', clean_base64):
                logger.error(f"String doesn't look like valid base64: {actual_base64_data[:50]}...")
                return f"[INVALID_BASE64: {len(base64_data)} chars]"

            # Decode the base64 data
            image_bytes = base64.b64decode(clean_base64)

            # Create a hash of the image data for the filename
            image_hash = hashlib.md5(image_bytes).hexdigest()[:12]

            # Create a meaningful filename
            timestamp = int(time.time())
            filename_parts = [f"img_{timestamp}_{image_hash}"]

            # Add context information if available
            if client_id:
                filename_parts.append(f"client_{client_id}")
            if test_id:
                filename_parts.append(f"test_{test_id}")
            if session_id:
                filename_parts.append(f"session_{session_id}")
            if context_key != "unknown":
                filename_parts.append(f"key_{context_key}")

            # Enhanced image format detection
            extension = 'bin'  # Default
            mime_type = 'application/octet-stream'  # Default

            # Check magic bytes for format detection
            if len(image_bytes) >= 3 and image_bytes[:3] == b'\xff\xd8\xff':
                extension = 'jpg'
                mime_type = 'image/jpeg'
            elif len(image_bytes) >= 8 and image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                extension = 'png'
                mime_type = 'image/png'
            elif len(image_bytes) >= 6 and (image_bytes[:6] == b'GIF87a' or image_bytes[:6] == b'GIF89a'):
                extension = 'gif'
                mime_type = 'image/gif'
            elif len(image_bytes) >= 12 and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                extension = 'webp'
                mime_type = 'image/webp'
            elif len(image_bytes) >= 2 and image_bytes[:2] == b'BM':
                extension = 'bmp'
                mime_type = 'image/bmp'
            elif len(image_bytes) >= 10 and image_bytes[6:10] in [b'JFIF', b'Exif']:
                extension = 'jpg'
                mime_type = 'image/jpeg'
            else:
                # Try to detect from original data URL if available
                if base64_data.startswith('data:image/'):
                    try:
                        mime_part = base64_data.split(';')[0].replace('data:', '')
                        if 'jpeg' in mime_part or 'jpg' in mime_part:
                            extension = 'jpg'
                            mime_type = 'image/jpeg'
                        elif 'png' in mime_part:
                            extension = 'png'
                            mime_type = 'image/png'
                        elif 'gif' in mime_part:
                            extension = 'gif'
                            mime_type = 'image/gif'
                        elif 'webp' in mime_part:
                            extension = 'webp'
                            mime_type = 'image/webp'
                    except Exception:
                        pass

            filename = f"{'_'.join(filename_parts)}.{extension}"
            filepath = os.path.join(image_dir, filename)

            # Save the image with proper binary mode
            with open(filepath, 'wb') as f:
                f.write(image_bytes)

            images_processed += 1
            bytes_saved += len(base64_data)

            logger.info(f"💾 Saved base64 image to {filepath} ({len(image_bytes)} bytes, {mime_type})")

            # Return a simple string reference to keep JSON structure intact
            return f"[IMAGE_SAVED: {filename}]"

        except Exception as e:
            logger.error(f"❌ Failed to save base64 image: {e}")
            # Return a truncated version as fallback
            return f"[BASE64_IMAGE_SAVE_FAILED: {len(base64_data)} chars, error: {str(e)}]"

    def process_dict(obj: Dict, path: str = "") -> Dict:
        """Recursively process a dictionary to find and replace base64 images."""
        result = {}

        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key

            # Debug: log large strings to see what we're missing
            if isinstance(value, str) and len(value) > 1000:
                preview = value[:100] + "..." if len(value) > 100 else value
                is_json_like = key.endswith('_json') or (value.lstrip().startswith(('[', '{')) and value.rstrip().endswith((']', '}')))
                logger.info(f"🔍 Found large string at {current_path}: {len(value)} chars, JSON-like: {is_json_like}, preview: {preview}")

            if isinstance(value, dict):
                # Recursively process nested dictionaries
                result[key] = process_dict(value, current_path)
            elif isinstance(value, list):
                # Process lists
                result[key] = process_list(value, current_path)
            elif isinstance(value, str) and is_base64_image(value):
                # This looks like a base64 image, save it and replace with reference
                logger.info(f"🖼️  Found base64 image at {current_path} ({len(value)} chars)")
                result[key] = save_base64_image(value, key)
            elif isinstance(value, str) and len(value) > 1000 and key.endswith('_json'):
                # Special handling for JSON strings that might contain base64 images
                try:
                    logger.info(f"🔍 Processing JSON string at {current_path}")
                    parsed_json = json.loads(value)
                    processed_json = process_json_for_base64(parsed_json, current_path)
                    result[key] = json.dumps(processed_json, default=str)
                    logger.info(f"✅ Processed JSON string at {current_path}")
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Failed to parse JSON at {current_path}, treating as regular string")
                    if len(value) > 10000:
                        result[key] = f"[LARGE_STRING_TRUNCATED: {len(value)} chars]"
                    else:
                        result[key] = value
                except Exception as e:
                    logger.error(f"❌ Error processing JSON at {current_path}: {e}")
                    if len(value) > 10000:
                        result[key] = f"[LARGE_STRING_TRUNCATED: {len(value)} chars]"
                    else:
                        result[key] = value
            elif isinstance(value, str) and len(value) > 10000:
                # Fallback: any very large string gets truncated
                logger.warning(f"⚠️  Fallback truncation of large string at {current_path} ({len(value)} chars)")
                result[key] = f"[LARGE_STRING_TRUNCATED: {len(value)} chars]"
            else:
                # Keep the value as-is
                result[key] = value

        return result

    def process_list(obj: list, path: str = "") -> list:
        """Recursively process a list to find and replace base64 images."""
        result = []

        for i, value in enumerate(obj):
            current_path = f"{path}[{i}]"

            # Debug: log large strings to see what we're missing
            if isinstance(value, str) and len(value) > 1000:
                preview = value[:100] + "..." if len(value) > 100 else value
                is_json_like = (value.lstrip().startswith(('[', '{')) and value.rstrip().endswith((']', '}')))
                logger.info(f"🔍 Found large string at {current_path}: {len(value)} chars, JSON-like: {is_json_like}, preview: {preview}")

            if isinstance(value, dict):
                result.append(process_dict(value, current_path))
            elif isinstance(value, list):
                result.append(process_list(value, current_path))
            elif isinstance(value, str) and is_base64_image(value):
                logger.info(f"🖼️  Found base64 image at {current_path} ({len(value)} chars)")
                result.append(save_base64_image(value, f"index_{i}"))
            elif isinstance(value, str) and len(value) > 10000:
                # Fallback: any very large string gets truncated
                logger.warning(f"⚠️  Fallback truncation of large string at {current_path} ({len(value)} chars)")
                result.append(f"[LARGE_STRING_TRUNCATED: {len(value)} chars]")
            else:
                result.append(value)

        return result

    # Add debugging to see payload structure
    logger.info(f"🔍 Processing payload with keys: {list(processed_payload.keys()) if isinstance(processed_payload, dict) else type(processed_payload)}")

    # Process the payload
    processed_payload = process_dict(processed_payload)

    # Log processing statistics
    if images_processed > 0:
        logger.success(f"📊 Processed payload: {images_processed} images saved, {bytes_saved} chars removed from payload")
    else:
        logger.warning("📊 No base64 images found in payload - check detection logic")

    return processed_payload

def _send_log_to_remote(log_payload: Dict, endpoint_url: str, log_description: str,
                       client_id: str = None, test_id: str = None, session_id: str = None,
                       rabbitize_url: str = None, operator: str = None):
    """Helper function to send a log payload to the remote logging endpoint.

    If rabbitize_url and all required IDs are provided, will use the local /feedback endpoint.
    Otherwise falls back to the original remote endpoint.

    Args:
        operator: Optional operator name to categorize the feedback (e.g., "actor", "validator", "corrector")
    """
    # Process the payload to handle large base64 images
    try:
        # Calculate original payload size for debugging
        original_size = len(json.dumps(log_payload, default=str))
        logger.info(f"🔍 Original payload size: {original_size:,} bytes for {log_description}")

        processed_payload = process_payload_for_size_limits(log_payload, client_id, test_id, session_id)

        # Calculate processed payload size for debugging
        processed_size = len(json.dumps(processed_payload, default=str))
        size_reduction = original_size - processed_size
        logger.info(f"🔍 Processed payload size: {processed_size:,} bytes (reduced by {size_reduction:,} bytes)")

        if processed_size > 100000:  # Still over 100KB limit
            logger.warning(f"⚠️  Processed payload still large: {processed_size:,} bytes (limit: ~100KB)")

        logger.debug(f"Processed payload for size limits: {log_description}")
    except Exception as e:
        logger.error(f"❌ Failed to process payload for size limits: {e}")
        # Continue with original payload if processing fails
        processed_payload = log_payload

    # Check if we can use the local feedback endpoint
    if rabbitize_url and client_id and test_id and session_id:
        logger.debug(f"Sending to local feedback: operator={operator}, client_id={client_id}, test_id={test_id}, session_id={session_id}")
    else:
        missing = []
        if not rabbitize_url: missing.append("rabbitize_url")
        if not client_id: missing.append("client_id")
        if not test_id: missing.append("test_id")
        if not session_id: missing.append("session_id")
        logger.warning(f"Cannot use local feedback endpoint, missing: {', '.join(missing)}")

    if rabbitize_url and client_id and test_id and session_id:
        try:
            feedback_payload = {
                "client_id": client_id,
                "test_id": test_id,
                "session_id": session_id,
                "payload": processed_payload
            }

            # Add operator if provided
            if operator:
                feedback_payload["operator"] = operator

            response = requests.post(f"{rabbitize_url}/feedback", json=feedback_payload, timeout=5)
            response.raise_for_status()

            filename = f"feedback_{operator}.json" if operator else "feedback_loop.json"
            logger.success(f"✅ Successfully sent {log_description} to {filename}",
                         {"status_code": response.status_code, "endpoint": f"{rabbitize_url}/feedback"})
            return  # Success, don't try remote endpoint
        except requests.exceptions.HTTPError as e:
            error_detail = {
                "status_code": e.response.status_code if e.response else None,
                "response_text": e.response.text if e.response else None,
                "url": f"{rabbitize_url}/feedback",
                "payload_keys": list(feedback_payload.keys()),
                "operator": operator,
                "client_id": client_id,
                "test_id": test_id,
                "session_id": session_id
            }
            logger.error(f"❌ HTTP Error sending to feedback endpoint: {e}", error_detail)
        except Exception as e:
            logger.warning(f"⚠️ Failed to send to local feedback endpoint: {e}")

    # Original remote endpoint logic
    # try:
    #     response = requests.post(endpoint_url, json=processed_payload, timeout=5)
    #     response.raise_for_status()
    #     logger.debug(f"Successfully sent {log_description} to {endpoint_url}. Status: {response.status_code}")
    # except requests.exceptions.Timeout:
    #     logger.warning(f"Timeout while sending {log_description} to {endpoint_url}")
    # except requests.exceptions.RequestException as e:
    #     logger.warning(f"Error sending {log_description} to {endpoint_url}: {e}")
    # except Exception as e:
    #     logger.error(f"An unexpected error occurred during remote logging of {log_description}: {e}", exc_info=True)

def log_agent_thinking_event(
    event_type: str,
    caller_id: str,
    client_id: str = None,
    test_id: str = None,
    step_number: Optional[int] = None,
    prompt_data: Optional[Dict | str] = None,
    response_data: Optional[Dict | str] = None,
    metadata: Optional[Dict] = None,
    session_id: str = None,
    rabbitize_url: str = None,
    operator: str = None
):
    """Logs a structured event related to agent's thinking or LLM interaction."""
    log_entry = {
        "timestamp_event": time.time(),
        "event_type": event_type,
        "caller_id": caller_id,
    }
    if client_id:
        log_entry["client_id"] = client_id
    if test_id:
        log_entry["test_id"] = test_id
    if step_number is not None:
        log_entry["step_number"] = step_number

    # This part is for the local, potentially nested log_entry
    if prompt_data:
        if isinstance(prompt_data, dict):
            log_entry["prompt_summary"] = strip_base64_from_json(prompt_data)
            images_preview = []
            if "contents" in prompt_data and isinstance(prompt_data["contents"], list):
                for content_item in prompt_data["contents"]:
                    if isinstance(content_item, dict) and "parts" in content_item and isinstance(content_item["parts"], list):
                        for part in content_item["parts"]:
                            if isinstance(part, dict) and "inlineData" in part and \
                               isinstance(part["inlineData"], dict) and "data" in part["inlineData"] and \
                               isinstance(part["inlineData"]["data"], str):
                                images_preview.append(f"Image preview: {part['inlineData']['data'][:60]}...")
            if images_preview:
                log_entry["prompt_images_preview"] = images_preview
        else: # string prompt
            log_entry["prompt_text"] = str(prompt_data)

    if response_data:
        log_entry["response_data"] = response_data

    if metadata:
        log_entry["metadata"] = metadata

    # Local logging with potentially nested structure (good for detailed local inspection)
    # logger.info("🤔 [AGENT_THINKING_EVENT]", log_entry)

    # --- Remote Logging to DuckDB endpoint ---
    remote_log_url = "https://ducksub.grinx.ai/api/save-parquet/recon_gossip"

    # Base fields for any log entry to recon_gossip
    base_log_payload = {
        "timestamp_event": log_entry["timestamp_event"],
        "caller_id": caller_id, # Already defined in the function signature
    }
    if client_id: base_log_payload["client_id"] = client_id
    if test_id: base_log_payload["test_id"] = test_id
    if step_number is not None: base_log_payload["step_number"] = step_number
    # We'll include top-level metadata with each actual message/event logged to gossip
    # as it might be relevant to that specific logged item.
    # If metadata is None, it simply won't be added.

    if event_type == "llm_request" and isinstance(prompt_data, dict) and "contents" in prompt_data:
        current_prompt_messages = prompt_data.get("contents", [])
        if current_prompt_messages:
            # The "current user message" for the prompt is the last one.
            # This contains the latest screenshot and user instructions.
            current_user_turn_message = current_prompt_messages[-1]
            if isinstance(current_user_turn_message, dict):
                log_payload = {
                    **base_log_payload,
                    "event_type": "llm_current_user_message",
                    "message_role": current_user_turn_message.get("role"),
                    "message_parts_json": json.dumps(current_user_turn_message.get("parts"), default=str),
                }
                if metadata: log_payload["metadata_json"] = json.dumps(metadata, default=str)
                _send_log_to_remote(log_payload, remote_log_url, f"llm_current_user_message for {client_id or 'N/A'}/{test_id or 'N/A'}",
                                   client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator=operator)

    elif event_type == "llm_response_success" and isinstance(response_data, dict) and "candidates" in response_data:
        for cand_index, candidate in enumerate(response_data.get("candidates", [])): # Usually one candidate
            if isinstance(candidate, dict) and "content" in candidate and isinstance(candidate["content"], dict):
                model_response_message = candidate["content"]
                log_payload = {
                    **base_log_payload,
                    "event_type": "llm_model_response_message",
                    "message_role": model_response_message.get("role"),
                    "message_parts_json": json.dumps(model_response_message.get("parts"), default=str),
                    "candidate_index": cand_index,
                }
                if metadata: log_payload["metadata_json"] = json.dumps(metadata, default=str)
                _send_log_to_remote(log_payload, remote_log_url, f"llm_model_response_message (cand {cand_index}) for {client_id or 'N/A'}/{test_id or 'N/A'}",
                                   client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator=operator)

    elif event_type == "llm_response_error": # Handling specific LLM error events
        error_details_payload = {}
        if response_data: # This is expected to contain error details from the API call
            if isinstance(response_data, dict):
                error_details_payload["error_details_json"] = json.dumps(response_data, default=str)
            else:
                error_details_payload["error_details_text"] = str(response_data)

        log_payload = {
            **base_log_payload,
            "event_type": event_type, # Preserves "llm_response_error"
            **error_details_payload
        }
        if metadata: log_payload["metadata_json"] = json.dumps(metadata, default=str)
        _send_log_to_remote(log_payload, remote_log_url, f"llm_error_event ({event_type}) for {client_id or 'N/A'}/{test_id or 'N/A'}",
                           client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator=operator)
    else:
        # if isinstance(current_user_turn_message, dict):
        #     log_payload = {
        #         **base_log_payload,
        #         "event_type": "llm_current_user_message",
        #         "message_role": current_user_turn_message.get("role"),
        #         "message_parts_json": json.dumps(current_user_turn_message.get("parts"), default=str),
        #     }
        #     if metadata: log_payload["metadata_json"] = json.dumps(metadata, default=str)
        #     operator = str(operator + '_other')
        #     _send_log_to_remote(log_payload, remote_log_url, f"other ({event_type}) for {client_id or 'N/A'}/{test_id or 'N/A'}",
        #                     client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator=operator)

        current_prompt_messages = prompt_data.get("contents", [])
        if current_prompt_messages:
            # The "current user message" for the prompt is the last one.
            # This contains the latest screenshot and user instructions.
            current_user_turn_message = current_prompt_messages[-1]
            if isinstance(current_user_turn_message, dict):
                log_payload = {
                    **base_log_payload,
                    "event_type": "llm_current_user_message",
                    "message_role": current_user_turn_message.get("role"),
                    "message_parts_json": json.dumps(current_user_turn_message.get("parts"), default=str),
                }
                operator = str(operator + '_other')
                if metadata: log_payload["metadata_json"] = json.dumps(metadata, default=str)
                _send_log_to_remote(log_payload, remote_log_url, f"other_llm_current_user_message for {client_id or 'N/A'}/{test_id or 'N/A'}",
                                   client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator=operator)


    # Note: Other event_types are not explicitly sent to the remote `recon_gossip` log with this logic.
    # They are still logged locally by the `logger.info` call at the beginning of this function.
    # If other specific events need to go to `recon_gossip`, explicit handling for them would be added here.

def clear_firebase_data(client_id: str, test_id: str):
    """
    Clear any existing data for the specified client_id and test_id in Firebase.

    Args:
        client_id: The client ID
        test_id: The test ID

    Returns:
        bool: True if successful, False otherwise
    """
    if not firebase_initialized:
        logger.warning("Firebase not initialized, skipping data clearing")
        return False

    try:
        ref = db.reference(f"recon/{client_id}/{test_id}")
        ref.delete()
        logger.info(f"🗑️ Cleared existing Firebase data for {client_id}/{test_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to clear Firebase data: {e}", exc_info=True)
        return False

def update_task_status(client_id: str, test_id: str, status: str, extra_data: dict = None):
    """
    Update the status of a task in Firebase.

    Args:
        client_id: The client ID
        test_id: The test ID
        status: The new status (success, timeout, failed, error)
        extra_data: Optional additional data to include

    Returns:
        bool: True if successful, False otherwise
    """
    if not firebase_initialized:
        logger.warning("Firebase not initialized, skipping status update")
        return False

    try:
        ref = db.reference(f"recon/{client_id}/{test_id}")

        update_data = {
            "status": status,
            "end_time": time.time(),
            "is_final": True
        }

        if extra_data:
            update_data.update(extra_data)

        ref.update(update_data)
        logger.success(f"✅ Updated task status to '{status}' in Firebase for {client_id}/{test_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update task status in Firebase: {e}", exc_info=True)
        return False

def save_to_gcs(client_id: str, test_id: str, path: str, data, content_type: str = None):
    """
    Save data to Google Cloud Storage and locally to assets folder.

    Args:
        client_id: The client ID
        test_id: The test ID
        path: Path within the recon folder (don't include /recon prefix)
        data: Data to save (bytes for binary data, dict for JSON)
        content_type: Content type of the data

    Returns:
        tuple: (success_bool, public_url or error_message)
    """
    # Prepare data for saving
    save_data = None
    if isinstance(data, bytes):
        # Binary data (images, etc.)
        content_type = content_type or "application/octet-stream"
        save_data = data
    elif isinstance(data, dict) or isinstance(data, list):
        # JSON data
        json_data = json.dumps(data, ensure_ascii=False, default=str)
        content_type = content_type or "application/json"
        save_data = json_data.encode('utf-8')
    elif isinstance(data, str):
        # String data
        content_type = content_type or "text/plain"
        save_data = data.encode('utf-8')
    else:
        logger.error(f"Unsupported data type: {type(data)}")
        return False, f"Unsupported data type: {type(data)}"

    # Save locally to assets folder
    local_full_path = f"assets/recon/{client_id}/{test_id}/{path}"
    try:
        # Create directory structure if it doesn't exist
        local_dir = os.path.dirname(local_full_path)
        os.makedirs(local_dir, exist_ok=True)

        # Save the file locally
        with open(local_full_path, 'wb') as f:
            f.write(save_data)

        logger.info(f"💾 Saved locally: {local_full_path}")
    except Exception as e:
        logger.error(f"❌ Failed to save locally: {e}")
        # Continue with GCS save even if local save fails

    # Save to GCS if initialized
    if True: #not gcs_initialized or gcs_client is None:
        logger.warning("GCS not initialized, only saved locally")
        return True, local_full_path  # Return local path if GCS not available

    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        gcs_full_path = f"recon/{client_id}/{test_id}/{path}"
        blob = bucket.blob(gcs_full_path)

        # Upload to GCS
        blob.upload_from_string(save_data, content_type=content_type)

        # Make the blob publicly readable
        blob.make_public()

        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{gcs_full_path}"
        logger.success(f"☁️ Saved data to GCS and made public: {gcs_full_path}")
        return True, public_url
    except Exception as e:
        logger.error(f"❌ Failed to save data to GCS: {e}", exc_info=True)
        # Even if GCS fails, we have local copy
        return True, local_full_path

def save_debug_data(client_id: str, test_id: str, step: int, screenshot: bytes, ui_elements: List[Dict],
                    matching_elements: List[Dict] = None, intent: str = None,
                    correction_applied: bool = False, step_data: Dict = None):
    """
    Save comprehensive debug data to GCS including screenshots, OCR results, and step metadata.

    Args:
        client_id: The client ID
        test_id: The test ID
        step: The step number
        screenshot: Original screenshot bytes
        ui_elements: OCR-detected UI elements
        matching_elements: Elements matching intent (optional)
        intent: The agent's intent (optional)
        correction_applied: Whether coordinate correction was applied
        step_data: Complete step data (optional)

    Returns:
        dict: Dictionary of success results for each saved item
    """
    if not gcs_initialized or gcs_client is None:
        logger.warning("GCS not initialized, skipping debug data storage")
        return {"success": False, "reason": "GCS not initialized"}

    results = {}
    timestamp = int(time.time())
    #step_folder = f"step_{step}_{timestamp}"
    step_folder = f"step_{step}"

    # 1. Save original screenshot (only if it's valid)
    if screenshot and len(screenshot) > 0:
        try:
            success, url = save_to_gcs(
                client_id, test_id,
                f"{step_folder}/original_screenshot.jpg",
                screenshot,
                "image/jpeg"
            )
            results["original_screenshot"] = {"success": success, "url": url if success else None}
        except Exception as e:
            logger.error(f"❌ Failed to save original screenshot: {e}")
            results["original_screenshot"] = {"success": False, "error": str(e)}
    else:
        logger.warning("Empty screenshot provided, skipping screenshot storage")
        results["original_screenshot"] = {"success": False, "reason": "Empty screenshot"}

    # 2. Save OCR visualization if UI elements exist
    if screenshot and len(screenshot) > 0 and ui_elements and len(ui_elements) > 0:
        try:
            ocr_viz = visualize_ocr_elements(screenshot, ui_elements, matching_elements)
            success, url = save_to_gcs(
                client_id, test_id,
                f"{step_folder}/ocr_visualization.jpg",
                ocr_viz,
                "image/jpeg"
            )
            results["ocr_visualization"] = {"success": success, "url": url if success else None}
        except Exception as e:
            logger.error(f"Failed to create OCR visualization: {e}")
            results["ocr_visualization"] = {"success": False, "error": str(e)}

    # 3. Save OCR metadata (elements detected, matches, etc.)
    ocr_metadata = {
        "timestamp": timestamp,
        "step": step,
        "intent": intent,
        "num_elements_detected": len(ui_elements),
        "elements": [
            {
                "text": el.get("text", ""),
                "confidence": el.get("confidence", 0),
                "center": el.get("center", (0, 0)),
                "bbox": el.get("bbox", (0, 0, 0, 0))
            }
            for el in ui_elements
        ],
        "correction_applied": correction_applied
    }

    if matching_elements:
        ocr_metadata["matching_elements"] = [
            {
                "text": el.get("text", ""),
                "match_score": el.get("match_score", 0),
                "match_reason": el.get("match_reason", ""),
                "center": el.get("center", (0, 0))
            }
            for el in matching_elements
        ]

    try:
        success, url = save_to_gcs(
            client_id, test_id,
            f"{step_folder}/ocr_metadata.json",
            ocr_metadata,
            "application/json"
        )
        results["ocr_metadata"] = {"success": success, "url": url if success else None}
    except Exception as e:
        logger.error(f"Failed to save OCR metadata: {e}")
        results["ocr_metadata"] = {"success": False, "error": str(e)}

    # 4. Save complete step data if provided
    if step_data:
        try:
            # Remove large binary data to avoid storing duplicates
            if "screenshot" in step_data:
                step_data = {**step_data}  # Create a copy
                step_data["screenshot"] = "<binary data removed>"

            success, url = save_to_gcs(
                client_id, test_id,
                f"{step_folder}/step_data.json",
                step_data,
                "application/json"
            )
            results["step_data"] = {"success": success, "url": url if success else None}
        except Exception as e:
            logger.error(f"Failed to save step data: {e}")
            results["step_data"] = {"success": False, "error": str(e)}

    logger.info(f"Saved debug data to GCS for {client_id}/{test_id}/{step_folder}")
    return results

def call_gemini_api(payload, attempt=1, max_attempts=3, timeout=20):
    """
    Call the Gemini API with timeout protection
    """
    try:
        logger.api_call(f"Calling Gemini API (attempt {attempt}/{max_attempts})",
                       endpoint=GEMINI_API_URL.split('?')[0] + "?key=***")
        response = requests.post(
            GEMINI_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.warning(f"⏱️ Gemini API timeout on attempt {attempt}")
        if attempt < max_attempts:
            # Reduce payload size on timeout
            if "contents" in payload and len(payload["contents"]) > 2:
                # Keep only the most recent message
                payload["contents"] = payload["contents"][-2:]
                logger.warning("📉 Reduced payload size due to timeout")
            return call_gemini_api(payload, attempt + 1, max_attempts, timeout)
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request error on attempt {attempt}: {e}")
        if attempt < max_attempts:
            return call_gemini_api(payload, attempt + 1, max_attempts, timeout)
        raise


def strip_base64_from_json(data):
    """Strip base64 data from JSON for logging purposes."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in ["data", "base64"]:
                # Check if this looks like base64 data (long string with specific character set)
                if isinstance(value, str) and len(value) > 100:
                    result[key] = f"[BASE64_DATA_STRIPPED: {len(value)} chars]"
                else:
                    result[key] = strip_base64_from_json(value)
            else:
                result[key] = strip_base64_from_json(value)
        return result
    elif isinstance(data, list):
        return [strip_base64_from_json(item) for item in data]
    else:
        return data

def prune_history(history, max_items=5):
    """
    Prune history to keep it at a manageable size by removing screenshots from older entries.
    This preserves the entire action history and text context while saving memory.

    Args:
        history: The full history list
        max_items: Maximum number of items to keep with screenshots

    Returns:
        list: History with screenshots removed from older entries
    """
    if not history or len(history) <= max_items:
        return history

    # Calculate which entries should keep their screenshots (the most recent max_items)
    keep_screenshot_indices = set(range(len(history) - max_items, len(history)))

    # For older entries, remove screenshots but keep all text context
    screenshot_bytes_removed = 0
    entries_pruned = 0

    for i in range(len(history)):
        if i not in keep_screenshot_indices and 'screenshot' in history[i]:
            # Store the size for logging
            screenshot_size = len(history[i]['screenshot']) if history[i]['screenshot'] else 0
            screenshot_bytes_removed += screenshot_size

            # Remove the screenshot
            history[i]['screenshot'] = b""
            entries_pruned += 1

    logger.info(f"🧹 Pruned screenshots from {entries_pruned} history entries, freed ~{screenshot_bytes_removed/1024:.1f}KB while preserving text context")
    return history

def start_session(rabbitize_url: str, target_url: str, max_retries: int, objective: str, client_id: str, test_id: str) -> str:
    """Start a browser session via the Rabbitize API using /start endpoint.

    Returns:
        str: The sessionId returned by the /start endpoint
    """
    retries = 0
    while retries < max_retries:
        try:
            # Updated to use /start endpoint with just the URL
            payload = {"url": target_url}
            response = requests.post(f"{rabbitize_url}/start", json=payload, timeout=30)
            response.raise_for_status()

            # Extract sessionId from response
            response_data = response.json()
            session_id = response_data.get('sessionId')
            if not session_id:
                raise ValueError("No sessionId returned from /start endpoint")

            logger.success(f"🚀 Session started successfully",
                         {"payload": payload, "session_id": session_id})
            remote_log_url = ''
            log_payload = dict()
            log_payload['objective'] = objective
            _send_log_to_remote(log_payload, remote_log_url, f"other_llm_current_user_message for {client_id or 'N/A'}/{test_id or 'N/A'}",
                    client_id=client_id, test_id=test_id, session_id=session_id, rabbitize_url=rabbitize_url, operator='objective')

            return session_id
        except Exception as e:
            retries += 1
            logger.error(f"❌ Failed to start session (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not start session after {max_retries} attempts")
            time.sleep(5)

def get_screenshot(rabbitize_runs_dir: str, client_id: str, test_id: str, session_id: str, step: int, max_retries: int = 40, retry_delay: int = 12) -> bytes:
    """Fetch the screenshot for the given step from the local filesystem."""
    start_time = time.time()

    # Construct local file path - replacing 'interactive' with session_id
    if step == 0:
        file_path = os.path.join(rabbitize_runs_dir, client_id, test_id, session_id, "screenshots", "start.jpg")
    else:
        file_path = os.path.join(rabbitize_runs_dir, client_id, test_id, session_id, "screenshots", f"{step-1}.jpg")

    fallback_path = os.path.join(rabbitize_runs_dir, client_id, test_id, "latest.jpg")

    for attempt in range(max_retries):
        try:
            # Switch to fallback path after 10 failed attempts
            if attempt >= 10:
                current_path = fallback_path
                logger.info(f"🔄 Switching to fallback screenshot path after {attempt} failed attempts: {fallback_path}")
            else:
                current_path = file_path

            # Check if file exists
            if os.path.exists(current_path):
                with open(current_path, 'rb') as f:
                    content = f.read()
                    elapsed = time.time() - start_time
                    logger.success(f"📸 Screenshot for step {step} fetched successfully",
                                 {"path": current_path, "elapsed": f"{elapsed:.2f}s", "attempts": attempt+1})
                    return content
            else:
                logger.info(f"Screenshot for step {step} not found at {current_path}, retrying in {retry_delay} seconds... (attempt {attempt+1}/{max_retries})")
                time.sleep(retry_delay)

        except Exception as e:
            logger.error(f"Error while fetching screenshot: {e}")
            logger.info(f"Retrying after error (attempt {attempt+1}/{max_retries})")
            time.sleep(retry_delay)

    raise HTTPException(status_code=404, detail=f"Screenshot for step {step} not found after {max_retries} attempts")

def get_dom_md(rabbitize_runs_dir: str, client_id: str, test_id: str, session_id: str, max_retries: int = 3) -> str:
    """Fetch the DOM markdown from the local filesystem."""
    retries = 0
    file_path = os.path.join(rabbitize_runs_dir, client_id, test_id, "latest.md")

    while retries < max_retries:
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    logger.info("DOM markdown fetched successfully")
                    return content
            else:
                logger.warning(f"DOM markdown file not found at {file_path}")
                return ""
        except Exception as e:
            retries += 1
            logger.error(f"Failed to fetch DOM markdown (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                logger.warning(f"Failed to fetch DOM markdown after {max_retries} attempts. Proceeding without it.")
                return ""
            time.sleep(5)

def get_dom_coordinates(rabbitize_runs_dir: str, client_id: str, test_id: str, session_id: str, step: int, max_retries: int = 3) -> Dict:
    """
    Fetch the DOM coordinates data for the given step from the local filesystem.

    Args:
        rabbitize_runs_dir: The base directory for Rabbitize runs
        client_id: The client ID
        test_id: The test ID
        session_id: The session ID
        step: The current step number
        max_retries: Maximum number of retry attempts

    Returns:
        Dictionary containing DOM coordinates data or empty dict if not available
    """
    # Use latest.json for DOM coordinates as discussed
    file_path = os.path.join(rabbitize_runs_dir, client_id, test_id, session_id, "latest.json")

    retries = 0
    start_time = time.time()

    while retries < max_retries:
        try:
            logger.info(f"Fetching DOM coordinates for step {step} (attempt {retries+1}/{max_retries})")

            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    dom_data = json.load(f)
                    elements_count = len(dom_data.get("elements", []))
                    logger.info(f"DOM coordinates fetched successfully for step {step}: {elements_count} elements")
                    return dom_data
            else:
                logger.warning(f"DOM coordinates not found for step {step} at {file_path}, retrying...")
                retries += 1
                time.sleep(2)
                continue

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in DOM coordinates file for step {step}: {e}")
            retries += 1
            time.sleep(2)
        except Exception as e:
            logger.error(f"Unexpected error fetching DOM coordinates for step {step}: {e}")
            retries += 1
            time.sleep(2)

    logger.warning(f"Failed to fetch DOM coordinates for step {step} after {max_retries} attempts")
    return {}

def send_command(rabbitize_url: str, session_id: str, tool_name: str, args: dict, max_retries: int = 3) -> list:
    """Send a command to the Rabbitize API using /execute endpoint."""
    command_map = {
        "click": [":click"],
        "right_click": [":right-click"],
        "middle_click": [":middle-click"],
        "move_mouse": [":move-mouse", ":to", args.get("x"), args.get("y")],
        "click_hold": [":click-hold"],
        "click_release": [":click-release"],
        "keypress": [":keypress", args.get("x")],
        "scroll_wheel_up": [":scroll-wheel-up", args.get("x")],
        "scroll_wheel_down": [":scroll-wheel-down", args.get("x")],
        "report_done": ["report_done"],
    }
    command = command_map.get(tool_name)
    if not command:
        raise ValueError(f"Unknown tool: {tool_name}")

    # Add extra validation for move_mouse coordinates
    if tool_name == "move_mouse":
        x, y = args.get("x"), args.get("y")
        # Log the requested coordinates for debugging
        logger.debug(f"🖱️ Mouse movement requested", {"x": x, "y": y})

        # Validate coordinates are within reasonable bounds
        if x is not None and y is not None:
            if x < 0 or x > 1920 or y < 0 or y > 1080:
                logger.warning(f"Coordinates ({x}, {y}) are outside the expected bounds (0-1920, 0-1080)")
        else:
            logger.warning(f"Missing coordinates for move_mouse: x={x}, y={y}")

    retries = 0
    while retries < max_retries:
        try:
            payload = {"command": command}
            # Updated to use /execute endpoint
            response = requests.post(f"{rabbitize_url}/execute", json=payload, timeout=5)
            response.raise_for_status()
            logger.success(f"✅ Command sent successfully",
                         {"command": command, "session_id": session_id})
            return command
        except Exception as e:
            retries += 1
            logger.error(f"Failed to send command {command} (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not send command after {max_retries} attempts")
            time.sleep(5)

def end_session(rabbitize_url: str, session_id: str, max_retries: int = 3):
    """End a browser session via the Rabbitize API using /end endpoint."""
    retries = 0
    while retries < max_retries:
        try:
            # Updated to use /end endpoint
            response = requests.post(f"{rabbitize_url}/end", json={}, timeout=5)
            response.raise_for_status()
            logger.info(f"Session ended for session_id: {session_id}")
            return
        except Exception as e:
            retries += 1
            logger.error(f"Failed to end session (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                logger.warning(f"Could not end session after {max_retries} attempts, continuing anyway")

def compute_image_hash(image_bytes: bytes) -> str:
    """Compute a perceptual hash of the image for comparison."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(image))
    except Exception as e:
        return 0

def detect_cursor(screenshot: bytes, expected_x: int = None, expected_y: int = None) -> tuple[str, tuple[int, int]]:
    """
    Detect the cursor color and position in a screenshot - optimized for CPU-only environments.

    Args:
        screenshot: The screenshot as bytes
        expected_x: Expected x position of cursor (from last mouse move)
        expected_y: Expected y position of cursor (from last mouse move)

    Returns:
        tuple: (cursor_color, (x, y)) where cursor_color is 'red', 'green', 'blue', or 'not_found'
    """
    logger.debug(f"🔍 Starting cursor detection",
                {"image_size": f"{len(screenshot)} bytes", "expected_coords": f"({expected_x}, {expected_y})"})

    if not screenshot:
        logger.warning("Empty screenshot provided to detect_cursor")
        # If no screenshot and no previous cursor position, assume center of screen
        if expected_x is None or expected_y is None:
            logger.info("No screenshot and no expected position - assuming cursor at center (960, 540)")
            return "not_found", (960, 540)
        return "not_found", (expected_x or 0, expected_y or 0)

    try:
        # Convert screenshot bytes to OpenCV format
        img = cv2.imdecode(np.frombuffer(screenshot, np.uint8), -1)
        if img is None:
            logger.warning("Could not decode screenshot for cursor detection")
            # Return the expected position if available, otherwise center
            if expected_x is not None and expected_y is not None:
                return "not_found", (expected_x, expected_y)
            return "not_found", (960, 540)  # Assume center of 1920x1080 screen

        logger.info(f"Successfully decoded image: shape={img.shape}, type={img.dtype}")

        # Convert to RGB for easier color detection
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        logger.info("Successfully converted image to RGB")

        # Define color ranges for cursor dots with more tolerance
        red_lower = np.array([180, 0, 0])   # More permissive lower bound
        red_upper = np.array([255, 80, 80]) # More permissive upper bound

        green_lower = np.array([0, 180, 0])
        green_upper = np.array([80, 255, 80])

        blue_lower = np.array([0, 0, 180])
        blue_upper = np.array([80, 80, 255])

        # Create masks for each color using a more CPU-efficient approach
        # Use smaller regions if expected coordinates are provided
        if expected_x is not None and expected_y is not None:
            # Define a search region around expected coordinates
            search_radius = 50  # Increased radius to catch more potential cursors
            x_min = max(0, expected_x - search_radius)
            y_min = max(0, expected_y - search_radius)
            x_max = min(img.shape[1], expected_x + search_radius)
            y_max = min(img.shape[0], expected_y + search_radius)

            # Only process the focused region
            region = img_rgb[y_min:y_max, x_min:x_max]

            # Check for each color in the focused region
            for color_name, (lower, upper) in [
                ("red", (red_lower, red_upper)),
                ("green", (green_lower, green_upper)),
                ("blue", (blue_lower, blue_upper))
            ]:
                # Create mask for just this region
                mask = cv2.inRange(region, lower, upper)
                count = cv2.countNonZero(mask)

                if count > 0:
                    # Find coordinates of matching pixels
                    y_indices, x_indices = np.where(mask > 0)

                    if len(x_indices) > 0:
                        # Calculate center of matching pixels
                        cx = int(np.mean(x_indices)) + x_min
                        cy = int(np.mean(y_indices)) + y_min
                        logger.info(f"Found {color_name} cursor at ({cx}, {cy}) in focused region")
                        return color_name, (cx, cy)

        # Check key regions if focused search failed
        key_regions = [
            ((0, 0), (img.shape[1], 150), "top"),  # Top navigation
            ((0, 0), (200, img.shape[0]), "left"),  # Left sidebar
            ((img.shape[1]//2-300, img.shape[0]//2-300),
             (img.shape[1]//2+300, img.shape[0]//2+300), "center")  # Center area
        ]

        for (x1, y1), (x2, y2), region_name in key_regions:
            region = img_rgb[y1:y2, x1:x2]

            for color_name, (lower, upper) in [
                ("red", (red_lower, red_upper)),
                ("green", (green_lower, green_upper)),
                ("blue", (blue_lower, blue_upper))
            ]:
                # Create mask for just this region
                mask = cv2.inRange(region, lower, upper)
                count = cv2.countNonZero(mask)

                if count > 0:
                    # Find coordinates of matching pixels
                    y_indices, x_indices = np.where(mask > 0)

                    if len(x_indices) > 0:
                        # Calculate center of matching pixels
                        cx = int(np.mean(x_indices)) + x1
                        cy = int(np.mean(y_indices)) + y1
                        logger.info(f"Found {color_name} cursor at ({cx}, {cy}) in {region_name} region")
                        return color_name, (cx, cy)

        # If cursor not found and we have expected coordinates, return those
        if expected_x is not None and expected_y is not None:
            logger.warning(f"No cursor found, returning expected position: ({expected_x}, {expected_y})")
            return "not_found", (expected_x, expected_y)

        # No cursor found, no expected position - use center of screen as fallback
        logger.warning("No cursor found, returning center position")
        center_x, center_y = img.shape[1] // 2, img.shape[0] // 2
        return "not_found", (center_x, center_y)

    except Exception as e:
        logger.error(f"Error detecting cursor: {e}", exc_info=True)
        # If we have expected coordinates, return those
        if expected_x is not None and expected_y is not None:
            return "not_found", (expected_x, expected_y)
        # Otherwise return center of 1920x1080 screen
        return "not_found", (960, 540)

def generate_cursor_visualization(screenshot: bytes, cursor_color: str, cursor_position: tuple[int, int]) -> bytes:
    """
    Generate a visualization of the screenshot with the cursor position highlighted.

    Args:
        screenshot: Original screenshot as bytes
        cursor_color: Color of the cursor ('red', 'green', 'blue')
        cursor_position: (x, y) position of the cursor

    Returns:
        bytes: Modified screenshot with cursor highlighted
    """
    if cursor_color == "not_found" or not screenshot:
        return screenshot

    try:
        # Convert bytes to PIL Image
        img = Image.open(io.BytesIO(screenshot))
        draw = ImageDraw.Draw(img)

        # Draw a circle around the cursor position
        x, y = cursor_position
        radius = 30
        color_map = {
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255)
        }
        outline_color = color_map.get(cursor_color, (255, 255, 0))

        # Draw a circle and a crosshair
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), outline=outline_color, width=3)
        draw.line((x-radius, y, x+radius, y), fill=outline_color, width=2)
        draw.line((x, y-radius, x, y+radius), fill=outline_color, width=2)

        # Add text label
        draw.text((x+radius+5, y-10), f"Cursor: {cursor_color}", fill=outline_color)

        # Convert back to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG')
        return output.getvalue()
    except Exception as e:
        logger.warning(f"Error generating cursor visualization: {e}")
        return screenshot

def detect_progress_from_alignment(alignment_text: str) -> bool:
    """Analyze intent alignment text to determine if we're making progress.

    Returns:
        bool: True if making progress, False if stuck or off track
    """
    if not alignment_text or len(alignment_text.strip()) == 0:
        return False

    # Look for positive indicators in the alignment text
    positive_indicators = [
        "successful", "success", "progress", "aligned", "intended",
        "achieved", "moved", "changed", "clicked", "loaded", "appeared",
        "correctly", "as expected", "visible", "displayed"
    ]

    # Look for negative indicators in the alignment text
    negative_indicators = [
        "not aligned", "unsuccessful", "failed", "no change", "same",
        "stuck", "did not", "didn't", "hasn't", "no progress", "not as intended",
        "not working", "unintended", "incorrect", "error", "missing"
    ]

    # Count positive and negative indicators
    positive_count = sum(1 for word in positive_indicators if word.lower() in alignment_text.lower())
    negative_count = sum(1 for word in negative_indicators if word.lower() in alignment_text.lower())

    # Analyze the sentiment of the alignment text
    logger.info(f"Progress analysis: positive={positive_count}, negative={negative_count} in: '{alignment_text}'")

    # If significantly more negative than positive, we're not making progress
    if negative_count > positive_count:
        return False

    # If significantly more positive than negative, we're making progress
    if positive_count > negative_count:
        return True

    # If tied or no indicators found, default based on the presence of negative phrases
    for phrase in ["no change", "did not", "didn't", "hasn't", "same"]:
        if phrase.lower() in alignment_text.lower():
            return False

    # Default to making progress if we can't determine otherwise
    return True

def calculate_dynamic_temperature(stuck_counter: int, is_making_progress: bool, screenshot_distance: int) -> float:
    """Calculate an appropriate temperature based on whether we're stuck or making progress.

    Args:
        stuck_counter: How many consecutive actions have shown little progress
        is_making_progress: Whether we're making progress based on intent alignment
        screenshot_distance: Visual difference between consecutive screenshots

    Returns:
        float: A temperature value between 0.1 and 0.7
    """
    # Base temperature starts higher than the default 0.2
    base_temp = 0.3

    # If we're making good progress and screenshots show changes
    if is_making_progress and screenshot_distance > 10:
        # Lower temperature for more focused behavior
        return max(0.2, base_temp - 0.1)

    # If we're stuck, gradually increase temperature to encourage exploration
    if stuck_counter > 1:
        # Increase temperature based on stuck counter, capped at 0.7
        exploration_boost = min(0.4, stuck_counter * 0.1)
        new_temp = base_temp + exploration_boost
        logger.info(f"Increasing temperature to {new_temp:.2f} due to being stuck for {stuck_counter} steps")
        return new_temp

    # Default to base temperature
    return base_temp

def compare_screenshots(previous_screenshot: bytes, current_screenshot: bytes, last_command: str = None, agent_explanation: str = None, client_id: str = None, test_id: str = None, step: int = None, session_id: str = None, rabbitize_url: str = None) -> tuple:
    """Compare two screenshots using Gemini API and return a description of changes and progress assessment.

    Returns:
        tuple: (changes_description, is_making_progress, has_visual_change)
    """
    if not previous_screenshot or not current_screenshot:
        return "", False, False

    # Validate that both screenshots have actual content
    if len(previous_screenshot) == 0 or len(current_screenshot) == 0:
        logger.warning("Empty screenshot data detected, skipping comparison")
        return "", False, False

    system_instruction = {
        "parts": [{
            "text": """You are analyzing two consecutive screenshots from a browser session to identify what has changed.
            Your task is to briefly and precisely describe what visual changes occurred between the first screenshot (BEFORE)
            and the second screenshot (AFTER). Focus on significant changes like:
            - New elements appearing or disappearing
            - Text or content changes
            - Position changes of elements
            - Color or style changes
            - Mouse cursor position changes (red, green, or blue dot)
            - Any loading or progress indicators

            **IGNORE THE TIMESTAMP CHANGES IN THE LOWER LEFT CORNER, this is expected and normal.

            If the agent's plan or intent is provided, also BRIEFLY assess whether the observed changes align with what the agent was trying to accomplish. You can add one sentence at the end of your description that evaluates if the action had the intended effect.

            Important guidelines:
            - Be factual and objective - only report what you can directly observe
            - Avoid interpretations or speculation about why changes occurred
            - Use precise, measurable terms when possible (e.g., "moved 100px to the right" instead of "moved right")
            - Focus on the most significant changes if there are many
            - Be consistent in your terminology and how you describe similar changes
            - Pay special attention to the position of the cursor (red/green/blue dot)

            Be concise and specific. Limit your response to 1-3 short sentences.
            First describe what visually changed, then assess alignment with agent's intent if provided."""
        }]
    }

    command_context = f" after executing '{last_command}'" if last_command else ""

    # Add agent explanation context if available
    agent_intent = ""
    if agent_explanation and len(agent_explanation.strip()) > 0:
        agent_intent = f" The agent's stated plan was: \"{agent_explanation.strip()}\". Please structure your response as: \"OBSERVED: [visual changes]. INTENT ALIGNMENT: [brief evaluation if the changes align with intent].\""
    else:
        # If no agent explanation, just get visual changes
        agent_intent = " Please describe only what visually changed."

    user_prompt = f"Compare these two consecutive screenshots and describe what changed {command_context}.{agent_intent} Be factual, precise, and objective. Pay special attention to the red/green/blue dot on the screen that indicates where the cursor is placed. Red cursor = cannot click, Green cursor = over a clickable object (link, button, etc), Blue cursor = over a draggable object."

    contents = [
        {
            "role": "user",
            "parts": [
                {"text": user_prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(previous_screenshot).decode("utf-8")}},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(current_screenshot).decode("utf-8")}}
            ]
        }
    ]

    payload = {
        "systemInstruction": system_instruction,
        "contents": contents,
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 10150,
            "stopSequences": []
        }
    }

    logger.debug("📊 Sending screenshot comparison request to Gemini API",
                {"temperature": 0.1, "topP": 0.95, "topK": 40})
    try:
        # Log thinking event before API call
        log_agent_thinking_event(
            event_type="llm_request",
            caller_id="compare_screenshots",
            client_id=client_id, # Note: client_id might be None here if not passed in
            test_id=test_id,   # Note: test_id might be None here
            step_number=step,    # Note: step might be None here
            prompt_data=payload,
            metadata={"context": "screenshot_comparison"},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="validator"
        )

        response = requests.post(GEMINI_API_FLASH_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        response.raise_for_status()
        result = response.json()

        # Log thinking event after API call (success)
        log_agent_thinking_event(
            event_type="llm_response_success",
            caller_id="compare_screenshots",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            response_data=result,
            metadata={"context": "screenshot_comparison"},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="validator"
        )

        changes_description = ""

        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                text = ""
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        text += part["text"]
                changes_description = text.strip()
                logger.info(f"Screenshot comparison result: {changes_description}")
        else:
            logger.warning("No valid text in Gemini API response for screenshot comparison")

        # Calculate if there are visual changes (using phash)
        prev_hash = imagehash.phash(Image.open(io.BytesIO(previous_screenshot)))
        curr_hash = imagehash.phash(Image.open(io.BytesIO(current_screenshot)))
        hash_distance = prev_hash - curr_hash
        has_visual_change = hash_distance > 5  # Threshold can be adjusted

        # Extract intent alignment to determine if we're making progress
        alignment_text = ""
        if "INTENT ALIGNMENT:" in changes_description:
            alignment_text = changes_description.split("INTENT ALIGNMENT:")[1].strip()

        is_making_progress = detect_progress_from_alignment(alignment_text)
        logger.info(f"Progress assessment: making_progress={is_making_progress}, visual_change={has_visual_change}, distance={hash_distance}")

        # Send the screenshot comparison to Firebase if we have client and test IDs
        if False: #firebase_initialized and last_command:
            try:
                # Extract client_id and test_id from the context if present
                client_id = None
                test_id = None
                # This is a bit of a hack, but it works to get the IDs from the URL pattern
                # Format: /api/quick/{client_id}/{test_id}/interactive/screenshots/...
                url_parts = last_command.split('/')
                if len(url_parts) >= 6 and 'interactive' in url_parts:
                    interactive_index = url_parts.index('interactive')
                    if interactive_index >= 3:
                        client_id = url_parts[interactive_index-2]
                        test_id = url_parts[interactive_index-1]

                if client_id and test_id:
                    # Find the current step based on timestamps
                    # We'll use the current time to find the most recent step
                    current_time = time.time()
                    steps_ref = db.reference(f"recon/{client_id}/{test_id}/steps")
                    steps_data = steps_ref.get()

                    if steps_data:
                        # Get the most recent step
                        recent_step = max(steps_data.keys(), key=lambda k: steps_data[k].get('timestamp', 0))

                        # Update that step with the screenshot comparison
                        step_ref = db.reference(f"recon/{client_id}/{test_id}/steps/{recent_step}")
                        step_ref.update({
                            "screenshot_comparison": {
                                "description": changes_description,
                                "is_making_progress": is_making_progress,
                                "has_visual_change": has_visual_change,
                                "visual_distance": hash_distance,
                                "timestamp": current_time
                            }
                        })
                        logger.info(f"Updated step {recent_step} with screenshot comparison in Firebase")
            except Exception as e:
                logger.error(f"Failed to send screenshot comparison to Firebase: {e}")

        # Send the screenshot comparison to Firebase if we have client and test IDs
        if False: #firebase_initialized and client_id and test_id and step is not None:
            try:
                # Update the step with the screenshot comparison data
                step_ref = db.reference(f"recon/{client_id}/{test_id}/steps/{step}")
                step_ref.update({
                    "screenshot_comparison": {
                        "description": changes_description,
                        "is_making_progress": is_making_progress,
                        "has_visual_change": has_visual_change,
                        "visual_distance": hash_distance,
                        "timestamp": time.time()
                    }
                })
                logger.info(f"Updated step {step} with screenshot comparison in Firebase for {client_id}/{test_id}")
            except Exception as e:
                logger.error(f"Failed to send screenshot comparison to Firebase: {e}")

        return changes_description, is_making_progress, has_visual_change
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            error_body = e.response.text
            try:
                error_json = e.response.json()
                logger.info(f"Gemini API returned 400 error: {json.dumps(error_json, indent=2)}")
            except json.JSONDecodeError:
                logger.info(f"Gemini API returned 400 error (non-JSON): {error_body}")
        logger.error(f"HTTP error during screenshot comparison: {e}")
        # Log thinking event after API call (HTTP error)
        log_agent_thinking_event(
            event_type="llm_response_error",
            caller_id="compare_screenshots",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            response_data={"error": str(e), "status_code": e.response.status_code if e.response else None, "response_text": e.response.text if e.response else None},
            metadata={"context": "screenshot_comparison"},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="validator"
        )
        return "", False, False
    except Exception as e:
        logger.error(f"Error during screenshot comparison: {e}")
        # Log thinking event after API call (general error)
        log_agent_thinking_event(
            event_type="llm_response_error",
            caller_id="compare_screenshots",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            response_data={"error": str(e), "traceback": traceback.format_exc()},
            metadata={"context": "screenshot_comparison"},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="validator"
        )
        return "", False, False

def calculate_action_diversity(history: list, window_size: int = 5) -> float:
    """Measures how diverse recent actions have been (0-1 scale).

    A higher score means more unique actions in the recent history.
    A lower score indicates possible loops or repetitive behavior.

    Args:
        history: List of action history items
        window_size: Number of recent actions to consider

    Returns:
        float: Diversity score between 0-1
    """
    if not history:
        return 1.0  # Default to high diversity when no history

    # Get recent actions
    recent = history[-window_size:] if len(history) >= window_size else history

    # Extract action types and coordinates for move_mouse actions
    action_signatures = []
    for item in recent:
        tool_name = item.get('tool_name', '')
        args = item.get('args', {})

        # For move_mouse, include general area of the screen (divide into 9 sectors)
        if tool_name == 'move_mouse' and 'x' in args and 'y' in args:
            x, y = args['x'], args['y']
            # Divide screen into 9 sectors (3x3 grid)
            x_sector = min(2, x // 640)  # 0, 1, or 2 (left, middle, right)
            y_sector = min(2, y // 360)  # 0, 1, or 2 (top, middle, bottom)
            sector = (x_sector, y_sector)
            action_signatures.append((tool_name, sector))
        else:
            # For other actions, just use the tool name and args
            action_signatures.append((tool_name, tuple(sorted(args.items()))))

    # Calculate diversity: unique actions / total actions
    unique_actions = set(action_signatures)
    diversity = len(unique_actions) / len(recent)

    return diversity

def get_next_action(screenshot: bytes, objective: str, history: list, client_id: str = None, test_id: str = None, step: int = None, dom_elements: List[Dict] = None, dom_markdown: str = None, session_id: str = None, rabbitize_url: str = None) -> tuple[str, dict, str, str, int]:
    # Check if the screenshot is empty or invalid
    if not screenshot or len(screenshot) == 0:
        logger.error("Empty screenshot data detected, cannot proceed with action determination")
        raise HTTPException(status_code=500, detail="Invalid screenshot data")

    # First, make sure we have a manageable history size
    history = prune_history(history, max_items=5)

    # Compute the perceptual hash of the current screenshot as a string
    current_hash_str = compute_image_hash(screenshot)

    # Convert the current hash string to an ImageHash object
    try:
        current_hash = imagehash.hex_to_hash(current_hash_str)
    except:
        current_hash = 0

    # Check if the current screenshot is similar to the previous one
    screenshot_reminder = ""
    changes_description = ""
    coordinate_feedback = ""
    is_making_progress = True  # Default to true for first action
    has_visual_change = True   # Default to true for first action
    stuck_counter = 0          # Track consecutive non-productive actions

    # Initialize stuck counter if not present in history
    if len(history) > 0 and "stuck_counter" not in history[-1]:
        for item in history:
            item["stuck_counter"] = 0

    # Calculate action diversity for recent history
    diversity_score = calculate_action_diversity(history)
    logger.info(f"Action diversity score: {diversity_score:.2f}")

    # Prepare diversity feedback
    diversity_feedback = ""
    if diversity_score < 0.3 and len(history) >= 3:
        diversity_feedback = "Your recent actions have been very similar. Try a COMPLETELY different approach - move to a different area of the screen or try a different interaction type."

    # Detect cursor position in the screenshot
    expected_x, expected_y = None, None
    if history and history[-1].get("tool_name") == "move_mouse" and history[-1].get("args"):
        expected_x = history[-1]["args"].get("x")
        expected_y = history[-1]["args"].get("y")

    # If this is the first action, set expected position to center of screen
    if not history:
        expected_x, expected_y = 960, 540  # Center of 1920x1080 screen

    # Call cursor detection function with a simple timeout
    cursor_color, cursor_position = with_timeout(
        detect_cursor,
        args=(screenshot, expected_x, expected_y),
        timeout_duration=5,
        default=("not_found", (expected_x or 960, expected_y or 540))
    )
    logger.info(f"Detected cursor: {cursor_color} at position {cursor_position}")

    # Generate enhanced screenshot with cursor highlighted if found
    enhanced_screenshot = screenshot
    if cursor_color != "not_found":
        try:
            enhanced_screenshot = generate_cursor_visualization(screenshot, cursor_color, cursor_position)
        except Exception as e:
            logger.error(f"Visualization generation failed: {e}", exc_info=True)
            enhanced_screenshot = screenshot  # Fall back to original

    # Prepare DOM elements information if available
    dom_elements_text = ""
    clickable_dom_count = 0
    if dom_elements:
        try:
            dom_elements_text = prepare_dom_elements_for_prompt(dom_elements)
            clickable_dom_count = len(filter_clickable_elements(dom_elements))
            logger.info(f"Added {clickable_dom_count} interactive DOM elements to prompt")
        except Exception as e:
            logger.error(f"Failed to prepare DOM elements for prompt: {e}")

    # Extract OCR elements ONLY when DOM data is insufficient or agent is stuck
    # Priority: DOM elements > OCR fallback
    ocr_elements_text = ""
    should_run_ocr = (
        (not dom_elements_text or clickable_dom_count < 3) or  # Insufficient DOM data
        (stuck_counter > 1)  # Agent is stuck multiple times (more restrictive)
    )

    if should_run_ocr:
        try:
            if screenshot and len(screenshot) > 0:
                logger.info(f"🔍 Using OCR fallback (DOM elements: {clickable_dom_count}, stuck: {stuck_counter > 1})")
                # Use timeout to prevent OCR from blocking
                ui_elements = with_timeout(
                    extract_ui_elements_with_ocr,
                    args=(screenshot,),
                    timeout_duration=3,  # 3 second timeout
                    default=[]
                )
                if ui_elements and len(ui_elements) > 0:
                    # Generate OCR metadata for the LLM
                    ocr_elements_text = generate_ui_element_metadata(ui_elements)
                    logger.info(f"Added {len(ui_elements)} OCR text blocks to prompt")
                else:
                    logger.debug("No OCR text blocks extracted from screenshot")
        except Exception as e:
            logger.error(f"Failed to extract OCR elements for prompt: {e}")
            ocr_elements_text = ""
    else:
        logger.debug(f"Skipping OCR - sufficient DOM data ({clickable_dom_count} elements) and agent not stuck")

    if len(history) >= 1:
        last_hash_str = history[-1].get("screenshot_hash")
        last_command = None
        last_tool_name = history[-1].get("tool_name", "")
        stuck_counter = history[-1].get("stuck_counter", 0)

        # Add special handling for move_mouse feedback
        if last_tool_name == "move_mouse" and history[-1].get("args") is not None:
            last_x = history[-1]["args"].get("x")
            last_y = history[-1]["args"].get("y")
            if last_x is not None and last_y is not None:
                coordinate_feedback = f"Your last mouse move was to coordinates ({last_x}, {last_y}). Remember that x is HORIZONTAL (left to right, 0-1920) and y is VERTICAL (top to bottom, 0-1080). "

                # Add feedback about cursor position vs expected position
                if cursor_color != "not_found":
                    actual_x, actual_y = cursor_position
                    distance = ((actual_x - last_x) ** 2 + (actual_y - last_y) ** 2) ** 0.5
                    if distance > 20:  # If cursor is far from where it was moved
                        coordinate_feedback += f"Note: The cursor is {distance:.1f} pixels away from where you moved it. "

        if history[-1].get("tool_name") and history[-1].get("args") is not None:
            args_str = ", ".join([f"{k}={v}" for k, v in history[-1].get("args", {}).items()])
            last_command = f"{history[-1]['tool_name']}({args_str})"

        # Get a description of changes between the previous and current screenshots
        if len(history) >= 1:
            prev_agent_explanation = history[-1].get("agent_explanation", "")

            # Skip screenshot comparison for performance if we're stuck
            if stuck_counter >= 3:
                logger.info("Skipping screenshot comparison due to being stuck")
                changes_description = "No significant visual changes detected."
                is_making_progress = False
                has_visual_change = False
            else:
                # No ThreadPoolExecutor - use simple compare_screenshots call with timeout
                try:
                    compare_result = with_timeout(
                        compare_screenshots,
                        args=(history[-1].get("screenshot"), screenshot, last_command, prev_agent_explanation, client_id, test_id, step, session_id, rabbitize_url),
                        timeout_duration=8,
                        default=("Screenshot comparison timed out.", False, False)
                    )
                    changes_description, is_making_progress, has_visual_change = compare_result
                except Exception as e:
                    logger.error(f"Screenshot comparison failed: {e}", exc_info=True)
                    changes_description = "Screenshot comparison failed due to error."
                    is_making_progress = False
                    has_visual_change = False

            # Format the changes description if it contains both observed changes and intent alignment
            formatted_changes = changes_description
            if "OBSERVED:" in changes_description and "INTENT ALIGNMENT:" in changes_description:
                parts = changes_description.split("INTENT ALIGNMENT:")
                observed = parts[0].replace("OBSERVED:", "").strip()
                alignment = parts[1].strip()
                formatted_changes = f"{observed} Intent alignment: {alignment}"
                logger.info(f"Intent evaluation: {alignment}")

            # Store both the original and formatted descriptions
            if changes_description and len(history) > 0:
                history[-1]["changes_description"] = formatted_changes
                history[-1]["raw_changes_description"] = changes_description
                logger.info(f"Screenshot comparison with intent evaluation: {formatted_changes}")

            # Update stuck counter based on progress assessment
            if not is_making_progress and not has_visual_change:
                stuck_counter += 1
                logger.info(f"Stuck counter increased to {stuck_counter}")
            else:
                if stuck_counter > 0:
                    logger.info(f"Resetting stuck counter from {stuck_counter} to 0")
                stuck_counter = 0

        if last_hash_str:
            # Convert the last hash string to an ImageHash object
            last_hash = imagehash.hex_to_hash(last_hash_str)
            # Calculate the Hamming distance between the ImageHash objects
            try:
                distance = current_hash - last_hash
            except:
                distance = 0

            logger.info(f"Distance between current and last screenshot: {distance}")
            if distance < 5:  # Threshold can be adjusted
                screenshot_reminder = (
                    "The current screenshot is very similar to the previous one. "
                    "This suggests your last action didn't change the screen significantly. "
                    "Try a different approach."
                )
                # If no visual change, this is evidence of being stuck
                if not has_visual_change and stuck_counter < 1:
                    stuck_counter += 1
                    logger.info(f"Stuck counter increased to {stuck_counter} due to similar screenshots")

    # Create message for most recent actions only
    last_three_actions = history[-3:] if len(history) >= 3 else history
    actions_str = ", ".join([
        f"{turn['tool_name']}({', '.join([f'{k}={v}' for k, v in turn['args'].items()])})"
        if turn['args'] else f"{turn['tool_name']}()"
        for turn in last_three_actions
    ])
    actions_text = (
        "You haven't taken any actions yet."
        if not last_three_actions
        else f"Your last 3 actions were: {actions_str}."
    )

    # Add the coordinate feedback to help model understand the coordinate system
    if coordinate_feedback:
        actions_text += coordinate_feedback

    # Add cursor feedback
    cursor_feedback = ""
    if cursor_color != "not_found":
        x, y = cursor_position
        cursor_meaning = {
            "red": "non-clickable area",
            "green": "clickable element (link, button)",
            "blue": "draggable element"
        }.get(cursor_color, "unknown type")
        cursor_feedback = f"I can see your cursor as a {cursor_color} dot at position ({x}, {y}), indicating a {cursor_meaning}. "
    else:
        if expected_x is not None and expected_y is not None:
            cursor_feedback = f"I cannot see a cursor dot at the expected position ({expected_x}, {expected_y}). The cursor may be over an area where it's not visible or the move_mouse command did not place it as expected. "

    # Add diversity feedback to action text if needed
    if diversity_feedback:
        actions_text += f" {diversity_feedback}"

    # Add the changes description to the feedback text
    if changes_description and len(history) >= 1:
        if history[-1].get("tool_name") and history[-1].get("args") is not None:
            args_str = ", ".join([f"{k}={v}" for k, v in history[-1].get("args", {}).items()])
            last_command = f"{history[-1]['tool_name']}({args_str})"
            formatted_description = history[-1].get("changes_description", changes_description)
            actions_text += f" Since you executed {last_command}, {formatted_description}"

    # Add element information to the prompt - prioritize DOM over OCR
    if dom_elements_text:
        dom_elements_intro = f"\n\nThe page contains these {clickable_dom_count} interactive elements you can interact with:\n"
        actions_text += dom_elements_intro + dom_elements_text

        # If we also have OCR data, present it as supplementary
        if ocr_elements_text:
            ocr_elements_intro = "\n\nAdditional text elements detected visually (for reference):\n"
            actions_text += ocr_elements_intro + ocr_elements_text
    elif ocr_elements_text:
        # Only OCR data available (fallback mode)
        ocr_elements_intro = "\n\nText elements detected on the screen (visual detection - DOM data unavailable):\n"
        actions_text += ocr_elements_intro + ocr_elements_text

    # Add DOM markdown content to the prompt (only for current step)
    if dom_markdown and len(dom_markdown.strip()) > 0:
        # Truncate if it's very large to avoid token limits
        max_markdown_length = 10000  # Adjust based on token limits and importance
        truncated_markdown = dom_markdown[:max_markdown_length]
        if len(dom_markdown) > max_markdown_length:
            truncated_markdown += "\n... [content truncated due to length]"

        dom_markdown_intro = "\n\nHere is the page content in text form (this is the raw text extracted from the DOM):\n"
        dom_markdown_intro += "```markdown\n"
        actions_text += dom_markdown_intro + truncated_markdown + "\n```"
        logger.info(f"Added DOM markdown content to prompt ({len(truncated_markdown)} chars)")

    # Add visual verification prompt when stuck
    visual_verification = ""
    if stuck_counter >= 2:
        visual_verification = (
            "\n\n**VISUAL VERIFICATION REQUIRED**: "
            f"I {'can' if cursor_color != 'not_found' else 'cannot'} see the cursor in the current screenshot. "
        )
        if cursor_color != "not_found":
            x, y = cursor_position
            visual_verification += f"It appears as a {cursor_color} dot at position ({x}, {y}). "
            if cursor_color == "red":
                visual_verification += "This indicates you're over a non-clickable area. Try moving to something that looks clickable. "
            elif cursor_color == "green":
                visual_verification += "This indicates you're over a clickable element! You can try clicking now. "
            elif cursor_color == "blue":
                visual_verification += "This indicates you're over a draggable element. "
        else:
            visual_verification += (
                "Please look carefully at the screenshot and describe what you see at your current cursor position. "
                "Is there anything that looks clickable near where your cursor should be? "
                "If you can't see a cursor dot (red/green/blue), try moving to a more obvious clickable element like a button or link. "
            )

    # Add stuck guidance if necessary
    stuck_guidance = ""
    if stuck_counter >= 3:
        stuck_guidance = (
            "\n\nYou appear to be stuck. Try these strategies IN ORDER (don't skip ahead):"
            "\n1. LOOK VERY CAREFULLY for the dot indicating your cursor position (RED = non-clickable area, GREEN = clickable link/button, BLUE = draggable element)"
            "\n2. Move to a COMPLETELY DIFFERENT part of the page (if you were in top-left, try bottom-right)"
            "\n3. Try scrolling the page to see more content (scroll_wheel_down with x=150)"
            "\n4. Look for and try clicking on navigation elements (tabs, menus, links)"
            "\n5. Look for any content that might be relevant to the task"
        )

    # Enhanced cursor emphasis
    cursor_emphasis = (
        "\n\n**CRITICAL CURSOR INSTRUCTION**: After each move_mouse action, you MUST look for "
        "the colored dot showing your cursor position. The dot will be RED (non-clickable), "
        "GREEN (clickable link/button), or BLUE (draggable element). "
        "If you don't see the cursor dot, you CANNOT click anything - try another move_mouse "
        "action to a more obviously interactive element."
    )

    # Strategy shift requirement
    strategy_shift = (
        "\n\n**STRATEGY SHIFT REQUIREMENT**: If you've tried the same approach 2-3 times without "
        "success (e.g., clicking in the same area), you MUST try something COMPLETELY different. "
        "Move to a different section of the page, try scrolling, or interact with a different "
        "type of element."
    )

    # Truncate system instruction text to avoid oversized requests
    system_instruction_text = f"""You are a browser automation assistant. Your ONLY goal is to achieve: {objective}.

            You control a mouse and keyboard interacting with a web browser. You will receive a screenshot after EACH action, showing the current state of the browser. You MUST use these screenshots to understand what is happening and to plan your next action. TREAT THE SCREENSHOTS AS YOUR EYES. TREAT THE MOUSE CURSOR AS YOU FINGERS. MOVE IT OVER THINGS YOU ARE CONSIDERING. GREEN DOT = CLICKABLE, BLUE DOT = DRAGGABLE.

            **EXTREMELY IMPORTANT RESPONSE FORMAT**
            1. ALWAYS first give a brief explanation (2-3 sentences) describing what you currently see on the screen and your plan
            2. THEN make your function call

            NEVER SKIP THE EXPLANATION PART! The explanation is just as important as the function call.

            **VERY IMPORTANT INSTRUCTIONS - READ AND FOLLOW THESE CAREFULLY:**

        1. **Screenshot Analysis is EVERYTHING:**  Your ONLY source of information about the browser is the sequence of screenshots.
        2. **Mouse Movement is MANDATORY Before Clicking:**  You *CANNOT* click unless you've first used move_mouse.
        3. **The Red/Green/Blue Dot:** After each move_mouse action, look for a small RED/GREEN/BLUE DOT showing the cursor.
        4. **CURSOR COLOR MEANING:**
           - RED DOT = cursor is over a non-clickable area
           - GREEN DOT = cursor is over a clickable link, button, or element
           - BLUE DOT = cursor is over a draggable element
        5. **MUST VERIFY CURSOR:** Always verify you see the cursor dot before clicking.
        6. **Use Provided Element Data:** You'll receive both DOM elements and OCR text data with precise coordinates. Use these to guide your mouse movements instead of guessing coordinates.
        7. **When You Are Finished:**  If you have achieved the objective, use the report_done action.
        8. **IF AT FIRST YOU DON'T SUCCEED, TRY SOMETHING COMPLETELY DIFFERENT.**
        {cursor_emphasis}{strategy_shift}{visual_verification}{stuck_guidance}

            Available tools and their arguments:
            - click:  args: {{}}  // Requires PRIOR move_mouse
            - right_click: args: {{}}  // Requires PRIOR move_mouse
            - middle_click: args: {{}}  // Requires PRIOR move_mouse
            - move_mouse: args: {{ "x": <integer>, "y": <integer> }}
            - click_hold: args: {{}}
            - click_release: args: {{}}
            - scroll_wheel_up: args: {{ "x": <integer> }} // x is the number of 100-pixel ticks
            - scroll_wheel_down: args: {{ "x": <integer> }} // x is the number of 100-pixel ticks
            - report_done: args: {{ "feedback": "<string>"}}  // Use this when the objective is complete
            """

    system_instruction = {
        "parts": [{
            "text": system_instruction_text
        }]
    }

    user_prompt_text = f"Here is the current screen. {actions_text} {screenshot_reminder} {cursor_feedback} What do you see, what is your plan, and what is your next action? First, describe briefly what you see and your plan, then provide the function call."

    # Add specific coordinate guidance
    user_prompt_text += " IMPORTANT COORDINATE REMINDER: When using move_mouse, specify x,y coordinates where x is HORIZONTAL (0-1920, increases as you move RIGHT) and y is VERTICAL (0-1080, increases as you move DOWN). Use precise coordinates, and aim directly for clickable elements."

    # Add prompt for explanation
    user_prompt_text += " REQUIRED RESPONSE FORMAT: 1) First, provide a brief explanation of what you see and your plan. 2) Then make your function call. Both parts are required for every response."

    # Add emphasis on finding the cursor dot when stuck
    if stuck_counter >= 2:
        user_prompt_text += " CRITICAL: Look for the colored dot (RED/GREEN/BLUE) showing your cursor position before clicking. If you don't see it, move the cursor to a more visible area."

        # Add cursor detection result info to the prompt
        if cursor_color != "not_found":
            x, y = cursor_position
            user_prompt_text += f" I have detected a {cursor_color} cursor at position ({x}, {y})."
        else:
            user_prompt_text += " I could not detect any cursor dot in the current screenshot."

    logger.info(f"Current Feedback: {actions_text} {screenshot_reminder} {cursor_feedback}")


    payload = dict()
    payload['actions_text'] = actions_text
    payload['screenshot_reminder'] = screenshot_reminder
    payload['cursor_feedback'] = cursor_feedback
    #payload['contents'] = payload

    # Log thinking event before API call
    log_agent_thinking_event(
        event_type="llm_request",
        caller_id="get_next_action",
        client_id=client_id,
        test_id=test_id,
        step_number=step,
        prompt_data=payload, # Send the full payload for detailed logging
        metadata=payload,
        #metadata={"attempt": attempt + 1, "temperature": current_temp, "diversity_score": diversity_score, "stuck_counter": stuck_counter},
        session_id=session_id,
        rabbitize_url=rabbitize_url,
        operator="evaluator"
    )

    contents = []
    # Calculate which turns should include images (only the last 3)
    keep_image_indices = set(range(max(0, len(history) - 3), len(history)))

    # Process ALL history entries, not just the last 3
    for i, turn in enumerate(history):
        # For image inclusion calculation, we need to know if this is one of the last 3 entries
        include_image = i >= len(history) - 3

        user_parts = []
        if include_image and turn.get('screenshot') and len(turn.get('screenshot', b'')) > 0:
            # Store reference to the image to avoid duplicate encoding
            encoded_image = base64.b64encode(turn['screenshot']).decode("utf-8")
            logger.debug(f"Including screenshot for history turn {i}, image size: {len(encoded_image)} chars")
            user_parts.append({"text": "This was the screen state that led to your following action."}) # Text first
            user_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": encoded_image}})
        elif not include_image: # Older history, screenshot pruned from prompt
            args_str = ", ".join([f"{k}={v}" for k, v in turn.get('args', {}).items()])
            text_summary = f"Reviewing an older step: You explained: \"{turn.get('agent_explanation', 'No explanation provided for that step.')}\" "
            text_summary += f"You then called tool: {turn.get('tool_name', 'unknown_tool')}({args_str}). "
            if turn.get('changes_description'):
                 text_summary += f"The observed outcome at that time was: \"{turn.get('changes_description')}\"."
            else:
                 text_summary += "No specific outcome change was recorded for that step."
            user_parts.append({"text": text_summary})
            logger.debug(f"Excluding image for history turn {i}, providing text summary instead.")
        elif not turn.get('screenshot') or len(turn.get('screenshot', b'')) == 0:
            # Should ideally not happen if prune_history works, but as a fallback
            user_parts.append({"text": f"Previous state (visuals for turn {i} are unavailable). Your action is documented below."})
            logger.warning(f"Screenshot data missing for history turn {i} when attempting to build prompt.")

        # Only add user message if user_parts is not empty
        if user_parts:
            contents.append({
                "role": "user",
                "parts": user_parts
            })
        else: # Should not happen with the logic above, but good to log
            logger.warning(f"No user parts generated for history turn {i}")

        # Add the model's response - include both explanation and function call
        model_parts = []
        if turn.get("agent_explanation"):
            model_parts.append({"text": turn["agent_explanation"]})
        model_parts.append({"functionCall": {"name": turn["tool_name"], "args": turn["args"]}})

        contents.append({
            "role": "model",
            "parts": model_parts
        })

    # Validate current screenshot before adding to request
    if screenshot and len(screenshot) > 0:
        # Use the enhanced screenshot with cursor highlighted if available
        screenshot_to_use = enhanced_screenshot if cursor_color != "not_found" else screenshot
        encoded_current_image = base64.b64encode(screenshot_to_use).decode("utf-8")
        logger.debug(f"Current screenshot size: {len(encoded_current_image)} chars")

        contents.append({
            "role": "user",
            "parts": [
                {"text": user_prompt_text},
                {"inlineData": {"mimeType": "image/jpeg", "data": encoded_current_image}}
            ]
        })
    else:
        logger.error("Current screenshot is empty, cannot create valid API request")
        raise HTTPException(status_code=500, detail="Invalid screenshot data")

    # Determine the appropriate temperature based on stuck status and diversity
    # Apply higher temperature when diversity is low to encourage exploration
    diversity_boost = 0.0
    if diversity_score < 0.4:
        # Add up to 0.2 temperature boost for low diversity
        diversity_boost = 0.2 * (1.0 - diversity_score)
        logger.info(f"Adding diversity boost to temperature: +{diversity_boost:.2f}")

    # Combine stuck counter boost with diversity boost
    dynamic_temp = calculate_dynamic_temperature(stuck_counter, is_making_progress,
                                              current_hash - imagehash.hex_to_hash(history[-1].get("screenshot_hash", "0")) if len(history) > 0 else 0)

    # Apply diversity boost
    dynamic_temp += diversity_boost
    dynamic_temp = min(0.9, dynamic_temp)  # Cap at 0.9 to avoid extreme randomness

    # Try up to 3 times to get a valid response with function call
    for attempt in range(3):
        # Increase temperature slightly on each retry
        current_temp = dynamic_temp + (attempt * 0.1)
        current_temp = min(0.9, current_temp)  # Cap at 0.9

        payload = {
            "systemInstruction": system_instruction,
            "contents": contents,
            "tools": TOOLS,
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {
                "temperature": current_temp,
                "topP": 0.95,
                "topK": 40,
                "maxOutputTokens": 10150,
                "stopSequences": []
            }
        }

        # Log the stripped version of the payload (without base64 data)
        stripped_payload = strip_base64_from_json(payload)

        logger.api_call(f"Requesting next action from Gemini API",
                       endpoint="Gemini API",
                       payload={
                           "temperature": current_temp,
                           "diversity": f"{diversity_score:.2f}",
                           "stuck_counter": stuck_counter,
                           "attempt": f"{attempt+1}/3",
                           "payload_size": f"{len(str(stripped_payload))} chars"
                       })

        # Log thinking event before API call
        log_agent_thinking_event(
            event_type="llm_request",
            caller_id="get_next_action",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            prompt_data=payload, # Send the full payload for detailed logging
            metadata={"attempt": attempt + 1, "temperature": current_temp, "diversity_score": diversity_score, "stuck_counter": stuck_counter},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="actor"
        )

        try:
            # Use the timeout-protected API call function
            try:
                result = call_gemini_api(payload, timeout=25)
                logger.info(str(result))

                # Log thinking event after API call (success)
                log_agent_thinking_event(
                    event_type="llm_response_success",
                    caller_id="get_next_action",
                    client_id=client_id,
                    test_id=test_id,
                    step_number=step,
                    response_data=result,
                    metadata={"attempt": attempt + 1},
                    session_id=session_id,
                    rabbitize_url=rabbitize_url,
                    operator="actor"
                )

                # Parse the response
                candidate = result["candidates"][0]
                text_feedback = ""
                function_call = None

                # Extract text and function call from the response
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        text_feedback += part["text"] + " "
                    elif "functionCall" in part:
                        if function_call is None:
                            function_call = part["functionCall"]

                # If we got a function call, process it and return
                if function_call is not None:
                    # Ensure we have explanatory text
                    if not text_feedback.strip():
                        logger.warning("Model did not provide explanatory text before function call, adding default explanation")
                        tool_name = function_call["name"]
                        args = function_call.get("args", {})

                        # Generate a more contextual default explanation based on the tool being used
                        if tool_name == "move_mouse":
                            x, y = args.get("x", 0), args.get("y", 0)
                            text_feedback = f"I need to interact with an element. Moving to coordinates ({x}, {y})."
                        elif tool_name == "click":
                            text_feedback = f"I see a clickable element at the cursor position and will click it."
                        elif "scroll" in tool_name:
                            direction = "up" if tool_name == "scroll_wheel_up" else "down"
                            amount = args.get("x", 0)
                            text_feedback = f"Scrolling {direction} to see more content."
                        elif tool_name == "report_done":
                            text_feedback = "I've completed the objective."
                        else:
                            text_feedback = f"Using {tool_name} to interact with the page."

                    # Clean up text feedback
                    text_feedback = text_feedback.strip()

                    # Check for short explanations
                    if len(text_feedback.split()) < 10:  # If fewer than 10 words
                        logger.warning(f"Model provided unusually short explanation: '{text_feedback}'")
                        # If too short, augment it with context based on the tool
                        tool_name = function_call["name"]
                        args = function_call.get("args", {})

                        # Add additional context based on the tool
                        if tool_name == "move_mouse":
                            x, y = args.get("x", 0), args.get("y", 0)
                            text_feedback += f" I'm moving the mouse to coordinates ({x}, {y}) to position over what appears to be an important element."
                        elif tool_name == "click":
                            text_feedback += " I'm clicking to interact with the element where the cursor is currently positioned."

                    tool_name = function_call["name"]
                    args = function_call.get("args", {})
                    feedback = f"Calling {tool_name} with args: {args}"

                    logger.info(f"🤖 Model feedback: [cyan]{text_feedback}[/cyan]")
                    return tool_name, args, feedback, text_feedback, stuck_counter

                # If we got here, no function call was found
                logger.warning(f"No function call in response on attempt {attempt+1}/3, text: {text_feedback[:100]}...")

                # On the last attempt, use a fallback default action
                if attempt == 2:
                    # Default to moving the cursor to the center of the screen or a different region based on stuck counter
                    logger.warning("Using fallback action")

                    # Different fallback actions based on how many times we've been stuck
                    tool_name = "move_mouse"

                    if len(history) == 0:
                        # First action - move to center
                        args = {"x": 960, "y": 540}
                        feedback = f"Falling back to default action: {tool_name} with args: {args}"
                    elif stuck_counter >= 2:
                        # We're stuck - try a different region based on last position
                        if history and history[-1].get("tool_name") == "move_mouse" and history[-1].get("args"):
                            last_x = history[-1]["args"].get("x", 960)
                            last_y = history[-1]["args"].get("y", 540)

                            # Move to a completely different region
                            if last_x < 960 and last_y < 540:  # Top-left → move to bottom-right
                                args = {"x": 1400, "y": 800}
                            elif last_x >= 960 and last_y < 540:  # Top-right → move to bottom-left
                                args = {"x": 400, "y": 800}
                            elif last_x < 960 and last_y >= 540:  # Bottom-left → move to top-right
                                args = {"x": 1400, "y": 200}
                            else:  # Bottom-right → move to top-left
                                args = {"x": 400, "y": 200}
                        else:
                            # No history or last action wasn't move_mouse
                            args = {"x": 800, "y": 400}  # Just pick a reasonable position

                        feedback = f"Falling back to different region: {tool_name} with args: {args}"
                    else:
                        # Not stuck - try scrolling if we've made any move_mouse actions
                        if any(h.get("tool_name") == "move_mouse" for h in history):
                            tool_name = "scroll_wheel_down"
                            args = {"x": 100}
                            feedback = f"Falling back to scrolling: {tool_name} with args: {args}"
                        else:
                            # No move_mouse yet - move to center
                            args = {"x": 960, "y": 540}
                            feedback = f"Falling back to default action: {tool_name} with args: {args}"

                        # Use the text feedback if any was returned, otherwise use a default message
                        if text_feedback.strip():
                            text_feedback = text_feedback.strip() + f" No function call was generated, so I'm going to {tool_name} to {args}."
                        else:
                            text_feedback = f"I need to continue exploring the interface. I'll {tool_name} to {args}."

                        logger.info(f"Using fallback action with feedback: {text_feedback}")
                        return tool_name, args, feedback, text_feedback, stuck_counter

            except (requests.exceptions.HTTPError, requests.exceptions.RequestException,
                    json.JSONDecodeError, KeyError, ValueError, TimeoutError) as e:
                logger.error(f"Error during API request on attempt {attempt+1}/3: {e}")

                # Log thinking event after API call (error)
                log_agent_thinking_event(
                    event_type="llm_response_error",
                    caller_id="get_next_action",
                    client_id=client_id,
                    test_id=test_id,
                    step_number=step,
                    response_data={"error": str(e), "traceback": traceback.format_exc()},
                    metadata={"attempt": attempt + 1},
                    session_id=session_id,
                    rabbitize_url=rabbitize_url,
                    operator="actor"
                )

                # If we're on the last attempt, use a fallback action
                if attempt == 2:
                    logger.warning("Using emergency fallback due to API errors")
                    # Simple fallback - move to center if first action, otherwise try clicking or scrolling
                    tool_name = "move_mouse"
                    args = {"x": 960, "y": 540}

                    if len(history) > 0:
                        # Not the first action - determine what to do based on previous actions
                        last_action = history[-1].get("tool_name", "")

                        if last_action == "move_mouse":
                            # Last action was move_mouse, try clicking
                            tool_name = "click"
                            args = {}
                        elif last_action == "click" or "scroll" in last_action:
                            # Last action was click or scroll, try scrolling down
                            tool_name = "scroll_wheel_down"
                            args = {"x": 100}

                    feedback = f"Emergency fallback due to API errors: {tool_name} with args: {args}"
                    text_feedback = "I'm continuing to explore the interface. API errors prevented detailed analysis."

                    return tool_name, args, feedback, text_feedback, stuck_counter

        except (requests.exceptions.HTTPError, requests.exceptions.RequestException,
                json.JSONDecodeError, KeyError, ValueError, TimeoutError) as e:
            logger.error(f"Error during API request on attempt {attempt+1}/3: {e}")

            # Log thinking event after API call (outer error)
            log_agent_thinking_event(
                event_type="llm_response_error_outer",
                caller_id="get_next_action",
                client_id=client_id,
                test_id=test_id,
                step_number=step,
                response_data={"error": str(e), "traceback": traceback.format_exc()},
                metadata={"attempt": attempt + 1},
                session_id=session_id,
                rabbitize_url=rabbitize_url,
                operator="actor"
            )

            # If we're on the last attempt, use a fallback action
            if attempt == 2:
                logger.warning("Using emergency fallback due to API errors")
                # Simple fallback - move to center if first action, otherwise try clicking or scrolling
                tool_name = "move_mouse"
                args = {"x": 960, "y": 540}

                if len(history) > 0:
                    # Not the first action - determine what to do based on previous actions
                    last_action = history[-1].get("tool_name", "")

                    if last_action == "move_mouse":
                        # Last action was move_mouse, try clicking
                        tool_name = "click"
                        args = {}
                    elif last_action == "click" or "scroll" in last_action:
                        # Last action was click or scroll, try scrolling down
                        tool_name = "scroll_wheel_down"
                        args = {"x": 100}

                feedback = f"Emergency fallback due to API errors: {tool_name} with args: {args}"
                text_feedback = "I'm continuing to explore the interface. API errors prevented detailed analysis."

                return tool_name, args, feedback, text_feedback, stuck_counter

    # We should never get here due to fallbacks, but just in case
    logger.error("Failed to get valid response after multiple attempts, using emergency fallback")
    tool_name = "move_mouse"
    args = {"x": 960, "y": 540}
    feedback = "Emergency fallback: moving to center"
    text_feedback = "I need to explore the interface. Moving to the center of the screen."
    return tool_name, args, feedback, text_feedback, stuck_counter

def send_to_firebase(client_id: str, test_id: str, step: int, data: dict):
    """
    Send data to Firebase Realtime Database.

    Args:
        client_id: The client ID
        test_id: The test ID
        step: The current step number
        data: The data to store
    """
    if not firebase_initialized:
        logger.warning("Firebase not initialized, skipping data storage")
        return False

    try:
        # Create reference to the recon node
        ref = db.reference(f"recon/{client_id}/{test_id}/steps/{step}")

        # Add timestamp
        data['timestamp'] = time.time()

        # Set data at the reference
        ref.set(data)

        logger.success(f"✅ Successfully sent step {step} data to Firebase",
                      {"client_id": client_id, "test_id": test_id})
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send data to Firebase: {e}", exc_info=True)
        return False

def coordinate_correction_helper(
    screenshot: bytes,
    intent: str,
    current_position: tuple[int, int],
    cursor_color: str,
    rabbitize_url: str = None,
    rabbitize_runs_dir: str = None,
    client_id: str = None,
    test_id: str = None,
    session_id: str = None,
    step: int = None
) -> tuple[bool, tuple[int, int], str]:
    """
    Helper function to analyze a screenshot when the agent is struggling to click
    on the right element, and automatically find better coordinates.

    Args:
        screenshot: Current screenshot bytes
        intent: Agent's stated intention (from text_feedback)
        current_position: Current cursor position (x, y)
        cursor_color: Current cursor color ("red", "green", "blue", "not_found")
        rabbitize_url: URL for the playwright API (needed for executing moves)
        client_id: Client ID for debugging/logging
        test_id: Test ID for debugging/logging
        step: Current step number

    Returns:
        tuple: (success, new_coordinates, explanation)
    """
    # Only activate for non-clickable (red) cursors or when cursor wasn't found
    if cursor_color != "red" and cursor_color != "not_found":
        return False, current_position, "Cursor is already on a clickable element"

    logger.info(f"🎯 Activating coordinate correction helper",
               {"cursor_color": cursor_color, "position": current_position})

    # APPROACH 1: Use DOM Coordinates (most accurate)
    if step is not None:
        dom_data = get_dom_coordinates(rabbitize_runs_dir, client_id, test_id, session_id, step)

        if dom_data and "elements" in dom_data and len(dom_data["elements"]) > 0:
            logger.info(f"Using DOM coordinates with {len(dom_data['elements'])} elements")

            # Find matching elements based on intent
            matching_elements = find_dom_elements_matching_intent(dom_data, intent)

            # If we found elements, use the highest-scored one
            if matching_elements:
                best_match = matching_elements[0]
                position = best_match.get("position", {})
                match_x = position.get("centerX")
                match_y = position.get("centerY")

                if match_x is not None and match_y is not None:
                    match_score = best_match.get("match_score", 0)
                    tag_name = best_match.get("tagName", "")
                    element_text = best_match.get("text", "")
                    match_reason = best_match.get("match_reason", "")

                    logger.info(f"Found matching element via DOM: {tag_name} '{element_text}' at ({match_x}, {match_y}) with score {match_score}")

                    # Generate visualization for debugging
                    try:
                        dom_viz = visualize_dom_elements(screenshot, dom_data, matching_elements[:5])

                        # Save debug data to GCS if available
                        if client_id and test_id:
                            debug_id = f"dom_correction_{int(time.time())}_{hash(intent) % 10000}"

                            # Store visualization and data
                            save_to_gcs(
                                client_id, test_id,
                                #f"dom_correction_{step}_{int(time.time())}/visualization.jpg",
                                f"dom_correction_{step}/visualization.jpg",
                                dom_viz,
                                "image/jpeg"
                            )

                            # Store matching elements data
                            save_to_gcs(
                                client_id, test_id,
                                #f"dom_correction_{step}_{int(time.time())}/matching_elements.json",
                                f"dom_correction_{step}/matching_elements.json",
                                {
                                    "intent": intent,
                                    "matching_elements": [
                                        {
                                            "tagName": el.get("tagName", ""),
                                            "text": el.get("text", ""),
                                            "match_score": el.get("match_score", 0),
                                            "match_reason": el.get("match_reason", ""),
                                            "position": el.get("position", {})
                                        }
                                        for el in matching_elements[:5]
                                    ],
                                    "step": step,
                                    "timestamp": time.time()
                                }
                            )
                    except Exception as e:
                        logger.error(f"Failed to generate DOM visualization: {e}")

                    # Execute the move if possible
                    if rabbitize_url:
                        try:
                            args = {"x": match_x, "y": match_y}
                            command = send_command(rabbitize_url, session_id, "move_mouse", args)
                            logger.info(f"Executed DOM-guided move to '{element_text}' at ({match_x}, {match_y})")
                            explanation = f"Moved to {tag_name} '{element_text}' at ({match_x}, {match_y}) - {match_reason}"
                            return True, (match_x, match_y), explanation
                        except Exception as e:
                            logger.error(f"Failed to execute DOM-guided move: {e}")
                            # Fall through to other approaches

    # APPROACH 2: OCR-based element detection
    ui_elements = extract_ui_elements_with_ocr(screenshot)
    logger.info(f"Extracted {len(ui_elements)} UI elements using OCR")

    # Try to find matching elements based on intent
    matching_elements = find_elements_matching_intent(ui_elements, intent)

    # If we found promising matches, use the coordinates directly
    if matching_elements:
        best_match = matching_elements[0]  # Take the highest confidence match
        match_x, match_y = best_match["center"]
        logger.info(f"Found matching element via OCR: '{best_match['text']}' at ({match_x}, {match_y})")

        # Only execute if a move is possible
        if rabbitize_url:
            correction_successful = False
            try:
                # Execute the improved move_mouse command
                args = {"x": match_x, "y": match_y}
                command = send_command(rabbitize_url, session_id, "move_mouse", args)
                logger.info(f"Executed OCR-guided move to '{best_match['text']}' at ({match_x}, {match_y})")
                correction_successful = True
            except Exception as e:
                logger.error(f"Failed to execute OCR-guided move: {e}")
                # Fall through to vision model correction

            if correction_successful:
                return True, (match_x, match_y), f"Moved to '{best_match['text']}' at ({match_x}, {match_y}) (OCR-guided)"

    # APPROACH 3: Vision model (last resort)
    # Generate OCR metadata for the vision model
    ocr_metadata = generate_ui_element_metadata(ui_elements)

    # Add DOM element metadata if available
    dom_metadata = ""
    if step is not None and 'dom_data' in locals() and dom_data and "elements" in dom_data:
        dom_elements = filter_clickable_elements(dom_data.get("elements", []))
        dom_metadata = "DOM ELEMENT MAP:\n"

        # Add up to 15 most likely clickable elements
        for i, element in enumerate(dom_elements[:15]):
            tag_name = element.get("tagName", "")
            text = element.get("text", "") or "[no text]"
            position = element.get("position", {})
            x = position.get("centerX", 0)
            y = position.get("centerY", 0)
            dom_metadata += f"{i+1}. {tag_name} '{text}' at ({x}, {y})\n"

    # Create API request with focused prompt
    system_instruction = {
        "parts": [{
            "text": """You are analyzing a screenshot where a browser automation agent
            is trying to click on a specific element but has moved to a position where
            the cursor is red (non-clickable) or not visible.

            Your ONLY task is to find the exact element they're looking for based on their intent,
            and provide the precise coordinates where they should move the mouse instead.

            Look for buttons, tabs, links, or other clickable elements that match their intent.
            If you find it, provide the x,y coordinates of the center of that element.

            Be extremely precise and concise in your response.
            """
        }]
    }

    x, y = current_position
    user_prompt = f"""
    The agent intended to: "{intent}"

    They moved the cursor to position ({x}, {y}) but the cursor shows as {"RED (non-clickable)" if cursor_color == "red" else "not visible"}.

    Here are the text elements detected on the page that might help you:
    {ocr_metadata}

    {dom_metadata}

    Analyze the screenshot and find the exact element they're trying to interact with based on their stated intent.
    Please provide your response in this format ONLY:

    ANALYSIS: [brief explanation of what element you found]
    COORDINATES: [x],[y]

    If you cannot determine the element with confidence, respond with:
    ANALYSIS: Cannot determine target element
    COORDINATES: NONE
    """

    contents = [
        {
            "role": "user",
            "parts": [
                {"text": user_prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(screenshot).decode("utf-8")}}
            ]
        }
    ]

    payload = {
        "systemInstruction": system_instruction,
        "contents": contents,
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 10150,
            "stopSequences": []
        }
    }

    logger.info(f"Sending coordinate correction request to Gemini API with OCR and DOM metadata")
    try:
        # Log thinking event before API call
        log_agent_thinking_event(
            event_type="llm_request",
            caller_id="coordinate_correction_helper",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            prompt_data=payload,
            metadata={"intent": intent, "current_position": current_position, "cursor_color": cursor_color},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="corrector"
        )

        # Use existing API call function with timeout protection
        result = with_timeout(
            call_gemini_api,
            args=(payload,),
            kwargs={"timeout": 15},
            timeout_duration=20,
            default=None
        )

        if not result:
            logger.warning("Coordinate correction API call timed out")
            # Log thinking event after API call (timeout)
            log_agent_thinking_event(
                event_type="llm_response_error",
                caller_id="coordinate_correction_helper",
                client_id=client_id,
                test_id=test_id,
                step_number=step,
                response_data={"error": "API call timed out"},
                metadata={"intent": intent, "current_position": current_position, "cursor_color": cursor_color},
                session_id=session_id,
                rabbitize_url=rabbitize_url,
                operator="corrector"
            )
            return False, current_position, "Analysis timed out"

        # Log thinking event after API call (success)
        log_agent_thinking_event(
            event_type="llm_response_success",
            caller_id="coordinate_correction_helper",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            response_data=result,
            metadata={"intent": intent, "current_position": current_position, "cursor_color": cursor_color},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="corrector"
        )

        # Parse response
        text_response = ""
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    if "text" in part:
                        text_response += part["text"].strip() + " "

        logger.info(f"Coordinate correction response: {text_response}")

        # Extract coordinates using regex
        import re
        analysis = "No analysis provided"
        analysis_match = re.search(r"ANALYSIS:\s*(.+?)(?=COORDINATES:|$)", text_response)
        if analysis_match:
            analysis = analysis_match.group(1).strip()

        coords_match = re.search(r"COORDINATES:\s*(\d+),\s*(\d+)", text_response)
        if coords_match:
            new_x = int(coords_match.group(1))
            new_y = int(coords_match.group(2))

            # Validate coordinates are within reasonable bounds
            if 0 <= new_x <= 1920 and 0 <= new_y <= 1080:
                logger.info(f"Correction found better coordinates: ({new_x}, {new_y}), Analysis: {analysis}")

                # Only execute if a move is possible (we have the playwright URL)
                if rabbitize_url:
                    correction_successful = False
                    try:
                        # Execute the improved move_mouse command
                        args = {"x": new_x, "y": new_y}
                        command = send_command(rabbitize_url, session_id, "move_mouse", args)
                        logger.info(f"Executed corrected move to ({new_x}, {new_y})")
                        correction_successful = True
                    except Exception as e:
                        logger.error(f"Failed to execute corrected move: {e}")
                        return False, current_position, f"Failed to execute move: {e}"

                    if correction_successful:
                        return True, (new_x, new_y), f"Corrected to ({new_x}, {new_y}): {analysis}"
                else:
                    # Just return the coordinates if we can't execute the move
                    return True, (new_x, new_y), f"Found better coordinates ({new_x}, {new_y}): {analysis}"
            else:
                logger.warning(f"Correction returned invalid coordinates: ({new_x}, {new_y})")

        # If we get here, no valid coordinates were found
        logger.info(f"No valid correction coordinates found. Analysis: {analysis}")
        return False, current_position, f"Correction failed: {analysis}"

    except Exception as e:
        logger.error(f"Error in coordinate correction: {e}", exc_info=True)
        # Log thinking event after API call (general error)
        log_agent_thinking_event(
            event_type="llm_response_error",
            caller_id="coordinate_correction_helper",
            client_id=client_id,
            test_id=test_id,
            step_number=step,
            response_data={"error": str(e), "traceback": traceback.format_exc()},
            metadata={"intent": intent, "current_position": current_position, "cursor_color": cursor_color},
            session_id=session_id,
            rabbitize_url=rabbitize_url,
            operator="corrector"
        )
        return False, current_position, f"Correction error: {str(e)}"

def extract_ui_elements_with_ocr(screenshot: bytes) -> List[Dict[str, Any]]:
    """
    Extract meaningful text blocks from a screenshot using OCR.
    Groups individual words into coherent text elements.

    Args:
        screenshot: Screenshot bytes

    Returns:
        List of dictionaries with text blocks and their coordinates
    """
    # Check if the screenshot is valid
    if screenshot is None or len(screenshot) == 0:
        logger.warning("Empty screenshot provided to OCR. Skipping OCR analysis.")
        return []

    # Check if Tesseract OCR is available
    if not HAS_TESSERACT:
        logger.info("Tesseract OCR not available. Skipping OCR-based element detection.")
        return []

    try:
        # Convert screenshot to OpenCV format
        img = cv2.imdecode(np.frombuffer(screenshot, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            logger.warning("Could not decode screenshot for OCR")
            return []

        # Convert to grayscale for better OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        try:
            # Use PSM 6 (uniform block of text) instead of PSM 11 (sparse text) to get better text blocks
            ocr_data = with_timeout(
                pytesseract.image_to_data,
                args=(gray,),
                kwargs={"output_type": pytesseract.Output.DICT, "config": "--psm 6"},
                timeout_duration=5,
                default=None
            )

            if ocr_data is None:
                logger.warning("OCR timed out or failed")
                return []

            # Group words into meaningful text blocks
            text_blocks = []
            current_block = []
            current_line = -1
            min_confidence = 50  # Lower threshold for more text detection

            n_boxes = len(ocr_data['text'])

            for i in range(n_boxes):
                text = ocr_data['text'][i].strip()
                conf = int(ocr_data['conf'][i])
                level = int(ocr_data['level'][i])

                # Skip empty text or very low confidence
                if not text or conf < min_confidence:
                    continue

                # Get line number and block info
                line_num = ocr_data['line_num'][i]
                block_num = ocr_data['block_num'][i]

                # Get bounding box
                x = ocr_data['left'][i]
                y = ocr_data['top'][i]
                w = ocr_data['width'][i]
                h = ocr_data['height'][i]

                word_info = {
                    "text": text,
                    "confidence": conf,
                    "bbox": (x, y, x + w, y + h),
                    "center": (x + w // 2, y + h // 2),
                    "line_num": line_num,
                    "block_num": block_num,
                    "level": level
                }

                # Start a new block if we're on a different line or block
                if current_line != line_num or (current_block and
                    abs(word_info["center"][1] - current_block[-1]["center"][1]) > 10):

                    # Finish the current block if it has content
                    if current_block:
                        text_blocks.append(_create_text_block(current_block))
                        current_block = []

                    current_line = line_num

                current_block.append(word_info)

            # Don't forget the last block
            if current_block:
                text_blocks.append(_create_text_block(current_block))

            # Filter out very short or common words that aren't useful for navigation
            useful_blocks = []
            for block in text_blocks:
                block_text = block["text"].strip()

                # Skip very short single words unless they look like UI elements
                if len(block_text) < 2:
                    continue

                # Skip common single words that don't help with navigation
                if (len(block_text.split()) == 1 and
                    block_text.lower() in ["the", "and", "or", "to", "a", "an", "of", "in", "on", "at", "by", "for", "with", "as", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can"]):
                    continue

                # Skip very low confidence blocks
                if block["confidence"] < 40:
                    continue

                useful_blocks.append(block)

            logger.success(f"🔤 Extracted {len(useful_blocks)} meaningful text blocks from {len(text_blocks)} total blocks using OCR")
            return useful_blocks

        except Exception as e:
            logger.error(f"Error during OCR extraction: {e}", exc_info=True)
            return []

    except Exception as e:
        logger.error(f"Error preparing image for OCR: {e}", exc_info=True)
        return []

def _create_text_block(word_list: List[Dict]) -> Dict[str, Any]:
    """
    Create a text block from a list of words.

    Args:
        word_list: List of word dictionaries

    Returns:
        Combined text block dictionary
    """
    if not word_list:
        return {}

    # Combine text with spaces
    combined_text = " ".join(word["text"] for word in word_list)

    # Calculate average confidence
    avg_confidence = sum(word["confidence"] for word in word_list) / len(word_list)

    # Calculate bounding box that encompasses all words
    min_x = min(word["bbox"][0] for word in word_list)
    min_y = min(word["bbox"][1] for word in word_list)
    max_x = max(word["bbox"][2] for word in word_list)
    max_y = max(word["bbox"][3] for word in word_list)

    # Calculate center point
    center_x = (min_x + max_x) // 2
    center_y = (min_y + max_y) // 2

    return {
        "text": combined_text,
        "confidence": int(avg_confidence),
        "bbox": (min_x, min_y, max_x, max_y),
        "center": (center_x, center_y),
        "area": (max_x - min_x) * (max_y - min_y),
        "word_count": len(word_list)
    }

def find_elements_matching_intent(ui_elements: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    """
    Find UI elements that match the agent's intent based on text similarity.

    Args:
        ui_elements: List of extracted UI elements
        intent: The agent's stated intention

    Returns:
        List of matching elements, sorted by match quality
    """
    if not ui_elements or not intent:
        return []

    # Extract key terms from intent
    intent_lower = intent.lower()
    # Remove common words that don't help identify UI elements
    common_words = ["the", "to", "on", "a", "an", "want", "would", "like", "try", "i", "will", "need", "should", "click", "move", "go"]

    # Extract potential target words from the intent
    target_words = []
    for word in intent_lower.replace("'", "").replace('"', '').split():
        word = word.strip(".,():;!?")
        if len(word) > 2 and word not in common_words:  # Only consider meaningful words
            target_words.append(word)

    logger.info(f"Extracted target words from intent: {target_words}")

    # Score each UI element based on text matching
    scored_elements = []
    for element in ui_elements:
        element_text = element["text"].lower()
        score = 0
        match_reason = ""

        # Perfect match: element text appears exactly in intent
        if element_text in intent_lower:
            score += 100
            match_reason = "exact text match"

        # Word-level matches
        for word in target_words:
            if word in element_text:
                score += 30
                match_reason += f"contains '{word}', "
            elif element_text in word:
                score += 20
                match_reason += f"is part of '{word}', "

        # Prioritize shorter text (likely buttons, links) over paragraphs
        if len(element_text) < 20:
            score += 15

        # Prioritize elements with high OCR confidence
        score += min(element["confidence"] / 10, 10)  # Max 10 points for confidence

        # Only include elements with decent matching score
        if score > 30:  # Arbitrary threshold
            scored_elements.append({
                **element,
                "match_score": score,
                "match_reason": match_reason.strip(", ")
            })

    # Sort by matching score, descending
    return sorted(scored_elements, key=lambda x: x["match_score"], reverse=True)

def generate_ui_element_metadata(ui_elements: List[Dict[str, Any]]) -> str:
    """
    Generate a concise text description of UI elements for use in prompts.

    Args:
        ui_elements: List of UI elements from OCR

    Returns:
        String containing metadata about UI elements
    """
    if not ui_elements:
        return "No text elements detected."

    # Sort elements by confidence and relevance (longer text blocks often more useful)
    sorted_elements = sorted(ui_elements,
                           key=lambda x: (x["confidence"] * 0.7 + len(x["text"]) * 0.3),
                           reverse=True)

    # Take only the top N most relevant elements to avoid overwhelming the model
    top_elements = sorted_elements[:12]

    metadata = "TEXT BLOCKS FOUND:\n"
    for i, element in enumerate(top_elements):
        text = element["text"]
        x, y = element["center"]
        word_count = element.get("word_count", len(text.split()))
        confidence = element["confidence"]

        # Truncate very long text for display
        display_text = text if len(text) <= 40 else text[:37] + "..."

        metadata += f"{i+1}. \"{display_text}\" at ({x}, {y}) [{word_count} words, {confidence}% confident]\n"

    return metadata

def visualize_ocr_elements(screenshot: bytes, ui_elements: List[Dict[str, Any]], matching_elements: List[Dict[str, Any]] = None) -> bytes:
    """
    Generate a visualization of the OCR elements detected on the screenshot.

    Args:
        screenshot: Original screenshot bytes
        ui_elements: List of all detected UI elements
        matching_elements: List of elements that match the intent (optional)

    Returns:
        bytes: Modified screenshot with UI elements highlighted
    """
    if not ui_elements:
        return screenshot

    try:
        # Convert bytes to PIL Image
        img = Image.open(io.BytesIO(screenshot))
        draw = ImageDraw.Draw(img)

        # Draw all detected elements with yellow boxes
        for element in ui_elements:
            x1, y1, x2, y2 = element["bbox"]
            draw.rectangle((x1, y1, x2, y2), outline=(255, 255, 0), width=1)

            # Add small text label with confidence
            confidence = element["confidence"]
            text = element["text"][:10] + "..." if len(element["text"]) > 10 else element["text"]
            draw.text((x1, y1-10), f"{text} ({confidence}%)", fill=(255, 255, 0))

        # If we have matching elements, highlight them in green
        if matching_elements:
            for element in matching_elements:
                x1, y1, x2, y2 = element["bbox"]
                # Draw thicker green box around matching elements
                draw.rectangle((x1-2, y1-2, x2+2, y2+2), outline=(0, 255, 0), width=2)

                # Draw the center point
                cx, cy = element["center"]
                radius = 5
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(0, 255, 0))

                # Add label with score
                if "match_score" in element:
                    score = element["match_score"]
                    draw.text((x1, y2+5), f"Score: {score:.1f}", fill=(0, 255, 0))

        # Convert back to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG')
        return output.getvalue()
    except Exception as e:
        logger.warning(f"Error generating OCR visualization: {e}")
        return screenshot

def find_dom_elements_matching_intent(dom_data: Dict, intent: str) -> List[Dict]:
    """
    Find DOM elements that match the agent's intent based on text and attribute similarity.

    Args:
        dom_data: DOM coordinates data
        intent: The agent's stated intention

    Returns:
        List of matching elements, sorted by match quality
    """
    if not dom_data or not intent or "elements" not in dom_data:
        return []

    # Extract the list of elements
    elements = dom_data.get("elements", [])

    if not elements:
        return []

    # Convert intent to lowercase for case-insensitive matching
    intent_lower = intent.lower()

    # Remove common words that don't help identify UI elements
    common_words = ["the", "to", "on", "a", "an", "want", "would", "like", "try", "i", "will",
                   "need", "should", "click", "move", "go", "it", "is", "am", "are", "can", "could"]

    # Extract target words from the intent
    target_words = []
    for word in intent_lower.replace("'", "").replace('"', '').split():
        word = word.strip(".,():;!?")
        if len(word) > 2 and word not in common_words:
            target_words.append(word)

    logger.info(f"Extracted target words from intent: {target_words}")

    # Score each DOM element based on various factors
    scored_elements = []
    for element in elements:
        # Skip elements that are not visible (outside viewport)
        position = element.get("position", {})
        if position.get("x", -1) < 0 or position.get("y", -1) < 0:
            continue

        # Skip elements with zero width or height
        if position.get("width", 0) <= 0 or position.get("height", 0) <= 0:
            continue

        # Get element properties
        tag_name = element.get("tagName", "").lower()
        element_text = element.get("text", "").lower()
        element_id = element.get("id", "").lower()
        class_names = element.get("classNames", "").lower()
        attributes = element.get("attributes", {})

        # Skip script, style, etc. tags which aren't clickable
        if tag_name in ["script", "style", "meta", "link", "noscript"]:
            continue

        # Initialize score and match reason
        score = 0
        match_reason = ""

        # Prioritize interactive elements
        if tag_name in ["a", "button", "input", "select", "textarea", "label"]:
            score += 30
            match_reason += f"{tag_name} element, "

        # Check for input type
        if tag_name == "input" and "type" in attributes:
            input_type = attributes["type"].lower()
            if input_type in ["submit", "button"]:
                score += 15
                match_reason += f"input type={input_type}, "

        # Exact text match (highest priority)
        if element_text and element_text in intent_lower:
            score += 100
            match_reason += f"text '{element_text}' found in intent, "

        # Word-level text matches
        if element_text:
            for word in target_words:
                if word in element_text:
                    score += 40
                    match_reason += f"contains word '{word}', "
                elif element_text in word:
                    score += 20
                    match_reason += f"is part of word '{word}', "

        # Check ID and class for matches
        if element_id:
            for word in target_words:
                if word in element_id:
                    score += 20
                    match_reason += f"id contains '{word}', "

        # Check attributes (especially href, value, placeholder)
        for attr, value in attributes.items():
            if isinstance(value, str):
                value_lower = value.lower()

                # Check href for links
                if attr == "href" and tag_name == "a":
                    # Look for text in the URL
                    for word in target_words:
                        if word in value_lower:
                            score += 15
                            match_reason += f"href contains '{word}', "

                # Check button/input values
                if attr in ["value", "placeholder", "title", "alt", "aria-label"]:
                    value_lower = value.lower()
                    if value_lower in intent_lower:
                        score += 25
                        match_reason += f"{attr}='{value_lower}' found in intent, "

                    for word in target_words:
                        if word in value_lower:
                            score += 15
                            match_reason += f"{attr} contains '{word}', "

        # Size-based scoring (prioritize reasonably-sized clickable elements)
        # Very small elements might be icons, very large ones might be containers
        width = position.get("width", 0)
        height = position.get("height", 0)

        # Ideal clickable element size (between 20x20 and 300x100)
        if 20 <= width <= 300 and 20 <= height <= 100:
            score += 10
            match_reason += f"good size ({width}x{height}), "

        # Position-based scoring (elements in typical UI locations)
        # Elements in the center, top navbar, or sidebar are often interactive
        x = position.get("centerX", 0)
        y = position.get("centerY", 0)
        viewport_width = dom_data.get("viewport", {}).get("width", 1920)
        viewport_height = dom_data.get("viewport", {}).get("height", 1080)

        # Center area
        center_x = viewport_width / 2
        center_y = viewport_height / 2
        if center_x - 200 <= x <= center_x + 200 and center_y - 200 <= y <= center_y + 200:
            score += 5
            match_reason += "centered position, "

        # Top navbar area
        if 0 <= y <= 100:
            score += 5
            match_reason += "top navbar position, "

        # Only include elements with a reasonable score
        if score >= 30:
            scored_elements.append({
                **element,
                "match_score": score,
                "match_reason": match_reason.strip(", ")
            })

    # Sort by match score (highest first)
    return sorted(scored_elements, key=lambda x: x.get("match_score", 0), reverse=True)

def filter_clickable_elements(dom_elements: List[Dict]) -> List[Dict]:
    """
    Filter DOM elements to keep only those that are likely to be clickable.

    Args:
        dom_elements: List of DOM elements

    Returns:
        Filtered list of clickable elements
    """
    if not dom_elements:
        return []

    clickable_elements = []

    for element in dom_elements:
        tag_name = element.get("tagName", "").lower()
        attributes = element.get("attributes", {})

        # Automatically include standard interactive elements
        if tag_name in ["a", "button", "input", "select", "textarea"]:
            if tag_name != "input" or attributes.get("type", "") not in ["hidden"]:
                clickable_elements.append(element)
                continue

        # Include elements with click/mousedown event handlers
        for attr, value in attributes.items():
            if isinstance(value, str) and any(event in attr.lower() for event in ["click", "mousedown", "touchstart"]):
                clickable_elements.append(element)
                break

        # Include elements with role attributes that indicate interactivity
        role = attributes.get("role", "").lower()
        if role in ["button", "link", "menuitem", "tab", "checkbox", "radio", "switch", "option"]:
            clickable_elements.append(element)
            continue

    return clickable_elements

def prepare_dom_elements_for_prompt(dom_elements: List[Dict], limit: int = 12) -> str:
    """
    Prepare a concise text description of DOM elements for the model prompt.

    Args:
        dom_elements: List of DOM elements
        limit: Maximum number of elements to include

    Returns:
        String with highlighted interactive elements
    """
    if not dom_elements:
        return "No DOM element data available."

    # Filter to focus on interactive elements first
    clickable_elements = filter_clickable_elements(dom_elements)

    # Prioritize elements by position and type
    prioritized_elements = []

    # First add navigation and main action elements
    for element in clickable_elements:
        tag_name = element.get("tagName", "").lower()
        element_text = element.get("text", "").strip()
        position = element.get("position", {})

        # Skip elements with invalid positions
        if position.get("x", -1) < 0 or position.get("y", -1) < 0:
            continue

        # Skip elements with empty text unless they're inputs
        if not element_text and tag_name not in ["input", "button", "select"]:
            continue

        # Prioritize navigation elements (typically at the top)
        if position.get("y", 1000) < 150:
            prioritized_elements.append(element)

        # Prioritize main menu/tabs (often on left side or top)
        if (position.get("x", 1000) < 300 or
            (position.get("y", 1000) < 250 and tag_name in ["a", "button"])):
            prioritized_elements.append(element)

        # Prioritize buttons with action-oriented text
        if tag_name == "button" or element.get("role") == "button":
            if element_text and any(action in element_text.lower()
                                  for action in ["submit", "search", "apply", "ok", "save", "next", "continue"]):
                prioritized_elements.append(element)

    # Add remaining clickable elements
    for element in clickable_elements:
        if element not in prioritized_elements:
            prioritized_elements.append(element)

    # Deduplicate while preserving order
    unique_elements = []
    seen = set()
    for element in prioritized_elements:
        # Create a hashable identifier for the element
        position = element.get("position", {})
        element_id = f"{element.get('tagName')}-{element.get('text')}-{position.get('x')}-{position.get('y')}"
        if element_id not in seen:
            seen.add(element_id)
            unique_elements.append(element)

    # Limit to specified number of elements
    elements_to_show = unique_elements[:limit]

    # Format the elements for the prompt
    prompt_text = "INTERACTIVE ELEMENTS ON PAGE:\n"
    for i, element in enumerate(elements_to_show):
        tag_name = element.get("tagName", "").lower()
        element_text = element.get("text", "").strip()
        if not element_text:
            element_text = "[no text]"
        elif len(element_text) > 50:
            element_text = element_text[:47] + "..."

        position = element.get("position", {})
        x = position.get("centerX", position.get("x", 0) + position.get("width", 0) // 2)
        y = position.get("centerY", position.get("y", 0) + position.get("height", 0) // 2)

        # Add attributes that help identify the element
        attributes = element.get("attributes", {})
        attr_text = ""
        if "href" in attributes and tag_name == "a":
            href = attributes["href"]
            if href and len(href) > 30:
                href = href[:27] + "..."
            attr_text = f" href=\"{href}\""
        elif "placeholder" in attributes:
            attr_text = f" placeholder=\"{attributes['placeholder']}\""
        elif "value" in attributes and attributes["value"]:
            attr_text = f" value=\"{attributes['value']}\""
        elif "aria-label" in attributes and attributes["aria-label"]:
            attr_text = f" aria-label=\"{attributes['aria-label']}\""

        # Format the element line
        prompt_text += f"{i+1}. <{tag_name}{attr_text}> {element_text} at ({x}, {y})\n"

    return prompt_text

def visualize_dom_elements(screenshot: bytes, dom_data: Dict, matching_elements: List[Dict] = None) -> bytes:
    """
    Generate a visualization of the DOM elements on the screenshot.

    Args:
        screenshot: Original screenshot bytes
        dom_data: DOM coordinates data
        matching_elements: List of elements that match the intent (optional)

    Returns:
        bytes: Modified screenshot with DOM elements highlighted
    """
    if not screenshot or not dom_data or "elements" not in dom_data:
        return screenshot

    try:
        # Convert bytes to PIL Image
        img = Image.open(io.BytesIO(screenshot))
        draw = ImageDraw.Draw(img)

        # Create a set of element IDs from matching elements for quicker lookup
        matching_ids = {}
        if matching_elements:
            for i, el in enumerate(matching_elements):
                # Create a unique identifier for the element based on its properties
                el_id = f"{el.get('tagName', '')}-{el.get('text', '')}-{el.get('position', {}).get('x', 0)}-{el.get('position', {}).get('y', 0)}"
                matching_ids[el_id] = i + 1  # Use index+1 as rank

        # Draw all clickable elements with blue outline
        clickable_elements = filter_clickable_elements(dom_data.get("elements", []))
        for element in clickable_elements:
            position = element.get("position", {})
            if position.get("x", -1) < 0 or position.get("y", -1) < 0:
                continue

            x1 = position.get("x", 0)
            y1 = position.get("y", 0)
            x2 = x1 + position.get("width", 0)
            y2 = y1 + position.get("height", 0)

            # Skip tiny or enormous elements
            if x2 - x1 < 5 or y2 - y1 < 5 or x2 - x1 > 1000 or y2 - y1 > 800:
                continue

            # Create element identifier
            el_id = f"{element.get('tagName', '')}-{element.get('text', '')}-{position.get('x', 0)}-{position.get('y', 0)}"

            # Draw blue outline for all clickable elements
            draw.rectangle((x1, y1, x2, y2), outline=(0, 0, 255), width=1)

            # Add a small label with the tag name
            tag_name = element.get("tagName", "").lower()
            draw.text((x1, y1-10), tag_name, fill=(0, 0, 255))

            # If this is a matching element, highlight it more prominently
            if el_id in matching_ids:
                # Use a thicker green outline for matched elements
                draw.rectangle((x1-2, y1-2, x2+2, y2+2), outline=(0, 255, 0), width=2)

                # Add a label with rank and text
                rank = matching_ids[el_id]
                element_text = element.get("text", "")
                text_preview = (element_text[:20] + "...") if len(element_text) > 20 else element_text
                score = element.get("match_score", 0)

                # Draw a more prominent label
                label = f"#{rank} {text_preview} ({score})"
                draw.text((x1, y2+5), label, fill=(0, 255, 0))

                # Draw the center point
                cx = position.get("centerX", (x1 + x2) // 2)
                cy = position.get("centerY", (y1 + y2) // 2)
                radius = 5
                draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(0, 255, 0))

        # Convert back to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG')
        return output.getvalue()
    except Exception as e:
        logger.warning(f"Error generating DOM visualization: {e}")
        return screenshot

# --- FastAPI Endpoints ---

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/debug/cursor-detection")
async def debug_cursor_detection():
    """Debug endpoint to test cursor detection on a sample image."""
    try:
        # Create a test image with known colored dots
        test_img = np.zeros((1080, 1920, 3), dtype=np.uint8)

        # Add a green dot at (500, 300)
        cv2.circle(test_img, (500, 300), 5, (0, 255, 0), -1)

        # Add a red dot at (1000, 500)
        cv2.circle(test_img, (1000, 500), 5, (255, 0, 0), -1)

        # Add a blue dot at (1500, 700)
        cv2.circle(test_img, (1500, 700), 5, (0, 0, 255), -1)

        # Convert to bytes
        success, buffer = cv2.imencode('.jpg', test_img)
        if not success:
            return {"status": "error", "message": "Failed to encode test image"}

        test_image_bytes = buffer.tobytes()

        # Test detection for each expected cursor
        results = []
        for expected_x, expected_y in [(500, 300), (1000, 500), (1500, 700)]:
            color, position = detect_cursor(test_image_bytes, expected_x, expected_y)
            results.append({
                "expected_position": (expected_x, expected_y),
                "detected_color": color,
                "detected_position": position
            })

        # Test detection without expected position
        color, position = detect_cursor(test_image_bytes)
        results.append({
            "expected_position": None,
            "detected_color": color,
            "detected_position": position
        })

        return {
            "status": "success",
            "opencv_version": cv2.__version__,
            "numpy_version": np.__version__,
            "test_image_size": len(test_image_bytes),
            "results": results
        }
    except Exception as e:
        logger.error(f"❌ Error in cursor detection debug: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.get("/debug/ocr-test")
async def debug_ocr_test(url: str = None):
    """
    Debug endpoint to test OCR functionality on a real or generated image.

    Args:
        url: Optional URL of an image to test OCR on

    Returns:
        OCR results and visualization
    """
    try:
        if not HAS_TESSERACT:
            return {
                "status": "error",
                "message": "Tesseract OCR is not available in this environment"
            }

        # If URL is provided, download the image
        if url:
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                test_image_bytes = response.content
                logger.info(f"⬇️ Downloaded test image from URL",
                           {"url": url, "size": f"{len(test_image_bytes)} bytes"})
            except Exception as e:
                return {"status": "error", "message": f"Failed to download image from URL: {e}"}
        else:
            # Create a test image with sample text
            test_img = np.ones((768, 1024, 3), dtype=np.uint8) * 255  # White background

            # Add some sample text to the image
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(test_img, "Login", (100, 100), font, 1, (0, 0, 0), 2)
            cv2.putText(test_img, "Submit", (300, 200), font, 1, (0, 0, 0), 2)
            cv2.putText(test_img, "Cancel", (500, 300), font, 1, (0, 0, 0), 2)
            cv2.putText(test_img, "Click here to continue", (200, 400), font, 1, (0, 0, 0), 2)

            # Add some UI-like elements
            cv2.rectangle(test_img, (95, 75), (155, 115), (200, 200, 200), 2)  # Login button
            cv2.rectangle(test_img, (295, 175), (355, 215), (200, 200, 200), 2)  # Submit button
            cv2.rectangle(test_img, (495, 275), (555, 315), (200, 200, 200), 2)  # Cancel button

            # Convert to bytes
            success, buffer = cv2.imencode('.jpg', test_img)
            if not success:
                return {"status": "error", "message": "Failed to encode test image"}

            test_image_bytes = buffer.tobytes()
            logger.info(f"Created synthetic test image, size: {len(test_image_bytes)} bytes")

        # Run OCR on the image
        ui_elements = extract_ui_elements_with_ocr(test_image_bytes)

        # Create a test intent
        test_intent = "I want to click on the Login button"

        # Find matching elements
        matching_elements = find_elements_matching_intent(ui_elements, test_intent)

        # Generate visualization
        visualization = visualize_ocr_elements(test_image_bytes, ui_elements, matching_elements)

        # Encode visualization as base64 for response
        viz_base64 = base64.b64encode(visualization).decode('utf-8')

        return {
            "status": "success",
            "ocr_enabled": HAS_TESSERACT,
            "num_elements_detected": len(ui_elements),
            "detected_elements": [
                {
                    "text": el["text"],
                    "confidence": el["confidence"],
                    "center": el["center"],
                    "area": el["area"]
                }
                for el in ui_elements
            ],
            "test_intent": test_intent,
            "matching_elements": [
                {
                    "text": el["text"],
                    "match_score": el["match_score"],
                    "match_reason": el.get("match_reason", ""),
                    "center": el["center"]
                }
                for el in matching_elements
            ],
            "visualization_base64": viz_base64
        }
    except Exception as e:
        logger.error(f"Error in OCR test: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.get("/debug/gcs-browse")
async def debug_gcs_browse(client_id: str = None, test_id: str = None, prefix: str = None):
    """
    Debug endpoint to browse GCS storage for recon data.

    Args:
        client_id: Optional client ID to filter
        test_id: Optional test ID to filter
        prefix: Optional path prefix to browse

    Returns:
        List of files in GCS storage
    """
    if not gcs_initialized or gcs_client is None:
        return {
            "status": "error",
            "message": "GCS not initialized"
        }

    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)

        # Build the prefix path
        path_prefix = "recon"
        if client_id:
            path_prefix += f"/{client_id}"
            if test_id:
                path_prefix += f"/{test_id}"
                if prefix:
                    path_prefix += f"/{prefix}"

        # List all blobs with the prefix
        blobs = bucket.list_blobs(prefix=path_prefix, delimiter="/")

        # Extract file information
        files = []
        for blob in blobs:
            # Only include leaf files, not directories
            if not blob.name.endswith('/'):
                files.append({
                    "name": blob.name,
                    "size": blob.size,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "content_type": blob.content_type,
                    "url": f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob.name}"
                })

        # Sort by updated time if available
        files.sort(key=lambda x: x.get("updated", ""), reverse=True)

        return {
            "status": "success",
            "path_prefix": path_prefix,
            "file_count": len(files),
            "files": files
        }
    except Exception as e:
        logger.error(f"Error browsing GCS storage: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.get("/debug/gcs-download")
async def debug_gcs_download(filepath: str):
    """
    Debug endpoint to download a file from GCS storage.

    Args:
        filepath: Path to the file in GCS

    Returns:
        File contents (JSON or base64 encoded for binary)
    """
    if not gcs_initialized or gcs_client is None:
        return {
            "status": "error",
            "message": "GCS not initialized"
        }

    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filepath)

        if not blob.exists():
            return {
                "status": "error",
                "message": f"File not found: {filepath}"
            }

        # Download the content
        content = blob.download_as_bytes()

        # Check content type
        content_type = blob.content_type or ""

        if "json" in content_type:
            # Parse JSON content
            json_content = json.loads(content)
            return {
                "status": "success",
                "content_type": content_type,
                "data": json_content
            }
        elif "image" in content_type or "jpg" in filepath or "jpeg" in filepath or "png" in filepath:
            # Return base64 encoded image
            base64_content = base64.b64encode(content).decode('utf-8')
            return {
                "status": "success",
                "content_type": content_type,
                "data_base64": base64_content
            }
        else:
            # Default to text content
            text_content = content.decode('utf-8', errors='replace')
            return {
                "status": "success",
                "content_type": content_type,
                "data_text": text_content
            }
    except Exception as e:
        logger.error(f"Error downloading from GCS storage: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.post("/start")
async def start_task(task: TaskRequest):
    """Start a browser automation task."""
    logger.info(f"Starting Recon task: {task.dict()}")
    rabbitize_url = task.rabbitize_url
    target_url = task.target_url
    objective = task.objective
    client_id = task.client_id
    test_id = task.test_id
    rabbitize_runs_dir = task.rabbitize_runs_dir
    max_steps = task.max_steps

    try:
        # Start session and get the sessionId from the response
        session_id = start_session(rabbitize_url, target_url, 3, objective, client_id, test_id)
        logger.info(f"Using session_id: {session_id}")
        history = []
        stuck_counter = 0
        last_cursor_color = "not_found"
        last_cursor_position = (960, 540)  # Default to center of screen

        # Initialize task in Firebase
        if False: # firebase_initialized:
            # Clear any existing data for this task first
            clear_firebase_data(client_id, test_id)

            # Store initial information about the task
            task_ref = db.reference(f"recon/{client_id}/{test_id}")
            task_info = {
                "objective": objective,
                "target_url": target_url,
                "client_id": client_id,
                "test_id": test_id,
                "max_steps": max_steps,
                "start_time": time.time(),
                "status": "running"
            }
            task_ref.update(task_info)
            logger.info(f"Initialized task in Firebase: {client_id}/{test_id}")

        # Perform initial OpenCV check
        try:
            # Simple test to ensure OpenCV is working
            test_img = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.circle(test_img, (50, 50), 20, (0, 0, 255), -1)
            logger.info("OpenCV verification successful")
        except Exception as e:
            logger.error(f"OpenCV verification failed: {e}", exc_info=True)

        for step in range(max_steps):
            logger.info(f"Step {step + 1}/{max_steps}")
            try:
                # Get screenshot with extra validation
                screenshot = None
                screenshot_success = False

                for screenshot_attempt in range(3):  # Try up to 3 times to get a valid screenshot
                    try:
                        logger.info(f"Fetching screenshot (attempt {screenshot_attempt + 1}/3)")
                        screenshot = get_screenshot(rabbitize_runs_dir, client_id, test_id, session_id, step, max_retries=13, retry_delay=5)

                        # Validate screenshot data is not empty
                        if not screenshot or len(screenshot) == 0:
                            logger.error(f"Empty screenshot received, retrying...")
                            time.sleep(2)
                            continue

                        # Try to decode the image to verify it's valid
                        img = None
                        try:
                            img = cv2.imdecode(np.frombuffer(screenshot, np.uint8), -1)
                        except Exception as img_e:
                            logger.error(f"Failed to decode screenshot: {img_e}")
                            time.sleep(2)
                            continue

                        if img is None:
                            logger.error("Failed to decode screenshot, retrying...")
                            time.sleep(2)
                            continue

                        # Screenshot is valid
                        logger.info(f"Valid screenshot obtained: {len(screenshot)} bytes, shape: {img.shape}")
                        screenshot_success = True
                        break
                    except Exception as e:
                        logger.error(f"Error getting screenshot: {e}", exc_info=True)
                        time.sleep(2)

                if not screenshot_success or screenshot is None or len(screenshot) == 0:
                    logger.error("Failed to obtain valid screenshot after multiple attempts")
                    end_session(rabbitize_url, session_id)

                    # Update task status to failed
                    if False: # firebase_initialized:
                        update_task_status(client_id, test_id, "failed", {
                            "error": "Failed to obtain a valid screenshot after multiple attempts",
                            "steps_completed": step
                        })

                    return {"status": "failed", "steps": step, "final_feedback": "Failed to obtain a valid screenshot after multiple attempts"}

                # Detect cursor position and color in the screenshot
                expected_x, expected_y = None, None
                if history and history[-1].get("tool_name") == "move_mouse" and history[-1].get("args"):
                    expected_x = history[-1]["args"].get("x")
                    expected_y = history[-1]["args"].get("y")

                # If this is the first action, set expected position to center of screen
                if not history:
                    expected_x, expected_y = 960, 540  # Center of 1920x1080 screen

                # Fetch DOM coordinates early - this provides element information for better targeting
                dom_data = {}
                dom_elements = []
                clickable_dom_elements = []
                try:
                    dom_data = get_dom_coordinates(rabbitize_runs_dir, client_id, test_id, session_id, step, max_retries=2)
                    if dom_data and "elements" in dom_data:
                        dom_elements = dom_data.get("elements", [])
                        clickable_dom_elements = filter_clickable_elements(dom_elements)
                        logger.info(f"DOM coordinates fetched successfully: {len(dom_elements)} elements, {len(clickable_dom_elements)} clickable")
                    else:
                        logger.warning(f"No DOM coordinates data available for step {step}")
                except Exception as e:
                    logger.error(f"Error fetching DOM coordinates: {e}")

                # Fetch DOM markdown for the current step - provides textual content
                dom_markdown = None
                try:
                    dom_markdown = get_dom_md(rabbitize_runs_dir, client_id, test_id, session_id)
                    if dom_markdown and len(dom_markdown.strip()) > 0:
                        dom_markdown_length = len(dom_markdown)
                        logger.info(f"DOM markdown fetched successfully: {dom_markdown_length} chars")
                    else:
                        logger.warning(f"No DOM markdown content available for step {step}")
                except Exception as e:
                    logger.error(f"Error fetching DOM markdown: {e}")

                # Detect cursor position with timeout protection
                cursor_color, cursor_position = with_timeout(
                    detect_cursor,
                    args=(screenshot, expected_x, expected_y),
                    timeout_duration=5,
                    default=("not_found", (expected_x or 960, expected_y or 540))
                )

                # Store cursor information for possible correction
                last_cursor_color = cursor_color
                last_cursor_position = cursor_position

                # Check if coordinate correction is needed
                # Conditions:
                # 1. Last action was move_mouse
                # 2. Cursor is red (non-clickable) or not found
                # 3. We're not at the first step
                # 4. We have a screenshot
                correction_applied = False

                if (len(history) > 0 and
                    history[-1].get("tool_name") == "move_mouse" and
                    (cursor_color == "red" or cursor_color == "not_found") and
                    screenshot is not None and
                    stuck_counter > 0):  # Only try correction if we've been stuck at least once

                    logger.info(f"Conditions met for coordinate correction: cursor={cursor_color}, last_action=move_mouse, stuck={stuck_counter}")

                    # Get the agent's last stated intention
                    agent_intent = history[-1].get("agent_explanation", "")
                    if agent_intent:
                        # Activate coordinate correction helper
                        success, corrected_position, explanation = coordinate_correction_helper(
                            screenshot=screenshot,
                            intent=agent_intent,
                            current_position=cursor_position,
                            cursor_color=cursor_color,
                            rabbitize_url=rabbitize_url,
                            rabbitize_runs_dir=rabbitize_runs_dir,
                            client_id=client_id,
                            test_id=test_id,
                            session_id=session_id,
                            step=step
                        )

                        if success:
                            logger.info(f"Coordinate correction succeeded: {explanation}")
                            correction_applied = True

                            # Update the history - Replace the last move_mouse entry with the corrected coordinates
                            # This makes the main LLM think it actually moved to the correct spot
                            corrected_x, corrected_y = corrected_position

                            # Store the original entry for logging
                            original_entry = dict(history[-1])

                            # Modify the entry in-place (preserve explanation and other metadata)
                            history[-1]["args"]["x"] = corrected_x
                            history[-1]["args"]["y"] = corrected_y
                            history[-1]["feedback"] += f" [Corrected from ({cursor_position[0]}, {cursor_position[1]}) to ({corrected_x}, {corrected_y})]"

                            # Record in Firebase that a correction occurred (if enabled)
                            if False: # firebase_initialized:
                                correction_data = {
                                    "correction": {
                                        "original_coordinates": {"x": cursor_position[0], "y": cursor_position[1]},
                                        "corrected_coordinates": {"x": corrected_x, "y": corrected_y},
                                        "explanation": explanation,
                                        "timestamp": time.time()
                                    }
                                }
                                send_to_firebase(client_id, test_id, f"correction-{step}", correction_data)

                            # Update cursor position for next step
                            cursor_position = corrected_position

                            # If we're lucky, the cursor might now be on a clickable element
                            # We'll detect this in the next screenshot, but for now, assume it might have changed
                            cursor_color = "unknown"  # Will be re-detected on next step

                            logger.info(f"Updated history with corrected coordinates: ({corrected_x}, {corrected_y})")
                        else:
                            logger.info(f"Coordinate correction failed: {explanation}")

                # Get next action from the agent - if a correction was applied, this operates on updated cursor info
                tool_name, args, feedback, text_feedback, stuck_counter = get_next_action(
                    screenshot,
                    objective,
                    history,
                    client_id,
                    test_id,
                    step,
                    dom_elements,
                    dom_markdown,
                    session_id,
                    rabbitize_url
                )

                if tool_name == "report_done":
                    logger.info(f"Objective completed at step {step + 1}")
                    end_session(rabbitize_url, session_id)

                    # Save final step to Firebase
                    if False: # firebase_initialized:
                        firebase_data = {
                            "command": {
                                "tool_name": tool_name,
                                "args": args,
                                "explanation": text_feedback
                            },
                            "feedback": feedback,
                            "is_final": True
                        }
                        send_to_firebase(client_id, test_id, step, firebase_data)

                        # Update task status to success
                        update_task_status(client_id, test_id, "success", {
                            "steps_completed": step,
                            "feedback": feedback,
                            "total_steps": step + 1
                        })

                    return {"status": "success", "steps": step + 1, "final_feedback": feedback}

                screenshot_hash = compute_image_hash(screenshot)
                history.append({
                    "tool_name": tool_name,
                    "args": args,
                    "command": send_command(rabbitize_url, session_id, tool_name, args),
                    "feedback": feedback,
                    "screenshot": screenshot,
                    "screenshot_hash": screenshot_hash,
                    "agent_explanation": text_feedback,
                    "stuck_counter": stuck_counter
                })

                # Cap history size to prevent memory issues
                if len(history) > 10:
                    # Use our prune_history function to retain all entries but clear old screenshots
                    history = prune_history(history, max_items=5)

                # Save step data to Firebase
                if False: # firebase_initialized:
                    # Determine if we have screenshot comparison data for the previous step
                    comparison_data = None
                    if len(history) >= 2 and "changes_description" in history[-2]:
                        comparison_data = history[-2]["changes_description"]

                    firebase_data = {
                        "command": {
                            "tool_name": tool_name,
                            "args": args,
                            "explanation": text_feedback
                        },
                        "feedback": feedback,
                        "step_number": step,
                        "screenshot_comparison": comparison_data,
                        "stuck_counter": stuck_counter,
                        "correction_applied": correction_applied,
                        "dom_markdown_available": bool(dom_markdown and len(dom_markdown.strip()) > 0)
                    }
                    send_to_firebase(client_id, test_id, step, firebase_data)

                # Save comprehensive debug data to GCS
                # Only save every other step to reduce storage usage
                if step % 2 == 0 or correction_applied:
                    try:
                        # Create a step_data object with all relevant information
                        step_data = {
                            "step_number": step,
                            "timestamp": time.time(),
                            "command": {
                                "tool_name": tool_name,
                                "args": args,
                                "explanation": text_feedback
                            },
                            "feedback": feedback,
                            "stuck_counter": stuck_counter,
                            "correction_applied": correction_applied,
                            "dom_markdown_available": bool(dom_markdown and len(dom_markdown.strip()) > 0)
                        }

                        # Include comparison data if available
                        if len(history) >= 2 and "changes_description" in history[-2]:
                            step_data["screenshot_comparison"] = history[-2]["changes_description"]

                        # If DOM markdown is available, save truncated version for debugging
                        if dom_markdown and len(dom_markdown.strip()) > 0:
                            # Save it as a separate file to avoid bloating the step data
                            save_to_gcs(
                                client_id=client_id,
                                test_id=test_id,
                                #path=f"step_{step}_{int(time.time())}/dom_markdown.md",
                                path=f"step_{step}/dom_markdown.md",
                                data=dom_markdown[:50000] if len(dom_markdown) > 50000 else dom_markdown,  # Truncate very large DOM markdown
                                content_type="text/markdown"
                            )
                            logger.info(f"Saved DOM markdown content to GCS for step {step}")

                        # Extract OCR data if we're at a step where corrections might be needed
                        # (after move_mouse actions or when stuck)
                        extract_ocr = False
                        if (tool_name == "move_mouse" or
                            (len(history) > 0 and history[-1].get("tool_name") == "move_mouse") or
                            stuck_counter > 0):
                            extract_ocr = True

                        if extract_ocr:
                            ui_elements = extract_ui_elements_with_ocr(screenshot)
                            if ui_elements:
                                # Find potential matches based on the agent's explanation
                                matching_elements = find_elements_matching_intent(ui_elements, text_feedback)

                                # Save everything to GCS
                                save_debug_data(
                                    client_id=client_id,
                                    test_id=test_id,
                                    step=step,
                                    screenshot=screenshot,
                                    ui_elements=ui_elements,
                                    matching_elements=matching_elements,
                                    intent=text_feedback,
                                    correction_applied=correction_applied,
                                    step_data=step_data
                                )
                                logger.info(f"Saved step {step} debug data to GCS with OCR analysis")
                            else:
                                # Save without OCR if no elements found
                                save_to_gcs(
                                    client_id=client_id,
                                    test_id=test_id,
                                    #path=f"step_{step}_{int(time.time())}/step_data.json",
                                    path=f"step_{step}/step_data.json",
                                    data=step_data,
                                    content_type="application/json"
                                )
                                save_to_gcs(
                                    client_id=client_id,
                                    test_id=test_id,
                                    path=f"step_{step}/screenshot.jpg",
                                    #path=f"step_{step}_{int(time.time())}/screenshot.jpg",
                                    data=screenshot,
                                    content_type="image/jpeg"
                                )
                                logger.info(f"Saved step {step} debug data to GCS without OCR analysis")
                        else:
                            # Save basic data without OCR
                            save_to_gcs(
                                client_id=client_id,
                                test_id=test_id,
                                #path=f"step_{step}_{int(time.time())}/step_data.json",
                                path=f"step_{step}/step_data.json",
                                data=step_data
                            )
                            save_to_gcs(
                                client_id=client_id,
                                test_id=test_id,
                                #path=f"step_{step}_{int(time.time())}/screenshot.jpg",
                                path=f"step_{step}/screenshot.jpg",
                                data=screenshot,
                                content_type="image/jpeg"
                            )
                            logger.info(f"Saved step {step} basic data to GCS")
                    except Exception as e:
                        logger.error(f"Failed to save debug data to GCS: {e}")

                logger.info(f"Action completed: {tool_name}")

            except HTTPException as e:
                # Critical error - fail the whole run
                logger.error(f"Critical error during step {step}: {e}")
                end_session(rabbitize_url, session_id)

                # Save error state to Firebase
                if False: # firebase_initialized:
                    firebase_data = {
                        "error": str(e),
                        "step_number": step,
                        "is_final": True,
                        "timestamp": time.time()
                    }
                    send_to_firebase(client_id, test_id, step, firebase_data)

                    # Update task status to failed
                    update_task_status(client_id, test_id, "failed", {
                        "error": str(e),
                        "step_number": step,
                        "steps_completed": step
                    })

                if "Could not fetch screenshot" in str(e):
                    return {"status": "failed", "steps": step, "final_feedback": f"Failed to obtain screenshot after multiple attempts - the AI can no longer see the browser window: {str(e)}"}
                else:
                    return {"status": "failed", "steps": step, "final_feedback": f"Critical error: {str(e)}"}
            except Exception as e:
                logger.error(f"Error during step {step}: {e}", exc_info=True)
                # Try to continue with the next step for non-critical errors
                time.sleep(2)
                continue

        logger.info(f"Max steps ({max_steps}) reached")
        end_session(rabbitize_url, session_id)

        # Generate a summary of the session
        timeout_summary = "No actions were taken before the task timed out."
        if history: # Only generate summary if there's history
            logger.info(f"Generating timeout summary for {client_id}/{test_id} as max steps were reached.")
            timeout_summary = generate_timeout_summary(objective, history, client_id, test_id, session_id, rabbitize_url)
        else:
            logger.info(f"No history to generate timeout summary for {client_id}/{test_id}.")

        # Save timeout state to Firebase
        if False: # firebase_initialized:
            firebase_data = {
                "step_number": max_steps, # Representing the final state/summary step
                "is_final": True,
                "feedback": timeout_summary, # Use the new summary
                "reason": "Maximum steps reached",
                "timestamp": time.time()
            }
            # Using max_steps as the "step" key for the summary data
            send_to_firebase(client_id, test_id, max_steps, firebase_data)
            logger.info(f"Saved timeout summary to Firebase for {client_id}/{test_id} under step {max_steps}.")

            # Update overall task status to timeout
            update_task_status(client_id, test_id, "timeout", {
                "steps_completed": max_steps,
                "feedback": timeout_summary, # Use the new summary
                "reason": "Maximum steps reached"
            })
            logger.info(f"Updated overall task status to 'timeout' with summary for {client_id}/{test_id}.")

        return {"status": "timeout", "steps": max_steps, "final_feedback": timeout_summary} # Use the new summary

    except Exception as e:
        logger.error(f"Unexpected error in task: {e}", exc_info=True)
        try:
            end_session(rabbitize_url, session_id)
        except:
            pass

        # Record error in Firebase
        if False: # firebase_initialized:
            try:
                # Update task status to error
                update_task_status(client_id, test_id, "error", {
                    "error_message": str(e),
                    "traceback": traceback.format_exc()
                })
            except Exception as firebase_error:
                logger.error(f"Failed to record error in Firebase: {firebase_error}")

        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.get("/debug/cors-test")
async def debug_cors_test():
    """Test endpoint for CORS and Firebase integration."""
    try:
        firebase_status = "initialized" if firebase_initialized else "not initialized"
        cors_config = {
            "origins": [
                "http://localhost:8280",
                "https://silflay.rabbitize.ai",
                "https://thumper.rabbitize.ai",
                "https://dev.rabbitize.ai",
                "http://silflay.rabbitize.ai",
                "http://thumper.rabbitize.ai",
                "http://dev.rabbitize.ai"
            ],
            "regex": r"https://.*\.rabbitize\.ai|http://.*\.rabbitize\.ai",
            "methods": ["*"],
            "headers": ["*"]
        }

        # Try to write to Firebase if initialized
        firebase_test_result = "not attempted"
        if False: # firebase_initialized:
            try:
                test_ref = db.reference("recon/cors-test")
                test_ref.set({
                    "timestamp": time.time(),
                    "message": "CORS test successful"
                })
                firebase_test_result = "success"
            except Exception as e:
                firebase_test_result = f"error: {str(e)}"

        return {
            "status": "success",
            "cors_config": cors_config,
            "firebase_status": firebase_status,
            "firebase_test": firebase_test_result,
            "timestamp": time.time()
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/debug/dom-test")
async def debug_dom_test(client_id: str, test_id: str, step: int = 0):
    """
    Debug endpoint to test DOM coordinate fetching and visualization.

    Args:
        client_id: Client ID
        test_id: Test ID
        step: Step number

    Returns:
        DOM coordinates data and visualization
    """
    try:
        # Check for required parameters
        if not client_id or not test_id:
            return {
                "status": "error",
                "message": "client_id and test_id are required"
            }

        # Construct the base URL for Playwright API
        # Use a reasonable default that works in most environments
        rabbitize_url = f"http://10.0.0.53:8889"

        # Fetch the screenshot for visualization
        screenshot = None
        try:
            screenshot = get_screenshot(rabbitize_url, client_id, test_id, step, max_retries=3, retry_delay=2)
            if not screenshot or len(screenshot) == 0:
                return {
                    "status": "warning",
                    "message": f"Could not fetch screenshot for step {step}"
                }
        except Exception as e:
            logger.error(f"Error fetching screenshot: {e}")
            screenshot = None

        # Fetch DOM coordinates
        dom_data = get_dom_coordinates(rabbitize_url, client_id, test_id, step, max_retries=3)

        if not dom_data or "elements" not in dom_data:
            return {
                "status": "error",
                "message": f"Could not fetch DOM coordinates for step {step}"
            }

        # Get clickable elements
        clickable_elements = filter_clickable_elements(dom_data.get("elements", []))

        # Create a fake intent for testing
        test_intent = "I want to click on a button"

        # Find matching elements
        matching_elements = find_dom_elements_matching_intent(dom_data, test_intent)

        # Generate visualization if we have a screenshot
        visualization_base64 = None
        if screenshot:
            visualization = visualize_dom_elements(screenshot, dom_data, matching_elements[:5])
            visualization_base64 = base64.b64encode(visualization).decode('utf-8')

        # Prepare response
        response = {
            "status": "success",
            "viewport": dom_data.get("viewport", {}),
            "metadata": dom_data.get("metadata", {}),
            "element_count": len(dom_data.get("elements", [])),
            "clickable_element_count": len(clickable_elements),
            "matching_elements_count": len(matching_elements),
            "test_intent": test_intent,
            "top_matches": [
                {
                    "tagName": el.get("tagName", ""),
                    "text": el.get("text", ""),
                    "match_score": el.get("match_score", 0),
                    "match_reason": el.get("match_reason", ""),
                    "position": el.get("position", {})
                }
                for el in matching_elements[:5]
            ]
        }

        if visualization_base64:
            response["visualization_base64"] = visualization_base64

        return response
    except Exception as e:
        logger.error(f"Error in DOM test: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

@app.get("/debug/dom-markdown")
async def debug_dom_markdown(client_id: str, test_id: str):
    """
    Debug endpoint to test DOM markdown retrieval.

    Args:
        client_id: Client ID
        test_id: Test ID

    Returns:
        DOM markdown content or error message
    """
    try:
        # Check for required parameters
        if not client_id or not test_id:
            return {
                "status": "error",
                "message": "client_id and test_id are required"
            }

        # Construct the base URL for Playwright API
        # Use a reasonable default that works in most environments
        rabbitize_url = f"http://10.0.0.53:8889"

        # Fetch DOM markdown
        dom_markdown = get_dom_md(rabbitize_url, client_id, test_id)

        if not dom_markdown or len(dom_markdown.strip()) == 0:
            return {
                "status": "warning",
                "message": "No DOM markdown content available"
            }

        # Return the DOM markdown
        return {
            "status": "success",
            "content_length": len(dom_markdown),
            "content_preview": dom_markdown[:500] + ("..." if len(dom_markdown) > 500 else ""),
            "full_content": dom_markdown if len(dom_markdown) < 10000 else dom_markdown[:10000] + "\n\n[content truncated...]"
        }
    except Exception as e:
        logger.error(f"Error in DOM markdown test: {e}", exc_info=True)
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3737)