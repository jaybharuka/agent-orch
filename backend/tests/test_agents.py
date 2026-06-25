"""LangGraph agent tests."""
import pytest

from app.agents.graph import agent_graph, build_agent_graph
from app.agents.schemas import AgentState, Subtask
from app.agents.specialist import specialist_node
from app.agents.supervisor import SupervisorAgent, supervisor_node
from app.agents.reviewer import reviewer_node
from app.memory.memory_manager import MemoryContext, MemoryManager


class _FakeMemoryManager:
    def __init__(self):
        self.initialized = []
        self.saved_outputs = []
        self.finalized = []

    async def get_memory_context(self, task_id, user_id, query):
        return MemoryContext(similar_tasks=[], facts=[], working_outputs={})

    async def initialize_task(self, task_id, user_id, description, plan):
        self.initialized.append((task_id, user_id, description, plan))

    async def save_specialist_output(self, task_id, subtask_id, output, tools_used):
        self.saved_outputs.append((task_id, subtask_id, output, tools_used))

    async def finalize_task(self, **kwargs):
        self.finalized.append(kwargs)


def test_build_agent_graph():
    graph = build_agent_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_supervisor_node_creates_plan_and_initializes_task():
    fake_manager = _FakeMemoryManager()

    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Research the latest AI orchestration patterns",
        "execution_plan": [],
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.0,
        "escalation_required": False,
        "retry_counts": {},
        "status": "planning",
        "memory_manager": fake_manager,
        "escalation_service": None,
    }
    result = await supervisor_node()(state)
    assert result["status"] in ("executing", "escalated")
    assert len(result["execution_plan"]) > 0
    assert result["confidence_score"] >= 0
    assert len(fake_manager.initialized) == 1
    assert fake_manager.initialized[0][0] == "task-1"


@pytest.mark.asyncio
async def test_reviewer_node_scores_complete_outputs():
    plan = [
        Subtask(id="1", description="Search", assigned_agent="research", output="found data"),
        Subtask(id="2", description="Analyze", assigned_agent="data_analysis", output="analysis done"),
    ]
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test",
        "execution_plan": plan,
        "current_subtask_index": 2,
        "memory_manager": _FakeMemoryManager(),
        "agent_outputs": {"1": "found data", "2": "analysis done"},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "retry_counts": {},
        "status": "reviewing",
        "escalation_service": None,
    }
    result = await reviewer_node(state)
    assert result["status"] == "complete"
    assert result["reviewer_score"] >= 0


@pytest.mark.asyncio
async def test_specialist_node_factory_executes_matching_subtask(monkeypatch):
    async def mock_react_loop(subtask, agent_type, state=None):
        subtask.status = "complete"
        subtask.output = f"done by {agent_type}"
        return subtask.output

    monkeypatch.setattr("app.agents.specialist._run_react_loop", mock_react_loop)

    plan = [
        Subtask(id="1", description="Search", assigned_agent="research"),
    ]
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test",
        "execution_plan": plan,
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "retry_counts": {},
        "status": "executing",
        "memory_manager": _FakeMemoryManager(),
        "escalation_service": None,
    }
    result = await specialist_node(state, agent_type="research")
    assert result["current_subtask_index"] == 1
    assert result["agent_outputs"]["1"] == "done by research"


@pytest.mark.asyncio
async def test_specialist_node_saves_output_to_memory_manager(monkeypatch):
    async def mock_react_loop(subtask, agent_type, state=None):
        subtask.status = "complete"
        subtask.output = "done by memory"
        subtask.tool_calls = [{"tool": "web_search", "output": "result"}]
        return subtask.output

    monkeypatch.setattr("app.agents.specialist._run_react_loop", mock_react_loop)

    saved = {}

    class FakeManager:
        async def save_specialist_output(self, task_id, subtask_id, output, tools_used):
            saved["task_id"] = task_id
            saved["subtask_id"] = subtask_id
            saved["output"] = output
            saved["tools_used"] = tools_used

    plan = [Subtask(id="1", description="Search", assigned_agent="research")]
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test",
        "execution_plan": plan,
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "retry_counts": {},
        "status": "executing",
        "memory_manager": FakeManager(),
        "escalation_service": None,
    }
    result = await specialist_node(state, agent_type="research")
    assert result["current_subtask_index"] == 1
    assert saved["output"] == "done by memory"
    assert "web_search" in saved["tools_used"]


@pytest.mark.asyncio
async def test_agent_graph_runs_to_completion(monkeypatch):
    async def mock_react_loop(subtask, agent_type, state=None):
        subtask.status = "complete"
        subtask.output = f"mock output for {agent_type}"
        subtask.tool_calls = [{"tool": "mock_tool", "output": "mock result"}]
        return subtask.output

    async def mock_escalate(state):
        return {"status": "escalated", "escalation_required": True}

    fake_manager = _FakeMemoryManager()

    monkeypatch.setattr("app.agents.specialist._run_react_loop", mock_react_loop)
    monkeypatch.setattr("app.agents.graph._escalate_node", mock_escalate)

    initial_state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Test the agent graph",
        "execution_plan": [],
        "current_subtask_index": 0,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.0,
        "escalation_required": False,
        "retry_counts": {},
        "status": "planning",
        "memory_manager": fake_manager,
        "escalation_service": None,
    }

    graph = build_agent_graph()
    result = await graph.ainvoke(initial_state)
    assert result["status"] in ("complete", "escalated", "failed")
    assert len(result["execution_plan"]) > 0


def test_agent_graph_export_exists():
    assert agent_graph is not None


@pytest.mark.asyncio
async def test_reviewer_finalizes_task_when_score_passes():
    plan = [
        Subtask(id="1", description="Search", assigned_agent="research", status="complete", output="research data"),
    ]
    fake_manager = _FakeMemoryManager()
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Research data",
        "execution_plan": plan,
        "current_subtask_index": 1,
        "agent_outputs": {"1": "research data"},
        "memory_context": [],
        "confidence_score": 0.85,
        "duration_ms": 1200.0,
        "cost_usd": 0.02,
        "tags": ["ai"],
        "escalation_required": False,
        "retry_counts": {},
        "status": "reviewing",
        "memory_manager": fake_manager,
        "escalation_service": None,
    }
    result = await reviewer_node(state)
    assert result["status"] == "complete"
    assert len(fake_manager.finalized) == 1
    assert fake_manager.finalized[0]["task_id"] == "task-1"
    assert fake_manager.finalized[0]["reviewer_score"] >= 0.7


@pytest.mark.asyncio
async def test_reviewer_marks_subtasks_for_retry():
    plan = [
        Subtask(id="1", description="Search", assigned_agent="research", status="complete", output="research data"),
        Subtask(id="2", description="Analyze", assigned_agent="data_analysis", status="failed", output=""),
    ]
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Research and analyze data",
        "execution_plan": plan,
        "current_subtask_index": 2,
        "agent_outputs": {"1": "research data"},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "retry_counts": {},
        "status": "reviewing",
        "memory_manager": _FakeMemoryManager(),
        "escalation_service": None,
    }
    result = await reviewer_node(state)
    assert result["status"] == "executing"
    assert result["retry_counts"].get("2") == 1
    assert plan[1].status == "pending"


@pytest.mark.asyncio
async def test_reviewer_escalates_when_score_too_low():
    plan = [
        Subtask(id="1", description="Search", assigned_agent="research", status="failed", output=""),
    ]
    state: AgentState = {
        "task_id": "task-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "original_task": "Research and analyze data",
        "execution_plan": plan,
        "current_subtask_index": 1,
        "agent_outputs": {},
        "memory_context": [],
        "confidence_score": 0.9,
        "escalation_required": False,
        "retry_counts": {"1": 2},
        "status": "reviewing",
        "memory_manager": _FakeMemoryManager(),
        "escalation_service": None,
    }
    result = await reviewer_node(state)
    assert result["status"] == "escalated"
    assert result["escalation_required"] is True
