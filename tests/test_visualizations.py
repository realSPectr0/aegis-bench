import importlib.util, json, tempfile, unittest
from pathlib import Path
import numpy as np
from tools.visualize_benchmark import aggregate, load_report
from tools.visualize_model_weights import inspect

class VisualizationTests(unittest.TestCase):
    def test_load_security_and_legacy_reports(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); modern=root/'modern.json'; legacy=root/'legacy.json'
            modern.write_text(json.dumps({'schema_version':'security-category-2','model':'m','category':'prompt_injection','results':[{'case_id':'x','attack_type':'direct','status':'ok','attack_success':False,'task_correct':True,'latency_seconds':1}]}))
            legacy.write_text(json.dumps({'target_model':'old','benchmark_part':'local_and_agent_safety','results':[{'id':'INJECT-1','category':'agent_safety','status':'solved','solved':True,'total_seconds':2}]}))
            rows=load_report(modern)+load_report(legacy); self.assertEqual(len(rows),2)
            self.assertTrue(any(r['metric']=='task_correctness' and r['value']==1 for r in aggregate(rows)))
    def test_malformed_empty_and_missing_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.json'; p.write_text('{')
            with self.assertRaisesRegex(ValueError,'malformed JSON'): load_report(p)
            p.write_text(json.dumps({'results':[]}))
            with self.assertRaisesRegex(ValueError,'no supported rows'): load_report(p)
        rows=[{'label':'m','category':'c','attack_type':'a','infrastructure_error':True,'latency_seconds':None,'attack_success':None,'task_correct':None,'unnecessary_refusal':None}]
        latency=[r for r in aggregate(rows) if r['metric']=='latency'][0]; self.assertIsNone(latency['value']); self.assertEqual(latency['n'],0)
    def test_npz_weight_measurements(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weights.npz'; np.savez(p,layer=np.array([1.,2.,3.]))
            rows=inspect([p],2); self.assertEqual(rows[0]['tensor'],'layer'); self.assertEqual(rows[0]['elements'],3); self.assertEqual(rows[0]['sampled'],2)
    def test_unsupported_weight_format_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'weights.gguf'; p.write_bytes(b'GGUF')
            with self.assertRaisesRegex(ValueError,'unsupported weight format'): inspect([p])
    @unittest.skipUnless(importlib.util.find_spec('matplotlib'),'matplotlib not installed')
    def test_plot_dependency_available(self):
        import matplotlib
        self.assertTrue(matplotlib.__version__)
