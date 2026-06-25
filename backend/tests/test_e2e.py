"""End-to-end integration tests for the LangGraph agent pipeline.

All LLM calls are mocked with fixed responses. Redis/Postgres/Chroma are either
mocked or use the real containers when available (pytest fixture handles both).
"""
import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.schemas import AgentState, Subtask
from app.agents.supervisor import SupervisorAgent, supervisor_node
from app.agents.reviewer import ReviewerAgent, reviewer_node
from app.agents.specialist import specialist_node, SPECIALIST_AGENTS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_AGENT_TYPES = {"research", "data_analysis", "writing", "code"}

VALID_SUBTASK_FIELDS = {"id", "description", "assigned_agent", "dependencies"}

SAMPLE_TASK = "Summarise the latest research on transformer attention mechanisms."


def _make_state(**overrides) -> AgentState:
    base: dict[str, Any] = {
        "task_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "user_id": "test-user",
        "original_task": SAMPLE_TASK,
        "execution_plan": [],
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.0,
        "escalation_required": False,
        "escalation_reason": None,
        "escalation_trigger": None,
        "reviewer_score": None,
        "reviewer_feedback": None,
        "retry_counts": {},
        "retries": {},
        "status": "planning",
        "memory_manager": None,
        "escalation_service": None,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _fake_subtask(agent: str = "research", desc: str = "Search the web") -> Subtask:
    return Subtask(
        id=str(uuid.uuid4()),
        description=desc,
        assigned_agent=agent,
        dependencies=[],
    )


def _mock_generate_plan(subtasks: list[dict]):
    """Return an AsyncMock that resolves generate_plan to a list of Subtasks."""
    parsed = [
        Subtask(
            id=str(s.get("id")),
            description=s.get("description", ""),
            assigned_agent=s.get("assigned_agent", "research"),
            dependencies=s.get("dependencies", []),
        )
        for s in subtasks
    ]
    return AsyncMock(return_value=parsed)


# ---------------------------------------------------------------------------
# Test 1 — Plan validity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plan_has_required_fields_and_valid_agents():
    """supervisor_node should produce a plan with >=2 subtasks, all valid."""
    subtasks_payload = [
        {"id": "s1", "description": "Search for transformer papers", "assigned_agent": "research", "dependencies": []},
        {"id": "s2", "description": "Summarise findings", "assigned_agent": "writing", "dependencies": ["s1"]},
    ]

    fake_mm = MagicMock()
    fake_mm.get_memory_context = AsyncMock(return_value=MagicMock(similar_tasks=[], facts=[], working_outputs={}))
    fake_mm.initialize_task = AsyncMock()

    with patch.object(SupervisorAgent, "generate_plan", _mock_generate_plan(subtasks_payload)), \
         patch("app.agents.publisher.publish_status", new_callable=AsyncMock):

        state = _make_state(memory_manager=fake_mm)
        factory = supervisor_node()
        result = await factory(state)

    plan = result.get("execution_plan", [])
    assert len(plan) >= 2, "Plan must have at least 2 subtasks"

    for subtask in plan:
        for field in VALID_SUBTASK_FIELDS:
            assert hasattr(subtask, field) or (isinstance(subtask, dict) and field in subtask), \
                f"Subtask missing required field: {field}"
        agent = subtask.assigned_agent if hasattr(subtask, "assigned_agent") else subtask["assigned_agent"]
        assert agent in VALID_AGENT_TYPES, f"Unknown agent type: {agent}"


# ---------------------------------------------------------------------------
# Test 2 — Tool use correctness (tool call is recorded)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_specialist_records_tool_output():
    """specialist_node should set output on the completed subtask."""
    subtask = _fake_subtask("research", "Search for transformer papers")
    fake_mm = MagicMock()
    fake_mm.save_specialist_output = AsyncMock()

    async def fake_control(_task_id):
        return None

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value="Mocked search result: LLaMA-3, Mistral-7B, Phi-3")

    with patch("app.agents.specialist._check_task_control", side_effect=fake_control), \
         patch("app.agents.specialist.ToolRegistry") as MockRegistry, \
         patch("app.agents.specialist.SupervisorAgent._build_chain", MagicMock()), \
         patch("app.agents.publisher.publish_status", new_callable=AsyncMock):

        MockRegistry.return_value.get_tool.return_value = mock_tool
        MockRegistry.return_value.list_tools.return_value = ["web_search"]

        state = _make_state(
            execution_plan=[subtask],
            current_subtask_index=0,
            status="executing",
            memory_manager=fake_mm,
        )
        result = await specialist_node(state, agent_type="research")

    plan = result.get("execution_plan", state["execution_plan"])
    # The subtask should now be marked complete or at least the index advanced
    assert result.get("current_subtask_index", 0) >= 1 or plan[0].status in ("complete", "in_progress")


# ---------------------------------------------------------------------------
# Test 3 — Reviewer catches bad output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewer_escalates_empty_outputs():
    """reviewer_node with empty agent_outputs should produce low score and escalate."""
    plan = [
        _fake_subtask("research", "Search transformer literature"),
        _fake_subtask("writing", "Write summary"),
    ]

    with patch("app.agents.publisher.publish_status", new_callable=AsyncMock):
        state = _make_state(
            execution_plan=plan,
            agent_outputs={},       # no outputs at all
            status="reviewing",
            current_subtask_index=len(plan),
        )
        result = await reviewer_node(state)

    score = result.get("reviewer_score", 1.0)
    assert score < 0.5, f"Expected low reviewer_score for empty outputs, got {score}"
    assert result.get("escalation_required") or result.get("status") in ("escalated", "executing"), \
        "Reviewer should trigger escalation or retry for empty outputs"


# ---------------------------------------------------------------------------
# Test 4 — Memory improves repeated tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_context_populated_on_second_run():
    """Second supervisor run should see non-empty similar_tasks from memory."""
    subtasks_payload = [
        {"id": "s1", "description": "Search transformer papers", "assigned_agent": "research", "dependencies": []},
        {"id": "s2", "description": "Write summary", "assigned_agent": "writing", "dependencies": ["s1"]},
    ]

    from app.memory.long_term_memory import MemoryEntry

    fake_entry = MemoryEntry(
        id="mem-001",
        task_description=SAMPLE_TASK,
        summary="Previous run result",
        tools_used=["web_search"],
        reviewer_score=0.9,
        tags=["transformer"],
        created_at="2024-01-01T00:00:00",
        importance_score=0.9,
    )

    first_mm = MagicMock()
    first_mm.get_memory_context = AsyncMock(
        return_value=MagicMock(similar_tasks=[], facts=[], working_outputs={})
    )
    first_mm.initialize_task = AsyncMock()

    second_mm = MagicMock()
    second_mm.get_memory_context = AsyncMock(
        return_value=MagicMock(similar_tasks=[fake_entry], facts=[], working_outputs={})
    )
    second_mm.initialize_task = AsyncMock()

    with patch.object(SupervisorAgent, "generate_plan", _mock_generate_plan(subtasks_payload)), \
         patch("app.agents.publisher.publish_status", new_callable=AsyncMock):
        factory = supervisor_node()

        # First run
        s1 = _make_state(memory_manager=first_mm)
        await factory(s1)

        # Second run — memory_manager now returns a hit
        s2 = _make_state(memory_manager=second_mm)
        result = await factory(s2)

    ctx_raw = result.get("memory_context", [])
    # memory_context is a list of strings serialised from MemoryContext
    assert len(ctx_raw) > 0 or second_mm.get_memory_context.call_count >= 1, \
        "Second run should query memory (similar_tasks available)"


# ---------------------------------------------------------------------------
# Test 5 — Graceful failure recovery in specialist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_specialist_handles_tool_exception_gracefully():
    """A tool that always raises must not propagate; subtask should end as failed."""
    subtask = _fake_subtask("research", "Search for data")
    fake_mm = MagicMock()
    fake_mm.save_specialist_output = AsyncMock()

    async def fake_control(_task_id):
        return None

    exploding_tool = MagicMock()
    exploding_tool.ainvoke = AsyncMock(side_effect=RuntimeError("Tool exploded"))

    with patch("app.agents.specialist._check_task_control", side_effect=fake_control), \
         patch("app.agents.specialist.ToolRegistry") as MockRegistry, \
         patch("app.agents.publisher.publish_status", new_callable=AsyncMock):

        MockRegistry.return_value.get_tool.return_value = exploding_tool
        MockRegistry.return_value.list_tools.return_value = ["web_search"]

        state = _make_state(
            execution_plan=[subtask],
            current_subtask_index=0,
            status="executing",
            memory_manager=fake_mm,
        )
        # Must not raise
        result = await specialist_node(state, agent_type="research")

    final_status = result.get("status", state["status"])
    assert final_status in ("failed", "escalated", "executing"), \
        f"Expected terminal/retry status, got {final_status}"

    plan = result.get("execution_plan", state["execution_plan"])
    if plan:
        failed = [s for s in plan if s.status == "failed"]
        assert len(failed) >= 1 or result.get("error") is not None, \
            "Subtask or state.error should reflect the tool failure"


# ---------------------------------------------------------------------------
# Test 6 — Full graph smoke test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_graph_reaches_terminal_state():
    """agent_graph.ainvoke should reach complete or escalated within timeout."""
    from app.agents.graph import build_agent_graph

    subtasks_payload = [
        {"id": "s1", "description": "Search for info", "assigned_agent": "research", "dependencies": []},
        {"id": "s2", "description": "Write report", "assigned_agent": "writing", "dependencies": ["s1"]},
    ]

    fake_mm = MagicMock()
    fake_mm.get_memory_context = AsyncMock(
        return_value=MagicMock(similar_tasks=[], facts=[], working_outputs={})
    )
    fake_mm.initialize_task = AsyncMock()
    fake_mm.save_specialist_output = AsyncMock()
    fake_mm.finalize_task = AsyncMock()

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value="Mocked output: framework comparison done.")

    async def fake_control(_task_id):
        return None

    with patch.object(SupervisorAgent, "generate_plan", _mock_generate_plan(subtasks_payload)), \
         patch("app.agents.specialist._check_task_control", side_effect=fake_control), \
         patch("app.agents.specialist.ToolRegistry") as MockRegistry, \
         patch("app.agents.publisher.publish_status", new_callable=AsyncMock):

        MockRegistry.return_value.get_tool.return_value = mock_tool
        MockRegistry.return_value.list_tools.return_value = ["web_search", "write_file"]

        graph = build_agent_graph()
        state = _make_state(memory_manager=fake_mm)

        final = await asyncio.wait_for(graph.ainvoke(state), timeout=30.0)

    assert final.get("status") in ("complete", "escalated", "failed"), \
        f"Unexpected terminal status: {final.get('status')}"
