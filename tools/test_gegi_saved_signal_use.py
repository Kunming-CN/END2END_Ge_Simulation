"""Saved classifications retain identity/nulls and cannot refit or alter energy."""
import gzip
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib

import gegi_saved_signal_use as U
import gegi_saved_reconstruction as S
import gegi_imaging as I
from test_gegi_saved_reconstruction import fixture


def completed_inputs(root, wrong_energy=False):
    campaign = fixture(root)
    seals = {}
    for seal in campaign.glob('chunks/*/*/DONE.json'):
        database = seal.parent/'events.sqlite'
        with closing(sqlite3.connect(database)) as db:
            body, = db.execute('SELECT metadata FROM events').fetchone()
            event = json.loads(zlib.decompress(body))
            event['readout_summary'] = I.readout_summary(event)
            if wrong_energy:
                event['readout_summary']['energy_keV'] = 123.
            body = S.encoded(event)
            db.execute('UPDATE events SET metadata=?,metadata_sha256=?',
                       (zlib.compress(body), U.hashlib.sha256(body).hexdigest()))
            db.commit()
        receipt = S.read(seal)
        receipt['artifacts']['events.sqlite']['sha256'] = S.sha(database)
        S.write(seal, receipt)
        seals[str(receipt['identity']['chunk_index'])] = S.sha(seal)
    complete = S.read(campaign/'COMPLETE.json'); complete['chunks'] = seals
    S.write(campaign/'COMPLETE.json', complete)
    reconstruction = root/'reconstruction'
    S.process(campaign, None, reconstruction)
    return campaign, reconstruction


class SavedSignalUseTests(unittest.TestCase):
    def test_identity_nulls_and_original_bytes_preserved_without_refit(self):
        with tempfile.TemporaryDirectory(dir=S.ROOT/'.local') as folder:
            root = Path(folder); campaign, reconstruction = completed_inputs(root)
            before = {p:S.sha(p) for p in root.rglob('*') if p.is_file()}
            with patch.object(U.R, 'reconstruct_event', side_effect=AssertionError('No fit')):
                result = U.process(campaign, reconstruction, root/'uses')
            self.assertEqual(result['counts']['pulse_groups'], 2)
            self.assertEqual(result['counts']['native_failed_groups'], 2)
            self.assertEqual(result['new_validated_imaging_recoveries'], 0)
            self.assertEqual(result['categories'], {'failed_or_incomplete':2})
            self.assertEqual(before, {p:S.sha(p) for p in before})
            with gzip.open(root/'uses/chunks/000.jsonl.gz', 'rt') as stream:
                row = json.loads(next(stream))
            self.assertEqual(row['original_identity']['raw_primary_id'], 0)
            self.assertIsNone(row['signal_use']['spectroscopy']['energy_keV'])
            with self.assertRaisesRegex(ValueError, 'new derivative'):
                U.process(campaign, reconstruction, root/'uses')

    def test_rehashed_input_energy_change_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory(dir=S.ROOT/'.local') as folder:
            root = Path(folder); campaign, reconstruction = completed_inputs(root, True)
            with self.assertRaisesRegex(ValueError, 'spectroscopy changed'):
                U.process(campaign, reconstruction, root/'uses')
            self.assertFalse((root/'uses/COMPLETE.json').exists())


if __name__ == '__main__':
    unittest.main()
