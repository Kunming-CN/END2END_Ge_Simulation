"""Empirical joint outgoing solid-angle and energy measure after first Compton.

For cosine c, each existing angular hat h_j is normalized by its cosine
integral A_j. Its mixture mass p_j comes from the same development bin.
Use uniform azimuth, so the angular density is sum_j(p_j h_j/A_j)/(2*pi).
Each term transports its original residual atoms to c with the unchanged
bounded empirical energy map. The conditional shares at c are proportional
to p_j h_j/A_j. No free Klein-Nishina angular factor is substituted.
"""

import argparse
from collections import Counter
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3

import numpy as np

import gegi_compton_energy_kernel as energy
import gegi_empirical_escape_tails as tails
import gegi_empirical_first_scatter_response as response
from gegi_photon_continuation import solid_angle_density_per_sr
import scenario_workflow as W


def angular_model(kernel, incident_keV, bin_field='livermore_bins'):
    """Piecewise-linear angular density with a unit integral over cosine."""
    incident = kernel['incident_energies_keV']
    if incident_keV not in incident:
        return None
    bins = kernel['incident_groups'][incident.index(incident_keV)][bin_field]
    centers = np.asarray(kernel['cosine_bin_centers'])
    masses = np.asarray([b['development_angular_mass'] for b in bins], dtype=float)
    if (masses.shape != centers.shape or np.any(masses < 0) or not np.isfinite(masses).all()
            or not math.isclose(math.fsum(masses), 1., rel_tol=0., abs_tol=1e-14)):
        raise ValueError('Require normalized development angular masses')
    x = np.r_[-1., centers, 1.]
    widths = np.diff(x)
    if not np.isfinite(widths).all() or (widths <= 0).any():
        raise ValueError('Use ordered cosine centers strictly between -1 and 1')
    areas = (widths[:-1]+widths[1:])/2
    areas[0] += widths[0]/2
    areas[-1] += widths[-1]/2
    peaks = masses/areas
    heights = np.r_[peaks[0], peaks, peaks[-1]]
    cumulative = np.r_[0., np.cumsum(widths*(heights[:-1]+heights[1:])/2)]
    return dict(x=x, heights=heights, cumulative=cumulative, masses=masses, hat_areas=areas, peaks=peaks)


def angular_cdf(model, cosine):
    x, y = model['x'], model['heights']
    index = np.clip(np.searchsorted(x, cosine, side='right')-1, 0, len(x)-2)
    return model['cumulative'][index]+(cosine-x[index])*(y[index]+np.interp(cosine, x, y))/2


def joint_nodes(kernel, incident_keV, cosine, model=None):
    """Return the parent atom support, normalized conditional weights and angular density per sr."""
    parent = energy.conditional_nodes(kernel, incident_keV, cosine)
    if parent['weights'] is None:
        return parent | dict(angular_density_per_sr=None)
    model = angular_model(kernel, incident_keV) if model is None else model
    hats = parent['angular_bin_weights']
    values = np.array([model['peaks'][j]*v for j, v in hats])
    density = math.fsum(values)
    if density == 0.:
        return parent | dict(status='zero_empirical_angular_density', angular_density_per_sr=0., weights=None)
    conditional = values/density
    incident = kernel['incident_energies_keV'].index(incident_keV)
    bins = kernel['incident_groups'][incident]['livermore_bins']
    counts = [len(bins[j]['development_residual_atoms']) for j, _ in hats]
    weights = np.repeat(conditional/np.asarray(counts), counts)
    return parent | dict(weights=weights, angular_density_per_sr=density/(2*math.pi),
                         baseline_angular_bin_weights=hats,
                         angular_bin_weights=[(j, float(v)) for (j, _), v in zip(hats, conditional, strict=True)])


def energy_holdout(kernel, incident, samples, model):
    checks = []
    mass = kernel['native_metadata']['native_electron_rest_keV']
    lower_free = energy.free_outgoing(incident, -1., mass)
    for _, cosine, actual, inadmissible in samples:
        prediction = joint_nodes(kernel, incident, cosine, model)
        if prediction['weights'] is None:
            continue
        outgoing, weights = prediction['outgoing_energies_keV'], prediction['weights']
        order = np.argsort(outgoing)
        outgoing, weights = outgoing[order], weights[order]
        cumulative = np.cumsum(weights)
        bounds = outgoing[np.searchsorted(cumulative, energy.QUANTILES)]
        residual = outgoing-actual
        crps = float(weights @ (abs(residual)-residual*(2*cumulative-weights-1)))
        pit = math.fsum(weights[outgoing < actual])+.5*math.fsum(weights[outgoing == actual])
        checks.append((crps, abs(prediction['free_outgoing_keV']-actual), pit, bounds[2] <= actual <= bounds[-3],
                       bounds[1] <= actual <= bounds[-2], bounds[0] <= actual <= bounds[-1],
                       math.fsum(weights[outgoing < lower_free]), inadmissible))
    return checks


def angular_holdout(samples, model, incident):
    cosine = np.array([r[1] for r in samples])
    predicted = np.interp(cosine, model['x'], model['heights'])/(2*math.pi)
    kn = [solid_angle_density_per_sr(incident, c) for c in cosine]
    return dict(heldout_count=len(samples), empirical_nll_per_sr=float(-np.log(predicted).mean()),
                analytic_kn_nll_per_sr=float(-np.log(kn).mean()),
                empirical_cdf_decile_counts=np.histogram(angular_cdf(model, cosine), bins=np.linspace(0., 1., 11))[0].tolist())


def controls(kernel, archive):
    _, _, _, samples, failures, missing, _ = energy.load_archive(archive)
    W.require(failures == kernel['invalid_source_rows'] and missing == kernel['missing_source_rows'],
              'Use the same validated source sample roster')
    rows = []
    for i, incident in enumerate(kernel['incident_energies_keV']):
        livermore, free = [energy.separated_samples(samples[j, i], kernel['cosine_bin_edges']) for j in (0, 1)]
        model = angular_model(kernel, incident)
        free_model = angular_model(kernel, incident, 'free_klein_nishina_control_bins')
        parent = kernel['incident_groups'][i]
        W.require(all([r[0] for r in dev] == b['development_sample_indices'] for (dev, _), b in
                      zip(livermore, parent['livermore_bins'], strict=True)), 'The heldout/development split changed')
        holdout = [r for _, test in livermore for r in test]
        free_holdout = [r for _, test in free for r in test]
        by_bin = [energy_holdout(kernel, incident, test, model) for _, test in livermore]
        all_checks = [row for group in by_bin for row in group]
        rows.append(dict(incident_keV=incident, hat_cosine_areas=model['hat_areas'].tolist(),
                         integrated_angular_energy_mass=float(model['cumulative'][-1]),
                         angular_bin_development_masses=model['masses'].tolist(),
                         angular=angular_holdout(holdout, model, incident),
                         free_control_angular=angular_holdout(free_holdout, free_model, incident),
                         free_control_max_energy_error_keV=max(abs(r[2]-energy.free_outgoing(
                             incident, r[1], kernel['native_metadata']['native_electron_rest_keV'])) for r in free_holdout),
                         baseline_conditional_holdout=parent['heldout_prediction'],
                         joint_conditional_holdout=energy.heldout_scores(all_checks, len(holdout)),
                         by_bin=[dict(bin_index=j, baseline=b['heldout_prediction'],
                                      joint=energy.heldout_scores(by_bin[j], len(test)))
                                 for j, (b, (_, test)) in enumerate(zip(parent['livermore_bins'], livermore, strict=True))]))
    return rows


def identity(row, trial_index):
    return row['original_trigger_id'], row['pair_index'], tuple(row['site_index_order']), row['incident_keV'], trial_index


def saved_joint(cases, parent_curves, tail_curves, rate_support, tail_control, kernel, rates, sigma_first):
    absorb = {identity(b, b['trial_index']): b['response'] for b in rate_support['changed_rows'] if b['branch'] == 'absorption'}
    escape = {identity(b, b['trial_index']): b['extended_log_covered_factor_per_mm3_observed_keV2']
              for b in tail_control['changed_states']}
    rates_at, _ = response.bank.trial.rate_functions(rates)
    bound = [min(rates), max(rates)]
    results = []
    log_field = 'log_covered_factor_per_mm3_observed_keV2'
    for branch, index, original, outgoing, original_weight, parts in cases:
        key = branch['curve_key']
        curve = parent_curves[key]
        model = curve['model']
        e0, length = branch['incident_keV'], original['separation_mm']
        obs = branch['measured_first_site_keV'], model['measured_second_site_keV']
        sigmas = sigma_first, model['sigma_second_keV']
        prediction = joint_nodes(kernel, e0, original['first_scatter_cosine'])
        W.require(np.array_equal(outgoing, prediction['outgoing_energies_keV']), 'The mixture changed an outgoing atom')
        weights = prediction['weights']
        branches = response.integrate_atoms(e0, length, obs, sigmas, outgoing, weights, rates_at, bound, curve)
        main = branches['escape']
        tail_logs, tail_masses = [], []
        for tail, _, mask in parts:
            second, _ = response.grid.escape_logs(tail_curves[tail], outgoing[mask], np.ones(mask.sum(), dtype=bool))
            W.require(np.isfinite(second).all(), 'A joint atom lies outside verified continuation')
            status = np.full(mask.sum(), response.COMPUTED)
            first = response.log_gaussian(obs[0], e0-outgoing[mask], sigma_first)
            term = response.summarize_branch(weights[mask], first, second, status, -2*math.log(length))
            tail_logs.append(term[log_field])
            tail_masses.append(term['covered_mass'])
        W.require(math.isclose(math.fsum([main['covered_mass'], *tail_masses]), 1., abs_tol=2e-15) and
                  branches['absorption']['coverage_status'] == 'full', 'The joint response needs full verified atom support')
        new_escape = float(np.logaddexp.reduce([main[log_field], *tail_logs]))
        ident = identity(branch, index)
        old_abs = absorb.get(ident, original['branches']['absorption'])[log_field]
        old_escape = escape.get(ident, original['branches']['escape'][log_field])
        log_angle = math.log(prediction['angular_density_per_sr'])
        updated = dict(absorption=branches['absorption'][log_field], escape=new_escape)
        results.append(dict(original_trigger_id=ident[0], pair_index=ident[1], site_index_order=ident[2],
                            incident_keV=e0, trial_index=index, first_scatter_cosine=original['first_scatter_cosine'],
                            atom_count=len(outgoing), conditional_mass=math.fsum(weights), uncovered_conditional_mass=0.,
                            angular_density_per_sr=prediction['angular_density_per_sr'],
                            baseline_angular_bin_weights=prediction['baseline_angular_bin_weights'],
                            joint_conditional_bin_weights=prediction['angular_bin_weights'],
                            baseline_conditional_log_factors=dict(absorption=old_abs, escape=old_escape),
                            joint_conditional_log_factors=updated,
                            joint_log_factors={name: v+log_angle for name, v in updated.items()}))
    return results


def run(args):
    W.require(not args.output.exists(), 'Use a fresh joint-response evidence path')
    cases, required, parents, recipe, _, rates, support = tails.setup(args)
    kernel = W.read(args.kernel)
    tail_receipt = W.read(args.tail_comparison)
    tail_sha = W.sha(args.tail_bank)
    W.require(tail_sha == tail_receipt['tail_bank_sha256'] and tail_receipt['recipe'] == recipe and
              tail_receipt['coverage_counts'] == {'full': len(cases)}, 'Use the completed verified empirical tail bank')
    with closing(sqlite3.connect(args.tail_bank.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        continuations = {k: json.loads(v) for k, v in db.execute('SELECT curve,summary FROM curves')}
    W.require(continuations.keys() == required.keys() and all(b['status'] == tails.VERIFIED for b in continuations.values()),
              'Missing independently verified escape continuations')
    reference = W.read(args.reference)
    rows = saved_joint(cases, parents, continuations, support, tail_receipt, kernel, rates,
                       reference['settings']['sigma_first_keV'])
    result = dict(kind='gegi_empirical_first_compton_joint_controls_v1', source_sha256=W.sha(__file__),
                  baseline_recipe=recipe, tail_comparison_sha256=W.sha(args.tail_comparison), tail_bank_sha256=tail_sha,
                  holdout=controls(kernel, args.sampler_archive), selected_trials=reference['selected_trials'],
                  original_trial_status_counts=reference['trial_status_counts'], states=rows,
                  conditional_log_units='ln numerical factor in mm^-3 keV^-2 before solid angle density',
                  joint_log_units='ln numerical factor in mm^-3 keV^-2 with angular density per sr incorporated via dV2=L12²dL dOmega',
                  scope='Conditional on first Compton at the first vertex. Linear cosine hats smooth development bin masses. '
                        'Uniform azimuth is assumed. No source position fit, arrival rate, ADC selection or production model weights.')
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('reference', 'kernel', 'measured-plan', 'plan', 'probe', 'new-rates', 'bank',
                   'quadrature-extension', 'coefficient-extension', 'rate-support', 'tail-bank',
                   'tail-comparison', 'sampler-archive', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    result = run(parser.parse_args())
    print(dict(scored=len(result['states']), original_statuses=result['original_trial_status_counts']))


if __name__ == '__main__':
    main()
