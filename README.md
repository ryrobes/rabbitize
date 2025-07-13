# Rabbitize MCP Server

A Model Context Protocol (MCP) server that provides LLMs with tools to control Rabbitize browser automation sessions. This server acts as a proxy between LLMs and Rabbitize, automatically managing session lifecycle and returning screenshots as base64 images.

## Features

- **Automatic Session Management**: Handles Rabbitize session creation and cleanup
- **Visual Feedback**: Returns screenshots as base64 images after each command
- **MCP Protocol Compliance**: Implements the standard MCP protocol over stdin/stdout
- **Command Execution**: Supports all Rabbitize commands (clicks, navigation, etc.)
- **Error Handling**: Robust error handling with meaningful error messages
- **Session Status**: Real-time session status monitoring

## Installation

### Prerequisites

1. **Python 3.8+** installed
2. **Rabbitize server** running (typically on `http://localhost:3000`)
3. **Node.js** and **npm** for running Rabbitize

### Setup

1. **Clone/Download the MCP server files**:
   ```bash
   # Download the files to your project directory
   wget https://example.com/rabbitize_mcp_server_simple.py
   wget https://example.com/requirements.txt
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Make the server executable**:
   ```bash
   chmod +x rabbitize_mcp_server_simple.py
   ```

4. **Start your Rabbitize server**:
   ```bash
   cd /path/to/rabbitize
   npm start
   # or
   node src/server.js
   ```

## Usage

### Running the MCP Server

The MCP server communicates over stdin/stdout using JSON-RPC protocol:

```bash
# Basic usage
python rabbitize_mcp_server_simple.py

# With custom Rabbitize URL
python rabbitize_mcp_server_simple.py --rabbitize-url http://localhost:3000

# With debug logging
python rabbitize_mcp_server_simple.py --log-level DEBUG
```

### Available Tools

The server provides the following tools to LLMs:

#### 1. `rabbitize_start_session`
Start a new browser session with a given URL.

**Parameters:**
- `url` (string): The URL to navigate to

**Returns:**
- Success message with session details
- Base64 encoded screenshot of the initial page

**Example:**
```json
{
  "name": "rabbitize_start_session",
  "arguments": {
    "url": "https://example.com"
  }
}
```

#### 2. `rabbitize_execute`
Execute a command in the active session.

**Parameters:**
- `command` (array): Command as array of strings

**Returns:**
- Command execution result
- Base64 encoded screenshot after command execution

**Example:**
```json
{
  "name": "rabbitize_execute",
  "arguments": {
    "command": [":move-mouse", ":to", "100", "200"]
  }
}
```

**Common Commands:**
- `[":click"]` - Click at current mouse position
- `[":move-mouse", ":to", "100", "200"]` - Move mouse to coordinates
- `[":scroll-wheel-down", "3"]` - Scroll down 3 clicks
- `[":keypress", "Enter"]` - Press Enter key
- `[":url", "https://example.com"]` - Navigate to URL

#### 3. `rabbitize_get_screenshot`
Get the latest screenshot from the active session.

**Parameters:** None

**Returns:**
- Base64 encoded screenshot of current page state

#### 4. `rabbitize_end_session`
End the current session and cleanup resources.

**Parameters:** None

**Returns:**
- Session termination confirmation
- Statistics about the session

#### 5. `rabbitize_status`
Get current session status information.

**Parameters:** None

**Returns:**
- Session status details (active, session ID, command count, etc.)

## Integration with LLMs

### Claude Desktop

To use with Claude Desktop, add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rabbitize": {
      "command": "python",
      "args": ["/path/to/rabbitize_mcp_server_simple.py"],
      "env": {
        "PYTHONPATH": "/path/to/your/project"
      }
    }
  }
}
```

### Other MCP Clients

The server implements the standard MCP protocol and should work with any MCP-compatible client:

1. **Start the server** as a subprocess
2. **Communicate via stdin/stdout** using JSON-RPC
3. **Send initialize request** first
4. **Use tools/list** to get available tools
5. **Call tools** using tools/call method

## Example Workflow

Here's a typical workflow when using the MCP server:

1. **Initialize Session**:
   ```
   LLM calls rabbitize_start_session with URL
   → Server starts Rabbitize session
   → Returns screenshot of loaded page
   ```

2. **Interact with Page**:
   ```
   LLM calls rabbitize_execute with mouse/keyboard commands
   → Server executes command in browser
   → Returns screenshot showing the result
   ```

3. **Get Current State**:
   ```
   LLM calls rabbitize_get_screenshot
   → Server returns current page screenshot
   ```

4. **End Session**:
   ```
   LLM calls rabbitize_end_session
   → Server cleanup and returns session stats
   ```

## Configuration

### Environment Variables

- `RABBITIZE_URL`: Default Rabbitize server URL (default: `http://localhost:3000`)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

### Command Line Arguments

- `--rabbitize-url`: Set Rabbitize server URL
- `--log-level`: Set logging level

## Error Handling

The server provides comprehensive error handling:

- **Connection Errors**: When Rabbitize server is unreachable
- **Session Errors**: When session fails to start or becomes invalid
- **Command Errors**: When commands fail to execute
- **Protocol Errors**: When JSON-RPC protocol is violated

All errors are returned as standard JSON-RPC error responses with descriptive messages.

## Troubleshooting

### Common Issues

1. **"Connection refused" errors**:
   - Ensure Rabbitize server is running on the expected port
   - Check firewall settings
   - Verify the URL is correct

2. **"No screenshot available"**:
   - Session may not have started properly
   - Check Rabbitize server logs
   - Ensure sufficient disk space for screenshots

3. **"Session not active"**:
   - Start a session first using `rabbitize_start_session`
   - Check if session timed out or crashed

### Debug Mode

Run with debug logging to see detailed information:

```bash
python rabbitize_mcp_server_simple.py --log-level DEBUG
```

### Log Files

Logs are written to stderr and include:
- Session lifecycle events
- Command execution details
- Error messages with stack traces
- Screenshot capture attempts

## Architecture

```
LLM Client
    ↓ (MCP Protocol over stdin/stdout)
MCP Server
    ↓ (HTTP API calls)
Rabbitize Server
    ↓ (Controls)
Playwright Browser
```

The MCP server acts as a bridge, translating MCP tool calls into Rabbitize API calls and returning structured responses with screenshots.

## Security Considerations

- The server runs browser automation, which can be security-sensitive
- Only run in trusted environments
- Be cautious with URLs and commands from untrusted sources
- Consider network isolation for production use

## Performance Tips

- Screenshots are automatically compressed to reduce memory usage
- Session cleanup happens automatically on shutdown
- Consider screenshot resolution vs. performance trade-offs
- Monitor disk space usage for screenshot storage

## Contributing

To extend the MCP server:

1. Add new tools in the `_register_tools()` method
2. Implement tool handlers in `_handle_tools_call()`
3. Update the documentation
4. Test with various MCP clients

## License

This project is provided as-is for educational and development purposes.
