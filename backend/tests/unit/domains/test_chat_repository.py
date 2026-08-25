from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.repository import ChatMessageRepository


@pytest.mark.asyncio
async def test_message_history_breaks_equal_timestamp_ties_in_turn_order():
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    await ChatMessageRepository(session).list_for_session("thread-1")

    statement = session.execute.await_args.args[0]
    sql = " ".join(
        str(statement.compile(compile_kwargs={"literal_binds": True})).split()
    )
    assert "ORDER BY chat_messages.created_at ASC" in sql
    assert "chat_messages.role = 'user'" in sql
    assert "chat_messages.id ASC" in sql
