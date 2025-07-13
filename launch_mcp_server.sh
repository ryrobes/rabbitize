#!/bin/bash
# Launch script for Rabbitize MCP Server

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🐰 Rabbitize MCP Server Launcher${NC}"
echo "=================================="

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is required but not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Using Python $PYTHON_VERSION"

# Check if requirements are installed
if ! python3 -c "import requests, aiofiles" &> /dev/null; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip3 install -r requirements.txt
fi

# Check if Rabbitize server is running
RABBITIZE_URL="${RABBITIZE_URL:-http://localhost:3000}"
echo "Checking if Rabbitize server is running at $RABBITIZE_URL..."

if curl -s -f "$RABBITIZE_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Rabbitize server is running${NC}"
elif curl -s -f "$RABBITIZE_URL" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Rabbitize server is running${NC}"
else
    echo -e "${YELLOW}⚠ Rabbitize server not detected at $RABBITIZE_URL${NC}"
    echo "Please ensure Rabbitize is running before using the MCP server."
    echo "You can start it with: npm start (in the Rabbitize directory)"
    echo ""
    echo "Continuing anyway - the MCP server will start but tools will fail until Rabbitize is running..."
fi

# Create the rabbitize-runs directory if it doesn't exist
mkdir -p rabbitize-runs
echo "Created rabbitize-runs directory for session data"

# Set default log level
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Start the MCP server
echo -e "${GREEN}Starting MCP server...${NC}"
echo "Log level: $LOG_LEVEL"
echo "Rabbitize URL: $RABBITIZE_URL"
echo ""
echo "The server will communicate over stdin/stdout using JSON-RPC protocol."
echo "To test the server, run: python3 test_mcp_server.py"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

# Execute the MCP server
exec python3 rabbitize_mcp_server_simple.py \
    --rabbitize-url "$RABBITIZE_URL" \
    --log-level "$LOG_LEVEL" \
    "$@"