"""Specialist agent implementation with ReAct loop and factory."""
import asyncio
import json

import redis.asyncio as redis

from app.agents.prompts.specialist import SPECIALIST_SYSTEM_PROMPT
from app.agents.publisher import publish_status
from app.agents.schemas import AgentState, Subtask
from app.agents.tools.registry import ToolRegistry
from app.config import settings
from app.memory.memory_manager import MemoryManager


class EscalationRequired(Exception):
    """Raised when a specialist must pause for human approval."""

    def __init__(self, trigger: str, reason: str) -> None:
        self.trigger = trigger
        self.reason = reason
        super().__init__(reason)


AGENT_ALLOWED_TOOLS = {
    "research": ["web_search", "http_request"],
    "data_analysis": ["db_query", "run_code"],
    "writing": ["read_file", "write_file"],
    "code": ["run_code", "read_file", "write_file"],
}

SPECIALIST_AGENTS = set(AGENT_ALLOWED_TOOLS.keys())


def _is_sensitive_tool_call(tool_name: str, tool_inputs: dict) -> bool:
    """Return True when a tool call requires human approval before running."""
    if tool_name == "http_request":
        method = str(tool_inputs.get("method", "GET")).upper()
        if method in ("POST", "PUT", "DELETE"):
            return True
    return False


async def _check_task_control(task_id: str, timeout: float = 0.1) -> dict | None:
    """Non-blocking check for a user-requested escalation on this task."""
    client = redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = client.pubsub()
    channel = f"task_control:{task_id}"
    await pubsub.subscribe(channel)
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            message = await pubsub.get_message(timeout=0.05)
            if message and message["type"] == "message":
                return json.loads(message["data"])
        return None
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await client.close()


def _select_tool(subtask: Subtask, allowed_tools: list[str]) -> str | None:
    """Pick the best allowed tool based on simple keyword matching."""
    description = subtask.description.lower()

    for tool in allowed_tools:
        if tool == "web_search" and any(kw in description for kw in ("search", "lookup", "find")):
            return tool
        if tool == "http_request" and any(kw in description for kw in ("http", "api", "request", "fetch")):
            return tool
        if tool == "db_query" and any(kw in description for kw in ("query", "database", "sql", "db")):
            return tool
        if tool == "run_code" and any(kw in description for kw in ("code", "run", "execute", "python", "compute")):
            return tool
        if tool == "read_file" and any(kw in description for kw in ("read", "load", "open")):
            return tool
        if tool == "write_file" and any(kw in description for kw in ("write", "save", "create file", "output")):
            return tool

    # Prefer write_file over read_file as the default for writing/code agents.
    if "write_file" in allowed_tools:
        return "write_file"
    return allowed_tools[0] if allowed_tools else None


def _build_tool_inputs(tool_name: str, subtask: Subtask) -> dict:
    """Build reasonable default inputs for each tool."""
    if tool_name == "web_search":
        return {"query": subtask.description}
    if tool_name == "http_request":
        return {"url": "https://httpbin.org/get", "method": "GET", "body": {}}
    if tool_name == "db_query":
        return {"sql": "SELECT now()"}
    if tool_name == "run_code":
        return {"code": "print('Hello from specialist')", "language": "python"}
    if tool_name == "read_file":
        return {"path": "data.txt"}
    if tool_name == "write_file":
        safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in subtask.description[:50]).strip("_")
        return {
            "path": f"{safe_name}.md",
            "content": f"# {subtask.description}\n\n{subtask.description}\n\nThis section covers the required analysis and findings.",
        }
    return {}


def _is_done(iteration: int, result: str) -> bool:
    """Determine if the ReAct loop should terminate early."""
    if iteration >= 4:
        return True
    if result and not result.startswith("Error:"):
        return True
    return False


async def _run_react_loop(
    subtask: Subtask, agent_type: str, state: AgentState | None = None
) -> str:
    """Run a ReAct loop (max 5 iterations) for the given subtask."""
    allowed_tools = AGENT_ALLOWED_TOOLS.get(agent_type, [])
    registry = ToolRegistry()
    observations: list[str] = []
    subtask.status = "in_progress"

    for iteration in range(5):
        thought = f"Iteration {iteration + 1}: selecting the best tool for subtask '{subtask.description}'."
        tool_name = _select_tool(subtask, allowed_tools)

        if tool_name is None:
            observations.append(f"Iteration {iteration + 1}: no allowed tool available.")
            break

        tool = registry.get_tool(tool_name)
        if tool is None:
            observations.append(f"Iteration {iteration + 1}: tool '{tool_name}' not found in registry.")
            break

        tool_inputs = _build_tool_inputs(tool_name, subtask)

        if state is not None:
            control = await _check_task_control(state["task_id"])
            if control and control.get("escalation_required"):
                trigger = str(control.get("trigger", "user_requested"))
                raise EscalationRequired(trigger, f"User-requested escalation: {control.get('reason', '')}")
            if _is_sensitive_tool_call(tool_name, tool_inputs):
                raise EscalationRequired(
                    "sensitive_operation",
                    f"Sensitive tool call '{tool_name}' requires human approval",
                )

        try:
            result = await tool.ainvoke(tool_inputs)
        except Exception as exc:
            result = f"Error: {exc}"

        # If read_file fails and write_file is available, switch to write_file.
        if tool_name == "read_file" and str(result).startswith("Error:") and "write_file" in allowed_tools:
            tool_name = "write_file"
            tool_inputs = _build_tool_inputs("write_file", subtask)
            if state is not None and _is_sensitive_tool_call(tool_name, tool_inputs):
                raise EscalationRequired("sensitive_operation", f"Sensitive tool call '{tool_name}' requires human approval")
            try:
                result = await (registry.get_tool("write_file")).ainvoke(tool_inputs)
            except Exception as exc2:
                result = f"Error: {exc2}"

        subtask.tool_calls.append({
            "iteration": iteration + 1,
            "thought": thought,
            "tool": tool_name,
            "inputs": tool_inputs,
            "output": result,
        })
        observations.append(f"Iteration {iteration + 1}: used {tool_name}, result: {result}")

        if _is_done(iteration, result):
            break

    has_success = any(
        not str(call.get("output", "")).startswith("Error:")
        for call in subtask.tool_calls
    )
    subtask.status = "complete" if has_success else "failed"
    subtask.output = "\n".join(observations)
    return subtask.output


async def specialist_node(state: AgentState, agent_type: str) -> AgentState:
    """Factory-style LangGraph node for a specialist agent type.

    Use with functools.partial(specialist_node, agent_type="research") when
    registering nodes in the graph.
    """
    plan = list(state["execution_plan"])
    index = state["current_subtask_index"]
    outputs = dict(state["agent_outputs"])
    memory_manager = state.get("memory_manager")
    retries = dict(state.get("retries", {}))

    escalation_required = False
    escalation_reason: str | None = None
    escalation_trigger: str | None = None

    if index < len(plan) and plan[index].assigned_agent == agent_type:
        subtask = plan[index]

        if retries.get(subtask.id, 0) >= 2:
            subtask.status = "failed"
            escalation_required = True
            escalation_reason = "repeated_failure"
            escalation_trigger = "repeated_failure"
            index += 1  # must advance so _route_execution doesn't loop on the same subtask
        else:
            try:
                output = await _run_react_loop(subtask, agent_type, state)
            except EscalationRequired as exc:
                subtask.status = "failed"
                subtask.error = exc.reason
                output = exc.reason
                escalation_required = True
                escalation_reason = exc.trigger
                escalation_trigger = exc.trigger

            outputs[subtask.id] = output
            if subtask.status == "failed" and not escalation_required:
                retries[subtask.id] = retries.get(subtask.id, 0) + 1
                if retries[subtask.id] >= 2:
                    escalation_required = True
                    escalation_reason = "repeated_failure"
                    escalation_trigger = "repeated_failure"
            index += 1

            if memory_manager is not None and not escalation_required:
                tools_used = [
                    call.get("tool")
                    for call in subtask.tool_calls
                    if call.get("tool")
                ]
                await memory_manager.save_specialist_output(
                    task_id=state["task_id"],
                    subtask_id=subtask.id,
                    output=output,
                    tools_used=tools_used,
                )

    status = "escalated" if escalation_required else ("reviewing" if index >= len(plan) else "executing")
    await publish_status(state["user_id"], state["task_id"], status)
    result: AgentState = {
        "execution_plan": plan,
        "current_subtask_index": index,
        "agent_outputs": outputs,
        "status": status,
        "retries": retries,
    }
    if escalation_required:
        result["escalation_required"] = True
        result["escalation_reason"] = escalation_reason
        result["escalation_trigger"] = escalation_trigger
    return result


class SpecialistAgent:
    """Legacy wrapper kept for compatibility with existing imports."""

    def __init__(self) -> None:
        self.system_prompt = SPECIALIST_SYSTEM_PROMPT
        self.registry = ToolRegistry()

    async def execute_subtask(self, subtask: Subtask) -> str:
        """Execute a subtask using the ReAct loop."""
        return await _run_react_loop(subtask, subtask.assigned_agent)
