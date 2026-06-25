"""
End-to-end demo: research top 3 open-source LLM frameworks (2024).

Usage (local):
    python demo/run_demo.py

Usage (Docker):
    docker-compose --profile demo run demo

The script:
  1. Creates a session + task via the REST API
  2. Directly invokes the LangGraph workflow (async)
  3. Auto-approves any escalation with decision="approve"
  4. Prints the final report, trace summary, and saved memory entry
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8003")
DEMO_USER_ID = "demo-user"
DEMO_TASK = (
    "Research the top 3 open-source LLM frameworks released in 2024, compare their "
    "GitHub stars and key features, analyze adoption trends, and produce a structured "
    "markdown report with a recommendation."
)

POLL_INTERVAL = 2  # seconds
MAX_WAIT = 120     # seconds


def _hr(char: str = "─", width: int = 70) -> str:
    return char * width


def _print_section(title: str, content: str) -> None:
    print(f"\n{_hr()}")
    print(f"  {title}")
    print(_hr())
    print(content)


async def create_session(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{API_BASE}/api/v1/sessions/",
        json={"title": f"Demo — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"},
    )
    resp.raise_for_status()
    session_id = resp.json()["id"]
    print(f"✓ Session created: {session_id}")
    return session_id


async def create_task(client: httpx.AsyncClient, session_id: str) -> str:
    resp = await client.post(
        f"{API_BASE}/api/v1/tasks/",
        json={"session_id": session_id, "payload": {"description": DEMO_TASK}},
    )
    resp.raise_for_status()
    task_id = resp.json()["id"]
    print(f"✓ Task created:   {task_id}")
    return task_id


async def invoke_workflow(task_id: str, session_id: str) -> dict:
    """Run the LangGraph agent graph directly (bypasses Celery for the demo)."""
    from app.agents.graph import agent_graph
    from app.db.session import async_session
    from app.services.escalation_service import EscalationService  # noqa: F811

    async with async_session() as db:
        from app.memory.memory_manager import MemoryManager

        mm = MemoryManager()
        es = EscalationService(memory_manager=mm, db_session=db)

        initial_state = {
            "task_id": task_id,
            "session_id": session_id,
            "user_id": DEMO_USER_ID,
            "original_task": DEMO_TASK,
            "execution_plan": [],
            "current_subtask_index": 0,
            "agent_outputs": {},
            "memory_context": [],
            "confidence_score": 0.0,
            "escalation_required": False,
            "retry_counts": {},
            "retries": {},
            "status": "planning",
            "memory_manager": mm,
            "escalation_service": es,
        }

        try:
            final_state = await agent_graph.ainvoke(initial_state)
        except RuntimeError as exc:
            msg = str(exc)
            print(f"\n⚠  {msg}")
            if "authentication" in msg.lower() or "ANTHROPIC_API_KEY" in msg:
                print("   → Add a real key to .env: ANTHROPIC_API_KEY=sk-ant-...")
            return {"status": "failed", "error": msg}
        except Exception as exc:
            print(f"\n⚠  Unexpected workflow error: {exc}")
            return {"status": "failed", "error": str(exc)}
        finally:
            await mm.close()

    return final_state


async def poll_for_escalation(client: httpx.AsyncClient, user_id: str, timeout: int = 30) -> dict | None:
    """Return the first pending approval request for this user, or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = await client.get(f"{API_BASE}/api/v1/reviews/pending")
        if resp.status_code == 200:
            items = resp.json()
            if items:
                return items[0]
        await asyncio.sleep(POLL_INTERVAL)
    return None


async def auto_approve(client: httpx.AsyncClient, request_id: str) -> None:
    resp = await client.post(
        f"{API_BASE}/api/v1/reviews/{request_id}/decide",
        json={
            "decision": "approve",
            "notes": "Demo auto-approval",
            "reviewer_user_id": str(uuid.uuid4()),
        },
    )
    if resp.status_code == 200:
        print(f"  ✓ Auto-approved escalation {request_id}")
    else:
        print(f"  ✗ Auto-approve failed: {resp.status_code} {resp.text[:200]}")


async def main() -> None:
    print(_hr("═"))
    print("  AGENT ORCHESTRATION — END-TO-END DEMO")
    print(_hr("═"))

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Health check
        try:
            health = (await client.get(f"{API_BASE}/health")).json()
            print(f"\n✓ Backend health: {health['status']}  services={health.get('services', {})}")
        except Exception as exc:
            print(f"\n✗ Backend unreachable at {API_BASE}: {exc}")
            print("  Start the stack with: docker-compose up -d")
            sys.exit(1)

        session_id = await create_session(client)
        task_id = await create_task(client, session_id)

    print(f"\n⟳  Running agent workflow (this may take 60–90s with a real API key)…")
    t0 = time.time()
    final_state = await invoke_workflow(task_id, session_id)
    elapsed = time.time() - t0

    status = final_state.get("status", "unknown")
    print(f"\n✓ Workflow finished in {elapsed:.1f}s — status={status}")

    if status == "failed":
        _print_section("ERROR", final_state.get("error", "unknown error"))
        return

    if status == "escalated":
        print("\n⟳  Workflow escalated — auto-approving via API…")
        async with httpx.AsyncClient(timeout=10.0) as client:
            req = await poll_for_escalation(client, DEMO_USER_ID)
            if req:
                await auto_approve(client, req["id"])
            else:
                print("  No pending escalation found within timeout.")

    # Print results
    final_output = final_state.get("final_output") or "(no output produced)"
    _print_section("FINAL REPORT", final_output)

    plan = final_state.get("execution_plan", [])
    plan_list = [
        f"  [{i+1}] {getattr(s, 'assigned_agent', '?'):12s} — {getattr(s, 'description', '?')[:60]}"
        for i, s in enumerate(plan)
    ]
    trace_summary = "\n".join([
        f"  Subtasks    : {len(plan)}",
        f"  Elapsed     : {elapsed:.1f}s",
        f"  Conf. score : {final_state.get('confidence_score', 0):.2f}",
        f"  Review score: {final_state.get('reviewer_score', 0):.2f}",
        "",
        "  Plan:",
        *plan_list,
    ])
    _print_section("TRACE SUMMARY", trace_summary)

    print(f"\n{_hr('═')}")
    print("  Demo complete. Open http://localhost:3000 to inspect via the UI.")
    print(_hr("═"))


if __name__ == "__main__":
    asyncio.run(main())
