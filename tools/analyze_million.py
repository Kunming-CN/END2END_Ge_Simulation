"""Read-only, chunk-bounded analysis of completed long_transport compact HDF5.

No transport, SSD, readout, package installation, or archive extraction is invoked.
The separate supervisor audits the lossless raw archives.
"""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import platform
import sys
import time
from datetime import datetime, timezone

import h5py
import numpy as np
import hit_event_view as hv

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.local/million-analysis'
CAMPAIGN = ROOT / '.local/cs137-1m'
OLD = ROOT / '.local/peak-native-delivery/cs10000-v2'
OLD_VIEW = ROOT / '.local/million-transport-dev/hit-view'
MODELS = ('AK02', 'SAP22')
SOURCES = ('tools/analyze_million.py', 'tools/test_analyze_million.py',
           'tools/MILLION_ANALYSIS.md', 'tools/hit_event_view.py', 'tools/long_transport.py')
HORIZON = 100000
CATEGORIES = tuple(hv.LABELS)
LIMITATIONS = [
    'Deposition truth Edep only; not reconstructed energy, an ADC spectrum, or measured data.',
    'No SSD, readout, electronics noise, fitted FWHM, calibrated CCE or physical resolution is included.',
    'Nominal uncollimated source and saved geometry; no matched experimental control or efficiency validation.',
    'Material energy is recorded-only deposition. Unscored world air and escaping energy prevent energy closure.',
    'STEP chords and track birth records are not complete trajectories across unscored material.',
    'Raw scoring coordinates are global metres, despite xloc/yloc/zloc field names; no transform is applied.',
    'Isolated 100 us groups reset at each first positive Ge row; no activity, live-time or pileup model.',
    'Full/compact/Compton classifications are ancestry/tolerance candidates from the existing classifier; categories overlap.',
    '660--663 keV describes emitted line photons. The inclusive 650--670 keV Edep band is not an exact photopeak.',
    'The compact audit checks all-primary scalars and retained detail. All 200 raw archives are audited separately by the supervisor.',
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hv.digest(path)


def read(path):
    return hv.read(path)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        f.write('\n')


def output_path(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.parent == BASE.resolve() and p.name.startswith('analysis-'),
            'Output must be a new .local/million-analysis/analysis-* path')
    require(not p.exists(), 'refusing overwrite')
    return p


def source_hashes():
    return {n: sha(ROOT / n) for n in SOURCES}


def check_sources(frozen):
    require(frozen['source_sha256'] == source_hashes(), 'Analysis source changed after freeze')


def seed_for(base, model, index):
    h = hashlib.sha256(f'{base}/{model}/{index}'.encode()).digest()
    return 1 + int.from_bytes(h[:8], 'big') % 2147483646


def plans(config):
    require(config['models'] == list(MODELS), 'Unexpected model census')
    n, size = config['events_per_model'], config['chunk_size']
    require(type(n) is int and 0 < n <= 1000000 and type(size) is int and 0 < size <= 10000,
            'Invalid campaign bounds')
    rows = [dict(model=m, index=i, start=s, count=min(size, n-s),
                 seed=seed_for(config['seed'], m, i))
            for m in MODELS for i, s in enumerate(range(0, n, size))]
    require(len({r['seed'] for r in rows}) == len(rows), 'Seed collision')
    return rows


def verified(path, expected):
    require(sha(path) == expected, 'Hash mismatch: ' + str(path.relative_to(ROOT)))


def campaign_inputs(directory):
    c = read(directory / 'config.json')
    digest = sha(directory / 'config.json')
    require((directory / 'config.sha256').read_text().strip() == digest, 'Config hash mismatch')
    require(c['kind'] == 'long_cs137_transport_v1', 'Unknown campaign')
    complete = read(directory / 'COMPLETE.json')
    require(complete['status'] == 'completed_transport' and complete['kind'] == c['kind']
            and complete['config_sha256'] == digest, 'Incomplete/mismatched completion receipt')
    rows = plans(c)
    require(complete['completed_decays'] == sum(r['count'] for r in rows), 'Completion census')
    require(set(complete['models']) == set(MODELS), 'Completion models')
    for name, value in c['source_sha256'].items():
        p = (ROOT / name).resolve()
        require(p.is_relative_to(ROOT), 'Source outside project')
        verified(p, value)
    templates = {}
    for model in MODELS:
        require(set(c['templates'][model]) == {'geometry.gdml', 'run.mac', 'prepared.json',
                                              'geometry-report.json', 'scenario.json'}, 'Template inventory')
        for name, value in c['templates'][model].items():
            verified(directory / 'inputs' / model / name, value)
            verified(OLD / model / 'transport' / name, value)
        templates[model] = read(directory / 'inputs' / model / 'prepared.json')
        require(templates[model]['grouping_policy']['horizon_ns'] == HORIZON, 'Grouping changed')
        require(templates[model]['decay_photon_line_window_keV'] == [660, 663], 'Line definition changed')
    return c, complete, rows, templates


def checkpoint(directory, row, config_hash):
    base = directory / 'chunks' / row['model'] / f"{row['index']:04d}"
    done = read(base / 'DONE.json')
    require(done['status'] == 'verified' and done['plan'] == row and
            done['config_sha256'] == config_hash, 'DONE plan/config/seed mismatch')
    attempt = (base / done['attempt']).resolve()
    require(attempt.parent == base.resolve(), 'Escaping attempt')
    require(set(done['files_sha256']) == {'compact.h5', 'transport.json', 'archive.json', 'truth.lh5.gz'},
            'DONE inventory mismatch')
    for name in ('compact.h5', 'transport.json', 'archive.json'):
        verified(attempt / name, done['files_sha256'][name])
    transport, archive = read(attempt / 'transport.json'), read(attempt / 'archive.json')
    require(transport['plan'] == row and transport['config_sha256'] == config_hash and
            transport['status'] == 'process_completed' and transport['returncode'] == 0, 'Transport receipt')
    expected_command = ['remage', '--flat-output', '-t', '1', '--rand-seed', str(row['seed']),
                        '-o', 'truth.lh5', '-g', 'geometry.gdml', '--', 'run.mac']
    require(transport['command'] == expected_command, 'Transport command/seed mismatch')
    require(archive['raw_sha256'] == transport['raw_sha256'] and
            archive['archive_sha256'] == done['files_sha256']['truth.lh5.gz'] and
            archive['archive_bytes'] == (attempt / 'truth.lh5.gz').stat().st_size, 'Archive receipt binding')
    require(sum((attempt/n).stat().st_size for n in done['files_sha256']) == done['artifact_bytes'],
            'DONE artifact byte count')
    evidence = dict(plan=row, done_sha256=sha(base/'DONE.json'), attempt=done['attempt'],
                    files_sha256=done['files_sha256'], raw_sha256=archive['raw_sha256'],
                    raw_bytes=archive['raw_bytes'], archive_content_audit='separate supervisor',
                    transport_wall_seconds=transport['wall_seconds'])
    return attempt / 'compact.h5', done, evidence


def scalar(v):
    if hasattr(v, 'item'):
        v = v.item()
    if isinstance(v, bytes):
        v = v.decode('utf-8')
    require(isinstance(v, (str, int, float, bool)), 'Unsupported scalar')
    require(not isinstance(v, float) or math.isfinite(v), 'Nonfinite detail')
    return v


def load_chunk(path, row, template, raw_hash):
    """One chunk in memory. Validate semantics even if a mutated file was rehashed."""
    n, start = row['count'], row['start']
    with h5py.File(path, 'r') as f:
        require(set(f) == {'events', 'details', 'row_maps', 'processes'}, 'Compact top-level schema')
        require(f.attrs['kind'] == 'compact_cs137_transport_v1' and
                f.attrs['primary_count'] == n and f.attrs['global_offset'] == start and
                f.attrs['model_id'] == row['model'] and f.attrs['raw_sha256'] == raw_hash, 'Compact identity')
        meta = json.loads(f.attrs['metadata_json'])
        expected_meta = dict(template, primary_count=n, seed=row['seed'])
        require(meta == expected_meta, 'Compact metadata changed beyond count/seed')
        ledger = {k: ds[:] for k, ds in f['events'].items()}
        require(set(ledger) == {'local_event_id', 'global_decay_id', 'ge_energy_keV', 'has_ge_energy',
                                'decay_photons', 'line_photons', 'material_energy_keV'}, 'Ledger columns')
        require(all(len(a) == n for a in ledger.values()), 'Ledger census')
        for key, expected in [('local_event_id', np.arange(n)), ('global_decay_id', np.arange(start, start+n))]:
            require(ledger[key].dtype.kind in 'iu' and np.array_equal(ledger[key], expected), 'Duplicate/missing '+key)
        ge = ledger['ge_energy_keV']
        require(ge.ndim == 1 and np.isfinite(ge).all() and (ge >= 0).all(), 'Invalid Ge energy')
        require(ledger['has_ge_energy'].dtype.kind == 'b' and
                np.array_equal(ledger['has_ge_energy'], ge > 0), 'Zero census mismatch')
        for key in ('decay_photons', 'line_photons'):
            require(ledger[key].ndim == 1 and ledger[key].dtype.kind in 'iu' and (ledger[key] >= 0).all(), 'Photon count')
        require((ledger['line_photons'] <= ledger['decay_photons']).all(), 'Line exceeds photon census')
        mats = json.loads(f['events/material_energy_keV'].attrs['materials_json'])
        material = ledger['material_energy_keV']
        require(mats == sorted(set(meta['material_tables'].values())) and material.shape == (n, len(mats))
                and np.isfinite(material).all() and (material >= 0).all(), 'Material ledger')
        require(np.allclose(material[:, mats.index('G4_Ge')], ge, rtol=1e-12, atol=1e-10), 'Material/Ge mismatch')
        for k in ('ge_energy_keV', 'material_energy_keV'):
            require(f['events/'+k].attrs['units'] == 'keV', 'Ledger units')
        proc_ids = f['processes/procid'][:]
        processes = dict(zip(map(int, proc_ids), map(scalar, f['processes/name'][:])))
        require(len(processes) == len(proc_ids), 'Duplicate process IDs')
        positive_ids = np.flatnonzero(ge > 0)
        tables = ['vtx', 'particles', 'tracks', *sorted(meta['material_tables'])]
        events = {int(i): {'event_id': int(i), 'tables': {k: [] for k in tables}} for i in positive_ids}
        raw_totals, schemas = {}, {}
        retained_ge = np.zeros(n)
        positive_material = np.zeros_like(material)
        for key in tables:
            table = f['details/'+key]
            arrays = {k: ds[:] for k, ds in table.items()}
            ids = arrays['evtid']; maps = f['row_maps/'+key][:]
            require(ids.ndim == 1 and ids.dtype.kind in 'iu' and (ids >= 0).all() and (ids < n).all()
                    and (np.diff(ids.astype(np.int64)) >= 0).all(), 'Invalid table event IDs: '+key)
            require(maps.dtype.kind in 'iu' and len(maps) == len(ids) and (maps >= 0).all()
                    and (np.diff(maps.astype(np.int64)) > 0).all(), 'Duplicate/unordered raw row map: '+key)
            require(all(a.ndim == 1 and len(a) == len(ids) for a in arrays.values()), 'Ragged table')
            require(all(np.isfinite(a).all() for a in arrays.values() if a.dtype.kind == 'f'), 'Nonfinite table')
            schemas[key] = {k: {'dtype': str(ds.dtype), 'attrs': {a: scalar(v) for a, v in ds.attrs.items()}}
                            for k, ds in table.items()}
            for name, ds in table.items():
                unit = ('m' if name.startswith(('xloc', 'yloc', 'zloc', 'dist_to_surf')) else
                        'ns' if name == 'time' else 'keV' if name == 'edep' else 'MeV' if name == 'ekin' else None)
                require(unit is None or ds.attrs.get('units') == unit, 'Unexpected units: '+key+'/'+name)
            if key in ('vtx', 'particles'):
                require(np.array_equal(ids, np.arange(n)) and np.array_equal(maps, np.arange(n)), 'Primary census')
            if key.startswith('stp/'):
                require((arrays['edep'] >= 0).all(), 'Negative deposition')
                sums = np.bincount(ids, weights=arrays['edep'], minlength=n)
                positive_material[:, mats.index(meta['material_tables'][key])] += sums
                if key == 'stp/germanium':
                    retained_ge = sums
                    require(np.array_equal(maps, np.arange(len(maps))), 'Incomplete Ge row map')
            raw_totals[key] = len(ids)
            # Row maps refer to original raw tables, never compact-table offsets.
            for j in np.flatnonzero(np.isin(ids, positive_ids)):
                events[int(ids[j])]['tables'][key].append(
                    {'raw_row_index': int(maps[j]), **{k: scalar(a[j]) for k, a in arrays.items()}})
        require(np.allclose(retained_ge, ge, rtol=1e-12, atol=1e-10), 'Ge row/scalar disagreement')
        require(np.allclose(positive_material[positive_ids], material[positive_ids], rtol=1e-12, atol=1e-10),
                'Positive-event material detail/scalar disagreement')
        for i, event in events.items():
            tracks = event['tables']['tracks']
            # Duplicate track IDs are a classifier graph error: retain the group as unknown.
            emitted = [t for t in tracks if t['particle'] == 22 and
                       'radioactivedecay' in processes.get(t['procid'], '').lower()]
            require(len(emitted) == ledger['decay_photons'][i] and
                    sum(660 <= t['ekin']*1000 <= 663 for t in emitted) == ledger['line_photons'][i],
                    'Positive-event photon denominator mismatch')
            require(math.fsum(r['edep'] for r in event['tables']['stp/germanium']) == ge[i], 'Exact Ge sum mismatch')
        counts = dict(decays=n, ge_positive=len(events), decay_photons=int(ledger['decay_photons'].sum()),
                      line_photons=int(ledger['line_photons'].sum()))
        return dict(ledger=ledger, events=events, processes=processes, counts=counts, materials=mats,
                    retained_raw_rows=raw_totals, schemas=schemas)


class Histogram:
    """Disjoint exact zero, [lo,hi) bins excluding zero, and explicit tails."""
    def __init__(self, edges=None):
        self.edges = np.asarray(np.arange(0, 1401, dtype=float) if edges is None else edges)
        require(len(self.edges) >= 2 and np.isfinite(self.edges).all() and (np.diff(self.edges) > 0).all(), 'Bin edges')
        self.bins = np.zeros(len(self.edges)-1, dtype=np.int64)
        self.zero = self.under = self.over = self.total = 0

    def add(self, values):
        a = np.asarray(values, dtype=float)
        require(np.isfinite(a).all(), 'Nonfinite histogram input')
        self.total += len(a); self.zero += int((a == 0).sum())
        a = a[a != 0]
        self.under += int((a < self.edges[0]).sum()); self.over += int((a >= self.edges[-1]).sum())
        inside = a[(a >= self.edges[0]) & (a < self.edges[-1])]
        self.bins += np.bincount(np.searchsorted(self.edges, inside, side='right')-1, minlength=len(self.bins))

    def result(self):
        require(self.total == self.zero+self.under+self.over+int(self.bins.sum()), 'Histogram census')
        return dict(edges_keV=self.edges.tolist(), counts=self.bins.tolist(), exact_zero=self.zero,
                    underflow=self.under, overflow=self.over, total=self.total,
                    convention='exact zero separate; other bins [lo,hi), underflow < first, overflow >= last')


def classify_retained(event, processes, classifier=hv.classify):
    """Classifier failures retain every positive row and group with an explicit error."""
    try:
        result = classifier(event, processes, HORIZON)
        require(result['event_id'] == event['event_id'], 'Classifier identity')
        expected = hv.pulse_groups(event['tables']['stp/germanium'], HORIZON)
        require(len(result['groups']) == len(expected), 'Classifier dropped a group')
        for i, (g, rows) in enumerate(zip(result['groups'], expected)):
            require(g['group_id'] == i and g['ge_raw_row_indices'] == [r['raw_row_index'] for r in rows]
                    and g['ge_energy_keV'] == math.fsum(r['edep'] for r in rows), 'Classifier group census')
        return result
    except Exception as error:
        groups = []
        for i, rows in enumerate(hv.pulse_groups(event['tables']['stp/germanium'], HORIZON)):
            groups.append(dict(group_id=i, origin_time_ns=rows[0]['time'], horizon_ns=HORIZON,
                               ge_raw_row_indices=[r['raw_row_index'] for r in rows],
                               relative_delays_ns=[r['time']-rows[0]['time'] for r in rows],
                               ge_energy_keV=math.fsum(r['edep'] for r in rows), categories=['unknown'],
                               source_photon_energy_keV=None, source_photon_track_ids=[],
                               observed_compton_site_count=None, reason='Classifier failure; no candidate inferred'))
        return dict(event_id=event['event_id'], groups=groups,
                    classifier_error={'type': type(error).__name__, 'message': str(error)})


class Families:
    def __init__(self):
        self.rows = []

    def add(self, group):
        energy = group['source_photon_energy_keV']
        match = next((r for r in self.rows if (energy is None and r['anchor_keV'] is None) or
                      (energy is not None and r['anchor_keV'] is not None and
                       abs(energy-r['anchor_keV']) <= hv.energy_tolerance(r['anchor_keV']))), None)
        if match is None:
            match = dict(anchor_keV=energy, min_keV=energy, max_keV=energy, groups=0,
                         categories={k: 0 for k in CATEGORIES})
            self.rows.append(match)
        match['groups'] += 1
        if energy is not None:
            match['min_keV'] = min(match['min_keV'], energy); match['max_keV'] = max(match['max_keV'], energy)
        for category in group['categories']:
            match['categories'][category] += 1


def ratio(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator,
                fraction=numerator/denominator if denominator else None)


def representative_rank(group, identity):
    energy = group['source_photon_energy_keV']
    preferred = energy is not None and abs(energy-661.657) <= hv.energy_tolerance(661.657)
    return (not preferred, abs(energy-661.657) if energy is not None else float('inf'),
            identity['global_decay_id'], group['group_id'])


def compare_old():
    run, manifest = read(OLD/'run.json'), read(OLD_VIEW/'manifest.json')
    verified(OLD/'run.json', hv.PINS['campaign_run'])
    require(manifest['input_pins']['campaign_run'] == hv.PINS['campaign_run'] and
            manifest['source_sha256']['tools/hit_event_view.py'] == sha(ROOT/'tools/hit_event_view.py'), 'Old classification binding')
    result = {'description': 'Descriptive simulation sample comparison only; different random seeds, not a matched experimental control.',
              'run_sha256': sha(OLD/'run.json'), 'viewer_manifest_sha256': sha(OLD_VIEW/'manifest.json'), 'models': {}}
    for m in MODELS:
        selected = OLD_VIEW/m/'selected.json.gz'
        verified(selected, manifest['files'][m+'/selected.json.gz']['sha256'])
        with gzip.open(selected, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        c = run['models'][m]['counts']; categories = Counter(); families = Families(); line_full = set()
        for e in data['evidence']:
            for g in e['groups']:
                categories.update(g['categories']); families.add(g)
                if 'full' in g['categories'] and 660 <= (g['source_photon_energy_keV'] or 0) <= 663:
                    line_full.add((e['event_id'], g['source_photon_track_ids'][0]))
        require(len(data['events']) == c['initial_decays']-c['zero_deposit_primaries'], 'Old positive census')
        require(dict(categories) == {k: v for k, v in manifest['models'][m]['category_group_counts'].items() if v}, 'Old categories')
        result['models'][m] = dict(initial_decays=c['initial_decays'], positive_ge_decays=len(data['events']),
                                  isolated_groups=sum(len(e['groups']) for e in data['evidence']),
                                  emitted_RDM_photons=c['decay_photons'], emitted_line_photons=c['line_photons'],
                                  category_group_counts={k: categories[k] for k in CATEGORIES},
                                  line_full_unique_roots=len(line_full), photon_families=families.rows,
                                  positive_fraction=ratio(len(data['events']), c['initial_decays']),
                                  line_full_per_emitted_line=ratio(len(line_full), c['line_photons']))
    return result


def histogram_files(output, histograms):
    write_json(output/'histograms.json', histograms)
    with (output/'histograms.csv').open('x', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['model', 'population', 'bin', 'lower_keV', 'upper_keV', 'count'])
        for model, populations in histograms.items():
            for population, h in populations.items():
                w.writerow([model, population, 'exact_zero', 0, 0, h['exact_zero']])
                w.writerow([model, population, 'underflow', '-inf', h['edges_keV'][0], h['underflow']])
                for i, count in enumerate(h['counts']):
                    w.writerow([model, population, '[lo,hi) excluding exact zero', *h['edges_keV'][i:i+2], count])
                w.writerow([model, population, 'overflow', h['edges_keV'][-1], 'inf', h['overflow']])


def plot_svg(hist, title, max_energy=1400):
    counts = hist['counts'][:max_energy]; peak = max(counts, default=1)
    points = ' '.join(f'{60+700*(i+.5)/max_energy:.2f},{235-190*math.log10(1+c)/math.log10(1+max(1,peak)):.2f}'
                      for i, c in enumerate(counts))
    return (f'<svg viewBox="0 0 800 290" role="img" aria-label="{html.escape(title)}">'
            f'<title>{html.escape(title)}</title><text x="60" y="22">{html.escape(title)}</text>'
            '<path d="M60 40V235H760" fill="none" stroke="#555"/>'
            f'<polyline points="{points}" fill="none" stroke="#116a92" stroke-width="1.3"/>'
            '<text x="8" y="46">log1p</text><text x="8" y="64">count</text>'
            f'<text x="60" y="256">0</text><text x="714" y="256">{max_energy}</text>'
            '<text x="320" y="280">Ge deposition truth Edep (keV)</text></svg>')


def report(output, summary, histograms, representatives):
    page = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>Million-decay deposition truth</title><style>body{font:16px/1.55 system-ui;margin:auto;max-width:1100px;padding:20px;color:#183345;background:#f5f8fa}h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%;background:white}td,th{padding:9px;text-align:left;border-bottom:1px solid #ccd7df}svg{width:100%;background:white;margin:12px 0}small{color:#435766}.scroll{overflow:auto}code{overflow-wrap:anywhere}</style>',
            '<h1>Two million saved Cs137 decays</h1><p><strong>Deposition truth, not reconstructed energy.</strong> One million initial decays per detector. No SSD, readout or noise has run for this campaign.</p>',
            '<div class="scroll"><table><tr><th>Stage</th><th>Counted object</th><th>Meaning</th></tr>',
            '<tr><td>Initial decay</td><td>Every primary, including zeros</td><td>One global ID within each detector</td></tr>',
            '<tr><td>Emitted photon</td><td>RDM photon births; 660–663 keV subset</td><td>Photons are not primary decays or detected groups</td></tr>',
            '<tr><td>Positive Ge decay</td><td>At least one positive Ge deposit</td><td>Transport deposition only</td></tr>',
            '<tr><td>Isolated group</td><td>Fixed 100 μs windows from first positive row</td><td>Separate grouping census; no acquisition model</td></tr>',
            '<tr><td>Photon family candidate</td><td>Single linked source photon, ancestry and tolerance tests</td><td>Full/compact/observed Compton labels overlap</td></tr></table></div>']
    for m in MODELS:
        s = summary['models'][m]; old = summary['old10k']['models'][m]
        page += [f'<h2>{m}</h2><div class="scroll"><table><tr><th>Quantity</th><th>1M sample</th><th>Old 10k sample</th></tr>']
        for label, key in [('Initial decays', 'initial_decays'), ('Positive Ge decays', 'positive_ge_decays'),
                           ('Isolated 100 μs groups', 'isolated_groups'), ('Emitted RDM photons', 'emitted_RDM_photons'),
                           ('Emitted 660–663 keV photons', 'emitted_line_photons'), ('Line full-energy unique roots', 'line_full_unique_roots')]:
            page.append(f'<tr><td>{label}</td><td>{s[key]:,}</td><td>{old[key]:,}</td></tr>')
        page += [f'<tr><td>Positive fraction per initial decay</td><td>{100*s["positive_fraction"]["fraction"]:.4f}%</td><td>{100*old["positive_fraction"]["fraction"]:.4f}%</td></tr></table></div>',
                 f'<p>Inclusive 650–670 keV deposition band: {s["band650_670_initial_decays"]:,} initial decays / {s["band650_670_groups"]:,} groups. This is not an exact photopeak count. Exact-zero decays: {s["zero_ge_decays"]:,}.</p>',
                 plot_svg(histograms[m]['per_initial_decay'], m+' · all-decay spectrum; exact zeros listed separately'),
                 plot_svg(histograms[m]['per_isolated_group'], m+' · isolated-group spectrum'),
                 '<p><small>1 keV bins, [lower, upper), exact zero separate. Y uses log10(1 + count). Exact counts and explicit tails are in histograms.csv/json; positive-only histogram also supplied. No fit or smearing.</small></p>',
                 '<div class="scroll"><table><tr><th>Actual source family keV (anchor; tolerance grouped)</th><th>Groups</th><th>Full</th><th>Compact/full</th><th>1 Compton/full</th><th>2 Compton/full</th><th>Partial</th><th>Unknown</th></tr>']
        for f in sorted(s['photon_families'], key=lambda x: x['anchor_keV'] or -1):
            label = 'Unknown' if f['anchor_keV'] is None else repr(f['anchor_keV'])
            page.append('<tr><td>'+label+'</td><td>'+str(f['groups'])+'</td>'+''.join(f'<td>{f["categories"][k]}</td>' for k in ('full','compact','compton1','compton2','partial','unknown'))+'</tr>')
        page += ['</table></div><p>Illustrative representatives (first by preferred 661.657 keV family, then closest source energy and global ID):</p><ul>']
        for category in ('compact','full','compton1','compton2','partial'):
            choices = representatives[m]['categories'][category]
            text = '; '.join(f'global {r["global_decay_id"]} / chunk {r["chunk_index"]} / local {r["local_event_id"]} / group {r["group_id"]}, photon {r["source_photon_energy_keV"]!r} keV' for r in choices) or 'No observed candidate'
            page.append(f'<li>{html.escape(hv.LABELS[category])}: {html.escape(text)}</li>')
        page.append('</ul>')
    page += ['<h2>Interpretation and provenance</h2><p>The old 10k comparison is descriptive simulation sampling, not an experimental control. SAP22 is a different geometry. No fitted width, resolution, efficiency or Li-response claim is made.</p><ul>']
    page += ['<li>'+html.escape(x)+'</li>' for x in LIMITATIONS]
    page += ['</ul><p>Local evidence: summary.json, provenance.json, histograms.csv/json, positive-groups.csv.gz, all-event-scalars.h5 and representative-events.json. Full raw archives stay local. This standalone page has no external scripts, fonts or data requests.</p></html>']
    (output/'report.html').write_text(''.join(page), encoding='utf-8')


def analyze(directory, output, frozen):
    started = time.perf_counter(); check_sources(frozen)
    output = output_path(output)
    c, complete, rows, templates = campaign_inputs(directory)
    require(sha(directory/'config.json') == frozen['config_sha256'] and
            sha(directory/'COMPLETE.json') == frozen['complete_sha256'], 'Campaign changed after freeze')
    old = compare_old()
    output.mkdir(parents=True)
    provenance = dict(config_sha256=sha(directory/'config.json'), complete_sha256=sha(directory/'COMPLETE.json'),
                      config=c, complete=complete, simulation_runtime=read(directory/'runtime.json'),
                      source_sha256=frozen['source_sha256'], chunks=[], raw_table_schemas={},
                      classifier_method=hv.METHOD, input_root=str(directory.relative_to(ROOT)),
                      archive_audit='Independent supervisor; this program does not claim archive content verification')
    summary = dict(status='analysis_in_progress', models={}, old10k=old, limitations=LIMITATIONS,
                   runtime=dict(python=sys.version, numpy=np.__version__, h5py=h5py.__version__,
                                hdf5=h5py.version.hdf5_version, platform=platform.platform()),
                   histogram_width_keV=1, band650_670='inclusive [650,670] keV, not exact photopeak',
                   family_rule='First encountered source energy anchor; existing numerical tolerance; exact min/max retained',
                   command=[sys.executable, *sys.argv], random_seed='none; deterministic saved-data analysis')
    histograms, representatives = {}, {}
    with h5py.File(output/'all-event-scalars.h5', 'x') as scalars, gzip.open(output/'positive-groups.csv.gz', 'xt', encoding='utf-8', newline='') as csvfile:
        scalars.attrs['kind'] = 'million_deposition_truth_v1'
        scalars.attrs['coordinate_policy'] = 'Raw scoring coordinates global m; no reinterpretation'
        fields = ['model','chunk_index','global_offset','local_event_id','global_decay_id','seed','group_id',
                  'ge_energy_keV','source_photon_energy_keV','categories','classifier_status','evidence_json']
        writer = csv.DictWriter(csvfile, fieldnames=fields); writer.writeheader()
        for model in MODELS:
            total = Counter(); cats = Counter(); families = Families(); full_roots = set(); line_full_roots = set()
            best = {k: [] for k in CATEGORIES}; saved = {}; raw_totals = Counter(); material_parts = {}
            hist = {k: Histogram() for k in ('per_initial_decay','positive_initial_decay','per_isolated_group')}
            group = scalars.create_group(model)
            next_global = 0; energy_parts = []; group_energy_parts = []; failures = []
            for row in (r for r in rows if r['model'] == model):
                require(row['start'] == next_global, 'Cross-chunk ID collision/gap')
                path, done, evidence = checkpoint(directory, row, provenance['config_sha256'])
                chunk = load_chunk(path, row, templates[model], evidence['raw_sha256'])
                require(chunk['counts'] == done['counts'], 'Independent counts differ from DONE')
                provenance['chunks'].append(evidence)
                if model not in provenance['raw_table_schemas']:
                    provenance['raw_table_schemas'][model] = chunk['schemas']
                require(provenance['raw_table_schemas'][model] == chunk['schemas'], 'Schema changed between chunks')
                ledger = chunk['ledger']; ge = ledger['ge_energy_keV']; n = row['count']
                for key, a in ledger.items():
                    if key not in group:
                        ds = group.create_dataset(key, shape=(c['events_per_model'], *a.shape[1:]), dtype=a.dtype,
                                                  chunks=True, compression='gzip', shuffle=True, fletcher32=True)
                        if 'energy_keV' in key: ds.attrs['units'] = 'keV'
                        if key == 'material_energy_keV': ds.attrs['materials_json'] = json.dumps(chunk['materials'])
                    group[key][row['start']:row['start']+n] = a
                if 'chunk_index' not in group:
                    for k in ('chunk_index','seed'):
                        group.create_dataset(k, shape=(c['events_per_model'],), dtype='int64', chunks=True,
                                             compression='gzip', shuffle=True, fletcher32=True)
                group['chunk_index'][row['start']:row['start']+n] = row['index']
                group['seed'][row['start']:row['start']+n] = row['seed']
                next_global += n; total.update(chunk['counts']); raw_totals.update(chunk['retained_raw_rows'])
                hist['per_initial_decay'].add(ge); hist['positive_initial_decay'].add(ge[ge > 0])
                total['zero'] += int((ge == 0).sum()); total['band_decays'] += int(((ge >= 650)&(ge <= 670)).sum())
                energy_parts.append(math.fsum(ge))
                for j, material in enumerate(chunk['materials']):
                    material_parts.setdefault(material, []).append(math.fsum(ledger['material_energy_keV'][:,j]))
                for local_id, event in chunk['events'].items():
                    identity = dict(model=model, chunk_index=row['index'], global_offset=row['start'],
                                    local_event_id=local_id, global_decay_id=row['start']+local_id, seed=row['seed'])
                    classified = classify_retained(event, chunk['processes'])
                    if 'classifier_error' in classified:
                        failures.append(dict(**identity, error=classified['classifier_error']))
                    total['classified_positive'] += 1
                    for g in classified['groups']:
                        total['groups'] += 1; cats.update(g['categories']); families.add(g)
                        hist['per_isolated_group'].add([g['ge_energy_keV']]); group_energy_parts.append(g['ge_energy_keV'])
                        total['band_groups'] += int(650 <= g['ge_energy_keV'] <= 670)
                        if 'full' in g['categories']:
                            key = (identity['global_decay_id'], g['source_photon_track_ids'][0]); full_roots.add(key)
                            if 660 <= g['source_photon_energy_keV'] <= 663: line_full_roots.add(key)
                        writer.writerow(dict(**identity, group_id=g['group_id'], ge_energy_keV=g['ge_energy_keV'],
                                             source_photon_energy_keV=g['source_photon_energy_keV'],
                                             categories='|'.join(g['categories']),
                                             classifier_status='failed_unknown' if 'classifier_error' in classified else 'returned',
                                             evidence_json=json.dumps(dict(group=g, event_graph_errors=classified.get('graph_errors', []),
                                                                          classifier_error=classified.get('classifier_error')), separators=(',', ':'), allow_nan=False)))
                        ref = dict(**identity, group_id=g['group_id'], source_photon_energy_keV=g['source_photon_energy_keV'])
                        for category in g['categories']:
                            candidates = best[category]
                            candidates.append((representative_rank(g, identity), ref))
                            candidates.sort(key=lambda x: x[0]); del candidates[2:]
                            if any(r['global_decay_id'] == identity['global_decay_id'] for _, r in candidates):
                                saved[identity['global_decay_id']] = dict(identity=identity, event=event,
                                    classification=classified, processes=chunk['processes'], provenance=evidence)
                    active = {r['global_decay_id'] for choices in best.values() for _, r in choices}
                    saved = {k: v for k, v in saved.items() if k in active}
                if (row['index']+1) % 10 == 0:
                    print(f"{model}: {next_global} decays, {total['ge_positive']} positive, {total['groups']} groups", flush=True)
            require(next_global == c['events_per_model'], 'Final range')
            require({k: total[k] for k in ('decays','ge_positive','decay_photons','line_photons')} ==
                    {k: complete['models'][model][k] for k in ('decays','ge_positive','decay_photons','line_photons')}, 'COMPLETE count mismatch')
            require(total['zero']+total['ge_positive'] == total['decays'] and
                    total['classified_positive'] == total['ge_positive'], 'Independent zero/positive census')
            require(sum(cats[k] for k in ('full','partial','unknown')) == total['groups'], 'Exclusive energy classes')
            require(math.isclose(math.fsum(energy_parts), math.fsum(group_energy_parts), rel_tol=1e-14, abs_tol=1e-8), 'Group energy partition')
            histograms[model] = {k: v.result() for k, v in hist.items()}
            require(histograms[model]['per_isolated_group']['total'] == total['groups'], 'Group histogram census')
            summary['models'][model] = dict(initial_decays=total['decays'], zero_ge_decays=total['zero'],
                positive_ge_decays=total['ge_positive'], isolated_groups=total['groups'],
                emitted_RDM_photons=total['decay_photons'], emitted_line_photons=total['line_photons'],
                category_group_counts={k: cats[k] for k in CATEGORIES}, photon_families=families.rows,
                full_unique_roots=len(full_roots), line_full_unique_roots=len(line_full_roots),
                positive_fraction=ratio(total['ge_positive'], total['decays']),
                groups_per_initial_decay=ratio(total['groups'], total['decays']),
                full_per_group=ratio(cats['full'], total['groups']),
                full_per_emitted_RDM_photon=ratio(len(full_roots), total['decay_photons']),
                line_full_per_emitted_line=ratio(len(line_full_roots), total['line_photons']),
                band650_670_initial_decays=total['band_decays'], band650_670_groups=total['band_groups'],
                recorded_ge_energy_keV=math.fsum(energy_parts),
                recorded_material_energy_keV={k: math.fsum(v) for k, v in material_parts.items()},
                retained_raw_row_counts=dict(raw_totals), classifier_failures=failures,
                invariants=dict(zero_plus_positive_equals_initial=True, all_positive_events_classified=True,
                                local_global_ranges_unique=True, done_complete_counts_match=True,
                                scalar_detail_positive_energy_match=True, histogram_censuses_match=True,
                                exclusive_full_partial_unknown_equals_groups=True, group_energy_partition=True))
            representatives[model] = dict(categories={k: [r for _, r in v] for k, v in best.items()},
                                          events=[saved[k] for k in sorted(saved)])
    histogram_files(output, histograms)
    write_json(output/'representative-events.json', dict(rule='Up to two/category, prefer 661.657 keV within existing tolerance, then nearest actual energy, global ID and group ID; illustrative only',
                                                        coordinate_units='global m', models=representatives))
    check_sources(frozen)
    verified(directory/'config.json', provenance['config_sha256']); verified(directory/'COMPLETE.json', provenance['complete_sha256'])
    summary['status'] = 'completed_saved_data_analysis'
    summary['completed_utc'] = datetime.now(timezone.utc).isoformat()
    summary['analysis_wall_seconds'] = time.perf_counter()-started
    summary['source_sha256'] = frozen['source_sha256']
    write_json(output/'provenance.json', provenance)
    report(output, summary, histograms, representatives)
    summary['files'] = {p.name: dict(sha256=sha(p), bytes=p.stat().st_size) for p in output.iterdir() if p.is_file()}
    write_json(output/'summary.json', summary)
    verify_output(output)
    write_json(output/'COMPLETE.json', dict(status='verified_saved_data_analysis', summary_sha256=sha(output/'summary.json'),
                                           wall_seconds_including_output_verification=time.perf_counter()-started,
                                           counts={m: {k: summary['models'][m][k] for k in ('initial_decays','positive_ge_decays','isolated_groups')} for m in MODELS}))
    return summary


def verify_output(output):
    """Read generated data only; never rerun compact analysis or classifier."""
    summary = read(output/'summary.json'); hist = read(output/'histograms.json')
    for name, entry in summary['files'].items():
        verified(output/name, entry['sha256']); require((output/name).stat().st_size == entry['bytes'], 'Output size')
    seen = {m: set() for m in MODELS}; group_ids = {m: set() for m in MODELS}; counts = {m: Counter() for m in MODELS}
    group_hist = {m: Histogram() for m in MODELS}
    with gzip.open(output/'positive-groups.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            m = r['model']; gid = int(r['global_decay_id']); local = int(r['local_event_id'])
            require(gid == int(r['global_offset'])+local, 'Export identity')
            key = (gid, int(r['group_id'])); require(key not in group_ids[m], 'Duplicate exported group')
            group_ids[m].add(key); seen[m].add(gid); counts[m].update(r['categories'].split('|'))
            group_hist[m].add([float(r['ge_energy_keV'])])
    with h5py.File(output/'all-event-scalars.h5', 'r') as f:
        for m in MODELS:
            s = summary['models'][m]; n = s['initial_decays']; positives = set(); zero = 0
            all_hist, pos_hist = Histogram(), Histogram()
            for start in range(0, n, 10000):
                ids = f[m+'/global_decay_id'][start:start+10000]; ge = f[m+'/ge_energy_keV'][start:start+10000]
                require(np.array_equal(ids, np.arange(start, start+len(ids))), 'Export scalar census')
                positives.update(map(int, ids[ge > 0])); zero += int((ge == 0).sum())
                all_hist.add(ge); pos_hist.add(ge[ge > 0])
            require(positives == seen[m] and len(positives) == s['positive_ge_decays'] and zero == s['zero_ge_decays'], 'Export positive census')
            require(len(group_ids[m]) == s['isolated_groups'] and {k: counts[m][k] for k in CATEGORIES} == s['category_group_counts'], 'Export category census')
            require(all_hist.result() == hist[m]['per_initial_decay'] and
                    pos_hist.result() == hist[m]['positive_initial_decay'] and
                    group_hist[m].result() == hist[m]['per_isolated_group'], 'Export histogram bin mismatch')
            for population, expected in [('per_initial_decay', n), ('positive_initial_decay', len(positives)), ('per_isolated_group', len(group_ids[m]))]:
                h = hist[m][population]
                require(sum(h['counts'])+h['exact_zero']+h['underflow']+h['overflow'] == h['total'] == expected, 'Export histogram census')
    return {m: dict(positive_events=len(seen[m]), groups=len(group_ids[m])) for m in MODELS}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['freeze','run','verify'])
    p.add_argument('--campaign', type=Path, default=CAMPAIGN)
    p.add_argument('--output', type=Path, default=BASE/'analysis-results')
    p.add_argument('--frozen', type=Path, default=BASE/'analysis-freeze.json')
    a = p.parse_args()
    if a.action == 'freeze':
        target = output_path(a.frozen); target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, dict(source_sha256=source_hashes(), config_sha256=sha(a.campaign/'config.json'),
                                complete_sha256=sha(a.campaign/'COMPLETE.json'), utc=datetime.now(timezone.utc).isoformat()))
        print('Source hashes frozen:', target.relative_to(ROOT))
    elif a.action == 'run':
        result = analyze(a.campaign.resolve(), a.output, read(a.frozen))
        print(json.dumps({m: {k: s[k] for k in ('initial_decays','positive_ge_decays','isolated_groups')} for m,s in result['models'].items()}))
    else:
        print(json.dumps(verify_output(a.output)))


if __name__ == '__main__':
    main()
