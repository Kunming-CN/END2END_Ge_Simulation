"""Saved response validation separated from the frozen scientific source adapter.

Successful pulse records have no status key. Native failures explicitly retain
status and null unknown quantities. No simulation or calibration runs here.
"""
from pathlib import Path
import math
from decay_workflow import W, request, ledger
from ring_workflow import energy_sum_matches
def response(directory,resolved,report,root=W.ROOT,*,historical=False):
    base=Path(directory);out=base/'response';actual=W.read(base/'decay-request.json')
    W.require(actual==request(directory,resolved,root,historical=historical),'Response request authority changed.')
    env=W.read(out/'workflow-decay-response.json');p=W.read(base/'transport/prepared.json');op=resolved['operating_model']
    W.require(report['kind']=='workflow_decay_native_response_v1' and report['configuration_sha256']==W.digest(resolved) and
        report['request_sha256']==W.sha(base/'decay-request.json') and env['kind']=='workflow_decay_response_v1' and
        env['native_report_sha256']==W.sha(out/'run.json') and env['counts']==report['counts'] and
        env['configuration_sha256']==W.digest(resolved) and env['request_sha256']==report['request_sha256'] and
        env['source_sha256']==actual['source_sha256'] and env['source_contract']==report['source_contract']==resolved['decay_source_contract'] and
        env['source_id']==report['source_id']==resolved['selection']['source'] and
        env['model_contract']==report['model_contract']==p['model_contract'],'Shared response source/model envelope changed.')
    W.require(report['signed_operating_bias_V']==env['signed_operating_bias_V']==op['signed_bias_V'] and
        report['wiring_factor']==env['wiring_factor']==op['wiring_factor'] and report['contact_potentials_V']==op['contact_potentials_V'] and
        report['new_field_solution'] is env['new_field_solution'] is True and report['geometry_checks']['field_cache_used'] is False and
        report['independent_calibration_calls']==env['independent_calibration_calls']==1,'Own fields/wiring/calibration policy changed.')
    cal=report['calibration'];W.require(cal==env['calibration'] and cal['energy_keV']==500 and cal['time_step_ns']==2 and
        all(type(cal[k]) in (int,float) and math.isfinite(cal[k]) and cal[k]>0 for k in ('ionisation_energy_eV','charge_C','peak_V','volts_per_keV')) and
        math.isclose(cal['charge_C'],500000/cal['ionisation_energy_eV']*1.602176634e-19,rel_tol=1e-12) and
        math.isclose(cal['volts_per_keV'],cal['peak_V']/500,rel_tol=1e-12),'Independent injection invalid.')
    if op['wiring_factor']==-1:
        inj=W.read(out/'negative-injection.json')
        W.require(cal['raw_charge_C']<0 and cal['electronics_input_charge_C']==cal['charge_C']==-cal['raw_charge_C'] and
            cal['wiring_factor']==-1 and inj['calibration']==cal and inj['input_is_independent_of_event_truth'] is True,
            'Negative wiring lost independent signed injection.')
    else:W.require(not (out/'negative-injection.json').exists(),'Positive detector has unexpected negative injection.')
    source=ledger(directory,resolved,root,historical=historical)
    truths=[W.decode_json(v) for v in (out/'truth.jsonl').read_text(encoding='utf-8').splitlines()]
    W.require(source==truths,'Native response changed source truth.')
    rows=[W.decode_json(v) for v in (out/'scalars.jsonl').read_text(encoding='utf-8').splitlines()]
    primaries=[v for v in rows if v['record_kind']=='decay'];pulses=[v for v in rows if v['record_kind']=='pulse']
    W.require([v['event_id'] for v in primaries]==list(range(len(source))) and len(primaries)==resolved['selection']['primary_count'],
        'Response lost zero or nonzero primaries.')
    expected={(e['event_id'],g['group_id']):(e,g) for e in source for g in e['pulse_groups']}
    W.require(len(pulses)==len(expected) and {(v['event_id'],v['group_id']) for v in pulses}==set(expected),'Pulse identity changed.')
    for v,e in zip(primaries,source):
        W.require(v['global_decay_id']==e['global_decay_id'] and v['zero_deposit']==all(s['energy_keV']==0 for s in e['steps']) and
            energy_sum_matches(v['deposited_energy_keV'],(s['energy_keV'] for s in e['steps'])) and
            v['raw_row_indices']==[s['raw_row_index'] for s in e['steps']] and v['pulse_count']==len(e['pulse_groups']),
            'Response primary truth changed.')
    for v in pulses:
        e,g=expected[(v['event_id'],v['group_id'])];byrow={s['raw_row_index']:s for s in e['steps']}
        W.require(v['group']==g and v['origin_time_ns']==g['origin_time_ns'] and v['raw_row_indices']==g['row_indices'] and
            energy_sum_matches(v['deposited_energy_keV'],(byrow[i]['energy_keV'] for i in g['row_indices'])),'Pulse truth/time changed.')
        if v.get('status')=='native_transport_failed':
            W.require(v['accepted'] is False and all(v[k] is None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns',
                'native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')),
                'Native failure invented charge/readout quantities.')
        elif op['wiring_factor']==-1:
            r=v['readout'];W.require(r['wiring']['factor']==-1 and r['wiring']['model_id']==resolved['selection']['detector'] and
                r['raw_native_final_charge_keV']==v['final_induced_keV'],'Negative readout lost native signed signal.')
    if op['wiring_factor']==-1:
        for line in (out/'traces.jsonl').read_text(encoding='utf-8').splitlines():
            t=W.decode_json(line)['trace'];W.require(t['raw_native_induced_charge_fC']==[-v for v in t['induced_charge_fC']] and
                t['raw_native_current_nA']==[-v for v in t['current_nA']],'Native trace signs changed.')
    return report
