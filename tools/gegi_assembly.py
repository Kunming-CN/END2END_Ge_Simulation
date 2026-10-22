"""Publish a checked GeGI assembly from saved GDML; never run radiation or SSD.

Freeze this exporter, build the restricted native inspector, then inspect/build.
Ordinary site publication only validates and copies the completed saved bundle.
refresh_presentation() updates an authenticated saved display without native work.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/gegi-website'
SAVED = ROOT / '.local/runs/gegi-source-left-v1/transport'
BUNDLE = WORK / 'assembly-signal-v3'
DISPLAY_BUNDLE = WORK / 'assembly-display-audit-20261022'
FREEZE = WORK / 'assembly-signal-v3-source-freeze.json'
NATIVE_FREEZE = WORK / 'assembly-native-source-freeze.json'
NATIVE = WORK / 'build/gegi-scene-native.json'
RECEIPT = WORK / 'assembly-native-receipt.json'
EXE = WORK / 'build/gegi_scene'
KIND = 'gegi_saved_assembly_v1'
# Exactly the current public six-file predecessor may be staged by build_site
# before this saved-data display is copied. No generic stale-source exemption.
PREVIOUS_BUNDLES = frozenset({'6a725558513bc6761450cd6fbee4e14ca11b91a66eb160f80c422f7520923081'})
# Exact eight-file saved publication before the 2026-10-22 presentation audit.
# Its file/event/native-source checks remain mandatory under current sources.
PRESENTATION_PREDECESSORS = frozenset({'bae59d7ee0916648e41792c8732f81e682b87939efc706ce5c0116667a53dd1d'})
EVENTS = ROOT / '.local/gegi-10m/reconstruction-v3/assembly-events.json'
EVENTS_SHA256 = '4ceebc1c3d8c63479db1ced63edc230387de8a983934ef62d4a73d57499f8210'
ASSET = 'scenarios/assets/gegi_cryostat_v1.json'
SOURCE_FILES = ('tools/gegi_assembly.py', 'tools/gegi_assembly.html', 'tools/gegi_assembly.js',
                'tools/gegi_signal_journey.js',
                'tools/gegi_scene.cc', 'tools/gegi_mesh.hh', 'tools/gegi_scene/CMakeLists.txt', 'tools/geant4_scene/scene.cc',
                'tools/site_routes.py', 'tools/site_discovery.py')
NATIVE_SOURCE_FILES = ('tools/gegi_scene.cc', 'tools/gegi_mesh.hh', 'tools/gegi_scene/CMakeLists.txt',
                       'tools/geant4_scene/scene.cc')
PRESERVED_DISPLAY_FILES = ('scene.json', 'event-data.json', 'geometry.gdml', 'preview.svg',
                          'cross-section.svg', 'gegi_signal_journey.js')
INPUT_FILES = ('geometry.gdml', 'geometry-report.json', 'geometry.log', 'prepared.json', 'run.json')
LEGACY_PUBLIC_FILES = ('index.html', 'viewer.js', 'scene.json', 'preview.svg', 'cross-section.svg', 'geometry.gdml')
PUBLIC_FILES = (*LEGACY_PUBLIC_FILES, 'event-data.json', 'gegi_signal_journey.js')
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
COLORS = {'outer': '#79c9ee', 'inner': '#efc972', 'germanium': '#ca9bff', 'cryostat_vacuum': '#6d91ad'}
LABELS = {'cryostat_vacuum': 'Vacuum envelope', 'germanium': 'GeGI crystal',
          'outer_front': 'Outer front cover', 'outer_side': 'Outer side wall', 'outer_rear': 'Outer rear wall',
          'inner_front': 'Inner front shield', 'inner_side': 'Inner side shield', 'inner_rear': 'Inner rear shield'}
PRIVATE = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]|/mnt/[a-z]/|/home/[^/\s]+/|file:///|\.local[\\/]', re.I)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))+'\n').encode()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def info(path):
    return {'sha256': sha(path), 'bytes': Path(path).stat().st_size}


def public(body):
    text = body.decode('utf-8')
    require(PRIVATE.search(text) is None, 'Private path in public assembly')
    require(not re.search(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}', text),
            'Credential-like text in public assembly')
    return body


def checked(path, base, new=False):
    path, base = Path(path).absolute(), Path(base).resolve()
    require('..' not in path.parts and path == path.resolve() and path != base and path.is_relative_to(base),
            'Escaped or linked output path')
    if new:
        require(not path.exists(), 'Output already exists: '+path.name)
    return path


def write(path, body, public_output=False):
    if public_output:
        public(body)
    with Path(path).open('xb') as stream:
        stream.write(body)


def source_hashes():
    original = (ROOT/'tools/geant4_scene/scene.cc').read_bytes()
    adapted = original.replace(b'.local/peak-native-delivery/cs10000-v2', b'.local/runs/gegi-source-left-v1/transport').replace(
        b'.local/geometry-events-publication/build', b'.local/gegi-website/build')
    adapted = adapted.replace(b'int main(', b'#include "gegi_mesh.hh"\nint main(').replace(
        b'auto* poly=solid->CreatePolyhedron();', b'auto* poly=gegi_polyhedron(solid);')
    require((ROOT/'tools/gegi_scene.cc').read_bytes() == adapted, 'Native mesh core differs beyond restricted paths/GeGI mesh helper')
    return {ref: sha(ROOT/ref) for ref in SOURCE_FILES}


def inputs():
    prepared, run, report = (read(SAVED/name) for name in ('prepared.json', 'run.json', 'geometry-report.json'))
    require(prepared['status'] == 'complete' and run['status'] == 'complete' and run['returncode'] == 0,
            'Saved transport did not complete')
    require(run['prepared_sha256'] == sha(SAVED/'prepared.json'), 'Saved preparation changed')
    for name in ('geometry.gdml', 'geometry-report.json', 'geometry.log'):
        require(prepared['files_sha256'][name] == sha(SAVED/name), 'Saved geometry input changed: '+name)
    asset = read(ROOT/ASSET)
    require(asset == prepared['cryostat_contract'], 'Saved/current GeGI cryostat differ')
    for ref in (ASSET, 'models/GeGI_3D.yaml', 'transport/gegi_geometry.py', 'transport/catalog_geometry.py',
                'transport/pixi.toml', 'transport/pixi.lock'):
        require(sha(ROOT/ref) == prepared['source_sha256'][ref], 'Saved geometry authority changed: '+ref)
    require(prepared['model_id'] == 'GeGI_3D' and asset['compatible_detectors'] == ['GeGI_3D'], 'Wrong compatible model')
    require(prepared['coordinate_transform']['rotation_local_to_global'] == IDENTITY
            and prepared['coordinate_transform']['translation_global_mm'] == [0, 0, 0], 'GeGI coordinates changed')
    require(report['kind'] == 'gegi_geometry_report_v1' and report['overlaps_passed'] is True
            and report['overlap_samples_per_volume'] == 10000 and report['overlap_tolerance_mm'] == 0,
            'Saved overlap evidence is incomplete')
    log = (SAVED/'geometry.log').read_text(encoding='utf-8')
    for name in LABELS:
        require(re.search(r'Checking overlaps for volume '+name+r':0 .*?OK!', log), 'Missing saved volume overlap: '+name)
    require(len(re.findall('Checking overlaps for volume ', log)) == 8, 'Saved assembly volume census changed')
    return prepared, report, asset, {name: info(SAVED/name) for name in INPUT_FILES}


def freeze():
    inputs()
    saved_events()
    WORK.mkdir(parents=True, exist_ok=True)
    value = {'kind': KIND, 'source_sha256': source_hashes(), 'saved_events_sha256': EVENTS_SHA256}
    if FREEZE.exists():
        require(read(FREEZE) == value, 'Existing source freeze differs; preserve it and diagnose changed source')
    else:
        write(checked(FREEZE, WORK, new=True), encoded(value))
    return value


def frozen():
    value = read(FREEZE)
    require(value == {'kind': KIND, 'source_sha256': source_hashes(), 'saved_events_sha256': EVENTS_SHA256},
            'Exporter changed after source freeze')
    saved_events()
    return value


def validate_events(data):
    """Validate exact scored-chord semantics; never invent missing trajectory legs."""
    require(data.get('kind') == 'gegi_saved_path_display_v1' and isinstance(data.get('records'), list),
            'Invalid saved GeGI event display')
    seen = set()
    for record in data['records']:
        identity, radiation = record['original_identity'], record['radiation']
        required = ('chunk_index', 'raw_primary_id', 'pulse_group_id', 'campaign_initial_id')
        require(all(type(identity.get(k)) is int and identity[k] >= 0 for k in required),
                'Missing original saved-event identity')
        key = tuple(identity[k] for k in required)
        require(key not in seen, 'Duplicate original saved event'); seen.add(key)
        require(radiation['event_id'] == identity['raw_primary_id']
                and radiation.get('scope') == 'positive_energy_Ge_scored_step_chords_only',
                'Saved radiation identity or scored-chord scope differs')
        require(isinstance(radiation.get('segments'), list) and isinstance(radiation.get('births'), list),
                'Saved steps and creation vertices must be explicit')
        rows = set()
        for row in radiation['segments']:
            for name in ('pre_mm', 'post_mm', 'position_mm'):
                require(isinstance(row.get(name), list) and len(row[name]) == 3
                        and all(type(x) in (int, float) and math.isfinite(x) for x in row[name]),
                        'Invalid saved mm coordinate')
            require(all(type(row.get(k)) is int for k in ('track_id', 'parent_track_id', 'particle_pdg', 'raw_row_index'))
                    and row['raw_row_index'] >= 0 and row['raw_row_index'] not in rows,
                    'Invalid or duplicated original step row')
            rows.add(row['raw_row_index'])
            require(type(row.get('energy_keV')) in (int, float) and math.isfinite(row['energy_keV'])
                    and row['energy_keV'] > 0 and type(row.get('time_ns')) in (int, float)
                    and math.isfinite(row['time_ns']), 'Invalid saved deposited energy or time')
        # This exact display payload contains no available signal counterpart.
        # Future signal attachment requires a new bound derivative, with an exact
        # same-original-identity contract; never borrow a representative waveform.
        require(record.get('signal_event') is None, 'This saved display has no bound signal counterpart')
        require(radiation['births'] == [], 'This saved derivative has no track-birth records')
        require(all(re.fullmatch(r'[a-f0-9]{64}', record['provenance'].get(k, ''))
                    for k in ('metadata_sha256', 'store_sha256')), 'Saved event provenance missing')
    return data


def saved_events():
    body = EVENTS.read_bytes()
    require(hashlib.sha256(body).hexdigest() == EVENTS_SHA256, 'Saved event display input changed')
    return validate_events(json.loads(body)), body


def inline_json(value):
    """Safe application/json text: no HTML closing tag can terminate the block."""
    return encoded(value).decode().replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def close(a, b, tolerance=1e-8):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tolerance) for x, y in zip(a, b))
    return type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and abs(a-b) <= tolerance


def section_y0(volume):
    """Intersect the actual native triangle mesh with the y=0 plane, in mm."""
    segments = {}
    for face in volume['triangles']:
        points = [volume['vertices_global_mm'][i] for i in face]
        intersections = []
        for a, b in zip(points, points[1:]+points[:1]):
            if abs(a[1]) < 1e-10:
                intersections.append([a[0], 0., a[2]])
            if a[1]*b[1] < -1e-20:
                t = -a[1]/(b[1]-a[1])
                intersections.append([a[0]+t*(b[0]-a[0]), 0., a[2]+t*(b[2]-a[2])])
        unique = {tuple(round(x, 9) for x in p): p for p in intersections}
        if len(unique) < 2:
            continue
        require(len(unique) == 2, 'Unexpected coplanar native section triangle')
        pair = list(unique.values())
        if math.dist(*pair) > 1e-8:
            segments[tuple(sorted(unique))] = pair
    require(segments, 'Empty native section')
    return list(segments.values())


def validate_scene(native, report, prepared):
    require(native['generator'] == 'G4GDMLParser/G4Polyhedron' and native['units'] == 'mm'
            and native['geant4_version_number'] == 1132 and native['rotation_steps'] == 64,
            'Unexpected mesh provenance or units')
    volumes = native['volumes']
    require(len(volumes) == 9 and len({v['name'] for v in volumes}) == 9, 'Expected air world plus eight assembly volumes')
    world = volumes[0]
    require(world['parent'] == -1 and world['material'] == 'G4_AIR' and world['logical_volume'] == 'world', 'Wrong air world')
    require({v['name'] for v in volumes[1:]} == set(LABELS), 'GeGI assembly census differs')
    parts = {p['name']: p for p in report['geometry']['parts']}
    require(set(parts) == set(LABELS)-{'cryostat_vacuum', 'germanium'}, 'GeGI layer census differs')
    vacuum_index = next(i for i, v in enumerate(volumes) if v['name'] == 'cryostat_vacuum')
    for index, volume in enumerate(volumes):
        vertices = volume['vertices_global_mm']
        require(vertices and all(len(p) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in p)
                                 for p in vertices), 'Invalid native vertex')
        for key, count in (('triangles', 3), ('wireframe', 2)):
            require(volume[key] and all(len(face) == count and all(type(i) is int and 0 <= i < len(vertices)
                                      for i in face) for face in volume[key]), 'Invalid native mesh indices')
        require(close(volume['rotation_local_to_global'], IDENTITY), 'Noncanonical GeGI rotation')
        if not index:
            continue
        require(volume['parent'] == (0 if index == vacuum_index else vacuum_index)
                and volume['copy_number'] == 0, 'GeGI hierarchy/copy number changed')
        name = volume['name']
        if name != 'cryostat_vacuum':
            require(volume['material'] == prepared['material_tables']['stp/'+name], 'Native material differs from saved scoring material')
        bounds = [[min(p[a] for p in vertices), max(p[a] for p in vertices)] for a in range(3)]
        if name == 'germanium':
            require(volume['material'] == 'G4_Ge' and volume['solid_type'] == 'G4IntersectionSolid', 'Wrong crystal CSG/material')
            require(close(volume['translation_global_mm'], [0, 0, 0]) and
                    close(bounds, [[-45, 45], [-45, 45], [-5.5, 5.5]]), 'Crystal origin/bounds differ')
            require(all(abs(p[0])+abs(p[1]) <= 45*math.sqrt(2)+1e-7 for p in vertices), 'Octagonal crystal shape differs')
        else:
            if name == 'cryostat_vacuum':
                ri, ro = 0, report['geometry']['vacuum_radius_mm']; z0, z1 = report['geometry']['vacuum_z_bounds_mm']
                require(volume['material'] == 'G4_Galactic', 'Wrong envelope material')
            else:
                part = parts[name]; ri, ro = part['rmin_mm'], part['rmax_mm']; z0, z1 = part['zmin_mm'], part['zmax_mm']
                require(volume['material'] == 'G4_Al', 'Wrong wall material')
            require(volume['solid_type'] == 'G4Tubs' and close(bounds, [[-ro, ro], [-ro, ro], [z0, z1]])
                    and close(volume['translation_global_mm'], [0, 0, (z0+z1)/2]), 'Native cylindrical dimensions differ')
            require(all(close(math.hypot(*p[:2]), ri) or close(math.hypot(*p[:2]), ro) for p in vertices),
                    'Native cylinder radial bounds differ')
        section_y0(volume)
    require(close(parts['outer_front']['zmax_mm']-5.5, 8.1) and
            close(parts['outer_front']['zmax_mm']-parts['outer_front']['zmin_mm'], 1.6) and
            close(parts['inner_front']['zmax_mm']-parts['inner_front']['zmin_mm'], .8), 'Dimensioned front stack changed')


def inspect_native():
    sources = frozen(); prepared, report, _, pins = inputs()
    checked(NATIVE, WORK, new=True); checked(RECEIPT, WORK, new=True)
    require(EXE.is_file(), 'Build the restricted GeGI native inspector first')
    executable = info(EXE)
    log = checked(WORK/'assembly-native.log', WORK, new=True)
    if os.name == 'nt':
        def linux(path):
            require(str(path).lower().startswith('c:\\'), 'WSL input must be on the project drive')
            return '/mnt/c/'+path.as_posix()[3:]
        command = ['wsl.exe', '-d', 'Ubuntu-24.04', '--cd', linux(ROOT), '--exec', 'bash', '-c',
                   'exec "$HOME/.pixi/bin/pixi" run --locked --no-install --manifest-path transport/pixi.toml "$@"',
                   'gegi-scene', linux(EXE), linux(SAVED/'geometry.gdml'), linux(NATIVE)]
    else:
        command = [str(EXE), str(SAVED/'geometry.gdml'), str(NATIVE)]
    with log.open('x', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    require(result.returncode == 0, 'Native geometry inspection failed; preserve its log/output')
    validate_scene(read(NATIVE), report, prepared)
    require(frozen() == sources and inputs()[3] == pins and info(EXE) == executable, 'Inputs changed during native inspection')
    receipt = {'kind': KIND, 'status': 'complete', 'radiation_calls': 0, 'field_solves': 0,
               'source_freeze_sha256': sha(FREEZE), 'input_files': pins, 'native_executable': executable,
               'native_scene': info(NATIVE), 'log': info(log)}
    write(RECEIPT, encoded(receipt))
    return receipt


def saved_native():
    # Reading an immutable saved native scene does not regenerate its display.
    # A new display build still requires its own exact current freeze below.
    sources = {'kind': KIND, 'source_sha256': source_hashes()}
    prepared, report, asset, pins = inputs(); receipt = read(RECEIPT)
    # Rendering/portable-publish changes can reuse an unchanged native export.
    # Retain its ORIGINAL full freeze and receipt; check every native build input.
    native_freeze = NATIVE_FREEZE if NATIVE_FREEZE.exists() else FREEZE
    baseline = read(native_freeze)
    native_sources = ('tools/gegi_scene.cc', 'tools/gegi_mesh.hh', 'tools/gegi_scene/CMakeLists.txt',
                      'tools/geant4_scene/scene.cc')
    require(baseline['kind'] == KIND and all(baseline['source_sha256'][ref] == sources['source_sha256'][ref]
            for ref in native_sources), 'Native exporter source changed; saved mesh cannot be rebound')
    require(receipt['kind'] == KIND and receipt['status'] == 'complete' and receipt['radiation_calls'] == 0
            and receipt['field_solves'] == 0 and receipt['source_freeze_sha256'] == sha(native_freeze)
            and receipt['input_files'] == pins and receipt['native_scene'] == info(NATIVE)
            and receipt['native_executable'] == info(EXE), 'Native scene receipt differs')
    native = read(NATIVE); validate_scene(native, report, prepared)
    return sources, native, prepared, report, asset, pins


def public_scene(native, prepared, report, asset, pins):
    parts = {p['name']: p for p in report['geometry']['parts']}
    volumes = []
    for original in native['volumes'][1:]:
        volume = dict(original); name = volume['name']
        volume['parent'] -= 1  # Public hierarchy excludes the air world only.
        volume['label'] = LABELS[name]
        volume['color'] = COLORS.get(name, COLORS[name.split('_')[0]]) if name not in COLORS else COLORS[name]
        volume['basis'] = parts[name]['basis'] if name in parts else (
            'canonical octagonal crystal, unchanged' if name == 'germanium' else 'nominal outer enclosure')
        volume['section_y0_mm'] = section_y0(volume)
        volumes.append(volume)
    return {'kind': KIND, 'model_id': prepared['model_id'], 'cryostat_id': asset['id'],
            'units': 'mm', 'coordinate_convention': asset['coordinate_convention'],
            'generator': native['generator'], 'geant4_version_number': 1132, 'rotation_steps': 64,
            'volumes': volumes, 'layers': report['geometry']['parts'],
            'geometry_gdml_sha256': pins['geometry.gdml']['sha256'],
            'model_sha256': prepared['model_sha256'], 'asset_sha256': sha(ROOT/ASSET),
            'scope': asset['scope'], 'omitted': asset['omitted'],
            'material_approximation': asset['radiation_material']['approximation']}


def svg_header(title, width=1000, height=720):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
            f'<title>{html.escape(title)}</title><rect width="100%" height="100%" fill="#101925"/>',
            '<g font-family="system-ui,sans-serif" fill="#edf4fb">']


def svg_line(a, b, color, width=1, opacity=1):
    return f'<path d="M {a[0]:.5f},{a[1]:.5f} L {b[0]:.5f},{b[1]:.5f}" fill="none" stroke="{color}" stroke-width="{width}" opacity="{opacity}"/>'


def clip_half_line(a, b):
    """Clip y > 0 even when one native vertex lies exactly on the cut plane."""
    if a[1] > 0 and b[1] > 0:
        return None
    if a[1] <= 0 and b[1] <= 0:
        return a, b
    t = -a[1] / (b[1] - a[1])
    p = [x + t * (y - x) for x, y in zip(a, b)]
    return (a, p) if a[1] <= 0 else (p, b)


def preview_svg(scene):
    out = svg_header('GeGI native mesh half cutaway: y less than or equal to zero')
    out.append('<text x="35" y="43" font-size="25">GeGI cryostat · native mesh cutaway</text>')
    yaw, pitch = .55, -.35
    def project(p):
        x, y, z = p[0], p[1], p[2]+26.4
        a, b = math.cos(yaw)*x+math.sin(yaw)*z, -math.sin(yaw)*x+math.cos(yaw)*z
        c = math.cos(pitch)*y-math.sin(pitch)*b
        return [490+4.4*a, 310-4.4*c]
    for volume in scene['volumes']:
        if volume['name'] == 'cryostat_vacuum':
            continue
        for ia, ib in volume['wireframe']:
            a, b = volume['vertices_global_mm'][ia], volume['vertices_global_mm'][ib]
            segment = clip_half_line(a, b)
            if segment is None:
                continue
            a, b = segment
            out.append(svg_line(project(a), project(b), volume['color'], .75, .45))
        for a, b in volume['section_y0_mm']:
            out.append(svg_line(project(a), project(b), volume['color'], 2.2))
    for p, color, label in (([22, 0, 0], '#ff9090', '+x'), ([0, 22, 0], '#83e7a6', '+y'), ([0, 0, 22], '#9dbfff', '+z front')):
        q = project(p); out.append(svg_line(project([0, 0, 0]), q, color, 2))
        out.append(f'<text x="{q[0]+5:.2f}" y="{q[1]-6:.2f}" fill="{color}" font-size="16">{label}</text>')
    for index, (color, label) in enumerate(((COLORS['germanium'], 'Ge crystal'), (COLORS['outer'], 'Outer Al cover'), (COLORS['inner'], 'Inner Al shield'))):
        x = 50+index*300
        out.append(f'<rect x="{x}" y="566" width="16" height="16" fill="{color}"/><text x="{x+25}" y="581" font-size="19">{label}</text>')
    out.extend(['<text x="35" y="626" font-size="18">Crystal center (0, 0, 0); +z is the detector front. Coordinates in mm.</text>',
                '<text x="35" y="660" font-size="18" fill="#efc972">Measured front layers; nominal side/rear enclosure and gap split.</text>',
                '<text x="35" y="690" font-size="16" fill="#b9cadd">Holders, cold finger and instrument body are not modeled.</text>', '</g></svg>'])
    return ('\n'.join(out)+'\n').encode()


def section_svg(scene):
    out = svg_header('GeGI native mesh section y equals zero, with front detail', 1000, 720)
    out.extend(['<text x="30" y="40" font-size="25">GeGI cross-section · y = 0 · millimetres</text>',
                '<text x="30" y="72" font-size="17" fill="#b9cadd">Exact plane intersections of the saved native mesh. +z points upward.</text>'])
    def draw_panel(x0, y0, scale, zoffset, front=False):
        def project(p):
            return [x0+scale*p[0], y0-scale*(p[2]-zoffset)]
        for v in scene['volumes']:
            if v['name'] == 'cryostat_vacuum':
                continue
            for a, b in v['section_y0_mm']:
                if front:
                    if max(a[2], b[2]) < 3 or min(a[2], b[2]) > 15:
                        continue
                    if a[2] < 3 or b[2] < 3:
                        t = (3-a[2])/(b[2]-a[2]); p = [x+t*(y-x) for x, y in zip(a, b)]
                        if a[2] < 3:
                            a = p
                        else:
                            b = p
                out.append(svg_line(project(a), project(b), v['color'], 2))
        return project
    main = draw_panel(350, 157, 4.6, 13.6)
    for z, label in ((13.6, '13.6 outer front'), (5.5, '5.5 crystal front'), (-5.5, '−5.5 crystal rear'), (-60, '−60 inner rear'), (-66.4, '−66.4 outer rear')):
        p = main([62, 0, z]); out.append(svg_line(p, [655, p[1]], '#7a8d9e', .8))
        out.append(f'<text x="665" y="{p[1]+5:.2f}" font-size="16">z = {label}</text>')
    out.append('<text x="45" y="565" font-size="20">Front detail (z expanded 5× relative to x)</text>')
    # Same mesh section, independently enlarged z-axis only for thin-layer legibility.
    for v in scene['volumes']:
        if v['name'] not in ('germanium', 'outer_front', 'inner_front'):
            continue
        for a, b in v['section_y0_mm']:
            if min(a[2], b[2]) < 5.4:
                continue
            def detail(p):
                return [350+4*p[0], 685-12*(p[2]-5.5)]
            out.append(svg_line(detail(a), detail(b), v['color'], 2.4))
    for z, label, color in ((13.6, 'Outer cover: 1.6 mm', COLORS['outer']), (9.5, 'Inner shield: 0.8 mm', COLORS['inner']), (5.5, 'Crystal front; total standoff 8.1 mm', COLORS['germanium'])):
        y = 685-12*(z-5.5)
        out.append(f'<text x="620" y="{y+5:.2f}" font-size="16" fill="{color}">{label}</text>')
    out.append('<text x="45" y="120" font-size="17" fill="#efc972">Nominal gaps: crystal → shield 3.2 mm; shield → cover 2.5 mm.</text>')
    out.extend(['</g></svg>'])
    return ('\n'.join(out)+'\n').encode()


def render_page(scene, events, provenance, report):
    """Render saved values through the current template and navigation only."""
    rows = '<tr><td>GeGI crystal</td><td>Octagonal; x/y bounds ±45</td><td>−5.5 to +5.5</td><td>Frozen detector model</td></tr>'
    for part in report['geometry']['parts']:
        rows += f'<tr><td>{LABELS[part["name"]]}</td><td>{part["rmin_mm"]:g} to {part["rmax_mm"]:g}</td><td>{part["zmin_mm"]:g} to {part["zmax_mm"]:g}</td><td>{html.escape(part["basis"])}</td></tr>'
    page = (ROOT/'tools/gegi_assembly.html').read_text(encoding='utf-8')
    import site_routes
    import site_discovery
    route = 'assemblies/gegi/index.html'
    tags = (f'<meta name="description" content="{html.escape(site_discovery.LANDINGS[route], quote=True)}">'
            f'<link rel="canonical" href="{site_discovery.canonical(route)}">')
    page = page.replace('<title>', tags+'<title>', 1).replace('__NAV__', site_routes.page_navigation(route))
    event_marker = '<script type="application/json" id="event-data"></script>'
    require(page.count(event_marker) == 1, 'Expected exactly one saved-event JSON insertion point')
    return page.replace('__ROWS__', rows).replace('__PROVENANCE__', html.escape(json.dumps(provenance, indent=2))).replace(
        '__SCENE__', inline_json(scene)).replace(event_marker,
        '<script type="application/json" id="event-data">'+inline_json(events)+'</script>')


def build():
    frozen()
    sources, native, prepared, report, asset, pins = saved_native()
    events, event_bytes = saved_events()
    checked(BUNDLE, WORK, new=True)
    scene = public_scene(native, prepared, report, asset, pins)
    provenance = {'kind': KIND, 'input_files': pins, 'source_sha256': sources['source_sha256'],
                  'model_sha256': prepared['model_sha256'], 'asset_sha256': sha(ROOT/ASSET),
                  'native_executable': info(EXE), 'native_scene': info(NATIVE),
                  'native_core_reuse': 'G4GDMLParser/G4Polyhedron core with confined paths. Cryostat walls use direct native meshes. The crystal uses an exact G4PolyhedronArbitrary octagon derived from the unchanged native bounds and diagonal DistanceToOut, avoiding singleton-union failure and Boolean display offsets. Transport GDML unchanged.',
                  'native_crystal_occupancy_check': {'boundary_vertices': 16, 'boundary_face_centers': 20, 'deterministic_points': 3969, 'basis': 'Native Inside checks on derived mesh vertices/face centers and against octagonal occupancy; not exhaustive geometry validation.'},
                  'renderer_reuse': 'Canvas projection, face sorting and camera controls adapted from geometry_events.html.',
                  'coordinate_convention': asset['coordinate_convention'], 'geometry_report': report,
                  'material_approximation': asset['radiation_material']['approximation'],
                  'scope': asset['scope'], 'omitted': asset['omitted'],
                  'software': {'geant4': prepared['runtime']['packages']['geant4']['version'],
                               'remage_geometry_check': prepared['runtime']['packages']['remage']['version']},
                  'display_revision': 'saved_scored_segments_v3',
                  'saved_event_display': {'sha256': EVENTS_SHA256, 'record_count': len(events['records']),
                    'scored_segment_count': sum(len(r['radiation']['segments']) for r in events['records']),
                    'signal_counterparts_attached': 0, 'units': {'position': 'mm', 'energy': 'keV', 'time': 'ns'},
                    'scope': 'Exact positive-energy germanium scored-step chords. Not complete tracks through unscored material.',
                    'selection': 'Saved representative identities for transport display only; no source-labelled signal reconstruction.'},
                  'radiation_calls': 0, 'field_solves': 0}
    page = render_page(scene, events, provenance, report)
    bodies = {'index.html': page.encode(), 'viewer.js': (ROOT/'tools/gegi_assembly.js').read_bytes(),
              'scene.json': encoded(scene), 'preview.svg': preview_svg(scene), 'cross-section.svg': section_svg(scene),
              'geometry.gdml': (SAVED/'geometry.gdml').read_bytes(), 'event-data.json': event_bytes,
              'gegi_signal_journey.js': (ROOT/'tools/gegi_signal_journey.js').read_bytes()}
    for body in bodies.values():
        public(body)
    require(saved_native()[0] == sources and inputs()[3] == pins and saved_events()[1] == event_bytes,
            'Frozen inputs changed while rendering')
    BUNDLE.mkdir()
    for name, body in bodies.items():
        write(BUNDLE/name, body, public_output=True)
    manifest = {**provenance, 'status': 'complete', 'assembly_volume_count': 8, 'world_volume_published': False,
                'files': {name: info(BUNDLE/name) for name in PUBLIC_FILES}}
    write(BUNDLE/'manifest.json', encoded(manifest), public_output=True)
    return validate_bundle()


def refresh_presentation(source_bundle, output_bundle):
    """Create a new display bundle from the exact saved eight-file predecessor.

    Only HTML, viewer code and presentation provenance are regenerated. Native
    inspection, mesh construction, radiation and semiconductor work are absent.
    """
    source_bundle = Path(source_bundle)
    predecessor_hash = sha(source_bundle/'manifest.json')
    require(predecessor_hash in PRESENTATION_PREDECESSORS,
            'Presentation refresh requires the exact authenticated saved predecessor')
    original = validate_bundle(source_bundle)
    output_bundle = checked(output_bundle, WORK, new=True)
    sources = source_hashes()
    require(sha(ROOT/'tools/gegi_signal_journey.js') == original['files']['gegi_signal_journey.js']['sha256'],
            'Presentation refresh cannot change the saved signal journey')
    provenance = {key: value for key, value in original.items() if key != 'files'}
    provenance.update(source_sha256=sources, display_revision='presentation_audit_20261022',
                      presentation_refresh={'kind': 'gegi_assembly_presentation_refresh_v1',
                        'predecessor_manifest_sha256': predecessor_hash,
                        'predecessor_manifest': original})
    bodies = {name: (source_bundle/name).read_bytes() for name in PRESERVED_DISPLAY_FILES}
    bodies['index.html'] = render_page(json.loads(bodies['scene.json']), json.loads(bodies['event-data.json']),
                                       provenance, original['geometry_report']).encode()
    bodies['viewer.js'] = (ROOT/'tools/gegi_assembly.js').read_bytes()
    for body in bodies.values():
        public(body)
    require(source_hashes() == sources and sha(source_bundle/'manifest.json') == predecessor_hash
            and all(info(source_bundle/name) == record for name, record in original['files'].items()),
            'Saved bundle or presentation source changed while rendering')
    output_bundle.mkdir()
    for name in PUBLIC_FILES:
        write(output_bundle/name, bodies[name], public_output=True)
    require(source_hashes() == sources, 'Presentation source changed before manifest completion')
    manifest = {**provenance, 'files': {name: info(output_bundle/name) for name in PUBLIC_FILES}}
    write(output_bundle/'manifest.json', encoded(manifest), public_output=True)
    return validate_bundle(output_bundle)


def validate_presentation_refresh(manifest):
    refresh = manifest.get('presentation_refresh')
    if refresh is None:
        return
    require(set(refresh) == {'kind', 'predecessor_manifest_sha256', 'predecessor_manifest'}
            and refresh['kind'] == 'gegi_assembly_presentation_refresh_v1', 'Unknown presentation refresh provenance')
    original = refresh['predecessor_manifest']
    require(refresh['predecessor_manifest_sha256'] in PRESENTATION_PREDECESSORS
            and hashlib.sha256(encoded(original)).hexdigest() == refresh['predecessor_manifest_sha256'],
            'Presentation predecessor manifest changed')
    require(set(manifest) == set(original) | {'presentation_refresh'}
            and manifest['display_revision'] == 'presentation_audit_20261022', 'Unexpected presentation refresh fields')
    for key, value in original.items():
        if key not in ('source_sha256', 'files', 'display_revision'):
            require(manifest[key] == value, 'Presentation refresh changed saved provenance: '+key)
    for name in PRESERVED_DISPLAY_FILES:
        require(manifest['files'][name] == original['files'][name],
                'Presentation refresh changed saved scientific artifact: '+name)


def validate_bundle(bundle=BUNDLE):
    bundle = Path(bundle); manifest = read(bundle/'manifest.json')
    manifest_hash = sha(bundle/'manifest.json')
    legacy = manifest_hash in PREVIOUS_BUNDLES
    predecessor = manifest_hash in PRESENTATION_PREDECESSORS
    require(manifest['kind'] == KIND and manifest['status'] == 'complete' and
            manifest['assembly_volume_count'] == 8 and manifest['radiation_calls'] == manifest['field_solves'] == 0,
            'Incomplete GeGI assembly publication')
    require(set(manifest['files']) == set(LEGACY_PUBLIC_FILES if legacy else PUBLIC_FILES),
            'Unexpected assembly file set')
    for name, record in manifest['files'].items():
        require(info(bundle/name) == record, 'Saved assembly artifact changed: '+name)
        public((bundle/name).read_bytes())
    public((bundle/'manifest.json').read_bytes())
    require(sha(bundle/'geometry.gdml') == manifest['input_files']['geometry.gdml']['sha256'], 'Published GDML differs')
    scene = read(bundle/'scene.json')
    require(len(scene['volumes']) == 8 and {v['name'] for v in scene['volumes']} == set(LABELS), 'Public assembly census differs')
    current_sources = source_hashes()
    require(manifest['source_sha256'] == current_sources or legacy or predecessor,
            'Public assembly exporter source differs')
    require(all(manifest['source_sha256'][ref] == current_sources[ref] for ref in NATIVE_SOURCE_FILES),
            'Saved assembly native exporter source differs')
    validate_presentation_refresh(manifest)
    if not legacy:
        events = validate_events(read(bundle/'event-data.json'))
        require(sha(bundle/'event-data.json') == EVENTS_SHA256
                and manifest['saved_event_display']['sha256'] == EVENTS_SHA256
                and manifest['saved_event_display']['record_count'] == len(events['records'])
                and manifest['saved_event_display']['scored_segment_count'] == sum(len(r['radiation']['segments']) for r in events['records'])
                and manifest['saved_event_display']['signal_counterparts_attached'] == 0,
                'Saved event display provenance differs')
        page = (bundle/'index.html').read_text(encoding='utf-8')
        embedded = re.findall(r'<script type="application/json" id="event-data">(.*?)</script>', page, re.S)
        require(len(embedded) == 1 and json.loads(embedded[0]) == events, 'Embedded and downloadable saved events differ')
        require('<script src="gegi_signal_journey.js"></script>' in page, 'Shared signal viewer missing')
        require(sha(bundle/'gegi_signal_journey.js') == manifest['source_sha256']['tools/gegi_signal_journey.js'],
                'Shared signal viewer differs from source freeze')
        require(sha(bundle/'gegi_signal_journey.js') == current_sources['tools/gegi_signal_journey.js'],
                'Saved signal journey source changed')
    if bundle == BUNDLE and not predecessor:
        sources, native, prepared, report, asset, pins = saved_native()
        require(scene == public_scene(native, prepared, report, asset, pins) and manifest['input_files'] == pins,
                'Public mesh differs from its native saved source')
    return manifest


def publish(site_output, bundle=None):
    """Called by build_site.py; copies existing checked files without native work."""
    target = checked(Path(site_output)/'assemblies/gegi', Path(site_output))
    bundle = (DISPLAY_BUNDLE if DISPLAY_BUNDLE.exists() else BUNDLE) if bundle is None else Path(bundle)
    if bundle == BUNDLE and not bundle.exists():
        # A clean clone retains the hash-checked public bundle in the site tree.
        # Validation here reads source and public artifacts only, never .local data.
        manifest = validate_bundle(target)
    else:
        manifest = validate_bundle(bundle)
        target.mkdir(parents=True, exist_ok=True)
        for name in (*manifest['files'], 'manifest.json'):
            checked(target/name, target)
            shutil.copyfile(bundle/name, target/name)
        require(validate_bundle(target) == manifest, 'Copied GeGI assembly differs')
    return {'kind': KIND, 'page': 'assemblies/gegi/index.html', 'assembly_volume_count': 8,
            'geometry_sha256': manifest['input_files']['geometry.gdml']['sha256'],
            'files': ['assemblies/gegi/'+name for name in (*manifest['files'], 'manifest.json')]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'inspect', 'build', 'validate'))
    args = parser.parse_args()
    result = {'freeze': freeze, 'inspect': inspect_native, 'build': build, 'validate': validate_bundle}[args.action]()
    print(json.dumps({'kind': KIND, 'action': args.action, 'status': result.get('status', 'complete'),
                      'assembly_volume_count': result.get('assembly_volume_count', 8)}, sort_keys=True))
