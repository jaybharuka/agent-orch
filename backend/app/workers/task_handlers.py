"""Celery task handlers."""
from app.workers.celery_app import celery_app


@celery_app.task(bind=True)
def run_agent_workflow(self, task_id: str) -> dict:
    """Execute the LangGraph agent workflow for a task."""
    return {"task_id": task_id, "status": "pending"}
