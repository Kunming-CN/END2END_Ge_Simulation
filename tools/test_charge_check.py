"""M4a synthetic storage-contract fixtures. No physics or runtime execution.

Every fixture is newly constructed; no historical run is edited or rebased.
Tests call the real helper and (where applicable) public Run.cmd dispatch.
"""
import argparse
from contextlib import redirect_stdout
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import charge_check as cc

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = None
SEQ = 0


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    return {str(p.relative_to(path)): (sha(p), p.stat().st_size, p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


def jsonl(path, rows):
    path.write_text(''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in rows), encoding='utf-8')


def mirror(base, name, records, columns):
    jsonl(base / (name + '.jsonl'), records)
    with (base / (name + '.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in records:
            w.writerow([json.dumps(r, separators=(',', ':')) if k == 'record_json' else
                        (str(r[k]).lower() if type(r.get(k)) is bool else r.get(k)) for k in columns])


SC = ['record_kind','event_id','global_decay_id','group_id','origin_time_ns','deposited_energy_keV','final_induced_keV','accepted','rejection_reason','record_json']
EP = ['event_id','global_decay_id','group_id','raw_row_index','parcel_index','seed_uint64','record_json']
TR = ['event_id','global_decay_id','record_json']


def refresh(root):
    """TEST ONLY rehash mutated synthetic artifacts to exercise semantic guards."""
    run = root / '.local/runs/synthetic'
    base = run / 'AK02/response'
    r = read(base / 'run.json')
    r['artifacts'] = {p.name: sha(p) for p in base.iterdir() if p.name != 'run.json'}
    r['artifact_bytes'] = {p.name: p.stat().st_size for p in base.iterdir() if p.name != 'run.json'}
    save(base / 'run.json', r)
    parent = read(run / 'run.json')
    parent['models']['AK02']['response_report_sha256'] = sha(base / 'run.json')
    parent['models']['AK02']['counts'] = r['counts']
    parent['models']['AK02']['status'] = r['status']
    save(run / 'run.json', parent)


def fixture(root, fail=False):
    for rel in ['Run.cmd', 'tools/scenario_cli.ps1', 'tools/charge_check.ps1', 'tools/charge_check.py',
                'models/AK02.yaml', 'models/catalog.json', 'simulation/native_readout_profile.json',
                *cc.ES_SOURCES, *['simulation/' + s for s in cc.SOURCES], *['transport/' + s for s in cc.STREAM_SOURCES]]:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    run = root / '.local/runs/synthetic'
    base, transport = run / 'AK02/response', run / 'AK02/transport'
    base.mkdir(parents=True)
    (transport / 'stream').mkdir(parents=True)
    (run / 'run.lock').write_bytes(b'SYNTHETIC TEST existing lock\n')
    rawhash = hashlib.sha256(b'SYNTHETIC TEST ONLY, not LH5\n').hexdigest()
    (transport / 'truth.lh5').write_bytes(b'SYNTHETIC TEST ONLY, not LH5\n')
    groups, truth, scalars, endpoints, signals = [], [], [], [], []
    counts = dict.fromkeys(cc.COUNT_KEYS, 0)
    diagnostics = []
    for event in range(3):
        steps, gs = [], []
        if event:
            origin = 325801375576.251 + event * 1000000
            step = dict(raw_row_index=event, time_ns=origin, energy_keV=10.0,
                        raw=dict(evtid=event, raw_row_index=event, time=origin, edep=10.0))
            steps = [step]
            gs = [dict(group_id=0, row_indices=[event], relative_times_ns=[0.0], origin_time_ns=origin,
                       last_deposit_time_ns=origin, horizon_ns=100000, electronics_state='reset_nominal_isolated_window',
                       tail_truncated_possible=True, boundary_split_within_horizon=False, recovery_not_established=False)]
        t = dict(event_id=event, global_decay_id=event, steps=steps, pulse_groups=gs,
                 line_photon_count=1, decay_photon_count=1, material_energy_keV={'G4_Ge':10.0 if event else 0.0},
                 particles=[], tracks=[], vtx=[], decay_photons=[])
        truth.append(t)
        scalars.append(dict(record_kind='decay',event_id=event,global_decay_id=event,group_id=None,
                            deposited_energy_keV=10.0 if event else 0.0,pulse_count=len(gs),zero_deposit=not bool(event),
                            raw_row_indices=[event] if event else [],line_photon_count=1,decay_photon_count=1,
                            material_energy_keV=t['material_energy_keV'],full_energy_closure=None))
        counts['initial_decays'] += 1
        counts['initial_primaries'] += 1
        counts['line_photons'] += 1
        counts['decay_photons'] += 1
        counts['zero_deposit_primaries'] += not bool(event)
        if not event:
            continue
        pulse = dict(record_kind='pulse',event_id=event,global_decay_id=event,group_id=0,group=gs[0],
                     origin_time_ns=origin,raw_row_indices=[event],deposited_energy_keV=10.0,parcels=16,seed_family=2609261)
        counts['groups'] += 1
        if fail and event == 2:
            pulse.update(status='native_transport_failed', accepted=False, trace_saved=False, rejection_reason='native_transport_failed',
                         raw_table='stp/germanium', deposition_delays_ns=[0.0],
                         source_lh5_sha256=rawhash, native_error=dict(type='ArgumentError',message='Invalid waveform support',exact_error='ArgumentError: Invalid waveform support',stage='NativeLiExample.native_event'))
            for k in ('final_induced_keV','charge_end_ns','native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','transport_flags','endpoints','readout','current_nA','induced_charge_fC'):
                pulse[k] = None
            diagnostics.append(dict(record_kind='native_failure_diagnostic',pulse=pulse,original_event=t,original_group=gs[0],original_steps=steps,settings={}))
            counts['native_failed_groups'] += 1
            counts['rejected'] += 1
        else:
            pulse.update(accepted=True,rejection_reason=None,trace_saved=True,charge_end_ns=4.0,final_induced_keV=-2.0,
                         native_any_negative_charge=True,native_min_charge_keV=-2.0,native_max_charge_keV=0.0,
                         transport_flags=dict(carrier_parcels=32,geometric_contacts=0,step_limits=32,stopped_without_contact=0),
                         readout=dict(input_sample_count=3,original_sample_count=50000,saturated=False,
                                      untruncated_final_charge_keV=-2.0,untruncated_charge_end_ns=4.0,
                                      charge_clipped_at_window=False,final_charge_C=-2e3/2.95*1.602176634e-19))
            counts['accepted'] += 1
            counts['native_charge_samples'] += 3
            counts['analog_samples'] += 50000
            signals.extend([[event,event,0,0.0,0.0],[event,event,0,2.0,-1.0],[event,event,0,4.0,-2.0]])
            for parcel in range(1,17):
                for species in ('electron','hole'):
                    seed = int.from_bytes(hashlib.sha256(f'2609261/{event}/{event}/{parcel}'.encode()).digest()[:8],'big')
                    endpoints.append(dict(event_id=event,global_decay_id=event,group_id=0,raw_row_index=event,parcel_index=parcel,
                                          raw_table='stp/germanium',source_lh5_sha256=rawhash,original_time_ns=origin,origin_time_ns=origin,
                                          deposition_delay_ns=0.0,deposited_energy_keV=10.0,parcel_weight_keV=10/16,
                                          step_final_induced_keV=-2.0,seed_uint64=str(seed),
                                          endpoint=dict(parcel_index=parcel,species=species,samples=3,step_limit_reached=True,
                                                        inside_semiconductor=True,status='step_limit',position_mm=[1,2,3],contact_ids=[])))
        scalars.append(pulse)
    mirror(base,'scalars',scalars,SC)
    mirror(base,'truth',truth,TR)
    mirror(base,'endpoints',endpoints,EP)
    with (base/'signals.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(cc.SIGNAL_COLUMNS);w.writerows(signals)
    sources={s:sha(root/'simulation'/s) for s in cc.SOURCES}
    tsources={s:sha(root/'transport'/s) for s in cc.STREAM_SOURCES}
    modelhash=sha(root/'models/AK02.yaml')
    prepared=dict(kind='cs137_prepared_v1',model_id='AK02',model_sha256=modelhash,primary_count=3,
                  grouping_policy=cc.GROUPING,clock_policy='remage_initial_decay_secondaries_zero',
                  coordinate_transform=dict(definition='SYNTHETIC TEST transform'),source_sha256=tsources,files_sha256={})
    for name in ('scenario.json','geometry.gdml','run.mac'):
        (transport/name).write_text('SYNTHETIC TEST ONLY\n')
        prepared['files_sha256'][name]=sha(transport/name)
    save(transport/'prepared.json',prepared)
    save(base/'input-prepared.json',prepared)
    save(transport/'run.json',dict(status='complete',returncode=0,prepared_sha256=sha(transport/'prepared.json'),source_lh5_sha256=rawhash))
    jsonl(transport/'stream/decays-00000000.jsonl',truth)
    manifest=dict(kind='cs137_decay_stream_v1',status='complete',model_id='AK02',model_sha256=modelhash,primary_count=3,
                  global_decay_id_range=[0,2],grouping_policy=cc.GROUPING,clock_policy=prepared['clock_policy'],
                  coordinate_transform=prepared['coordinate_transform'],units=dict(energy='keV',length='mm',time='ns'),
                  raw_position_unit='m',raw_track_energy_unit='MeV',source_lh5_sha256=rawhash,source_sha256=tsources,
                  raw_tables={'particles': {'columns': {'evtid': {'dtype':'int32','units':''},
                                                       'vertexid': {'dtype':'int32','units':''}}, 'rows':3}},
                  prepared_sha256=sha(transport/'prepared.json'),run_sha256=sha(transport/'run.json'),
                  chunks=[dict(file='decays-00000000.jsonl',count=3,first_global_decay_id=0,sha256=sha(transport/'stream/decays-00000000.jsonl'))],
                  config_sha256=sha(transport/'scenario.json'),geometry_sha256=sha(transport/'geometry.gdml'),macro_sha256=sha(transport/'run.mac'))
    save(transport/'stream/manifest.json',manifest)
    save(base/'input-contract.json',manifest)
    profile=read(root/'simulation/native_readout_profile.json')
    # Explicit supported profile; no producer execution.
    for name in ('profile-input.json','profile.json'):
        shutil.copyfile(root/'simulation/native_readout_profile.json',base/name)
    config=dict(schema_version=2,calibration_energy_keV=500.0,expected_primary_count=3,max_samples_per_event=500000,
                max_window_ns=1e6,require_all_events=True,tail_shaping_constants=20.0,trace_max_points=600,**profile['settings'])
    save(base/'readout-config.json',config)
    report=dict(kind='native_response_v1',input_kind='cs137_decay_stream_v1',status='completed_with_native_failures' if fail else 'completed_provisional_native_response',
                model_id='AK02',model_sha256=modelhash,counts=counts,input_sha256=sha(transport/'stream/manifest.json'),source_lh5_sha256=rawhash,
                source_sha256=sources,boundary_guard=dict(kind='ssd_0_11_8_boundary_guard_v1',installed=True,package_files_modified=False,
                native_source_sha256='0358c255e37c38f62eee6f1e476c0ed48560708dfcd3d367d2688eaa022232ad'),
                guard_source_sha256=sources['native_boundary_guard.jl'],guard_wrapper_sha256=sources['native_response_guarded.jl'],
                parcels=16,seed_family=2609261,diffusion=True,end_drift_when_no_field=False,self_repulsion=False,drift_dt_ns=2,
                nominal_drift_cap_ns=10000,readout_contact_id=1,temperature_K=77,stored_temperature_K=78,bias_V=500,ionisation_energy_eV=2.95,
                seed_rule='SHA256(seed/global_event_id/raw_row_index/parcel_index), first8 bytes big-endian UInt64; no chunk/group index',
                units=cc.UNITS,grouping_policy=cc.GROUPING,native_failure_policy='record',native_failure_allowlist=['Noncontact endpoint outside crystal','Invalid waveform support'],
                charge_csv_policy='examples',trace_selection='first 4 pulse groups in original census order',
                field_settings=dict(precision_bits=64,min_spacing_mm=0.05,max_spacing_mm=2,sor=1,potential_rechecks=4),
                profile=profile,profile_sha256=sha(base/'profile-input.json'),config_sha256=sha(base/'readout-config.json'),
                environment=dict(julia_version='1.13.0',ssd_version='0.11.8',environment_manifest_sha256=sources['Manifest.toml']),
                readout_environment=dict(julia_version='1.13.0',pinned_julia_version='1.13.0',json_version='1.9.0',manifest_sha256=sources['Manifest.toml'],project_sha256=sources['Project.toml']))
    for name in cc.ARTIFACTS:
        if not (base/name).exists():
            (base/name).write_text('SYNTHETIC TEST opaque presentation\n')
    if fail: jsonl(base/'native-failures.jsonl',diagnostics)
    save(base/'run.json',report)
    save(run/'run.json',dict(kind='native_campaign_v1',status='completed_with_native_failures' if fail else 'completed_provisional_native_campaign',
                            events_per_model=3,detectors=['AK02'],models={'AK02':{}},
                            source_sha256={**{'simulation/'+k:v for k,v in sources.items() if k != 'readout_demo.json'},
                                           'simulation/native_readout_profile.json':sha(root/'simulation/native_readout_profile.json')}))
    refresh(root)


def custom_fixture(root):
    """Independent synthetic ES/EE lineage; originals exist only in the mirror."""
    run=root/'.local/runs/synthetic';base=run/'AK02/response';mirror_root=run/'electronics/inputs'
    sources={p:sha(root/p) for p in cc.ES_SOURCES}
    for name in sources:
        dest=mirror_root/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,dest)
    defaults=read(root/'simulation/readout_demo.json')
    def configuration(profile):
        c={k:v for k,v in defaults.items() if k!='max_total_samples'}
        c.update(schema_version=2,expected_primary_count=None,**profile['settings']);return c
    def descriptor(path):
        d=read(mirror_root/path)
        return dict(path=path,sha256=sha(mirror_root/path),schema_version=d['schema_version'],kind=d['kind'])
    profile=read(root/'simulation/native_readout_profile.json')
    profile['name']='synthetic-custom';profile['settings'].update(gain=7.0,feedback_capacitance_pF=0.8,shaping_tau_us=0.8)
    raw='.local/electronics-profiles/raw.json';save(mirror_root/raw,profile)
    paths=[raw]
    for name,gain in [('ancestor',9.0),('selected',11.0)]:
        profile=copy.deepcopy(profile);profile['name']='synthetic-'+name;profile['settings']['gain']=gain
        config=configuration(profile)
        bundle=dict(schema_version=1,kind='electronics_settings_bundle_v1',revision=1,profile=profile,
                    configuration=config,physics_sha256=cc.settings_physics_hash(config),
                    provenance=dict(input=descriptor(paths[-1]),defaults=dict(path='simulation/readout_demo.json',sha256=sources['simulation/readout_demo.json'],schema_version=1),sources_sha256=sources))
        path='.local/electronics-profiles/'+name+'.json';save(mirror_root/path,bundle);paths.append(path)
    save(run/'electronics/profile.json',profile)
    for name in ('profile-input.json','profile.json'):shutil.copyfile(run/'electronics/profile.json',base/name)
    config=configuration(profile);resolved=dict(config,expected_primary_count=3);save(base/'readout-config.json',resolved)
    report=read(base/'run.json');report.update(profile=profile,profile_sha256=sha(base/'profile-input.json'),config_sha256=sha(base/'readout-config.json'));save(base/'run.json',report)
    parent=read(run/'run.json');parent['source_sha256'].update(sources)
    parent['electronics']=dict(schema_version=1,kind='saved_electronics_execution_v1',input=descriptor(paths[-1]),
        inputs_root='.local/runs/synthetic/electronics/inputs',copies_sha256={**sources,**{p:sha(mirror_root/p) for p in paths}},
        sources_sha256=sources,profile_path='.local/runs/synthetic/electronics/profile.json',profile_sha256=sha(run/'electronics/profile.json'),
        configuration=config,physics_sha256=cc.settings_physics_hash(config),
        feasibility=dict(time_step_ns=2,isolated_horizon_ns=100000,last_sample_ns=99998,calibration_samples=8001,
                         scope='Arithmetic sample/window feasibility; numerical injection calibration remains part of native execution, not experimental validation'))
    save(run/'run.json',parent);refresh(root)
    return paths


class ChargeTests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/self.id().split('.')[-1]
        self.root=self.home/'root'
        fixture(self.root)
        self.run=self.root/'.local/runs/synthetic'
        self.base=self.run/'AK02/response'

    def inspect(self):
        before=snapshot(self.root)
        with mock.patch('subprocess.Popen',side_effect=AssertionError('external process forbidden')), mock.patch('os.system',side_effect=AssertionError('external process forbidden')):
            result=cc.inspect_run(self.root,'synthetic')
        self.assertEqual(before,snapshot(self.root))
        save(self.home/'helper-result.json',result)
        return result

    def rejected(self):
        result=self.inspect()
        self.assertFalse(result['storage_complete'],result)
        self.assertFalse(result['eligible'])
        return result

    def change_report(self, **changes):
        r=read(self.base/'run.json');r.update(changes);save(self.base/'run.json',r);refresh(self.root)

    def signals(self, mutate):
        with (self.base/'signals.csv').open(newline='') as f: rows=list(csv.reader(f))
        mutate(rows)
        with (self.base/'signals.csv').open('w',newline='') as f: csv.writer(f).writerows(rows)
        refresh(self.root)

    def scalars(self, mutate):
        records=[json.loads(x) for x in (self.base/'scalars.jsonl').read_text().splitlines()]
        mutate(records)
        mirror(self.base,'scalars',records,SC);refresh(self.root)

    def command(self, *args):
        global SEQ
        SEQ+=1
        argv=['cmd.exe','/d','/c','Run.cmd',*args]
        env=dict(os.environ,SITE_PYTHON=sys.executable,PYTHONDONTWRITEBYTECODE='1')
        before=snapshot(self.root)
        got=subprocess.run(argv,cwd=self.root,env=env,capture_output=True,text=True,timeout=60)
        self.assertEqual(before,snapshot(self.root))
        save(self.home/f'command-{SEQ:03}.json',dict(command=argv,exit_code=got.returncode,stdout=got.stdout,stderr=got.stderr))
        return got

    def test_complete_signed_negative_and_examples_all(self):
        r=self.inspect();self.assertTrue(r['storage_complete']);self.assertTrue(r['producer_compatible'])
        self.assertFalse(r['eligible']);self.assertEqual(r['runtime_verified'],'NOT_CHECKED');self.assertEqual(r['replay_supported'],'NOT_IMPLEMENTED')
        d=r['detectors'][0];self.assertEqual(d['stored_samples'],6);self.assertEqual(d['counts']['zero_deposit_primaries'],1)
        self.assertEqual(d['groups'][0]['final_induced_keV'],-2);self.assertTrue(d['groups'][0]['nonzero_negative_samples_present'])

    def test_public_cli_json_and_read_only(self):
        r=self.command('charge-check','-Name','synthetic','-Json');self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(json.loads(r.stdout)['storage_complete'])

    def test_public_cli_rejects_flags_including_defaults(self):
        for args in [('-Preset','demo'),('-Seed','26092631'),('-Scenario','lbnl-cs137'),('-SettingsMode','interactive'),('-DryRun',),('-Open',),('-BuildExporter',),('-ElectronicsProfile',''),('-Typo','x')]:
            self.assertNotEqual(self.command('charge-check','-Name','synthetic',*args).returncode,0)

    def test_public_cli_missing_name_and_typo(self):
        for args in [('charge-check',),('charge-chek','-Name','synthetic')]:
            self.assertNotEqual(self.command(*args).returncode,0)

    def test_detector_absent_no_fallback(self):
        r=self.command('charge-check','-Name','synthetic','-Detector','SAP22','-Json')
        self.assertEqual(r.returncode,2);self.assertEqual(json.loads(r.stdout)['findings'][0]['code'],'missing_detector')

    def test_examples_only_partial(self):
        self.signals(lambda rows:rows.__delitem__(slice(4,None)))
        r=self.rejected();self.assertEqual(r['detectors'][0]['missing_samples'][0]['reason'],'missing_group')

    def test_truncated(self):
        self.signals(lambda rows:rows.pop());r=self.rejected()
        self.assertEqual(r['detectors'][0]['missing_samples'][0]['reason'],'truncated_group')

    def test_missing_signals(self):
        (self.base/'signals.csv').unlink();r=self.rejected()
        self.assertIn('inventory',r['detectors'][0]['findings'][-1]['detail'])

    def test_duplicate(self):
        self.signals(lambda rows:rows.insert(2,rows[1]));self.rejected()

    def test_reordered(self):
        self.signals(lambda rows:rows.__setitem__(slice(1,4),list(reversed(rows[1:4]))));self.rejected()

    def test_extra(self):
        self.signals(lambda rows:rows.append(rows[1]));self.rejected()

    def test_mismatched_ids(self):
        self.signals(lambda rows:rows[2].__setitem__(0,'2'));self.rejected()

    def test_identity_float_rejected(self):
        self.signals(lambda rows:rows[1].__setitem__(0,'1.0'));self.rejected()

    def test_nan(self):
        self.signals(lambda rows:rows[2].__setitem__(4,'nan'));self.rejected()

    def test_infinite(self):
        self.signals(lambda rows:rows[2].__setitem__(3,'inf'));self.rejected()

    def test_bad_grid(self):
        self.signals(lambda rows:rows[2].__setitem__(3,'2.1'));self.rejected()

    def test_bad_start(self):
        self.signals(lambda rows:rows[1].__setitem__(3,'2.0'));self.rejected()

    def test_rectified_negative(self):
        self.signals(lambda rows:rows[3].__setitem__(4,'2.0'));self.rejected()

    def test_wrong_extrema(self):
        self.scalars(lambda records:records[2].update(native_min_charge_keV=-3.0));self.rejected()

    def test_wrong_end_support(self):
        self.scalars(lambda records:records[2].update(charge_end_ns=6.0));self.rejected()

    def test_float_spelling_tolerance(self):
        self.signals(lambda rows:rows[2].__setitem__(3,'2.0000000000000004'));self.assertTrue(self.inspect()['storage_complete'])

    def test_bad_units(self):
        self.change_report(units=dict(cc.UNITS,time='us'));self.rejected()

    def test_bad_endpoint(self):
        records=[json.loads(x) for x in (self.base/'endpoints.jsonl').read_text().splitlines()]
        records[0]['step_final_induced_keV']=2.0;mirror(self.base,'endpoints',records,EP);refresh(self.root);self.rejected()

    def test_bad_origin(self):
        self.scalars(lambda records:records[2].update(origin_time_ns=1));self.rejected()

    def test_absolute_origin_is_not_relative_tolerance_override(self):
        self.scalars(lambda records:records[2].update(origin_time_ns=records[2]['origin_time_ns']+0.01));self.rejected()

    def test_census_zero_missing(self):
        self.scalars(lambda records:records.pop(0));self.rejected()

    def test_bool_identity(self):
        self.scalars(lambda records:records[0].update(event_id=False));self.rejected()

    def test_nested_identity_list_float(self):
        self.scalars(lambda records:records[2].update(raw_row_indices=[1.0]));self.rejected()

    def test_global_identity_range_float(self):
        manifest=self.run/'AK02/transport/stream/manifest.json'
        m=read(manifest);m['global_decay_id_range']=[0.0,2.0]
        save(manifest,m);save(self.base/'input-contract.json',m)
        self.change_report(input_sha256=sha(manifest));self.rejected()

    def test_json_float_overflow(self):
        path=self.run/'run.json'
        path.write_text(path.read_text().replace('{','{"unused_overflow":1e9999,',1))
        r=self.rejected();self.assertEqual(r['findings'][0]['code'],'invalid_json')

    def test_oversized_integer_number_is_rejected(self):
        with self.assertRaises(cc.Rejected):cc.number(10**400,'synthetic huge time')

    def test_endpoint_overflow_cli_structured_no_write(self):
        rows=[json.loads(x) for x in (self.base/'endpoints.jsonl').read_text().splitlines()]
        rows[0]['endpoint']['position_mm'][0]=10**1000
        mirror(self.base,'endpoints',rows,EP);refresh(self.root)
        got=self.command('charge-check','-Name','synthetic','-Json')
        self.assertEqual(got.returncode,0,got.stderr)
        result=json.loads(got.stdout);self.assertFalse(result['storage_complete'])
        self.assertIn('finite number required',result['detectors'][0]['findings'][-1]['detail'])
        self.assertNotIn('Traceback',got.stderr)

    def test_parent_array_cli_structured_no_write(self):
        save(self.run/'run.json',[])
        got=self.command('charge-check','-Name','synthetic','-Json')
        self.assertEqual(got.returncode,2,got.stderr)
        result=json.loads(got.stdout);self.assertEqual(result['inspection_status'],'blocked')
        self.assertEqual(result['findings'][0]['code'],'invalid_json');self.assertNotIn('Traceback',got.stderr)

    def test_nested_container_cli_structured_no_write(self):
        p=read(self.run/'run.json');p['models']['AK02']=[];save(self.run/'run.json',p)
        got=self.command('charge-check','-Name','synthetic','-Json')
        self.assertEqual(got.returncode,2,got.stderr);self.assertFalse(json.loads(got.stdout)['storage_complete'])
        self.assertNotIn('Traceback',got.stderr)

    def test_final_recheck_invalidates_detector_and_human_claims(self):
        before=snapshot(self.root);observed=[];actual=cc.inspect_detector
        def detector(*args):
            result=actual(*args);observed.append(copy.deepcopy(result));return result
        with mock.patch.object(cc,'inspect_detector',side_effect=detector), mock.patch.object(cc.Reader,'recheck',side_effect=cc.Rejected('changed_during_read','injected final recheck failure')):
            result=cc.inspect_run(self.root,'synthetic')
        self.assertTrue(observed[0]['storage_complete']);self.assertTrue(observed[0]['producer_compatible'])
        self.assertEqual(result['inspection_status'],'blocked');self.assertFalse(result['verification_final'])
        child=result['detectors'][0]
        for obj in (result,child):
            self.assertFalse(obj['storage_complete']);self.assertFalse(obj['producer_compatible'])
        self.assertEqual(child['observations_status'],'nonfinal');self.assertIn('provenance',child);self.assertIn('groups',child)
        output=io.StringIO()
        with mock.patch.object(cc,'inspect_run',return_value=result),redirect_stdout(output):
            self.assertEqual(cc.main(['--name','synthetic']),2)
        self.assertNotIn('storage_complete=True',output.getvalue());self.assertNotIn('producer_compatible=True',output.getvalue())
        self.assertIn('observations=nonfinal',output.getvalue());self.assertEqual(before,snapshot(self.root))
        save(self.home/'recheck-result.json',result);(self.home/'human-output.txt').write_text(output.getvalue())

    def test_count_float(self):
        r=read(self.base/'run.json');r['counts']['groups']=2.0;save(self.base/'run.json',r);refresh(self.root);self.rejected()

    def test_changed_artifact(self):
        with (self.base/'signals.csv').open('a') as f:f.write('\n')
        self.rejected()

    def test_rehashed_incompatible_config(self):
        c=read(self.base/'readout-config.json');c['gain']+=1;save(self.base/'readout-config.json',c)
        self.change_report(config_sha256=sha(self.base/'readout-config.json'));self.rejected()

    def test_rehashed_config_expected_count_only_strict(self):
        c=read(self.base/'readout-config.json');c['expected_primary_count']=3.0;save(self.base/'readout-config.json',c)
        self.change_report(config_sha256=sha(self.base/'readout-config.json'));self.rejected()

    def test_source_difference_separate(self):
        with (self.root/'simulation/native_response.jl').open('a') as f:f.write('\n# synthetic incompatible producer\n')
        r=self.inspect();self.assertTrue(r['storage_complete']);self.assertFalse(r['producer_compatible'])

    def test_recorded_runtime_incompatibility(self):
        r=read(self.base/'run.json');r['readout_environment']['julia_version']='0.0.0'
        save(self.base/'run.json',r);refresh(self.root)
        result=self.inspect();self.assertTrue(result['storage_complete']);self.assertFalse(result['producer_compatible'])

    def test_no_current_profile_fallback(self):
        profile=read(self.root/'simulation/native_readout_profile.json');profile['settings']['gain']=99
        save(self.root/'simulation/native_readout_profile.json',profile)
        result=self.inspect();self.assertTrue(result['storage_complete'])
        self.assertEqual(result['detectors'][0]['provenance']['profile_sha256'],sha(self.base/'profile-input.json'))

    def test_rehashed_unknown_source_inventory(self):
        r=read(self.base/'run.json');r['source_sha256']['unreviewed.jl']='0'*64;save(self.base/'run.json',r);refresh(self.root);self.rejected()

    def test_parent_control_difference_reported(self):
        p=read(self.run/'run.json');p['source_sha256']['tools/scenario_cli.ps1']='0'*64;save(self.run/'run.json',p)
        r=self.inspect();self.assertTrue(r['storage_complete']);self.assertIn('parent_source_differences',[f['code'] for f in r['findings']])

    def test_parent_final_child_binding(self):
        p=read(self.run/'run.json');p['models']['AK02']['response_report_sha256']='0'*64;save(self.run/'run.json',p);self.rejected()

    def test_duplicate_json_keys(self):
        (self.run/'run.json').write_text('{"kind":"native_campaign_v1","kind":"other"}')
        self.rejected()

    def test_unsupported_serialization_not_opened(self):
        (self.base/'batch.jls').write_bytes(b'NEVER DESERIALIZE');r=self.rejected()
        self.assertEqual(r['detectors'][0]['findings'][-1]['code'],'not_supported')

    def test_unsupported_parent(self):
        save(self.run/'run.json',dict(kind='million_native_checkpoint_v1'))
        r=self.rejected();self.assertEqual(r['findings'][0]['code'],'not_supported')

    def test_missing_lock(self):
        (self.run/'run.lock').unlink();r=self.rejected();self.assertEqual(r['lock_observation'],'missing_lock')

    def test_held_lock(self):
        with cc.existing_lock(cc.Reader(self.root),'.local/runs/synthetic/run.lock'):
            # Cannot snapshot an exclusively held lock; the API must return without opening inputs.
            r=cc.inspect_run(self.root,'synthetic')
        self.assertEqual(r['lock_observation'],'held_or_inaccessible_lock')

    def test_unsafe_name(self):
        r=cc.inspect_run(self.root,'../synthetic');self.assertEqual(r['findings'][0]['code'],'unsafe_path')

    def test_reparse_path(self):
        target=self.home/'external';target.mkdir()
        (target/'run.lock').write_text('TEST')
        # Junction creation needs no symlink privilege on Windows; only fixture paths.
        got=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(self.root/'.local/runs/linked'),str(target)],capture_output=True,text=True)
        self.assertEqual(got.returncode,0,got.stderr)
        r=cc.inspect_run(self.root,'linked');self.assertEqual(r['findings'][0]['code'],'unsafe_path')

    def test_failed_groups_nulls_no_charge(self):
        other=self.home/'failure-root';fixture(other,fail=True)
        r=cc.inspect_run(other,'synthetic');save(self.home/'failure-result.json',r)
        self.assertTrue(r['storage_complete'],r);d=r['detectors'][0]
        self.assertEqual(d['counts']['native_failed_groups'],1);self.assertIsNone(d['groups'][-1]['samples'])

    def test_failed_group_fabricated_zero_rejected(self):
        other=self.home/'failure-root';fixture(other,fail=True)
        self.root=other;self.run=other/'.local/runs/synthetic';self.base=self.run/'AK02/response'
        self.scalars(lambda records:records[-1].update(final_induced_keV=0));self.rejected()

    def test_failed_group_has_no_magic_sample(self):
        other=self.home/'failure-root';fixture(other,fail=True)
        self.root=other;self.run=other/'.local/runs/synthetic';self.base=self.run/'AK02/response'
        self.signals(lambda rows:rows.append(['2','2','0','0.0','0.0']));self.rejected()

    def test_no_write_or_process_api(self):
        original=io.open
        def only_read(file,mode='r',*a,**kw):
            self.assertFalse(any(c in mode for c in 'wax+'),mode)
            return original(file,mode,*a,**kw)
        with mock.patch('io.open',only_read),mock.patch('subprocess.Popen',side_effect=AssertionError('process forbidden')):
            r=cc.inspect_run(self.root,'synthetic')
        self.assertTrue(r['storage_complete'])

    def test_bounded_reader(self):
        with mock.patch.object(cc,'MAX_FILE',100):
            r=cc.inspect_run(self.root,'synthetic')
        self.assertEqual(r['findings'][0]['code'],'not_supported')


class CustomLineageTests(unittest.TestCase):
    inspect=ChargeTests.inspect
    rejected=ChargeTests.rejected
    command=ChargeTests.command

    def setUp(self):
        ChargeTests.setUp(self)
        self.paths=custom_fixture(self.root)
        self.mirror=self.run/'electronics/inputs'

    def binding(self, mutate):
        p=read(self.run/'run.json');mutate(p['electronics']);save(self.run/'run.json',p)

    def rehash(self, sources=False, parent_sources=False):
        """TEST ONLY: make changed synthetic copies hash-consistent, not valid."""
        p=read(self.run/'run.json');b=p['electronics']
        if sources:
            b['sources_sha256']={name:sha(self.mirror/name) for name in cc.ES_SOURCES}
        for name in self.paths[1:]:
            d=read(self.mirror/name);prior=d['provenance']['input']['path'];previous=read(self.mirror/prior)
            d['provenance']['input']=dict(path=prior,sha256=sha(self.mirror/prior),kind=previous['kind'],schema_version=previous['schema_version'])
            if sources:
                d['provenance']['sources_sha256']=b['sources_sha256']
                d['provenance']['defaults']['sha256']=b['sources_sha256']['simulation/readout_demo.json']
            save(self.mirror/name,d)
        b['input']['sha256']=sha(self.mirror/self.paths[-1])
        b['copies_sha256']={name:sha(self.mirror/name) for name in [*cc.ES_SOURCES,*self.paths]}
        if parent_sources:
            p['source_sha256'].update(b['sources_sha256'])
            r=read(self.base/'run.json')
            for name,value in b['sources_sha256'].items():
                if name.startswith('simulation/') and name[11:] in r['source_sha256']:r['source_sha256'][name[11:]]=value
            save(self.base/'run.json',r)
        save(self.run/'run.json',p);refresh(self.root)

    def test_custom_complete_mirror_only_and_cli(self):
        result=self.inspect();self.assertTrue(result['storage_complete'],result);self.assertTrue(result['producer_compatible'])
        lineage=result['detectors'][0]['provenance']['electronics_lineage']
        self.assertEqual(len(lineage['input_ancestry']),3);self.assertEqual(len(lineage['required_copies_sha256']),12)
        self.assertFalse((self.root/self.paths[-1]).exists())
        got=self.command('charge-check','-Name','synthetic','-Json');self.assertEqual(got.returncode,0,got.stderr)
        self.assertTrue(json.loads(got.stdout)['storage_complete'])

    def test_empty_copy_inventory(self):
        self.binding(lambda b:b.update(copies_sha256={}));self.rejected()
        got=self.command('charge-check','-Name','synthetic','-Json')
        self.assertEqual(got.returncode,0,got.stderr);self.assertFalse(json.loads(got.stdout)['storage_complete'])

    def test_missing_declared_ancestor(self):
        self.binding(lambda b:b['copies_sha256'].pop(self.paths[0]));self.rejected()

    def test_extra_declared_copy(self):
        (self.mirror/'unrelated.txt').write_text('synthetic extra')
        self.binding(lambda b:b['copies_sha256'].update({'unrelated.txt':sha(self.mirror/'unrelated.txt')}));self.rejected()

    def test_extra_undeclared_copy(self):
        (self.mirror/'unrelated.txt').write_text('synthetic extra');self.rejected()

    def test_empty_source_inventory(self):
        self.binding(lambda b:b.update(sources_sha256={}));self.rejected()

    def test_missing_input_descriptor(self):
        self.binding(lambda b:b.pop('input'));self.rejected()

    def test_input_descriptor_hash(self):
        self.binding(lambda b:b['input'].update(sha256='0'*64));self.rejected()

    def test_deleted_binding_does_not_fallback(self):
        p=read(self.run/'run.json');p.pop('electronics');save(self.run/'run.json',p);self.rejected()

    def test_null_binding_does_not_fallback(self):
        p=read(self.run/'run.json');p['electronics']=None;save(self.run/'run.json',p);self.rejected()

    def test_missing_ancestor_copy(self):
        (self.mirror/self.paths[0]).unlink();self.rejected()

    def test_changed_ancestor_copy(self):
        with (self.mirror/self.paths[0]).open('a') as f:f.write('\n')
        self.rejected()

    def test_missing_default_copy(self):
        (self.mirror/'simulation/readout_demo.json').unlink();self.rejected()

    def test_changed_default_copy(self):
        p=self.mirror/'simulation/readout_demo.json';d=read(p);d['calibration_energy_keV']=999;save(p,d);self.rejected()

    def test_rehashed_incompatible_default_copy(self):
        p=self.mirror/'simulation/readout_demo.json';d=read(p);d['calibration_energy_keV']=999;save(p,d)
        self.rehash(sources=True,parent_sources=True)
        result=self.rejected();self.assertIn('frozen settings default',result['detectors'][0]['findings'][-1]['detail'])

    def test_missing_source_copy(self):
        (self.mirror/'tools/electronics_settings.ps1').unlink();self.rejected()

    def test_changed_source_copy(self):
        (self.mirror/'tools/electronics_settings.ps1').write_text('SYNTHETIC incompatible source format');self.rejected()

    def test_rehashed_source_copy_cannot_rebase_parent(self):
        (self.mirror/'tools/electronics_settings.ps1').write_text('SYNTHETIC incompatible source format')
        self.rehash(sources=True)
        result=self.rejected();self.assertIn('original parent/settings source',result['detectors'][0]['findings'][-1]['detail'])

    def test_rehashed_ancestor_configuration(self):
        p=self.mirror/self.paths[1];d=read(p);d['configuration']['gain']=222
        d['physics_sha256']=cc.settings_physics_hash(d['configuration']);save(p,d);self.rehash()
        result=self.rejected();self.assertIn('independent bundle configuration',result['detectors'][0]['findings'][-1]['detail'])

    def test_missing_ancestor_configuration(self):
        p=self.mirror/self.paths[1];d=read(p);d.pop('configuration');save(p,d);self.rehash();self.rejected()

    def test_rehashed_ancestor_physics_hash(self):
        p=self.mirror/self.paths[1];d=read(p);d['physics_sha256']='0'*64;save(p,d);self.rehash();self.rejected()

    def test_rehashed_ancestor_default_descriptor(self):
        p=self.mirror/self.paths[1];d=read(p);d['provenance']['defaults']['sha256']='0'*64;save(p,d);self.rehash();self.rejected()

    def test_rehashed_ancestor_source_inventory(self):
        p=self.mirror/self.paths[1];d=read(p);d['provenance']['sources_sha256']={};save(p,d);self.rehash();self.rejected()

    def test_rehashed_incompatible_raw_profile(self):
        p=self.mirror/self.paths[0];d=read(p);d['settings']['gain']=True;save(p,d);self.rehash();self.rejected()

    def test_unsupported_ancestor_schema(self):
        p=self.mirror/self.paths[0];d=read(p);d['schema_version']=1;save(p,d);self.rehash()
        result=self.rejected();self.assertEqual(result['detectors'][0]['findings'][-1]['code'],'not_supported')

    def test_ancestry_from_another_profile(self):
        p=self.mirror/self.paths[0];d=read(p);d['name']='different-lineage';d['settings']['gain']=555;save(p,d)
        self.binding(lambda b:b['copies_sha256'].update({self.paths[0]:sha(p)}));self.rejected()

    def test_other_selected_bundle_cannot_replace_recorded_profile(self):
        p=self.mirror/self.paths[-1];d=read(p);d['profile']['settings']['gain']=555;d['configuration']['gain']=555
        d['physics_sha256']=cc.settings_physics_hash(d['configuration']);save(p,d);self.rehash()
        # Even a self-consistent replacement bundle must match execution config/profile.
        self.binding(lambda b:b.update(configuration=d['configuration'],physics_sha256=d['physics_sha256']))
        self.rejected()

    def test_parent_configuration_and_physics_do_not_override_bundle(self):
        def mutate(b):
            b['configuration']['gain']=777;b['physics_sha256']=cc.settings_physics_hash(b['configuration'])
        self.binding(mutate);self.rejected()

    def test_cycle(self):
        p=self.mirror/self.paths[-1];d=read(p);d['provenance']['input']=dict(read(self.run/'run.json')['electronics']['input']);save(p,d);self.rehash()
        result=self.rejected();self.assertIn('cyclic settings provenance',result['detectors'][0]['findings'][-1]['detail'])

    def test_depth_limit(self):
        b=read(self.run/'run.json')['electronics'];template=read(self.mirror/self.paths[-1])
        for i in range(16):
            path='.local/electronics-profiles/deep-'+str(i)+'.json';d=copy.deepcopy(template)
            d['provenance']['input']=dict(path=self.paths[-1],sha256=sha(self.mirror/self.paths[-1]),kind='electronics_settings_bundle_v1',schema_version=1)
            save(self.mirror/path,d);self.paths.append(path)
        self.binding(lambda v:v['input'].update(path=self.paths[-1],sha256=sha(self.mirror/self.paths[-1])))
        self.rehash();result=self.rejected();self.assertIn('exceeds 16',result['detectors'][0]['findings'][-1]['detail'])

    def test_windows_powershell5_physics_hash_contract(self):
        config=read(self.run/'run.json')['electronics']['configuration'];cases=[]
        for value in [0.8,0.8000000000000002,1.2345678901234567,1e-5,1e15,1e16,-0.0]:
            c=dict(config,gain=value);cases.append(c)
        save(self.home/'hash-cases.json',cases)
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        script=self.home/'hash-contract.ps1'
        script.write_text(". "+quote(self.root/'tools/electronics_settings.ps1')+"\n$cases=Get-Content -Raw "+quote(self.home/'hash-cases.json')+" | ConvertFrom-Json\nforeach($case in $cases){Get-ESPhysicsHash $case}\n",encoding='utf-8')
        argv=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)]
        got=subprocess.run(argv,capture_output=True,text=True,timeout=30)
        save(self.home/'hash-contract-terminal.json',dict(command=argv,exit_code=got.returncode,stdout=got.stdout,stderr=got.stderr,source_sha256={p:sha(self.root/p) for p in ('tools/electronics_settings.ps1','tools/native_run_validation.ps1','tools/charge_check.py')}))
        self.assertEqual(got.returncode,0,got.stderr);self.assertEqual(got.stdout.splitlines(),[cc.settings_physics_hash(c) for c in cases])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',required=True);parser.add_argument('tests',nargs='*');args=parser.parse_args()
    EVIDENCE=(ROOT/args.evidence).resolve()
    if not EVIDENCE.is_relative_to(ROOT/'.local/charge-reuse-v1/implementation'):parser.error('Use charge-reuse implementation evidence')
    EVIDENCE.mkdir(parents=True,exist_ok=False)
    save(EVIDENCE/'scope.json',dict(test_only=True,synthetic_storage_contract=True,scientific_acceptance=False,python=sys.executable,argv=sys.argv))
    unittest.main(argv=[__file__,*args.tests],verbosity=2)
