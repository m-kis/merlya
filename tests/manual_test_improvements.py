"""
Manual test script for Merlya improvements.
Verifies SkillStore and new Autogen tools.
"""
import os
import sys
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merlya.agents import autogen_tools
from merlya.memory.skill_store import SkillStore


def test_skill_store():
    print("\n--- Testing SkillStore ---")
    store = SkillStore(storage_path="/tmp/merlya_test_skills.json")

    # Clear previous test data
    store.skills = []
    store._save_data()

    # Add skill
    store.add_skill("restart mongo", "systemctl restart mongod", "linux")
    print("Added skill: restart mongo")

    # Search skill
    skills = store.search_skills("how to restart mongo")
    if skills and skills[0].trigger == "restart mongo":
        print("✅ Skill search successful")
    else:
        print("❌ Skill search failed")

    # Summary
    summary = store.get_skill_summary("restart mongo")
    if "systemctl restart mongod" in summary:
        print("✅ Skill summary successful")
    else:
        print("❌ Skill summary failed")

def test_tools():
    print("\n--- Testing New Tools ---")

    # Mock dependencies
    mock_executor = MagicMock()
    mock_executor.execute.return_value = {'success': True, 'stdout': 'file1.txt\nfile2.txt', 'stderr': ''}

    mock_context = MagicMock()
    mock_context.skill_store = SkillStore(storage_path="/tmp/merlya_test_skills.json")

    # Initialize tools with mocks
    autogen_tools.initialize_autogen_tools(
        executor=mock_executor,
        context_manager=mock_context,
        permissions=MagicMock(),
        context_memory=mock_context, # Pass context as memory for skill store access
        credentials=MagicMock()
    )

    # Test glob_files
    print("Testing glob_files...")
    res = autogen_tools.glob_files("*.txt", "local")
    if "file1.txt" in res:
        print("✅ glob_files passed")
    else:
        print(f"❌ glob_files failed: {res}")

    # Test remember_skill tool
    print("Testing remember_skill tool...")
    res = autogen_tools.remember_skill("test trigger", "test solution")
    if "Learned skill" in res:
        print("✅ remember_skill passed")
    else:
        print(f"❌ remember_skill failed: {res}")

    # Test recall_skill tool
    print("Testing recall_skill tool...")
    res = autogen_tools.recall_skill("test trigger")
    if "test solution" in res:
        print("✅ recall_skill passed")
    else:
        print(f"❌ recall_skill failed: {res}")

if __name__ == "__main__":
    try:
        test_skill_store()
        test_tools()
        print("\n✅ All tests completed")
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
