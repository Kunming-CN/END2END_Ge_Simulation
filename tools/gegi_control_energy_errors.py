"""Extract per-site energy errors from sealed independent GeGI ADC controls."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import stdev


HASHES = {
    'uncertainty': '6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24',
    'general_adc': '308a0f5ec78757cc929d26b2d3280d78c685b91b38ee88837b157178cb85e2d7',
    'targeted_adc': '939d7a78fc5f83586e6a4c464e18f0215808721f4ede3a7a1c91be843ee5da44',
    'negative_orders': '57618e7916b58a4c826a9a5c2f603d55257e2a2d57808e3d29f73110fdc44d14',
    'overlap': 'c3567a4cc684053df73f16b2e79f11fe555f34482d9fa408f7ecda77e649d740',
}


def read(path, digest):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Changed saved control receipt: {path.name}')
    return json.loads(data)


def exact_cell_errors(cells, energies, reference):
    """Use a bijection of measured to independently verified terminal cells."""
    target = [s['cell'] for s in reference]
    if (len(cells) != len(target) or len({tuple(c) for c in target}) != len(target)
            or sorted(cells) != sorted(target) or any(e is None for e in energies)):
        return None
    return [dict(reference_index=i, measured_site_index=cells.index(cell), terminal_cell=cell,
                 injected_energy_keV=reference[i]['energy_keV'], measured_energy_keV=energies[cells.index(cell)],
                 measured_minus_injected_keV=energies[cells.index(cell)]-reference[i]['energy_keV'])
            for i, cell in enumerate(target)]


def measured_pair(record, cohort):
    if cohort == 'general':
        index, cells, energies, orders = (record['index'], [s['contact_ids'] for s in record['sites']],
            [s['energy_keV'] for s in record['sites']], record['orders'])
    elif cohort == 'targeted_cs':
        index, cells, energies, orders = (record['pairing_index'], record['contact_ids'],
                                          record['measured_site_energies_keV'], record['order_hypotheses'])
    else:
        index, cells, energies, orders = (record['pairing_index'], record['cells'],
                                          record['measured_site_energies_keV'], record['orders'])
    return index, cells, energies, [{k: o[k] for k in ('site_index_order', 'kinematically_allowed')} for o in orders]


def two_site(trial, archived, phase, noise, neighborhood, pair_inputs):
    cohort = trial['cohort']
    if trial['adc_sha256'] != archived['adc_sha256']:
        raise ValueError('The measured energies refer to different saved ADC samples')
    reference = [dict(cell=r['contact_ids'], energy_keV=r['energy_keV'], position_mm=r['xyz_mm'],
                      response_sha256=r.get('record_sha256', r.get('native_record_sha256')))
                 for r in trial['reference_sites']]
    pairings = []
    for fit, measured in zip(trial['pairings'], pair_inputs, strict=True):
        index, cells, energies, orders = measured_pair(measured, cohort)
        if (index, cells) != (fit['pairing_index'], fit['cells']):
            raise ValueError('The original measured pairing changed')
        mapped = exact_cell_errors(cells, energies, reference) if fit['match_label'] == 'true_two_site_assignment' else None
        if fit['match_label'] == 'true_two_site_assignment' and mapped is None:
            raise ValueError('An archived exact pairing lost its cell correspondence')
        for model in fit['hypotheses'].values():
            if model['measured_site_energies_keV'] != energies or (mapped is not None and
                    [v[-1] for v in model['site_errors_in_input_order']] != [r['measured_minus_injected_keV'] for r in mapped]):
                raise ValueError('Energy or signed error differs from the archived position control')
        pairings.append(dict(pairing_index=index, measured_cells=cells, measured_energies_keV=energies, original_orders=orders,
                             fit_status=fit['status'], mapping_status=fit['match_label'], site_residuals=mapped))
    return dict(cohort=cohort, trial_id=trial['trial'], adc_sha256=trial['adc_sha256'], noise=noise, adc_phase_ns=phase,
                noise_seed=archived['noise_seed'], layout=trial['geometry'], neighborhood=neighborhood,
                trigger_status=trial['trigger_status'], reference=reference, pairings=pairings,
                heldout_site_pair_distances_mm=[math.dist(a['position_mm'], b['position_mm'])
                                               for i, a in enumerate(reference) for b in reference[i+1:]])


def overlap_condition(row, design):
    layout = design['physical_layouts'][row['layout_index']]
    if [p['injection_id'] for p in layout] != row['holdout_injection_ids']:
        raise ValueError('The overlap input geometry changed')
    reference = [dict(cell=p['cell'], energy_keV=e, position_mm=p['position_mm'],
                      injection_id=p['injection_id'], response_sha256=p['sha256'])
                 for p, e in zip(layout, row['input_energies_keV'], strict=True)]
    cells, energies = row.get('measured_cells', []), row.get('measured_energies_keV', [])
    mapped = exact_cell_errors(cells, energies, reference) if row['readout_status'] == 'evaluated' else None
    return dict(cohort='three_cell_overlap', trial_id=row['condition_index'], adc_sha256=row['adc_sha256'],
                adc_phase_ns=row['phase_ns'], noise='nominal', noise_seed=row['noise_seed'], layout=row['layout_index'],
                allocation_index=row['allocation_index'], noise_replicate=row['noise_replicate'],
                trigger_status=row['readout_status'], reference=reference,
                heldout_site_pair_distances_mm=[math.dist(a['position_mm'], b['position_mm'])
                                               for i, a in enumerate(reference) for b in reference[i+1:]],
                pairings=[dict(pairing_index=None, original_orders=[], measured_cells=cells, measured_energies_keV=energies,
                               mapping_status='unique_three_cell_component_allocation' if mapped is not None else 'unknown',
                               site_residuals=mapped)])


def stats(values):
    n = len(values)
    return dict(n=n, mean_keV=math.fsum(values)/n, rms_keV=math.sqrt(math.fsum(v*v for v in values)/n),
                sample_sd_keV=stdev(values) if n > 1 else None, residual_range_keV=[min(values), max(values)])


def grouped_errors(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        for pair in row['pairings']:
            for residual in pair['site_residuals'] or []:
                combined = row | residual
                groups[tuple(combined[k] for k in keys)].append(residual['measured_minus_injected_keV'])
    return [dict(zip(keys, group, strict=True)) | stats(values) for group, values in groups.items()]


def fixed_condition_seed_differences(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['layout'], row['allocation_index'], row['adc_phase_ns'])].append(row)
    result = []
    for (layout, allocation, phase), trials in groups.items():
        a, b = sorted(trials, key=lambda t: t['noise_replicate'])
        if a['reference'] != b['reference'] or a['noise_seed'] == b['noise_seed'] or a['adc_sha256'] == b['adc_sha256']:
            raise ValueError('Overlap seed pair is not the original held-fixed condition')
        first, second = (t['pairings'][0]['site_residuals'] for t in (a, b))
        difference = ([q['measured_energy_keV']-p['measured_energy_keV'] for p, q in zip(first, second, strict=True)]
                      if first is not None and second is not None else None)
        result.append(dict(layout=layout, allocation_index=allocation, adc_phase_ns=phase, trial_ids=[a['trial_id'], b['trial_id']],
                           seeds=[a['noise_seed'], b['noise_seed']], seed_1_minus_seed_0_keV=difference))
    return result


def summarize(rows, contrasts):
    cohort_counts = {}
    for cohort in sorted({r['cohort'] for r in rows}):
        trials = [r for r in rows if r['cohort'] == cohort]
        exact = [p for r in trials for p in r['pairings'] if p['site_residuals'] is not None]
        cohort_counts[cohort] = dict(readout_conditions=len(trials), physical_layouts=len({r['layout'] for r in trials}),
                                     matched_hypotheses=len(exact), scored_sites=sum(len(p['site_residuals']) for p in exact),
                                     mapping_counts=dict(Counter(p['mapping_status'] for r in trials for p in r['pairings'])))
    widths = {}
    for allocation in sorted({r['allocation_index'] for r in contrasts}):
        selected = [r['seed_1_minus_seed_0_keV'] for r in contrasts if r['allocation_index'] == allocation
                    and r['seed_1_minus_seed_0_keV'] is not None]
        widths[str(allocation)] = {'matched_fixed_conditions': len(selected), 'repeatability_scale_keV_by_cell':
            [math.sqrt(math.fsum(v*v for v in column)/(2*len(column))) for column in zip(*selected, strict=True)]}
    return dict(cohorts=cohort_counts,
                by_cohort_energy_noise=grouped_errors(rows, ('cohort', 'injected_energy_keV', 'noise')),
                by_layout_energy_noise=grouped_errors(rows, ('cohort', 'layout', 'injected_energy_keV', 'noise')),
                by_neighborhood_energy_noise=grouped_errors([r for r in rows if 'neighborhood' in r],
                                                            ('cohort', 'neighborhood', 'injected_energy_keV', 'noise')),
                overlap_same_condition_repeatability=widths)


def run(inputs):
    archived = {k: read(inputs[k], digest) for k, digest in HASHES.items()}
    rows = []
    for trial in archived['uncertainty']['trials']:
        cohort, index = trial['cohort'], trial['trial']
        if cohort == 'general':
            r = archived['general_adc']['trials'][index]
            rows.append(two_site(trial, r, r['adc_phase_ns'], r['noise'], r['neighborhood'], r['measured_pairings']))
        elif cohort == 'targeted_cs':
            h = archived['targeted_adc']
            r = h['trials'][index]
            rows.append(two_site(trial, r, h['design']['adc_phase_ns'], 'nominal', r['neighborhood'], r['fits']))
        elif cohort == 'negative_mixture':
            r = archived['negative_orders']['negative_controls'][index]
            rows.append(two_site(trial, r, r['adc_phase_ns'], 'nominal', 'known_multipoint', r['pairings']))
        else:
            raise ValueError(f'Unknown control cohort {cohort}')
    overlap = archived['overlap']
    overlap_rows = [overlap_condition(r, overlap['design']) for r in overlap['conditions']]
    contrasts = fixed_condition_seed_differences(overlap_rows)
    rows += overlap_rows
    return dict(kind='gegi_independent_adc_component_energy_errors_v1', input_sha256=HASHES,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), rows=rows,
                overlap_seed_differences=contrasts, summary=summarize(rows, contrasts),
                definition='Measured ADC site energy minus injected energy, matched only by an exact terminal-cell bijection. '
                           'The order ledger is conditional and simultaneous injections have no photon sequence. Multi-point '
                           'and wrong pairings retain measured energies without per-site truth matching. The overlap allocation '
                           'is a controlled three-component charge comparison, with no photon order. Samples repeat physical layouts.',
                uncertainty='For each held-fixed overlap condition, subtract the two fresh noise-seed measurements. The descriptive '
                            'repeatability scale is the RMS seed difference divided by sqrt(2), by allocation and cell. It assumes '
                            'independent seeded noise readings under that setup and does not measure geometry bias, physical '
                            'energy resolution, or a transferable Gaussian width. No measured detector calibration is present.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (*HASHES, 'output'):
        parser.add_argument('--'+name.replace('_', '-'), required=True, type=Path)
    paths = vars(parser.parse_args())
    output = paths.pop('output')
    if output.exists():
        parser.error('Choose a new output path')
    result = run(paths)
    data = (json.dumps(result, allow_nan=False, sort_keys=True, separators=(',', ':'))+'\n').encode()
    with output.open('xb') as stream:
        stream.write(data)
    print(json.dumps(dict(sha256=hashlib.sha256(data).hexdigest(), cohorts=result['summary']['cohorts'])))


if __name__ == '__main__':
    main()
