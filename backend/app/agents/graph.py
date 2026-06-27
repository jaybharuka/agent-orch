"""LangGraph workflow definition."""
import asyncio
import json
import uuid

from langgraph.graph import StateGraph, END

from app.agents.publisher import publish_status
from app.agents.schemas import AgentState, Subtask
from app.agents.specialist import SPECIALIST_AGENTS, specialist_node
from app.agents.supervisor import supervisor_node
from app.agents.reviewer import reviewer_node
from app.services.escalation_service import EscalationService


def _make_specialist_node(agent_type: str):
    """Return an async LangGraph node for the given specialist agent type."""
    async def _node(state: AgentState) -> AgentState:
        return await specialist_node(state, agent_type=agent_type)
    return _node


def _route_supervisor(state: AgentState) -> str:
    if state.get("escalation_required"):
        return "escalate"
    return "execute"


def _route_execution(state: AgentState) -> str:
    """Route to the next specialist node based on the current subtask."""
    if state.get("escalation_required"):
        return "escalate"
    plan = state["execution_plan"]
    index = state["current_subtask_index"]
    if index >= len(plan):
        return "review"
    agent = plan[index].assigned_agent
    if agent in SPECIALIST_AGENTS:
        return agent
    return "review"


def _route_reviewer(state: AgentState) -> str:
    if state["status"] == "escalated":
        return "escalate"
    if state["status"] == "executing":
        return "revise"
    return "complete"


def _route_escalate(state: AgentState) -> str:
    """After escalation: resume execution on approve, end on reject/timeout."""
    if state.get("status") == "executing" and not state.get("escalation_required"):
        return "execute"
    return "end"


def _execute_passthrough(state: AgentState) -> AgentState:
    """Passthrough node used as the execution router entry point."""
    return {"status": state["status"]}


def _derive_escalation_trigger(state: AgentState) -> str:
    """Map the escalation reason to an approval trigger."""
    if state.get("escalation_trigger"):
        return state["escalation_trigger"]
    reason = (
        state.get("reviewer_feedback") or state.get("escalation_reason") or ""
    ).lower()
    if "confidence" in reason:
        return "low_confidence"
    if "reviewer" in reason or "retry" in reason:
        return "low_reviewer_score"
    if "sensitive" in reason:
        return "sensitive_operation"
    if "user" in reason:
        return "user_requested"
    return "sensitive_operation"


_TRIGGER_PROPOSED_ACTIONS: dict[str, str] = {
    "low_confidence": "proceed with low-confidence plan",
    "repeated_failure": "retry failed subtask after repeated failures",
    "sensitive_operation": "execute sensitive tool call",
    "low_reviewer_score": "proceed with low reviewer score",
    "user_requested": "user requested takeover",
}


async def _wait_for_resolution(
    escalation_service: EscalationService, request_id: str, timeout: float = 3600
) -> dict | None:
    """Block on the Redis pub/sub channel until the request is resolved."""
    redis_client = await escalation_service._get_redis()
    channel = f"approval_resolved:{request_id}"
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async with asyncio.timeout(timeout):
            async for message in pubsub.listen():
                if message["type"] == "message":
                    return json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


async def _escalate_node(state: AgentState) -> AgentState:
    """Pause execution, create an approval request, and await human resolution."""
    escalation_service = state.get("escalation_service")
    if escalation_service is None:
        await publish_status(state["user_id"], state["task_id"], "escalated")
        return {
            "status": "escalated",
            "escalation_required": True,
            "error": "Escalation service not available",
        }

    trigger = _derive_escalation_trigger(state)
    proposed_action = _TRIGGER_PROPOSED_ACTIONS.get(
        trigger, "Wait for human review before proceeding"
    )
    agent_reasoning = (
        state.get("reviewer_feedback")
        or state.get("escalation_reason")
        or "Escalated by orchestrator"
    )

    try:
        request = await escalation_service.escalate(
            state=state,
            trigger=trigger,
            proposed_action=proposed_action,
            agent_reasoning=agent_reasoning,
        )
        message = await _wait_for_resolution(escalation_service, str(request.id))
    except asyncio.TimeoutError:
        await publish_status(state["user_id"], state["task_id"], "escalated")
        return {
            "status": "escalated",
            "escalation_required": True,
            "error": "Approval resolution timed out",
        }
    except Exception as exc:
        await publish_status(state["user_id"], state["task_id"], "escalated")
        return {
            "status": "escalated",
            "escalation_required": True,
            "error": f"Escalation failed: {exc}",
        }

    if message is None:
        await publish_status(state["user_id"], state["task_id"], "escalated")
        return {
            "status": "escalated",
            "escalation_required": True,
            "error": "No approval resolution received",
        }

    decision = message.get("decision")

    if decision == "approve":
        resolved = await escalation_service.get_by_id(request.id)
        if resolved and resolved.modified_plan:
            new_plan = [
                Subtask(**subtask) for subtask in resolved.modified_plan
            ]
            await publish_status(state["user_id"], state["task_id"], "executing")
            return {
                "status": "executing",
                "escalation_required": False,
                "execution_plan": new_plan,
                "current_subtask_index": 0,
                "agent_outputs": {},
                "retry_counts": {},
            }
        # Advance past the current subtask so it doesn't re-trigger escalation.
        plan = list(state.get("execution_plan", []))
        idx = state.get("current_subtask_index", 0)
        agent_outputs = dict(state.get("agent_outputs", {}))
        if idx < len(plan):
            subtask = plan[idx]
            subtask.status = "complete"
            subtask.output = f"[Human-approved] {subtask.description}"
            agent_outputs[subtask.id] = subtask.output
            idx += 1
        await publish_status(state["user_id"], state["task_id"], "executing")
        return {
            "status": "executing",
            "escalation_required": False,
            "execution_plan": plan,
            "current_subtask_index": idx,
            "agent_outputs": agent_outputs,
        }

    if decision == "reject":
        resolved = await escalation_service.get_by_id(request.id)
        await publish_status(state["user_id"], state["task_id"], "failed")
        return {
            "status": "failed",
            "escalation_required": False,
            "error": resolved.reviewer_notes if resolved else "Rejected by reviewer",
        }

    # take_over or any other decision
    await publish_status(state["user_id"], state["task_id"], "escalated")
    return {
        "status": "escalated",
        "escalation_required": True,
        "escalation_reason": agent_reasoning,
    }


def build_agent_graph():
    """Construct Supervisor → Specialist agents → Reviewer → Escalate graph."""
    builder = StateGraph(AgentState)

    # Specialist nodes instantiated from the factory.
    builder.add_node("supervisor", supervisor_node())
    builder.add_node("execute", _execute_passthrough)
    for agent_type in SPECIALIST_AGENTS:
        builder.add_node(agent_type, _make_specialist_node(agent_type))
    builder.add_node("reviewer", reviewer_node)
    builder.add_node("escalate", _escalate_node)

    builder.set_entry_point("supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {"execute": "execute", "escalate": "escalate"},
    )
    _execution_routes = {
        "research": "research",
        "data_analysis": "data_analysis",
        "writing": "writing",
        "code": "code",
        "review": "reviewer",
        "escalate": "escalate",
    }
    builder.add_conditional_edges("execute", _route_execution, _execution_routes)

    # After each specialist node, route back to the execution router.
    for agent_type in SPECIALIST_AGENTS:
        builder.add_conditional_edges(agent_type, _route_execution, _execution_routes)

    builder.add_conditional_edges(
        "reviewer",
        _route_reviewer,
        {"complete": END, "revise": "execute", "escalate": "escalate"},
    )
    builder.add_conditional_edges(
        "escalate",
        _route_escalate,
        {"execute": "execute", "end": END},
    )

    return builder.compile()


agent_graph = build_agent_graph()
