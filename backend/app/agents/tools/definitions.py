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
    """Search the web and return structured results (rich stub data)."""
    q = query.lower()
    if any(kw in q for kw in ("llm", "framework", "langchain", "llamaindex", "dspy", "haystack")):
        results = [
            {
                "title": "Top LLM Frameworks 2024: LangChain, LlamaIndex, DSPy Compared",
                "url": "https://dev.to/top-llm-frameworks-2024",
                "snippet": (
                    "LangChain (85k GitHub stars) dominates with agents, chains, tools and memory. "
                    "LlamaIndex (30k stars) excels at RAG and document retrieval pipelines. "
                    "DSPy (15k stars) offers automatic prompt optimization and compilation. "
                    "All three released major versions in 2024 with improved async and multi-modal support."
                ),
            },
            {
                "title": "GitHub Stars & Adoption Trends: Open-source LLM Orchestration 2024",
                "url": "https://ossinsight.io/llm-frameworks-2024",
                "snippet": (
                    "Adoption in 2024: LangChain 85k stars (+60% YoY), 50M+ monthly PyPI downloads. "
                    "LlamaIndex 30k stars (+200% YoY), primary choice for enterprise RAG. "
                    "DSPy 15k stars (+400% YoY), fastest growing — used in research and production pipelines. "
                    "Recommendation: LangChain for general agents, LlamaIndex for RAG, DSPy for prompt optimization."
                ),
            },
            {
                "title": "Key Features Matrix: LangChain vs LlamaIndex vs DSPy (2024)",
                "url": "https://aicomparison.dev/llm-frameworks",
                "snippet": (
                    "LangChain: LCEL expression language, 600+ integrations, LangGraph for multi-agent workflows, LangSmith observability. "
                    "LlamaIndex: query engines, structured retrieval, multi-document agents, 160+ vector store connectors. "
                    "DSPy: declarative signatures, automatic few-shot optimization, typed predictors, ChainOfThought, ReAct modules."
                ),
            },
        ]
    elif any(kw in q for kw in ("github stars", "adoption", "trend", "popularity")):
        results = [
            {
                "title": "Open-source AI Framework Popularity Rankings 2024",
                "url": "https://star-history.com/llm-frameworks",
                "snippet": (
                    "Star history shows: LangChain peaked at 85k, consistent growth. "
                    "LlamaIndex surged from 5k to 30k in 12 months. "
                    "DSPy went from 2k to 15k, driven by academic citations and production use."
                ),
            }
        ]
    else:
        results = [
            {
                "title": f"Research findings: {query}",
                "url": "https://research.example.com/findings",
                "snippet": (
                    f"Analysis of '{query}' reveals key insights: multiple open-source frameworks "
                    "emerged in 2024 addressing LLM orchestration, RAG, and agent-based workflows. "
                    "GitHub activity, download metrics, and community size are primary adoption indicators."
                ),
            }
        ]
    return json.dumps({"query": query, "results": results, "total": len(results)})


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
        rows = [dict(row) for row in result.mappings()]
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
