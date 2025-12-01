import unittest
from unittest.mock import MagicMock

import pytest

# Skip module if ansible_runner not installed
pytest.importorskip("ansible_runner", reason="ansible_runner not installed")

from merlya.agents.provisioning import ProvisioningAgent


class TestProvisioningAgent(unittest.TestCase):
    def setUp(self):
        self.context_manager = MagicMock()
        self.agent = ProvisioningAgent(self.context_manager)

        # Mock executors
        self.agent.ansible = MagicMock()
        self.agent.terraform = MagicMock()
        self.agent.llm = MagicMock()

    def test_ansible_execution(self):
        # Mock LLM plan
        self.agent.llm.generate.return_value = '{"tool": "ansible", "playbook": "site.yml"}'
        self.agent.ansible.run_playbook.return_value = {"success": True}

        # Execute with confirm=True
        result = self.agent.run("Deploy site", confirm=True)

        self.agent.ansible.run_playbook.assert_called_with("site.yml")
        self.assertTrue(result["results"]["success"])

    def test_terraform_plan(self):
        # Mock LLM plan
        self.agent.llm.generate.return_value = '{"tool": "terraform", "dir": "./tf", "action": "plan"}'
        self.agent.terraform.plan.return_value = {"success": True, "rc": 2}

        result = self.agent.run("Plan terraform")

        self.agent.terraform.plan.assert_called_with("./tf")
        self.assertTrue(result["results"]["success"])


if __name__ == '__main__':
    unittest.main()
