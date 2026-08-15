import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.infrastructure.database.base import Base

# Every ORM model must be imported here, or Base.metadata is empty and
# `alembic revision --autogenerate` produces an empty migration.
from app.domains.users.model.invited_email import InvitedEmailModel  # noqa: F401
from app.domains.users.model.user_model import UserModel  # noqa: F401
from app.domains.documents.model.document_model import DocumentModel  # noqa: F401
from app.observability.model.run_model import RunModel, RunStepModel  # noqa: F401
from app.observability.model.guardrail_model import GuardrailEventModel  # noqa: F401
from app.domains.chat.model.chat_model import ChatMessageModel, ChatSessionModel  # noqa: F401
from app.domains.drafts.model.draft_model import DraftModel  # noqa: F401
from app.domains.units.model.unit_model import UnitModel  # noqa: F401
from app.domains.companies.model.company_model import CompanyModel  # noqa: F401
from app.core.authz.model.permission_grant_model import PermissionGrantModel  # noqa: F401
from app.domains.units.model.unit_membership_model import UnitMembershipModel  # noqa: F401
from app.domains.pools.model.document_pool_model import DocumentPoolModel  # noqa: F401
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel  # noqa: F401
from app.domains.drafts.model.draft_share_model import DraftShareModel  # noqa: F401
from app.domains.notifications.model.notification_model import NotificationModel  # noqa: F401
from app.domains.audit.model.audit_log_model import AuditLogModel  # noqa: F401
from app.domains.quotas.model.usage_counter_model import UsageCounterModel  # noqa: F401
from app.domains.quotas.model.company_quota_model import CompanyQuotaModel  # noqa: F401
from app.domains.feedback.model.feedback_model import FeedbackModel  # noqa: F401
from app.domains.training.model.training_run_model import TrainingRunModel  # noqa: F401
from app.domains.training.model.training_sample_model import TrainingSampleModel  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read the connection string from application settings rather than
# alembic.ini. Deliberately the schema-owner connection
# (effective_alembic_database_url), not settings.DATABASE_URL directly: from
# Faz 3 (Postgres RLS) onward the app itself connects as a restricted,
# non-owner role that cannot run DDL -- see DATABASE_URL/ALEMBIC_DATABASE_URL's
# own docstrings in app.core.config.
config.set_main_option("sqlalchemy.url", settings.effective_alembic_database_url)

target_metadata = Base.metadata

#: LangGraph's AsyncPostgresSaver owns the checkpoint tables via its own
#: .setup() call (app/infrastructure/checkpointing/postgres.py), run at
#: application startup, not through Alembic. They must be excluded from
#: autogenerate -- otherwise the next `alembic revision --autogenerate` sees
#: tables Alembic doesn't know it doesn't own and emits DROP statements for
#: them.
_CHECKPOINT_TABLE_PREFIX = "checkpoint"


def include_object(object_, name, type_, reflected, compare_to):
    """Exclude LangGraph's self-managed checkpoint tables from autogenerate."""
    if type_ == "table" and name and name.startswith(_CHECKPOINT_TABLE_PREFIX):
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection."""
    context.configure(
        url=settings.effective_alembic_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using the async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
