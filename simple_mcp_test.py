#!/usr/bin/env python3
"""
Simple MCP Protocol Test

Demonstrates the basic approach to testing any MCP server by sending
raw JSON-RPC messages and validating responses.
"""

import json
import subprocess
import sys

def test_mcp_protocol_basics():
    """Test basic MCP protocol compliance"""

    print("🧪 Testing MCP Protocol Basics")
    print("=" * 40)

    # Start the MCP server
    process = subprocess.Popen(
        [sys.executable, "rabbitize_mcp_server_simple.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    def send_and_receive(request):
        """Send JSON-RPC request and get response"""
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        response_line = process.stdout.readline()
        return json.loads(response_line.strip()) if response_line else None

    try:
        # Test 1: Server Initialization
        print("1. Testing server initialization...")
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }

        response = send_and_receive(init_request)
        if response and response.get("result"):
            print(f"   ✓ Server name: {response['result']['name']}")
            print(f"   ✓ Protocol version: {response['result']['protocolVersion']}")
        else:
            print(f"   ✗ Initialization failed: {response}")
            return False

        # Test 2: Tools List
        print("2. Testing tools enumeration...")
        tools_request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 2
        }

        response = send_and_receive(tools_request)
        if response and response.get("result"):
            tools = response['result']['tools']
            print(f"   ✓ Found {len(tools)} tools:")
            for tool in tools:
                print(f"     - {tool['name']}")
        else:
            print(f"   ✗ Tools list failed: {response}")
            return False

        # Test 3: Invalid Method (Error Handling)
        print("3. Testing error handling...")
        invalid_request = {
            "jsonrpc": "2.0",
            "method": "nonexistent/method",
            "id": 3
        }

        response = send_and_receive(invalid_request)
        if response and response.get("error"):
            print(f"   ✓ Proper error handling: {response['error']['message']}")
        else:
            print(f"   ✗ Error handling failed: {response}")
            return False

        print("\n✅ Basic MCP protocol tests passed!")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

    finally:
        process.terminate()
        process.wait()

if __name__ == "__main__":
    test_mcp_protocol_basics()