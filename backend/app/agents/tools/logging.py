"""Tool invocation logging decorator and persistence."""
import functools
import time
from app.db.session import async_session
from app.models.tool_invocation import ToolInvocation


async def _persist_log(
    tool_name: str,
    inputs: dict,
    output: str | None,
    latency_ms: float,
    error: str | None,
) -> None:
    """Persist a tool invocation to Postgres."""
    try:
        async with async_session() as session:
            invocation = ToolInvocation(
                tool_name=tool_name,
                inputs=inputs,
                output=output,
                latency_ms=latency_ms,
                error=error,
            )
            session.add(invocation)
            await session.commit()
    except Exception as log_error:
        # Logging failures must not break tool execution.
        print(f"Failed to log tool invocation for {tool_name}: {log_error}")


def log_tool_invocation(func):
    """Decorator that logs tool_name, inputs, output, latency_ms, and error."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        tool_name = func.__name__
        inputs = dict(kwargs)
        output = None
        error = None
        try:
            output = await func(*args, **kwargs)
            return output
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            await _persist_log(tool_name, inputs, output, latency_ms, error)

    return wrapper
