"""Seed ChromaDB with 3 synthetic task memories so the supervisor has useful context."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.memory.long_term_memory import LongTermMemory

SEED_USER_ID = "demo-user"

SEEDS = [
    {
        "task_id": "seed-001",
        "task_description": "LLM benchmark comparison 2024",
        "final_output": (
            "Compared GPT-4o, Claude 3.5 Sonnet, and Gemini 1.5 Pro on MMLU, HumanEval, and "
            "MATH benchmarks. Claude 3.5 Sonnet led on coding (87.7% HumanEval). "
            "GPT-4o led on MMLU (87.2%). Report saved to llm_benchmarks_2024.md"
        ),
        "tools_used": ["web_search", "write_file"],
        "reviewer_score": 0.92,
        "tags": ["llm", "benchmark", "comparison", "2024"],
    },
    {
        "task_id": "seed-002",
        "task_description": "GitHub stars analysis script for open-source AI repos",
        "final_output": (
            "Python script using PyGitHub API to fetch star counts, fork counts, and commit "
            "frequency for top AI repos. Outputs sorted CSV. Handles rate-limiting with "
            "exponential backoff. Tested against 50 repos in under 30s."
        ),
        "tools_used": ["run_code", "write_file"],
        "reviewer_score": 0.88,
        "tags": ["github", "python", "data-analysis", "stars"],
    },
    {
        "task_id": "seed-003",
        "task_description": "Technical report writing template for framework comparisons",
        "final_output": (
            "Reusable markdown template with sections: Executive Summary, Methodology, "
            "Results Table, Feature Matrix, Adoption Trend Chart (mermaid), and Recommendation. "
            "Template validated against 3 prior comparison reports."
        ),
        "tools_used": ["write_file"],
        "reviewer_score": 0.85,
        "tags": ["writing", "template", "markdown", "report"],
    },
]


async def seed():
    ltm = LongTermMemory()
    print("Seeding ChromaDB with 3 synthetic task memories...")
    for s in SEEDS:
        try:
            entry_id = await ltm.store_task_result(
                task_id=s["task_id"],
                user_id=SEED_USER_ID,
                task_description=s["task_description"],
                final_output=s["final_output"],
                tools_used=s["tools_used"],
                reviewer_score=s["reviewer_score"],
                tags=s["tags"],
            )
            print(f"  ✓ Seeded '{s['task_description'][:50]}...' → {entry_id}")
        except Exception as exc:
            print(f"  ✗ Failed to seed '{s['task_description'][:40]}': {exc}")
    await ltm.close()
    print("Seeding complete.")


if __name__ == "__main__":
    asyncio.run(seed())
