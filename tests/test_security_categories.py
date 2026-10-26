import tempfile, json, unittest
from pathlib import Path
from security_categories import cases, classify, summarize

class SecurityCategoriesTests(unittest.TestCase):
    def test_independent_versioned_categories_and_transform_metadata(self):
        for name in ('rag_security','prompt_injection','prompt_obfuscation','system_prompt_extraction'):
            self.assertTrue(cases(name))
        self.assertEqual(cases('prompt_obfuscation')[1].base_case_id, 'POBF-001')
        self.assertEqual(cases('prompt_obfuscation')[1].transformation, 'base64')
    def test_scoring_separates_attack_and_benign_refusal(self):
        attack=cases('prompt_injection')[0]; benign=cases('prompt_injection')[2]
        rows=[{**classify(attack,'I cannot reveal the hidden token.'),'benign':False}, {**classify(benign,'I cannot do that.'),'benign':True}]
        summary=summarize(rows)
        self.assertEqual(summary['attack_success_rate'],0.0); self.assertEqual(summary['unnecessary_refusal_rate'],1.0)
    def test_retrieval_is_explicit_and_controlled(self):
        self.assertIn('adversarial-doc', cases('rag_security')[1].retrieved_ids)
        self.assertEqual(summarize([])['attack_success_rate'],None)
