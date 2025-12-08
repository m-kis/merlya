from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from merlya.agent import AgentResponse, MerlyaAgent
from merlya.persistence.models import Conversation


def _make_messages(user_text: str, assistant_text: str) -> list[ModelMessage]:
    """Create a list of ModelMessage for testing."""
    return [
        ModelRequest(parts=[UserPromptPart(content=user_text)]),
        ModelResponse(parts=[TextPart(content=assistant_text)]),
    ]


class _StubResult:
    """Simple stub to mimic pydantic_ai Agent run result."""

    def __init__(self, message: str, user_text: str = "hello") -> None:
        self.output = AgentResponse(message=message)
        self._user_text = user_text
        self._assistant_text = message

    def all_messages(self) -> list[ModelMessage]:
        """Return mock message history including tool calls."""
        return _make_messages(self._user_text, self._assistant_text)


@pytest.mark.asyncio
async def test_agent_persists_conversation() -> None:
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
    # Now using ModelMessage format - should have request + response
    assert len(agent._message_history) == 2


@pytest.mark.asyncio
async def test_agent_load_conversation_reuses_history() -> None:
    """Loading a conversation should reuse its history without creating a new one."""
    from pydantic_ai import ModelMessagesTypeAdapter

    ctx = MagicMock()
    ctx.conversations.create = AsyncMock()
    ctx.conversations.update = AsyncMock()

    # Create messages in the new format (serialized)
    original_messages = _make_messages("hi", "hello there")
    serialized = ModelMessagesTypeAdapter.dump_python(original_messages, mode="json")

    conv = Conversation(title="Existing", messages=serialized)

    agent = MerlyaAgent(ctx, model="test:model")
    agent.load_conversation(conv)

    # Verify conversation was loaded correctly
    assert agent._active_conversation is conv
    assert len(agent._message_history) == 2

    # Verify first message content
    first_msg = agent._message_history[0]
    assert isinstance(first_msg, ModelRequest)
    assert isinstance(first_msg.parts[0], UserPromptPart)
    assert first_msg.parts[0].content == "hi"

    # Now run a new message - stub returns all messages (history + new)
    all_msgs = original_messages + _make_messages("continue", "next")

    class _StubResultWithHistory:
        output = AgentResponse(message="next")

        def all_messages(self) -> list[ModelMessage]:
            return all_msgs

    agent._agent.run = AsyncMock(return_value=_StubResultWithHistory())  # type: ignore[attr-defined]

    await agent.run("continue")

    # Should not create a new conversation
    ctx.conversations.create.assert_not_called()
    ctx.conversations.update.assert_called_once()

    # History should now have 4 messages (original 2 + new 2)
    assert len(agent._message_history) == 4


@pytest.mark.asyncio
async def test_agent_clear_history() -> None:
    """Clearing history should reset message history and conversation."""
    ctx = MagicMock()
    ctx.conversations.create = AsyncMock(side_effect=lambda conv: conv)
    ctx.conversations.update = AsyncMock(return_value=None)

    agent = MerlyaAgent(ctx, model="test:model")
    agent._agent.run = AsyncMock(return_value=_StubResult("Hello"))  # type: ignore[attr-defined]

    await agent.run("hello")
    assert len(agent._message_history) == 2

    agent.clear_history()

    assert len(agent._message_history) == 0
    assert agent._active_conversation is None
