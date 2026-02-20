import asyncio
from loguru import logger
import sys

# Configure logger for output
logger.remove()
logger.add(sys.stdout, level="DEBUG")

from merlya.core.context import SharedContext
from merlya.agent.main import MerlyaAgent

async def main():
    logger.info("Initializing context...")
    ctx = await SharedContext.create()
    
    # Needs a router mock or init router
    # We can just initialize the router
    from merlya.health import run_startup_checks
    health = await run_startup_checks()
    ctx.health = health
    await ctx.init_router(health.model_tier)

    # Use MerlyaAgent
    agent = MerlyaAgent(context=ctx)
    
    user_input = "liste les fichiers dans le dossier /tmp"
    logger.info(f"Sending prompt: {user_input}")
    
    try:
        # We need the router_result
        route_result = await ctx.router.route(user_input)
        result = await agent.run(user_input, router_result=route_result)
        logger.info(f"Main Response: {result.message}")
    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)
        
if __name__ == "__main__":
    asyncio.run(main())
