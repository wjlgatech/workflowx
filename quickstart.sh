#!/usr/bin/env bash
#
# WorkflowX Quickstart — from zero to real data in 10 minutes.
#
# Run this ON YOUR MAC (not in Cowork VM):
#   cd ~/Projects/workflowx && bash quickstart.sh
#
# What it does:
#   1. Checks/installs Screenpipe
#   2. Installs workflowx with all dependencies
#   3. Wires up Claude Desktop MCP config
#   4. Runs first capture to verify everything works
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  WorkflowX Quickstart${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── Step 1: Screenpipe ───────────────────────────────────────
echo -e "\n${BOLD}[1/4] Screenpipe${NC}"

if command -v screenpipe &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Already installed: $(which screenpipe)"
elif [ -d "/Applications/screenpipe.app" ] || [ -d "$HOME/Applications/screenpipe.app" ]; then
    echo -e "  ${GREEN}✓${NC} Screenpipe.app found"
else
    echo -e "  ${YELLOW}Not found.${NC} Install Screenpipe first:"
    echo ""
    echo "    Option A (brew):  brew install mediar-ai/screenpipe/screenpipe"
    echo "    Option B (app):   https://screenpi.pe — download the macOS app"
    echo ""
    echo "  After installing, start Screenpipe and re-run this script."
    echo "  Screenpipe needs to run for at least 30 minutes to gather useful data."
    echo ""
    read -p "  Press Enter if Screenpipe is running, or Ctrl+C to install it first... "
fi

# Check if Screenpipe DB exists
SP_DB="$HOME/.screenpipe/db.sqlite"
if [ -f "$SP_DB" ]; then
    SP_SIZE=$(du -h "$SP_DB" | cut -f1)
    echo -e "  ${GREEN}✓${NC} Database: $SP_DB ($SP_SIZE)"
else
    echo -e "  ${YELLOW}⚠${NC} No database at $SP_DB"
    echo "    Start Screenpipe and let it run for a while, then re-run this script."
    echo "    The database is created after Screenpipe captures its first screen events."
fi

# ── Step 2: Install WorkflowX ───────────────────────────────
echo -e "\n${BOLD}[2/4] Installing workflowx${NC}"

PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo -e "  ${RED}✗${NC} Python not found. Install Python 3.10+."
    exit 1
fi

echo -e "  Python: $($PYTHON_CMD --version)"

# Install with all extras
if $PYTHON_CMD -m pip install -e ".[all]" --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} workflowx installed"
elif $PYTHON_CMD -m pip install -e ".[all]" --break-system-packages --quiet 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} workflowx installed (--break-system-packages)"
else
    echo -e "  ${YELLOW}Trying with venv...${NC}"
    $PYTHON_CMD -m venv .venv
    source .venv/bin/activate
    pip install -e ".[all]" --quiet
    PYTHON_CMD="$(pwd)/.venv/bin/python"
    echo -e "  ${GREEN}✓${NC} workflowx installed in venv"
fi

# Verify
WX_VERSION=$($PYTHON_CMD -c "from workflowx import __version__; print(__version__)" 2>/dev/null || echo "unknown")
echo -e "  Version: $WX_VERSION"

# Find the actual python path for MCP config
PYTHON_PATH="$($PYTHON_CMD -c 'import sys; print(sys.executable)')"

# ── Step 3: Claude Desktop MCP ──────────────────────────────
echo -e "\n${BOLD}[3/4] Claude Desktop MCP config${NC}"

CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"
mkdir -p "$CONFIG_DIR"

# Build workflowx MCP entry with absolute python path
$PYTHON_CMD -c "
import json, os

config_file = '$CONFIG_FILE'
python_path = '$PYTHON_PATH'
home = os.path.expanduser('~')

# The MCP server entry
wx_entry = {
    'command': python_path,
    'args': ['-m', 'workflowx.mcp_server'],
    'env': {
        'WORKFLOWX_DATA_DIR': os.path.join(home, '.workflowx'),
        'WORKFLOWX_HOURLY_RATE': '75',
    }
}

# Load existing config or create new
if os.path.exists(config_file):
    with open(config_file) as f:
        config = json.load(f)
    existing_servers = list(config.get('mcpServers', {}).keys())
    print(f'  Existing MCP servers: {existing_servers}')
else:
    config = {}

config.setdefault('mcpServers', {})
config['mcpServers']['workflowx'] = wx_entry

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)

print(f'  Config: {config_file}')
print(f'  Python: {python_path}')
print(f'  Servers: {list(config[\"mcpServers\"].keys())}')
"
echo -e "  ${GREEN}✓${NC} Claude Desktop configured"

# ── Step 4: First capture ────────────────────────────────────
echo -e "\n${BOLD}[4/4] First capture test${NC}"

if [ -f "$SP_DB" ]; then
    # Try a 2-hour capture
    $PYTHON_CMD -c "
from workflowx.config import load_config
from workflowx.capture.screenpipe import ScreenpipeAdapter
from workflowx.inference.clusterer import cluster_into_sessions
from workflowx.storage import LocalStore
from datetime import datetime, timedelta

config = load_config()
sp = ScreenpipeAdapter(db_path=config.screenpipe_db_path)

if not sp.is_available():
    print('  Screenpipe DB not found. Start Screenpipe first.')
    exit(0)

since = datetime.now() - timedelta(hours=2)
events = sp.read_events(since=since, limit=2000)
print(f'  Events (last 2h): {len(events)}')

if events:
    sessions = cluster_into_sessions(events, gap_minutes=config.session_gap_minutes, min_events=config.min_session_events)
    store = LocalStore(config.data_dir)
    store.save_sessions(sessions)
    print(f'  Sessions created: {len(sessions)}')
    for s in sessions[:5]:
        apps = ', '.join(s.apps_used[:3])
        print(f'    {s.start_time.strftime(\"%H:%M\")}-{s.end_time.strftime(\"%H:%M\")}  {s.total_duration_minutes:.0f}min  [{apps}]  {s.friction_level.value}')
    if len(sessions) > 5:
        print(f'    ... and {len(sessions) - 5} more')
    print(f'  Saved to: {config.data_dir}')
else:
    print('  No events found. Screenpipe may need more time to capture data.')
    print('  Let it run for 30+ minutes, then re-run this script.')
"
else
    echo -e "  ${YELLOW}Skipped${NC} — no Screenpipe DB yet."
    echo "  Start Screenpipe, wait 30 min, then run:"
    echo "    workflowx capture --hours 2"
fi

# ── Summary ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next:"
echo "  1. RESTART Claude Desktop (Cmd+Q, reopen)"
echo "  2. Look for the wrench icon → 'workflowx' with 12 tools"
echo "  3. Say: \"Check my workflowx status\""
echo ""
echo "  Once Screenpipe has 30+ min of data:"
echo "  \"Capture my last 2 hours and tell me what I've been doing\""
echo "  \"What's eating my time? Show me the friction.\""
echo "  \"Propose a replacement for my worst workflow\""
echo ""
