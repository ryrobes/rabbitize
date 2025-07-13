#!/usr/bin/env python3
"""
MCP Tool Testing Framework

Comprehensive testing for individual MCP tools including:
- Parameter validation
- Response structure validation
- Error case handling
- Performance testing
"""

import json
import subprocess
import sys
import time
import base64
from typing import Dict, Any, Optional

class MCPToolTester:
    """Framework for testing MCP tools systematically"""

    def __init__(self, server_command):
        self.server_command = server_command
        self.process = None

    def start_server(self):
        """Start the MCP server"""
        self.process = subprocess.Popen(
            self.server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Initialize the server
        init_response = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "tool-tester", "version": "1.0.0"}
        })

        return init_response.get("result") is not None

    def stop_server(self):
        """Stop the MCP server"""
        if self.process:
            self.process.terminate()
            self.process.wait()

    def send_request(self, method: str, params: Optional[Dict] = None, request_id: int = 1) -> Dict[str, Any]:
        """Send JSON-RPC request and return response"""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id
        }

        if params:
            request["params"] = params

        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()

        response_line = self.process.stdout.readline()
        return json.loads(response_line.strip()) if response_line else {}

    def test_tool_schema_validation(self):
        """Test that all tools have proper schemas"""
        print("🔍 Testing Tool Schema Validation")
        print("-" * 40)

        tools_response = self.send_request("tools/list")
        if not tools_response.get("result"):
            print("❌ Failed to get tools list")
            return False

        tools = tools_response["result"]["tools"]

        for tool in tools:
            print(f"Testing {tool['name']}...")

            # Check required fields
            required_fields = ['name', 'description', 'inputSchema']
            for field in required_fields:
                if field not in tool:
                    print(f"  ❌ Missing required field: {field}")
                    return False

            # Validate inputSchema structure
            schema = tool['inputSchema']
            if schema.get('type') != 'object':
                print(f"  ❌ inputSchema must be type 'object'")
                return False

            if 'properties' not in schema:
                print(f"  ❌ inputSchema missing 'properties'")
                return False

            print(f"  ✅ Schema valid")

        print("✅ All tool schemas valid\n")
        return True

    def test_tool_parameter_validation(self):
        """Test parameter validation for tools"""
        print("🔧 Testing Parameter Validation")
        print("-" * 40)

        # Test missing required parameters
        print("Testing missing required parameters...")
        response = self.send_request("tools/call", {
            "name": "rabbitize_start_session",
            "arguments": {}  # Missing required 'url'
        })

        if response.get("error") and response["error"]["code"] == -32602:
            print("  ✅ Properly rejected missing required parameter")
        else:
            print(f"  ❌ Should reject missing required parameter: {response}")
            return False

        # Test invalid tool name
        print("Testing invalid tool name...")
        response = self.send_request("tools/call", {
            "name": "nonexistent_tool",
            "arguments": {}
        })

        if response.get("error") and response["error"]["code"] == -32601:
            print("  ✅ Properly rejected invalid tool name")
        else:
            print(f"  ❌ Should reject invalid tool name: {response}")
            return False

        print("✅ Parameter validation working correctly\n")
        return True

    def test_tool_response_structure(self):
        """Test that tool responses have proper structure"""
        print("📋 Testing Response Structure")
        print("-" * 40)

        # Test a simple tool first (status)
        print("Testing rabbitize_status response...")
        response = self.send_request("tools/call", {
            "name": "rabbitize_status",
            "arguments": {}
        })

        if not response.get("result"):
            print(f"  ❌ No result in response: {response}")
            return False

        result = response["result"]

        # Check for 'content' field
        if "content" not in result:
            print(f"  ❌ Missing 'content' field: {result}")
            return False

        content = result["content"]
        if not isinstance(content, list):
            print(f"  ❌ 'content' should be a list: {type(content)}")
            return False

        # Check content items have proper structure
        for item in content:
            if "type" not in item:
                print(f"  ❌ Content item missing 'type': {item}")
                return False

            if item["type"] == "text" and "text" not in item:
                print(f"  ❌ Text content missing 'text' field: {item}")
                return False

            if item["type"] == "image":
                required_image_fields = ["data", "mimeType"]
                for field in required_image_fields:
                    if field not in item:
                        print(f"  ❌ Image content missing '{field}': {item}")
                        return False

        print("  ✅ Response structure valid")
        print("✅ Response structure testing complete\n")
        return True

    def test_performance(self):
        """Test response times for tools"""
        print("⏱️  Testing Performance")
        print("-" * 40)

        # Test status tool performance (should be fast)
        start_time = time.time()
        response = self.send_request("tools/call", {
            "name": "rabbitize_status",
            "arguments": {}
        })
        end_time = time.time()

        response_time = end_time - start_time
        print(f"Status tool response time: {response_time:.3f}s")

        if response_time > 5.0:  # Should respond within 5 seconds
            print(f"  ❌ Response too slow: {response_time:.3f}s")
            return False
        else:
            print(f"  ✅ Response time acceptable")

        print("✅ Performance testing complete\n")
        return True

    def run_all_tests(self):
        """Run all testing suites"""
        print("🚀 Starting Comprehensive MCP Tool Testing")
        print("=" * 50)

        if not self.start_server():
            print("❌ Failed to start server")
            return False

        try:
            tests = [
                self.test_tool_schema_validation,
                self.test_tool_parameter_validation,
                self.test_tool_response_structure,
                self.test_performance
            ]

            for test in tests:
                if not test():
                    print(f"❌ Test failed: {test.__name__}")
                    return False

            print("🎉 All tests passed!")
            return True

        finally:
            self.stop_server()

def main():
    """Run the tool testing framework"""
    tester = MCPToolTester([sys.executable, "rabbitize_mcp_server_simple.py"])
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()