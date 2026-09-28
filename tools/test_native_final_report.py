import csv,gzip,json,unittest
from pathlib import Path
import native_final_report as R
ROOT=R.ROOT; OUT=ROOT/'.local/native-final-report-v2'
class FinalReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete=R.read(OUT/'COMPLETE.json'); cls.summary=R.read(OUT/'summary.json')
    def test_complete_inventory_and_hashes(self):
        self.assertEqual(self.complete['status'],'verified_native_response_report')
        actual={p.name for p in OUT.iterdir() if p.is_file() and not p.name.startswith('check-') and p.name!='check.mjs'}
        self.assertEqual(actual,set(self.complete['files'])|{'COMPLETE.json'})
        for name,e in self.complete['files'].items():
            p=OUT/name; self.assertEqual(R.sha(p),e['sha256']); self.assertEqual(p.stat().st_size,e['bytes'])
    def test_group_join_is_complete_unique(self):
        seen=set(); count=0
        with gzip.open(OUT/'groups.csv.gz','rt',encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                key=(row['model'],int(row['event_id']),int(row['group_id']))
                self.assertNotIn(key,seen);seen.add(key);count+=1
        self.assertEqual(count,23693); self.assertEqual(len(seen),23693)
    def test_response_partitions(self):
        expected={'AK02':(12420,127,1536,10757),'SAP22':(11273,281,77,10915)}
        for m,(groups,failed,rejected,accepted) in expected.items():
            s=self.summary['models'][m]['response']
            self.assertEqual((s['groups'],s['native_failed'],s['readout_rejected'],s['accepted']),
                             (groups,failed,rejected,accepted))
            self.assertEqual(groups,failed+rejected+accepted)
        self.assertEqual(self.summary['totals']['accepted'],21672)
        self.assertEqual(self.summary['totals']['native_failed'],408)
    def test_failure_taxonomy(self):
        self.assertEqual(self.summary['models']['AK02']['response']['failure_classes'],{'boundary_stall':127})
        self.assertEqual(self.summary['models']['SAP22']['response']['failure_classes'],
                         {'boundary_stall':276,'input_domain_compatibility':5})
        self.assertEqual(self.summary['models']['AK02']['response']['rejection_reasons'],{'below_threshold':1536})
        self.assertEqual(self.summary['models']['SAP22']['response']['rejection_reasons'],{'below_threshold':77})
    def test_line_full_accounting(self):
        a=self.summary['models']['AK02']['line_full']; s=self.summary['models']['SAP22']['line_full']
        self.assertEqual((a['truth_groups'],a['native_failed'],a['readout_rejected'],a['accepted']),(806,2,0,804))
        self.assertEqual((s['truth_groups'],s['native_failed'],s['readout_rejected'],s['accepted']),(531,6,0,525))
        self.assertEqual(a['accepted_reco_650_670'],630)
        self.assertEqual(s['accepted_reco_650_670'],514)
    def test_histogram_census(self):
        h=R.read(OUT/'histograms.json'); csv_counts={}
        with (OUT/'histograms.csv').open(encoding='utf-8',newline='') as f:
            for row in csv.DictReader(f):
                key=(row['model'],row['stage']);csv_counts[key]=csv_counts.get(key,0)+int(row['count'])
        for m in R.MODELS:
            s=self.summary['models'][m]['response']
            self.assertEqual(h[m]['deposited_truth']['total'],s['groups'])
            self.assertEqual(h[m]['native_induced']['total'],s['native_completed'])
            self.assertEqual(h[m]['reconstructed_accepted']['total'],s['accepted'])
            for stage in h[m]:self.assertEqual(csv_counts[(m,stage)],h[m][stage]['total'])
            self.assertGreaterEqual(h[m]['native_induced']['underflow'],1)
if __name__=='__main__':unittest.main(verbosity=2)
