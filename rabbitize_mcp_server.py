#!/usr/bin/env python3
"""
Rabbitize MCP Server

A Model Context Protocol server that provides LLMs with tools to control Rabbitize sessions,
automatically managing session lifecycle and returning screenshots as base64 images.
"""

import asyncio
import json
import base64
import requests
import time
import os
import logging
import uuid
from typing import Dict, Any, Optional, List
from pathlib import Path
import aiohttp
import aiofiles
from urllib.parse import urljoin
import signal
import sys
import threading
from datetime import datetime

# MCP imports
try:
    from mcp import McpServer, Tool, TextContent, ImageContent
    from mcp.types import JSONRPCRequest, JSONRPCResponse, JSONRPCError
except ImportError:
    print("MCP library not found. Please install: pip install mcp")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RabbitizeSession:
    """Manages a Rabbitize session with automatic lifecycle management"""

    def __init__(self, base_url: str = "http://localhost:3000", client_id: str = None, test_id: str = None):
        self.base_url = base_url
        self.client_id = client_id or f"mcp-client-{uuid.uuid4().hex[:8]}"
        self.test_id = test_id or f"mcp-test-{uuid.uuid4().hex[:8]}"
        self.session_id = None
        self.is_active = False
        self.command_counter = 0
        self.session_data = {}
        self.last_screenshot_path = None

        # HTTP session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'RabbitizeMCP/1.0'
        })

        logger.info(f"Initialized Rabbitize session manager for {self.client_id}/{self.test_id}")

    async def start_session(self, url: str) -> Dict[str, Any]:
        """Start a new Rabbitize session"""
        try:
            payload = {
                "url": url,
                "clientId": self.client_id,
                "testId": self.test_id
            }

            logger.info(f"Starting Rabbitize session for URL: {url}")
            response = self.session.post(
                urljoin(self.base_url, "/start"),
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                self.session_id = result.get('sessionId')
                self.is_active = True
                self.command_counter = 0

                logger.info(f"Session started successfully: {self.session_id}")

                # Wait a moment for initial screenshot
                await asyncio.sleep(2)

                # Get initial screenshot
                screenshot_b64 = await self.get_latest_screenshot()

                return {
                    "success": True,
                    "sessionId": self.session_id,
                    "clientId": self.client_id,
                    "testId": self.test_id,
                    "url": url,
                    "screenshot": screenshot_b64,
                    "message": f"Session started successfully at {url}"
                }
            else:
                error_msg = f"Failed to start session: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

        except Exception as e:
            error_msg = f"Error starting session: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    async def execute_command(self, command: List[str]) -> Dict[str, Any]:
        """Execute a command in the active session"""
        if not self.is_active:
            return {
                "success": False,
                "error": "No active session. Please start a session first."
            }

        try:
            payload = {"command": command}

            logger.info(f"Executing command: {command}")
            response = self.session.post(
                urljoin(self.base_url, "/execute"),
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                self.command_counter += 1

                # Wait a moment for screenshot to be taken
                await asyncio.sleep(1)

                # Get the updated screenshot
                screenshot_b64 = await self.get_latest_screenshot()

                return {
                    "success": True,
                    "command": command,
                    "commandIndex": self.command_counter,
                    "result": result,
                    "screenshot": screenshot_b64,
                    "message": f"Command executed successfully: {' '.join(map(str, command))}"
                }
            else:
                error_msg = f"Failed to execute command: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    async def end_session(self) -> Dict[str, Any]:
        """End the active session"""
        if not self.is_active:
            return {
                "success": False,
                "error": "No active session to end"
            }

        try:
            logger.info("Ending Rabbitize session")
            response = self.session.post(
                urljoin(self.base_url, "/end"),
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                self.is_active = False
                self.session_id = None

                logger.info("Session ended successfully")
                return {
                    "success": True,
                    "result": result,
                    "commandsExecuted": self.command_counter,
                    "message": "Session ended successfully"
                }
            else:
                error_msg = f"Failed to end session: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

        except Exception as e:
            error_msg = f"Error ending session: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    async def get_latest_screenshot(self) -> Optional[str]:
        """Get the latest screenshot as base64"""
        try:
            # Try to get the latest screenshot from the session
            screenshot_path = f"rabbitize-runs/{self.client_id}/{self.test_id}/{self.session_id}/latest.jpg"

            if os.path.exists(screenshot_path):
                async with aiofiles.open(screenshot_path, 'rb') as f:
                    image_data = await f.read()
                    return base64.b64encode(image_data).decode('utf-8')

            # Fallback: try to get from a different path structure
            alt_path = f"rabbitize-runs/{self.client_id}/{self.test_id}/{self.session_id}/screenshots"
            if os.path.exists(alt_path):
                screenshots = sorted([f for f in os.listdir(alt_path) if f.endswith('.jpg')])
                if screenshots:
                    latest_screenshot = os.path.join(alt_path, screenshots[-1])
                    async with aiofiles.open(latest_screenshot, 'rb') as f:
                        image_data = await f.read()
                        return base64.b64encode(image_data).decode('utf-8')

            logger.warning("No screenshot found")
            return None

        except Exception as e:
            logger.error(f"Error getting screenshot: {str(e)}")
            return None

    async def get_session_status(self) -> Dict[str, Any]:
        """Get current session status"""
        return {
            "isActive": self.is_active,
            "sessionId": self.session_id,
            "clientId": self.client_id,
            "testId": self.test_id,
            "commandCounter": self.command_counter,
            "baseUrl": self.base_url
        }

    def cleanup(self):
        """Cleanup resources"""
        if self.session:
            self.session.close()
        logger.info("Session cleanup completed")

class RabbitizeMCPServer:
    """MCP Server for Rabbitize integration"""

    def __init__(self, rabbitize_url: str = "http://localhost:3000"):
        self.rabbitize_url = rabbitize_url
        self.rabbitize_session = RabbitizeSession(rabbitize_url)
        self.server = McpServer("rabbitize-mcp")

        # Register tools
        self._register_tools()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(f"Rabbitize MCP Server initialized with Rabbitize at {rabbitize_url}")

    def _register_tools(self):
        """Register MCP tools"""

        @self.server.tool(
            name="rabbitize_start_session",
            description="Start a new Rabbitize browser session with a given URL",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to navigate to when starting the session"
                    }
                },
                "required": ["url"]
            }
        )
        async def start_session(url: str):
            """Start a new Rabbitize session"""
            result = await self.rabbitize_session.start_session(url)

            if result["success"] and result.get("screenshot"):
                return [
                    TextContent(
                        type="text",
                        text=f"Session started successfully!\n\n"
                             f"Session ID: {result.get('sessionId')}\n"
                             f"URL: {result.get('url')}\n"
                             f"Client ID: {result.get('clientId')}\n"
                             f"Test ID: {result.get('testId')}\n\n"
                             f"Initial screenshot captured and displayed below."
                    ),
                    ImageContent(
                        type="image",
                        data=result["screenshot"],
                        mimeType="image/jpeg"
                    )
                ]
            else:
                return [TextContent(
                    type="text",
                    text=f"Failed to start session: {result.get('error', 'Unknown error')}"
                )]

        @self.server.tool(
            name="rabbitize_execute",
            description="Execute a command in the active Rabbitize session and return the result with screenshot",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The command to execute as an array of strings (e.g., [':click'] or [':move-mouse', ':to', '100', '200'])"
                    }
                },
                "required": ["command"]
            }
        )
        async def execute_command(command: List[str]):
            """Execute a command in the active session"""
            result = await self.rabbitize_session.execute_command(command)

            if result["success"] and result.get("screenshot"):
                return [
                    TextContent(
                        type="text",
                        text=f"Command executed successfully!\n\n"
                             f"Command: {' '.join(result['command'])}\n"
                             f"Command Index: {result.get('commandIndex')}\n"
                             f"Result: {json.dumps(result.get('result', {}), indent=2)}\n\n"
                             f"Updated screenshot displayed below."
                    ),
                    ImageContent(
                        type="image",
                        data=result["screenshot"],
                        mimeType="image/jpeg"
                    )
                ]
            else:
                return [TextContent(
                    type="text",
                    text=f"Failed to execute command: {result.get('error', 'Unknown error')}"
                )]

        @self.server.tool(
            name="rabbitize_get_screenshot",
            description="Get the latest screenshot from the active Rabbitize session",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        async def get_screenshot():
            """Get the latest screenshot"""
            if not self.rabbitize_session.is_active:
                return [TextContent(
                    type="text",
                    text="No active session. Please start a session first."
                )]

            screenshot_b64 = await self.rabbitize_session.get_latest_screenshot()

            if screenshot_b64:
                return [
                    TextContent(
                        type="text",
                        text="Latest screenshot from the active session:"
                    ),
                    ImageContent(
                        type="image",
                        data=screenshot_b64,
                        mimeType="image/jpeg"
                    )
                ]
            else:
                return [TextContent(
                    type="text",
                    text="No screenshot available. The session may not have started yet or there was an error."
                )]

        @self.server.tool(
            name="rabbitize_end_session",
            description="End the current Rabbitize session",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        async def end_session():
            """End the current session"""
            result = await self.rabbitize_session.end_session()

            if result["success"]:
                return [TextContent(
                    type="text",
                    text=f"Session ended successfully!\n\n"
                         f"Commands executed: {result.get('commandsExecuted', 0)}\n"
                         f"Result: {json.dumps(result.get('result', {}), indent=2)}"
                )]
            else:
                return [TextContent(
                    type="text",
                    text=f"Failed to end session: {result.get('error', 'Unknown error')}"
                )]

        @self.server.tool(
            name="rabbitize_status",
            description="Get the current status of the Rabbitize session",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        async def get_status():
            """Get session status"""
            status = await self.rabbitize_session.get_session_status()
            return [TextContent(
                type="text",
                text=f"Rabbitize Session Status:\n\n"
                     f"Active: {status['isActive']}\n"
                     f"Session ID: {status.get('sessionId', 'None')}\n"
                     f"Client ID: {status['clientId']}\n"
                     f"Test ID: {status['testId']}\n"
                     f"Commands executed: {status['commandCounter']}\n"
                     f"Base URL: {status['baseUrl']}"
            )]

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")

        # End the session if active
        if self.rabbitize_session.is_active:
            asyncio.create_task(self.rabbitize_session.end_session())

        # Cleanup
        self.rabbitize_session.cleanup()

        sys.exit(0)

    async def run(self):
        """Run the MCP server"""
        try:
            logger.info("Starting Rabbitize MCP Server...")
            await self.server.run()
        except Exception as e:
            logger.error(f"Server error: {str(e)}")
            raise
        finally:
            self.rabbitize_session.cleanup()

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Rabbitize MCP Server")
    parser.add_argument(
        "--rabbitize-url",
        default="http://localhost:3000",
        help="Base URL for Rabbitize server (default: http://localhost:3000)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Create and run server
    server = RabbitizeMCPServer(args.rabbitize_url)

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()