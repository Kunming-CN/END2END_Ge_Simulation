"""Bounded, lossless Ge-positive saved-event viewer. Standard library; no solver."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local/geometry-events-publication/bundle'
SAVED = ROOT / '.local/peak-native-delivery/cs10000-v2'
WORK = ROOT / '.local/million-transport-dev'
OUTPUT = WORK / 'hit-view'
SOURCES = ('tools/hit_event_view.py', 'tools/hit_event_view.html',
           'tools/test_hit_event_view.py', 'tools/HIT_EVENT_VIEW.md')
PINS = {'geometry_manifest': 'd188d2fba1b17248152b88c86fdac72962c364611599ff51161febccd9326a9f',
        'campaign_run': 'f563969cf57f3f6ff34c09dd4748ddafddcc3d7df8f4d06941b18e5212c5b43d'}
COUNTS = {'AK02': 121, 'SAP22': 115}
LABELS = {'compact': 'Compact full-energy SSE candidate',
          'compton1': 'One observed Compton site + absorption candidate',
          'compton2': 'Two observed Compton sites + absorption candidate',
          'full': 'Photon full-containment candidate',
          'partial': 'Partial photon-energy candidate',
          'unknown': 'Mixed / unknown photon ancestry or energy'}
METHOD = {
    'energy_tolerance_keV': 'max(1e-5, 1e-8 * source_photon_energy_keV)',
    'pulse_grouping': 'Positive Ge rows sorted by (time, raw_row_index); fixed [first, first+100000 ns) windows, matching frozen preparation. Raw clocks and relative delays retained.',
    'ancestry': 'Every positive Ge row must resolve through the complete saved track graph to exactly one common RadioactiveDecay photon with an ion parent. Missing/cyclic/mixed ancestry is unknown.',
    'containment': 'Ge energy in ONE pulse group matches that photon birth kinetic energy; no resolved non-Ge loss or positive Ge energy from that root outside the group above tolerance. Numerical candidate, not reconstructed energy.',
    'compact': 'Maximum pairwise distance between positive Ge deposit coordinates <= 1 mm. Sampling locations, not calibrated PSD or exact microscopic extent. No restriction on electron step count.',
    'compton': 'Child electron creation process compt on photon lineage. Exact (parent photon, time, x,y,z) duplicates form one observed creation site. Multiple electrons/steps do not count as multiple scatters. Unresolved coincident interactions remain possible.',
    'compton_candidates': 'Full containment plus exactly one/two observed Compton creation sites, all on the source photon and matched to a Ge photon STEP post vertex, followed (nondecreasing saved time) by a similarly matched phot electron creation site. No per-step process or residual photon energy is saved; physical interaction count/ordering is not certified.',
    'partial': 'Below source photon energy within one pulse group. Escape and unscored loss unresolved; positive non-Ge deposits on this ancestry are separately reported as direct evidence, not a complete energy balance.',
    'overlay': 'All selected Ge-positive primaries superimposed, not simultaneous decays. Default: every Ge STEP chord/deposit plus recorded photon STEP chords and photon births on contributing ancestry. No invented connections across air or between steps.',
    'limitations': 'Frozen nominal geometry/source. Not complete trajectories, SSD drift, Erec, calibrated CCE, PSD, efficiency, physical resolution, or measured-spectrum validation. Native-response failures do not remove radiation events.'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def safe(path, base, new=False):
    path, base = Path(path).absolute(), Path(base).resolve()
    require('..' not in path.parts and path == path.resolve() and path.is_relative_to(base)
            and path != base, 'escaped or linked path')
    require(not new or not path.exists(), 'refusing overwrite')
    return path


def verify(path, expected):
    require(digest(path) == expected, 'SHA-256 mismatch: ' + Path(path).name)


def source_hashes():
    return {name: digest(ROOT / name) for name in SOURCES}


def energy_tolerance(energy):
    return max(1e-5, 1e-8 * energy)


def energy_class(deposit, photon):
    tol = energy_tolerance(photon)
    if abs(deposit - photon) <= tol:
        return 'full'
    return 'partial' if deposit < photon - tol else 'unknown'


def ancestry(tracks, processes):
    """Return per-track source roots and graph errors, including unused graph rows."""
    by_id = {t['trackid']: t for t in tracks}
    errors = []
    if len(by_id) != len(tracks):
        errors.append('duplicate track IDs')
    roots = {}
    for tid in by_id:
        seen, found, cur = set(), [], tid
        while cur:
            if cur in seen:
                errors.append('cycle at track ' + str(cur)); break
            if cur not in by_id:
                errors.append('missing parent track ' + str(cur)); break
            seen.add(cur)
            t = by_id[cur]
            if t['particle'] == 22 and processes.get(t['procid']) == 'RadioactiveDecay':
                parent = by_id.get(t['parent_trackid'])
                if parent and parent['particle'] >= 1000000000:
                    found.append(cur)
                else:
                    errors.append('RDM photon without saved ion parent')
            cur = t['parent_trackid']
        roots[tid] = found
    return by_id, roots, sorted(set(errors))


def position(row):
    return tuple(row[k] for k in ('xloc', 'yloc', 'zloc'))


def diameter_mm(rows):
    points = list({position(r) for r in rows})
    return 1000 * max((math.dist(a, b) for i, a in enumerate(points) for b in points[i+1:]), default=0)


def pulse_groups(rows, horizon_ns):
    require(horizon_ns > 0 and math.isfinite(horizon_ns), 'invalid pulse horizon')
    groups = []
    for row in sorted((r for r in rows if r['edep'] > 0), key=lambda r: (r['time'], r['raw_row_index'])):
        if not groups or row['time'] - groups[-1][0]['time'] >= horizon_ns:
            groups.append([])
        groups[-1].append(row)
    return groups


def observed_sites(tracks, by_id, roots, root, processes, ge_rows):
    sites = {}
    for t in tracks:
        parent = by_id.get(t['parent_trackid'])
        proc = processes.get(t['procid'])
        if t['particle'] != 11 or proc not in ('compt', 'phot') or not parent or parent['particle'] != 22:
            continue
        if roots.get(parent['trackid']) != [root]:
            continue
        key = (proc, parent['trackid'], t['time'], *position(t))
        if key not in sites:
            matched = [r['raw_row_index'] for r in ge_rows if r['trackid'] == parent['trackid']
                       and math.dist(position(t), tuple(r[k+'_post'] for k in ('xloc', 'yloc', 'zloc'))) <= 1e-9]
            sites[key] = {'process': proc, 'parent_photon_trackid': parent['trackid'],
                          'time_ns': t['time'], 'position_m': list(position(t)),
                          'electron_track_ids': [], 'electron_raw_rows': [], 'matched_ge_photon_step_rows': matched,
                          'location_evidence': 'Ge STEP post vertex within 1e-9 m' if matched else 'Ge location unresolved'}
        sites[key]['electron_track_ids'].append(t['trackid'])
        sites[key]['electron_raw_rows'].append(t['raw_row_index'])
    return sorted(sites.values(), key=lambda s: (s['time_ns'], s['parent_photon_trackid'], s['process'], s['position_m']))


def classify(event, processes, horizon_ns=100000):
    tables = event['tables']; ge = tables['stp/germanium']
    by_id, roots, graph_errors = ancestry(tables['tracks'], processes)
    positive = [r for r in ge if r['edep'] > 0]
    relevant_roots = {root for r in positive for root in roots.get(r['trackid'], [])}
    relevant_photons = set()
    for r in positive:
        tid, seen = r['trackid'], set()
        while tid in by_id and tid not in seen:
            seen.add(tid)
            if by_id[tid]['particle'] == 22:
                relevant_photons.add(tid)
            tid = by_id[tid]['parent_trackid']
    # Include photon descendants of a contributing root, including escaping branches.
    relevant_photons.update(tid for tid, t in by_id.items() if t['particle'] == 22 and relevant_roots.intersection(roots.get(tid, [])))
    result = {'event_id': event['event_id'], 'ge_energy_keV': math.fsum(r['edep'] for r in positive),
              'ge_step_count': len(ge), 'positive_ge_step_count': len(positive),
              'graph_errors': graph_errors, 'relevant_photon_track_ids': sorted(relevant_photons), 'groups': []}
    for group_id, rows in enumerate(pulse_groups(ge, horizon_ns)):
        origin = rows[0]['time']; root_sets = [roots.get(r['trackid'], []) for r in rows]
        unique = sorted({v for rs in root_sets for v in rs})
        row_ids = {r['raw_row_index'] for r in rows}
        identity_errors = [r['raw_row_index'] for r in rows if r['trackid'] not in by_id or
                           any(r[k] != by_id[r['trackid']][k] for k in ('parent_trackid', 'particle'))]
        g = {'group_id': group_id, 'origin_time_ns': origin, 'horizon_ns': horizon_ns,
             'ge_raw_row_indices': [r['raw_row_index'] for r in rows],
             'relative_delays_ns': [r['time'] - origin for r in rows],
             'ge_energy_keV': math.fsum(r['edep'] for r in rows), 'source_photon_track_ids': unique,
             'deposit_diameter_mm': diameter_mm(rows), 'step_identity_errors': identity_errors,
             'categories': ['unknown'], 'source_photon_energy_keV': None, 'sites': [],
             'observed_compton_site_count': None,
             'limitation': 'Creation sites are observed/inferred topology, not exact interaction multiplicity; no per-step process or residual kinetic energy.'}
        if graph_errors or identity_errors or len(unique) != 1 or any(len(rs) != 1 for rs in root_sets):
            g['reason'] = 'Missing, cyclic, mixed or non-photon ancestry; no photon-energy classification.'
        else:
            root = unique[0]; photon = by_id[root]['ekin'] * 1000
            tol = energy_tolerance(photon)
            nonge = [(name, r) for name, rr in tables.items() if name.startswith('stp/') and name != 'stp/germanium'
                     for r in rr if r['edep'] > 0 and roots.get(r['trackid']) == [root]]
            outside = [r for r in positive if r['raw_row_index'] not in row_ids and roots.get(r['trackid']) == [root]]
            sites = observed_sites(tables['tracks'], by_id, roots, root, processes, ge)
            # Keep complete root sites as evidence, but only in-window sites count for this group.
            # The first Ge photon step stores PRE time while electron birth is at POST time.
            in_window = [s for s in sites if 0 <= s['time_ns'] - origin < horizon_ns]
            comps = [s for s in in_window if s['process'] == 'compt']
            photos = [s for s in in_window if s['process'] == 'phot']
            passive_energy = math.fsum(r['edep'] for _, r in nonge)
            outside_energy = math.fsum(r['edep'] for r in outside)
            g.update(source_photon_energy_keV=photon, energy_tolerance_keV=tol,
                     energy_residual_keV=g['ge_energy_keV'] - photon,
                     source_photon_birth_time_ns=by_id[root]['time'],
                     source_photon_delay_to_group_ns=origin - by_id[root]['time'],
                     root_non_ge_energy_keV=passive_energy,
                     root_non_ge_rows=[{'table': k, 'raw_row_index': r['raw_row_index']} for k, r in nonge],
                     root_other_group_ge_energy_keV=outside_energy,
                     sites=sites, observed_compton_site_count=len(comps))
            category = energy_class(g['ge_energy_keV'], photon) if photon > 0 else 'unknown'
            if category == 'full' and (passive_energy > tol or outside_energy > tol):
                category = 'unknown'
            g['categories'] = [category]
            if category == 'full':
                if g['deposit_diameter_mm'] <= 1:
                    g['categories'].append('compact')
                direct_ge = lambda s: s['parent_photon_trackid'] == root and bool(s['matched_ge_photon_step_rows'])
                if len(comps) in (1, 2) and all(direct_ge(s) for s in comps) and any(
                        direct_ge(s) and s['time_ns'] >= max(c['time_ns'] for c in comps) for s in photos):
                    g['categories'].append('compton' + str(len(comps)))
                g['reason'] = 'One pulse group numerically contains the linked photon birth energy; transport-only candidate.'
            elif category == 'partial':
                g['reason'] = ('Recorded positive non-Ge loss on this photon ancestry; remaining deficit unresolved.'
                               if passive_energy > 0 else 'Escape / non-Ge or unscored loss unresolved; no precise escape claim.')
            else:
                g['reason'] = 'Energy exceeds linked photon budget or containment conflicts with other recorded loss.'
        result['groups'].append(g)
    return result


def pack(event, columns):
    return {'event_id': event['event_id'], 'tables': {k: [[r[c] for c in columns[k]] for r in rows]
            for k, rows in event['tables'].items() if rows}}


def unpack(event, columns):
    return {'event_id': event['event_id'], 'tables': {k: [dict(zip(cols, row)) for row in event['tables'].get(k, [])]
                                                   for k, cols in columns.items()}}


def inspect_inputs():
    verify(SOURCE / 'manifest.json', PINS['geometry_manifest'])
    verify(SAVED / 'run.json', PINS['campaign_run'])
    manifest, run = read(SOURCE / 'manifest.json'), read(SAVED / 'run.json')
    require(manifest['status'] == 'complete' and run['status'] == 'completed_with_native_failures', 'wrong receipts')
    require(manifest['campaign_run_sha256'] == PINS['campaign_run'], 'campaign binding mismatch')
    require(manifest['computational_dependency_sha256'] == run['source_sha256'], 'source provenance mismatch')
    for name, sha in run['source_sha256'].items():
        verify(safe(ROOT / name, ROOT), sha)
    # ALL original event chunks/scenes are verified, not only selected chunks.
    for name, info in manifest['files'].items():
        p = safe(SOURCE / name, SOURCE); verify(p, info['sha256'])
        require(p.stat().st_size == info['bytes'], 'source size mismatch')
    prepared, receipts = {}, {'run.json': PINS['campaign_run']}
    for model in COUNTS:
        scene = read(SOURCE / model / 'scene.json')
        require(scene['source_position_global_mm'] == [0, 37.073, .29], 'source moved')
        for name, sha in scene['originals_sha256'].items():
            p = safe(SAVED / model / 'transport' / name, SAVED / model / 'transport')
            verify(p, sha); receipts[f'{model}/transport/{name}'] = sha
        prepared[model] = read(SAVED / model / 'transport/prepared.json')
        require(prepared[model]['grouping_policy']['horizon_ns'] == 100000, 'changed pulse horizon')
        require(scene['raw_lh5_sha256'] == read(SAVED / model / 'transport/run.json')['source_lh5_sha256'], 'raw source mismatch')
    return manifest, run, prepared, receipts


def analyze():
    manifest, run, prepared, receipts = inspect_inputs()
    payloads = {}
    for model, count in COUNTS.items():
        scene = read(SOURCE / model / 'scene.json'); index = scene['event_index']
        columns = {k: ['raw_row_index', *schema] for k, schema in index['raw_columns'].items()}
        processes = {p['procid']: p['name'] for p in index['processes']}
        selected, evidence, ids, totals = [], [], [], Counter()
        next_id = 0
        for chunk in index['chunks']:
            data = read(safe(SOURCE / model / chunk['file'], SOURCE / model))
            require(data['model'] == model and data['first'] == next_id == chunk['first'] and
                    len(data['events']) == chunk['count'], 'chunk census mismatch')
            for event in data['events']:
                require(event['event_id'] == next_id, 'event ID mismatch'); next_id += 1
                for key, rows in event['tables'].items():
                    for r in rows:
                        require(r['evtid'] == event['event_id'] and r['raw_row_index'] == totals[key], 'raw row census mismatch')
                        require(set(r) == set(columns[key]), 'column loss')
                        totals[key] += 1
                if not any(r['edep'] > 0 for r in event['tables']['stp/germanium']):
                    continue
                packed = pack(event, columns)
                require(unpack(packed, columns) == event, 'lossy selected record encoding')
                selected.append(packed); ids.append(event['event_id'])
                evidence.append(classify(event, processes, prepared[model]['grouping_policy']['horizon_ns']))
        require(next_id == 10000 and ids == index['ge_hit_ids'] and len(ids) == count, 'Ge-positive census mismatch')
        require(dict(totals) == {k: v for k, v in index['raw_rows'].items() if v}, 'raw totals mismatch')
        require(10000-count == run['models'][model]['counts']['zero_deposit_primaries'], 'receipt census mismatch')
        categories = {key: [{'event_id': e['event_id'], 'group_id': g['group_id']} for e in evidence
                            for g in e['groups'] if key in g['categories']] for key in LABELS}
        # Prefer the highest observed photon-energy family, without a hard-coded Cs line band.
        representatives = {}
        for key, members in categories.items():
            lookup = {(e['event_id'], g['group_id']): g for e in evidence for g in e['groups']}
            highest = max((lookup[(m['event_id'], m['group_id'])]['source_photon_energy_keV'] or 0 for m in members), default=0)
            family = [m for m in members if abs((lookup[(m['event_id'], m['group_id'])]['source_photon_energy_keV'] or 0)-highest) <= energy_tolerance(highest)]
            metric = 'deposit_diameter_mm' if key == 'compact' else 'ge_energy_keV'
            ordered = sorted(family, key=lambda m: (lookup[(m['event_id'], m['group_id'])][metric], m['event_id'], m['group_id']))
            representatives[key] = ordered[len(ordered)//2] if ordered else None
        payloads[model] = {'schema_version': 1, 'model': model, 'event_ids': ids,
                           'columns': columns, 'events': selected, 'evidence': evidence,
                           'categories': categories, 'representatives': representatives,
                           'representative_rule': 'Highest observed source-photon energy family (same numerical tolerance), then upper median deposit diameter for compact candidates or Ge energy otherwise; ties by original primary/group ID. No fixed Cs energy band. Illustrative, not statistical typicality.'}
    return payloads, manifest, run, receipts


def freeze(path):
    path = safe(path, WORK, new=True)
    require(path.name.startswith('viewer-') and path.suffix == '.json', 'freeze evidence requires viewer-*.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(encoded({'source_sha256': source_hashes(), 'input_pins': PINS}))


def build(output, frozen):
    output = safe(output, WORK, new=True)
    require(output == OUTPUT, 'only the assigned hit-view output is writable')
    frozen = safe(frozen, WORK)
    require(frozen.name.startswith('viewer-'), 'wrong freeze record')
    frozen_data = read(frozen)
    require(frozen_data == {'source_sha256': source_hashes(), 'input_pins': PINS}, 'sources not frozen')
    hashes = source_hashes()
    payloads, upstream, run, receipts = analyze()
    require(source_hashes() == hashes, 'source changed during analysis')
    output.mkdir(parents=True)
    result = {'schema_version': 1, 'status': 'complete', 'source_sha256': hashes,
              'input_pins': PINS, 'receipt_sha256': receipts, 'computational_dependency_sha256': run['source_sha256'],
              'method': METHOD, 'category_labels': LABELS, 'upstream': upstream['upstream'],
              'runtime': {'python': sys.version, 'randomness': 'none; deterministic saved-data analysis'},
              'population': 'All 121 AK02 / 115 SAP22 Ge-positive primaries only. All 20,000 decays remain in the existing all-event viewer.',
              'all_events_url': '../cs137-10k-geometry/geometry.html', 'models': {}, 'files': {}}
    for model, payload in payloads.items():
        (output / model).mkdir()
        for name, data in [('scene.json', (SOURCE / model / 'scene.json').read_bytes()),
                           ('selected.json.gz', gzip.compress(encoded(payload), compresslevel=9, mtime=0))]:
            with (output / model / name).open('xb') as f:
                f.write(data)
        verify(output / model / 'scene.json', upstream['files'][f'{model}/scene.json']['sha256'])
        result['models'][model] = {'scene': f'{model}/scene.json', 'selected': f'{model}/selected.json.gz',
                                   'selected_count': len(payload['events']),
                                   'category_group_counts': {k: len(v) for k, v in payload['categories'].items()},
                                   'source_scene_sha256': upstream['files'][f'{model}/scene.json']['sha256']}
    for name, data in [('hit_event_view.html', (ROOT / SOURCES[1]).read_bytes()),
                       ('README.md', (ROOT / SOURCES[3]).read_bytes())]:
        with (output / name).open('xb') as f:
            f.write(data)
    require(source_hashes() == hashes, 'source changed during export; preserve incomplete output')
    inspect_inputs()  # Refuse source/receipt changes before issuing a complete derivative receipt.
    for path in sorted(output.rglob('*')):
        if path.is_file():
            result['files'][path.relative_to(output).as_posix()] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    require(sum(v['bytes'] for v in result['files'].values()) <= 4_000_000, 'bundle exceeds bounded 4 MB budget')
    with (output / 'manifest.json').open('xb') as f:
        f.write(encoded(result))
    return result


def validate(output):
    output = safe(output, WORK)
    manifest = read(output / 'manifest.json')
    require(manifest['status'] == 'complete' and manifest['source_sha256'] == source_hashes(), 'incomplete or changed-source bundle')
    require(manifest['input_pins'] == PINS, 'input pins changed')
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    require(actual == {*manifest['files'], 'manifest.json'}, 'output file census mismatch')
    for name, info in manifest['files'].items():
        p = safe(output / name, output); verify(p, info['sha256'])
        require(p.stat().st_size == info['bytes'], 'output size mismatch')
    payloads, _, _, receipts = analyze()
    require(receipts == manifest['receipt_sha256'], 'receipt mismatch')
    for model, expected in payloads.items():
        verify(output / model / 'scene.json', digest(SOURCE / model / 'scene.json'))
        raw = gzip.decompress((output / model / 'selected.json.gz').read_bytes())
        require(raw == encoded(expected), 'selected records/classification changed')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--freeze', type=Path)
    mode.add_argument('--build', action='store_true')
    mode.add_argument('--validate', action='store_true')
    parser.add_argument('--frozen', type=Path, default=WORK / 'viewer-freeze.json')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.freeze:
        freeze(args.freeze); print('Frozen source hashes recorded. No bundle generated.')
    elif args.check:
        data, _, _, _ = analyze()
        print(json.dumps({m: {'events': len(p['events']), 'groups': {k: len(v) for k, v in p['categories'].items()}}
                          for m, p in data.items()}, indent=2))
    else:
        result = build(args.output, args.frozen) if args.build else validate(args.output)
        print(json.dumps({'status': result['status'], 'models': result['models'],
                          'bytes': sum(v['bytes'] for v in result['files'].values())}, indent=2))


if __name__ == '__main__':
    main()
