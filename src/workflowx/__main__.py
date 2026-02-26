"""Allow running WorkflowX MCP server directly: python -m workflowx"""
from workflowx.mcp_server import run_mcp_stdio

if __name__ == "__main__":
    run_mcp_stdio()
