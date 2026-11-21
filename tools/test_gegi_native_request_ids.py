"""Explicit request flag only; no field/cache or physics calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gegi_mixed_acquisition as M


class NativeRequestIDs(unittest.TestCase):
    def test_stream_flag_is_only_request_difference_and_keeps_nominal_count(self):
        with tempfile.TemporaryDirectory(dir=M.ROOT/'.local') as folder:
            root=Path(folder)
            for name in ('legacy','stream','finite'):(root/name).mkdir()
            with patch.object(M,'field_cache',return_value={'sha256':'same-fields'}), \
                 patch.object(M,'file_sha',return_value='f'*64):
                ordinary=M.native_request(root/'legacy',1110000,response_mode='native_signals_only_v1')
                streamed=M.native_request(root/'stream',1110000,response_mode='native_signals_only_v1',
                                          event_id_policy=M.STREAMING_EVENT_ID_POLICY)
                finite=M.native_request(root/'finite',1110000,event_id_policy='finite_primary_count_v1')
            old=json.loads(ordinary.read_bytes());new=json.loads(streamed.read_bytes())
            self.assertNotIn('event_id_policy',old)
            self.assertEqual(new.pop('event_id_policy'),'streaming_transport_driver_v1')
            self.assertEqual(new,old)
            self.assertEqual(new['selection']['primary_count'],1110000)
            self.assertEqual(json.loads(finite.read_bytes())['event_id_policy'],'finite_primary_count_v1')

    def test_unknown_policy_rejected_before_cache_access_or_output(self):
        with tempfile.TemporaryDirectory(dir=M.ROOT/'.local') as folder:
            with patch.object(M,'field_cache') as cache:
                for policy in ('unknown',True,42):
                    with self.subTest(policy=policy),self.assertRaisesRegex(ValueError,'event ID policy'):
                        M.native_request(Path(folder),1110000,event_id_policy=policy)
                cache.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_fresh_count_has_no_500_ceiling_and_still_rejects_invalid_counts(self):
        class ReachedRequest(Exception):pass
        with tempfile.TemporaryDirectory(dir=M.ROOT/'.local') as folder:
            root=Path(folder)
            for count in (0,-1,1.5,True):
                with self.subTest(count=count),self.assertRaisesRegex(ValueError,'positive integer'):
                    M.run(root/'invalid',primary_count=count)
            with patch.object(M,'native_request',side_effect=ReachedRequest) as request:
                with self.assertRaises(ReachedRequest):M.run(root/'accepted',primary_count=20000000)
                request.assert_called_once_with(root/'accepted',20000000)


if __name__=='__main__':unittest.main()
