#!/usr/bin/env bash
#
# WorkflowX MCP Setup — one command to connect Claude to your workflows.
#
# Usage:
#   cd workflowx && bash setup-mcp.sh
#
# What this does:
#   1. Installs workflowx with MCP + capture + inference dependencies
#   2. Merges workflowx config into your Claude Desktop MCP settings
#   3. Verifies the MCP server can start
#
# After running this, restart Claude Desktop and you'll see 12 new tools.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}WorkflowX MCP Setup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 1: Install ──────────────────────────────────────────
echo -e "\n${BOLD}[1/3] Installing workflowx...${NC}"

if pip install -e ".[all]" --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} workflowx installed with all extras"
else
    echo -e "  ${YELLOW}Trying with --break-system-packages...${NC}"
    pip install -e ".[all]" --break-system-packages --quiet
    echo -e "  ${GREEN}✓${NC} workflowx installed"
fi

# ── Step 2: Claude Desktop Config ────────────────────────────
echo -e "\n${BOLD}[2/3] Configuring Claude Desktop...${NC}"

WORKFLOWX_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH="$(which python3 || which python)"

# Detect Claude Desktop config location
if [[ "$OSTYPE" == "darwin"* ]]; then
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
elif [[ "$OSTYPE" == "linux"* ]]; then
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Claude"
else
    CONFIG_DIR="$HOME/AppData/Roaming/Claude"
fi

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# Create config dir if needed
mkdir -p "$CONFIG_DIR"

# Build the workflowx MCP entry
WORKFLOWX_ENTRY=$(cat <<EOF
{
  "command": "$PYTHON_PATH",
  "args": ["-m", "workflowx.mcp_server"],
  "env": {
    "WORKFLOWX_DATA_DIR": "$HOME/.workflowx",
    "WORKFLOWX_HOURLY_RATE": "75"
  }
}
EOF
)

if [ -f "$CONFIG_FILE" ]; then
    # Merge into existing config using python
    python3 -c "
import json, sys

config_path = '$CONFIG_FILE'
with open(config_path) as f:
    config = json.load(f)

config.setdefault('mcpServers', {})
config['mcpServers']['workflowx'] = json.loads('''$WORKFLOWX_ENTRY''')

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f'  Updated: {config_path}')
print(f'  MCP servers: {list(config[\"mcpServers\"].keys())}')
"
else
    # Create new config
    python3 -c "
import json

config = {'mcpServers': {'workflowx': json.loads('''$WORKFLOWX_ENTRY''')}}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)

print(f'  Created: $CONFIG_FILE')
"
fi
echo -e "  ${GREEN}✓${NC} Claude Desktop configured"

# ── Step 3: Verify ───────────────────────────────────────────
echo -e "\n${BOLD}[3/3] Verifying MCP server...${NC}"

if python3 -c "from workflowx.mcp_server import create_mcp_server; s = create_mcp_server(); assert s is not None; print('  Server created with', len(s._tool_manager._tools) if hasattr(s, '_tool_manager') else '12+', 'tools')" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} MCP server is ready"
else
    # Fallback check
    if python3 -c "from workflowx.mcp_server import TOOL_REGISTRY; print(f'  {len(TOOL_REGISTRY)} tools registered')"; then
        echo -e "  ${GREEN}✓${NC} MCP server module loads correctly"
    else
        echo -e "  ${RED}✗${NC} MCP server failed to load. Check: pip install 'workflowx[mcp]'"
        exit 1
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Desktop"
echo "  2. Look for the 🔌 icon — you should see 'workflowx' with 12 tools"
echo "  3. Ask Claude: \"Check my workflowx status\""
echo ""
echo "If Screenpipe is running, try:"
echo "  \"Capture my last 4 hours of work and tell me what I was doing\""
echo "  \"What are my highest-friction workflows this week?\""
echo "  \"Propose a replacement for my worst time sink\""
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
