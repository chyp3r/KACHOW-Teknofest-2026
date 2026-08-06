"""Application startup and shutdown hooks.

The expensive, one-off work that used to be paid by whichever unlucky user sent
the first request happens here instead: loading models into Ollama and compiling
the LangGraph workflows. On Apple Silicon a cold 9B load is several seconds, and
paying it inside a request makes the system look far slower than it is.

Every step is best-effort. A missing Ollama or an unreachable Qdrant must not
prevent the API from booting -- the health endpoint should come up and report the
problem rather than the process dying at import time.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Cap on startup warm-up. Past this the API should come up anyway and let the
#: first request pay the remainder.
WARMUP_TIMEOUT_SECONDS = 120


async def _warm_up_models() -> None:
    """Load the configured models into Ollama's memory."""
    from app.ai.llms import get_fast_llm_client, get_llm_client

    clients = [get_llm_client()]
    fast = get_fast_llm_client()
    if fast is not clients[0]:
        clients.append(fast)

    for client in clients:
        warm_up = getattr(client, "warm_up", None)
        if warm_up is None:
            continue
        await warm_up()


async def _warm_up_graphs() -> None:
    """Compile the workflows and build the retriever before traffic arrives."""
    from app.api.dependency import (
        get_document_analysis_graph,
        get_draft_graph,
        get_mevzuat_retriever,
        get_planning_graph,
        get_rag_graph,
        get_routing_graph,
    )

    retriever = await get_mevzuat_retriever()
    analysis_graph = await get_document_analysis_graph(retriever)
    rag_graph = await get_rag_graph()
    draft_graph = await get_draft_graph()
    routing_graph = await get_routing_graph()
    await get_planning_graph(analysis_graph, rag_graph, draft_graph, routing_graph)
    logger.info("Compiled all AI workflows.")


async def _startup() -> None:
    """Run every warm-up step, tolerating individual failures."""
    tasks = [_warm_up_graphs()]
    if settings.OLLAMA_WARMUP_ON_STARTUP:
        tasks.append(_warm_up_models())

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=WARMUP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Startup warm-up exceeded %ss; continuing without it.",
            WARMUP_TIMEOUT_SECONDS,
        )
        return

    for result in results:
        if isinstance(result, Exception):
            logger.warning("A startup warm-up step failed: %s", result)


def _require_auth_in_production() -> None:
    """Refuse to boot a production deployment with auth left open.

    /chat and /documents hold a local model busy for tens of seconds per
    request and read whatever storage_path/session_id they're given (see
    settings.REQUIRE_AUTH's docstring) -- open by default so the competition
    demo works without a login flow, but a real "production" deployment left
    that way is the IDOR this phase exists to close. Refusing to boot is
    deliberate: REQUIRE_AUTH is trivial to flip and a log line is easy to
    miss, but a process that never started is not.

    Raises:
        RuntimeError: If `ENVIRONMENT == "production"` and `REQUIRE_AUTH` is
            not enabled.
    """
    if settings.ENVIRONMENT == "production" and not settings.REQUIRE_AUTH:
        raise RuntimeError(
            "REQUIRE_AUTH must be enabled when ENVIRONMENT=production -- "
            "set REQUIRE_AUTH=true or run with ENVIRONMENT=development/staging."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown.

    Args:
        app: The FastAPI application.

    Yields:
        Control to the running application.
    """
    logger.info("Starting %s (%s)...", settings.PROJECT_NAME, settings.ENVIRONMENT)

    _require_auth_in_production()

    # Registers the event bus's listeners as a side effect of import (the
    # @subscribe decorator runs at module load time). Without this import
    # DocumentService/DraftService's publish() calls have no subscriber at
    # all -- the bus was write-only.
    import app.events.subscribers  # noqa: F401

    # Deliberately outside _startup()'s WARMUP_TIMEOUT_SECONDS budget: the
    # planning graph's compilation (inside _warm_up_graphs) needs the
    # checkpointer already open, and a slow Postgres must not silently steal
    # time from the model warm-up budget or get skipped by it.
    from app.infrastructure.checkpointing import init_checkpointer

    await init_checkpointer()

    # Best-effort, like every other step here: a seeding failure must not
    # prevent the API from booting. Placed after the checkpointer (so the
    # database is known-reachable) and outside _startup()'s warm-up budget,
    # same reasoning as init_checkpointer() itself.
    from app.domains.users.seeder import seed_default_users

    await seed_default_users()

    await _startup()
    logger.info("Startup complete; accepting requests.")
    try:
        yield
    finally:
        logger.info("Shutting down %s.", settings.PROJECT_NAME)
        from app.infrastructure.checkpointing import close_checkpointer

        await close_checkpointer()
