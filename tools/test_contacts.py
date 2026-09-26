"""Stdlib contact-display guards; no ParaView import, rendering or native writes.

Run: python -B tools/test_contacts.py
"""
import copy
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

import render_contacts as rc
from build_site import adapt, contact_legend


def item():
    return {'id': 'AK02', 'model_sha256': rc.ORIGINAL_HASHES['AK02'],
            'contacts': [{'id': 1, 'name': 'point contact', 'potential_V': 0},
                         {'id': 2, 'name': 'Lithium Contact', 'potential_V': 500}],
            'bounds_mm': [-1, 1, -1, 1, 0, 2], 'coordinate_system': 'cylindrical',
            'readout_contact_id': 1}


def fixture(run, metadata=None):
    metadata = item() if metadata is None else metadata
    tree = ET.Element('GenericParaViewApplication')
    state = ET.SubElement(tree, 'ServerManagerState', version='6.1.1')
    collection = ET.SubElement(state, 'ProxyCollection', name='sources')

    def proxy(pid, group, kind, properties):
        node = ET.SubElement(state, 'Proxy', id=pid, group=group, type=kind)
        for name, values in properties.items():
            prop = ET.SubElement(node, 'Property', name=name, number_of_elements=str(len(values)))
            for i, value in enumerate(values):
                ET.SubElement(prop, 'Element', index=str(i), value=str(value))
        return node

    for index, name in enumerate(rc.MESHES, 1):
        pid = str(index)
        proxy(pid, 'sources', 'XMLPolyDataReader',
              {'FileName': [run / name], 'FileNameInfo': [run / name]})
        label = 'Germanium crystal | mm'
        if index > 1:
            c = rc.contacts(metadata)[index - 2]
            label = f"Electrode {c['id']} | {c['name']} | {c['potential_V']} V"
        ET.SubElement(collection, 'Item', id=pid, name=label)
        actor = proxy(str(index + 10), 'representations', 'GeometryRepresentation', {
            'Visibility': [1], 'Scale': [1 if index == 1 else 1.001] * 3,
            'Translation': [0, 0, 0 if index == 1 else -0.001],
            'Orientation': [0, 0, 0], 'Origin': [0, 0, 0],
            'DiffuseColor': [0.6] * 3, 'AmbientColor': [1] * 3, 'Opacity': [1],
            'Representation': ['Surface'], 'ColorArrayName': [''] * 5, 'Specular': [0.25]})
        prop = ET.SubElement(actor, 'Property', name='Input')
        ET.SubElement(prop, 'Proxy', value=pid)
    voltages = [c['potential_V'] for c in rc.contacts(metadata)]
    title = [metadata['id'] + ' ; Geometry',
             f'{max(voltages) - min(voltages):g} V ; 78 K ; dimensions in mm'] + [
        f"{'Orange' if c['id'] == metadata['readout_contact_id'] else 'Grey'}: "
        f"{c['name']} ({c['potential_V']:g} V)" for c in rc.contacts(metadata)]
    proxy('4', 'sources', 'TextSource', {'Text': ['\n'.join(title)]})
    ET.SubElement(collection, 'Item', id='4', name=metadata['id'] + ' | Geometry')
    proxy('20', 'views', 'RenderView', {
        'CameraPosition': [5, -8, 3], 'CameraFocalPoint': [0, 0, 1],
        'CameraViewUp': [0, 0, 1], 'CameraParallelScale': [3],
        'CameraParallelProjection': [1], 'CameraViewAngle': [30], 'ViewSize': [1200, 850]})
    layouts = ET.SubElement(state, 'ProxyCollection', name='layouts')
    ET.SubElement(layouts, 'Item', id='30', name='01 Geometry')
    return tree


class ContactTests(unittest.TestCase):
    def setUp(self):
        self.run = (rc.ROOT / 'fixture-run').resolve()
        self.tree = fixture(self.run)

    def styled(self, tree=None):
        # Pure XML tests use synthetic paths, without requiring native data.
        with patch.object(rc, 'checked_path', side_effect=lambda path, root, **kw: Path(path)):
            return rc.style_state(ET.tostring(tree if tree is not None else self.tree), self.run, item())

    def test_style_and_nonstyle_preservation(self):
        data, report = self.styled()
        before, after = self.tree, ET.fromstring(data)
        changed = []
        for old, new in zip(before.iter(), after.iter()):
            self.assertEqual(old.tag, new.tag)
            if old.attrib != new.attrib:
                changed.append((old, new))
                self.assertEqual(old.tag, 'Element')
        # One RGB component already equals the requested color.
        self.assertEqual(len(changed), 21)
        for index, name in enumerate(rc.MESHES, 11):
            actor = after.find(f".//Proxy[@id='{index}']")
            self.assertEqual([float(v) for v in rc.values(actor, 'DiffuseColor')], rc.STYLE[name]['rgb'])
            self.assertEqual([float(v) for v in rc.values(actor, 'Opacity')], [rc.STYLE[name]['opacity']])
        for old_proxy, new_proxy in zip(before.findall('.//Proxy[@id]'), after.findall('.//Proxy[@id]')):
            for old_prop, new_prop in zip(old_proxy.findall('Property'), new_proxy.findall('Property')):
                if old_prop.get('name') not in {'DiffuseColor', 'AmbientColor', 'Opacity', 'Text'}:
                    self.assertEqual(ET.tostring(old_prop), ET.tostring(new_prop))
        self.assertEqual(report['display_transforms']['contact_02.vtp']['Scale'], ['1.001'] * 3)
        self.assertEqual(report['display_transforms']['contact_02.vtp']['Translation'], ['0', '0', '-0.001'])
        self.assertEqual(report['legend'][:2], ['AK02 ; Geometry', '500 V ; 78 K ; dimensions in mm'])
        self.assertIn('Contact 2: Lithium Contact (500 V)', '\n'.join(report['legend']))
        self.assertEqual(len(report['legend']), 4)
        self.assertIn(rc.SURFACE_NOTE, contact_legend(item()))
        self.assertEqual(self.styled(), (data, report))

    def test_title_idempotence_and_strict_suffix(self):
        data, report = self.styled()
        self.assertEqual(self.styled(ET.fromstring(data)), (data, report))
        for suffix in ('\n', '\nExtra annotation', ' changed'):
            tree = ET.fromstring(data)
            value = tree.find(".//Proxy[@id='4']/Property[@name='Text']/Element")
            value.set('value', value.get('value') + suffix)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'title'):
                self.styled(tree)
        tree = copy.deepcopy(self.tree)
        value = tree.find(".//Proxy[@id='4']/Property[@name='Text']/Element")
        value.set('value', value.get('value').replace('Grey: Lithium Contact', 'Grey: invented contact'))
        with self.assertRaisesRegex(ValueError, 'title'):
            self.styled(tree)

    def test_historical_palette_validation(self):
        rc.validate_palette(rc.STYLE)
        for mutation in ('mesh', 'key', 'rgb', 'nan', 'infinity', 'negative', 'large', 'bool', 'label'):
            style = copy.deepcopy(rc.STYLE)
            entry = style['contact_01.vtp']
            if mutation == 'mesh':
                style['unexpected.vtp'] = entry
            elif mutation == 'key':
                entry['extra'] = 1
            elif mutation == 'rgb':
                entry['rgb'] = [0, 1]
            elif mutation == 'label':
                entry['color'] = 'Orange\n<script>'
            else:
                entry['opacity'] = {'nan': float('nan'), 'infinity': float('inf'),
                                    'negative': -0.1, 'large': 1.1, 'bool': True}[mutation]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                rc.validate_palette(style)

    def test_extra_pipeline_and_unregistered_readers_rejected(self):
        for kind in ('Clip', 'XMLRectilinearGridReader', 'ProgrammableSource', 'XMLPolyDataReader'):
            tree = copy.deepcopy(self.tree)
            ET.SubElement(tree.find('ServerManagerState'), 'Proxy', id='99', group='sources', type=kind)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'Unexpected unregistered'):
                self.styled(tree)

    def test_bad_scene_sources_and_titles(self):
        for name, replacement in [('FileName', 'fields.vtr'), ('FileName', 'contact_01.vtp'),
                                  ('FileNameInfo', 'other.vtp')]:
            tree = copy.deepcopy(self.tree)
            tree.find(f".//Proxy[@id='3']/Property[@name='{name}']/Element").set('value', str(self.run / replacement))
            with self.subTest(name=name, replacement=replacement), self.assertRaises(ValueError):
                self.styled(tree)
        tree = copy.deepcopy(self.tree)
        tree.find(".//Proxy[@id='4']/Property[@name='Text']/Element").set('value', 'SAP22 ; Geometry')
        with self.assertRaisesRegex(ValueError, 'title/model'):
            self.styled(tree)

    def test_hidden_changed_scale_and_camera_rejected(self):
        for pid, name, value in [('13', 'Visibility', '0'), ('13', 'Scale', '1.1'),
                                 ('20', 'CameraPosition', 'nan')]:
            tree = copy.deepcopy(self.tree)
            tree.find(f".//Proxy[@id='{pid}']/Property[@name='{name}']/Element").set('value', value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.styled(tree)

    def test_mesh_counts_nonempty(self):
        for points, cells, valid in [(5, 4, True), (0, 4, False), (5, 0, False)]:
            data = f'<VTKFile type="PolyData"><PolyData><Piece NumberOfPoints="{points}" NumberOfPolys="{cells}"/></PolyData></VTKFile>'.encode()
            with patch.object(Path, 'open', return_value=io.BytesIO(data)):
                if valid:
                    self.assertEqual(rc.mesh_counts(Path('mesh.vtp')), {'points': points, 'cells': cells})
                else:
                    with self.assertRaisesRegex(ValueError, 'Empty'):
                        rc.mesh_counts(Path('mesh.vtp'))

    def test_metadata_identity_and_hashes(self):
        canonical = item()
        fields = {'detector_id': 'AK02', 'source': copy.deepcopy(canonical)}
        sha = rc.ORIGINAL_HASHES['AK02']
        rc.validate_metadata('AK02', canonical, fields, sha)
        for target, key, value in [('top', 'detector_id', 'SAP22'), ('source', 'id', 'SAP22'),
                                    ('source', 'model_sha256', '0' * 64), ('source', 'contacts', [])]:
            changed = copy.deepcopy(fields)
            (changed if target == 'top' else changed['source'])[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                rc.validate_metadata('AK02', canonical, changed, sha)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            rc.validate_metadata('AK02', canonical, fields, '0' * 64)

    def test_contacts_and_signed_categorical_colors(self):
        canonical = item()
        canonical['contacts'][1]['potential_V'] = -500
        self.assertIn('(-500 V)', rc.contact_label(rc.contacts(canonical)[1]))
        html = contact_legend(canonical)
        self.assertIn('Cyan-blue', html)
        self.assertIn('(-500 V)', html)
        self.assertNotIn('p+', html)
        self.assertNotIn('n+', html)
        for bad in ([], [canonical['contacts'][0]] * 2,
                    [{'id': 1, 'name': 'x', 'potential_V': float('nan')}, canonical['contacts'][1]]):
            with self.assertRaises(ValueError):
                rc.contacts(dict(canonical, contacts=bad))

    def test_all_selection_and_gegi_skip(self):
        catalog = {name: dict(item(), id=name) for name in rc.ORIGINAL_HASHES}
        self.assertEqual(len(rc.select_detectors(catalog)), 16)
        self.assertNotIn(rc.SKIP, rc.select_detectors(catalog))
        for selection in ([], ['GeGI_3D'], ['AK02', 'AK02'], ['../AK02'], ['missing']):
            with self.assertRaises(ValueError):
                rc.select_detectors(catalog, selection)

    def test_output_existing_escape_reserved_and_links(self):
        for path in (rc.ROOT, rc.ROOT / 'docs', rc.ROOT / '.local',
                     rc.ROOT / '.local/../docs', rc.ROOT / '.local/autonomy/new',
                     rc.ROOT / '.local/site-build/new'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                rc.output_path(path)
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                rc.checked_path(self.run, rc.ROOT)
        with patch.object(rc, 'no_links'), patch.object(Path, 'exists', return_value=True):
            with self.assertRaisesRegex(ValueError, 'nonexistent'):
                rc.output_path(rc.ROOT / '.local/contact-test-output')
        with patch.object(Path, 'exists', return_value=True), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaisesRegex(ValueError, 'already exists'):
                rc.render(b'', {}, self.run, None)
            mkdir.assert_not_called()

    def test_canonical_catalog_and_html_links(self):
        catalog = rc.canonical_catalog()
        for ident in rc.select_detectors(catalog):
            html = adapt('<main><a href="old.csv">Old result</a></main>',
                         Path(f'detectors/{ident}/index.html'), catalog)
            self.assertIn('href="old.csv"', html)
            self.assertIn(f'../../models/{ident}.yaml', html)
            self.assertIn(f'../../downloads/{ident}.zip', html)
            self.assertIn('id="contact-legend"', html)
            for contact in rc.contacts(catalog[ident]):
                from html import escape
                self.assertIn(escape(rc.contact_label(contact)), html)
        gegi = adapt('<main>GeGI content</main>', Path('detectors/GeGI_3D/index.html'), catalog)
        self.assertNotIn('id="contact-legend"', gegi)
        self.assertIn('GeGI content', gegi)
        self.assertIn('supplement.html', gegi)
        home = adapt('<main></main>', Path('index.html'), catalog)
        self.assertIn('detectors/AK02/index.html#contact-legend', home)
        self.assertIn('downloads/all-models.zip', home)

    def test_legend_escapes_catalog_text(self):
        canonical = item()
        canonical['contacts'][0]['name'] = '<sensor & electrode>'
        self.assertIn('&lt;sensor &amp; electrode&gt;', contact_legend(canonical))
        self.assertNotIn('<sensor', contact_legend(canonical))


class ApplyTests(unittest.TestCase):
    """Disposable synthetic project; never applies to real native/preview data."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='contact-test-', dir=rc.ROOT / '.local')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.full_catalog = rc.canonical_catalog()
        canonical = self.full_catalog['AK02']
        self.catalog = {'AK02': canonical}
        self.mock_catalog = patch.object(rc, 'canonical_catalog', return_value=self.catalog)
        self.mock_catalog.start()
        self.addCleanup(self.mock_catalog.stop)
        for name in rc.TOOL_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((rc.ROOT / name).read_bytes())
        self.add_detector('AK02')
        self.run = rc.native_run(self.root, 'AK02')
        self.write_catalog()
        self.make_stage('stage')
        self.originals = {path.name: path.read_bytes() for path in self.run.iterdir()}

    def add_detector(self, ident):
        canonical = self.full_catalog[ident]
        self.catalog[ident] = canonical
        run = rc.native_run(self.root, ident)
        run.mkdir(parents=True)
        model = (rc.ROOT / 'models' / canonical['model']).read_bytes()
        for relative in ('models/' + canonical['model'], canonical['source']):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(model)
        (run / 'model.snapshot.yaml').write_bytes(model)
        fields = {'detector_id': ident, 'source': dict(canonical, model=str(self.root / canonical['source']))}
        (run / 'fields.json').write_bytes(rc.json_bytes(fields))
        mesh = b'<VTKFile type="PolyData"><PolyData><Piece NumberOfPoints="5" NumberOfPolys="4"/></PolyData></VTKFile>'
        for name in rc.MESHES:
            (run / name).write_bytes(mesh)
        (run / '01_geometry.pvsm').write_bytes(ET.tostring(fixture(run, canonical)))
        (run / '01_geometry.png').write_bytes(b'\x89PNG\r\n\x1a\noriginal-test-placeholder')

    def write_catalog(self):
        (self.root / 'models/catalog.json').write_bytes(rc.json_bytes({'detectors': list(self.catalog.values())}))

    def make_stage(self, name, ids=None):
        self.stage = self.root / '.local' / name
        rows = []
        for ident in sorted(self.catalog if ids is None else ids):
            state, row = rc.preflight(ident, self.catalog[ident], self.root)
            folder = self.stage / ident
            folder.mkdir(parents=True)
            (folder / '01_geometry.pvsm').write_bytes(state)
            (folder / '01_geometry.png').write_bytes(b'\x89PNG\r\n\x1a\nplaceholder-' + name.encode())
            row['outputs'] = {name: rc.sha256(folder / name) for name in rc.OUTPUTS}
            rows.append(row)
        self.report = {**rc.report_header(self.root), 'python': '3.12.7', 'paraview': '6.1.1', 'detectors': rows}
        self.save_report()

    def apply_all_baselines(self):
        for ident in sorted(set(self.full_catalog) - {'AK02', rc.SKIP}):
            self.add_detector(ident)
        self.write_catalog()
        self.make_stage('first-all')
        rc.apply_stage(self.stage, self.root)

    def native_bytes(self):
        return {f'{ident}/{name}': (rc.native_run(self.root, ident) / name).read_bytes()
                for ident in self.catalog for name in rc.OUTPUTS}

    def different_palette(self):
        style = copy.deepcopy(rc.STYLE)
        style['contact_01.vtp'].update(rgb=[0.8, 0.2, 0.1], color='Vermilion')
        style['contact_02.vtp'].update(rgb=[0.1, 0.3, 0.8], color='Azure')
        return style

    def save_report(self):
        (self.stage / 'inventory.json').write_bytes(rc.json_bytes(self.report))

    def assert_no_native_change(self):
        self.assertEqual({path.name: path.read_bytes() for path in self.run.iterdir()}, self.originals)
        self.assertFalse((self.root / rc.APPLIED).exists())

    def test_successful_two_file_apply_and_build_guard(self):
        result = rc.apply_stage(self.stage, self.root)
        self.assertEqual(result['status'], 'applied')
        changed = {path.name for path in self.run.iterdir() if path.read_bytes() != self.originals[path.name]}
        self.assertEqual(changed, set(rc.OUTPUTS))
        for name in rc.OUTPUTS:
            self.assertEqual((self.run / name).read_bytes(), (self.stage / 'AK02' / name).read_bytes())
        with zipfile.ZipFile(self.stage / 'originals.zip') as archive:
            expected = {(self.run / name).relative_to(self.root).as_posix() for name in rc.OUTPUTS}
            self.assertEqual(set(archive.namelist()), expected)
            for name in rc.OUTPUTS:
                self.assertEqual(archive.read((self.run / name).relative_to(self.root).as_posix()), self.originals[name])
        rc.verify_applied_style(self.root)
        with self.assertRaisesRegex(ValueError, 'already applied or attempted'):
            rc.apply_stage(self.stage, self.root)
        # A full-gallery reset or image-only overwrite must block the new color key.
        for name in rc.OUTPUTS:
            path = self.run / name
            styled = path.read_bytes()
            path.write_bytes(self.originals[name])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'color key cannot be published'):
                rc.verify_applied_style(self.root)
            path.write_bytes(styled)

    def test_source_mutation_rejected_before_writes(self):
        path = self.run / 'fields.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.originals[path.name] = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source/input'):
            rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()
        self.assertFalse((self.stage / 'originals.zip').exists())

    def test_native_png_edit_rejected_before_writes(self):
        path = self.run / '01_geometry.png'
        path.write_bytes(path.read_bytes() + b'edited')
        self.originals[path.name] = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source/input'):
            rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()
        self.assertFalse((self.stage / 'originals.zip').exists())

    def test_output_mutation_rejected_before_writes(self):
        path = self.stage / 'AK02/01_geometry.png'
        path.write_bytes(path.read_bytes() + b'edited')
        with self.assertRaisesRegex(ValueError, 'output hash changed'):
            rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()
        self.assertFalse((self.stage / 'originals.zip').exists())

    def test_rehashed_geometry_edit_rejected(self):
        path = self.stage / 'AK02/01_geometry.pvsm'
        tree = ET.fromstring(path.read_bytes())
        tree.find(".//Proxy[@id='20']/Property[@name='CameraPosition']/Element").set('value', '500')
        path.write_bytes(ET.tostring(tree))
        self.report['detectors'][0]['outputs'][path.name] = rc.sha256(path)
        self.save_report()
        with self.assertRaisesRegex(ValueError, 'more than approved styling'):
            rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()

    def test_unexpected_files_ids_paths_and_old_schema(self):
        extra = self.stage / 'extra.txt'
        extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'Unexpected or missing'):
            rc.apply_stage(self.stage, self.root)
        extra.unlink()
        original_report = copy.deepcopy(self.report)
        for mutation in ('duplicate', 'escape', 'old-schema'):
            self.report = copy.deepcopy(original_report)
            if mutation == 'duplicate':
                self.report['detectors'] *= 2
            elif mutation == 'escape':
                self.report['detectors'][0]['sources']['../../outside'] = '0' * 64
            else:
                self.report['schema_version'] = 2
            self.save_report()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                rc.apply_stage(self.stage, self.root)
            self.assert_no_native_change()
            self.assertFalse((self.stage / 'originals.zip').exists())

    def test_injected_mid_apply_rollback(self):
        replace = rc.atomic_replace
        calls = 0

        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('injected second-file failure')
            replace(path, data)

        with patch.object(rc, 'atomic_replace', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'All attempted display/index replacements restored'):
                rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()
        self.assertEqual(json.loads((self.stage / 'apply-receipt.json').read_bytes())['status'], 'rolled_back')
        self.assertTrue((self.stage / 'originals.zip').is_file())
        with self.assertRaisesRegex(ValueError, 'already applied or attempted'):
            rc.apply_stage(self.stage, self.root)

    def test_late_failure_restores_existing_applied_inventory(self):
        rc.apply_stage(self.stage, self.root)
        old_index = (self.root / rc.APPLIED).read_bytes()
        old_native = self.native_bytes()
        self.make_stage('late-failure')
        replace = rc.atomic_replace
        calls = 0

        def fail_receipt_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('injected final receipt failure')
            replace(path, data)

        with patch.object(rc, 'atomic_replace', side_effect=fail_receipt_once):
            with self.assertRaisesRegex(RuntimeError, 'replacements restored'):
                rc.apply_stage(self.stage, self.root)
        self.assertEqual(self.native_bytes(), old_native)
        self.assertEqual((self.root / rc.APPLIED).read_bytes(), old_index)
        with zipfile.ZipFile(self.stage / 'originals.zip') as archive:
            self.assertEqual(archive.read(rc.APPLIED), old_index)

    def test_apply_rejects_symlinks_before_writes(self):
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                rc.apply_stage(self.stage, self.root)
        self.assert_no_native_change()
        self.assertFalse((self.stage / 'originals.zip').exists())

    def test_fresh_same_style_restage_reapply(self):
        first_stage = self.stage
        rc.apply_stage(first_stage, self.root)
        first_receipt = (first_stage / 'apply-receipt.json').read_bytes()
        prior = (self.root / rc.APPLIED).read_bytes()
        self.make_stage('same-style-restage')
        self.assertEqual(self.report['prior_applied_sha256'], rc.digest(prior))
        self.assertEqual(set(self.report['provenance']), set(rc.TOOL_SOURCES))
        for name, sha in self.report['provenance'].items():
            self.assertEqual(sha, rc.sha256(self.root / name))
        receipt = rc.apply_stage(self.stage, self.root)
        self.assertFalse(receipt['upgrade_style'])
        self.assertEqual(receipt['schema_version'], 2)
        rc.verify_applied_style(self.root)
        with zipfile.ZipFile(self.stage / 'originals.zip') as archive:
            self.assertEqual(archive.read(rc.APPLIED), prior)
        self.assertEqual((first_stage / 'apply-receipt.json').read_bytes(), first_receipt)

    def test_rgb_label_upgrade_requires_flag_and_full_stage(self):
        self.apply_all_baselines()
        prior = (self.root / rc.APPLIED).read_bytes()
        old_native = self.native_bytes()
        old_style = copy.deepcopy(rc.STYLE)
        with patch.object(rc, 'STYLE', self.different_palette()):
            # Current publication stays strict while a new palette is previewed.
            with self.assertRaisesRegex(ValueError, 'Applied palette differs'):
                rc.verify_applied_style(self.root)
            self.make_stage('new-palette-preview', ['AK02'])
            self.assertIn('Vermilion', '\n'.join(self.report['detectors'][0]['legend']))
            self.assertEqual(self.native_bytes(), old_native)
            with self.assertRaisesRegex(ValueError, 'explicit --upgrade-style'):
                rc.apply_stage(self.stage, self.root)
            with self.assertRaisesRegex(ValueError, 'full 16-detector'):
                rc.apply_stage(self.stage, self.root, upgrade_style=True)
            self.assertFalse((self.stage / 'originals.zip').exists())
            self.make_stage('new-palette-all')
            with self.assertRaisesRegex(ValueError, 'explicit --upgrade-style'):
                rc.apply_stage(self.stage, self.root)
            self.assertFalse((self.stage / 'originals.zip').exists())
            receipt = rc.apply_stage(self.stage, self.root, upgrade_style=True)
            self.assertTrue(receipt['upgrade_style'])
            self.assertEqual(receipt['prior_style'], old_style)
            self.assertEqual(json.loads((self.root / rc.APPLIED).read_bytes())['style'], rc.STYLE)
            rc.verify_applied_style(self.root)
            for ident in self.catalog:
                tree = ET.fromstring((rc.native_run(self.root, ident) / '01_geometry.pvsm').read_bytes())
                self.assertEqual([float(v) for v in rc.values(tree.find(".//Proxy[@id='12']"), 'DiffuseColor')],
                                 rc.STYLE['contact_01.vtp']['rgb'])
                self.assertIn('Azure', rc.values(tree.find(".//Proxy[@id='4']"), 'Text')[0])
            with zipfile.ZipFile(self.stage / 'originals.zip') as archive:
                self.assertEqual(archive.read(rc.APPLIED), prior)

    def test_historical_title_requires_matching_prior_native_hashes(self):
        rc.apply_stage(self.stage, self.root)
        prior = (self.root / rc.APPLIED).read_bytes()
        with patch.object(rc, 'STYLE', self.different_palette()):
            # Without a verified ledger the former labels are not accepted.
            with patch.object(rc, 'read_applied', return_value=({}, None)):
                with self.assertRaisesRegex(ValueError, 'Unexpected geometry title'):
                    rc.preflight('AK02', self.catalog['AK02'], self.root)
            for name in rc.OUTPUTS:
                path = self.run / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Source changed'):
                    rc.preflight('AK02', self.catalog['AK02'], self.root)
                path.write_bytes(original)
            changed = json.loads(prior)
            entry = changed['detectors']['AK02']
            name = '01_geometry.png'
            entry['outputs'][name] = '0' * 64
            entry['sources'][(self.run / name).relative_to(self.root).as_posix()] = '0' * 64
            (self.root / rc.APPLIED).write_bytes(rc.json_bytes(changed))
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                rc.preflight('AK02', self.catalog['AK02'], self.root)
        # No apply was attempted; the original application's evidence remains.
        self.assertEqual(json.loads((self.stage / 'apply-receipt.json').read_bytes())['status'], 'applied')

    def test_populated_historical_ledger_rollback_after_index_replacement(self):
        self.apply_all_baselines()
        prior = (self.root / rc.APPLIED).read_bytes()
        old_native = self.native_bytes()
        replace = rc.atomic_replace
        calls = 0

        def fail_final_receipt_once(path, data):
            nonlocal calls
            calls += 1
            if calls == 2 * len(self.catalog) + 2:
                raise OSError('injected receipt failure after populated-ledger upgrade')
            replace(path, data)

        with patch.object(rc, 'STYLE', self.different_palette()):
            self.make_stage('upgrade-rollback')
            with patch.object(rc, 'atomic_replace', side_effect=fail_final_receipt_once):
                with self.assertRaisesRegex(RuntimeError, 'replacements restored'):
                    rc.apply_stage(self.stage, self.root, upgrade_style=True)
        self.assertEqual(self.native_bytes(), old_native)
        self.assertEqual((self.root / rc.APPLIED).read_bytes(), prior)
        rc.verify_applied_style(self.root)
        receipt = json.loads((self.stage / 'apply-receipt.json').read_bytes())
        self.assertEqual(receipt['status'], 'rolled_back')
        self.assertTrue(receipt['upgrade_style'])
        with zipfile.ZipFile(self.stage / 'originals.zip') as archive:
            self.assertEqual(archive.read(rc.APPLIED), prior)

    def test_tool_or_prior_ledger_edit_requires_restage(self):
        for name in rc.TOOL_SOURCES:
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n# changed after staging\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'schema 3'):
                rc.apply_stage(self.stage, self.root)
            path.write_bytes(original)
            self.assertFalse((self.stage / 'originals.zip').exists())
        rc.apply_stage(self.stage, self.root)
        self.make_stage('ledger-hash-check')
        path = self.root / rc.APPLIED
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'schema 3'):
            rc.apply_stage(self.stage, self.root)
        self.assertFalse((self.stage / 'originals.zip').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
