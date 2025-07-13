# Rabbitize MCP Server - Project Structure

## Files Created

### Core MCP Server Files

1. **`rabbitize_mcp_server_simple.py`** - The main MCP server implementation
   - Implements JSON-RPC over stdin/stdout
   - Manages Rabbitize session lifecycle
   - Provides 5 tools for LLM interaction
   - Converts screenshots to base64 automatically

2. **`requirements.txt`** - Python dependencies
   - Flask, requests, aiofiles, etc.
   - All dependencies needed to run the MCP server

### Documentation

3. **`README.md`** - Comprehensive documentation
   - Installation instructions
   - Usage examples
   - Tool descriptions
   - Integration guides for Claude Desktop and other MCP clients

4. **`PROJECT_STRUCTURE.md`** - This file (project overview)

### Testing and Utilities

5. **`test_mcp_server.py`** - Test script for the MCP server
   - Demonstrates full workflow
   - Tests all 5 tools
   - Saves screenshots for inspection
   - Useful for debugging and validation

6. **`launch_mcp_server.sh`** - Launch script (executable)
   - Checks prerequisites
   - Verifies Rabbitize is running
   - Sets up environment
   - Starts the MCP server

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start Rabbitize server** (in another terminal):
   ```bash
   cd /path/to/rabbitize
   npm start
   ```

3. **Launch MCP server**:
   ```bash
   ./launch_mcp_server.sh
   ```

4. **Test the server**:
   ```bash
   python3 test_mcp_server.py
   ```

## Available Tools

- `rabbitize_start_session` - Start browser session
- `rabbitize_execute` - Execute commands with screenshot feedback
- `rabbitize_get_screenshot` - Get current screenshot
- `rabbitize_end_session` - End session
- `rabbitize_status` - Get session status

## Integration

### With Claude Desktop
Add to `claude_desktop_config.json`:
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

### With Other MCP Clients
The server uses standard JSON-RPC over stdin/stdout, so it should work with any MCP-compatible client.

## Architecture

```
LLM Client → MCP Server → Rabbitize API → Playwright Browser
```

The MCP server acts as a bridge, providing a clean tool interface for LLMs while handling all the session management and image processing automatically.

## Key Features

- **Visual Feedback**: Every command returns a screenshot
- **Session Management**: Automatic session lifecycle handling
- **Error Handling**: Comprehensive error reporting
- **Base64 Images**: Screenshots converted to base64 for LLM consumption
- **Standard Protocol**: Uses MCP protocol for compatibility

## Next Steps

1. Test the server with `test_mcp_server.py`
2. Integrate with your MCP client (Claude Desktop, etc.)
3. Start automating web tasks with visual feedback!

This is a much more efficient approach than creating large tool definitions, as the MCP server handles all the complexity and provides a clean interface for LLMs to interact with Rabbitize.