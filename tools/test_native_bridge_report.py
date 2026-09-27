"""Bounded display/receipt tests. No native computation."""
import json,tempfile,unittest
from pathlib import Path
import native_bridge_report as r
class ReportTests(unittest.TestCase):
    def test_plot_signed_and_escaped(self):
        s=r.plot({'time_ns':[0,2,4],'q':[0,-1,2]},'q','<charge>')
        self.assertIn('&lt;charge&gt;',s);self.assertIn('-1',s);self.assertIn('4 ns',s)
    def test_nonfinite_trace_rejected(self):
        with self.assertRaisesRegex(ValueError,'Invalid display'):
            r.plot({'time_ns':[0,1],'q':[0,float('nan')]},'q','q')
    def test_namespace_is_part_of_identity(self):
        a={'namespace':'cs137-1m','event_id':1,'group_id':0}
        b=dict(a,namespace='cs10000-v2-diagnostic')
        self.assertNotEqual(r.key(a),r.key(b))
    def test_incomplete_and_overwrite_refused(self):
        with tempfile.TemporaryDirectory(prefix='report-unit-',dir=r.ROOT/'.local/native-bridge-pilot') as d:
            p=Path(d);(p/'run.json').write_text(json.dumps({'status':'running'}))
            with self.assertRaisesRegex(ValueError,'not complete'):r.inspect(p)
            with self.assertRaisesRegex(ValueError,'New report'):r.build(p,p)
if __name__=='__main__':unittest.main(verbosity=2)
