import pexpect
import sys

print("Starting Merlya REPL...")
child = pexpect.spawn("uv run merlya", encoding="utf-8", timeout=30)
child.logfile = sys.stdout

try:
    child.expect("Merlya >")
    print("Found prompt! Sending command...")
    child.sendline("liste les fichiers dans /tmp")
    
    # Wait for the response showing it hit Agent
    child.expect("Merlya >")
    print("\nSUCCESS: Command processed!")
    
    child.sendline("/exit")
    child.expect(pexpect.EOF)
except Exception as e:
    print(f"\nERROR: {e}")
    sys.exit(1)
