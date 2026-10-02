"""Finite preview tests: pure shared checker, isolated inputs and no dispatch."""
import builtins
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import local_ui_scenarios as S

FIXTURES = S.ROOT / '.local/m11i-scenario-preview-v1/backend/test-fixtures'


@contextmanager
def no_dispatch_or_writes():
    """Exercise valid/refusal routes while outputs and native imports refuse."""
    real_import, real_open, real_loader = builtins.__import__, Path.open, S._load_checker
    attempts, denied = [], []
    def limited_import(name, *args, **kwargs):
        if name.split('.')[0] in {'numpy', 'yaml', 'handoff', 'cs137'}:
            attempts.append('import ' + name)
            raise AssertionError('Native or numerical import')
        return real_import(name, *args, **kwargs)
    def read_only(path, mode='r', *args, **kwargs):
        if any(flag in mode for flag in 'wax+'):
            attempts.append('output')
            raise AssertionError('Output attempted')
        return real_open(path, mode, *args, **kwargs)
    with ExitStack() as stack:
        def guarded_loader(*args):
            checker = real_loader(*args)
            for name in ('native_helpers', 'prepare'):
                denied.append(stack.enter_context(patch.object(checker, name, side_effect=AssertionError(name))))
            return checker
        stack.enter_context(patch.object(S, '_load_checker', side_effect=guarded_loader))
        stack.enter_context(patch('builtins.__import__', side_effect=limited_import))
        stack.enter_context(patch.object(Path, 'open', read_only))
        for owner, name in ((Path, 'mkdir'), (os, 'mkdir'), (os, 'makedirs'),
                            (subprocess, 'run'), (subprocess, 'Popen'), (shutil, 'which')):
            denied.append(stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name))))
        try:
            yield
        finally:
            if attempts:
                raise AssertionError('Forbidden input/output attempt: ' + ', '.join(attempts))
            for forbidden in denied:
                forbidden.assert_not_called()


class Scenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURES.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.addCleanup(self.temp.cleanup)
        self.fixture_root = Path(self.temp.name)

    def fixture(self):
        # Copy only the exact finite check inputs. No raw data or numerical cache.
        checker = S._load_checker(*S._checker_snapshot())
        relatives = set(checker.PINNED_INPUTS) | {S.CHECKER_PATH}
        relatives.update(checker.asset_ref(aid) for aid in checker.asset_records())
        relatives.update('scenarios/' + preset[0] + '.json' for preset in S.PRESETS)
        for relative in relatives:
            target = self.fixture_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((S.ROOT / relative).read_bytes())
        return self.fixture_root

    def unavailable(self):
        with no_dispatch_or_writes():
            with self.assertRaises(S.ScenarioPreviewUnavailable) as failure:
                S.checked_scenarios()
        self.assertEqual(str(failure.exception), S.UNAVAILABLE)
        self.assertIsNone(failure.exception.__cause__)

    def test_real_four_presets_public_allowlist_and_no_dispatch(self):
        path_before, environment_before = list(sys.path), dict(os.environ)
        source_files = {p.name for p in (S.ROOT / 'transport').iterdir()}
        with no_dispatch_or_writes():
            catalog = S.checked_scenarios()
        self.assertEqual(sys.path, path_before)
        self.assertEqual(dict(os.environ), environment_before)
        self.assertEqual({p.name for p in (S.ROOT / 'transport').iterdir()}, source_files)
        self.assertNotIn('_finite_scenario_preview_checker', sys.modules)
        self.assertEqual(set(catalog), {'kind', 'schema_version', 'configuration_status',
                                      'read_only', 'scientific_workers_launched', 'scenarios'})
        self.assertEqual({k: v for k, v in catalog.items() if k != 'scenarios'},
                         {'kind': 'finite_scenario_preview_v1', 'schema_version': 1,
                          'configuration_status': 'checked', 'read_only': True,
                          'scientific_workers_launched': 0})
        self.assertEqual([item['id'] for item in catalog['scenarios']], [p[0] for p in S.PRESETS])
        item_keys = {'id', 'configuration_sha256', 'detector', 'cryostat', 'source_pose',
                     'source', 'planned_primary_count', 'seed', 'units', 'source_pose_status',
                     'model_check', 'stages'}
        common_source_keys = {'id', 'particle', 'pdg', 'kinetic_energy_keV', 'angular_policy',
                              'direction_global', 'clock_policy', 'time_ns', 'normalization'}
        for item, preset in zip(catalog['scenarios'], S.PRESETS):
            self.assertEqual(set(item), item_keys)
            self.assertEqual(item['configuration_sha256'], preset[1])
            self.assertEqual(item['planned_primary_count'], 20)
            self.assertEqual(item['seed'], 26092631)
            self.assertEqual(item['units'], {'length': 'mm', 'time': 'ns', 'energy': 'keV',
                                             'angle': 'deg', 'potential': 'V', 'temperature': 'K'})
            detector = item['detector']
            self.assertEqual(set(detector), {'id', 'model_sha256', 'temperature_K', 'contacts', 'readout_contact_id'})
            self.assertEqual(detector['temperature_K'], 78)
            self.assertEqual(detector['readout_contact_id'], 1)
            self.assertEqual(detector['model_sha256'],
                '793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa' if preset[2] == 'AK02' else
                '614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3')
            self.assertEqual(detector['contacts'], [{'id': 1, 'potential_V': 0},
                {'id': 2, 'potential_V': 500 if preset[2] == 'AK02' else 700}])
            self.assertTrue(all(set(contact) == {'id', 'potential_V'} for contact in detector['contacts']))
            self.assertEqual(item['cryostat'], {'id': 'lbnl_modular_nominal_v1', 'capsule_axis_global': [0, 1, 0]})
            self.assertEqual(item['source_pose'], {'id': preset[4], 'position_global_mm':
                [0, 37.073 if preset[4] == 'nominal' else 42.073, 0.290]})
            source = item['source']
            self.assertEqual(source['id'], preset[3])
            self.assertEqual(source['time_ns'], 0)
            if source['particle'] == 'ion':
                self.assertEqual(set(source), common_source_keys | {'Z', 'A'})
                self.assertEqual((source['pdg'], source['Z'], source['A'], source['kinetic_energy_keV']),
                                 (1000551370, 55, 137, 0))
                self.assertIsNone(source['direction_global'])
                self.assertEqual(source['angular_policy'], 'radioactive_decay')
                self.assertEqual(source['clock_policy'], 'remage_initial_decay_secondaries_zero')
                self.assertEqual(source['normalization'],
                    'per initial Cs137 decay; conditional isolated windows, not activity/live time')
            else:
                self.assertEqual(set(source), common_source_keys)
                self.assertEqual((source['particle'], source['pdg'], source['kinetic_energy_keV']), ('gamma', 22, 662))
                self.assertEqual(source['direction_global'], [0, -1, 0])
                self.assertEqual(source['angular_policy'], 'fixed_global_direction')
                self.assertEqual(source['clock_policy'], 'synthetic_primary_time_zero')
                self.assertEqual(source['normalization'],
                    'per one synthetic 662 keV incident gamma; no decay/activity normalization')
            self.assertEqual(item['source_pose_status'], "candidate until this preparation's native checks pass")
            self.assertEqual(item['model_check'],
                'exact pinned bytes/reviewed metadata; independent YAML parse occurs only in prepare')
            self.assertEqual(item['stages'], {'geometry': 'not_executed', 'source_macro': 'not_prepared',
                                             'transport': 'not_executed', 'charge': 'not_executed', 'readout': 'not_executed'})
        text = json.dumps(catalog)
        for private in (str(S.ROOT), 'supported_stages', 'input_sha256', 'nominal_geometry', 'model_ref', 'readout_profile_ref'):
            self.assertNotIn(private, text)
        with self.assertRaises(TypeError): S.checked_scenarios('arbitrary-selector')

    def test_registry_valid_changed_preset_refuses_whole_catalog(self):
        root = self.fixture()
        config = root / ('scenarios/' + S.PRESETS[-1][0] + '.json')
        instance = json.loads(config.read_text())
        instance['source_pose'] = 'nominal'
        config.write_text(json.dumps(instance), encoding='utf-8')
        with patch.object(S, 'ROOT', root):
            checker = S._load_checker(*S._checker_snapshot())
            self.assertEqual(checker.check(config)['instance']['source_pose'], 'nominal')
            self.unavailable()

    def test_checker_source_mismatch_refuses_before_execution(self):
        root = self.fixture()
        with (root / S.CHECKER_PATH).open('ab') as stream:
            stream.write(b'\nraise RuntimeError("unapproved source executed")\n')
        with patch.object(S, 'ROOT', root), patch.object(S, '_load_checker', side_effect=AssertionError('exec')) as load:
            self.unavailable()
        load.assert_not_called()

    def test_checker_rechecked_after_all_four_checks(self):
        checker = S._load_checker(*S._checker_snapshot())
        with patch.object(checker, 'check', wraps=checker.check) as checked:
            with patch.object(S, '_load_checker', return_value=checker), patch.object(S, '_checker_snapshot',
                side_effect=[S._checker_snapshot(), ValueError('private changed-source path')]):
                self.unavailable()
        self.assertEqual(checked.call_count, 4)

    def test_plan_digest_and_identity_are_both_bound_to_literal_preset(self):
        checker = S._load_checker(*S._checker_snapshot())
        plan = checker.check(S.ROOT / ('scenarios/' + S.PRESETS[0][0] + '.json'))
        for section, key, value in (('instance', 'source_pose', 'plus5mm'),
                                    ('detector', 'id', 'SAP22'), ('source', 'id', 'mono_gamma_662_axis_v1')):
            changed = copy.deepcopy(plan)
            (changed['instance'] if section == 'instance' else changed['assets'][section])[key] = value
            with patch.object(checker, 'check', return_value=changed), patch.object(S, '_load_checker', return_value=checker):
                self.unavailable()

    def test_altered_pinned_input_and_rehashed_asset_semantics_refuse(self):
        root = self.fixture()
        model = root / 'models/AK02.yaml'
        original = model.read_bytes()
        model.write_bytes(original + b'\n')
        with patch.object(S, 'ROOT', root): self.unavailable()
        model.write_bytes(original)
        asset = root / 'scenarios/assets/mono_gamma_662_axis_v1.json'
        document = json.loads(asset.read_text())
        document['direction_global'] = [0, 1, 0]
        asset.write_text(json.dumps(document), encoding='utf-8')
        config = root / ('scenarios/' + S.PRESETS[1][0] + '.json')
        instance = json.loads(config.read_text())
        instance['source']['sha256'] = hashlib.sha256(asset.read_bytes()).hexdigest()
        config.write_text(json.dumps(instance), encoding='utf-8')
        with patch.object(S, 'ROOT', root):
            checker = S._load_checker(*S._checker_snapshot())
            with self.assertRaisesRegex(ValueError, 'semantics'): checker.check(config)
            self.unavailable()

    def test_linked_and_reparse_code_owned_inputs_refuse(self):
        source = S.ROOT / S.CHECKER_PATH
        real_lstat = Path.lstat
        # A reparse point is refused on Windows independently of symlink privilege.
        for path in (S.ROOT, source.parent, source, S.ROOT / ('scenarios/' + S.PRESETS[0][0] + '.json')):
            def flagged(candidate, *args, **kwargs):
                info = real_lstat(candidate, *args, **kwargs)
                if candidate == path:
                    values = {key: getattr(info, key) for key in ('st_mode',)}
                    values['st_file_attributes'] = stat.FILE_ATTRIBUTE_REPARSE_POINT
                    return type('ReparseInfo', (), values)()
                return info
            with patch.object(Path, 'lstat', flagged): self.unavailable()
        root = self.fixture()
        config = root / ('scenarios/' + S.PRESETS[0][0] + '.json')
        target = root / 'original-config.json'
        target.write_bytes(config.read_bytes())
        # Model a linked component without depending on Windows link privileges.
        def linked(candidate, *args, **kwargs):
            info = real_lstat(candidate, *args, **kwargs)
            if candidate == config:
                return type('LinkInfo', (), {'st_mode': stat.S_IFLNK, 'st_file_attributes': 0})()
            return info
        with patch.object(S, 'ROOT', root), patch.object(Path, 'lstat', linked): self.unavailable()


if __name__ == '__main__': unittest.main()
