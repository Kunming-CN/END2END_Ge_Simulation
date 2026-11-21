"""Empirical Livermore Eout response conditional on the true scattering cosine.

The normalized discrete energy measure comes from one direct native model
call per sample. A consumer must pass each same outgoing-energy atom through
both energy measurements and the second-site continuation before averaging.
Keep the mass at atoms outside the continuation's numerical domain explicit.
The empirical kernel supplies neither an angular prior nor detector selection.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


ARCHIVE_SHA256 = {
    'completion': 'ce02d38a16b9c19f28f0520549c6a776e9af595b345aaa203f0320825096c5ee',
    'request': '27e2a9c88f5b4431b969b01dc40ae6e5da1952bcbb296054e4e49587fd845434',
    'metadata': 'c5460ae9c6c9613aa720d8ff149d1dfea7261f33ab5cab4d91ae960dca2a30dc',
    'samples': '609a433fa0e8bfa2fde2959f9c0ee6228be38ee853d7b7c6dc11ef5cd29a9ac6',
}
QUANTILES = (.025, .05, .16, .5, .84, .95, .975)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_outgoing(incident_keV, cosine, mass_keV):
    return incident_keV/(1+(incident_keV/mass_keV)*(1-cosine))


def residual_atom(outgoing, center, incident):
    """Express a residual as a fraction of distance to its physical endpoint."""
    return (outgoing-center)/(incident-center if outgoing > center else center)


def conditional_nodes(receipt, incident_keV, cosine, *, curve_support_keV=None):
    """Return all node energies and masses. Supplying an interval only marks coverage."""
    if not (math.isfinite(incident_keV) and incident_keV > 0 and math.isfinite(cosine) and -1 <= cosine <= 1):
        raise ValueError('Use a positive incident energy in keV and a physical scattering cosine')
    energies = receipt['incident_energies_keV']
    if incident_keV not in energies:
        return dict(status='incident_energy_unrepresented', incident_keV=incident_keV, represented_energies_keV=energies,
                    outgoing_energies_keV=None, weights=None)
    group = receipt['incident_groups'][energies.index(incident_keV)]
    centers = receipt['cosine_bin_centers']
    hi = int(np.searchsorted(centers, cosine, side='right'))
    if hi == 0 or hi == len(centers):
        mixture = [(0 if hi == 0 else hi-1, 1.)]
    else:
        frac = (cosine-centers[hi-1])/(centers[hi]-centers[hi-1])
        mixture = [(hi-1, 1-frac), (hi, frac)] if frac else [(hi-1, 1.)]
    free = free_outgoing(incident_keV, cosine, receipt['native_metadata']['native_electron_rest_keV'])
    nodes, weights = [], []
    for index, mass in mixture:
        atoms = np.asarray(group['livermore_bins'][index]['development_residual_atoms'])
        if not atoms.size:
            return dict(status='missing_angular_bin', incident_keV=incident_keV, angular_bin_weights=mixture,
                        outgoing_energies_keV=None, weights=None)
        nodes.append(np.where(atoms > 0., incident_keV-(1-atoms)*(incident_keV-free), free*(1+atoms)))
        weights.append(np.full(len(atoms), mass/len(atoms)))
    nodes, weights = np.concatenate(nodes), np.concatenate(weights)
    result = dict(status='empirical_conditional_nodes', incident_keV=incident_keV, cosine=cosine,
                  free_outgoing_keV=free, outgoing_energies_keV=nodes, weights=weights, angular_bin_weights=mixture)
    if curve_support_keV is not None:
        lower, upper = curve_support_keV
        if not (math.isfinite(lower) and math.isfinite(upper) and 0. < lower <= upper):
            raise ValueError('Supply a finite positive continuation interval in keV')
        mask = (lower <= nodes) & (nodes <= upper)
        result.update(covered_mask=mask, covered_mass=math.fsum(weights[mask]), uncovered_mass=math.fsum(weights[~mask]))
    return result


def load_archive(root):
    paths = dict(completion=root/'COMPLETE.json', request=root/'request.json', metadata=root/'results/native.json',
                 samples=root/'results/samples.csv')
    if {k: digest(p) for k, p in paths.items()} != ARCHIVE_SHA256:
        raise ValueError('Select the exact archived Geant4 Compton samples and metadata')
    complete, request, meta = (json.loads(paths[k].read_bytes()) for k in ('completion', 'request', 'metadata'))
    if (complete['status'] != 'complete' or complete['returncode'] or not all(complete['checks'].values())
            or complete['request_sha256'] != ARCHIVE_SHA256['request']
            or complete['artifacts']['samples.csv']['sha256'] != ARCHIVE_SHA256['samples']
            or complete['artifacts']['native.json']['sha256'] != ARCHIVE_SHA256['metadata']
            or request['source_sha256'] != complete['source_sha256']
            or meta['model_names'] != request['models'] or meta['geant4_version_number'] != 1132
            or meta['material'] != 'G4_Ge' or meta['atomic_deexcitation'] or meta['registered_geometry_or_transport']
            or meta['couple_index'] != 0 or meta['binding_energy_policy'] != 'native local deposit'):
        raise ValueError('Archived native model, initialization or sample bindings differ')

    groups, recorded, failures = {}, {}, []
    for g in complete['groups']:
        key = (g['model_id'], g['energy_index'])
        groups[key], recorded[key] = [], set()
    worst_closure = 0.
    with paths['samples'].open(newline='') as stream:
        for row in csv.DictReader(stream):
            model, line = int(row['model_id']), int(row['energy_index'])
            index, key = int(row['sample_index']), (model, line)
            incident = request['energies_keV'][line]
            if (key not in recorded or index in recorded[key] or not 0 <= index < request['samples_per_energy'][model]
                    or int(row['seed']) != request['seeds'][model][line] or float(row['E0_keV']) != incident):
                raise ValueError('Native sample identity, seed or energy roster differs')
            recorded[key].add(index)
            if row['status'] != 'sampled' or not row['cos_true'] or not row['cos_free_native_mass']:
                failures.append(row)
                continue
            cosine, outgoing, inverse, closure = (float(row[k]) for k in ('cos_true', 'Eout_keV', 'cos_free_native_mass', 'closure_keV'))
            if not (-1 <= cosine <= 1 and 0 < outgoing <= incident and math.isfinite(inverse)
                    and abs(closure) <= request['energy_closure_tolerance_keV']):
                failures.append(row)
                continue
            worst_closure = max(worst_closure, abs(closure))
            groups[key].append((index, cosine, outgoing, not -1 <= inverse <= 1))
    missing = [{'model_id': m, 'energy_index': e, 'sample_indices': sorted(set(range(request['samples_per_energy'][m]))-indices)}
               for (m, e), indices in recorded.items() if len(indices) != request['samples_per_energy'][m]]
    return complete, request, meta, groups, failures, missing, worst_closure


def describe(residual):
    values = np.asarray(residual)
    return (dict(count=len(values), mean_keV=float(values.mean()), rms_keV=float(np.sqrt(np.mean(values**2))),
                 range_keV=[float(values.min()), float(values.max())], quantiles_keV=np.quantile(values, QUANTILES).tolist())
            if values.size else dict(count=0))


def heldout_predictions(receipt, incident, samples):
    """Compute per-draw CRPS, central coverage and mid-P CDF ranks."""
    checks = []
    native_mass = receipt['native_metadata']['native_electron_rest_keV']
    free_min = free_outgoing(incident, -1., native_mass)
    for _, cosine, actual, inverse_invalid in samples:
        result = conditional_nodes(receipt, incident, cosine)
        if result['weights'] is None:
            continue
        nodes, weights = result['outgoing_energies_keV'], result['weights']
        order = np.argsort(nodes)
        nodes, weights = nodes[order], weights[order]
        cumulative = np.cumsum(weights)
        quantiles = nodes[np.searchsorted(cumulative, QUANTILES)]
        delta = nodes-actual
        crps = float(weights @ (np.abs(delta)-delta*(2*cumulative-weights-1)))
        pit = math.fsum(weights[nodes < actual]) + .5*math.fsum(weights[nodes == actual])
        checks.append((crps, abs(result['free_outgoing_keV']-actual), pit,
                       quantiles[2] <= actual <= quantiles[-3], quantiles[1] <= actual <= quantiles[-2],
                       quantiles[0] <= actual <= quantiles[-1], math.fsum(weights[nodes < free_min]), inverse_invalid))
    return checks


def heldout_scores(checks, count):
    if not checks:
        return dict(heldout_count=count, scored=0)
    array = np.asarray(checks)
    return dict(heldout_count=count, scored=len(checks), crps_mean_keV=float(array[:, 0].mean()),
                native_free_point_crps_mean_keV=float(array[:, 1].mean()),
                central_68_90_95_counts=np.count_nonzero(array[:, 3:6], axis=0).tolist(),
                expected_heldout_free_inadmissible_mass=float(array[:, 6].sum()),
                observed_heldout_free_inadmissible_count=int(array[:, 7].sum()),
                mid_p_cdf_decile_counts=np.histogram(array[:, 2], bins=np.linspace(0., 1., 11))[0].tolist())


def separated_samples(samples, edges):
    bins = [[[], []] for _ in edges[:-1]]
    for sample in samples:
        index, cosine, _, _ = sample
        i = min(len(bins)-1, int(np.searchsorted(edges, cosine, side='right'))-1)
        bins[i][int(index % 5 == 0)].append(sample)
    return bins


def build(root, cosine_bins=16):
    if type(cosine_bins) is not int or cosine_bins < 1:
        raise ValueError('Use a positive number of cosine bins')
    complete, request, meta, groups, failures, missing, worst = load_archive(root)
    edges = np.linspace(-1., 1., cosine_bins+1)
    mass = meta['native_electron_rest_keV']
    energies = request['energies_keV']
    result = dict(kind='gegi_native_compton_conditional_energy_kernel_v1', input_sha256=ARCHIVE_SHA256, native_metadata=meta,
                  sampler_source_sha256=complete['source_sha256'], initialized_build_sha256=complete['build_sha256'],
                  native_data_release=dict(name=request['dataset'], version=request['dataset_version'],
                                           availability_sha256=request['availability_sha256']),
                  producer_sha256=digest(Path(__file__)), incident_energies_keV=energies,
                  explicit_unrepresented_incident_energies_keV=[661.657], cosine_bin_edges=edges.tolist(),
                  cosine_bin_centers=((edges[:-1]+edges[1:])/2).tolist(), residual_statistics_quantiles=QUANTILES,
                  incident_groups=[], invalid_source_rows=failures, missing_source_rows=missing, max_abs_energy_closure_keV=worst,
                  native_seed_by_model_and_energy=request['seeds'], native_expected_samples_per_energy=request['samples_per_energy'],
                  split='Holdout sample_index mod 5 == 0 within each native model/energy group; all other indices develop the kernel.',
                  kernel='Livermore: uniform empirical atoms per actual-cosine bin; linear mixture between neighboring bin centers, '
                         'edge bin at each physical cosine endpoint. This is an empirical angular interpolation approximation. '
                         'Residuals relative to the native-mass free curve scale by '
                         'distance to the corresponding physical energy bound (0 or incident energy). At exact forward angle '
                         'positive atoms collapse onto the upper physical endpoint. No interpolation across incident energies.',
                  scope='Direct archived Geant4 native model samples. Manual material-cuts couple, local binding deposition and disabled '
                        'atomic deexcitation. Free Klein-Nishina is a separate deterministic energy control. Heldout metrics describe '
                        'only these direct-model samples. No detector resolution, source position, event or angular prior, transport '
                        'acceptance, or production reconstruction changed.')
    for i, incident in enumerate(energies):
        livermore = separated_samples(groups[0, i], edges)
        control = separated_samples(groups[1, i], edges)
        livermore_n = sum(len(development) for development, _ in livermore)
        control_n = sum(len(development) for development, _ in control)
        bins, control_bins = [], []
        for j, ((development, holdout), (free_dev, free_holdout)) in enumerate(zip(livermore, control, strict=True)):
            def residual(samples):
                return [energy-free_outgoing(incident, cos, mass) for _, cos, energy, _ in samples]

            atoms = [residual_atom(energy, free_outgoing(incident, cos, mass), incident) for _, cos, energy, _ in development]
            bins.append(dict(bin_index=j, development_sample_indices=[r[0] for r in development], development_residual_atoms=atoms,
                             development_residual=describe(residual(development)), heldout_residual=describe(residual(holdout)),
                             development_angular_mass=len(development)/livermore_n if livermore_n else None,
                             development_free_inadmissible_count=sum(r[3] for r in development)))
            control_bins.append(dict(bin_index=j, development_residual=describe(residual(free_dev)),
                                     development_angular_mass=len(free_dev)/control_n if control_n else None,
                                     heldout_residual=describe(residual(free_holdout)),
                                     free_inadmissible_count=sum(r[3] for r in (*free_dev, *free_holdout))))
        group = dict(incident_keV=incident, livermore_bins=bins, free_klein_nishina_control_bins=control_bins)
        result['incident_groups'].append(group)
        all_checks = []
        for entry, (_, holdout) in zip(bins, livermore, strict=True):
            checks = heldout_predictions(result, incident, holdout)
            entry['heldout_prediction'] = heldout_scores(checks, len(holdout))
            all_checks.extend(checks)
        group['heldout_prediction'] = heldout_scores(all_checks, sum(len(holdout) for _, holdout in livermore))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sampler-archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cosine-bins', type=int, default=16)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output path')
    result = build(args.sampler_archive, args.cosine_bins)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, allow_nan=False, separators=(',', ':'), sort_keys=True)
        stream.write('\n')
    print(json.dumps(dict(sha256=digest(args.output), exact_incident_energies_keV=result['incident_energies_keV'],
                          holdout=[r['heldout_prediction'] for r in result['incident_groups']])))


if __name__ == '__main__':
    main()
