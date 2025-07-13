# 🧪 Complete Guide to Testing MCP Servers

This guide covers all the effective approaches for testing Model Context Protocol (MCP) servers, from basic protocol compliance to full integration testing.

## 🎯 Testing Approaches Overview

| Method | Purpose | When to Use | Effort Level |
|--------|---------|-------------|--------------|
| **Protocol Testing** | JSON-RPC compliance | Always (foundational) | Low |
| **Tool Testing** | Individual tool behavior | Core functionality | Medium |
| **Integration Testing** | End-to-end workflows | Real-world scenarios | High |
| **Client Testing** | MCP client compatibility | Production readiness | Medium |
| **Performance Testing** | Response times & load | Production optimization | Medium |

---

## 1. 🔧 **Protocol Testing** (Essential)

Tests the fundamental MCP JSON-RPC implementation.

### **What to Test:**
- ✅ Server initialization
- ✅ Tool enumeration (`tools/list`)
- ✅ Error handling (invalid methods/params)
- ✅ JSON-RPC compliance

### **Example:**
```python
# Test basic protocol compliance
def test_mcp_protocol():
    # 1. Initialize server
    init_response = send_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "clientInfo": {"name": "test-client", "version": "1.0.0"}
    })

    # 2. List tools
    tools_response = send_request("tools/list")

    # 3. Test error handling
    error_response = send_request("invalid/method")
```

**✅ Run:** `python3 simple_mcp_test.py`

---

## 2. 🛠️ **Tool Testing** (Critical)

Tests individual tool behavior, parameters, and responses.

### **What to Test:**
- ✅ Schema validation (required fields, types)
- ✅ Parameter validation (missing/invalid params)
- ✅ Response structure (content format)
- ✅ Error cases (invalid inputs)
- ✅ Performance (response times)

### **Tool Schema Validation:**
```python
# Verify each tool has proper schema
for tool in tools:
    assert 'name' in tool
    assert 'description' in tool
    assert 'inputSchema' in tool
    assert tool['inputSchema']['type'] == 'object'
    assert 'properties' in tool['inputSchema']
```

### **Parameter Validation:**
```python
# Test missing required parameters
response = call_tool("rabbitize_start_session", {})  # Missing 'url'
assert response['error']['code'] == -32602  # Invalid params
```

### **Response Structure:**
```python
# Validate MCP content format
response = call_tool("rabbitize_status", {})
content = response['result']['content']
assert isinstance(content, list)
for item in content:
    assert 'type' in item  # text, image, etc.
```

**✅ Run:** `python3 mcp_tool_testing.py`

---

## 3. 🔄 **Integration Testing** (Real-world)

Tests complete workflows from start to finish.

### **What to Test:**
- ✅ Session lifecycle (start → commands → end)
- ✅ State management (session persistence)
- ✅ Image handling (base64 screenshots)
- ✅ Error recovery (failed commands)

### **Complete Workflow Test:**
```python
def test_complete_workflow():
    # 1. Start session
    start_result = call_tool("rabbitize_start_session", {
        "url": "https://example.com"
    })
    assert start_result['success']
    assert 'screenshot' in start_result

    # 2. Execute commands
    execute_result = call_tool("rabbitize_execute", {
        "command": [":move-mouse", ":to", "100", "200"]
    })
    assert execute_result['success']
    assert 'screenshot' in execute_result

    # 3. End session
    end_result = call_tool("rabbitize_end_session", {})
    assert end_result['success']
```

**✅ Run:** `python3 test_mcp_server.py`

---

## 4. 🤝 **Client Compatibility Testing**

Tests with real MCP clients (Claude Desktop, etc.).

### **Manual Testing with Claude Desktop:**

1. **Configure Claude Desktop:**
   ```json
   {
     "mcpServers": {
       "rabbitize": {
         "command": "python3",
         "args": ["/path/to/rabbitize_mcp_server_simple.py"]
       }
     }
   }
   ```

2. **Test in Claude:**
   ```
   "Start a Rabbitize session at https://example.com"
   "Move the mouse to coordinates 200, 300"
   "Take a screenshot"
   "End the session"
   ```

3. **Verify:**
   - ✅ Tools appear in Claude
   - ✅ Screenshots display correctly
   - ✅ Error messages are clear
   - ✅ Session state is maintained

### **Automated Client Testing:**
```python
# Test with MCP client libraries
from mcp import Client

async def test_with_mcp_client():
    client = Client("python3", ["rabbitize_mcp_server_simple.py"])
    await client.initialize()

    tools = await client.list_tools()
    assert len(tools) == 5

    result = await client.call_tool("rabbitize_status", {})
    assert result['content']
```

---

## 5. ⚡ **Performance Testing**

Tests response times, memory usage, and scalability.

### **Response Time Testing:**
```python
def test_performance():
    # Test fast operations (< 1s)
    start_time = time.time()
    call_tool("rabbitize_status", {})
    assert (time.time() - start_time) < 1.0

    # Test medium operations (< 10s)
    start_time = time.time()
    call_tool("rabbitize_start_session", {"url": "https://example.com"})
    assert (time.time() - start_time) < 10.0
```

### **Memory/Resource Testing:**
```python
import psutil

def test_resource_usage():
    process = start_mcp_server()

    # Monitor memory usage
    memory_before = psutil.Process(process.pid).memory_info().rss

    # Execute many commands
    for i in range(100):
        call_tool("rabbitize_status", {})

    memory_after = psutil.Process(process.pid).memory_info().rss

    # Memory shouldn't grow significantly
    assert (memory_after - memory_before) < 100 * 1024 * 1024  # 100MB
```

---

## 6. 🐛 **Error Handling Testing**

Tests failure scenarios and error recovery.

### **Network Errors:**
```python
def test_network_errors():
    # Start MCP server with invalid Rabbitize URL
    server = start_server(rabbitize_url="http://localhost:9999")

    # Should handle connection errors gracefully
    response = call_tool("rabbitize_start_session", {"url": "https://example.com"})
    assert not response['success']
    assert 'connection' in response['error'].lower()
```

### **Invalid Inputs:**
```python
def test_invalid_inputs():
    # Test with various invalid inputs
    test_cases = [
        {"url": "not-a-url"},  # Invalid URL
        {"url": ""},           # Empty URL
        {"url": None},         # Null URL
    ]

    for case in test_cases:
        response = call_tool("rabbitize_start_session", case)
        assert not response['success']
```

---

## 7. 📊 **Testing Best Practices**

### **Automated Testing Pipeline:**
```bash
#!/bin/bash
# run_tests.sh - Complete testing pipeline

echo "🧪 Running MCP Server Tests..."

# 1. Protocol tests
python3 simple_mcp_test.py || exit 1

# 2. Tool tests
python3 mcp_tool_testing.py || exit 1

# 3. Integration tests
python3 test_mcp_server.py || exit 1

# 4. Performance tests
python3 performance_tests.py || exit 1

echo "✅ All tests passed!"
```

### **Continuous Integration:**
```yaml
# .github/workflows/test-mcp.yml
name: Test MCP Server
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.8'
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: ./run_tests.sh
```

### **Test Organization:**
```
tests/
├── unit/
│   ├── test_protocol.py      # Basic protocol tests
│   ├── test_tools.py         # Individual tool tests
│   └── test_schemas.py       # Schema validation
├── integration/
│   ├── test_workflows.py     # End-to-end workflows
│   └── test_session_mgmt.py  # Session management
├── performance/
│   ├── test_response_times.py
│   └── test_memory_usage.py
└── compatibility/
    ├── test_claude_desktop.py
    └── test_other_clients.py
```

---

## 8. 🎯 **Testing Checklist**

### **Before Release:**
- [ ] All protocol tests pass
- [ ] All tools have valid schemas
- [ ] Parameter validation works
- [ ] Error handling is comprehensive
- [ ] Response times are acceptable
- [ ] Memory usage is stable
- [ ] Works with target MCP clients
- [ ] Documentation is accurate

### **For Production:**
- [ ] Load testing completed
- [ ] Security testing done
- [ ] Monitoring/logging configured
- [ ] Error reporting set up
- [ ] Performance benchmarks established

---

## 🚀 **Quick Start Testing**

1. **Install dependencies:**
   ```bash
   python3 -m venv test_env
   source test_env/bin/activate
   pip install requests aiofiles
   ```

2. **Run all tests:**
   ```bash
   # Basic protocol compliance
   python3 simple_mcp_test.py

   # Comprehensive tool testing
   python3 mcp_tool_testing.py

   # Full integration test
   python3 test_mcp_server.py
   ```

3. **Test with real client:**
   - Configure Claude Desktop with your MCP server
   - Try the tools manually
   - Verify screenshots and responses

---

This comprehensive testing approach ensures your MCP server is reliable, performant, and compatible with MCP clients. Start with protocol testing, then move through tool testing to full integration testing for production readiness!