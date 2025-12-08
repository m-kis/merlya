from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.agent import AgentResponse, MerlyaAgent
from merlya.persistence.models import Conversation


class _StubResult:
    """Simple stub to mimic pydantic_ai Agent run result."""

    def __init__(self, message: str) -> None:
        self.output = AgentResponse(message=message)


@pytest.mark.asyncio
async def test_agent_persists_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent should create and update a conversation with message history."""
    ctx = MagicMock()
    ctx.conversations.create = AsyncMock(side_effect=lambda conv: conv)
    ctx.conversations.update = AsyncMock(return_value=None)

    agent = MerlyaAgent(ctx, model="test:model")
    agent._agent.run = AsyncMock(return_value=_StubResult("Hello back"))  # type: ignore[attr-defined]

    response = await agent.run("hello")

    assert response.message == "Hello back"
    assert agent._active_conversation is not None
    ctx.conversations.create.assert_called_once()
    ctx.conversations.update.assert_called()
    assert len(agent._history) == 2  # user + assistant


@pytest.mark.asyncio
async def test_agent_load_conversation_reuses_history() -> None:
    """Loading a conversation should reuse its history without creating a new one."""
    ctx = MagicMock()
    ctx.conversations.create = AsyncMock()
    ctx.conversations.update = AsyncMock()

    conv = Conversation(title="Existing", messages=[{"role": "user", "content": "hi"}])

    agent = MerlyaAgent(ctx, model="test:model")
    agent.load_conversation(conv)
    agent._agent.run = AsyncMock(return_value=_StubResult("next"))  # type: ignore[attr-defined]

    await agent.run("continue")

    ctx.conversations.create.assert_not_called()
    ctx.conversations.update.assert_called_once()
    assert agent._history[0]["content"] == "hi"
