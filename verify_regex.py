import re
import yaml
from pathlib import Path

path = Path("/Users/cedric/athena/athena_ai/commands/builtin/healthcheck.md")
content = path.read_text(encoding="utf-8")

print(f"File content length: {len(content)}")
print(f"First 50 chars: {repr(content[:50])}")

regex = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
match = re.match(regex, content, re.DOTALL)

if match:
    print("Regex MATCHED!")
    yaml_content = match.group(1)
    print(f"YAML content: {repr(yaml_content)}")
    try:
        meta = yaml.safe_load(yaml_content)
        print(f"Parsed YAML: {meta}")
    except Exception as e:
        print(f"YAML Parse Error: {e}")
else:
    print("Regex did NOT match.")
    # Debug why
    if not content.startswith("---"):
        print("Content does not start with '---'")
    
    parts = content.split("---")
    print(f"Split by '---' gives {len(parts)} parts")
