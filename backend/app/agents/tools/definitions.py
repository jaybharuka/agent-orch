"""LangChain tool definitions for the agent orchestration system."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Literal

import httpx
from langchain.tools import tool
from sqlalchemy import text

from app.agents.tools.logging import log_tool_invocation
from app.db.session import async_session


WORKSPACE_ROOT = Path("/workspace").resolve()


def _resolve_workspace_path(path: str) -> Path:
    """Resolve a path strictly inside /workspace."""
    target = (WORKSPACE_ROOT / path).resolve()
    if WORKSPACE_ROOT not in target.parents and target != WORKSPACE_ROOT:
        raise ValueError(f"Path must be within {WORKSPACE_ROOT}")
    return target


@tool
@log_tool_invocation
async def web_search(query: str) -> str:
    """Stub web search using DuckDuckGo-like result format."""
    results = [
        {
            "title": f"Search result for: {query}",
            "url": "https://example.com",
            "snippet": "This is a stub search result returned by the web_search tool.",
        }
    ]
    return json.dumps({"query": query, "results": results})


@tool
@log_tool_invocation
async def read_file(path: str) -> str:
    """Read a file safely within /workspace."""
    target = _resolve_workspace_path(path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return target.read_text(encoding="utf-8")


@tool
@log_tool_invocation
async def write_file(path: str, content: str) -> str:
    """Write a file safely within /workspace."""
    target = _resolve_workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return json.dumps({"path": str(target), "bytes_written": len(content.encode("utf-8"))})


@tool
@log_tool_invocation
async def run_code(code: str, language: str) -> str:
    """Execute Python code in a subprocess with a 30s timeout."""
    if language.lower() != "python":
        raise ValueError(f"Unsupported language: {language}. Only 'python' is supported.")

    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=WORKSPACE_ROOT, delete=False
    ) as temp_file:
        temp_file.write(code)
        temp_path = temp_file.name

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            temp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return json.dumps(
            {
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            },
            ensure_ascii=False,
        )
    except asyncio.TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.communicate()
        raise TimeoutError("Code execution exceeded the 30 second timeout")
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


@tool
@log_tool_invocation
async def db_query(sql: str) -> str:
    """Execute a read-only SQL query against the PostgreSQL session database."""
    sql_lower = sql.strip().lower()
    forbidden_keywords = {
        "insert",
        "update",
        "delete",
        "drop",
        "create",
        "alter",
        "truncate",
        "grant",
        "revoke",
        "merge",
        "replace",
        "execute",
        "call",
    }
    if not sql_lower.startswith("select"):
        raise ValueError("Only SELECT queries are allowed")
    if any(kw in sql_lower for kw in forbidden_keywords):
        raise ValueError(f"Forbidden keyword detected in read-only query")

    async with async_session() as session:
        result = await session.execute(text(sql))
        rows = [dict(row._mapping) for row in result.mappings()]
        return json.dumps(rows, default=str, ensure_ascii=False)


@tool
@log_tool_invocation
async def http_request(
    url: str,
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET",
    body: dict | None = None,
) -> str:
    """Make an external HTTP request."""
    body = body or {}
    async with httpx.AsyncClient(timeout=30) as client:
        method = method.upper()
        if method == "GET":
            response = await client.get(url, params=body)
        elif method == "POST":
            response = await client.post(url, json=body)
        elif method == "PUT":
            response = await client.put(url, json=body)
        elif method == "PATCH":
            response = await client.patch(url, json=body)
        elif method == "DELETE":
            response = await client.delete(url, params=body)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return json.dumps(
            {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
            },
            ensure_ascii=False,
        )
