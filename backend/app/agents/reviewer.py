"""Reviewer agent implementation."""
from app.agents.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.agents.publisher import publish_status
from app.agents.schemas import AgentState, Subtask
from app.memory.memory_manager import MemoryManager


SPECIALIST_AGENTS = {"research", "data_analysis", "writing", "code"}

STOP_WORDS = {
    "the", "a", "an", "to", "and", "or", "of", "for", "in", "on", "with",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "what", "how", "when", "where", "why", "who", "which", "this", "that",
}


class ReviewerAgent:
    """Evaluates specialist output and triggers human review if needed."""

    MAX_RETRIES = 2

    def __init__(self) -> None:
        self.system_prompt = REVIEWER_SYSTEM_PROMPT

    def _extract_keywords(self, text: str) -> set[str]:
        return {w for w in text.lower().split() if len(w) > 2 and w not in STOP_WORDS}

    def _coverage_score(self, task: str, outputs: list[str]) -> float:
        keywords = self._extract_keywords(task)
        if not keywords:
            return 1.0
        combined = " ".join(o.lower() for o in outputs)
        matched = sum(1 for kw in keywords if kw in combined)
        return matched / len(keywords)

    async def review(self, state: AgentState) -> dict:
        """Evaluate outputs, produce score/feedback, and decide retry/escalate/complete."""
        original_task = state["original_task"]
        agent_outputs = state["agent_outputs"]
        plan = list(state["execution_plan"])
        retry_counts = dict(state.get("retry_counts", {}))

        specialist_subtasks = [
            subtask for subtask in plan if subtask.assigned_agent in SPECIALIST_AGENTS
        ]

        if not specialist_subtasks:
            return {
                "reviewer_score": 0.0,
                "reviewer_feedback": "No specialist subtasks were found to review.",
                "final_output": None,
                "status": "escalated",
                "escalation_required": True,
                "escalation_reason": "No specialist subtasks in plan.",
            }

        total = len(specialist_subtasks)
        complete = sum(
            1 for s in specialist_subtasks if s.status == "complete" and s.output
        )
        completion_score = complete / total

        outputs = [str(agent_outputs.get(s.id, "")) for s in specialist_subtasks]
        coverage_score = self._coverage_score(original_task, outputs)

        score = round(0.7 * completion_score + 0.3 * coverage_score, 2)

        feedback = self._build_feedback(score, specialist_subtasks, agent_outputs)

        if score < 0.4:
            return {
                "reviewer_score": score,
                "reviewer_feedback": feedback,
                "final_output": None,
                "status": "escalated",
                "escalation_required": True,
                "escalation_reason": "low_reviewer_score",
                "escalation_trigger": "low_reviewer_score",
            }

        if score < 0.7:
            retry_subtasks = self._find_retry_candidates(specialist_subtasks, retry_counts)
            if retry_subtasks:
                first_retry_index = min(plan.index(s) for s in retry_subtasks)
                for s in retry_subtasks:
                    retry_counts[s.id] = retry_counts.get(s.id, 0) + 1
                    s.status = "pending"
                    s.output = None
                    s.error = None
                    s.tool_calls = []
                    agent_outputs.pop(s.id, None)

                return {
                    "reviewer_score": score,
                    "reviewer_feedback": feedback,
                    "status": "executing",
                    "retry_counts": retry_counts,
                    "current_subtask_index": first_retry_index,
                    "agent_outputs": agent_outputs,
                    "execution_plan": plan,
                }

            # No retries left; escalate.
            return {
                "reviewer_score": score,
                "reviewer_feedback": feedback,
                "final_output": None,
                "status": "escalated",
                "escalation_required": True,
                "escalation_reason": f"Reviewer score {score} is below 0.7 and retry budget is exhausted.",
            }

        final_output = "\n".join(
            f"[{s.id}] {s.description}\n{agent_outputs.get(s.id, '')}"
            for s in specialist_subtasks
        )

        memory_manager = state.get("memory_manager")
        if memory_manager is not None:
            await memory_manager.finalize_task(
                task_id=state["task_id"],
                user_id=state["user_id"],
                final_output=final_output,
                reviewer_score=score,
                confidence_score=state.get("confidence_score", 0.0),
                duration_ms=state.get("duration_ms") or 0.0,
                cost_usd=state.get("cost_usd") or 0.0,
                tags=state.get("tags") or [],
            )

        return {
            "reviewer_score": score,
            "reviewer_feedback": feedback,
            "final_output": final_output,
            "status": "complete",
        }

    def _build_feedback(
        self, score: float, subtasks: list[Subtask], agent_outputs: dict[str, str]
    ) -> str:
        lines = [f"Reviewer score: {score}"]
        for s in subtasks:
            output = agent_outputs.get(s.id, "")
            lines.append(
                f"- subtask {s.id} ({s.assigned_agent}): status={s.status}, "
                f"output_length={len(output)}, expected={s.expected_output or 'n/a'}"
            )
        return "\n".join(lines)

    def _find_retry_candidates(
        self, subtasks: list[Subtask], retry_counts: dict[str, int]
    ) -> list[Subtask]:
        """Return subtasks eligible for retry, up to MAX_RETRIES each."""
        candidates = []
        for s in subtasks:
            if s.status == "failed" or not s.output:
                if retry_counts.get(s.id, 0) < self.MAX_RETRIES:
                    candidates.append(s)
        return candidates


async def reviewer_node(state: AgentState) -> AgentState:
    """LangGraph node that reviews specialist outputs."""
    agent = ReviewerAgent()
    result = await agent.review(state)
    await publish_status(state["user_id"], state["task_id"], result["status"])
    return result
