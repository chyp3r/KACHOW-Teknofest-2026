"""In-process ASGI e2e fixtures: a real HTTP-shaped client against the full app.

**Transport: in-process ASGI, not a live server.** ``httpx.AsyncClient(transport=
ASGITransport(app=app), base_url=...)``. A real ``uvicorn`` process was
considered and rejected: (a) every monkeypatch below (the fake-client and
RLS-session injection) only reaches the app in the interpreter that set it --
a second process's imports of the same modules are separate objects
entirely; (b) ``tests/_db_fixtures.py``'s own docstring documents *why*
``owner_engine``/``app_engine`` are function-scoped -- an ``AsyncSession``'s
connection pool is bound to the event loop that created it, and a second
process/thread running uvicorn would reproduce that exact failure class one
level up; (c) ``client.stream("POST", ...)`` over ``ASGITransport`` still
streams a real ``StreamingResponse`` chunk by chunk, so SSE stays testable.

**What this transport cannot cover:** ``Request.is_disconnected()`` never
fires under ``ASGITransport`` (there is no real socket to drop), so the
client-disconnect abort path in ``chat/router.py::_sse_response`` is not
exercised here -- that is k6's job (Workstream E), not this suite's.

**Fake LLM/embeddings injection is not a single ``dependency_overrides``
call.** The compiled LangGraph workflows and retrievers in
``app.api.dependency`` are module-level singletons built by calling
``get_llm_client()``/``get_fast_llm_client()``/``get_embeddings_client()``
directly at *build* time, not through per-request ``Depends()`` -- so
overriding a FastAPI dependency does nothing here; the graphs would still
compile against real Ollama the moment anything triggers their first build
(including this fixture's own lifespan warm-up). Two things must both happen,
in order, before the app's lifespan runs a single line:

1. Every module that bound one of those three factory names via
   ``from ... import name`` gets its own name monkeypatched (patching the
   *source* module, ``app.ai.llms``/``app.ai.embeddings.models``, does not
   reach a module that already imported its own reference -- see
   ``_LLM_CLIENT_PATCH_TARGETS`` below, produced by grepping every call site
   in ``backend/app/``).
2. Every process-wide singleton ``app.api.dependency`` may have already built
   in an earlier (non-e2e) test run in this same pytest session is reset to
   ``None`` (``_DEPENDENCY_SINGLETONS`` below) -- otherwise a singleton built
   before this fixture ran keeps holding a real client forever, immune to any
   later patch.

**Auth is not actually gated by ``settings.REQUIRE_AUTH`` any more.**
``app/api/dependency.py::require_auth_if_enabled``'s own docstring explains
why: multi-tenancy made every row carry a ``company_id``, so there is no
"unauthenticated demo path" left to fall back to -- the function is
unconditional despite its name. ``tests/conftest.py``'s autouse
``_default_require_auth_off`` fixture flips a flag nothing in the auth
dependency chain reads any more; every unit test that needs an authenticated
route instead overrides ``get_current_user``/``require_auth_if_enabled``
directly via ``app.dependency_overrides`` (11 files already do this -- grep
confirms it). This fixture module does the same thing e2e tests actually
need: a real round trip through ``POST /api/v1/auth/login`` with a genuine
bcrypt-hashed password (``e2e_register_user`` below), never a shortcut
around it -- that round trip, and the RLS it feeds into via ``get_db``, is
the entire reason this suite exists instead of the 13 existing MemorySaver
graph tests.

**RLS is real, and so is get_db/get_owner_db/tenant_session -- unmodified.**
Rather than ``app.dependency_overrides``, this fixture monkeypatches the two
module-level sessionmakers ``app.infrastructure.database.session.
AsyncSessionLocal``/``OwnerAsyncSessionLocal`` those three functions all
close over, onto dedicated engines pointed at this test's own throwaway
``pg_test_database`` (``kachow_app`` / owner roles). ``dependency_overrides``
was tried first and rejected: it only reaches the two functions FastAPI
actually resolves through ``Depends(...)``, but ``AuditService.record`` and
every "out-of-request writer" ``tenant_session``'s own docstring lists (chat/
draft/run/guardrail recorders, notification-writing event subscribers) call
``tenant_session()`` directly -- an ordinary authenticated ``GET`` writing an
audit log entry was enough to open a real connection against this
container's actual dev database instead of the test one. Patching the
sessionmakers catches all three call paths at once.

**Qdrant is real, embeddings are fake.** ``app.infrastructure.vectorstore.
get_vector_store()`` is left untouched (it already points at the real
``settings.QDRANT_URL`` this container reaches), but every embedding it
stores/queries comes from ``FakeEmbeddingsClient`` -- deterministic,
correctly-dimensioned, and Qdrant does not care where a vector came from.
The ``document_qa`` collection is the one exception that needs isolating: a
random per-test suffix (``QA_COLLECTION_NAME`` is patched in every module
that duplicates that literal -- ``service.py``, ``document_tools.py``,
``dependency.py``'s ``_DOCUMENT_QA_COLLECTION_NAME`` -- see
``app/api/dependency.py:206-209``'s own comment on why it's a duplicated
literal, not an import) keeps one e2e test's uploaded chunks from leaking
into another's, and the collection is dropped at teardown.
"""

import uuid
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urlsplit

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests._db_fixtures import *  # noqa: F401,F403
from tests._db_fixtures import _with_database

from app.core.config import settings
from app.core.security import hash_password
from app.infrastructure.cache import get_cache
from app.main import app as fastapi_app

#: (module, attribute) pairs to monkeypatch so every LLM/embeddings call
#: anywhere in the app resolves to this fixture's fakes -- see this module's
#: own docstring for why patching the source module alone is not enough.
#: Produced by `grep -rn "get_llm_client\|get_fast_llm_client\|get_embeddings_client" backend/app/`.
_LLM_CLIENT_PATCH_TARGETS = [
    ("app.api.dependency", "get_llm_client"),
    ("app.api.dependency", "get_fast_llm_client"),
    ("app.api.dependency", "get_embeddings_client"),
    # app.lifespan._warm_up_models does `from app.ai.llms import ...` inside
    # its own function body, re-executed on every call -- patching the
    # source here (rather than app.lifespan, which never binds its own name
    # at module scope) is what reaches it.
    ("app.ai.llms", "get_llm_client"),
    ("app.ai.llms", "get_fast_llm_client"),
    ("app.domains.training.router", "get_fast_llm_client"),
]

#: Process-wide singletons app.api.dependency lazily builds and caches --
#: must be cleared before this fixture's fake clients are wired in, or a
#: singleton compiled by an earlier test keeps holding a real client for the
#: rest of the process.
_DEPENDENCY_SINGLETONS = [
    "_mevzuat_retriever",
    "_example_retriever",
    "_document_qa_retriever",
    "_document_analysis_mevzuat_retriever",
    "_document_analysis_graph",
    "_draft_graph",
    "_routing_graph",
    "_rag_graph",
    "_planning_graph",
]


def _app_role_url(pg_test_database: str) -> str:
    """The ``kachow_app`` role's URL against this test's throwaway database.

    Mirrors ``tests/_db_fixtures.py``'s own ``app_engine`` fixture's inline
    construction -- duplicated rather than imported because this module
    builds its own dedicated (``NullPool``) engine instead of reusing that
    fixture's pooled one; see ``e2e_client``'s own comment on why.
    """
    owner_admin_url = settings.effective_alembic_database_url
    return _with_database(
        f"postgresql+asyncpg://kachow_app:{settings.KACHOW_APP_DB_PASSWORD}@"
        f"{urlsplit(owner_admin_url).hostname}:{urlsplit(owner_admin_url).port}",
        pg_test_database,
    )


@pytest.fixture
async def e2e_client(
    monkeypatch,
    tmp_path,
    pg_test_database,
    fake_llm,
    fake_fast_llm,
    fake_embeddings,
) -> AsyncIterator[httpx.AsyncClient]:
    """A real HTTP-shaped client against the full app: RLS, real lifespan, fake models.

    See this module's docstring for the full rationale. Function-scoped, on
    purpose, mirroring ``tests/_db_fixtures.py``'s own "engines are
    function-scoped, not session-scoped" reasoning -- a compiled graph or an
    open checkpointer pool bound to one test's event loop cannot outlive it
    safely either.
    """
    import app.ai.llms as ai_llms
    import app.ai.tools.document_tools as document_tools
    import app.api.dependency as dependency
    import app.domains.companies.seeder as companies_seeder
    import app.domains.documents.service as document_service
    import app.domains.training.router as training_router
    import app.domains.users.seeder as users_seeder
    import app.infrastructure.database.session as session_module
    import app.infrastructure.storage as storage_module

    # 1. Point the LangGraph checkpointer (see app.lifespan.lifespan ->
    # init_checkpointer) at this test's own throwaway database instead of
    # the real one -- checkpointer_dsn reads effective_alembic_database_url,
    # i.e. ALEMBIC_DATABASE_URL when set.
    owner_url = _with_database(settings.effective_alembic_database_url, pg_test_database)
    monkeypatch.setattr(settings, "ALEMBIC_DATABASE_URL", owner_url)

    # 2. Isolated local document storage per test.
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(storage_module, "_storage_client", None)

    # 3. Fake LLM/embeddings clients at every binding site (see module docstring).
    def _llm(*_args: Any, **_kwargs: Any) -> Any:
        return fake_llm

    def _fast_llm(*_args: Any, **_kwargs: Any) -> Any:
        return fake_fast_llm

    def _embeddings(*_args: Any, **_kwargs: Any) -> Any:
        return fake_embeddings

    _fakes_by_name = {
        "get_llm_client": _llm,
        "get_fast_llm_client": _fast_llm,
        "get_embeddings_client": _embeddings,
    }
    for module_path, attr_name in _LLM_CLIENT_PATCH_TARGETS:
        module = {
            "app.api.dependency": dependency,
            "app.ai.llms": ai_llms,
            "app.domains.training.router": training_router,
        }[module_path]
        monkeypatch.setattr(module, attr_name, _fakes_by_name[attr_name])

    # 4. Drop any graph/retriever a previous test already compiled with real
    # clients -- must happen *after* the patches above, so the next lazy
    # build (whether during this fixture's own lifespan warm-up below, or on
    # the test's first request) uses the fakes.
    for singleton_name in _DEPENDENCY_SINGLETONS:
        monkeypatch.setattr(dependency, singleton_name, None)

    # 5. An isolated document_qa Qdrant collection for this test alone (see
    # module docstring on why the same literal is duplicated three times).
    qa_collection = f"document_qa_e2e_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(document_service, "QA_COLLECTION_NAME", qa_collection)
    monkeypatch.setattr(document_tools, "QA_COLLECTION_NAME", qa_collection)
    monkeypatch.setattr(dependency, "_DOCUMENT_QA_COLLECTION_NAME", qa_collection)
    # _probe_embedding_dimension caches its result process-wide; a fake
    # embeddings client from an earlier test may have used a different
    # dimension, which would otherwise silently stick.
    monkeypatch.setattr(document_service, "_qa_vector_size", None)

    # 6. Redirect the module-level sessionmakers app.infrastructure.database.
    # session.get_db/get_owner_db/tenant_session all close over, instead of
    # reimplementing those functions -- this is what makes get_db/
    # get_owner_db run *unmodified* here, and it is the only way to catch
    # tenant_session() too: AuditService.record (app/domains/audit/
    # service.py) and every "out-of-request writer" tenant_session's own
    # docstring lists (chat/draft/run/guardrail recorders, event
    # subscribers' notification writes) call tenant_session() directly, not
    # through any FastAPI Depends() an app.dependency_overrides entry could
    # intercept -- an audit-log write on a plain authenticated GET is enough
    # to reach it. Deliberately NullPool, and a dedicated engine rather than
    # tests/_db_fixtures.py's own app_engine/owner_engine fixtures: a
    # *pooled* asyncpg connection whose pool (with SQLAlchemy's default
    # pool_pre_ping=True, which session.py's own engines set) survives past
    # this fixture's teardown into a later test's already-different event
    # loop reproduces a genuine, observed failure here -- pytest-asyncio
    # gives every test its own loop, and pre-ping-ing a pooled connection
    # created on a since-closed loop raises "got Future ... attached to a
    # different loop" the moment it's checked out again. NullPool means
    # every checkout is a fresh connection, closed on checkin, so nothing
    # outlives this fixture's own explicit `dispose()` below for a later
    # test to inherit.
    e2e_app_engine = create_async_engine(_app_role_url(pg_test_database), future=True, poolclass=NullPool)
    e2e_owner_engine = create_async_engine(
        _with_database(settings.effective_alembic_database_url, pg_test_database),
        future=True,
        poolclass=NullPool,
    )
    e2e_app_session_maker = async_sessionmaker(bind=e2e_app_engine, class_=AsyncSession, expire_on_commit=False)
    e2e_owner_session_maker = async_sessionmaker(bind=e2e_owner_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(session_module, "AsyncSessionLocal", e2e_app_session_maker)
    monkeypatch.setattr(session_module, "OwnerAsyncSessionLocal", e2e_owner_session_maker)
    # app.domains.companies.seeder and app.domains.users.seeder each did
    # `from app.infrastructure.database.session import AsyncSessionLocal`/
    # `OwnerAsyncSessionLocal` -- a *name* import binds the sessionmaker
    # object into their own module namespace at their own import time, so
    # the patch above (which only replaces session_module's own attribute)
    # never reaches either. app.lifespan.lifespan calls seed_demo_company()
    # on every startup regardless of SEED_DEMO_COMPANY (it always checks for
    # an existing company first -- see that function's own docstring), so
    # this is not a hypothetical: it is exactly what produced this fixture's
    # first real symptom, a connection pooled on the *production* engine
    # getting pre-ping'd from a later test's already-different event loop.
    monkeypatch.setattr(companies_seeder, "AsyncSessionLocal", e2e_app_session_maker)
    monkeypatch.setattr(users_seeder, "OwnerAsyncSessionLocal", e2e_owner_session_maker)

    # 7. Clear rate-limit/blacklist state so a previous e2e test's login
    # attempts don't count against this one's 5-req/60s auth:login cap
    # (app/domains/auth/router.py's rate_limit(...) dependency) -- mirrors
    # `make reset-cache`'s own FLUSHALL.
    cache = get_cache()
    await cache.connect()
    await cache.client.flushall()

    try:
        # 8. Run the app's real lifespan (checkpointer init against this
        # test's DB, best-effort graph warm-up against the fakes above) and
        # hand back a client shaped like a real HTTP client.
        async with fastapi_app.router.lifespan_context(fastapi_app):
            transport = ASGITransport(app=fastapi_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://e2e.test") as client:
                yield client
    finally:
        await e2e_app_engine.dispose()
        await e2e_owner_engine.dispose()
        # Best-effort, matching `make reset-document-qa`'s own idiom -- a
        # dropped collection that fails to drop costs nothing but disk on a
        # throwaway dev Qdrant.
        try:
            async with httpx.AsyncClient(base_url=settings.QDRANT_URL, timeout=5.0) as qdrant_client:
                await qdrant_client.delete(f"/collections/{qa_collection}")
        except Exception:
            pass


@pytest.fixture
def e2e_register_user(pg_test_database) -> Callable[..., Any]:
    """Factory: insert a company + a real, bcrypt-hashed-password user.

    Unlike ``two_companies`` (``tests/_db_fixtures.py``), whose
    ``hashed_password='x'`` literal only ever needs to satisfy direct-SQL RLS
    assertions, an e2e test that calls ``POST /api/v1/auth/login`` needs a
    hash ``AuthService.authenticate_user`` can actually verify. Returns the
    plaintext password alongside the created ids so the caller can log in
    with it immediately.

    A dedicated, ``NullPool``, dispose-per-call owner engine -- not
    ``tests/_db_fixtures.py``'s own ``owner_engine`` fixture -- for the same
    reason ``e2e_client`` builds its own (see that fixture's comment): a
    pooled connection surviving past this fixture is exactly the shape of the
    cross-event-loop asyncpg finalization error that motivated it.
    """

    async def _register(
        *,
        username: Optional[str] = None,
        password: str = "e2e-test-password-1",
        role: str = "employee",
        clearance_level: str = "hizmete_ozel",
    ) -> dict:
        owner_engine = create_async_engine(
            _with_database(settings.effective_alembic_database_url, pg_test_database),
            future=True,
            poolclass=NullPool,
        )
        session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)
        company_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex
        resolved_username = username or f"e2e-user-{uuid.uuid4().hex[:8]}"
        async with session_maker() as session:
            await session.execute(
                text(
                    "INSERT INTO companies (id, name, slug, is_active, is_deleted, settings, created_at, updated_at) "
                    "VALUES (:id, :name, :slug, true, false, '{}', now(), now())"
                ),
                {
                    "id": company_id,
                    "name": f"E2E Co {resolved_username}",
                    "slug": f"e2e-{uuid.uuid4().hex[:8]}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO users (id, company_id, username, email, hashed_password, role, "
                    "clearance_level, is_active, is_deleted, created_at, updated_at) "
                    "VALUES (:id, :cid, :username, :email, :hashed, :role, :clearance, true, false, now(), now())"
                ),
                {
                    "id": user_id,
                    "cid": company_id,
                    "username": resolved_username,
                    "email": f"{resolved_username}@kachow.example",
                    "hashed": hash_password(password),
                    "role": role,
                    "clearance": clearance_level,
                },
            )
            await session.commit()
        await owner_engine.dispose()
        return {
            "company_id": company_id,
            "user_id": user_id,
            "username": resolved_username,
            "password": password,
        }

    return _register
