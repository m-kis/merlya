"""
Verify REPL refactoring by initializing AthenaREPL.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from athena_ai.repl import AthenaREPL
    print("✅ Successfully imported AthenaREPL from package")

    # Try to initialize (mocking env to avoid full startup cost/side effects if possible,
    # but here we just want to see if classes load and link)
    repl = AthenaREPL(env="test")
    print("✅ Successfully initialized AthenaREPL")

    # Check if components are linked
    if repl.command_handler:
        print("✅ CommandHandler linked")

    if repl.orchestrator:
        print("✅ Orchestrator linked")

except Exception as e:
    print(f"❌ Failed to initialize REPL: {e}")
    sys.exit(1)
