"""Export one measured-in-simulation electrode triplet for the public results page."""
import argparse
from hashlib import sha256
from pathlib import Path
import json
import math

import gegi_event_store as store
import scenario_workflow as workflow
from gegi_digital_saved import from_saved_event


def attach_transport_reference(run, candidates):
    """Evaluate the energy hypotheses against parent interactions after reconstruction."""
    from gegi_parent_gamma_reference import evaluate

    stream = run / 'transport/stream'
    stamps = workflow.read(run / 'COMPLETE.json')['artifacts']
    for name in ('manifest.json', 'events.jsonl'):
        if workflow.sha(stream / name) != stamps['transport/stream/' + name]['sha256']:
            raise ValueError('Transport reference differs from the sealed run.')
    manifest = workflow.read(stream / 'manifest.json')
    processes = {r['procid']: r['name'] for r in manifest['processes']}
    by_id = {row['event_id']: row for row in candidates}
    with (stream / 'events.jsonl').open(encoding='utf-8') as records:
        for line in records:
            event = json.loads(line)
            case = by_id.get(event['event_id'])
            if case is None:
                continue
            native = workflow.read(run / 'response/events' / f"{case['event_id']}.json")
            inputs = {'input_group': {'parent_event_metadata': event},
                      'input_steps': event['steps'], 'steps': native['steps']}
            ref = evaluate(inputs, processes, {'spatial_diagnostics': [], 'candidates': []})
            reference = ref['references']['ge5keV']
            ordered = reference['reference_cells_in_birth_order']
            cells = [site['contact_ids'] for site in case['sites']]
            order = [cells.index(cell) for cell in ordered] if ordered and sorted(ordered) == sorted(cells) else None
            case['transport_reference'] = dict(
                site_index_order=order, status=reference['status'], reason=reference['unknown_reason'],
                significant_interactions=reference['significant_interaction_count'],
                threshold_keV=reference['threshold_keV'], unassigned_energy_keV=ref['unassigned_interaction_energy_keV'],
                processes=[r['birth_process'] for r in sorted(ref['parent_interactions'], key=lambda r: r['birth_time_ns'])
                           if r['deposited_energy_keV'] >= reference['threshold_keV']])
    if any('transport_reference' not in row for row in candidates):
        raise ValueError('A selected candidate is missing from the transport stream.')
    return manifest['events_sha256']


def compact_two_source_check(path, profile_sha256, receipt):
    raw = path.read_bytes()
    report = json.loads(raw)
    if report['kind'] != 'gegi_two_source_energy_order_check_v1' or len(report['runs']) != 2:
        raise ValueError('Expected the sealed two-source energy-order check.')
    sources = []
    for run in sorted(report['runs'], key=lambda run: run['source_position_mm'][0]):
        initial = run['original_counts']['initial_primaries']
        unique = run['energy_unique']
        matched = run['fully_deposited_exact_cell_matches']
        outcomes = run['full_deposit_exact_match_order_outcomes']
        both = outcomes['both_allowed']
        if (run['digital_profile_sha256'] != profile_sha256
                or run['model_sha256'] != receipt['model_sha256']
                or run['field_cache_sha256'] != receipt['fields']['cache_sha256']
                or run['gamma_energy_keV'] != receipt['selection']['gamma_energy_keV']):
            raise ValueError('Two-source check uses a different digitizer, model, field or photon energy.')
        if not 0 <= both <= matched == sum(outcomes.values()) <= unique <= initial:
            raise ValueError('Two-source ordering counts are inconsistent.')
        sources.append(dict(source_position_mm=run['source_position_mm'], initial_primaries=initial,
                            unique_pairings=unique, full_deposit_cell_matches=matched, both_orders_allowed=both))
    return dict(source_sha256=sha256(raw).hexdigest(), sources=sources)


def export(run, event_id, collecting_id, output, validation=None, spectra=None, position_study=None,
           two_source_check=None):
    response = run / 'response'
    receipt = workflow.read(response / 'run.json')
    ref = f'events/{event_id}.json'
    if workflow.sha(response / ref) != receipt['artifacts'][ref]:
        raise ValueError('Event metadata differs from the completed run.')
    event = workflow.read(response / ref)
    replay = from_saved_event(event, receipt['channels'], run,
                              configuration_sha256=receipt['configuration_sha256'],
                              calibration_path=None)
    if collecting_id not in replay['topology']['collecting_contact_ids']:
        raise ValueError('Requested electrode did not pass the digital energy threshold.')
    native = store.native_csv(response / event['signals_ref'], event['channels'])
    metadata = {c['id']: c for c in receipt['channels']}
    digital = {c['contact_id']: c for c in replay['readout']['channels']}
    rows = []
    for cid in (collecting_id - 1, collecting_id, collecting_id + 1):
        meta = metadata[cid]
        if meta['guard'] or meta['family'] != metadata[collecting_id]['family']:
            raise ValueError('This illustration needs two neighboring strips on the same face.')
        rows.append(dict(name=meta['name'], **native[cid], **digital[cid]))
    result = dict(event_id=event_id, collecting_contact_id=collecting_id, channels=rows,
                  counts=receipt['counts'], topology=replay['topology'],
                  native_signals_sha256=event['signals_sha256'], event_sha256=receipt['artifacts'][ref],
                  configuration_sha256=receipt['configuration_sha256'],
                  readout_code_sha256=workflow.sha(Path(__file__).with_name('gegi_digital_readout.py')),
                  profile=replay['readout']['profile'], profile_sha256=replay['readout']['profile_sha256'],
                  pulser_calibration=replay['readout']['calibration'], window=replay['readout']['window'])
    output.mkdir(parents=True, exist_ok=True)
    if validation is not None:
        report = workflow.read(validation)
        if report['digital_profile_sha256'] != result['profile_sha256']:
            raise ValueError('Position check and example use different digitizer profiles.')
        stats = report['paired_comparisons']['independent_native_grid']['cfd_conditioned']['summary']
        result['position_benchmark'] = dict(n=stats['xy']['total'], both=stats['xy']['compared'],
            all_axes=stats['xy']['all_points_strip_center_fallback'], z=stats['depth'],
            energy_keV=report['reference_energy_keV'], trained=report['training_records'],
            coefficients_sha256=report['coefficients_sha256'], evaluation_sha256=workflow.sha(validation))
    if spectra is not None:
        report = workflow.read(spectra)
        if (report['response_receipt_sha256'] != workflow.sha(response / 'run.json')
                or report['digital_profile_sha256'] != result['profile_sha256']):
            raise ValueError('Order results must come from this native run and digitizer profile.')
        candidates = []
        for item in report['events']:
            pair_result = item.get('two_site') or {}
            if pair_result.get('status') != 'unique_energy_pairing':
                continue
            pairing, = [pair for pair in pair_result['pairings'] if pair['energy_compatible']]
            sites = [dict(contact_ids=[s['x_contact_id'], s['y_contact_id']],
                          x_strip=metadata[s['x_contact_id']]['name'], y_strip=metadata[s['y_contact_id']]['name'],
                          energy_keV=s['energy_keV']) for s in pairing['sites']]
            native_ref = f"events/{item['event_id']}.json"
            if workflow.sha(response / native_ref) != receipt['artifacts'][native_ref]:
                raise ValueError('Transport deposit reference differs from the completed run.')
            candidates.append(dict(event_id=item['event_id'], sites=sites, orders=pairing['compton_orders'],
                                   deposited_keV=workflow.read(response / native_ref)['truth_edep_keV'],
                                   source_line=pair_result.get('source_line'), measured_keV=pair_result['energy_keV'],
                                   cone_count=len(pairing['cones'])))
        result['energy_order_check'] = dict(candidates=candidates, spectra_sha256=workflow.sha(spectra),
                                            transport_events_sha256=attach_transport_reference(run, candidates),
                                            response_receipt_sha256=report['response_receipt_sha256'])
    if position_study is not None:
        study = workflow.read(position_study)
        check = result['energy_order_check']
        if (study['digital_profile_sha256'] != result['profile_sha256']
                or study['field_cache_sha256'] != receipt['fields']['cache_sha256']
                or set(study['events']) != {str(c['event_id']) for c in check['candidates']}):
            raise ValueError('Position study uses a different field, digitizer or event selection.')
        mixtures = []
        for c in check['candidates']:
            row = study['events'][str(c['event_id'])]
            if row['native_signals_sha256'] != receipt['artifacts'][f"events/{c['event_id']}-signals.csv"]:
                raise ValueError('Position study refers to different electrode signals.')
            c['fit_error_to_simulated_centroids_mm'] = row['errors_after_fitting']['lateral']['xyz_error_mm']
            mixtures.extend(row['independent_mixtures'])
        check['position_study'] = dict(source_sha256=workflow.sha(position_study), mixtures=len(mixtures))
        for mode in ('centre', 'lateral'):
            errors = [e for mix in mixtures for e in mix['errors'][mode]['xy_error_mm']]
            check['position_study'][mode + '_xy_rms_mm'] = math.sqrt(sum(e*e for e in errors) / len(errors))
    if two_source_check is not None:
        result['energy_order_check']['two_source_check'] = compact_two_source_check(
            two_source_check, result['profile_sha256'], receipt)
    (output / 'event.json').write_text(json.dumps(result, allow_nan=False, separators=(',', ':'))+'\n',
                                       encoding='utf-8', newline='\n')
    plot(result, output / 'signals.png')


def plot(result, destination):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(10, 6), constrained_layout=True)
    colors = ['#a64a11', '#0d526b', '#795299']
    for row, color in zip(result['channels'], colors):
        traces = row['trace']
        for ax, times, values in (
            (axes[0, 0], row['time_ns'], row['signed_induced_keV']),
            (axes[0, 1], traces['time_ns'], traces['digitized_preamp_V']),
            (axes[1, 0], traces['time_ns'], traces['fast_V']),
            (axes[1, 1], traces['time_ns'], traces['slow_V']),
        ):
            native_axis = ax is axes[0, 0]
            if ax is axes[1, 0] and row['contact_id'] == result['collecting_contact_id']:
                continue
            ax.plot(times, values if native_axis else [v * 1000 for v in values], color=color,
                    label=row['name'], lw=2, drawstyle='default' if native_axis else 'steps-post')
    for ax, title, unit in zip(axes.flat, ('Induced charge', 'Digitized preamplifier', 'Fast branch · adjacent strips', 'Slow branch · flat-top energy'),
                               ('Charge equivalent (keV)', 'Voltage (mV)', 'Voltage (mV)', 'Voltage (mV)')):
        ax.set(title=title, xlabel='Time (ns)', ylabel=unit)
        ax.grid(alpha=.2)
        ax.spines[['top','right']].set_visible(False)
    # Show the transient at acquisition scale; the slow panel retains its full gate.
    axes[0,1].set_xlim(0, max(r['time_ns'][-1] for r in result['channels']) + 100)
    axes[1,0].set_xlim(*result['profile']['fast_area_gate_ns'])
    axes[1,1].axvspan(*result['profile']['slow_plateau_gate_ns'], color='#54836a', alpha=.19,
                     label='Energy window')
    axes[1,1].legend(handles=[axes[1,1].patches[-1]], frameon=False)
    axes[0,0].legend(frameon=False)
    fig.savefig(destination, dpi=145, facecolor='white')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--event', type=int, required=True)
    parser.add_argument('--collector', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validation', type=Path, help='Saved independent position check using the same profile')
    parser.add_argument('--spectra', type=Path, help='Saved digital spectrum export with both Compton orders')
    parser.add_argument('--position-study', type=Path, help='Same-event spatial fits and independent position checks')
    parser.add_argument('--two-source-check', type=Path, help='Sealed independent two-source order check')
    args = parser.parse_args()
    if args.position_study and not args.spectra:
        parser.error('--position-study requires --spectra')
    if args.two_source_check and not args.spectra:
        parser.error('--two-source-check requires --spectra')
    export(args.run, args.event, args.collector, args.output, args.validation, args.spectra, args.position_study,
           args.two_source_check)
