"""Fill only the missing mean escape-response domains needed on the cobalt grid."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

import gegi_empirical_measured_grid as measured
import gegi_ideal_forward_fast_bank as fast
import gegi_trial_curve_quadrature_repair as repair
import scenario_workflow as W


KIND = 'gegi_measured_empirical_escape_extensions_v1'


def requested(data):
    limits = {key: [] for key in data.closed}
    mass = data.kernel['native_metadata']['native_electron_rest_keV']
    cosines = {}
    for i, branch in enumerate(data.indexed['branch_rows']):
        if branch['incident_keV'] not in measured.COBALT or branch['geometry_status'] != 'available_geometry':
            continue
        key = branch['curve_key']
        valid = np.isfinite(data.first_log[i])
        model = data.closed[key][0]['model']
        if key not in cosines:
            cosines[key] = measured.cosine_at(model, data.points[valid])[0]
        cosine = cosines[key]
        e = branch['incident_keV']
        for active, _, atoms in measured.angular_hats(data.kernel, e, cosine):
            c0, c1 = float(cosine[active].min()), float(cosine[active].max())
            f0, f1 = (measured.support_math.kernel.free_outgoing(e, c, mass) for c in (c0, c1))
            mapped = [float(measured.support_math.transport(a, f, e))
                      for a, f in ((atoms.min(), f0), (atoms.max(), f1))]
            limits[key].append(mapped)
    segments = {}
    for key, needed in limits.items():
        rows = data.closed[key]
        low, high = min(r[0] for r in needed), max(r[1] for r in needed)
        first, last = min(rows, key=lambda r:r['domain_keV'][0]), max(rows, key=lambda r:r['domain_keV'][1])
        left, right = first['domain_keV'][0], last['domain_keV'][1]
        model = rows[0]['model']
        if low < left:
            segments[key+':lower'] = dict(domain_keV=[low,left], model=model,
                                         boundary=first['comparison']['nodes'][0])
        if high > right:
            segments[key+':upper'] = dict(domain_keV=[right,high], model=model,
                                         boundary=last['comparison']['nodes'][-1])
    return segments


def make_recipe(data, domains):
    return dict(kind=KIND, inputs_sha256=data.inputs_sha256, required_segments=domains, first_order=32,
                fallback_order=64, azimuth_samples=256, heldout_log_error_target=.01,
                source_sha256={Path(p).name:W.sha(p) for p in (__file__,measured.__file__,fast.__file__,
                    fast.gaussian.__file__,repair.__file__)},
                software=measured.joint.response.bank.software())


def read_extensions(data, path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        saved, = db.execute('SELECT recipe FROM manifest WHERE id=1').fetchone()
        rows = {k:json.loads(s) for k,s in db.execute('SELECT curve,summary FROM curves')}
    target = requested(data)
    W.require(json.loads(saved) == make_recipe(data, target) and rows.keys() == target.keys(),
              'Use all exact declared empirical grid extension intervals')
    for key, row in rows.items():
        W.require(row['model'] == target[key]['model'] and row['domain_keV'] == target[key]['domain_keV'],
                  'An escape extension has incorrect measured geometry or endpoint support')
    return rows


def build(data, path):
    domains = requested(data)
    recipe = make_recipe(data, domains)
    bank = measured.joint.response.bank
    rates, total = bank.trial.rate_functions(data.rates)
    order = sorted(domains, key=lambda k: domains[k]['domain_keV'][0]-domains[k]['domain_keV'][1])
    with closing(sqlite3.connect(path)) as db:
        bank.create_bank(db, recipe)
        for i,key in enumerate(order, 1):
            target = domains[key]
            low, high = target['domain_keV']
            model = target['model']
            boundary = target['boundary']
            nodes = bank.curve.response_nodes(low, high, model['measured_second_site_keV'],
                                               model['sigma_second_keV'], 3)
            initial = dict(comparison=dict(nodes=[dict(intermediate_keV=float(e)) for e in nodes]))
            at = fast.checked_evaluator(model, data.crystal, rates, total, recipe['azimuth_samples'])
            item = target | dict(energies=np.asarray([low,high]))
            result = repair.repair_curve(db, key, initial, item, {boundary['intermediate_keV']:boundary}, at,
                        recipe['first_order'], recipe['fallback_order'], recipe['heldout_log_error_target'])
            print(dict(segment=i,total=len(order),key=key,status=result['status'],
                       direct_points=result['computed_direct_points'], elapsed=result['direct_seconds'],
                       heldout_error=result['comparison']['max_absolute_log_error']), flush=True)
    return read_extensions(data, path)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    args = p.parse_args()
    start = time.perf_counter()
    build(measured.context(args.probe), args.checkpoint)
    print('Elapsed seconds', time.perf_counter()-start, flush=True)
