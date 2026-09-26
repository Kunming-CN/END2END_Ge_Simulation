"""Stage two-contact geometry illustrations; never rebuild meshes or fields.

Use ParaView 6.1.1 pvpython with --detectors AK02 SAP22 (or --all) and
--output .local/<new-folder>. --check-only performs read-only stdlib preflight.
Only PNG, PVSM and an inventory are staged. The supervisor reviews/applies them.
Use --apply STAGED_DIR with ordinary Python after image review. Apply verifies
all inputs before writes, keeps originals.zip and an apply receipt in staging,
and maintains one .local/contact-display-applied.json for website build checks.
Historical schema-1 ledgers remain readable. A different palette may be previewed,
but applying it requires --upgrade-style and a fresh stage covering all 16 IDs.
New inventories use schema 3 (tool hashes and prior-ledger hash); schema-2 stages
must be restaged. New receipts use schema 2; previous receipts are never edited.
Replacement is atomic per file, not across files. Caught failures roll back;
host crashes/power loss or rollback I/O failure require inspecting that backup.
Run under the supervisor's exclusive project ownership, with no other writers.
The saved XML changes only actor colors/opacity and the existing title text;
loading that staged state preserves all other properties, including the camera
and the original display-only contact scale 1.001 and translation. This scale
is inherited anti-flicker styling, not a physical Li diffusion-layer thickness.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from export_models import ORIGINAL_HASHES, no_links, read_distribution, safe_path

ROOT = Path(__file__).resolve().parents[1]
RUN = '20260922_suite_v3'
SKIP = 'GeGI_3D'
MESHES = ('crystal.vtp', 'contact_01.vtp', 'contact_02.vtp')
OUTPUTS = ('01_geometry.png', '01_geometry.pvsm')
APPLIED = '.local/contact-display-applied.json'
TOOL_SOURCES = ('tools/render_contacts.py', 'tools/build_site.py', 'tools/test_contacts.py')
DISPLAY_NOTE = 'Original scale 1.001 and translation preserved; no mesh changes.'
STYLE = {
    'crystal.vtp': {'rgb': [0.42, 0.55, 0.65], 'opacity': 0.15, 'color': 'Grey-blue'},
    'contact_01.vtp': {'rgb': [0.94, 0.30, 0.16], 'opacity': 0.95, 'color': 'Orange-red'},
    'contact_02.vtp': {'rgb': [0.05, 0.60, 0.85], 'opacity': 0.35, 'color': 'Cyan-blue'},
}
SURFACE_NOTE = 'Contact surfaces, not physical Li diffusion-layer thickness.'
CATEGORY_NOTE = 'Colors identify contact IDs, not doping signs.'
TRANSFORMS = ('Scale', 'Translation', 'Orientation', 'Origin')
CAMERA = ('CameraPosition', 'CameraFocalPoint', 'CameraViewUp',
          'CameraParallelScale', 'CameraParallelProjection', 'CameraViewAngle')


def checked_path(path, root, *, file=False):
    """Reject links/junctions before resolving, including linked ancestors."""
    path, root = Path(path), Path(root)
    no_links(root)
    no_links(path)
    resolved = path.resolve(strict=file)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Path escapes approved root: ' + str(path))
    if file and not resolved.is_file():
        raise ValueError('Expected a regular file: ' + str(path))
    return resolved


def output_path(path, root=ROOT):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    local = checked_path(root / '.local', root)
    target = checked_path(path, local)
    if target == local or target.exists():
        raise ValueError('Output must be a new, nonexistent directory under .local')
    # Do not create/clean a supervisor state, site staging, or native directory.
    if target.relative_to(local).parts[0] in {'autonomy', 'site-build', 'site-previous'}:
        raise ValueError('Reserved output directory')
    return target


def sha256(path):
    with path.open('rb') as stream:
        result = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def contacts(item):
    values = item.get('contacts', [])
    if (len(values) != 2 or any(type(c.get('id')) is not int for c in values)
            or {c['id'] for c in values} != {1, 2}):
        raise ValueError('Expected exactly contact IDs 1 and 2')
    for contact in values:
        name, voltage = contact.get('name'), contact.get('potential_V')
        if (not isinstance(name, str) or not name.strip()
                or any(ord(c) < 32 for c in name)
                or type(voltage) not in (int, float) or not math.isfinite(voltage)):
            raise ValueError('Invalid contact name or voltage')
    return sorted(values, key=lambda c: c['id'])


def contact_label(contact):
    return f"Contact {contact['id']}: {contact['name']} ({contact['potential_V']:g} V)"


def validate_palette(style):
    """Validate historical data independently of the currently requested palette."""
    if not isinstance(style, dict) or set(style) != set(MESHES):
        raise ValueError('Palette must contain exactly the three geometry meshes')
    for entry in style.values():
        if not isinstance(entry, dict) or set(entry) != {'rgb', 'opacity', 'color'}:
            raise ValueError('Unexpected palette style keys')
        if not isinstance(entry['rgb'], list) or len(entry['rgb']) != 3:
            raise ValueError('Palette RGB must have three components')
        for value in [*entry['rgb'], entry['opacity']]:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Palette RGB/opacity must be finite numbers in [0, 1]')
        label = entry['color']
        if (not isinstance(label, str) or len(label) > 48
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?:[ -][A-Za-z0-9]+)*', label)):
            raise ValueError('Unsafe palette color label')


def canonical_catalog(root=ROOT):
    folder = checked_path(root / 'models', root)
    catalog = json.loads(read_distribution(folder)['catalog.json'])
    result = {item['id']: item for item in catalog['detectors']}
    for ident, item in result.items():
        if ident != SKIP:
            contacts(item)
    return result


def select_detectors(catalog, selected=None):
    selected = sorted(set(catalog) - {SKIP}) if selected is None else list(selected)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError('Select a nonempty subset without duplicate detector IDs')
    for ident in selected:
        if ident == SKIP:
            raise ValueError('GeGI_3D is explicitly deferred (34 channels)')
        if ident not in catalog or ident not in ORIGINAL_HASHES:
            raise ValueError('Unknown detector ID: ' + ident)
        contacts(catalog[ident])
    return sorted(selected)


def validate_metadata(ident, item, fields, snapshot_hash):
    if (item['id'] != ident or fields.get('detector_id') != ident
            or fields.get('source', {}).get('id') != ident):
        raise ValueError('Mismatched model IDs: ' + ident)
    expected = ORIGINAL_HASHES[ident]
    if any(value != expected for value in
           (item['model_sha256'], fields['source'].get('model_sha256'), snapshot_hash)):
        raise ValueError('Stale snapshot/model hash: ' + ident)
    for key in ('contacts', 'bounds_mm', 'coordinate_system', 'readout_contact_id'):
        if fields['source'].get(key) != item[key]:
            raise ValueError('Source metadata differs from canonical catalog: ' + key)
    contacts(item)


def mesh_counts(path):
    """Read XML counts without decoding, copying or altering binary arrays."""
    with path.open('rb') as stream:
        for _, node in ET.iterparse(stream, events=('start',)):
            if node.tag == 'VTKFile' and node.get('type') != 'PolyData':
                raise ValueError('Expected PolyData mesh: ' + path.name)
            if node.tag == 'Piece':
                points = int(node.get('NumberOfPoints', '0'))
                cells = sum(int(node.get(key, '0')) for key in
                            ('NumberOfVerts', 'NumberOfLines', 'NumberOfStrips', 'NumberOfPolys'))
                if points <= 0 or cells <= 0:
                    raise ValueError('Empty geometry mesh: ' + path.name)
                return {'points': points, 'cells': cells}
    raise ValueError('Missing geometry mesh piece: ' + path.name)


def values(proxy, name):
    prop = proxy.find(f"Property[@name='{name}']")
    if prop is None:
        raise ValueError('Missing scene property: ' + name)
    return [node.attrib['value'] for node in prop.findall('Element')]


def set_values(proxy, name, replacement):
    old = values(proxy, name)
    if len(old) != len(replacement):
        raise ValueError('Unexpected property size: ' + name)
    for node, value in zip(proxy.findall(f"Property[@name='{name}']/Element"), replacement):
        node.set('value', str(value))


def style_state(data, run, item, historical_style=None):
    """Fail closed on extra pipelines; modify only four presentation properties.

    Glyph prototypes are ParaView representation helpers, not registered sources.
    All registered sources must be the three exact readers plus one title.
    Only preflight supplies historical_style, after verifying the prior ledger's
    native state/image hashes. Ordinary callers accept original/current titles.
    """
    tree = ET.fromstring(data)
    state = tree.find('ServerManagerState')
    if state is None or state.get('version') != '6.1.1':
        raise ValueError('Expected a ParaView 6.1.1 baseline state')
    proxies = {p.attrib['id']: p for p in state.findall('Proxy')}
    registered = state.findall("ProxyCollection[@name='sources']/Item")
    if len(registered) != 4 or len({p.attrib['id'] for p in registered}) != 4:
        raise ValueError('Expected three geometry readers and one title')
    source_ids = {p.attrib['id'] for p in registered}
    source_names = {p.attrib['id']: p.attrib['name'] for p in registered}
    helpers = {'ArrowSource', 'ConeSource', 'CubeSource', 'CylinderSource',
               'LineSource', 'SphereSource', 'GlyphSource2D'}
    readers, title = {}, None
    for pid, proxy in proxies.items():
        kind = proxy.get('type')
        if proxy.get('group') == 'sources':
            if pid not in source_ids and kind not in helpers:
                raise ValueError('Unexpected unregistered scene source: ' + str(kind))
            if pid in source_ids:
                if kind == 'TextSource' and title is None:
                    title = proxy
                elif kind == 'XMLPolyDataReader':
                    names = values(proxy, 'FileName')
                    if len(names) != 1:
                        raise ValueError('Expected one geometry mesh per reader')
                    path = checked_path(Path(names[0]), run, file=True)
                    if path.parent != run or path.name not in MESHES or path.name in readers:
                        raise ValueError('Unexpected geometry mesh source')
                    if values(proxy, 'FileNameInfo') != names:
                        raise ValueError('Conflicting scene file provenance')
                    expected_name = 'Germanium crystal | mm'
                    if path.name != 'crystal.vtp':
                        contact = contacts(item)[MESHES.index(path.name) - 1]
                        expected_name = (f"Electrode {contact['id']} | {contact['name']} | "
                                         f"{contact['potential_V']} V")
                    if source_names[pid] != expected_name:
                        raise ValueError('Scene source identity differs from catalog: ' + path.name)
                    readers[path.name] = proxy
                else:
                    raise ValueError('Non-geometry registered source: ' + str(kind))
        # No additional file consumers (fields, textures, caches, etc.).
        for prop in proxy.findall('Property'):
            if (prop.get('name') in {'FileName', 'FileNames', 'FileNameInfo'}
                    or prop.find("Domain[@name='files']") is not None):
                if kind != 'XMLPolyDataReader' or pid not in source_ids:
                    raise ValueError('Unexpected file consumer in geometry state')
    if set(readers) != set(MESHES) or title is None:
        raise ValueError('Missing contacts, crystal or title')
    views = [p for p in proxies.values() if p.get('group') == 'views']
    layouts = state.findall("ProxyCollection[@name='layouts']/Item")
    if len(views) != 1 or views[0].get('type') != 'RenderView' or len(layouts) != 1:
        raise ValueError('Expected one geometry view/layout')
    camera = {name: values(views[0], name) for name in CAMERA}
    if any(not math.isfinite(float(v)) for row in camera.values() for v in row):
        raise ValueError('Invalid original camera; supervisor review required')
    size = [int(v) for v in values(views[0], 'ViewSize')]
    if len(size) != 2 or min(size) <= 0:
        raise ValueError('Invalid original view size')
    transforms = {}
    for name, reader in readers.items():
        reps = [p for p in proxies.values() if p.get('group') == 'representations'
                and p.get('type') == 'GeometryRepresentation'
                and p.find(f"Property[@name='Input']/Proxy[@value='{reader.attrib['id']}']") is not None]
        if len(reps) != 1 or reps[0].get('type') != 'GeometryRepresentation':
            raise ValueError('Expected one direct geometry actor: ' + name)
        actor = reps[0]
        if values(actor, 'Visibility') != ['1']:
            raise ValueError('Baseline geometry actor is hidden: ' + name)
        if values(actor, 'Representation') != ['Surface'] or any(values(actor, 'ColorArrayName')):
            raise ValueError('Expected a solid-color surface actor: ' + name)
        transforms[name] = {key: values(actor, key) for key in TRANSFORMS}
        expected_scale = [1.0 if name == 'crystal.vtp' else 1.001] * 3
        if [float(v) for v in transforms[name]['Scale']] != expected_scale:
            raise ValueError('Unexpected baseline display scale: ' + name)
        # These are the only geometry actor properties changed.
        set_values(actor, 'DiffuseColor', STYLE[name]['rgb'])
        set_values(actor, 'AmbientColor', STYLE[name]['rgb'])
        set_values(actor, 'Opacity', [STYLE[name]['opacity']])
    title_text = values(title, 'Text')[0]
    original_title = title_text.split('\n')
    if len(original_title) != 4 or original_title[0] != item['id'] + ' ; Geometry':
        raise ValueError('Unexpected geometry title/model identity')
    if not re.fullmatch(r'-?\d+(?:\.\d+)? V ; \d+(?:\.\d+)? K ; dimensions in mm', original_title[1]):
        raise ValueError('Unexpected geometry title conditions')
    # Keep temperature, bias span and units verbatim; catalog voltages retain signs.
    legend = original_title[:2] + [
        f"{STYLE['contact_%02d.vtp' % c['id']]['color']} - {contact_label(c)}"
        for c in contacts(item)]
    # Keep the four-line image header clear of tall detectors. Detailed
    # bulk/category/thickness notes remain in the HTML key and inventory.
    baseline = original_title[:2] + [
        f"{'Orange' if c['id'] == item['readout_contact_id'] else 'Grey'}: "
        f"{c['name']} ({c['potential_V']:g} V)" for c in contacts(item)]
    accepted = [baseline, legend]
    if historical_style is not None:
        validate_palette(historical_style)
        accepted.append(original_title[:2] + [
            f"{historical_style['contact_%02d.vtp' % c['id']]['color']} - {contact_label(c)}"
            for c in contacts(item)])
    if original_title not in accepted:
        raise ValueError('Unexpected geometry title; only original or exact styled legend is accepted')
    set_values(title, 'Text', ['\n'.join(legend)])
    return ET.tostring(tree, encoding='utf-8', xml_declaration=True), {
        'camera': camera, 'image_size': size, 'display_transforms': transforms,
        'legend': legend,
    }


def preflight(ident, item, root=ROOT):
    run = checked_path(root / 'Additional_Simulations/Visualization_3D/detectors'
                       / ident / 'runs' / RUN, root)
    paths = [checked_path(run / name, run, file=True) for name in
             (*OUTPUTS, 'fields.json', 'model.snapshot.yaml', *MESHES)]
    fields = json.loads((run / 'fields.json').read_bytes())
    validate_metadata(ident, item, fields, sha256(run / 'model.snapshot.yaml'))
    provenance = checked_path(root / safe_path(item['source']), root, file=True)
    recorded = checked_path(Path(fields['source']['model']), root, file=True)
    if recorded != provenance:
        raise ValueError('Source model path differs from canonical provenance')
    # Read only this small, recorded dependency, never its numerical cache.
    if sha256(recorded) != ORIGINAL_HASHES[ident]:
        raise ValueError('Changed recorded original model: ' + ident)
    paths += [recorded, checked_path(root / 'models' / item['model'], root, file=True),
              checked_path(root / 'models/catalog.json', root, file=True)]
    meshes = {name: mesh_counts(run / name) for name in MESHES}
    prior, ledger_bytes = read_applied(root, canonical_catalog(root))
    historical_style = None
    if ident in prior:
        # A ledger is not permission to relabel stale/edited native results.
        verify_sources(prior[ident], root)
        historical_style = json.loads(ledger_bytes)['style']
    staged, presentation = style_state((run / '01_geometry.pvsm').read_bytes(), run, item,
                                        historical_style=historical_style)
    inventory = {'id': ident, 'model_sha256': ORIGINAL_HASHES[ident],
                 'sources': {p.relative_to(root).as_posix(): sha256(p) for p in paths},
                 'meshes': meshes, **presentation}
    return staged, inventory


def verify_sources(inventory, root=ROOT):
    for name, expected in inventory['sources'].items():
        if sha256(checked_path(root / name, root, file=True)) != expected:
            raise ValueError('Source changed during staging: ' + name)


def render(staged, inventory, folder, p):
    """Load the styled baseline; update only geometry readers and render one view."""
    if folder.exists():
        raise ValueError('Generated destination already exists: ' + str(folder))
    folder.mkdir()
    state_path = folder / '01_geometry.pvsm'
    with state_path.open('xb') as stream:
        stream.write(staged)
    p.ResetSession()
    p._DisableFirstRenderCameraReset()
    p.LoadState(str(state_path))
    views, layouts = p.GetViews(), list(p.GetLayouts().values())
    sources = list(p.GetSources().values())
    if len(views) != 1 or len(layouts) != 1 or len(sources) != 4:
        raise ValueError('Loaded scene differs from validated geometry inventory')
    for source in sources:
        if source.SMProxy.GetXMLName() == 'XMLPolyDataReader':
            source.UpdatePipeline()
            info = source.GetDataInformation()
            name = Path(str(source.FileName[0])).name
            counts = {'points': info.GetNumberOfPoints(), 'cells': info.GetNumberOfCells()}
            if counts != inventory['meshes'][name]:
                raise ValueError('Loaded mesh counts differ: ' + name)
    p.Render(views[0])
    # Use the original layout dimensions and camera; never ResetCamera().
    p.SaveScreenshot(str(folder / '01_geometry.png'), layouts[0],
                     ImageResolution=inventory['image_size'])
    for name in ('01_geometry.png', '01_geometry.pvsm'):
        if not (folder / name).is_file() or not (folder / name).stat().st_size:
            raise ValueError('Missing/empty staged output: ' + name)
    inventory['outputs'] = {name: sha256(folder / name)
                            for name in ('01_geometry.png', '01_geometry.pvsm')}


def report_header(root=ROOT):
    validate_palette(STYLE)
    prior = checked_path(root / APPLIED, root)
    return {'schema_version': 3, 'style': STYLE, 'skipped': [SKIP],
            'surface_note': SURFACE_NOTE, 'category_note': CATEGORY_NOTE,
            'display_note': DISPLAY_NOTE, 'random_seed': None,
            'provenance': {name: sha256(checked_path(root / name, root, file=True)) for name in TOOL_SOURCES},
            'prior_applied_sha256': sha256(prior) if prior.exists() else None}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def native_run(root, ident):
    return checked_path(root / 'Additional_Simulations/Visualization_3D/detectors'
                        / ident / 'runs' / RUN, root)


def read_applied(root, catalog):
    path = checked_path(root / APPLIED, root)
    if not path.exists():
        return {}, None
    data = path.read_bytes()
    record = json.loads(data)
    if (set(record) != {'schema_version', 'style', 'detectors'}
            or record['schema_version'] != 1
            or not isinstance(record['detectors'], dict)):
        raise ValueError('Unexpected local applied inventory')
    validate_palette(record['style'])
    entries = record['detectors']
    if entries:
        select_detectors(catalog, entries)
    for ident, entry in entries.items():
        if (set(entry) != {'sources', 'outputs', 'model_sha256'}
                or entry['model_sha256'] != ORIGINAL_HASHES[ident]
                or set(entry['outputs']) != set(OUTPUTS)):
            raise ValueError('Invalid applied detector entry: ' + ident)
        run = native_run(root, ident)
        expected_sources = {(run / name).relative_to(root).as_posix() for name in
                            (*OUTPUTS, 'fields.json', 'model.snapshot.yaml', *MESHES)}
        expected_sources.update((safe_path(catalog[ident]['source']),
                                 'models/' + safe_path(catalog[ident]['model']), 'models/catalog.json'))
        if set(entry['sources']) != expected_sources:
            raise ValueError('Unexpected applied source inventory: ' + ident)
        for name, sha in entry['sources'].items():
            checked_path(root / safe_path(name), root, file=True)
            if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
                raise ValueError('Invalid applied source hash')
        if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
               for sha in entry['outputs'].values()):
            raise ValueError('Invalid applied output hash')
        if any(entry['sources'][(run / name).relative_to(root).as_posix()] != entry['outputs'][name]
               for name in OUTPUTS):
            raise ValueError('Inconsistent applied source/output hashes: ' + ident)
    return entries, data


def verify_applied_style(root=ROOT):
    """Local build gate only; the portable published-site validator is unchanged."""
    try:
        catalog = canonical_catalog(root)
        entries, ledger_bytes = read_applied(root, catalog)
        if ledger_bytes is None or json.loads(ledger_bytes)['style'] != STYLE:
            raise ValueError('Applied palette differs from current STYLE; an explicit full style upgrade is required')
        if set(entries) != set(select_detectors(catalog)):
            raise ValueError('Applied inventory must cover all 16 two-contact detectors')
        for ident, entry in entries.items():
            styled, current = preflight(ident, catalog[ident], root)
            run = native_run(root, ident)
            if (current['sources'] != entry['sources']
                    or any(sha256(run / name) != entry['outputs'][name] for name in OUTPUTS)
                    or (run / '01_geometry.pvsm').read_bytes() != styled):
                raise ValueError('Native geometry/image no longer matches applied style: ' + ident)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise ValueError('Contact color key cannot be published: ' + str(error)
                         + '. Review and apply a current tools/render_contacts.py stage for all 16 '
                         'detectors. A full gallery rebuild may have reset their geometry.') from error


def validate_stage(stage, root=ROOT, *, upgrade_style=False):
    """Return a fully checked in-memory transaction, with no filesystem writes."""
    stage = Path(stage)
    if not stage.is_absolute():
        stage = root / stage
    stage = checked_path(stage, root / '.local')
    if not stage.is_dir() or stage == (root / '.local').resolve():
        raise ValueError('Expected a staged directory below .local')
    if stage.relative_to((root / '.local').resolve()).parts[0] in {'autonomy', 'site-build', 'site-previous'}:
        raise ValueError('Reserved staged directory')
    for name in ('originals.zip', 'apply-receipt.json'):
        if (stage / name).exists():
            raise ValueError('Stage already applied or attempted; inspect backup/receipt before any retry')
    inventory_path = checked_path(stage / 'inventory.json', stage, file=True)
    inventory_bytes = inventory_path.read_bytes()
    report = json.loads(inventory_bytes)
    header = report_header(root)
    if (set(report) != set(header) | {'python', 'paraview', 'detectors'}
            or any(report.get(key) != value for key, value in header.items())
            or report.get('paraview') != '6.1.1'):
        raise ValueError('Expected current schema 3 stage with matching tool/prior-ledger hashes; restage with this renderer')
    catalog = canonical_catalog(root)
    rows = report['detectors']
    selected = select_detectors(catalog, [row['id'] for row in rows])
    if [row['id'] for row in rows] != selected:
        raise ValueError('Staged detector IDs must be unique and sorted')
    expected_files = {'inventory.json'} | {f'{ident}/{name}' for ident in selected for name in OUTPUTS}
    actual_files, actual_dirs = set(), set()
    for path in stage.rglob('*'):
        checked_path(path, stage)
        relative = path.relative_to(stage).as_posix()
        if path.is_file():
            actual_files.add(relative)
        elif path.is_dir():
            actual_dirs.add(relative)
        else:
            raise ValueError('Unexpected staged filesystem entry')
    if actual_files != expected_files or actual_dirs != set(selected):
        raise ValueError('Unexpected or missing staged files/directories')
    existing, old_applied = read_applied(root, catalog)
    different_style = old_applied is not None and json.loads(old_applied)['style'] != STYLE
    if different_style:
        if not upgrade_style:
            raise ValueError('Historical palette differs; applying it requires explicit --upgrade-style')
        if set(selected) != set(ORIGINAL_HASHES) - {SKIP}:
            raise ValueError('--upgrade-style requires a full 16-detector stage; partial/global mismatch refused')
    elif upgrade_style:
        raise ValueError('--upgrade-style requires a differing recorded prior palette')
    for entry in existing.values():
        verify_sources(entry, root)
    updates, replacements, originals = dict(existing), {}, {}
    for row in rows:
        ident = row['id']
        styled, fresh = preflight(ident, catalog[ident], root)
        if (set(row) != set(fresh) | {'outputs'} or set(row['outputs']) != set(OUTPUTS)
                or {key: row[key] for key in fresh} != fresh):
            raise ValueError('Staged source/input metadata changed: ' + ident)
        run = native_run(root, ident)
        updated_sources = dict(fresh['sources'])
        for name in OUTPUTS:
            data = checked_path(stage / ident / name, stage, file=True).read_bytes()
            if not data or digest(data) != row['outputs'][name]:
                raise ValueError('Staged output hash changed: ' + ident + '/' + name)
            if name.endswith('.pvsm') and data != styled:
                raise ValueError('Staged state changes more than approved styling: ' + ident)
            if name.endswith('.png') and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Staged output is not a PNG: ' + ident)
            target = checked_path(run / name, root, file=True)
            relative = target.relative_to(root).as_posix()
            original = target.read_bytes()
            if digest(original) != fresh['sources'][relative]:
                raise ValueError('Native input changed during apply preflight: ' + relative)
            originals[relative], replacements[relative] = original, data
            updated_sources[relative] = digest(data)
        updates[ident] = {'sources': updated_sources, 'outputs': row['outputs'],
                          'model_sha256': row['model_sha256']}
    originals[APPLIED] = old_applied
    replacements[APPLIED] = json_bytes({'schema_version': 1, 'style': STYLE, 'detectors': updates})
    return stage, report, digest(inventory_bytes), originals, replacements


def atomic_replace(path, data):
    """Replace one file using a flushed sibling; remove only our own temporary."""
    no_links(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.contact-display-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def apply_stage(stage, root=ROOT, *, upgrade_style=False):
    stage, report, inventory_hash, originals, replacements = validate_stage(stage, root, upgrade_style=upgrade_style)
    receipt_path = stage / 'apply-receipt.json'
    backup_path = stage / 'originals.zip'
    # Reserve a single backup exclusively. Existing/partial attempts are never reused.
    with zipfile.ZipFile(backup_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in originals.items():
            if data is not None:
                archive.writestr(name, data)
    # Verify the backup before touching any destination.
    with zipfile.ZipFile(backup_path) as archive:
        if (set(archive.namelist()) != {name for name, data in originals.items() if data is not None}
                or any(archive.read(name) != data for name, data in originals.items() if data is not None)):
            raise ValueError('Originals backup verification failed; native files were not changed')
    receipt = {'schema_version': 2, 'inventory_sha256': inventory_hash,
               'upgrade_style': upgrade_style, 'style': STYLE,
               'prior_style': json.loads(originals[APPLIED])['style'] if originals[APPLIED] is not None else None,
               'provenance': report['provenance'], 'prior_applied_sha256': report['prior_applied_sha256'],
               'backup_sha256': sha256(backup_path), 'detectors': [row['id'] for row in report['detectors']],
               'before': {name: None if data is None else digest(data) for name, data in originals.items()},
               'after': {name: digest(data) for name, data in replacements.items()}, 'status': 'applying'}
    with receipt_path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json_bytes(receipt).decode('utf-8'))
    attempted = []
    try:
        # Protect edits made between preflight and replacement, including the registry.
        if sha256(stage / 'inventory.json') != inventory_hash:
            raise ValueError('Staged inventory changed during apply')
        if any(report.get(key) != value for key, value in report_header(root).items()):
            raise ValueError('Tool provenance or prior ledger changed during apply')
        for row in report['detectors']:
            verify_sources(row, root)
            for name in OUTPUTS:
                if sha256(checked_path(stage / row['id'] / name, stage, file=True)) != row['outputs'][name]:
                    raise ValueError('Staged output changed during apply')
        for name, data in replacements.items():
            path = checked_path(root / name, root)
            current = path.read_bytes() if path.exists() else None
            if current != originals[name]:
                raise ValueError('Destination changed during apply: ' + name)
            attempted.append(name)
            atomic_replace(path, data)
        for row in report['detectors']:
            expected = dict(row['sources'])
            for name in OUTPUTS:
                relative = (native_run(root, row['id']) / name).relative_to(root).as_posix()
                expected[relative] = row['outputs'][name]
            verify_sources({'sources': expected}, root)
        for name, data in replacements.items():
            if sha256(checked_path(root / name, root, file=True)) != digest(data):
                raise ValueError('Applied destination changed: ' + name)
        receipt['status'] = 'applied'
        atomic_replace(receipt_path, json_bytes(receipt))
    except BaseException as error:
        failures = []
        for name in reversed(attempted):
            try:
                path = checked_path(root / name, root)
                if originals[name] is None:
                    if path.exists():
                        path.unlink()
                else:
                    atomic_replace(path, originals[name])
                if (path.read_bytes() if path.exists() else None) != originals[name]:
                    raise OSError('Restored bytes differ')
            except BaseException as rollback_error:
                failures.append(f'{name}: {rollback_error}')
        receipt.update(status='rollback_failed' if failures else 'rolled_back',
                       error=str(error), rollback_errors=failures)
        try:
            atomic_replace(receipt_path, json_bytes(receipt))
        except BaseException as receipt_error:
            failures.append('Cannot write failure receipt: ' + str(receipt_error))
        detail = ('Rollback incomplete; inspect originals.zip and receipt: ' + '; '.join(failures)
                  if failures else 'All attempted display/index replacements restored; originals.zip retained')
        raise RuntimeError('Apply failed: ' + str(error) + '. ' + detail) from error
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='All 16; explicitly skip GeGI_3D')
    group.add_argument('--detectors', nargs='+', metavar='ID')
    group.add_argument('--apply', type=Path, metavar='STAGED_DIR', help='Validate and apply a reviewed stage; stdlib only')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true', help='Read-only preflight; no output')
    parser.add_argument('--upgrade-style', action='store_true',
                        help='With --apply only: explicitly migrate a historical palette using all 16 detectors')
    args = parser.parse_args()
    if args.apply is not None:
        if args.output is not None or args.check_only:
            parser.error('--apply cannot be combined with --output or --check-only')
        print(json.dumps(apply_stage(args.apply, upgrade_style=args.upgrade_style), sort_keys=True, indent=2))
        return
    if args.upgrade_style:
        parser.error('--upgrade-style is only valid with --apply; previews need no upgrade permission')
    if args.output is None:
        parser.error('Staging/check-only requires --output')
    target = output_path(args.output)
    catalog = canonical_catalog()
    selected = select_detectors(catalog, None if args.all else args.detectors)
    header = report_header()
    prepared = [preflight(ident, catalog[ident]) for ident in selected]
    report = {**header, 'python': sys.version.split()[0],
              'detectors': [inventory for _, inventory in prepared]}
    if args.check_only:
        print(json.dumps(report, sort_keys=True, indent=2))
        return
    from paraview import simple as p, servermanager
    manager = servermanager.vtkSMProxyManager
    version = '.'.join(str(f()) for f in
                       (manager.GetVersionMajor, manager.GetVersionMinor, manager.GetVersionPatch))
    if version != '6.1.1':
        raise ValueError('Rendering requires reviewed ParaView 6.1.1; found ' + version)
    report['paraview'] = version
    # Revalidate after preflight, then claim an entirely new output directory.
    output_path(target)
    for _, inventory in prepared:
        verify_sources(inventory)
    target.mkdir(parents=True, exist_ok=False)
    for staged, inventory in prepared:
        render(staged, inventory, target / inventory['id'], p)
        verify_sources(inventory)
    if report_header() != header:
        raise ValueError('Tool sources or prior ledger changed while staging; do not apply these outputs')
    with (target / 'inventory.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(f'Staged {len(selected)} geometry illustrations; skipped {SKIP}. Review before applying.')


if __name__ == '__main__':
    main()
