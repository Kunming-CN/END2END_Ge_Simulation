"""Independent streamed saved-result census; no native work or calibration."""
from pathlib import Path
import itertools,math
import scenario_workflow as W
from ring_workflow import energy_sum_matches
from local_ui_jobs import safe_path

def json_lines(path):
    with Path(path).open(encoding='utf-8') as rows:
        for line in rows:yield W.decode_json(line)

def source_events(directory):
    base=Path(directory)/'transport/stream';manifest=W.read(base/'manifest.json')
    for chunk in manifest['chunks']:
        yield from json_lines(safe_path(base,chunk['file']))

def response_census(directory,resolved,report):
    base=Path(directory);out=base/'response';cal=report['calibration'];eion=report['ionisation_energy_eV']
    W.require(cal['energy_keV']==500 and cal['time_step_ns']==2 and cal['ionisation_energy_eV']==eion
        and all(type(cal[k]) in (int,float) and math.isfinite(cal[k]) and cal[k]>0 for k in ('ionisation_energy_eV','charge_C','peak_V','volts_per_keV'))
        and math.isclose(cal['charge_C'],500000/eion*1.602176634e-19,rel_tol=1e-12)
        and math.isclose(cal['volts_per_keV'],cal['peak_V']/500,rel_tol=1e-12),'Independent signed injection calibration is invalid.')
    rows=iter(json_lines(out/'scalars.jsonl'));sentinel=object()
    counts={key:0 for key in ('initial_primaries','initial_decays','zero_deposit_primaries','groups','accepted','rejected','native_failed_groups','readout_rejected','line_photons','decay_photons')}
    for eid,(source,truth) in enumerate(itertools.zip_longest(source_events(base),json_lines(out/'truth.jsonl'),fillvalue=sentinel)):
        W.require(source is not sentinel and truth is not sentinel and source==truth,'Native result changed or omitted original source truth.')
        W.require(type(source['event_id']) is int and source['event_id']==source['global_decay_id']==eid,'Source primary identities are not complete and ordered.')
        primary=next(rows,sentinel);W.require(primary is not sentinel and primary['record_kind']=='decay'
            and type(primary['event_id']) is type(primary['global_decay_id']) is int and primary['event_id']==primary['global_decay_id']==eid,'Response lost a zero or nonzero original primary.')
        zero=all(step['energy_keV']==0 for step in source['steps'])
        W.require(type(primary['zero_deposit']) is bool and primary['zero_deposit']==zero
            and primary['raw_row_indices']==[step['raw_row_index'] for step in source['steps']]
            and type(primary['pulse_count']) is int and primary['pulse_count']==len(source['pulse_groups'])
            and energy_sum_matches(primary['deposited_energy_keV'],(step['energy_keV'] for step in source['steps']))
            and primary['line_photon_count']==source['line_photon_count'] and primary['decay_photon_count']==source['decay_photon_count']
            and primary['material_energy_keV']==source['material_energy_keV'],'Response primary raw identity or deposition/photon census changed.')
        counts['initial_primaries']+=1;counts['initial_decays']+=1;counts['zero_deposit_primaries']+=zero
        counts['line_photons']+=source['line_photon_count'];counts['decay_photons']+=source['decay_photon_count']
        byrow={step['raw_row_index']:step for step in source['steps']}
        for group in source['pulse_groups']:
            pulse=next(rows,sentinel);W.require(pulse is not sentinel and pulse['record_kind']=='pulse'
                and type(pulse['event_id']) is type(pulse['global_decay_id']) is type(pulse['group_id']) is int
                and pulse['event_id']==pulse['global_decay_id']==eid and pulse['group_id']==group['group_id']
                and pulse['group']==group and pulse['origin_time_ns']==group['origin_time_ns'] and pulse['raw_row_indices']==group['row_indices']
                and energy_sum_matches(pulse['deposited_energy_keV'],(byrow[i]['energy_keV'] for i in group['row_indices']))
                and type(pulse['accepted']) is bool,'Response pulse/group identity or original raw rows changed.')
            failed=pulse.get('status')=='native_transport_failed'
            if failed:
                W.require(pulse['accepted'] is False and all(pulse[k] is None for k in ('readout','final_induced_keV','transport_flags','charge_end_ns',
                    'native_any_negative_charge','native_min_charge_keV','native_max_charge_keV','endpoints','current_nA','induced_charge_fC')),'Native failure invented response quantities.')
            else:W.require(pulse['readout']['accepted'] is pulse['accepted'],'Pulse acceptance differs from independent readout decision.')
            counts['groups']+=1;counts['accepted']+=pulse['accepted'];counts['rejected']+=not pulse['accepted'];counts['native_failed_groups']+=failed
            counts['readout_rejected']+=not failed and not pulse['accepted']
    W.require(next(rows,sentinel) is sentinel,'Unexpected or duplicated response scalar record.')
    W.require(counts['initial_primaries']==resolved['selection']['primary_count'] and all(type(report['counts'][key]) is int and report['counts'][key]==value for key,value in counts.items()),
        'Response summary disagrees with independent complete primary/group census.')
    return counts
