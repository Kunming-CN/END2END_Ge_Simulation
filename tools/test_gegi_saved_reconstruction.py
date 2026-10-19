"""Saved-data ownership, stop/resume and null census contracts. No physics."""
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib
import gegi_saved_reconstruction as G


def fixture(root):
    campaign=root/'campaign';campaign.mkdir();seals={}
    for i in range(2):
        folder=campaign/'chunks'/'fixture'/f'b{i:03d}';folder.mkdir(parents=True)
        event={'event_id':i,'group_id':0,'status':'native_failed','channels':None,'native_signals':None,
               'campaign_initial_offset':i*100,'source_group':'fixture',
               'reconstruction':{'status':'rejected','reason':'native_failed'},'readout_summary':None}
        body=G.encoded(event)
        db=sqlite3.connect(folder/'events.sqlite')
        db.execute('CREATE TABLE events(primary_id INTEGER,group_id INTEGER,metadata BLOB,metadata_sha256 TEXT)')
        db.execute('INSERT INTO events VALUES(?,?,?,?)',(i,0,zlib.compress(body),hashlib.sha256(body).hexdigest()))
        db.commit();db.close()
        G.write(folder/'DONE.json',{'identity':{'chunk_index':i},'artifacts':{'events.sqlite':{'sha256':G.sha(folder/'events.sqlite')}},
                                  'response':{'readout_recipe':{'channels':[]}}})
        seals[str(i)]=G.sha(folder/'DONE.json')
    G.write(campaign/'COMPLETE.json',{'status':'completed_with_native_failures','chunks':seals,
                                      'groups':{'fixture':{'pulse_groups':2,'initial_primaries':200}}})
    return campaign


class SavedTests(unittest.TestCase):
    def test_incompatible_calibration_is_rejected_before_output_or_fit(self):
        with tempfile.TemporaryDirectory(dir=G.ROOT/'.local') as d:
            root=Path(d);campaign=fixture(root);output=root/'derivative'
            with patch.object(G.A,'campaign',side_effect=ValueError('incompatible calibration')) as admission, \
                 patch.object(G.R,'TemplateBank') as bank:
                with self.assertRaisesRegex(ValueError,'incompatible calibration'):
                    G.process(campaign,root/'other-bank',output)
            admission.assert_called_once();bank.assert_not_called();self.assertFalse(output.exists())

    def test_stop_resume_keeps_failed_null_and_original_bytes(self):
        with tempfile.TemporaryDirectory(dir=G.ROOT/'.local') as d:
            root=Path(d);campaign=fixture(root);output=root/'derivative'
            originals={p:G.sha(p) for p in campaign.rglob('*') if p.is_file()}
            realwrite=G.write
            def write(path,value):
                realwrite(path,value)
                if Path(path).name=='progress.json' and value.get('chunks')==1:
                    (output/'stop.request').write_text('user requested')
            with patch.object(G,'write',side_effect=write):
                result=G.process(campaign,None,output)
            self.assertEqual(result['status'],'stopped_saved_reconstruction')
            self.assertFalse((output/'COMPLETE.json').exists())
            chunkhash=G.sha(output/'chunks/000.jsonl.gz')
            result=G.process(campaign,None,output,resume=True)
            self.assertEqual(result['counts']['pulse_groups'],2)
            self.assertEqual(result['counts']['native_failed_groups'],2)
            self.assertEqual(result['counts']['validated_recovered_groups'],0)
            self.assertEqual(G.sha(output/'chunks/000.jsonl.gz'),chunkhash)
            self.assertEqual({p:G.sha(p) for p in originals},originals)
            with gzip.open(output/'chunks/000.jsonl.gz','rt') as stream: row=json.loads(next(stream))
            self.assertIsNone(row['reconstruction']['energy_keV'])
            self.assertEqual(row['reconstruction']['candidates'],[])
            with self.assertRaisesRegex(ValueError,'already complete'):
                G.process(campaign,None,output,resume=True)

    def test_changed_chunk_seal_rejected(self):
        with tempfile.TemporaryDirectory(dir=G.ROOT/'.local') as d:
            campaign=fixture(Path(d))
            path=next(campaign.rglob('DONE.json'));path.write_bytes(path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'seal differs'):
                G.process(campaign,None,Path(d)/'derivative')

    def test_output_cannot_overlap_original(self):
        with tempfile.TemporaryDirectory(dir=G.ROOT/'.local') as d:
            campaign=fixture(Path(d))
            with self.assertRaisesRegex(ValueError,'outside immutable'):
                G.process(campaign,None,campaign/'output')


if __name__=='__main__':unittest.main()
