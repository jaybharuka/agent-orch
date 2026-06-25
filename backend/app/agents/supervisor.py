"""Supervisor agent implementation."""
import json
from pathlib import Path

import anthropic
import openai

from app.agents.prompts.supervisor import SUPERVISOR_SYSTEM_PROMPT
from app.agents.publisher import publish_status
from app.agents.schemas import AgentState, Subtask
from app.config import settings
from app.memory.memory_manager import MemoryManager


AGENT_CATALOG = """
- research: web searches and reading files to gather information
- data_analysis: SQL queries and Python code execution to analyze data
- writing: producing written outputs and saving files
- code: writing, reading, and executing Python code
""".strip()

TOOLS_CATALOG = """
- research: web_search (query the web), read_file (read from /workspace)
- data_analysis: db_query (read-only SQL on PostgreSQL), run_code (execute Python in /workspace)
- writing: write_file (write to /workspace)
- code: run_code (execute Python), read_file (read from /workspace), write_file (write to /workspace)
""".strip()


class SupervisorAgent:
    """Routes tasks to specialist agents and manages workflow state."""

    def __init__(self, memory_manager: MemoryManager | None = None) -> None:
        self.system_prompt = SUPERVISOR_SYSTEM_PROMPT
        self.plan_template_path = Path(__file__).parent / "prompts" / "supervisor_plan.txt"
        self.memory_manager = memory_manager or MemoryManager()

    def build_planning_prompt(self, task: str, memory_context: list[str]) -> str:
        """Build the planning prompt from the template file."""
        template = self.plan_template_path.read_text(encoding="utf-8")
        memory_text = (
            "\n".join(f"- {m}" for m in memory_context)
            if memory_context
            else "No relevant memories found."
        )
        return template.format(
            task=task,
            agents=AGENT_CATALOG,
            tools=TOOLS_CATALOG,
            memory_context=memory_text,
        )

    def _memory_context_to_lines(self, context) -> list[str]:
        """Convert a MemoryContext into prompt-ready lines."""
        lines: list[str] = []
        if context.similar_tasks:
            lines.append("Similar past tasks:")
            for entry in context.similar_tasks:
                lines.append(f"- {entry.task_description}: {entry.summary}")
        if context.facts:
            lines.append("Relevant facts:")
            for fact in context.facts:
                lines.append(f"- {fact}")
        if context.working_outputs:
            lines.append("Current working outputs:")
            for subtask_id, output in context.working_outputs.items():
                lines.append(f"- {subtask_id}: {output}")
        return lines

    async def generate_plan(
        self, task: str, task_id: str, user_id: str
    ) -> list[Subtask]:
        """Call Claude to generate a validated execution plan using memory context."""
        context = await self.memory_manager.get_memory_context(task_id, user_id, task)
        memory_context = self._memory_context_to_lines(context)
        prompt = self.build_planning_prompt(task, memory_context)

        if settings.nvidia_api_key:
            return await self._generate_via_nvidia(prompt)

        if settings.anthropic_api_key:
            return await self._generate_via_anthropic(prompt)

        return self._fallback_plan(task)

    async def _generate_via_nvidia(self, prompt: str) -> list["Subtask"]:
        """Call NVIDIA NIM (OpenAI-compatible) to generate the plan."""
        try:
            client = openai.AsyncOpenAI(
                api_key=settings.nvidia_api_key,
                base_url=settings.nvidia_base_url,
            )
            response = await client.chat.completions.create(
                model=settings.nvidia_model,
                max_tokens=2000,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or ""
            return self._parse_plan(content)
        except openai.AuthenticationError:
            raise RuntimeError(
                "NVIDIA NIM authentication failed — check NVIDIA_API_KEY in .env"
            )
        except openai.APIError as exc:
            raise RuntimeError(f"NVIDIA NIM API error: {exc}") from exc

    async def _generate_via_anthropic(self, prompt: str) -> list["Subtask"]:
        """Call Anthropic Claude to generate the plan."""
        try:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            return self._parse_plan(content)
        except anthropic.AuthenticationError:
            raise RuntimeError(
                "Anthropic authentication failed — check ANTHROPIC_API_KEY in .env"
            )
        except anthropic.APIError as exc:
            raise RuntimeError(f"Anthropic API error: {exc}") from exc

    def _parse_plan(self, raw: str) -> list[Subtask]:
        """Parse Claude's JSON output into Subtask objects."""
        try:
            # Handle possible markdown code fences.
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("\n", 1)[0]
                cleaned = cleaned.replace("```json", "").replace("```", "").strip()
            data = json.loads(cleaned)
            items = data.get("subtasks", data if isinstance(data, list) else [])
            return [Subtask(
                id=str(item.get("id")),
                description=item.get("description", ""),
                assigned_agent=item.get("agent", "research"),
                dependencies=item.get("dependencies", []),
                expected_output=item.get("expected_output"),
            ) for item in items]
        except Exception as exc:
            return self._fallback_plan(str(exc))

    def _fallback_plan(self, task: str | None = None) -> list[Subtask]:
        """Return a deterministic fallback plan when Claude is unavailable."""
        task = task or "the task"
        return [
            Subtask(
                id="1",
                description=f"Gather relevant context and references for: {task}",
                assigned_agent="research",
                dependencies=[],
                expected_output="Collected context and source references",
            ),
            Subtask(
                id="2",
                description=f"Analyze the gathered information for: {task}",
                assigned_agent="data_analysis",
                dependencies=["1"],
                expected_output="Insights and analysis results",
            ),
            Subtask(
                id="3",
                description=f"Produce the final written output for: {task}",
                assigned_agent="writing",
                dependencies=["2"],
                expected_output="Final deliverable text",
            ),
        ]

    def validate_dependencies(self, subtasks: list[Subtask]) -> tuple[bool, str | None]:
        """Check that every dependency references an existing subtask id."""
        ids = {s.id for s in subtasks}
        for subtask in subtasks:
            for dep in subtask.dependencies:
                if dep not in ids:
                    return False, f"Dependency '{dep}' of subtask '{subtask.id}' does not exist"
        return True, None

    def compute_confidence(self, task: str, subtasks: list[Subtask]) -> float:
        """Score the plan based on dependency validity and task coverage."""
        if not subtasks:
            return 0.0

        valid, _ = self.validate_dependencies(subtasks)
        if not valid:
            return 0.3

        # Simple keyword coverage: what fraction of meaningful task words appear in descriptions.
        stop_words = {
            "the", "a", "an", "to", "and", "or", "of", "for", "in", "on", "with",
            "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could", "should", "may", "might",
            "what", "how", "when", "where", "why", "who", "which", "this", "that",
        }
        task_words = {w for w in task.lower().split() if len(w) > 2 and w not in stop_words}
        descriptions = " ".join(s.description.lower() for s in subtasks)
        if not task_words:
            coverage = 1.0
        else:
            coverage = sum(1 for w in task_words if w in descriptions) / len(task_words)

        # Score is 0.5 base + 0.5 for coverage, capped at 1.0.
        return min(1.0, round(0.5 + 0.5 * coverage, 2))


def supervisor_node():
    """Factory that returns the LangGraph supervisor node.

    The MemoryManager is read from the non-serialized AgentState field so it can be
    injected via FastAPI dependency at graph invocation time.
    """
    async def _node(state: AgentState) -> AgentState:
        """LangGraph node that creates the execution plan."""
        memory_manager = state.get("memory_manager")
        if memory_manager is None:
            raise RuntimeError("AgentState is missing memory_manager")

        agent = SupervisorAgent(memory_manager)
        task = state["original_task"]
        task_id = state["task_id"]
        user_id = state["user_id"]

        subtasks = await agent.generate_plan(task, task_id, user_id)
        confidence_score = agent.compute_confidence(task, subtasks)

        await memory_manager.initialize_task(task_id, user_id, task, subtasks)

        escalation_required = confidence_score < 0.6
        escalation_reason: str | None = None
        escalation_trigger: str | None = None
        if escalation_required:
            escalation_reason = "low_confidence"
            escalation_trigger = "low_confidence"

        status = "escalated" if escalation_required else "executing"
        await publish_status(user_id, task_id, status)
        return {
            "execution_plan": subtasks,
            "confidence_score": confidence_score,
            "escalation_required": escalation_required,
            "escalation_reason": escalation_reason,
            "escalation_trigger": escalation_trigger,
            "status": status,
            "current_subtask_index": 0,
        }

    return _node
