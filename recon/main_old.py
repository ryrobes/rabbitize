import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import json
import time
import os
import base64

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Recon")

app = FastAPI()

class TaskRequest(BaseModel):
    playwright_url: str
    target_url: str
    objective: str
    client_id: str
    test_id: str
    max_steps: int = 20

# No TOOLS definition needed

# Validate API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    logger.error("GEMINI_API_KEY environment variable is not set")
    raise RuntimeError("GEMINI_API_KEY is required")
logger.info(f"API key (partial): {api_key[:4]}...{api_key[-4:]}")
# Use the correct endpoint for gemini-2.0-flash.
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={api_key}"


def start_session(playwright_url: str, target_url: str, client_id: str, test_id: str, max_retries: int = 3):
    retries = 0
    while retries < max_retries:
        try:
            payload = {"url": target_url, "client-id": client_id, "test-id": test_id}
            response = requests.post(f"{playwright_url}/api/create-worker", json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Session started: {json.dumps(payload)}")
            time.sleep(10)
            return
        except Exception as e:
            retries += 1
            logger.error(f"Failed to start session (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not start session after {max_retries} attempts")
            time.sleep(5)


def get_screenshot(playwright_url: str, client_id: str, test_id: str, max_retries: int = 3) -> bytes:
    retries = 0
    while retries < max_retries:
        try:
            url = f"{playwright_url}/api/quick/{client_id}/{test_id}/interactive/latest.jpg"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            logger.info("Screenshot fetched successfully")
            return response.content
        except Exception as e:
            retries += 1
            logger.error(f"Failed to fetch screenshot (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail="Could not fetch screenshot after multiple attempts")
            time.sleep(10)


def get_dom_md(playwright_url: str, client_id: str, test_id: str, max_retries: int = 3) -> str:
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
                logger.error(f"Failed to fetch DOM markdown after {max_retries} attempts")
                return ""
            time.sleep(5)


def send_command(playwright_url: str, tool_name: str, args: dict, max_retries: int = 3) -> list:
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
    if tool_name == "move_mouse" and ("x" not in args or "y" not in args):
        logger.error(f"Invalid args for move_mouse: {args}.  Missing x or y.")
        raise HTTPException(status_code=400, detail="Invalid arguments for move_mouse: Missing x or y.")

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
            time.sleep(2)
            return command
        except Exception as e:
            retries += 1
            logger.error(f"Failed to send command {command} (attempt {retries}/{max_retries}): {e}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not send command after {max_retries} attempts")
            time.sleep(5)

def validate_response(response_json: dict) -> tuple[str, dict, str]:
    """Validates the LLM's JSON response and extracts data."""
    try:
        tool_name = response_json["tool_name"]
        experience = response_json["experience"]
        args = response_json.get("args", {})
        feedback = response_json.get("feedback", f"Executing {tool_name}")

        if not isinstance(tool_name, str):
            raise ValueError("tool_name must be a string")
        if not isinstance(args, dict):
            raise ValueError("args must be a dictionary")
        if not isinstance(feedback, str):
            raise ValueError("feedback must be a string")

        if tool_name == "move_mouse":
            if not ("x" in args and "y" in args):
                raise ValueError("move_mouse requires 'x' and 'y' arguments")
            if not (isinstance(args["x"], int) and isinstance(args["y"], int)):
                raise ValueError("'x' and 'y' must be integers")
        if tool_name == "scroll_wheel_up" or tool_name == "scroll_wheel_down":
            if "x" not in args:
                raise ValueError(f"{tool_name} requires an 'x' argument")
            if not isinstance(args["x"], int):
                raise ValueError("'x' must be an integer")

        return tool_name, args, feedback, experience

    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Invalid LLM response format: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid LLM response format: {e}")



def query_llm(screenshot: bytes, dom_md: str, objective: str, history: list) -> tuple[str, dict, str]:
    retries = 0
    max_retries = 3
    while retries < max_retries:
        try:
            # --- Construct history string WITHOUT Base64 ---
            history_str_no_b64 = "\n".join(
                f"Step {i}: Command {json.dumps(h['command'])}, Feedback: {h['feedback']}, Image: [Image at Step {i}]"
                for i, h in enumerate(history)
            )
            logger.info(f"History (no Base64): \n{history_str_no_b64}")

            prompt = f"""
            You are a browser automation assistant. Your goal is to achieve: {objective}.

            You control a mouse and keyboard interacting with a web browser.  You are provided with a series of screenshots showing the current state of the browser - at each step you will be able to see how you commands are changing it's state and learn how to navigate an control it - a personal feedback loop where YOU are in control.

            **IMPORTANT INSTRUCTIONS:**

            1.  **Analyze the Screenshots:** Examine ALL screenshots, in order, to understand the history of actions and their effects. Pay close attention to whether the view changes between screenshots. If the view *doesn't* change after scrolling, you are likely at the top or bottom of the page.
            2.  **Mouse Movement is Required:**  You *MUST* use `move_mouse` to position the mouse cursor *before* you can `click`, `right_click`, or `middle_click`.  You cannot click without moving the mouse first. Think about *where* on the screenshot the element you want to interact with is located. Use (x, y) coordinates relative to the top-left corner of the image (0, 0) - the entire image is 1920, 1080 - so if the top left corner is 0,0 then the bottom left corner is 1920,1080 - please use this to make accurate mouse moves.  After moving the mouse, wait and examine the next screenshot to see if the red dot (your cursor) is where you intended. If not, `move_mouse` again.
            3.  **Scrolling:** Use `scroll_wheel_up` and `scroll_wheel_down` to scroll.  Each "tick" of scrolling moves the page by approximately 100 pixels.  Avoid excessive scrolling. Scroll in smaller increments (e.g., 50-150 pixels) to avoid overshooting.
            4. **Complete?**: If you believe the task defined by "{objective}"is done, use the action  `report_done`.
            5. **DOM Markdown**: Use this *only* to help clarify *text* content or relationships between elements if the screenshot is unclear. The screenshots are your primary source of information.

            You MUST respond in JSON format, using the following structure:

            ```json
            {{
              "tool_name": "<tool_name>",
              "args": {{ <tool_arguments> }},
              "feedback": "<feedback_message>",
              "experience": "<what-is-this?-what-are-you-trying-to-do?>"
            }}
            ```

            Available tools and their arguments:
            - click:  args: {{}}  // Requires prior move_mouse
            - right_click: args: {{}}  // Requires prior move_mouse
            - middle_click: args: {{}}  // Requires prior move_mouse
            - move_mouse: args: {{ "x": <integer>, "y": <integer> }}
            - click_hold: args: {{}}
            - click_release: args: {{}}
            - scroll_wheel_up: args: {{ "x": <integer> }} // x is the number of 100-pixel ticks
            - scroll_wheel_down: args: {{ "x": <integer> }} // x is the number of 100-pixel ticks
            - report_done: args: {{ "feedback": "<string>"}}  // Use this when the objective is complete

            History: {history_str_no_b64}
            DOM markdown: {dom_md}

            Based on the screenshots and the objective, provide the JSON for the next action. Respond *ONLY* with the JSON, no other text.
            """

            # --- Construct parts for ALL images ---
            image_parts = []
            for i, h in enumerate(history):
                encoded_image = base64.b64encode(h['screenshot']).decode("utf-8")  # Encode each image
                image_parts.append(
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": encoded_image,
                        }
                    }
                )
            # Add the current screenshot
            encoded_screenshot = base64.b64encode(screenshot).decode("utf-8")
            image_parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": encoded_screenshot,
                    }
                }
            )

            # --- Construct the payload ---
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},  # Text prompt comes first
                            *image_parts,     # Add ALL image parts (unpacked using *)
                        ],
                    }
                ],
            }

            # TEMPORARY DEBUGGING: Write payload to a file
            with open("/tmp/request_payload.json", "w") as f:
                json.dump(payload, f, indent=2)
            logger.info("Request payload written to /tmp/request_payload.json")

            logger.info("Sending request to Gemini API")
            logger.debug(f"Request payload: {json.dumps(payload, indent=2)}")  #VERY LARGE
            response = requests.post(
                GEMINI_API_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=30
            )
            response.raise_for_status()
            logger.info("Received response from Gemini API")

            result = response.json()
            logger.debug(f"Raw response from Gemini: {json.dumps(result, indent=2)}")

            if "candidates" not in result or not result["candidates"]:
                logger.error("No candidates in LLM response")
                raise ValueError("Invalid LLM response: No candidates")

            candidate = result["candidates"][0]
            if "content" not in candidate or "parts" not in candidate["content"]:
                logger.error("No content or parts in candidate")
                raise ValueError("Invalid LLM response: No content or parts")

            part = candidate["content"]["parts"][0]
            if "text" not in part:
                logger.error("No text in LLM response")
                raise ValueError("Invalid LLM response: No text")

            try:
                response_text = part["text"]
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                if start == -1 or end == -1:
                    raise json.JSONDecodeError("No valid JSON object found", response_text, 0)

                response_text = response_text[start:end]
                response_json = json.loads(response_text)
                tool_name, args, feedback, experience = validate_response(response_json)
                logger.info(f"Parsed LLM response: tool_name={tool_name}, args={args}, feedback={feedback}")
                return tool_name, args, feedback, experience

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                logger.error(f"Raw LLM response text: {response_text}")
                raise HTTPException(status_code=400, detail=f"Invalid LLM response (not valid JSON): {e}")

        except requests.HTTPError as e:
            retries += 1
            logger.error(f"Attempt {retries}/{max_retries} failed: {str(e)} - Response: {e.response.text}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not query LLM after {max_retries} attempts: {str(e)} - {e.response.text}")
            time.sleep(5)
        except Exception as e:
            retries += 1
            logger.error(f"Attempt {retries}/{max_retries} failed: {str(e)}")
            if retries >= max_retries:
                raise HTTPException(status_code=500, detail=f"Could not query LLM after {max_retries} attempts: {str(e)}")
            time.sleep(5)

@app.post("/start")
async def start_task(task: TaskRequest):
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
        screenshot = get_screenshot(playwright_url, client_id, test_id)
        dom_md = get_dom_md(playwright_url, client_id, test_id)
        tool_name, args, feedback, experience = query_llm(screenshot, dom_md, objective, history)

        logger.info(f"Agent feedback: {feedback}")
        logger.info(f"Agent ux: {experience}")

        if tool_name == "report_done":
            logger.info(f"Objective completed at step {step + 1}")
            return {"status": "success", "steps": step + 1, "final_feedback": feedback}

        command = send_command(playwright_url, tool_name, args)
        history.append({
            "command": command,
            "feedback": feedback,
            "screenshot": screenshot,  # Store the raw screenshot bytes
        })


    logger.info(f"Max steps ({max_steps}) reached")
    return {"status": "timeout", "steps": max_steps, "final_feedback": history[-1]["feedback"] if history else "No progress made"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)