"""Independent streamed saved-result census; no native work or calibration."""
from pathlib import Path
import csv,math
import scenario_workflow as W
import nonzero_events as N
from ring_workflow import energy_sum_matches
from local_ui_jobs import safe_path

def json_lines(path):
    with Path(path).open(encoding='utf-8') as rows:
        for line in rows:yield W.decode_json(line)

def source_events(directory,manifest=None):
    base=Path(directory)/'transport/stream';manifest=manifest or W.read(base/'manifest.json')
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
    initial=resolved['selection']['primary_count'];manifest=W.read(base/'transport/stream/manifest.json')
    policy=N.storage(report,report['counts'],initial_primaries=initial)
    source_policy=N.storage(manifest,initial_primaries=initial)
    if policy is not None:counts['nonzero_primaries']=0
    if source_policy is not None:
        W.require(policy==source_policy,'Sparse source and response event-storage census differ.')
        summary=N.initial_summary(manifest)
        counts.update({key:summary[key] for key in ('initial_primaries','initial_decays','zero_deposit_primaries','nonzero_primaries','line_photons','decay_photons')})
    truth_rows=iter(json_lines(out/'truth.jsonl'));signal_groups=set()
    stored_photons={'line_photons':0,'decay_photons':0}
    named=None
    selected=resolved['selection'].get('source')
    if selected not in (None,W.CS,W.GAMMA):
        import histogram_normalization as H
        contract=resolved.get('source_contract',resolved.get('decay_source_contract'))
        normal=H.descriptor(selected,contract)
        named={line['name']:0 for line in normal['diagnostic_lines']}
        if source_policy is not None:
            W.require(type(summary.get('line_photon_counts')) is dict,'Sparse source omitted its named photon census.')
            H.check_diagnostic_counts(summary.get('line_photon_counts'),summary)
            W.require(set(summary['line_photon_counts'])==set(named),'Sparse source changed its named photon windows.')
    stored_named=None if named is None else dict(named)
    for source in N.source_sequence(source_events(base,manifest),source_policy,initial):
        eid=source['event_id'];zero=not N.has_nonzero_deposit(source)
        if source_policy is None:
            counts['initial_primaries']+=1;counts['initial_decays']+=1;counts['zero_deposit_primaries']+=zero
            if policy is not None:counts['nonzero_primaries']+=not zero
            counts['line_photons']+=source['line_photon_count'];counts['decay_photons']+=source['decay_photon_count']
            if named is not None:H.add_diagnostic_event(named,source)
        else:
            stored_photons['line_photons']+=source['line_photon_count'];stored_photons['decay_photons']+=source['decay_photon_count']
            if stored_named is not None:H.add_diagnostic_event(stored_named,source)
        if policy is not None and zero:continue
        truth=next(truth_rows,sentinel)
        W.require(truth is not sentinel and source==truth,'Native result changed or omitted original stored source truth.')
        primary=next(rows,sentinel);W.require(primary is not sentinel and primary['record_kind']=='decay'
            and type(primary['event_id']) is type(primary['global_decay_id']) is int and primary['event_id']==primary['global_decay_id']==eid,'Response lost a zero or nonzero original primary.')
        W.require(type(primary['zero_deposit']) is bool and primary['zero_deposit']==zero
            and primary['raw_row_indices']==[step['raw_row_index'] for step in source['steps']]
            and type(primary['pulse_count']) is int and primary['pulse_count']==len(source['pulse_groups'])
            and energy_sum_matches(primary['deposited_energy_keV'],(step['energy_keV'] for step in source['steps']))
            and primary['line_photon_count']==source['line_photon_count'] and primary['decay_photon_count']==source['decay_photon_count']
            and primary['material_energy_keV']==source['material_energy_keV'],'Response primary raw identity or deposition/photon census changed.')
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
            if not failed:signal_groups.add((eid,group['group_id']))
            counts['groups']+=1;counts['accepted']+=pulse['accepted'];counts['rejected']+=not pulse['accepted'];counts['native_failed_groups']+=failed
            counts['readout_rejected']+=not failed and not pulse['accepted']
    W.require(next(truth_rows,sentinel) is sentinel,'Unexpected or duplicated response truth record.')
    W.require(next(rows,sentinel) is sentinel,'Unexpected or duplicated response scalar record.')
    if source_policy is not None:
        W.require(all(stored_photons[key]<=counts[key] for key in stored_photons),'Stored photons exceed the complete source census.')
        if named is not None:
            W.require(all(stored_named[key]<=summary['line_photon_counts'][key] for key in named),'Stored named photons exceed the complete source census.')
            named=summary['line_photon_counts']
    W.require(counts['initial_primaries']==resolved['selection']['primary_count'] and all(type(report['counts'][key]) is int and report['counts'][key]==value for key,value in counts.items()),
        'Response summary disagrees with independent complete primary/group census.')
    if named is not None:
        H.check_diagnostic_counts(named,report['counts']);counts['line_photon_counts']=named
    if policy is not None:
        N.validate_storage(policy,counts,initial_primaries=initial)
        for name in ('traces.jsonl','endpoints.jsonl'):
            for row in json_lines(out/name):
                W.require(type(row.get('event_id')) is int and type(row.get('group_id')) is int
                    and (row['event_id'],row['group_id']) in signal_groups,
                    'Sparse response retained an uncomputed or zero-input signal: '+name)
        signal_path=out/'signals.csv'
        if signal_path.exists():
            with signal_path.open(encoding='utf-8',newline='') as stream:
                for row in csv.DictReader(stream):
                    try:
                        key=(int(row['event_id']),int(row['group_id']))
                        W.require(int(row['global_decay_id'])==key[0],'Sparse signed signal changed its original decay ID.')
                        if 'batch' in report:
                            batch=report['batch']
                            W.require(int(row['local_initial_id'])==key[0] and int(row['global_initial_id'])==batch['global_initial_offset']+key[0]
                                and int(row['batch_index'])==batch['batch_index'],'Sparse signed signal changed its original batch/global identity.')
                    except (KeyError,ValueError):W.require(False,'Invalid sparse signed-signal identity.')
                    W.require(key in signal_groups,'Sparse response retained an uncomputed or zero-input signed signal.')
    return counts
