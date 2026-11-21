"""Exact energy-support closures of a saved empirical angular-hat mixture."""

import argparse
import math
from pathlib import Path

import numpy as np

import gegi_compton_energy_kernel as kernel
import gegi_empirical_compton_joint as joint
from gegi_photon_continuation import ELECTRON_REST_KEV
import scenario_workflow as W


def merge_intervals(intervals):
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], high)
        else:
            merged.append([float(low), float(high)])
    return merged


def transport(residuals, free_energy, incident):
    return np.where(residuals > 0., incident-(1-residuals)*(incident-free_energy), free_energy*(1+residuals))


def support(receipt, incident):
    """Map each archived atom through the endpoints of its hat's cosine support.

    The native-mass free energy increases with cosine. The signed residual
    map has slope 1+r for r<=0 or 1-r for r>0 with respect to free energy.
    Thus the endpoints bound the entire continuous image. A hat's zero
    endpoint may be reached only as a limit, so report support closures.
    """
    energies = receipt['incident_energies_keV']
    if incident not in energies:
        return dict(incident_keV=incident, status='incident_energy_unrepresented')
    model = joint.angular_model(receipt, incident)
    bins = receipt['incident_groups'][energies.index(incident)]['livermore_bins']
    mass = receipt['native_metadata']['native_electron_rest_keV']
    hats, ranges = [], []
    for j, group in enumerate(bins):
        if model['masses'][j] == 0.:
            continue
        cos_low, cos_high = map(float, model['x'][[j, j+2]])
        residuals = np.asarray(group['development_residual_atoms'])
        if np.any(np.abs(residuals) > 1) or not np.isfinite(residuals).all() or residuals.size == 0:
            raise ValueError('Use valid archived bounded residual atoms for each populated angular hat')
        lo = transport(residuals, kernel.free_outgoing(incident, cos_low, mass), incident)
        hi = transport(residuals, kernel.free_outgoing(incident, cos_high, mass), incident)
        indices = group['development_sample_indices']
        extrema = []
        for values, index, cosine in ((lo, int(lo.argmin()), cos_low), (hi, int(hi.argmax()), cos_high)):
            extrema.append(dict(energy_keV=float(values[index]), cosine=cosine,
                                development_sample_index=indices[index], residual=float(residuals[index])))
        ranges.extend(zip(lo, hi, strict=True))
        hats.append(dict(bin_index=j, cosine_support_closure=[cos_low, cos_high],
                         mixture_mass=float(model['masses'][j]), atom_count=len(indices),
                         minimum=extrema[0], maximum=extrema[1]))
    outgoing = merge_intervals(ranges)
    # The second scatter spans continuously from backscatter to forward.
    # Its minimum increases with the incoming atom energy.
    second = merge_intervals((a/(1+2*a/ELECTRON_REST_KEV), b) for a, b in outgoing)
    lowest = min(hats, key=lambda row: row['minimum']['energy_keV'])
    highest = max(hats, key=lambda row: row['maximum']['energy_keV'])
    return dict(incident_keV=incident, status='archived_empirical_measure',
                outgoing_support_closure_keV=outgoing, second_outgoing_support_closure_keV=second,
                minimum=dict(bin_index=lowest['bin_index'], **lowest['minimum']),
                maximum=dict(bin_index=highest['bin_index'], **highest['maximum']),
                second_backscatter_minimum_keV=second[0][0], hats=hats)


def missing_ranges(intervals, low, high):
    return dict(below_table_keV=[[a, min(low, b)] for a, b in intervals if a < low],
                above_table_keV=[[max(high, a), b] for a, b in intervals if b > high])


def run(args):
    W.require(not args.output.exists(), 'Select a fresh global-support evidence path')
    receipt = W.read(args.kernel)
    reference = W.read(args.joint)
    rate_support = W.read(args.rate_support)
    kernel_sha, rates_sha = W.sha(args.kernel), W.sha(args.rate_support)
    source = reference['baseline_recipe']
    W.require(kernel_sha == source['empirical_kernel_sha256'] == rate_support['kernel_sha256'] and
              rates_sha == source['rate_support_sha256'] and W.sha(joint.__file__) == reference['source_sha256'],
              'Use the exact joint model, archived kernel and initialized rate receipts')
    bank = joint.response.bank
    _, plan, basis, rates, _, _ = bank.setup(args.measured_plan, args.plan, args.probe, args.new_rates)
    request_file = args.coefficient_extension/'request.json'
    request = W.read(request_file)
    extra, binding = bank.trial.verified_extension(args.coefficient_extension, W.sha(request_file),
                                                   basis['original_rate_basis'], request['new_query_energies_keV'])
    W.require(request['base_coefficients'] == basis and not rates.keys() & extra.keys() and
              W.sha(request_file) == rate_support['request_sha256'] and
              binding == rate_support['coefficient_binding'] == source['coefficient_binding'],
              'Use the sealed base rate table and lower coefficient anchors')
    rates |= extra
    low, high = min(rates), max(rates)
    W.require([low, high] == rate_support['extended_coefficient_support_keV'], 'Rate interval differs from acceptance')
    lines = []
    for incident in receipt['incident_energies_keV']:
        row = support(receipt, incident)
        ranges = row['outgoing_support_closure_keV']
        escape = row['second_outgoing_support_closure_keV']
        row['coefficient_gaps'] = dict(incident=missing_ranges([[incident, incident]], low, high),
                                       intermediate=missing_ranges(ranges, low, high),
                                       second_outgoing=missing_ranges(escape, low, high))
        lines.append(row)
    result = dict(kind='gegi_empirical_joint_global_energy_support_v1', source_sha256=W.sha(__file__),
                  joint_receipt_sha256=W.sha(args.joint), empirical_kernel_sha256=kernel_sha,
                  rate_support_sha256=rates_sha, base_rate_basis=basis, added_rate_binding=binding,
                  initialized_coefficient_support_keV=[low, high], initialized_coefficient_count=len(rates),
                  native_first_scatter_electron_rest_keV=receipt['native_metadata']['native_electron_rest_keV'],
                  free_second_scatter_electron_rest_keV=ELECTRON_REST_KEV, lines=lines,
                  prior_interpolation_log_spacing=plan['rate_request']['prior_interpolation_log_spacing'],
                  unrepresented_lines=[support(receipt, v) for v in receipt['explicit_unrepresented_incident_energies_keV']],
                  scope='Support closures of the empirical hat/atom measure. A zero-weight hat endpoint can be a limit. '
                        'Coefficient intervals describe existing initialized rates. No new rates or curve domains are inferred.')
    with args.output.open('xb') as out:
        out.write(W.encoded(result)+b'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('joint', 'kernel', 'rate-support', 'probe', 'measured-plan', 'plan', 'new-rates',
                   'coefficient-extension', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    result = run(parser.parse_args())
    for row in result['lines']:
        print(row['incident_keV'], row['outgoing_support_closure_keV'], row['second_backscatter_minimum_keV'],
              row['coefficient_gaps'])


if __name__ == '__main__':
    main()
