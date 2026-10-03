"""Read-only teaching source and focused template checks; never exports."""
import unittest
import pipeline_demo as P
import saved_focus_pages as F
import gamma_showcase as S

class TeachingFocusTests(unittest.TestCase):
    def test_checked_original_data_and_offline_renderer(self):
        source=P.ROOT/'.local/pipeline-showcase'
        original=(source/'data.json').read_bytes();data=P.validate_export(source)
        html=F.render(data).decode('utf-8')
        self.assertEqual(original,(source/'data.json').read_bytes())
        self.assertNotIn('__FOCUSED_PLOTS_JS__',html)
        self.assertIn('SavedFocusPlots',html);self.assertIn('Full saved window',html)
        self.assertNotIn('src="http',html)
        S.exact(S.decode(original),data,'Every original teaching value')

if __name__=='__main__':unittest.main()
