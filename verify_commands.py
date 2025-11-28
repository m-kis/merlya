import sys
import os
from pathlib import Path

# Add the project root to the python path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

try:
    from athena_ai.commands.loader import get_command_loader
    
    loader = get_command_loader()
    commands = loader.list_commands()
    
    print(f"Loaded {len(commands)} commands:")
    for name, desc in commands.items():
        print(f" - /{name}: {desc}")
        
    if "healthcheck" in commands:
        print("\nSUCCESS: 'healthcheck' command is loaded.")
    else:
        print("\nFAILURE: 'healthcheck' command is NOT loaded.")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
