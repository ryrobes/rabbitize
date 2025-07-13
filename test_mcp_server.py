#!/usr/bin/env python3
"""
Test script for Rabbitize MCP Server

This script demonstrates how to communicate with the MCP server directly
using JSON-RPC protocol over stdin/stdout.
"""

import json
import subprocess
import sys
import time
import base64
from pathlib import Path

def send_request(process, method, params=None, request_id=1):
    """Send a JSON-RPC request to the MCP server"""
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "id": request_id
    }

    if params:
        request["params"] = params

    # Send request
    request_json = json.dumps(request) + "\n"
    process.stdin.write(request_json.encode())
    process.stdin.flush()

    # Read response
    response_line = process.stdout.readline()
    if response_line:
        return json.loads(response_line.decode().strip())
    return None

def test_mcp_server():
    """Test the MCP server with a complete workflow"""

    # Start the MCP server
    print("Starting MCP server...")
    process = subprocess.Popen(
        [sys.executable, "rabbitize_mcp_server_simple.py", "--log-level", "INFO"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False
    )

    try:
        # 1. Initialize the server
        print("1. Initializing server...")
        response = send_request(process, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        })

        if response and "result" in response:
            print(f"   ✓ Server initialized: {response['result']['name']}")
        else:
            print(f"   ✗ Initialization failed: {response}")
            return

        # 2. List available tools
        print("2. Listing available tools...")
        response = send_request(process, "tools/list", {}, 2)

        if response and "result" in response:
            tools = response['result']['tools']
            print(f"   ✓ Found {len(tools)} tools:")
            for tool in tools:
                print(f"     - {tool['name']}: {tool['description']}")
        else:
            print(f"   ✗ Failed to list tools: {response}")
            return

        # 3. Start a Rabbitize session
        print("3. Starting Rabbitize session...")
        response = send_request(process, "tools/call", {
            "name": "rabbitize_start_session",
            "arguments": {
                "url": "https://example.com"
            }
        }, 3)

        if response and "result" in response:
            content = response['result']['content']
            print(f"   ✓ Session started successfully")

            # Check if we got a screenshot
            for item in content:
                if item['type'] == 'image':
                    print(f"   ✓ Received screenshot ({len(item['data'])} bytes)")

                    # Save screenshot for inspection
                    screenshot_path = Path("test_screenshot_start.jpg")
                    with open(screenshot_path, "wb") as f:
                        f.write(base64.b64decode(item['data']))
                    print(f"   ✓ Screenshot saved to {screenshot_path}")
                    break
        else:
            print(f"   ✗ Failed to start session: {response}")
            return

        # 4. Execute a command
        print("4. Executing command (move mouse)...")
        response = send_request(process, "tools/call", {
            "name": "rabbitize_execute",
            "arguments": {
                "command": [":move-mouse", ":to", "200", "300"]
            }
        }, 4)

        if response and "result" in response:
            content = response['result']['content']
            print(f"   ✓ Command executed successfully")

            # Check if we got a screenshot
            for item in content:
                if item['type'] == 'image':
                    print(f"   ✓ Received updated screenshot ({len(item['data'])} bytes)")

                    # Save screenshot for inspection
                    screenshot_path = Path("test_screenshot_command.jpg")
                    with open(screenshot_path, "wb") as f:
                        f.write(base64.b64decode(item['data']))
                    print(f"   ✓ Screenshot saved to {screenshot_path}")
                    break
        else:
            print(f"   ✗ Failed to execute command: {response}")

        # 5. Get session status
        print("5. Getting session status...")
        response = send_request(process, "tools/call", {
            "name": "rabbitize_status",
            "arguments": {}
        }, 5)

        if response and "result" in response:
            content = response['result']['content']
            print(f"   ✓ Status retrieved:")
            for item in content:
                if item['type'] == 'text':
                    print(f"     {item['text']}")
        else:
            print(f"   ✗ Failed to get status: {response}")

        # 6. Get current screenshot
        print("6. Getting current screenshot...")
        response = send_request(process, "tools/call", {
            "name": "rabbitize_get_screenshot",
            "arguments": {}
        }, 6)

        if response and "result" in response:
            content = response['result']['content']
            print(f"   ✓ Current screenshot retrieved")

            # Check if we got a screenshot
            for item in content:
                if item['type'] == 'image':
                    print(f"   ✓ Received current screenshot ({len(item['data'])} bytes)")

                    # Save screenshot for inspection
                    screenshot_path = Path("test_screenshot_current.jpg")
                    with open(screenshot_path, "wb") as f:
                        f.write(base64.b64decode(item['data']))
                    print(f"   ✓ Screenshot saved to {screenshot_path}")
                    break
        else:
            print(f"   ✗ Failed to get screenshot: {response}")

        # 7. End the session
        print("7. Ending session...")
        response = send_request(process, "tools/call", {
            "name": "rabbitize_end_session",
            "arguments": {}
        }, 7)

        if response and "result" in response:
            content = response['result']['content']
            print(f"   ✓ Session ended successfully")
            for item in content:
                if item['type'] == 'text':
                    print(f"     {item['text']}")
        else:
            print(f"   ✗ Failed to end session: {response}")

        print("\n✓ Test completed successfully!")
        print("Check the saved screenshots to see the results.")

    except Exception as e:
        print(f"Test failed with error: {e}")

    finally:
        # Clean up
        process.terminate()
        process.wait()

def test_server_startup():
    """Test that the server starts up correctly"""
    print("Testing server startup...")

    try:
        # Start the server briefly to test startup
        process = subprocess.Popen(
            [sys.executable, "rabbitize_mcp_server_simple.py", "--rabbitize-url", "http://localhost:3000"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Give it a moment to start
        time.sleep(2)

        # Send a simple ping
        if process.poll() is None:
            print("✓ Server started successfully")
            process.terminate()
            process.wait()
            return True
        else:
            print("✗ Server failed to start")
            stderr = process.stderr.read().decode()
            print(f"Error: {stderr}")
            return False

    except Exception as e:
        print(f"✗ Server startup test failed: {e}")
        return False

if __name__ == "__main__":
    print("=== Rabbitize MCP Server Test ===\n")

    # Check if the server file exists
    if not Path("rabbitize_mcp_server_simple.py").exists():
        print("✗ rabbitize_mcp_server_simple.py not found!")
        print("Please ensure the MCP server file is in the current directory.")
        sys.exit(1)

    # Test server startup first
    if not test_server_startup():
        print("\n✗ Server startup test failed. Check your setup.")
        sys.exit(1)

    print("\n" + "="*50)
    print("Running full MCP server test...")
    print("="*50 + "\n")

    # Run the full test
    test_mcp_server()