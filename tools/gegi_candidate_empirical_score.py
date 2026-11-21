"""Opt in to scoring saved candidates with a prepared empirical grid and normalizer."""

import argparse
from contextlib import closing
import gzip
import json
from pathlib import Path
import zlib

import numpy as np

import gegi_candidate_storage as storage
import gegi_continuous_plane as plane
import gegi_normalized_source_diagnostic as score
import scenario_workflow as W


FIELDS = [f'log_{name}_per_emitted_photon_mm6_keV2' for name in ('absorption', 'escape')]


def validate_candidates(imaging, archive, triggers):
    raw = imaging.read_bytes()
    saved = json.loads(gzip.decompress(raw) if imaging.suffix == '.gz' else raw)
    archive_sha = W.sha(archive)
    W.require(saved['input_sha256']['candidate_store'] == archive_sha, 'The imaging receipt names a different candidate archive')
    lookup = {r['original_trigger_id']:r for r in saved['triggers']}
    fit = saved['fit_receipt']
    position_model = fit.get('position_model', 'center')
    W.require(len(lookup) == len(saved['triggers']) and len({r['original_trigger_id'] for r in triggers}) == len(triggers),
              'Original candidate identities must be distinct')
    with closing(storage._open_readonly(archive)) as db:
        for prepared in triggers:
            tid = prepared['original_trigger_id']
            previous = lookup.get(tid)
            stored = db.execute('SELECT record,adc_sha256,record_sha256 FROM triggers WHERE trigger_id=?', (tid,)).fetchone()
            W.require(previous is not None and stored is not None,
                      f'Prepared trigger {tid} is absent from the saved measured fit scope')
            body, adc_sha, record_sha = stored
            record = json.loads(zlib.decompress(body))
            W.require(storage._record_digest(record, adc_sha) == record_sha == prepared['archive_record_sha256'] and
                      adc_sha == prepared['archive_adc_sha256'] and record['trigger_id'] == tid and
                      record['decision'] == 'candidate' and
                      record['trigger_time_ns'] == previous['trigger_time_ns'] == prepared['trigger_time_ns'] and
                      record['card']['energy_keV'] == previous['energy_keV'] == prepared['original_measured_trigger_energy_keV'] and
                      previous['projected_mass'] == prepared['original_projected_mass'] and
                      previous['unresolved_mass'] == prepared['original_unresolved_mass'],
                      f'Prepared trigger {tid} differs from the archived measured record')
            old = {p['index']:p for p in previous['pairings']}
            fitted = fit['candidates'][previous['two_strip_ordinal']-1]
            available = {p['index']:p for p in fitted['pairings']}
            W.require(fitted['ordinal'] == previous['two_strip_ordinal'] and fitted['time_ns'] == previous['trigger_time_ns']
                      and sorted(available) == sorted(p['pair_index'] for p in prepared['pairs']),
                      f'Prepared trigger {tid} differs from its saved fit pairing scope')
            for pair in prepared['pairs']:
                i = pair['pair_index']
                fitted_pair = available[i]
                original = old.get(i)
                waveform, model, _ = plane.waveform_position_fit(fitted_pair, position_model)
                valid = waveform is not None and waveform['optimizer_success']
                expected = (fitted_pair['cells'], original['site_energies_keV'] if original else None,
                            original['nominal_mass'] if original else None,
                            waveform['positions_mm'] if valid else None, model if valid else None)
                actual = tuple(pair[k] for k in ('cells','measured_site_energies_keV','original_pair_mass',
                                                 'fitted_vertices_mm','waveform_model'))
                W.require(expected == actual, f'Prepared trigger {tid}, pair {i} changed fitted geometry, energy or weight')
    return archive_sha


def normalization_grid(normal, index):
    cases = normal['normalization_cases']
    grid = index['trial_grid']
    radii, directions = np.asarray(grid['radii_mm']), np.asarray(grid['unit_vectors'])
    positions = ((radii[:,None,None]*directions)+grid['origin_mm']).reshape(-1,3)
    W.require(np.array_equal(positions, np.asarray([p['source_mm'] for p in cases])) and
              [p['grid_index'] for p in cases] == list(range(len(positions))),
              'The numerator and matching normalizer use different source grids')
    region = np.asarray([index['source_region_codes'].index(p['source_region']) for p in cases])
    normal_cases = []
    for p in cases:
        lines = [dict(line, uninitialized_exit_mass_analytic_upper_bound=max(
            item['uninitialized_exit_mass_analytic_upper_bound'] for s in line['seed_results'] for item in s['estimates']))
            for line in p['lines']]
        normal_cases.append(dict(p, role='full_grid', lines=lines))
    return positions, region, dict(normalization_cases=normal_cases, trial_scope='full_declared_grid')


def run(args):
    W.require(not args.output.exists(), 'Choose a fresh empirical source-score output path')
    prepared, index, normal = (W.read(p) for p in (args.numerator, args.index, args.normalization))
    W.require(prepared['kind']=='gegi_measured_empirical_grid_blind_v1' and
              prepared['input_sha256'].get(args.index.name)==W.sha(args.index) and
              prepared['input_sha256'].get(args.normalization.name)==W.sha(args.normalization) and
              normal['recipe']['inputs_sha256']['kernel']==prepared['input_sha256'].get('first-scatter-energy-kernel.json') and
              normal['recipe']['base_rate_basis']==index['basis'],
              'Use a prepared empirical numerator with its exact branch index and matching empirical normalizer')
    filename = prepared['dataset']['name']
    W.require(Path(filename).name == filename, 'The prepared array must be a sibling of its receipt')
    dataset = args.numerator.parent/filename
    W.require(W.sha(dataset) == prepared['dataset']['sha256'], 'Prepared numerator array hash differs')
    positions, region, norm = normalization_grid(normal,index)
    archive_sha = validate_candidates(args.imaging, args.archive, index['measured_triggers'])
    with np.load(dataset, allow_pickle=False) as arrays:
        full = {key:arrays[key] for key in FIELDS}
        expected = len(index['branch_rows']), len(positions)
        identities = [(r['original_trigger_id'], r['pair_index'], tuple(r['site_index_order']), r['incident_keV'])
                      for r in index['branch_rows']]
        W.require(len(set(identities)) == len(identities) and all(a.shape == expected and not np.isposinf(a).any() for a in full.values()),
                  'Prepared measured branches must retain distinct identities and the complete declared grid')
        blind = score.fit_blind(index, norm, full | dict(trial_positions_mm=positions, trial_source_region=region))
    result = dict(kind='gegi_candidate_empirical_source_score_v1', measured_analysis=blind, blind_sha256=W.digest(blind),
                  input_sha256={k:W.sha(v) for k,v in [('imaging',args.imaging), ('numerator',args.numerator),
                    ('index',args.index), ('normalization',args.normalization)]} | dict(archive=archive_sha, arrays=W.sha(dataset)),
                  calibration_measure=normal['recipe']['measure'], unsupported_incident_lines=normal['recipe']['unsupported'],
                  limitations='Prepared empirical ideal topology response on the declared source grid. Original measured pairing '
                              'weights and unresolved geometry are retained. No ADC selection calibration or confidence intervals.')
    with args.output.open('xb') as out:
        out.write(W.encoded(result)+b'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('imaging', 'archive', 'numerator', 'index', 'normalization', 'output'):
        p.add_argument('--'+option, type=Path, required=True)
    result = run(p.parse_args())
    print(dict(blind_sha256=result['blind_sha256'], triggers=len(result['measured_analysis']['measured_triggers'])))
