"""Saved GeGI display contracts; no science, image mutation, or site build."""
import copy
import csv
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import saved_plot_repairs as R

ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://www.w3.org/2000/svg'}
ORIGINALS = (R.BASE + '03_strip_channels.png',
             R.BASE + 'comparisons/08_strip_position.png',
             R.BASE + 'comparisons/08_strip_position.svg')


class SavedPlotRepairsTests(unittest.TestCase):
    def setUp(self):
        fixture_root = ROOT / '.local/student-site-audit-v1/repair-test'
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='saved-plot-', dir=fixture_root)
        self.site = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for rel in tuple(R.INPUT_HASHES) + ORIGINALS:
            target = self.site / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'docs' / rel, target)
        self.before = {rel: (self.site / rel).read_bytes() for rel in tuple(R.INPUT_HASHES) + ORIGINALS}

    def test_saved_channel_values_selection_signs_and_complete_grids(self):
        expected = {
            'strip_gap_sharing': (198, 98.5, ['X08', 'X09', 'Y08', 'Y09', 'Y10']),
            'three_spread': (289, 144.0, ['X06', 'X07', 'X10', 'X14', 'Y04', 'Y05', 'Y11', 'Y15']),
        }
        specs = R.channel_specifications(self.site)
        for spec in specs:
            event = spec['event']
            with (self.site / (R.BASE + f'events/{event}/channels.csv')).open(newline='') as source:
                rows = list(csv.DictReader(source))
            samples, end, selected = expected[event]
            self.assertEqual((len(spec['time_ns']), spec['time_ns'][-1], list(spec['channels'])),
                             (samples, end, selected))
            self.assertEqual(spec['time_ns'], [float(row['time_ns']) for row in rows])
            for name, values in spec['channels'].items():
                self.assertEqual(values, [float(row[name]) for row in rows])
                self.assertEqual(len(values), samples)
            self.assertTrue(any(v < 0 for v in spec['channels']['Y09' if event == 'strip_gap_sharing' else 'Y11']))
            self.assertEqual(spec['time_ns'][0], 0.0)
        tree = ET.fromstring(R.channels_svg(specs))
        data = json.loads(tree.find('s:metadata', NS).text)
        self.assertEqual(data['plots'], specs)
        for panel, spec in zip(tree.findall('s:g', NS), specs):
            paths = panel.findall("s:path[@class='trace']", NS)
            self.assertEqual([p.attrib['data-channel'] for p in paths], list(spec['channels']))
            self.assertTrue(all(len(re.findall('[ML]', p.attrib['d'])) == len(spec['time_ns']) for p in paths))

    def test_position_matches_public_truth_and_original_max_abs_final_rule(self):
        rows = R.position_specification(self.site)
        expected = {
            'random_10': ([41.352491825819016, -9.142025373876095], [-37.03110468189838, -37.03110468189838], ['X01', 'Y01']),
            'random_12': ([-41.90399497747421, 10.000617243349552], [-37.03110468189838, -37.03110468189838], ['X01', 'Y01']),
            'random_05': ([11.827326379716396, -39.35828059911728], [12.343701560632795, -37.03110468189838], ['X11', 'Y01']),
            'random_07': ([-11.692948639392853, 33.34851190447807], [-12.343701560632791, 32.093624057645265], ['X06', 'Y15']),
        }
        # Independent CSV/catalog reconstruction preserves zero ties in catalog order.
        catalog = json.loads((self.site / 'models/catalog.json').read_text())
        contacts = next(d for d in catalog['detectors'] if d['id'] == 'GeGI_3D')['contacts']
        for row in rows:
            self.assertEqual((row['truth_xy_mm'], row['estimate_xy_mm'], row['strips']), expected[row['event']])
            with (self.site / (R.BASE + f'events/{row["event"]}/channels.csv')).open(newline='') as source:
                final = list(csv.DictReader(source))[-1]
            for axis, face in enumerate(('X', 'Y')):
                choices = [c for c in contacts if c['name'].startswith(face) and 'guard' not in c['name']]
                strongest = sorted(choices, key=lambda c: abs(float(final[c['name']])), reverse=True)[0]
                self.assertEqual(row['strips'][axis], strongest['name'])
                bounds = strongest['bounds_mm']
                self.assertEqual(row['estimate_xy_mm'][axis], (bounds[2 * axis] + bounds[2 * axis + 1]) / 2)
        self.assertEqual(rows[0]['zero_signal_tie'], [True, True])
        self.assertEqual(rows[1]['zero_signal_tie'], [True, True])
        self.assertEqual(rows[2]['selected_final_signed_signal'][1] < 0, True)

    def test_legends_are_complete_outside_axes_and_inside_viewbox(self):
        tree = ET.fromstring(R.channels_svg(R.channel_specifications(self.site)))
        for group, count in zip(tree.findall('s:g', NS), (5, 8)):
            legends = group.findall("s:g[@class='channel-legend']", NS)
            self.assertEqual(len(legends), count)
            for legend in legends:
                label = legend.find('s:text', NS)
                self.assertEqual(label.text, legend.attrib['data-channel'])
                self.assertGreater(float(label.attrib['x']), 720)
                self.assertLess(float(label.attrib['x']) + 70, 1040)
                self.assertTrue(15 < float(label.attrib['y']) < 770)
        text = ''.join(tree.itertext())
        self.assertIn('Signed induced-charge fraction (dimensionless)', text)
        self.assertEqual(text.count('Time (ns)'), 2)
        self.assertNotIn('clipPath', ET.tostring(tree, encoding='unicode'))
        for group in tree.findall('s:g', NS):
            ticks = [e for e in group.findall('s:text', NS) if e.attrib.get('x') == '84']
            zero = next(e for e in ticks if e.text == '0')
            self.assertTrue(all(e is zero or abs(float(e.attrib['y']) - float(zero.attrib['y'])) >= 22 for e in ticks))

    def test_position_notes_are_outside_axes_and_coincident_ids_separate(self):
        rows = R.position_specification(self.site)
        tree = ET.fromstring(R.position_svg(rows))
        notes = [e for e in tree.findall('s:text', NS) if e.text == R.POSITION_NOTE]
        self.assertEqual(len(notes), 1)
        self.assertLess(float(notes[0].attrib['y']), 125)
        markers = tree.findall("s:g/s:path[@class='estimate-marker']", NS)
        self.assertEqual(markers[0].attrib['d'], markers[1].attrib['d'])
        labels = tree.findall("s:g/s:text[@class='estimate-label']", NS)
        self.assertEqual([label.text for label in labels], ['10 estimate', '12 estimate', '05 estimate', '07 estimate'])
        self.assertGreaterEqual(abs(float(labels[0].attrib['y']) - float(labels[1].attrib['y'])), 25)
        self.assertEqual(json.loads(tree.find('s:metadata', NS).text)['events'], rows)
        self.assertEqual(len(tree.findall("s:g/s:circle[@class='truth-marker']", NS)), 4)
        self.assertIn('Their non-guard final signals are zero.', ''.join(tree.itertext()))
        truth_labels = tree.findall("s:g/s:text[@class='truth-label']", NS)
        for estimate, truth in zip(labels, truth_labels):
            self.assertGreater(abs(float(estimate.attrib['y']) - float(truth.attrib['y'])), 20)

    def test_exact_source_input_preservation_and_minimal_outputs(self):
        manifest = R.assemble(self.site)
        self.assertEqual(R.validate(self.site), manifest)
        self.assertEqual(self.before, {rel: (self.site / rel).read_bytes() for rel in self.before})
        actual = {p.relative_to(self.site).as_posix() for p in self.site.rglob('*') if p.is_file()}
        self.assertEqual(actual, set(self.before) | set(R.PLOTS) | {R.MANIFEST})
        self.assertEqual(manifest['generator'], {R.GENERATOR: R.sha(ROOT / R.GENERATOR)})
        self.assertEqual(manifest['inputs'], R.INPUT_HASHES)

    def test_repeated_assembly_preserves_output_bytes_and_mtimes(self):
        R.assemble(self.site)
        before = {rel: ((self.site / rel).read_bytes(), (self.site / rel).stat().st_mtime_ns)
                  for rel in (*R.PLOTS, R.MANIFEST)}
        R.assemble(self.site)
        self.assertEqual(before, {rel: ((self.site / rel).read_bytes(), (self.site / rel).stat().st_mtime_ns)
                                 for rel in before})

    def test_rehashed_svg_edit_is_rejected_without_overwrite(self):
        R.assemble(self.site)
        path = self.site / R.PLOTS[0]
        path.write_bytes(path.read_bytes().replace(b'Time (ns)', b'Time (us)', 1))
        manifest_path = self.site / R.MANIFEST
        manifest = json.loads(manifest_path.read_text())
        manifest['outputs'][R.PLOTS[0]]['sha256'] = R.sha(path)
        manifest_path.write_text(json.dumps(manifest))
        before = {rel: (self.site / rel).read_bytes() for rel in (*R.PLOTS, R.MANIFEST)}
        with self.assertRaisesRegex(ValueError, 'rendered display differs'):
            R.validate(self.site)
        with self.assertRaisesRegex(ValueError, 'Unexpected managed'):
            R.assemble(self.site)
        self.assertEqual(before, {rel: (self.site / rel).read_bytes() for rel in before})

    def test_rehashed_input_edit_is_rejected_before_any_writes(self):
        R.assemble(self.site)
        rel = R.BASE + 'events/random_10/channels.csv'
        path = self.site / rel
        path.write_bytes(path.read_bytes().replace(b'0.0,0.0', b'0.0,0.1', 1))
        manifest_path = self.site / R.MANIFEST
        manifest = json.loads(manifest_path.read_text())
        manifest['inputs'][rel] = R.sha(path)
        manifest_path.write_text(json.dumps(manifest))
        before = {rel: (self.site / rel).read_bytes() for rel in (*R.PLOTS, R.MANIFEST)}
        for operation in (R.validate, R.assemble):
            with self.assertRaisesRegex(ValueError, 'differs from pinned original'):
                operation(self.site)
        self.assertEqual(before, {rel: (self.site / rel).read_bytes() for rel in before})

    def test_rehashed_manifest_position_or_rule_edit_is_rejected(self):
        R.assemble(self.site)
        path = self.site / R.MANIFEST
        original = path.read_bytes()
        for part in ('position', 'rule'):
            manifest = json.loads(original)
            if part == 'position':
                manifest['position_events'][0]['estimate_xy_mm'][0] += 1
            else:
                manifest['rules']['position'] = 'Changed tie-breaking rule'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'manifest differs'):
                R.validate(self.site)
        path.write_bytes(original)
        R.validate(self.site)

    def test_source_change_after_import_rejected_before_writes(self):
        with patch.object(R, 'SOURCE_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'source changed after import'):
                R.assemble(self.site)
        self.assertFalse((self.site / R.DISPLAY).exists())

    def test_selection_thresholds_ties_and_signed_channels(self):
        channels = {'Y01': [0, -.01], 'X01': [0, .01], 'X02': [.02, 0],
                    'Y02': [-.02, 0], 'X03': [.02, 0], 'Y03': [.0199, 0]}
        before = copy.deepcopy(channels)
        self.assertEqual(R.selected_channels(channels), ['X01', 'X02', 'Y01', 'Y02'])
        self.assertEqual(channels, before)

    def test_gallery_repair_preserves_original_routes_and_is_idempotent(self):
        text = (ROOT / 'docs/detectors/GeGI_3D/gallery.html').read_text(encoding='utf-8')
        patched = R.patch_gallery(text)
        self.assertEqual(R.patch_gallery(patched), patched)
        for original in ORIGINALS[:2]:
            route = original.removeprefix('detectors/GeGI_3D/')
            self.assertIn(f'href="{route}"', patched)
            self.assertNotIn(f'src="{route}"', patched)
        for route in ('display/03_strip_channels.svg', 'display/08_strip_position.svg'):
            self.assertIn(f'src="{route}"', patched)
            self.assertIn(f'href="{route}"', patched)
        old_images = re.findall(r'<img\b[^>]*>', text)
        unaffected = [tag for tag in old_images if not any(rel.removeprefix('detectors/GeGI_3D/') in tag for rel in ORIGINALS)]
        self.assertTrue(all(tag in patched for tag in unaffected))


if __name__ == '__main__':
    unittest.main()
