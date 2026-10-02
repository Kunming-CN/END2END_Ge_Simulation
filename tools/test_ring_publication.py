"""Focused synthetic saved-data checks; no physics, electronics or export run."""
import copy
from collections import Counter
from pathlib import Path
import tempfile
import unittest

import ring_publication as publication


class SavedSerialization(unittest.TestCase):
    def test_binary64_signed_zero_and_large_integer_roundtrip(self):
        value = {"zero": -0.0, "subnormal": 5e-324, "next_one": 1.0000000000000002,
                 "raw_row_index": 9007199254740993, "unknown": None, "nested": [False, -0.0]}
        self.assertTrue(publication.exact(value, publication.read_json_bytes(publication.encoded(value))))
        self.assertFalse(publication.exact(value, {**value, "zero": 0.0}))
        self.assertFalse(publication.exact(0, 0.0))
        self.assertFalse(publication.exact(False, 0))
        self.assertTrue(publication.exact(publication.read_json_bytes(b'{"geometry_zero":-0}')['geometry_zero'], -0.0))
        with self.assertRaises(ValueError):
            publication.read_json_bytes(b'{"energy":NaN}')

    def test_metadata_redaction_preserves_scientific_numbers_without_leaking_paths(self):
        source = {"effective_model_ref": ".local/ring-cs137-v1/production10000/GeRC02/transport/effective-model/GeRC02.yaml",
                  "executable": "C:/Users/owner/native/julia.exe", "source_sha256": {".local/private/input.tg": "a" * 64},
                  "native_final_charge_keV": -0.0, "contact_potentials_V": {"1": 0, "2": -370}, "model_id": "KMRC01_candidate"}
        before = copy.deepcopy(source)
        public, redactions = publication.sanitized_metadata(source)
        self.assertTrue(publication.exact(before, source))
        self.assertTrue(publication.exact(public["native_final_charge_keV"], source["native_final_charge_keV"]))
        self.assertEqual(public["contact_potentials_V"], source["contact_potentials_V"])
        self.assertEqual(len(redactions), 3)
        publication.public_safe(publication.encoded(public), "metadata")
        self.assertNotIn(b"owner", publication.encoded(redactions))
        with self.assertRaises(ValueError):
            publication.public_safe(publication.encoded(source), "raw scientific ledger")
        with self.assertRaises(ValueError):
            publication.sanitized_metadata({"token": "ghp_" + "a" * 30})

    def test_additive_native_inspector_changes_only_allowed_roots(self):
        original = (publication.ROOT / "tools/geant4_scene/scene.cc").read_bytes()
        expected = original.replace(b".local/peak-native-delivery/cs10000-v2", b".local/ring-cs137-v1").replace(
            b".local/geometry-events-publication/build", b".local/ring-publication-v1/build")
        self.assertEqual((publication.ROOT / "tools/ring_scene.cc").read_bytes(), expected)
        self.assertIn(b"G4VERSION_NUMBER==1132", expected)
        self.assertNotIn(b"G4RunManager", expected)


class FullPrimaryCensus(unittest.TestCase):
    def fixture(self, folder):
        totals = Counter(); chunks = []; event_rows = []
        for eid in range(10000):
            def row(table, **fields):
                record = {"raw_row_index": totals[table], "evtid": eid, **fields}
                totals[table] += 1
                return record
            tables = {
                "vtx": [row("vtx", time=0.0, xloc=0.0, yloc=0.037073, zloc=0.00029)],
                "particles": [row("particles", particle=1000551370, px=-0.0)],
                "tracks": [row("tracks", trackid=1, parent_trackid=0, particle=1000551370,
                               procid=-1, ekin=0.0, time=0.0, xloc=0.0, yloc=0.037073, zloc=0.00029)],
                "stp/germanium": [],
            }
            if eid == 7:
                tables["tracks"].append(row("tracks", trackid=2, parent_trackid=1, particle=22,
                                            procid=1, ekin=0.0005, time=3.0, xloc=-0.0, yloc=0.0, zloc=0.0))
                tables["stp/germanium"].append(row("stp/germanium", trackid=2, parent_trackid=1,
                                                    particle=22, edep=0.25, time=4.0,
                                                    xloc=-0.0, yloc=0.0, zloc=0.0))
            event_rows.append({"event_id": eid, "tables": tables})
            if len(event_rows) == 100:
                first = eid - 99; name = f"events-{first:05d}.json"
                (folder / name).write_bytes(publication.encoded({"model": "GeRC02", "first": first, "events": event_rows}))
                chunks.append({"file": name, "first": first, "count": 100, "sha256": publication.digest(folder / name)})
                event_rows = []
        sample = publication.read(folder / "events-00000.json")["events"][7]["tables"]
        schemas = {table: {k: {} for k in rows[0] if k != "raw_row_index"} for table, rows in sample.items()}
        index = {"event_count": 10000, "chunks": chunks, "raw_columns": schemas, "raw_rows": dict(totals),
                 "ge_hit_ids": [7], "zero_ge_primaries": 9999,
                 "processes": [{"procid": 1, "name": "RadioactiveDecay"}]}
        meta = {"model_id": "GeRC02", "primary_count": 10000, "grouping_policy": {"horizon_ns": 100000}}
        return meta, index

    def test_full_census_and_rehashed_identity_mutation(self):
        publication.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="synthetic-test-", dir=publication.WORK) as name:
            folder = Path(name)
            meta, index = self.fixture(folder)
            value = publication.selected_payload(folder, meta, index)
            self.assertEqual(value["event_ids"], [7])
            self.assertEqual(value["evidence"][0]["groups"][0]["relative_delays_ns"], [0.0])
            import hit_event_view as hits
            raw = hits.unpack(value["events"][0], value["columns"])
            self.assertTrue(publication.exact(raw["tables"]["stp/germanium"][0]["xloc"], -0.0))
            self.assertTrue(publication.exact(publication.read_json_bytes(publication.encoded(value)), value))
            with self.assertRaises(ValueError):
                publication.selected_payload(folder, {**meta, "primary_count": 500}, index)
            bad = publication.read(folder / "events-00000.json")
            bad["events"][4]["event_id"] = 5
            (folder / "events-00000.json").write_bytes(publication.encoded(bad))
            index["chunks"][0]["sha256"] = publication.digest(folder / "events-00000.json")
            with self.assertRaises(ValueError):
                publication.selected_payload(folder, meta, index)


class SavedRawCache(unittest.TestCase):
    def test_exact_cache_copy_and_changed_source_or_rehashed_chunk_identity_refused(self):
        from unittest.mock import patch
        import tempfile
        R = publication
        with tempfile.TemporaryDirectory(dir=R.ROOT / '.local') as temporary:
            base = Path(temporary); work = base / 'work'; cache = work / 'build/raw/GeRC02'
            cache.mkdir(parents=True); source = base / 'model/transport'; source.mkdir(parents=True)
            (source / 'prepared.json').write_text('{}\n'); freeze = work / 'freeze.json'; freeze.write_text('{}\n')
            chunks = []
            for number in range(100):
                name = f'events-{number*100:05d}.json'; (cache / name).write_bytes(b'{"value":-0.0}\n')
                chunks.append({'file': name, 'first': number*100, 'count': 100, 'sha256': R.digest(cache / name)})
            index = {'event_count': 10000, 'chunks': chunks}
            R.write_json(cache / 'index.json', index, public=False)
            R.write_json(cache / 'runtime.json', {'python': 'existing'}, public=False)
            record = {'kind': 'ring_saved_raw_export_v1', 'status': 'complete', 'model': 'GeRC02',
                      'exit_code': 0, 'radiation_calls': 0, 'native_calls': 0,
                      'source_freeze_sha256': R.digest(freeze), 'raw_reader_sha256': R.digest(R.ROOT / 'tools/geometry_events.py'),
                      'source_lh5_sha256': 'a'*64, 'prepared_sha256': R.digest(source / 'prepared.json'),
                      'index': R.artifact_info(cache / 'index.json')}
            R.write_json(cache / 'COMPLETE.json', record, public=False)
            context = {'model': 'GeRC02', 'modeldir': source.parent, 'transport': {'source_lh5_sha256': 'a'*64}}
            with patch.object(R, 'WORK', work), patch.object(R, 'FROZEN', freeze):
                out = base / 'copy'; out.mkdir(); result = R.saved_raw(context, out)
                self.assertEqual(result, index); self.assertEqual(len(list(out.iterdir())), 100)
                self.assertEqual((out / chunks[0]['file']).read_bytes(), b'{"value":-0.0}\n')
                wrong = {**context, 'transport': {'source_lh5_sha256': 'b'*64}}
                with self.assertRaisesRegex(ValueError, 'source binding'):
                    R.saved_raw(wrong, out)
                index['chunks'][1]['first'] = 0; (cache / 'index.json').write_bytes(R.encoded(index))
                record['index'] = R.artifact_info(cache / 'index.json'); (cache / 'COMPLETE.json').write_bytes(R.encoded(record))
                malformed = base / 'malformed'; malformed.mkdir()
                with self.assertRaisesRegex(ValueError, 'chunk identity'):
                    R.saved_raw(context, malformed)


class ZeroEnergyNativeLedger(unittest.TestCase):
    def test_zero_deposit_raw_rows_are_preserved_and_not_pulse_groups(self):
        from unittest.mock import patch
        R = publication
        with tempfile.TemporaryDirectory(dir=R.ROOT / '.local') as temporary:
            folder = Path(temporary)
            raw = {'raw_row_index': 0, 'edep': -0.0, 'time': 0.062, 'evtid': 7}
            tables = {'vtx': [], 'particles': [], 'tracks': [], 'stp/germanium': [raw]}
            R.write_json(folder / 'events.json', {'events': [{'event_id': 7, 'tables': tables}]}, public=False)
            decay = {'event_id': 7, 'vtx': [], 'particles': [], 'tracks': [],
                     'pulse_groups': [], 'steps': [{'raw': copy.deepcopy(raw), 'raw_row_index': 0, 'energy_keV': -0.0}]}
            scalar = {'record_kind': 'decay', 'event_id': 7, 'pulse_count': 0}
            context = {'modeldir': folder, 'derivative': None, 'current': {'counts': {'groups': 0}}}
            index = {'chunks': [{'file': 'events.json', 'sha256': R.digest(folder / 'events.json')}]}
            def check(record):
                with patch.object(R, 'records', side_effect=lambda p: iter([record if p.name == 'truth.jsonl' else scalar])):
                    return R.joined_groups(context, folder, index, {'evidence': []})
            self.assertEqual(check(decay), [])
            missing = copy.deepcopy(decay); missing['steps'] = []
            with self.assertRaisesRegex(ValueError, 'raw Ge row'):
                check(missing)
            lost_sign = copy.deepcopy(decay); lost_sign['steps'][0]['raw']['edep'] = 0.0
            with self.assertRaisesRegex(ValueError, 'raw Ge row'):
                check(lost_sign)
            false_positive = copy.deepcopy(decay); false_positive['steps'][0]['energy_keV'] = 1e-9
            with self.assertRaisesRegex(ValueError, 'Positive deposition'):
                check(false_positive)


class NativeFailureAndSignedHistograms(unittest.TestCase):
    def test_raw_negative_charge_and_unknown_failure_populations(self):
        eion = 2.95; one_keV = 1000 / eion * 1.602176634e-19
        scalars = [
            {"record_kind": "decay", "deposited_energy_keV": 0.0},
            {"record_kind": "decay", "deposited_energy_keV": 4.5},
            {"record_kind": "pulse", "deposited_energy_keV": 4.0, "final_induced_keV": -3.0,
             "readout": {"final_charge_C": 3.0 * one_keV, "preamp_peak_charge_equivalent_keV": 3.0,
                         "analog_energy_keV": 3.0, "reconstructed_energy_keV": 3.25}},
            {"record_kind": "pulse", "deposited_energy_keV": 0.5, "final_induced_keV": None, "readout": None},
        ]
        counts = {"initial_primaries": 2, "initial_decays": 2, "groups": 2, "native_failed_groups": 1,
                  "accepted": 1, "line_photons": 1}
        h = publication.histogram(scalars, counts, eion)
        stages = {stage: [row for row in h["bins"] if row["stage"] == stage] for stage in publication.STAGES}
        self.assertEqual(sum(r["count"] for r in stages["deposited_per_decay"]), 2)
        self.assertEqual(sum(r["count"] for r in stages["deposited_per_group"]), 2)
        self.assertEqual(sum(r["count"] for r in stages["native_terminal_charge"]), 1)
        self.assertEqual(stages["native_terminal_charge"][0]["bin"], 199)
        self.assertEqual(stages["accepted_peak_ADC"][0]["count"], 1)
        with self.assertRaises(ValueError):
            publication.histogram(scalars, {**counts, "native_failed_groups": 0}, eion)


class LosslessWebDelivery(unittest.TestCase):
    def test_all_100_gzip_chunks_preserve_census_sign_and_reject_rehashed_identity(self):
        import gzip
        publication.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='web-test-', dir=publication.WORK) as temporary:
            folder = Path(temporary)
            meta, index = FullPrimaryCensus().fixture(folder)
            expected = publication.selected_payload(folder, meta, index)
            for chunk in index['chunks']:
                old = folder / chunk['file']; body = old.read_bytes()
                zipped = gzip.compress(body, compresslevel=9, mtime=0)
                self.assertEqual(zipped, gzip.compress(body, compresslevel=9, mtime=0))
                self.assertEqual(gzip.decompress(zipped), body)
                old.unlink(); chunk.update({'file': chunk['file'] + '.gz', **publication.byte_info(zipped),
                    'encoding': 'gzip', 'gzip_mtime': 0, 'uncompressed_sha256': publication.byte_info(body)['sha256'],
                    'uncompressed_bytes': len(body)})
                (folder / chunk['file']).write_bytes(zipped)
            self.assertTrue(publication.exact(publication.selected_payload(folder, meta, index), expected))
            chunk = index['chunks'][0]; original = copy.deepcopy(chunk)
            original_body = (folder / chunk['file']).read_bytes()
            wrong_sign = gzip.decompress(original_body).replace(b'"px":-0.0', b'"px":0.0', 1)
            zipped = gzip.compress(wrong_sign, mtime=0)
            (folder / chunk['file']).write_bytes(zipped); chunk.update(publication.byte_info(zipped))
            with self.assertRaisesRegex(ValueError, 'Raw gzip content'):
                publication.checked_chunk(folder, chunk)
            chunk.update(original); (folder / chunk['file']).write_bytes(original_body)
            wrong_id = publication.checked_chunk(folder, chunk)
            wrong_id['events'][4]['event_id'] = 5
            body = publication.encoded(wrong_id); zipped = gzip.compress(body, mtime=0)
            (folder / chunk['file']).write_bytes(zipped)
            chunk.update({**publication.byte_info(zipped), 'uncompressed_sha256': publication.byte_info(body)['sha256'],
                          'uncompressed_bytes': len(body)})
            with self.assertRaises(ValueError):
                publication.selected_payload(folder, meta, index)

    def test_registered_archive_bytes_missing_registration_and_mutation(self):
        import zipfile
        publication.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='archive-test-', dir=publication.WORK) as temporary:
            folder = Path(temporary); body = b'{"charge":-0.0,"unknown":null,"event_id":7}\n'
            members = publication.zip_files(folder / 'ledgers.zip', {'truth.jsonl': body})
            record = {'response_record': {'archive_members': members,
                'archive_delivery': publication.delivery_map(members)}}
            archive_bytes = (folder / 'ledgers.zip').read_bytes()
            self.assertEqual(publication.response_bytes(folder, 'truth.jsonl', record), body)
            value = list(publication.response_records(folder, 'truth.jsonl', record))[0]
            self.assertTrue(publication.exact(value['charge'], -0.0)); self.assertIsNone(value['unknown'])
            self.assertEqual((folder / 'ledgers.zip').read_bytes(), archive_bytes)
            with self.assertRaises(FileNotFoundError):
                publication.response_bytes(folder, 'endpoints.jsonl', record)
            bad = copy.deepcopy(record)
            bad['response_record']['archive_delivery']['truth.jsonl']['member'] = 'endpoints.jsonl'
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                publication.response_bytes(folder, 'truth.jsonl', bad)
            with zipfile.ZipFile(folder / 'ledgers.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('truth.jsonl', body.replace(b'-0.0', b'0.0'))
            with self.assertRaisesRegex(ValueError, 'Archived public bytes'):
                publication.response_bytes(folder, 'truth.jsonl', record)

    def test_delivery_html_preserves_plot_bytes_and_routes_archive_only_links(self):
        source = b'<html><nav><a href="truth.jsonl">Truth</a><a href="traces.jsonl">Traces</a><a href="signals.csv">Signed signal</a></nav><svg><polyline points="0,-0.000001 3,4"/></svg></html>'
        result = publication.package_summary(source, publication.delivery_map({'truth.jsonl': {}, 'traces.jsonl': {}}))
        self.assertIn(b'href="ledgers.zip"', result); self.assertIn(b'href="signals.csv"', result)
        self.assertNotIn(b'href="truth.jsonl"', result)
        self.assertNotIn(b'href="traces.jsonl"', result)
        self.assertIn(b'<svg><polyline points="0,-0.000001 3,4"/></svg>', result)
        original_native = publication.package_summary(b'<html>old</html>', {}, original_native=True)
        self.assertIn(b'href="../ledgers.zip"', original_native)
        self.assertIn(b'href="signals.csv"', original_native)

    def test_registered_full_manifest_source_refuses_resealed_pin(self):
        from unittest.mock import patch
        publication.WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='pin-test-', dir=publication.WORK) as temporary:
            folder = Path(temporary)
            source = {'kind': 'ring_saved_publication_v1', 'status': 'complete',
                      'models': dict.fromkeys(publication.MODELS, {}), 'source_records': {'x': {'sha256': 'a' * 64, 'bytes': 3}}}
            body = publication.encoded(source); path = folder / 'packaging-source-manifest.json'; path.write_bytes(body)
            digest = publication.byte_info(body)['sha256']
            manifest = {'packaging': {'source_manifest': {'file': path.name, **publication.byte_info(body)},
                                      'source_records': copy.deepcopy(source['source_records'])}}
            with patch.object(publication, 'FULL_BUNDLE_MANIFEST', digest):
                self.assertEqual(publication.package_source(folder, manifest), source)
                false_source = copy.deepcopy(source); false_source['source_records']['x']['bytes'] = 4
                path.write_bytes(publication.encoded(false_source))
                manifest['packaging']['source_manifest'].update(publication.artifact_info(path))
                with self.assertRaisesRegex(ValueError, 'Unknown packaging source'):
                    publication.package_source(folder, manifest)

    def test_resealed_gzip_and_model_metadata_cannot_change_trusted_full_source(self):
        """Synthetic pinned full export isolates independent packaging authority."""
        import gzip
        from unittest.mock import patch
        R = publication
        with tempfile.TemporaryDirectory(prefix='authority-test-', dir=R.WORK) as temporary:
            folder = Path(temporary); source = {'kind': 'ring_saved_publication_v1', 'status': 'complete',
                'source_records': {}, 'models': {}, 'files': {}}
            current_files = {}; current_models = {}
            for model in R.MODELS:
                chunks = []; old_chunks = []; model_folder = folder / model; model_folder.mkdir()
                body = b'{"signed":-0.0,"event_id":7}\n'
                selected = gzip.compress(body, mtime=0)
                (model_folder / 'selected.json.gz').write_bytes(selected)
                source['files'][model + '/selected.json'] = R.byte_info(body)
                source['files'][model + '/selected.json.gz'] = R.byte_info(selected)
                current_files[model + '/selected.json.gz'] = R.byte_info(selected)
                for number in range(100):
                    name = f'events-{number*100:05d}.json'; zipped = gzip.compress(body, mtime=0)
                    source['files'][model + '/' + name] = R.byte_info(body)
                    (model_folder / (name + '.gz')).write_bytes(zipped)
                    current_files[model + '/' + name + '.gz'] = R.byte_info(zipped)
                    old = {'file': name, 'first': number*100, 'count': 100, 'sha256': R.byte_info(body)['sha256']}
                    old_chunks.append(old)
                    chunks.append({**old, 'file': name + '.gz', **R.byte_info(zipped), 'encoding': 'gzip', 'gzip_mtime': 0,
                        'uncompressed_sha256': R.byte_info(body)['sha256'], 'uncompressed_bytes': len(body)})
                original_scene = {'model': model, 'geometry': {'bias_V': -370, 'zero': -0.0},
                                  'event_index': {'chunks': old_chunks}}
                source['files'][model + '/scene.json'] = R.byte_info(R.encoded(original_scene))
                new_scene = {**original_scene, 'event_index': {'chunks': chunks}}
                (model_folder / 'scene.json').write_bytes(R.encoded(new_scene))
                current_files[model + '/scene.json'] = R.byte_info(R.encoded(new_scene))
                response_folder = model_folder / 'response'; response_folder.mkdir()
                old_run = {'model': model, 'charge': -0.0, 'unknown': None}
                members = {'run.json': R.encoded(old_run), 'summary.html': b'<html><nav><a href="truth.jsonl">Truth</a></nav></html>',
                           'truth.jsonl': body}
                if model == 'KMRC01_candidate':
                    members['original-native/summary.html'] = b'<html>original native</html>'
                inventory = R.zip_files(response_folder / 'ledgers.zip', members)
                source['files'][model + '/response/ledgers.zip'] = R.artifact_info(response_folder / 'ledgers.zip')
                current_files[model + '/response/ledgers.zip'] = source['files'][model + '/response/ledgers.zip']
                for name, info in inventory.items():
                    source['files'][model + '/response/' + name] = info
                old_record = {'archive_members': inventory, 'current_report': R.byte_info(R.encoded(old_run))}
                delivery = R.delivery_map(inventory); rewrites = {}
                for name in ('summary.html', 'original-native/summary.html'):
                    if name not in members:
                        continue
                    rewritten = R.package_summary(members[name], delivery, original_native=name.startswith('original-native/'))
                    path = response_folder / name; path.parent.mkdir(exist_ok=True); path.write_bytes(rewritten)
                    rewrites[name] = {'archive': 'ledgers.zip', 'member': name, 'original': inventory[name],
                                      'delivered': R.byte_info(rewritten)}
                    current_files[model + '/response/' + name] = R.byte_info(rewritten)
                new_run = {**old_run, 'web_delivery': {'archive_delivery': delivery, 'delivery_rewrites': rewrites,
                    'original_public_report': old_record['current_report'], 'source_full_manifest_sha256': ''}}
                original_model = {'scene': model + '/scene.json', 'source_scene_sha256': source['files'][model + '/scene.json']['sha256'],
                                  'selected': model + '/selected.json.gz',
                                  'dataset_binding': {'model': model, 'bias_V': -370}, 'response_record': old_record}
                source['models'][model] = original_model
                current_models[model] = {**original_model, 'source_scene_sha256': current_files[model + '/scene.json']['sha256'],
                    'response_record': {**old_record, 'archive_delivery': delivery, 'delivery_rewrites': rewrites}, '_run': new_run}
            full_body = R.encoded(source); pin = R.byte_info(full_body)['sha256']
            (folder / 'packaging-source-manifest.json').write_bytes(full_body)
            current_files['packaging-source-manifest.json'] = R.byte_info(full_body)
            for model, record in current_models.items():
                new_run = record.pop('_run'); new_run['web_delivery']['source_full_manifest_sha256'] = pin
                body = R.encoded(new_run); (folder / model / 'response/run.json').write_bytes(body)
                record['response_record']['current_report'] = R.byte_info(body)
                current_files[model + '/response/run.json'] = R.byte_info(body)
            current = {**source, 'models': current_models, 'files': current_files,
                'packaging': {'kind': 'ring_lossless_web_package_v1', 'scientific_recomputation': 0, 'source_records': {},
                    'source_manifest': {'file': 'packaging-source-manifest.json', **R.byte_info(full_body)}, 'gzip_chunks': 200,
                    'payload_bytes': sum(v['bytes'] for v in current_files.values()),
                    'max_payload_file_bytes': max(v['bytes'] for v in current_files.values())}}
            (folder / 'manifest.json').write_bytes(R.encoded(current))
            with patch.object(R, 'FULL_BUNDLE_MANIFEST', pin):
                R.validate_package_bindings(folder, current)
                changed = copy.deepcopy(current); changed['models']['GeRC02']['dataset_binding']['bias_V'] = 1
                with self.assertRaisesRegex(ValueError, 'scientific metadata'):
                    R.validate_package_bindings(folder, changed)
                scene_path = folder / 'GeRC02/scene.json'; scene = R.read(scene_path); chunk = scene['event_index']['chunks'][0]
                body = b'{"signed":0.0,"event_id":7}\n'; zipped = gzip.compress(body, mtime=0)
                (folder / 'GeRC02' / chunk['file']).write_bytes(zipped)
                chunk.update({**R.byte_info(zipped), 'uncompressed_sha256': R.byte_info(body)['sha256'], 'uncompressed_bytes': len(body)})
                scene_path.write_bytes(R.encoded(scene))
                current['files']['GeRC02/' + chunk['file']] = R.byte_info(zipped)
                current['files']['GeRC02/scene.json'] = R.artifact_info(scene_path)
                current['models']['GeRC02']['source_scene_sha256'] = R.digest(scene_path)
                with self.assertRaisesRegex(ValueError, 'Raw chunk source binding'):
                    R.validate_package_bindings(folder, current)


if __name__ == "__main__":
    unittest.main()
