import unittest

from merlya.security.risk_assessor import RiskAssessor


class TestRiskAssessor(unittest.TestCase):
    def setUp(self):
        self.assessor = RiskAssessor()

    def test_low_risk(self):
        risk = self.assessor.assess("ls -la")
        self.assertEqual(risk["level"], "low")

    def test_critical_risk(self):
        risk = self.assessor.assess("rm -rf /")
        self.assertEqual(risk["level"], "critical")

    def test_confirmation_required(self):
        self.assertTrue(self.assessor.requires_confirmation("critical"))
        self.assertFalse(self.assessor.requires_confirmation("low"))

if __name__ == '__main__':
    unittest.main()
