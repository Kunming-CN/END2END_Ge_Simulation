"""Join the four selected cobalt triggers to their saved readout and endpoint ledgers."""

import argparse
import gzip
import io
import json
from math import dist, fsum, isclose
from pathlib import Path

import numpy as np

import gegi_digital_readout as digital
from gegi_continuous_plane import GEOMETRY_KEYS
from gegi_digital_pairs import compton_orders, energy_pairings
from gegi_imaging import cone
from gegi_intersection_image_study import (ENDPOINTS, ENDPOINTS_SHA, LOCAL, PRIOR_STUDY,
                                           PRIOR_STUDY_SHA, is_subgroup, joined_row)
from gegi_plane_footprint_study import ACQUISITIONS, ROOT, V1_POOL, V1_POOL_SHA
from gegi_plane_prior_study import ACCOUNTING
from gegi_pool_measured_planes import digest, require
from gegi_trigger_windows import ARCHIVE_NAME, RELATIVE_NS
from gegi_two_site_cfd_study import angle_error, axis_between


INFLUENCE = LOCAL/'independent-1s-intersection-influence.json.gz'
INFLUENCE_SHA = '48e5f25bc9bfb50accb4ce67200b6017c28ae380b2b1e0dfd2605228b4dec43d'
MARGINALS = LOCAL/'independent-1s-weak-endpoint-pairing.json.gz'
MARGINALS_SHA = 'c271fec9aa7370c2a30e23b5ee3700cac0f08a9ca1b4d7561fa045aee5bbed5a'
OUTPUT = LOCAL/'cobalt-history-readout.json'
SELECTED = {'1173.23_keV': ('independent-b000003-250ms', (349, 414)),
            '1332.49_keV': ('independent-b000002-250ms', (6, 982))}
SOURCE = 'co60-right'
PAIR_KEYS = ('x_contact_id', 'y_contact_id', 'x_energy_keV', 'y_energy_keV', 'x_minus_y_energy_keV',
             'energy_tolerance_keV', 'energy_compatible', 'energy_keV')


def load_bound(path, expected, hashes):
    raw = path.read_bytes()
    require(digest(raw) == expected, f'Saved input changed: {path.name}')
    hashes[path.relative_to(ROOT).as_posix()] = expected
    if path.suffix == '.npz':
        return raw
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def read_block(item, hashes):
    folder = ACQUISITIONS/item['name']
    report = load_bound(folder/'report.json', item['report_sha256'], hashes)
    plane = load_bound(folder/'plane.json.gz', item['plane_sha256'], hashes)
    windows = load_bound(folder/ARCHIVE_NAME, item['adc_windows_sha256'], hashes)
    source, = [s for s in report['sources'] if s['key'] == SOURCE]
    programmed, = [s for s in item['sources'] if s['source_group'] == SOURCE]
    original = source['original']
    require(plane['input_sha256'] == item['plane_inputs'] and
            plane['input_sha256']['acquisition'] == item['report_sha256'] and
            plane['input_sha256']['adc_windows'] == item['adc_windows_sha256'] and
            plane['input_sha256']['calibration'] == plane['calibration_bundle']['archive_sha256'] and
            all(original[k] == programmed[k] for k in ('chunk_index', 'chunk_sha256', 'transport_sha256',
                                                       'radiation_seed', 'source_position_mm')) and
            source['scheduled_parent_seed'] == programmed['scheduled_parent_seed'] and
            all(report['design'][k] == item[k] for k in ('clock_seed', 'noise_seed')),
            'Saved acquisition, waveform fit or original source bindings differ')
    transform = original['coordinate_transform']
    require(np.array_equal(transform['rotation_local_to_global'], np.eye(3)) and
            transform['translation_global_mm'] == [0, 0, 0],
            'This study needs a common frame for programmed source and fitted detector positions')
    return report, plane, windows, programmed


def window_receipt(windows, item, row):
    ordinal = row['two_strip_ordinal']
    with np.load(io.BytesIO(windows), allow_pickle=False) as adc:
        status = str(adc['window_status'][ordinal-1])
        require(all(adc[key].item() == item[key] for key in ('report_sha256', 'known_component_adc_sha256',
                                                            'digital_profile_sha256', 'digital_timing_sha256')) and
                status == row['adc_window_status'] == 'captured' and
                adc['trigger_time_ns'][ordinal-1] == row['trigger_time_ns'] and
                np.array_equal(adc['relative_time_ns'], RELATIVE_NS) and
                np.array_equal(adc['contact_ids'], digital.CONTACT_IDS) and
                adc['volts_per_code'].item() == digital._LSB_V, 'Saved ADC window binding differs')
        index, = np.flatnonzero(adc['two_strip_ordinal'] == ordinal)
        codes = adc['adc_codes'][index]
        require(codes.shape == (len(digital.CONTACT_IDS), len(RELATIVE_NS)) and codes.dtype == np.dtype('int16'),
                'Unexpected saved ADC window sample format')
        return dict(status=status, relative_time_ns=RELATIVE_NS.tolist(), adc_codes_shape=list(codes.shape),
                    adc_codes_int16_le_sha256=digest(codes.astype('<i2', copy=False).tobytes()))


def cell_key(cell):
    return cell['x_contact_id'], cell['y_contact_id']


def strip_label(contact):
    return f'X{contact:02d}' if contact <= 16 else f'Y{contact-17:02d}'


def waveform_positions(orders):
    positions = [None, None]
    for order in orders:
        if 'axis' not in order:
            continue
        first, second = order['order']
        vertex = order['vertex_mm']
        other = [v-a*order['site_separation_mm'] for v, a in zip(vertex, order['axis'], strict=True)]
        for index, point in ((first, vertex), (second, other)):
            require(positions[index] is None or dist(positions[index], point) < 1e-10,
                    'Saved order geometries imply different waveform-fit positions')
            positions[index] = point
    return positions


def compare_pair(pair, saved, ideal, cells, source_mm):
    compatible = pair['energy_compatible']
    require(bool(saved) == compatible and ideal['energy_compatible'] == compatible,
            'The measured or endpoint-marginal pairing status differs')
    kept = {tuple(order['order']): order for order in saved['orders']} if compatible else {}
    positions = waveform_positions(kept.values())
    sites = []
    for measured, native, xyz in zip(pair['sites'], ideal['sites'], positions, strict=True):
        x, y = cell_key(measured)
        require((x, y) == cell_key(native), 'Measured and endpoint-marginal cells differ')
        cell = cells.get((x, y))
        sites.append({k: measured[k] for k in PAIR_KEYS} | dict(
            x_strip=strip_label(x), y_strip=strip_label(y), waveform_position_mm=xyz,
            endpoint_cell_deposit_keV=cell['deposit_keV'] if cell else 0.,
            endpoint_cell_centroid_local_mm=cell['deposit_centroid_local_mm'] if cell else None,
            waveform_to_endpoint_centroid_mm=dist(xyz, cell['deposit_centroid_local_mm']) if xyz and cell else None,
            endpoint_x_marginal_keV=native['x_energy_keV'], endpoint_y_marginal_keV=native['y_energy_keV'],
            endpoint_marginal_average_keV=native['energy_keV']))
    orders = []
    if compatible:
        calculated = compton_orders(sites)
        require(calculated == pair['compton_orders'] and
                set(kept) == {tuple(row['site_index_order']) for row in calculated if row['kinematically_allowed']},
                'Measured order ledger changed')
        for hypothesis in calculated:
            sequence = hypothesis['site_index_order']
            order = kept.get(tuple(sequence), dict(order=sequence, nominal_mass=0., status='excluded_compton_kinematics'))
            entry = hypothesis | order | dict(projected_mass=order['nominal_mass'] if order['status'] == 'projected' else 0.)
            if 'axis' in order:
                check = cone(*({'energy_keV': sites[i]['energy_keV'], 'position_mm': positions[i]} for i in sequence))
                require(check is not None and all(np.allclose(check[k], order[k], rtol=0., atol=1e-10)
                                                  for k in GEOMETRY_KEYS), 'Saved cone failed geometric parity')
                angle = angle_error(order['axis'], axis_between(source_mm, order['vertex_mm']))
                entry.update(geometric_source_angle_deg=angle, signed_source_residual_deg=angle-order['half_angle_deg'])
            orders.append(entry)
        require(saved['cells'] == [list(cell_key(site)) for site in sites] and
                saved['site_energies_keV'] == [site['energy_keV'] for site in sites], 'Saved waveform pairing differs')
    return dict(index=pair['index'], energy_compatible=compatible, sites=sites, orders=orders,
                status='energy_compatible' if compatible else 'excluded_strip_energy_mismatch',
                nominal_mass=saved['nominal_mass'] if compatible else 0.,
                waveform_fit_status=saved['waveform_fit_status'] if compatible else None)


def compare_occurrence(selected, center, report, measured, prior, endpoint, marginal, window, source):
    block, index = selected['block'], selected['trigger_index']
    card = report['two_strip_pairings']
    descriptor = joined_row(block, prior, measured, endpoint, f'{center:g}_keV')
    identity = ('trigger_index', 'two_strip_ordinal', 'trigger_time_ns', 'energy_keV')
    require(all(selected[k] == descriptor[k] for k in (*identity, 'native_group')) and
            descriptor['subgroup'] and is_subgroup(endpoint) and len(endpoint['endpoint_collections']) == 3 and
            report['energy_keV'] == report['additional_multi_strip_energy_keV'] == selected['energy_keV'] and
            report['trigger_time_ns'] == selected['trigger_time_ns'] and card == endpoint['measured_pairings'] and
            marginal['native_input_group_sha256'] == endpoint['native_input_group_sha256'] and
            marginal['endpoint_identity'] == {k: endpoint['native_group'][k] for k in marginal['endpoint_identity']},
            'Selected occurrence does not match the original report, endpoint and projection ledgers')

    cells = {cell_key(row): row for row in endpoint['endpoint_collections']}
    collectors = {row['contact_id']: row['slow_energy_keV'] for row in card['collectors']}
    xs, ys = (report[f'{face}_collecting_strips'] for face in ('x', 'y'))
    native_marginals = {cid: fsum(cell['deposit_keV'] for key, cell in cells.items() if cid in key)
                        for cid in collectors}
    require(sorted(collectors) == xs+ys == endpoint['collector_contact_ids'] and
            native_marginals == {int(cid): energy for cid, energy in marginal['ideal_strip_energy_keV'].items()} and
            all(fsum(collectors[cid] for cid in ids) == report[f'{face}_sum_keV']
                for face, ids in (('x', xs), ('y', ys))), 'Saved slow or endpoint strip margins differ')
    native = list(energy_pairings(xs, ys, native_marginals))
    require(native == marginal['ideal_pairings'], 'Saved endpoint reassociation differs')
    saved = {pair['index']: pair for pair in prior['pairings']}
    pairs = []
    for observed, recalculated, ideal in zip(card['pairings'], energy_pairings(xs, ys, collectors), native, strict=True):
        keys = ('index', 'energy_compatible')
        require(all(observed[k] == recalculated[k] for k in keys) and
                all(all(before[k] == after[k] for k in PAIR_KEYS) for before, after in
                    zip(observed['sites'], recalculated['sites'], strict=True)), 'Measured X/Y pairing differs')
        pairs.append(compare_pair(observed, saved.get(observed['index']), ideal, cells, source['source_position_mm']))
    allowed = [order for pair in pairs for order in pair['orders'] if order['kinematically_allowed']]
    require(len(allowed) == descriptor['allowed_hypotheses'] and
            sum(order['status'] == 'projected' for order in allowed) == descriptor['hypotheses'] and
            fsum(order['projected_mass'] for order in allowed) == descriptor['projected_mass'] and
            fsum(order['nominal_mass'] for order in allowed) == endpoint['allowed_order_mass'] and
            descriptor['projected_mass'] + descriptor['unresolved_mass'] == 1., 'Original order mass does not close')

    routed = []
    for (x, y), cell in cells.items():
        route = [dict(pairing_index=pair['index'], x_site_index=next((i for i, s in enumerate(pair['sites'])
                      if x == s['x_contact_id']), None), y_site_index=next((i for i, s in enumerate(pair['sites'])
                      if y == s['y_contact_id']), None)) for pair in pairs if pair['energy_compatible']]
        routed.append(cell | dict(x_strip=strip_label(x), y_strip=strip_label(y), readout_routes=route,
                                  measured_face_count=int(x in xs)+int(y in ys)))
    truth = endpoint['native_group']['truth_edep_keV']
    gaps = {f'missing_from_measured_{face}_keV': fsum(row['deposit_keV'] for cid, row in
            ((row[f'{face}_contact_id'], row) for row in routed) if cid not in ids)
            for face, ids in (('x', xs), ('y', ys))}
    require(all(value == marginal[key] for key, value in gaps.items()) and
            isclose(fsum(cell['deposit_keV'] for cell in routed), truth, rel_tol=0., abs_tol=1e-7) and
            all(isclose(fsum(native_marginals[cid] for cid in ids)+gaps[f'missing_from_measured_{face}_keV'], truth,
                        rel_tol=0., abs_tol=1e-7) for face, ids in (('x', xs), ('y', ys))), 'Native face energy does not close')
    return descriptor | dict(
        line_center_keV=center, native_group=endpoint['native_group'] | dict(chunk_index=source['chunk_index']),
        native_input_group_sha256=endpoint['native_input_group_sha256'], adc_window=window, pairings=pairs,
        collector_slow_energies=[dict(contact_id=cid, strip=strip_label(cid), slow_energy_keV=energy,
                                 endpoint_marginal_keV=native_marginals[cid]) for cid, energy in collectors.items()],
        x_slow_sum_keV=report['x_sum_keV'], y_slow_sum_keV=report['y_sum_keV'], endpoint_truth_deposit_keV=truth,
        measured_minus_truth_keV=report['energy_keV']-truth, endpoint_cells=routed, **gaps,
        weak_noncollector_contacts=[{key: row[key] for key in ('contact_id', 'adc_status', 'adc_detected',
                                    'adc_step_keV_equiv', 'endpoint_input_band', 'endpoint_input_keV')} |
                                    dict(strip=strip_label(row['contact_id'])) for row in endpoint['contacts']
                                    if row['endpoint_input_keV'] > 0.])


def run():
    hashes = {}
    prior = load_bound(PRIOR_STUDY, PRIOR_STUDY_SHA, hashes)
    pool = load_bound(V1_POOL, V1_POOL_SHA, hashes)
    influence = load_bound(INFLUENCE, INFLUENCE_SHA, hashes)
    endpoints = load_bound(ENDPOINTS, ENDPOINTS_SHA, hashes)
    marginals = load_bound(MARGINALS, MARGINALS_SHA, hashes)
    require(prior['original_pooled_sha256'] == V1_POOL_SHA and endpoints['status'] == marginals['status'] ==
            influence['status'] == 'completed' and influence['input_sha256'][PRIOR_STUDY.name] == PRIOR_STUDY_SHA and
            influence['input_sha256'][ENDPOINTS.name] == marginals['input_sha256'][ENDPOINTS.name] == ENDPOINTS_SHA,
            'The saved image, trigger selection and native ledgers must share the same baselines')
    endpoint_rows, marginal_rows = ({(row['block'], row['trigger_index']): row for row in artifact['events']}
                                    for artifact in (endpoints, marginals))
    require(endpoint_rows.keys() == marginal_rows.keys() and len(endpoint_rows) == 324,
            'Endpoint and marginal rosters must retain the 324 measured triggers')
    inputs = {item['name']: item for item in pool['inputs']}
    occurrences, blocks, line_baselines = [], {}, {}
    for layer, (block, ids) in SELECTED.items():
        line = influence['lines'][layer]
        selected = line['selected_pair_triggers']
        require([(row['block'], row['trigger_index']) for row in selected] == [(block, i) for i in ids],
                'Original cobalt trigger selection differs')
        item = inputs[block]
        report, plane, windows, source = read_block(item, hashes)
        prior_rows = {row['trigger_index']: row for row in prior['order_ledger'][block]}
        plane_rows = {row['trigger_index']: row for row in plane['triggers']}
        blocks[block] = {k: item[k] for k in ('clock_seed', 'noise_seed', 'plane_inputs')} | dict(source=source)
        line_baselines[layer] = {k: line[k] for k in (*ACCOUNTING, 'line_center_keV', 'distinct_projected_histories')}
        for row in selected:
            index = row['trigger_index']
            occurrences.append(compare_occurrence(row, line['line_center_keV'], report['triggers'][index-1],
                               plane_rows[index], prior_rows[index], endpoint_rows[block, index],
                               marginal_rows[block, index], window_receipt(windows, item, prior_rows[index]), source))
    return dict(kind='gegi_cobalt_history_readout_v1', status='completed', input_sha256=hashes,
                baseline={key: prior['views']['full']['layers']['all'][key] for key in ACCOUNTING},
                line_baselines=line_baselines, blocks=blocks, occurrences=occurrences,
                method=dict(positions='Saved center-template XYZ. Each cone stores its first site directly; its second '
                            'is recovered from the saved axis and separation. XY is fixed at strip centers.',
                            residual='Angle between back-projection axis and direction from vertex to programmed Co '
                            'position minus the energy-derived cone half-angle, in degrees. The programmed positions '
                            'are used only after the original fits, pairings and order masses are fixed.',
                            energy='Measured site energy averages the two slow strip energies. The ideal diagnostics '
                            'sum simulated deposited energy by endpoint intersection and independently by face. One '
                            'selected endpoint therefore contributes half its deposit to the ideal site-energy average.',
                            scope='Four selected trigger occurrences from two archived simulated histories. The cones '
                            'are conditional on a fully absorbed photon modeled with two measured sites.',
                            weak_step_lower_keV_equiv=endpoints['design']['minimum_weak_step_keV_equiv'],
                            collector_threshold_keV=endpoints['design']['collection_threshold_keV'],
                            new_transport_runs=0, new_drift_runs=0, new_adc_replays=0, new_waveform_fits=0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT, help='New JSON receipt in the private analysis folder')
    output = parser.parse_args().output.resolve()
    require(output.is_relative_to(LOCAL) and not output.exists(), 'Use a new path below the private analysis directory')
    files = (Path(__file__).resolve(), *(ROOT/'tools'/name for name in (
        'gegi_continuous_plane.py', 'gegi_digital_pairs.py', 'gegi_imaging.py', 'gegi_intersection_image_study.py',
        'gegi_trigger_windows.py', 'gegi_two_site_cfd_study.py')))
    hashes = {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in files}
    report = run() | dict(source_sha256=hashes)
    payload = json.dumps(report, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    require(all(digest(path.read_bytes()) == hashes[path.relative_to(ROOT).as_posix()] for path in files),
            'Study source changed during processing')
    with output.open('xb') as target:
        target.write(payload)
    print(f'{digest(payload)}  {output.name}')


if __name__ == '__main__':
    main()
