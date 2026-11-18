"""Accumulate nominal digital fast and slow spectra from a completed standalone GeGI run."""
from collections import Counter
import argparse
import json
import math
from pathlib import Path

import scenario_workflow as W
from gegi_digital_saved import from_saved_event
from gegi_digital_readout import PROFILE_SHA256


def spectra(run):
    response = run / 'response'
    receipt = W.read(response / 'run.json')
    complete = W.read(run / 'COMPLETE.json')
    if complete['artifacts']['response/run.json']['sha256'] != W.sha(response / 'run.json'):
        raise ValueError('The native response receipt differs from the completed run.')
    meta = receipt['channels']
    strips = {ch['id']: {'name': ch['name'], 'fast': Counter(), 'slow': Counter(),
                         'missing_fast': 0, 'missing_slow': 0} for ch in meta if not ch['guard']}
    groups = []
    valid = Counter()
    for pid in receipt['nonzero_event_ids']:
        ref = f'events/{pid}.json'
        if W.sha(response / ref) != receipt['artifacts'][ref]:
            raise ValueError('Original event differs from the native receipt: ' + ref)
        event = W.read(response / ref)
        replay = from_saved_event(event, meta, run, configuration_sha256=receipt['configuration_sha256'],
                                  include_traces=False)
        if replay['status'] == 'unavailable':
            groups.append({'event_id': pid, 'status': 'unavailable', 'reason': replay['reason']})
            for strip in strips.values():
                strip['missing_fast'] += 1
                strip['missing_slow'] += 1
            continue
        for ch in replay['readout']['channels']:
            strip = strips.get(ch['contact_id'])
            if strip is None:
                continue
            for name, key in [('fast', 'fast_signal_keV_equiv'), ('slow', 'slow_energy_keV')]:
                value = ch[key]
                if value is None:
                    strip['missing_'+name] += 1
                else:
                    strip[name][math.floor(value)] += 1
        result = replay['topology']
        valid[result['status']] += 1
        groups.append({'event_id': pid, 'status': result['status'], 'topology': result,
                       'position': replay['position'], 'two_site': replay['pairs'],
                       'readout_flags': replay['readout']['flags']})
    return {'kind': 'gegi_digital_spectra_v1', 'configuration_sha256': receipt['configuration_sha256'],
            'digital_profile_sha256': PROFILE_SHA256, 'original_counts': receipt['counts'],
            'selection': 'One entry per strip and available feature per saved nonzero primary. '
                         'Slow energies apply the digital detection threshold. Guards excluded from strip histograms.',
            'binning': 'Sparse lower edges, half-open width 1 keV for slow and 1 keV-equivalent for fast.',
            'digital_topology_counts': valid, 'strips': strips, 'events': groups}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = spectra(args.run)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, allow_nan=False, separators=(',', ':'))
        stream.write('\n')
    print(json.dumps(result['digital_topology_counts']))
