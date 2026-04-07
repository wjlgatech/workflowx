"""WorkflowX MS Graph module — authentication and API access for Outlook/Teams."""

from workflowx.ms_graph.auth import MSGraphAuth
from workflowx.ms_graph.client import MSGraphClient

__all__ = ["MSGraphAuth", "MSGraphClient"]
