"""Export one measured-in-simulation electrode triplet for the public results page."""
import argparse
from pathlib import Path
import json

import gegi_event_store as store
import scenario_workflow as workflow
from gegi_digital_saved import from_saved_event


def export(run, event_id, collecting_id, output, validation=None):
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
    args = parser.parse_args()
    export(args.run, args.event, args.collector, args.output, args.validation)
