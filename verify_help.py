import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Add the project root to the python path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

# Mock prompt_toolkit
sys.modules['prompt_toolkit'] = MagicMock()
sys.modules['prompt_toolkit.shortcuts'] = MagicMock()
sys.modules['prompt_toolkit.formatted_text'] = MagicMock()
sys.modules['prompt_toolkit.styles'] = MagicMock()
sys.modules['prompt_toolkit.auto_suggest'] = MagicMock()
sys.modules['prompt_toolkit.history'] = MagicMock()

# Mock rich
sys.modules['rich'] = MagicMock()
sys.modules['rich.console'] = MagicMock()
sys.modules['rich.markdown'] = MagicMock()
sys.modules['rich.panel'] = MagicMock()
sys.modules['rich.table'] = MagicMock()

# Mock athena_ai.repl.core to avoid importing it
sys.modules['athena_ai.repl.core'] = MagicMock()

try:
    # Now we can import help handler
    from athena_ai.repl.commands.help import HelpCommandHandler
    from athena_ai.commands.loader import get_command_loader
    
    # Mock REPL object
    class MockREPL:
        def __init__(self):
            self.command_loader = get_command_loader()
            self.logger = MagicMock()
            
    repl = MockREPL()
    help_handler = HelpCommandHandler(repl)
    
    print("--- Testing _custom_commands_section ---")
    section = help_handler._custom_commands_section()
    print(f"Section content:\n'{section}'")
    
    if "healthcheck" in section:
        print("\nSUCCESS: 'healthcheck' found in help section.")
    else:
        print("\nFAILURE: 'healthcheck' NOT found in help section.")
        
    # Also verify loader directly again
    print("\n--- Verify Loader Direct ---")
    commands = repl.command_loader.list_commands()
    print(f"Loader has {len(commands)} commands: {list(commands.keys())}")
    
    # Check if the file actually exists
    builtin_dir = Path(project_root) / "athena_ai" / "commands" / "builtin"
    print(f"\nChecking builtin dir: {builtin_dir}")
    if builtin_dir.exists():
        print(f"Builtin dir exists. Contents: {[f.name for f in builtin_dir.glob('*.md')]}")
    else:
        print("Builtin dir DOES NOT exist.")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
