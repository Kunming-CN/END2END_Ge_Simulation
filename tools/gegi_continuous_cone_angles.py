"""Evaluate conditional Compton angles on the frozen simultaneous-source acquisition."""

import argparse
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

from gegi_event_store import encoded, sha
from gegi_imaging import cone
from gegi_joint_acquisition_study import REPORT, REFERENCE, REFERENCE_SHA, ROOT
from gegi_joint_imaging import spectral_membership
from gegi_two_site_cfd_study import angle_error, axis_between


def angular_residual(candidate, source_mm):
    """Signed geometric angle to the source minus the energy-derived half angle, degrees."""
    return angle_error(candidate['axis'], axis_between(source_mm, candidate['vertex_mm'])) - candidate['half_angle_deg']


def calculate(acquisition, fitted, truth):
    measured = [t for t in acquisition['triggers'] if t.get('two_strip_pairings')]
    layers = spectral_membership([SimpleNamespace(energy_keV=t['energy_keV']) for t in measured])
    hypotheses, counts = [], Counter()
    for i, (trigger, result) in enumerate(zip(measured, fitted['candidates'], strict=True)):
        if trigger['trigger_time_ns'] != result['time_ns']:
            raise ValueError('Joint fit refers to a different trigger')
        layer, = [name for name, mask in layers.items() if mask[i]]
        if layer == 'other_energy':
            continue
        counts['in_line_windows'] += 1
        geometry = []
        for fit, pair in zip(result['pairings'], trigger['two_strip_pairings']['pairings'], strict=True):
            if (fit['index'], fit['energy_compatible']) != (pair['index'], pair['energy_compatible']):
                raise ValueError('Saved energy pairing has changed')
            if not pair['energy_compatible']:
                continue
            for mode, fits in fit['fit'].get('fits', {}).items():
                center = fits['center']
                if not center['optimizer_success']:
                    continue
                sites = [dict(energy_keV=site['energy_keV'], position_mm=xyz) for site, xyz in
                         zip(pair['sites'], center['positions_mm'], strict=True)]
                for order in pair['compton_orders']:
                    if order['kinematically_allowed']:
                        first, second = order['site_index_order']
                        candidate = cone(sites[first], sites[second])
                        if candidate is not None:
                            geometry.append(dict(pairing=pair['index'], order=[first, second], method=mode, **candidate))
        if geometry:
            counts['with_conditional_geometry'] += 1
        hypotheses.append(dict(ordinal=i+1, energy_keV=trigger['energy_keV'], layer=layer, geometry=geometry))

    source_positions = {s['key']: s['original']['source_position_mm'] for s in acquisition['sources']}
    for row in hypotheses:
        ref = truth['candidates'][row['ordinal']-1]
        if (not ref['comparison'] or ref['reference']['containment'] != 'full_energy_at_photon_birth'
                or ref['association'] != 'unique_matched'):
            continue
        source = ref['deposit_groups'][0]['source']
        comparison = ref['comparison']
        row['transport_reference'] = dict(source=source, source_mm=source_positions[source],
            campaign_initial_id=ref['deposit_groups'][0]['campaign_initial_id'],
            truth_order=comparison['truth_site_index_order'], truth_pairing=comparison['truth_pairing_index'])
        counts['exact_two_interaction_full_energy_references'] += 1
        for candidate in row['geometry']:
            candidate['source_residual_deg'] = angular_residual(candidate, source_positions[source])
    return dict(kind='gegi_simulated_continuous_cone_angles_v1', trigger_denominator=acquisition['counts']['qualified_triggers'],
                two_strip_denominator=len(measured), counts=counts, energy_layer_counts=Counter(h['layer'] for h in hypotheses),
                definition='All allowed orders for one fully absorbed photon at two sites. Both position methods use strip centers in XY. '
                           'The reference source enters only after energy-window selection and reconstruction.',
                residual='Signed source-to-cone angular residual in degrees. Repeated method estimates use the same triggers.',
                candidates=hypotheses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output
    if output.exists():
        raise FileExistsError(output)
    inputs = [(REPORT, '0c5111b47ab7f84f1ddf0514b04484c8a86e167cf179111f79bb0d0d8fed453a'),
              (ROOT / '.local/gegi-joint-two-site/continuous.json', '60464256affddba3c5ff784fbc786ed24ee6e60c843a55238085ca757bacb218'),
              (REFERENCE, REFERENCE_SHA)]
    data = []
    for path, digest in inputs:
        raw = path.read_bytes()
        if sha(raw) != digest:
            raise ValueError('Changed input: ' + path.name)
        data.append(json.loads(raw))
    result = calculate(*data)
    result['input_sha256'] = {path.relative_to(ROOT).as_posix(): digest for path, digest in inputs}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as out:
        out.write(encoded(result) + b'\n')
    print(json.dumps(result['counts']))


if __name__ == '__main__':
    main()
