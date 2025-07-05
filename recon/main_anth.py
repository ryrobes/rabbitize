import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import json
import time
import os
import base64
from PIL import Image
import imagehash
import io

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Recon")

# --- FastAPI App Initialization ---
app = FastAPI()

# --- Pydantic Model for Task Request ---
class TaskRequest(BaseModel):
    playwright_url: str
    target_url: str
    objective: str
    client_id: str
    test_id: str
    max_steps: int = 20

# --- Tool Definitions (Function Calling) ---
TOOLS = [
    {
        "name": "click",
        "description": "Left click at the current mouse position",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "right_click",
        "description": "Right click at the current mouse position",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "middle_click",
        "description": "Middle click at the current mouse position",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "move_mouse",
        "description": "Move mouse to pixel coordinates",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"}
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "click_hold",
        "description": "Click and hold at the current mouse position",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "click_release",
        "description": "Release the mouse at the current position",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "scroll_wheel_up",
        "description": "Scroll up by x clicks",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer", "description": "Number of scroll clicks"}},
            "required": ["x"]
        }
    },
    {
        "name": "scroll_wheel_down",
        "description": "Scroll down by x clicks",
        "input_schema": {
            "type": "object",
            "properties": {"x": {"type": "integer", "description": "Number of scroll clicks"}},
            "required": ["x"]
        }
    },
    {
        "name": "report_done",
        "description": "Signal objective complete with feedback",
        "input_schema": {
            "type": "object",
            "properties": {"feedback": {"type": "string", "description": "Explanation of what was achieved"}},
            "required": ["feedback"]
        }
    }
]

# --- API Configuration ---
api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
if not api_key:
    logger.error("ANTHROPIC_API_KEY environment variable is not set")
    raise RuntimeError("ANTHROPIC_API_KEY is required")
logger.info(f"API key (partial): {api_key[:4]}...{api_key[-4:]}")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-3-7-sonnet-20240229"
CLAUDE_API_HEADERS = {
    "x-api-key": api_key,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}

# --- Helper Functions ---

def start_session(playwright_url: str, target_url: str, client_id: str, test_id: str, max_retries: int = 3):
    """Start a browser session via the Playwright API."""
    retries = 0
    while retries < max_retries:
        try:
            payload = {"url": target_url, "client-id": client_id, "test-id": test_id}
            response = requests.post(f"{playwright_url}/api/create-worker", json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Session started: {json.dumps(payload)}")
            return
        except Exception as e:
            retries += 1
            logger.error(f"Failed to start session (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not start session after {max_retries} attempts")
            time.sleep(5)

def get_screenshot(playwright_url: str, client_id: str, test_id: str, step: int, max_retries: int = 40, retry_delay: int = 2) -> bytes:
    """Fetch the screenshot for the given step from the Playwright API with retries."""
    if step == 0:
        url = f"{playwright_url}/api/quick/{client_id}/{test_id}/interactive/screenshots/start.jpg"
    else:
        url = f"{playwright_url}/api/quick/{client_id}/{test_id}/interactive/screenshots/{step-1}.jpg"

    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            logger.info(f"Screenshot for step {step} fetched successfully")
            return response.content
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.info(f"Screenshot for step {step} not found, retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                raise
        except Exception as e:
            raise
    raise HTTPException(status_code=500, detail=f"Could not fetch screenshot for step {step} after {max_retries} attempts")

def get_dom_md(playwright_url: str, client_id: str, test_id: str, max_retries: int = 3) -> str:
    """Fetch the DOM markdown from the Playwright API (optional)."""
    retries = 0
    while retries < max_retries:
        try:
            url = f"{playwright_url}/api/quick/{client_id}/{test_id}/latest.md"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            logger.info("DOM markdown fetched successfully")
            return response.text
        except Exception as e:
            retries += 1
            logger.error(f"Failed to fetch DOM markdown (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                logger.warning(f"Failed to fetch DOM markdown after {max_retries} attempts. Proceeding without it.")
                return ""
            time.sleep(5)

def send_command(playwright_url: str, tool_name: str, args: dict, max_retries: int = 3) -> list:
    """Send a command to the Playwright API based on the tool called."""
    command_map = {
        "click": [":click"],
        "right_click": [":right-click"],
        "middle_click": [":middle-click"],
        "move_mouse": [":move-mouse", ":to", args.get("x"), args.get("y")],
        "click_hold": [":click-hold"],
        "click_release": [":click-release"],
        "scroll_wheel_up": [":scroll-wheel-up", args.get("x")],
        "scroll_wheel_down": [":scroll-wheel-down", args.get("x")],
        "report_done": ["report_done"],
    }
    command = command_map.get(tool_name)
    if not command:
        raise ValueError(f"Unknown tool: {tool_name}")

    retries = 0
    while retries < max_retries:
        try:
            payload = {"command": command}
            response = requests.post(f"{playwright_url}/api/interactive/execute", json=payload, timeout=5)
            response.raise_for_status()
            logger.info(f"Command sent: {json.dumps(payload)}")
            return command
        except Exception as e:
            retries += 1
            logger.error(f"Failed to send command {command} (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not send command after {max_retries} attempts")
            time.sleep(5)

def compute_image_hash(image_bytes: bytes) -> str:
    """Compute a perceptual hash of the image for comparison."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(image))
    except Exception as e:
        logger.error(f"Error computing image hash: {e}")
        return "0"

def get_next_action(screenshot: bytes, objective: str, history: list) -> tuple[str, dict, str]:
    # Compute the perceptual hash of the current screenshot as a string
    current_hash_str = compute_image_hash(screenshot)

    # Convert the current hash string to an ImageHash object
    try:
        current_hash = imagehash.hex_to_hash(current_hash_str)
    except:
        current_hash = 0

    # Check if the current screenshot is similar to the previous one
    screenshot_reminder = ""
    if len(history) >= 1:
        last_hash_str = history[-1].get("screenshot_hash")
        if last_hash_str:
            # Convert the last hash string to an ImageHash object
            try:
                last_hash = imagehash.hex_to_hash(last_hash_str)
                # Calculate the Hamming distance between the ImageHash objects
                distance = current_hash - last_hash
                logger.info(f"Distance between current and last screenshot: {distance}")
                if distance < 5:  # Threshold can be adjusted
                    screenshot_reminder = (
                        "The current screenshot is very similar to the previous one. "
                        "This suggests your last action didn't change the screen significantly. "
                        "Try a different approach."
                    )
            except Exception as e:
                logger.error(f"Error comparing image hashes: {e}")

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

    system_instruction = f"""You are a browser automation assistant. Your ONLY goal is to achieve: {objective}.

You control a mouse and keyboard interacting with a web browser. You will receive a screenshot after EACH action, showing the current state of the browser. You MUST use these screenshots to understand what is happening and to plan your next action. TREAT THE SCREENSHOTS AS YOUR EYES. TREAT THE MOUSE CURSOR AS YOU FINGERS. MOVE IT OVER THINGS YOU ARE CONSIDERING. GREEN DOT = CLICKABLE, BLUE DOT = DRAGGABLE.

**VERY IMPORTANT INSTRUCTIONS - READ AND FOLLOW THESE CAREFULLY:**

1. **Screenshot Analysis is EVERYTHING:**  Your ONLY source of information about the browser is the sequence of screenshots.  Examine each screenshot VERY carefully.  Compare it to the *previous* screenshot to see what changed (or didn't change) as a result of your last action.
2. **Mouse Movement is MANDATORY Before Clicking:**  You *CANNOT* click, right-click, or middle-click *UNLESS* you have first used `move_mouse` to position the cursor.
    *   **The Red/Green/Blue Dot:** After each `move_mouse` action, a new screenshot will be taken.  You *MUST* look for a small **RED DOT** in the new screenshot. This red dot shows the current location of the mouse cursor.
    *   **Iterative Mouse Movement:** If the red dot is *NOT* where you intended to click, you *MUST* use `move_mouse` *AGAIN* to adjust the position.  Keep moving the mouse in small increments until the red dot is *exactly* where you want to click.  Do NOT click until the red dot is in the correct place, as shown on a subsequent screenshot. Each time you move the mouse you must use the complete x, y coords.
    *  **(x, y) Coordinates:**  Use (x, y) coordinates relative to the *top-left* corner of the image, which is (0, 0). The image is 1920 pixels wide and 1080 pixels high.  So, the bottom-right corner is (1920, 1080). Again - x is pixel left from the edge, and y is pixels down from the top.
    *   ** When the cursor is GREEN, that means you are on a clickable link or element - if it is BLUE that means you are on something that is draggable - RED means you are on nethier, but perhaps you can scroll.
3. **Scrolling:**
    *   `scroll_wheel_up` and `scroll_wheel_down` move the page. The `x` argument is the number of "ticks," and each tick is *approximately* 100 pixels.
    *   **Small Scroll Increments:** Use *small* scroll amounts (e.g., 50-150) to avoid overshooting.
    *   **Check for Changes:** After scrolling, *carefully* compare the new screenshot to the previous one.  If the content *didn't change*, you are probably at the top or bottom of the page.  Don't keep scrolling if nothing is changing!
4. **Clicking:** Only click *after* you have used `move_mouse` to position the red dot *precisely* on the element you want to interact with.
5. **DOM Markdown:** Completely IGNORE and do not use the DOM.
6. **When You Are Finished:**  If you believe you have achieved the objective ("{objective}"), use the `report_done` action and explain what you did.
7. **Think, then Act:** Before *every* action, think about these things:
    *   What do I see on the CURRENT screenshot?
    *   What is my GOAL (what am I trying to achieve)?
    *   What is the BEST action to take NEXT to achieve that goal?
    *   WHERE on the screenshot should I move the mouse or scroll?

8. **IF AT FIRST YOU DON'T SUCCEED, TRY, TRY AGAIN:** If an action doesn't produce the result you expected, that's okay!  Use the new screenshot to understand *why* it didn't work, and try a *different* action.  Don't give up! Don't repeat the same failing action.

9. **GETTING STUCK?:** If the current screenshots looks exactly like the LAST screenshot - that means that what you are trying to do isn't working. Try something else, mouse around click on something that appears to be a link, button or other interactible.

You MUST respond using ONLY a function call, no additional text outside the function call.
"""

    user_prompt_text = f"Here is the current screen. {actions_text} {screenshot_reminder} What do you see, what is your plan, and what is your next action? First, describe briefly what you see and your plan, then provide the function call."

    logger.info(f"Current Feedback: {actions_text} {screenshot_reminder}")

    # Build the messages array for Claude API
    messages = []
    for turn in history:
        # Add user message with screenshot and previous action
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": "Here is what I did last: " + turn["feedback"]},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(turn['screenshot']).decode("utf-8")}}
            ]
        })

        # Add assistant response with tool call
        messages.append({
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "tool_use": {
                    "id": f"tool_{len(messages)}",
                    "name": turn["tool_name"],
                    "input": turn["args"] or {}
                }
            }]
        })

    # Add the current user message with the newest screenshot
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt_text},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(screenshot).decode("utf-8")}}
        ]
    })

    # Prepare the Claude API request payload
    payload = {
        "model": CLAUDE_MODEL,
        "messages": messages,
        "system": system_instruction,
        "tools": TOOLS,
        "max_tokens": 1024,
        "temperature": 0.2
    }

    logger.info("Sending request to Claude API")
    try:
        response = requests.post(
            CLAUDE_API_URL,
            json=payload,
            headers=CLAUDE_API_HEADERS,
            timeout=120
        )

        # Enhanced error logging
        if response.status_code == 400:
            error_detail = response.json() if response.text else "No error details available"
            logger.error(f"HTTP 400 Bad Request: {error_detail}")
            raise HTTPException(status_code=500, detail=f"Bad request to Claude API: {error_detail}")
        elif response.status_code != 200:
            logger.error(f"HTTP {response.status_code} from Claude API: {response.text}")
            raise HTTPException(status_code=500, detail=f"Error from Claude API (HTTP {response.status_code})")

        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during API request: {e}")
        raise HTTPException(status_code=500, detail=f"Error communicating with Claude API: {e}")

    logger.info("Received response from Claude API")
    try:
        result = response.json()

        # Parse the Claude API response
        text_feedback = ""
        tool_name = None
        args = {}

        # Extract content from Claude's response
        for content_item in result["content"]:
            if content_item["type"] == "text":
                text_feedback += content_item["text"] + " "
            elif content_item["type"] == "tool_use":
                tool_call = content_item["tool_use"]
                tool_name = tool_call["name"]
                args = tool_call["input"] or {}

        if not tool_name:
            logger.error("No tool call found in Claude's response")
            raise ValueError("No tool call in response")

        feedback = f"Calling {tool_name} with args: {args}"
        if text_feedback:
            logger.info(f"Model feedback: {text_feedback.strip()}")

        return tool_name, args, feedback
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Error parsing Claude API response: {e}")
        # Log the actual response if possible
        if 'response' in locals() and hasattr(response, 'text'):
            logger.error(f"Response content: {response.text[:1000]}...")
        raise HTTPException(status_code=500, detail=f"Error parsing Claude API response: {e}")

# --- FastAPI Endpoints ---

@app.post("/start")
async def start_task(task: TaskRequest):
    """Start a browser automation task."""
    logger.info(f"Starting Recon task: {task.dict()}")
    playwright_url = task.playwright_url
    target_url = task.target_url
    objective = task.objective
    client_id = task.client_id
    test_id = task.test_id
    max_steps = task.max_steps

    start_session(playwright_url, target_url, client_id, test_id)
    history = []
    for step in range(max_steps):
        logger.info(f"Step {step + 1}/{max_steps}")
        screenshot = get_screenshot(playwright_url, client_id, test_id, step)
        tool_name, args, feedback = get_next_action(screenshot, objective, history)

        if tool_name == "report_done":
            logger.info(f"Objective completed at step {step + 1}")
            requests.post(f"{playwright_url}/api/interactive/end", json={}, timeout=5)
            return {"status": "success", "steps": step + 1, "final_feedback": feedback}

        screenshot_hash = compute_image_hash(screenshot)
        history.append({
            "tool_name": tool_name,
            "args": args,
            "command": send_command(playwright_url, tool_name, args),
            "feedback": feedback,
            "screenshot": screenshot,
            "screenshot_hash": screenshot_hash
        })

    logger.info(f"Max steps ({max_steps}) reached")
    requests.post(f"{playwright_url}/api/interactive/end", json={}, timeout=5)
    return {"status": "timeout", "steps": max_steps, "final_feedback": history[-1]["feedback"] if history else "No progress made"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)