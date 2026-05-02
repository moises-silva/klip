"""
MCP host — connects to Google Workspace remote MCP servers over HTTP.
Implemented in Phase 4.

Architecture:
  Our app is an MCP *host*. It dispatches tool calls from Gemini to the
  appropriate remote MCP server using the user's delegated OAuth access token.
"""

# Official Google Workspace MCP server endpoints (HTTP transport)
CHAT_MCP_URL = "https://chatmcp.googleapis.com"
# People/directory MCP endpoint — confirm exact URL from Google documentation
PEOPLE_MCP_URL = "https://mcp.googleapis.com/people"  # placeholder


class WorkspaceMcpClient:
    """
    Connects to Google Workspace remote MCP servers on behalf of a user.
    Each instance is scoped to one user's OAuth access token.
    """

    def __init__(self, access_token: str):
        self.access_token = access_token

    async def list_tools(self) -> list[dict]:
        """Return combined tool manifests from all Workspace MCP servers."""
        # TODO Phase 4: open MCP sessions to CHAT_MCP_URL and PEOPLE_MCP_URL,
        #               call session.list_tools(), merge and return definitions.
        raise NotImplementedError("MCP client not yet implemented (Phase 4)")

    async def call_tool(self, tool_name: str, args: dict) -> dict:
        """Dispatch a tool call to the correct remote MCP server."""
        # TODO Phase 4: route to CHAT_MCP_URL or PEOPLE_MCP_URL based on
        #               tool_name prefix, forward args, return result content.
        raise NotImplementedError("MCP client not yet implemented (Phase 4)")
