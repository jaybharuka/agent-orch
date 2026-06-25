"""Tool registry for discovering and retrieving LangChain tools."""
from app.agents.tools.definitions import (
    db_query,
    http_request,
    read_file,
    run_code,
    web_search,
    write_file,
)


class ToolRegistry:
    """Registry that returns tools by name and lists all available tools."""

    def __init__(self) -> None:
        self._tools = {
            "web_search": web_search,
            "read_file": read_file,
            "write_file": write_file,
            "run_code": run_code,
            "db_query": db_query,
            "http_request": http_request,
        }

    def get_tool(self, name: str):
        """Retrieve a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return a list of all available tool names."""
        return list(self._tools.keys())

    def get_all_tools(self) -> list:
        """Return all registered tool instances."""
        return list(self._tools.values())
