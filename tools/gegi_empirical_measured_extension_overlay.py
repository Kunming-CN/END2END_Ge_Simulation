"""Verify or repair empirical-grid escape extensions, then seal blind scores."""

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_batched_escape_quadrature as positive
import gegi_empirical_measured_extensions as ext
import gegi_empirical_measured_grid as measured
import scenario_workflow as W


KIND = 'gegi_measured_empirical_escape_extension_overlay_v1'


def verified_against_positive(row, at, target):
    independent = row['comparison']['held_out']
    chosen = [independent[i] for i in sorted({0, len(independent)//2, len(independent)-1})]
    checks = []
    for point in chosen:
        control = at(point['intermediate_keV'], 256)
        if control['log_quadrature_difference'] > target:
            control = at(point['intermediate_keV'], 512)
        checks.append(dict(control, original_log_density=point['log_escape_density'],
                           absolute_difference=abs(control['log_escape_density']-point['log_escape_density'])))
    return checks, all(max(r['absolute_difference'], r['log_quadrature_difference']) <= target for r in checks)


def recipe(data, base, domains):
    return dict(kind=KIND, basis=ext.make_recipe(data, domains), prior_bank_sha256=W.sha(base),
                source_sha256={Path(p).name:W.sha(p) for p in (__file__, positive.__file__)},
                positive_quadrature_orders=[256, 512])


def build(data, base, overlay):
    domains = ext.requested(data)
    old = measured.read_curves(base)
    manifest = recipe(data, base, domains)
    bank = measured.joint.response.bank
    with closing(sqlite3.connect(base.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        sealed, = db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()
    W.require(json.loads(sealed) == manifest['basis'] and old.keys() <= domains.keys(),
              'Preserve the original incomplete fast-quadrature evidence')
    rates, total = bank.trial.rate_functions(data.rates)
    target_error = manifest['basis']['heldout_log_error_target']
    completed = Counter()
    with closing(sqlite3.connect(overlay)) as db:
        bank.create_bank(db, manifest)
        for key, target in domains.items():
            prior = db.execute('SELECT summary FROM curves WHERE curve=?', (key,)).fetchone()
            if prior is not None:
                completed[json.loads(prior[0])['status']] += 1
                continue
            previous = old.get(key)
            model = target['model']
            at = positive.checked_evaluator(model, data.crystal, rates, total, manifest['basis']['azimuth_samples'])
            checks = []
            keep = False
            if previous and previous['status'] == measured.tails.VERIFIED:
                checks, keep = verified_against_positive(previous, at, target_error)
            if keep:
                result = previous | dict(method='independent_positive_checks_of_saved_gaussian_curve',
                                         positive_checks=checks)
            else:
                low, high = target['domain_keV']
                nodes = bank.curve.response_nodes(low, high, model['measured_second_site_keV'], model['sigma_second_keV'], 3)
                initial = dict(comparison=dict(nodes=[dict(intermediate_keV=float(e)) for e in nodes]))
                boundary = target['boundary']
                try:
                    result = ext.repair.repair_curve(db, key, initial, target | dict(energies=np.asarray([low, high])),
                        {boundary['intermediate_keV']:boundary}, at, 256, 512, target_error)
                except W.ControlError as error:
                    if str(error) != 'No independent within-interval energy remains at floating-point precision':
                        raise
                    result = dict(status='heldout_interval_roundoff_unresolved', domain_keV=[low, high], model=model,
                                  reason=str(error))
                result |= dict(method='batched_positive_energy_rule', positive_checks=checks,
                               original_status=previous['status'] if previous else 'not_completed_in_prior_attempt')
            with db:
                db.execute('INSERT OR REPLACE INTO curves VALUES (?,?)', (key, W.encoded(result)))
            completed[result['status']] += 1
            print(dict(key=key, status=result['status'], method=result['method'],
                       fresh_direct_points=result.get('computed_direct_points')), flush=True)
    return read_overlay(data, base, overlay)


def read_overlay(data, base, overlay):
    domains = ext.requested(data)
    with closing(sqlite3.connect(overlay.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        saved, = db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()
        rows = {k:json.loads(v) for k,v in db.execute('SELECT curve,summary FROM curves')}
    W.require(json.loads(saved) == recipe(data, base, domains) and rows.keys() == domains.keys(),
              'Use the complete set of required verified or explicitly unresolved extensions')
    return rows


def score(data, base, overlay, output):
    arrays_path = output.with_suffix('.npz')
    W.require(not output.exists() and not arrays_path.exists(), 'Choose fresh blind JSON and array paths')
    started = time.perf_counter()
    rows = read_overlay(data, base, overlay)
    arrays = measured.evaluate(data, np.arange(len(data.points)), rows)
    reference = measured.compare_six(data, arrays, measured.six_point_indices(data))
    blind = measured.score(data, arrays)
    with arrays_path.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
    result = dict(kind='gegi_measured_empirical_grid_blind_v1', comparison=reference, input_sha256=data.inputs_sha256,
                  source_sha256={Path(p).name:W.sha(p) for p in (__file__, measured.__file__, measured.scorer.__file__)},
                  extensions_sha256=W.sha(overlay), prior_extensions_sha256=W.sha(base),
                  unsupported_incident_lines=data.normalization['recipe']['unsupported'], blind_sha256=W.digest(blind),
                  measured_analysis=blind, dataset=dict(name=arrays_path.name, sha256=W.sha(arrays_path)),
                  evaluation_seconds=time.perf_counter()-started,
                  extension_statuses=dict(Counter(row['status'] for row in rows.values())))
    measured.write(output, result)
    print(dict(comparison=reference, seconds=result['evaluation_seconds'], statuses=result['extension_statuses']), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for option in ('probe', 'base', 'overlay', 'output'):
        p.add_argument('--'+option, type=Path, required=True)
    a = p.parse_args()
    W.require(len({p.resolve() for p in (a.base, a.overlay, a.output, a.output.with_suffix('.npz'))}) == 4,
              'Preserve the frozen base and use distinct extension and output paths')
    W.require(not a.output.exists(), 'Choose a fresh blind output path')
    data = measured.context(a.probe)
    build(data, a.base, a.overlay)
    score(data, a.base, a.overlay, a.output)
