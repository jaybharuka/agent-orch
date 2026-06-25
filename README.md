# Agent Orchestration System

## Architecture

```
User ──► React UI (port 3000)
              │
              ▼
        FastAPI (port 8003) ──► PostgreSQL  (tasks, sessions, approvals)
              │                  Redis       (pub/sub, working memory, chat)
              ▼                  ChromaDB    (vector memory, semantic search)
        LangGraph Workflow
        ┌─────────────────────────────────────────────────────┐
        │ Supervisor ──► research │ data_analysis │ writing │  │
        │      │                  └──────code──────┘         │  │
        │      │                          ▼                  │  │
        │   Escalate ◄────────────── Reviewer                │  │
        │      │                                             │  │
        │   Human Review UI  (approve / reject / edit plan)  │  │
        └─────────────────────────────────────────────────────┘
```

| Component | Role |
|---|---|
| **Supervisor** | Decomposes task → subtask plan, scores confidence, escalates if < 0.6 |
| **Specialist** | Executes one subtask via ReAct loop with 6-tool registry |
| **Reviewer** | Scores output coverage; retries or escalates on score < 0.5 |
| **Escalation Service** | Creates approval_requests, publishes Redis events, awaits resolution |
| **Review Queue UI** | Approve / reject / edit plan in real-time via WebSocket |
| **Memory Manager** | Redis (working) + ChromaDB (semantic) + PostgreSQL (structured) |
| **Celery Worker** | Async task execution; Beat handles scheduled memory consolidation |

## Why This Is Not a Demo

- **Persistent memory**: tasks are stored in ChromaDB; the supervisor retrieves semantically similar past tasks to inform new plans from the very first repeat run.
- **Human escalation with loop resumption**: the graph blocks on a Redis pub/sub channel at `escalate` and resumes—including applying reviewer-edited plans—without restarting the workflow.
- **Full observability**: every node publishes status via WebSocket; approval chat threads persist in Redis (48-hour TTL); the health endpoint pings all three datastores.

## Quick Start

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker-compose up --build     # starts all 7 services
# Frontend:  http://localhost:3000
# API docs:  http://localhost:8003/docs
# Run demo:  docker-compose --profile demo run demo
```

## System Capabilities

| Capability | Value |
|---|---|
| Specialist agents | 4 (research, data_analysis, writing, code) |
| Tool types | 6 (web_search, http_request, db_query, run_code, read_file, write_file) |
| Escalation triggers | 5 (low_confidence, repeated_failure, sensitive_operation, low_reviewer_score, user_requested) |
| Working memory TTL | 48 hours (Redis) |
| Reviewer retry limit | 2 before escalation |
| WebSocket channels | approvals:{user_id}, task_control:{task_id}, approval_resolved:{request_id} |

## Phase Build Summary

1. **Phase 1** — Data models, DB migrations, task/session CRUD, Celery skeleton
2. **Phase 2** — Supervisor planner, specialist ReAct loop, reviewer scoring
3. **Phase 3** — Escalation service, approval requests API, Redis pub/sub wait loop
4. **Phase 4** — Memory Manager (Redis + ChromaDB + PostgreSQL), semantic retrieval
5. **Phase 5** — React UI (TaskQueue, SessionViewer, ReviewQueue, MemoryBrowser), CORS, health endpoint

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.1, LangChain 0.2 |
| API | FastAPI 0.111, Uvicorn, Pydantic v2 |
| LLM | Anthropic Claude (configurable) |
| Task queue | Celery 5.4, Redis 7 |
| Databases | PostgreSQL 16, Redis 7, ChromaDB |
| ORM / Migrations | SQLAlchemy 2 async, Alembic |
| Frontend | React 18, TypeScript, Tailwind CSS, Axios |
| Infra | Docker Compose, named volumes, healthchecks |

## Testing

```bash
pytest backend/tests/ -v
```

| Suite | Covers |
|---|---|
| `test_agents.py` | Supervisor plan generation, specialist ReAct loop, reviewer scoring |
| `test_escalation_service.py` | Trigger→severity mapping, Redis pub/sub, plan validation |
| `test_approval_requests.py` | State snapshot, non-serializable object exclusion |
| `test_reviews.py` | All 5 escalation triggers, modified-plan handling, WebSocket timing, chat ordering |
| `test_e2e.py` | Full graph smoke test, tool failure recovery, memory context on repeat runs |
