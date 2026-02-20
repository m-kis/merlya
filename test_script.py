import asyncio
from unittest.mock import AsyncMock, MagicMock
from merlya.router.handler import handle_agent
from merlya.router.classifier import AgentMode, RouterResult

async def main():
    ctx = MagicMock()
    ctx.t = MagicMock(side_effect=lambda key, **_kwargs: key)
    ctx._agent = None  
    
    agent = MagicMock()
    response = MagicMock()
    response.message = "Agent response"
    response.actions_taken = ["action1"]
    response.suggestions = ["suggestion1"]
    agent.run = AsyncMock(return_value=response)
    
    route_result = RouterResult(
        mode=AgentMode.DIAGNOSTIC,
        tools=["core", "system"],
    )

    try:
        res = await handle_agent(ctx, agent, "test input", route_result)
        print("RESULT:")
        print(res)
    except Exception as e:
        print("ERROR:")
        print(e)

asyncio.run(main())
