"""Bind held-out GeGI trigger cells to raw photon vertices and cell centroids."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import gzip
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
import sqlite3
from tempfile import TemporaryFile
from time import perf_counter

import h5py
import numpy as np

import gegi_continuous_pairing_study as pairing
import gegi_pixel_cfd_depth_study as depth_study
from gegi_joint_two_site import DEPTH_MM, LATERAL_DEPTH_MM, LATERAL_FRACTION


ROOT = pairing.ROOT
LOCAL = pairing.LOCAL
PAIRS = LOCAL / 'study.json'
PAIRS_SHA = '62c56967d2ea05984d0f94dff818acd0fd71361aa950086eea748167e0352735'
MATCH_TOL_MM = 1e-6
ENERGY_TOL_KEV = 1e-7
AXES = ('xloc', 'yloc', 'zloc')


def identity(group):
    return group['source'], group['raw_event_id'], group['group_id']


def weighted_centroid(rows):
    energy = math.fsum(row['energy_keV'] for row in rows)
    center = ([math.fsum(row['position_mm'][a] * row['energy_keV'] for row in rows) / energy
               for a in range(3)] if energy > 0 else None)
    return energy, center


def photon_steps(folder, done, events, hashes):
    """Read only the Ge photon STEP records needed from the original LH5."""
    archive = done['archives']['transport/truth.lh5']
    path = folder / 'transport/truth.lh5.gz'
    digest = pairing._hash(path)
    pairing.require(digest == archive['sha256'] == done['artifacts']['transport/truth.lh5.gz']['sha256'],
                    'Original LH5 archive differs from its sealed source')
    hashes[path.relative_to(ROOT).as_posix()] = digest
    original = sha256()
    with TemporaryFile(dir=LOCAL) as stream, gzip.open(path, 'rb') as src:
        while block := src.read(1024 * 1024):
            original.update(block)
            stream.write(block)
        pairing.require(stream.tell() == archive['original_bytes']
                        and original.hexdigest() == archive['original_sha256'], 'Original LH5 bytes changed')
        stream.seek(0)
        with h5py.File(stream, 'r') as data:
            ge = data['stp/germanium']
            columns = tuple(f'{axis}_{end}' for end in ('pre', 'post') for axis in AXES)
            def unit(key):
                value = ge[key].attrs['units']
                return value.decode() if isinstance(value, bytes) else value
            pairing.require(all(unit(key) == 'm' for key in columns)
                            and unit('time') == 'ns' and unit('edep') == 'keV', 'Unexpected raw Ge STEP units')
            ids = ge['evtid'][:]
            rows = np.flatnonzero(np.isin(ids, list(events)) & (ge['particle'][:] == 22))
            values = {key: ge[key][rows].tolist() for key in (*columns, 'time', 'edep', 'trackid')}
    output = defaultdict(list)
    for i, row in enumerate(rows):
        output[int(ids[row])].append(dict(
            raw_row_index=int(row), photon_trackid=values['trackid'][i], pre_time_ns=values['time'][i],
            deposited_energy_keV=values['edep'][i],
            pre_position_mm=[1000 * values[axis+'_pre'][i] for axis in AXES],
            post_position_mm=[1000 * values[axis+'_post'][i] for axis in AXES],
        ))
    return output


def lateral_inventory(cells, field, inputs):
    study, scan = depth_study, depth_study.scan
    bank = study.FULL
    complete = inputs.read(bank/'COMPLETE.json', scan.FULL_COMPLETE_SHA)
    request = inputs.read(bank/'bound-request.json', complete['request_sha256'])
    _, folder, expected = study.CAPTURES[0]
    capture = inputs.read(folder/'COMPLETE.json', expected)
    capture_request = inputs.read(folder/'bound-request.json', capture['request_sha256'])
    for recipe in (request, capture_request):
        pairing.require((recipe['model_sha256'], recipe['field_cache']['sha256'], recipe['field_precision_bits']) == field
                        and recipe['channels'] == request['channels']
                        and recipe['injection_energy_keV'] == study.ENERGY_KEV,
                        'Joint lateral bank and acquisition use different calibration fields')
    points = {row['target_ref']: row for row in request['grid'] if row['target_ref'].startswith('injections/')
              and tuple(row['contact_ids']) in cells}
    manifest = study.bank_manifest(inputs, complete, set(points))
    center_z = defaultdict(set)
    for ref, point in points.items():
        if manifest[ref]['status'] == 'completed' and manifest[ref]['valid'] and (bank/'bank'/ref).is_file():
            center_z[tuple(point['contact_ids'])].add(point['position_mm'][2])
    expected_grid = {(x, y, z) for x, y, z in product(LATERAL_FRACTION, LATERAL_FRACTION, LATERAL_DEPTH_MM)
                     if (x, y) != (0, 0)}
    fit, holdouts = defaultdict(dict), Counter()
    for row in capture['records']:
        cell = tuple(row['contact_ids'])
        if cell not in cells or row['status'] != 'completed' or not row['valid']:
            continue
        if row['role'] == 'holdout':
            holdouts[cell] += 1
            continue
        ref = folder / row['record_ref']
        pairing.require(pairing._hash(ref) == row['record_sha256'], 'Archived lateral training record changed')
        inputs.hashes[ref.relative_to(ROOT).as_posix()] = row['record_sha256']
        coord = (*row['offsets_pitch_fraction'], row['position_mm'][2])
        pairing.require(coord not in fit[cell], 'Repeated archived lateral training coordinate')
        fit[cell][coord] = row['position_mm']
    channels = request['channels']
    pitch = channels[1]['strip_center_mm'] - channels[0]['strip_center_mm']
    available = {}
    for cell in cells:
        center = center_z[cell] == set(DEPTH_MM)
        available[cell] = dict(
            center=bool(center), lateral=bool(center and fit[cell].keys() == expected_grid),
            captured_lateral_templates=len(fit[cell]), independent_lateral_holdouts=holdouts[cell],
            fit_xyz=list(fit[cell].values()),
            strip_centers_mm=[channels[cid-1]['strip_center_mm'] for cid in cell], pitch_mm=pitch,
        )
    return available


def position_support(training, xyz):
    detail = {key: value for key, value in training.items() if key != 'fit_xyz'}
    if xyz is None or not training['lateral']:
        return dict(detail, centroid_in_lateral_domain=None, centroid_matches_fit_point=None)
    offsets = [(xyz[i] - x) / training['pitch_mm'] for i, x in enumerate(training['strip_centers_mm'])]
    inside = all(LATERAL_FRACTION[0] <= value <= LATERAL_FRACTION[-1] for value in offsets)
    inside = inside and LATERAL_DEPTH_MM[0] <= xyz[2] <= LATERAL_DEPTH_MM[-1]
    return dict(detail, centroid_xy_pitch_fractions=offsets, centroid_in_lateral_domain=inside,
                centroid_matches_fit_point=any(math.dist(xyz, point) <= MATCH_TOL_MM for point in training['fit_xyz']))


def angle_difference(vertices, centers):
    if any(point is None for point in (*vertices, *centers)):
        return None
    a, b = ([y-x for x, y in zip(*pair, strict=True)] for pair in (vertices, centers))
    denominator = math.hypot(*a) * math.hypot(*b)
    cosine = math.fsum(x*y for x, y in zip(a, b, strict=True)) / denominator if denominator else None
    return math.degrees(math.acos(min(1, max(-1, cosine)))) if cosine is not None else None


def geometry_reference(group, old, native, steps, processes, training):
    pairing.require(native['input_event_sha256'] == old['native_input_group_sha256']
                    and native['event_id'] == group['raw_event_id'] and native['source_group'] == group['source'],
                    'Original native group identity differs from the pairing receipt')
    resolved = pairing.parent.evaluate(native, processes, {'spatial_diagnostics': [], 'candidates': []})
    ancestry = resolved['references']['ge5keV']
    sites = old['sites_in_birth_order']
    pairing.require(ancestry['status'] == old['status']
                    and ancestry['reference_cells_in_birth_order'] == [site['cell'] for site in sites],
                    'Reused exact-cell reference differs from the original ancestry')
    root, = old['depositing_root_gammas']
    ledger = resolved['row_assignment_ledger']
    measured = []
    for site in sites:
        birth = site['birth_position_mm']
        cell = site['cell']
        cell_rows = [row for row in ledger if row['collector_pair'] == cell]
        cell_energy, centroid = weighted_centroid(cell_rows)
        related = set(site['raw_row_indices'])
        site_energy_in_cell = math.fsum(row['energy_keV'] for row in cell_rows if row['raw_row_index'] in related)
        matches = [step for step in steps if step['photon_trackid'] == root['trackid']
                   and math.dist(step['post_position_mm'], birth) <= MATCH_TOL_MM
                   and step['pre_time_ns'] <= site['birth_time_ns']]
        step = matches[0] if len(matches) == 1 else None
        measured.append(dict(
            cell=cell, child_creation_anchor=dict(position_mm=birth, process=site['birth_process'],
                                                  birth_time_ns=site['birth_time_ns']),
            interaction_deposit_centroid_mm=site['deposit_centroid_mm'],
            interaction_deposited_energy_keV=site['deposited_energy_keV'],
            interaction_raw_row_indices=site['raw_row_indices'],
            cell_deposit_centroid_mm=centroid, cell_deposited_energy_keV=cell_energy,
            cell_raw_row_indices=[row['raw_row_index'] for row in cell_rows],
            interaction_energy_in_cell_keV=site_energy_in_cell,
            photon_step_status=('unique_ge_photon_step_post_vertex' if step else
                                'ambiguous_ge_photon_step_post_vertex' if matches else
                                'no_matching_ge_photon_step_post_vertex'),
            photon_step=step, matched_photon_step_rows=[match['raw_row_index'] for match in matches],
            joint_training=position_support(training[tuple(cell)], centroid),
        ))
    first, second = measured
    vertices = [site['photon_step']['post_position_mm'] if site['photon_step'] else None for site in measured]
    centroids = [site['cell_deposit_centroid_mm'] for site in measured]
    separation = lambda xyz: math.dist(*xyz) if all(point is not None for point in xyz) else None
    centroid_spacing, vertex_spacing = separation(centroids), separation(vertices)
    ordered = (vertex_spacing is not None and vertex_spacing > MATCH_TOL_MM
               and first['photon_step']['raw_row_index'] < second['photon_step']['raw_row_index'])
    truth_cells = [site['cell'] for site in measured]
    outside = math.fsum(row['energy_keV'] for row in ledger if row['collector_pair'] not in truth_cells)
    pairing.require(math.isclose(outside + math.fsum(site['cell_deposited_energy_keV'] for site in measured),
                                resolved['input_deposited_energy_keV'], rel_tol=0, abs_tol=ENERGY_TOL_KEV),
                    'Exact cells and outside energy do not close with the original group')
    return dict(
        original_identity={key: group[key] for key in ('source', 'raw_event_id', 'group_id', 'campaign_initial_id')},
        native_metadata_sha256=old['native_metadata_sha256'], transport_event_sha256=old['transport_event_sha256'],
        root_gamma_trackid=root['trackid'], containment=old['containment'], ancestry_status=old['status'],
        unassigned_energy_keV=old['unassigned_energy_keV'], energy_outside_two_cells_keV=outside,
        sites_in_child_birth_order=measured, photon_vertex_order=[0, 1] if ordered else None,
        photon_order_status='ordered_direct_photon_ge_steps' if ordered else 'unidentifiable',
        centroid_geometry_status='distinct_exact_cell_centroids' if centroid_spacing and centroid_spacing > MATCH_TOL_MM
        else 'unidentifiable',
        centroid_separation_mm=centroid_spacing, photon_vertex_separation_mm=vertex_spacing,
        cell_centroid_vs_photon_vertex_axis_difference_deg=angle_difference(vertices, centroids) if ordered else None,
    )


def run():
    start = perf_counter()
    inputs = depth_study.scan.Inputs()
    saved = inputs.read(PAIRS, PAIRS_SHA)
    acquisition = inputs.read(pairing.ACQUISITION, pairing.ACQUISITION_SHA)
    exact = [row for row in saved['candidates'] if row['comparison'] is not None
             and row['comparison']['pair_outcome'] == 'truth_pair_energy_compatible']
    unique = {}
    for row in exact:
        group, = row['deposit_groups']
        key = identity(group)
        known = unique.setdefault(key, (group, row['reference']))
        pairing.require(known[1] == row['reference'], 'Repeated occurrence carries a different truth group')
    pairing.require(len(exact) == 41 and len(unique) == 27 and all(row['association'] == 'unique_matched' for row in exact),
                    'Expected the original 41 exact-pair occurrences and 27 original groups')
    fields = {(source['original']['model_sha256'], source['original']['field_cache_sha256'],
               source['original']['field_precision_bits']) for source in acquisition['sources']}
    field, = fields
    cells = {tuple(site['cell']) for _, row in unique.values() for site in row['sites_in_birth_order']}
    training = lateral_inventory(cells, field, inputs)
    sources = {f'tools/{name}': pairing._hash(ROOT/'tools'/name) for name in (
        Path(__file__).name, 'gegi_continuous_pairing_study.py', 'gegi_parent_gamma_reference.py',
        'gegi_joint_two_site.py', 'gegi_pixel_cfd_depth_study.py')}

    groups = {}
    for source in sorted({key[0] for key in unique}):
        selected = {key: row for key, row in unique.items() if key[0] == source}
        folder = pairing.CAMPAIGN / 'chunks' / source / 'b000000'
        def checked(relative):
            path = folder / relative
            return inputs.read(path, saved['input_sha256'][path.relative_to(ROOT).as_posix()])
        done = checked('DONE.json')
        manifest = checked('transport/stream/manifest.json')
        transform = manifest['coordinate_transform']
        pairing.require(transform['rotation_local_to_global'] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                        and transform['translation_global_mm'] == [0, 0, 0], 'Detector coordinate convention changed')
        processes = {row['procid']: row['name'] for row in manifest['processes']}
        steps = photon_steps(folder, done, {key[1] for key in selected}, inputs.hashes)
        database = folder / 'events.sqlite'
        ref = database.relative_to(ROOT).as_posix()
        db_hash = pairing._hash(database)
        pairing.require(db_hash == saved['input_sha256'][ref] == done['artifacts']['events.sqlite']['sha256'],
                        'Native database seal differs from the pairing reference')
        inputs.hashes[ref] = db_hash
        with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            for key, (group, old) in selected.items():
                native = pairing.native_metadata(db, dict(group, metadata_sha256=old['native_metadata_sha256']))
                groups[key] = geometry_reference(group, old, native, steps[key[1]], processes, training)

    rows = []
    for entry in exact:
        group, = entry['deposit_groups']
        flags = entry['two_strip_pairings']['flags']
        overlap = [axis for axis in 'xy' if f'overlapping_{axis}_neighborhoods' in flags]
        key = identity(group)
        geometry = groups[key]
        rows.append(dict(trigger_index=entry['trigger_index'], trigger_time_ns=entry['trigger_time_ns'],
                         original_group_key=key, occurrence_id=group['occurrence_id'], arrival_class=group['arrival_class'],
                         truth_pairing_index=entry['comparison']['truth_pairing_index'],
                         truth_site_index_order=entry['comparison']['truth_site_index_order'],
                         neighborhood='near' if overlap else 'disjoint', overlapping_faces=overlap,
                         exact_cell_geometry=geometry['centroid_geometry_status'],
                         exact_photon_geometry=geometry['photon_order_status'],
                         sites_with_joint_lateral_training=sum(site['joint_training']['lateral']
                             for site in geometry['sites_in_child_birth_order'])))
    pairing.require(all(pairing._hash(ROOT / path) == digest for path, digest in sources.items()),
                    'Geometry reader or joint training definitions changed during export')
    return dict(
        kind='gegi_held_back_two_site_geometry_reference_v1', status='completed',
        design=dict(
            selection='Exactly two significant parent interactions in distinct matched cells, using the sealed 5 keV criterion.',
            order='Child track creation chronology is retained. A direct photon geometry requires two distinct and uniquely '
                  'matched Ge photon STEP post vertices in increasing raw row order along the original photon.',
            positions='Detector coordinates in mm. Whole-cell centroids use deposited Ge energy and exact saved collecting '
                      'pair endpoints of the pulse group. Interaction centroids instead use the original ancestry assignment.',
            neighborhood='Near if the two measured ±1 strip neighborhoods overlap on either face; disjoint otherwise.',
            lateral='Same-field center templates at 11 depths and the joint model’s complete 3-layer archived lateral grid. '
                    'Original transport positions remain held out from the template fit.',
            match_tolerance_mm=MATCH_TOL_MM, transport_replayed=False, drift_replayed=False, adc_replayed=False),
        calibration_field=dict(model_sha256=field[0], field_cache_sha256=field[1], field_precision_bits=field[2]),
        input_sha256=inputs.hashes, source_sha256=sources,
        summary=dict(occurrences=len(rows), original_groups=len(groups), exact_cells=len(cells),
                     occurrence_neighborhoods=dict(Counter(row['neighborhood'] for row in rows)),
                     occurrence_centroid_geometry=dict(Counter(row['exact_cell_geometry'] for row in rows)),
                     occurrence_photon_geometry=dict(Counter(row['exact_photon_geometry'] for row in rows)),
                     occurrence_lateral_coverage=dict(Counter(row['sites_with_joint_lateral_training'] for row in rows)),
                     joint_lateral_cells=sorted(cell for cell, model in training.items() if model['lateral'])),
        geometry_references=[dict(groups[key], original_group_key=key) for key in sorted(groups)],
        occurrences=rows, elapsed_s=perf_counter()-start,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    pairing.require(output.is_relative_to(LOCAL) and not output.exists(), 'Select a new result path under .local/gegi-continuous-pairing')
    result = run()
    with output.open('xb') as dst:
        dst.write(pairing.encoded(result) + b'\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
