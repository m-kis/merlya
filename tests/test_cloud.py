import unittest
from unittest.mock import MagicMock, patch
from athena_ai.agents.cloud import CloudAgent

class TestCloudAgent(unittest.TestCase):
    def setUp(self):
        self.context_manager = MagicMock()
        self.agent = CloudAgent(self.context_manager)
        
        # Mock executors
        self.agent.aws = MagicMock()
        self.agent.k8s = MagicMock()
        self.agent.llm = MagicMock()

    def test_aws_list_instances(self):
        # Mock LLM plan
        self.agent.llm.generate.return_value = '{"provider": "aws", "action": "list_instances"}'
        self.agent.aws.list_instances.return_value = {"success": True, "instances": []}
        
        result = self.agent.run("List AWS instances")
        
        self.agent.aws.list_instances.assert_called_once()
        self.assertTrue(result["results"]["success"])

    def test_k8s_list_pods(self):
        # Mock LLM plan
        self.agent.llm.generate.return_value = '{"provider": "k8s", "action": "list_pods", "namespace": "default"}'
        self.agent.k8s.list_pods.return_value = {"success": True, "pods": []}
        
        result = self.agent.run("List pods")
        
        self.agent.k8s.list_pods.assert_called_with("default")
        self.assertTrue(result["results"]["success"])

if __name__ == '__main__':
    unittest.main()
