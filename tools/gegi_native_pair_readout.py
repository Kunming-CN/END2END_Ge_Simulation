"""Bridge the fixed8 saved native mixtures to the existing nominal Julia readout."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
import time

import numpy as np
import gegi_event_store as S
import gegi_signal_reconstruction as R
import scenario_workflow as W

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('tools/gegi_native_pair_readout.py', 'tools/gegi_native_pair_readout.jl',
    'tools/test_gegi_native_pair_readout.py', 'tools/gegi_signal_reconstruction.py', 'tools/scenario_workflow.py',
    'tools/local_ui_jobs.py', 'simulation/gegi_response.jl', 'simulation/gegi_signal_helpers.jl',
    'simulation/readout.jl', 'simulation/readout_profiles.jl', 'simulation/readout_demo.json',
    'simulation/replay.jl', 'simulation/run.jl', 'simulation/Project.toml', 'simulation/Manifest.toml')


def complete_native(payload):
    """Validate full captured support; never replace it with FIT_GRID_NS."""
    if (payload['status'] != 'completed' or payload['valid'] is not True or not payload['endpoints'] or
            any(e['status'] != 'contact' or e['step_limit_reached'] or not e['contact_ids'] for e in payload['endpoints'])):
        raise ValueError('Complete contact endpoints are required before terminal hold')
    if payload['signal_coverage'] != R.ALL34_COVERAGE:
        raise ValueError('Complete native-signed34 coverage and units are required')
    signals = payload['channel_signals']
    if [s['contact_id'] for s in signals] != R.ALL34_IDS:
        raise ValueError('All34 original channel IDs are required')
    waves = [R._wave(s) for s in signals]
    t = waves[0][0]
    if (t[0] != 0. or any(not np.array_equal(t, other) for other,_ in waves) or
            any(q[0] != 0. for _,q in waves)):
        raise ValueError('Common complete zero-origin native time support is required')
    return {'sample_count': len(t), 'end_ns': float(t[-1]), 'dt_ns': float(t[1]-t[0]),
            'channels': len(waves), 'complete_contact_endpoints': True}


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def run(inverse, recipe_done, profile, output, max_seconds=180):
    started = time.perf_counter()
    inverse, recipe_done, profile, output = map(Path, (inverse, recipe_done, profile, output))
    if not 0 < max_seconds <= 180:
        raise ValueError('Use one execution of at most180seconds')
    prior = json.loads(inverse.read_bytes()); done = json.loads(recipe_done.read_bytes())
    if prior['status'] != 'completed' or [r['mixture_index'] for r in prior['records']] != list(range(8)):
        raise ValueError('Use the completed fixed8 ideal inverse cases')
    recipe = done['response']['readout_recipe']
    if S.sha(S.encoded(recipe)) != done['response']['readout_recipe_sha256']:
        raise ValueError('Saved nominal recipe binding changed')
    inputs = {str(p.resolve().relative_to(ROOT)): W.sha(p) for p in (inverse,recipe_done,profile)}
    sources = {name: W.sha(ROOT/name) for name in SOURCES}
    for name in ('readout.jl','readout_profiles.jl','gegi_signal_helpers.jl','replay.jl'):
        if recipe['source_code_sha256'][name] != sources['simulation/'+name]:
            raise ValueError('Frozen electronics/charge-sum helper changed: '+name)
    cases = []
    for record in prior['records']:
        if record['mixing_weights'] != [.5,.5] or record['time_offsets_ns'] != [0.,0.]:
            raise ValueError('Use the original fixed prompt equal-weight mixtures')
        components = []
        for ref,digest in zip(record['source_record_refs'],record['source_record_sha256']):
            matches = [name for name,h in prior['input_sha256'].items() if name.endswith('/'+ref) and h == digest]
            if len(matches) != 1 or W.sha(ROOT/matches[0]) != digest:
                raise ValueError('Original complete source record is missing or changed: '+ref)
            path = matches[0]; inputs[path] = digest
            payload = json.loads((ROOT/path).read_bytes())['payload']
            components.append({'ref':path,'sha256':digest,'complete_support':complete_native(payload)})
        cases.append({'mixture_index':record['mixture_index'], 'components':components,
                      'mixing_weights':record['mixing_weights'], 'time_offsets_ns':record['time_offsets_ns']})
    output.mkdir(parents=True, exist_ok=False)
    request = {'kind':'gegi_native_pair_readout_request_v1','root':str(ROOT),'source_sha256':sources,
        'input_sha256':inputs,'recipe':recipe,'profile_ref':str(profile.resolve()),'cases':cases,
        'horizon_ns':None,'tail_rule':'Existing ungated E.process_event: complete native support plus20nominal shaping constants (10000ns); zero current after verified complete native endpoints.',
        'opposite_predictions':'Excluded: saved inverse predictions only cover FIT_GRID_NS; no synthesized complete tail.'}
    write(output/'request.json',request)
    env = W.child_env(1)
    argv = [env['JULIA_EXE'],'--startup-file=no','--threads=1','--project='+str(ROOT/'simulation'),
            str(ROOT/'tools/gegi_native_pair_readout.jl'),str((output/'request.json').resolve()),str((output/'readout.json').resolve())]
    readout_started = time.perf_counter()
    with (output/'stdout.log').open('xb') as stdout, (output/'stderr.log').open('xb') as stderr:
        subprocess.run(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                       timeout=max_seconds-(time.perf_counter()-started), check=True)
    child_seconds = time.perf_counter()-readout_started
    raw = json.loads((output/'readout.json').read_bytes())
    if [r['mixture_index'] for r in raw['cases']] != list(range(8)) or any(len(r['channels']) != 34 for r in raw['cases']):
        raise ValueError('Readout must retain all8cases and272channels')
    for row,old in zip(raw['cases'],prior['records']):
        truth = old['evaluation']['truth_sites']
        for channel in row['channels']:
            cid = channel['contact_id']
            expected = sum(s['energy_keV'] for s in truth if cid in s['contact_ids'])
            channel['evaluation_only'] = {'expected_collecting_charge_keV':expected,
                'adc_energy_minus_expected_keV': channel['reconstructed_energy_keV']-expected if channel['reconstructed_energy_keV'] is not None else None,
                'analog_energy_minus_terminal_wired_keV':channel['analog_energy_keV']-channel['final_wired_induced_keV']}
        row['saved_inverse_evaluation_reused'] = {'matching_correct':old['evaluation']['matching_correct'],
            'total_energy_error_keV':old['evaluation']['total_energy_error_keV'],
            'site_errors':old['evaluation']['assignment_min_errors']['site_errors']}
    channels = [c for r in raw['cases'] for c in r['channels']]
    collectors = [c for c in channels if c['evaluation_only']['expected_collecting_charge_keV'] > 0]
    others = [c for c in channels if c['evaluation_only']['expected_collecting_charge_keV'] == 0]
    def describe(values):
        return {'n':len(values),'min':min(values),'max':max(values),'median':float(np.median(values))} if values else {'n':0}
    summary = {'cases':8,'channels':len(channels),'expected_collecting_channels':len(collectors),
        'collecting_channels_accepted':sum(c['accepted'] for c in collectors),
        'noncollecting_channels_accepted_by_peak':sum(c['accepted'] for c in others),
        'noncollecting_channels_above_terminal_collection_threshold':sum(c['collection_candidate'] for c in others),
        'rejection_reasons':dict(Counter(c['rejection_reason'] for c in channels if c['rejection_reason'])),
        'null_adc_energy_channels':sum(c['reconstructed_energy_keV'] is None for c in channels),
        'null_charge_t50_channels':sum(c['t50_ns'] is None for c in channels),
        'collecting_adc_error_keV':describe([c['evaluation_only']['adc_energy_minus_expected_keV'] for c in collectors if c['reconstructed_energy_keV'] is not None]),
        'collecting_analog_minus_terminal_keV':describe([c['evaluation_only']['analog_energy_minus_terminal_wired_keV'] for c in collectors]),
        'noncollecting_peak_equivalent_keV':describe([c['analog_energy_keV'] for c in others]),
        'charge_t50_ns':describe([c['t50_ns'] for c in channels if c['t50_ns'] is not None]),
        'accepted_peak_time_ns':describe([c['peak_time_ns'] for c in channels if c['accepted']])}
    if sources != {name:W.sha(ROOT/name) for name in SOURCES} or inputs != {name:W.sha(ROOT/name) for name in inputs}:
        raise ValueError('Bound source or saved inputs changed')
    result = {'kind':'gegi_native_pair_nominal_readout_diagnostic_v1','status':'completed_saved8_readout',
        'source_sha256':sources,'input_sha256':inputs,'request_sha256':W.sha(output/'request.json'),
        'julia_readout_sha256':W.sha(output/'readout.json'),'child_seconds':child_seconds,
        'elapsed_seconds':time.perf_counter()-started,'summary':summary,'cases':raw['cases'],
        'horizon_ns':None,'tail_rule':request['tail_rule'],'recipe_sha256':done['response']['readout_recipe_sha256'],
        'electronics_calibration':recipe['electronics_calibration'],'julia':raw['environment'],
        'new_calls':{'native':0,'field':0,'transport':0,'calibration_injection':0,'inverse_fit':0,'observed_mixture_readouts':8},
        'scope':'Nominal noiseless simulation electronics only. Peak time is an electronics maximum; t50/t90 are ideal cumulative-charge arrival estimators, not measured hardware timing. Truth is attached only after readout. No opposite-fit predictions or production changes.'}
    write(output/'result.json',result)
    write(output/'COMPLETE.json',{'status':result['status'],'result_sha256':W.sha(output/'result.json')})
    print(json.dumps({'summary':summary,'child_seconds':child_seconds,'elapsed_seconds':result['elapsed_seconds'],
                      'result_sha256':W.sha(output/'result.json')}),flush=True)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inverse',type=Path,default=ROOT/'.local/gegi-10m/signal-recovery-v1/validation/native-inverse-pair/result.json')
    parser.add_argument('--recipe-done',type=Path,default=ROOT/'.local/gegi-10m/campaign/chunks/co60-right/b000000/DONE.json')
    parser.add_argument('--profile',type=Path,default=ROOT/'simulation/native_readout_profile.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-seconds',type=float,default=180)
    args=parser.parse_args()
    run(args.inverse,args.recipe_done,args.profile,args.output,args.max_seconds)
