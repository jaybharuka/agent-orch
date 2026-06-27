"""
End-to-end demo: research top 3 open-source LLM frameworks (2024).

Usage (Docker demo profile):
    docker-compose --profile demo run --rm demo python demo/run_demo.py

Usage (exec into backend container):
    docker-compose exec backend python demo/run_demo.py

The script:
  1. Creates a session + task via the REST API
  2. Directly invokes the LangGraph workflow (async)
  3. When an escalation is detected, prints a message and waits for manual
     approval via the Review Queue UI at http://localhost:3000
  4. Prints the final report, trace summary, and saved memory entry
"""
import asyncio
import os
import sys
import time
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# When running inside the backend container, FastAPI is at :8000.
# The demo-profile service sets API_BASE_URL=http://backend:8000.
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
DEMO_USER_ID = "demo-user"
HUMAN_APPROVAL_TIMEOUT = 300  # 5 minutes

DEMO_TASK = (
    "Research the top 3 open-source LLM frameworks released in 2024, compare their "
    "GitHub stars and key features, analyze adoption trends, and produce a structured "
    "markdown report with a recommendation."
)


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


async def wait_for_human_approval(escalation_event: asyncio.Event) -> None:
    """
    Polls /reviews/pending every 3 seconds. When an escalation appears, prints
    a prompt and waits for a human to approve it via the UI. Stops once every
    pending request has been resolved (no longer pending).
    """
    notified: set[str] = set()
    deadline = time.time() + HUMAN_APPROVAL_TIMEOUT

    async with httpx.AsyncClient(timeout=10.0) as client:
        while not escalation_event.is_set():
            await asyncio.sleep(3)
            try:
                resp = await client.get(f"{API_BASE}/api/v1/reviews/pending")
                if resp.status_code != 200:
                    continue
                pending = resp.json()
            except Exception:
                continue

            for item in pending:
                rid = item.get("id", "")
                if rid and rid not in notified:
                    notified.add(rid)
                    print(f"\n{'⚠' * 3} ESCALATION DETECTED {'⚠' * 3}", flush=True)
                    print(f"  Request ID : {rid}", flush=True)
                    print(f"  Trigger    : {item.get('trigger', 'unknown')}", flush=True)
                    print(f"  Action     : {item.get('proposed_action', '')}", flush=True)
                    print(flush=True)
                    print("  ⚠ Escalation detected! Go to http://localhost:3000 and approve", flush=True)
                    print("    it in the Review Queue tab. Waiting up to 5 minutes...", flush=True)
                    print(flush=True)

            # Check if all notified requests are resolved.
            if notified and not pending:
                print("  ✓ All escalations resolved — workflow resuming.")
                escalation_event.set()
                return

            if time.time() > deadline:
                print("  ✗ Timed out waiting for human approval (5 min).")
                escalation_event.set()
                return


async def invoke_workflow(task_id: str, session_id: str) -> dict:
    """Run the LangGraph agent graph directly (bypasses Celery for the demo)."""
    from app.agents.graph import agent_graph
    from app.db.session import async_session
    from app.services.escalation_service import EscalationService

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
            final_state = await agent_graph.ainvoke(
                initial_state, {"recursion_limit": 100}
            )
        except RuntimeError as exc:
            msg = str(exc)
            print(f"\n⚠  {msg}")
            if "authentication" in msg.lower() or "NVIDIA" in msg or "ANTHROPIC" in msg:
                print("   → Check NVIDIA_API_KEY or ANTHROPIC_API_KEY in .env")
            return {"status": "failed", "error": msg}
        except Exception as exc:
            import traceback
            print(f"\n⚠  Unexpected workflow error: {exc}")
            traceback.print_exc()
            return {"status": "failed", "error": str(exc)}
        finally:
            await mm.close()

    return final_state


async def main() -> None:
    print(_hr("═"))
    print("  AGENT ORCHESTRATION — END-TO-END DEMO")
    print(_hr("═"))

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            health = (await client.get(f"{API_BASE}/health")).json()
            print(f"\n✓ Backend health: {health['status']}  services={health.get('services', {})}")
        except Exception as exc:
            print(f"\n✗ Backend unreachable at {API_BASE}: {exc}")
            print("  Start the stack with: docker-compose up -d")
            sys.exit(1)

        session_id = await create_session(client)
        task_id = await create_task(client, session_id)

    print(f"\n⟳  Running agent workflow (NVIDIA NIM · llama-3.1-70b)…")
    print("   Watch http://localhost:3000 for real-time status updates.\n")

    escalation_event = asyncio.Event()
    watcher = asyncio.create_task(wait_for_human_approval(escalation_event))

    t0 = time.time()
    final_state = await invoke_workflow(task_id, session_id)
    elapsed = time.time() - t0

    escalation_event.set()
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass

    status = final_state.get("status", "unknown")
    print(f"\n✓ Workflow finished in {elapsed:.1f}s — status={status}")

    if status == "failed":
        _print_section("ERROR", final_state.get("error", "unknown error"))
        return

    final_output = final_state.get("final_output") or "(no output produced)"
    _print_section("FINAL REPORT", final_output)

    plan = final_state.get("execution_plan", [])
    plan_list = [
        f"  [{i+1}] {getattr(s, 'assigned_agent', '?'):14s} — {getattr(s, 'description', '?')[:58]}"
        for i, s in enumerate(plan)
    ]
    trace_summary = "\n".join([
        f"  Subtasks    : {len(plan)}",
        f"  Elapsed     : {elapsed:.1f}s",
        f"  Conf. score : {final_state.get('confidence_score', 0):.2f}",
        f"  Review score: {final_state.get('reviewer_score', 0):.2f}",
        f"  Final status: {status}",
        "",
        "  Plan:",
        *plan_list,
    ])
    _print_section("TRACE SUMMARY", trace_summary)

    # Confirm memory was saved
    print(f"\n{_hr()}")
    print("  MEMORY CHECK")
    print(_hr())
    try:
        from app.memory.long_term_memory import LongTermMemory
        ltm = LongTermMemory()
        entries = await ltm.list_entries(DEMO_USER_ID)
        print(f"  ChromaDB entries for user '{DEMO_USER_ID}': {len(entries)}")
        for e in entries[-3:]:
            print(f"  • [{e.id[:8]}] score={e.reviewer_score:.2f}  {e.task_description[:60]}")
        await ltm.close()
    except Exception as exc:
        print(f"  ✗ Memory check failed: {exc}")

    print(f"\n{_hr('═')}")
    print("  Demo complete. Open http://localhost:3000 to inspect via the UI.")
    print(_hr("═"))


if __name__ == "__main__":
    asyncio.run(main())
