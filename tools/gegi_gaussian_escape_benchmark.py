"""Compare probability-variable quadrature with one frozen escape curve and witnesses."""

import argparse
from pathlib import Path
import time

import numpy as np

import gegi_candidate_trial_curve_bank as bank
import gegi_gaussian_escape_quadrature as transformed
import gegi_photon_observed_energy as direct
import scenario_workflow as W


LOG = 'log_escape_per_mm_observed_keV'


def run(probe, output):
    W.require(not output.exists(), 'Use a new quadrature evidence path')
    _, _, basis, rates, crystal, _ = bank.setup(probe/'measured-response-plan.json',
                                                probe/'source-trial-response-plan.json', probe, probe/'source-trial-rates')
    f, total = bank.trial.rate_functions(rates)
    files = {label: probe/name for label, name in
             [('curve', 'escape-response-curve-refined.json'),
              ('positive_tail', 'trial-curve-positive-tail-witness.json'),
              ('underflow', 'log-density-endpoint-acceptance.json')]}
    curve, positive, underflow = (W.read(p) for p in files.values())
    W.require(curve['original_rate_basis'] == basis['original_rate_basis'] and positive['basis'] == basis and
              all(row['source_sha256'][Path(direct.__file__).name] == W.sha(direct.__file__)
                  for row in (curve, positive, underflow)), 'Use the initialized inputs and frozen positive quadrature references')
    representative = curve['branches'][1]
    settings = curve['settings']
    samples, sigma = settings['azimuth_samples'], settings['sigma_second_keV']
    orders = (8, 16, 32, 64)

    def evaluate(first, second, energy, observed, order, fn):
        args = crystal, first, second, energy, f(energy), total
        started = time.perf_counter()
        if fn == 'positive_gl':
            result = direct.observed_continuation(*args, [observed], sigma_keV=sigma,
                     azimuth_samples=samples, energy_order=order, include_log=True)['observations'][0]
        else:
            result = transformed.observed_escape(*args, observed, sigma_keV=sigma,
                                                  azimuth_samples=samples, energy_order=order)
        return dict(result, wall_seconds=time.perf_counter()-started)

    def compare(first, second, energy, observed, reference, **metadata):
        cases = []
        for order in orders:
            r = evaluate(first, second, energy, observed, order, 'probability_gl')
            cases.append(dict(r, order=order, log_difference=r[LOG]-reference))
        return dict(metadata, intermediate_keV=energy, observed_keV=observed,
                    frozen_log_escape=reference, estimates=cases)

    first, second = representative['first_fitted_mm'], representative['second_fitted_mm']
    observed = representative['measured_second_site_keV']
    rows = representative['comparison']['held_out']
    curve_results = [compare(first, second, row['intermediate_keV'], observed, row['log_escape_density'])
                     for row in rows]
    # Time a fixed spread of the same heldout curve energies against the old
    # call on this machine. The old call also reports integrated unobserved mass.
    timing = []
    for index in np.linspace(0, len(rows)-1, 5, dtype=int):
        row = rows[index]
        old = evaluate(first, second, row['intermediate_keV'], observed, settings['energy_order'], 'positive_gl')
        timing.append(dict(heldout_index=int(index), reproduced_reference_difference=old[LOG]-row['log_escape_density'],
                           frozen_seconds=old['wall_seconds'],
                           by_order_seconds={str(r['order']): r['wall_seconds'] for r in curve_results[index]['estimates']}))

    witnesses = []
    for row in underflow['measured_fixed_first_witnesses']:
        o = row['observations']
        witnesses.append(compare(row['first_mm'], row['second_mm'], row['fixed_intermediate_keV'], o['observed_keV'], o[LOG],
                                 origin='saved_fixed_first', original_trigger_id=row['original_trigger_id'],
                                 frozen_density_status=o['escape_density_status']))
    model = positive['model']
    for row in positive['witness']:
        o = row['new_order_512']
        witnesses.append(compare(model['first_fitted_mm'], model['second_fitted_mm'], o['intermediate_keV'],
                                 model['measured_second_site_keV'], o['log_escape_density'], origin='saved_positive_tail',
                                 frozen_density_status=o['density_status']))
    energy = rows[len(rows)//2]['intermediate_keV']
    lowest, _ = transformed.photon.outgoing_energy_model(energy)
    for edge in (0., energy-lowest):
        old = evaluate(first, second, energy, edge, 512, 'positive_gl')
        witnesses.append(compare(first, second, energy, edge, old[LOG], origin='physical_deposit_edge',
                                 frozen_density_status=old['escape_density_status'], frozen_reference=old))

    result = dict(kind='gegi_gaussian_escape_probability_quadrature_v1', basis=basis, software=bank.software(),
                  source_sha256={Path(p).name: W.sha(p) for p in (__file__, transformed.__file__, direct.__file__)},
                  references_sha256={k: W.sha(p) for k, p in files.items()}, azimuth_samples=samples,
                  sigma_keV=sigma, representative_curve=dict(original_trigger_id=representative['original_trigger_id'],
                      pair_index=representative['pair_index'], site_index_order=representative['site_index_order'],
                      heldout=curve_results, paired_timings=timing), witnesses=witnesses,
                  acceptance_log_error_target=settings['max_log_error_target'])
    with output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.probe, args.output)
    for i, order in enumerate((8, 16, 32, 64)):
        print(order, *(max(abs(r['estimates'][i]['log_difference']) for r in group) for group in
                        (report['representative_curve']['heldout'], report['witnesses'])))
