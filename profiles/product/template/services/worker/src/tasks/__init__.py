from arq import ArqRedis


async def example_task(ctx: dict, payload: dict) -> dict:
    """Placeholder task — replace with real business logic."""
    return {"status": "ok", "payload": payload}
