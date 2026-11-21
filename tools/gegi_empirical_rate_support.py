"""Reevaluate a saved empirical six-point comparison with extended Ge rates.

The supplied curve bank and quadrature overlay stay fixed. New coefficients
can support a larger energy domain for absorption. Escape still requires an
independently verified response curve at each shared outgoing-energy atom.
"""

import argparse
from collections import Counter
from pathlib import Path

import gegi_empirical_first_scatter_response as empirical
import scenario_workflow as W


def compare(old_rows, new_rows):
    """Retain changed rows and require exact previous escape contributions."""
    changed = []
    counts = {name: Counter() for name in empirical.BRANCHES}
    for old, new in zip(old_rows, new_rows, strict=True):
        W.require({k: v for k, v in old.items() if k != 'trial_results'} ==
                  {k: v for k, v in new.items() if k != 'trial_results'},
                  'Extended rates changed branch identities or measured inputs')
        for index, (a, b) in enumerate(zip(old['trial_results'], new['trial_results'], strict=True)):
            W.require(W.encoded({k: v for k, v in a.items() if k != 'branches'}) ==
                      W.encoded({k: v for k, v in b.items() if k != 'branches'}),
                      'Extended rates changed conditional kernels')
            for name in empirical.BRANCHES:
                before, after = a['branches'][name], b['branches'][name]
                if after['covered_mass'] is not None:
                    counts[name][before['coverage_status']+' -> '+after['coverage_status']] += 1
                if before == after:
                    continue
                if name == 'escape':
                    # Supplementing material coefficients does not extend an interpolant.
                    fields = ('coverage_status', 'covered_mass', 'uncovered_mass', 'covered_density_status',
                              'covered_factor_per_mm3_observed_keV2', 'log_covered_factor_per_mm3_observed_keV2')
                    W.require(all(before[key] == after[key] for key in fields),
                              'The coefficient-only extension changed a verified escape contribution')
                changed.append(dict(original_trigger_id=new['original_trigger_id'], pair_index=new['pair_index'],
                                    site_index_order=new['site_index_order'], incident_keV=new['incident_keV'],
                                    trial_index=index, branch=name, response=after))
    return changed, {name: dict(values) for name, values in counts.items()}


def run(args):
    W.require(not args.output.exists(), 'Select a fresh coefficient-support receipt')
    bank, grid, repair = empirical.bank, empirical.grid, empirical.repair
    reference_sha = W.sha(args.reference)
    reference = W.read(args.reference)
    request_path = args.coefficient_extension/'request.json'
    request = W.read(request_path)
    W.require(request['kind'] == 'gegi_empirical_first_scatter_rate_extension_request_v1' and
              request['overlay_acceptance_sha256'] == reference_sha and
              reference['source_sha256'][Path(empirical.__file__).name] == W.sha(empirical.__file__) and
              reference['kernel_sha256'] == W.sha(args.kernel),
              'Use the exact empirical kernel, producer and six-point receipt named by the coefficient request')
    measured, plan, basis, rates, crystal, points = bank.setup(args.measured_plan, args.plan, args.probe, args.new_rates)
    W.require(basis == reference['bank_basis'] == request['base_coefficients'] and
              measured['measured_triggers'] == reference['measured_triggers'] and
              plan['selected_trials'] == reference['selected_trials'],
              'The saved six-point plan or its original initialized coefficients changed')
    keys, original = bank.geometries(measured, plan, crystal, points, basis['coefficient_support_keV'])
    base_sha, overlay_sha = W.sha(args.bank), W.sha(args.quadrature_extension)
    W.require(base_sha == reference['base_bank_sha256'] == request['unchanged_curve_bank_sha256'] and
              overlay_sha == reference['quadrature_extension']['sha256'] == request['unchanged_quadrature_overlay_sha256'],
              'Use the original curve bank and quadrature overlay')
    manifest, rows = grid.read_bank(args.bank, basis, keys)
    W.require(rows.keys() == keys.keys(), 'Use the completed original escape bank')
    _, replacements = repair.read_extension(args.quadrature_extension, base_sha, manifest, rows)
    rows |= replacements
    new, binding = bank.trial.verified_extension(args.coefficient_extension, W.sha(request_path),
                                                 basis['original_rate_basis'], request['new_query_energies_keV'])
    W.require(new and max(new) < min(rates), 'The requested rate extension must add only new lower anchors')
    rates |= new
    support = [min(rates), max(rates)]
    branches = empirical.evaluate(plan, keys, rows, original, W.read(args.kernel), rates, support)
    changed, transitions = compare(reference['branches'], branches)
    W.require(W.sha(args.bank) == base_sha and W.sha(args.quadrature_extension) == overlay_sha,
              'An original escape bank changed during the comparison')
    result = dict(kind='gegi_empirical_first_scatter_rate_support_comparison_v1', reference_sha256=reference_sha,
                  source_sha256={Path(__file__).name: W.sha(__file__), Path(empirical.__file__).name: W.sha(empirical.__file__)},
                  request_sha256=W.sha(request_path), coefficient_binding=binding, new_coefficient_anchors=len(new),
                  extended_coefficient_support_keV=support, original_coefficient_support_keV=basis['coefficient_support_keV'],
                  unchanged_curve_bank_sha256=base_sha, unchanged_quadrature_overlay_sha256=overlay_sha,
                  kernel_sha256=reference['kernel_sha256'],
                  first_scatter_angular_factor_status=reference['first_scatter_angular_factor_status'],
                  first_scatter_angular_density_per_sr=reference['first_scatter_angular_density_per_sr'],
                  conditional_factor_units=reference['conditional_factor_units'],
                  verified_totals=dict(original_branch_count=len(branches), trials_per_branch=len(plan['selected_trials'])),
                  coverage_transitions=transitions, changed_rows=changed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(W.encoded(result)+b'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('reference', 'kernel', 'measured-plan', 'plan', 'probe', 'new-rates', 'bank',
                   'quadrature-extension', 'coefficient-extension', 'output'):
        parser.add_argument('--'+option, type=Path, required=True)
    result = run(parser.parse_args())
    print(result['coverage_transitions'], 'changed rows:', len(result['changed_rows']))


if __name__ == '__main__':
    main()
