"""Two GeGI display repairs derived only from pinned public CSV/catalog data.

No simulation, original image editing, channel resampling, or position fitting.
The retained rules are strip_events.py:selected_channels and analyze_strips.py
lines 41-47 in Additional_Simulations/Visualization_3D/paraview/.
"""
from __future__ import annotations

import colorsys
import csv
import hashlib
import html
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 'detectors/GeGI_3D/runs/20260922_suite_v3/'
DISPLAY = 'detectors/GeGI_3D/display/'
MANIFEST = DISPLAY + 'manifest.json'
GENERATOR = 'tools/saved_plot_repairs.py'
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CHANNEL_EVENTS = ('strip_gap_sharing', 'three_spread')
POSITION_EVENTS = ('random_10', 'random_12', 'random_05', 'random_07')
CHANNEL_NAMES = tuple([f'X{i:02d}' for i in range(1, 17)] + ['X_guard'] +
                      [f'Y{i:02d}' for i in range(1, 17)] + ['Y_guard'])
INPUT_HASHES = {
    'models/catalog.json': 'ac5edd4c976a37cfcc80a8e507ac9347246a942ac843ed2ecc683079f220653b',
    BASE + 'comparisons/event_summary.csv': 'c5fd6d6ca945d12fdc803c4c4d51677bcf0da63d0507154e1e4c94918fb0f601',
    BASE + 'events/strip_gap_sharing/channels.csv': '41b0e5cac6aa11feb6a22f9c318d903f7c0f05a0c2a0ed3c37e09bfeee053add',
    BASE + 'events/three_spread/channels.csv': 'e4993287ab64ed7b713bd2a2c0f6d1fcf8dfe2f50d820fa4bb6c40cb69bbb58d',
    BASE + 'events/random_10/channels.csv': 'b821763109e7382bcd55ca031e43a99bc537633ba25915a7049306279fb9e32f',
    BASE + 'events/random_12/channels.csv': '94031ecd5c0d73e3d3e850f99e15ae631c2333696b182555f020a3f4de948b90',
    BASE + 'events/random_05/channels.csv': 'd233333bebcbec90766bac337cbdbdf22cd4b84dfb3cb2cb8119a7c807675834',
    BASE + 'events/random_07/channels.csv': '0e96abc671e0092748f839bcc8bb8a8c01a604075d6583561b498edc7132757e',
}
CHANNEL_RULE = 'All final |signal| >= 0.01 plus up to two strongest nonfinal channels with peak |signal| >= 0.02; original order breaks ties.'
POSITION_RULE = 'Strongest absolute final non-guard X and Y signals; original contact order breaks ties, including all-zero ties; use catalog contact-bound centres.'
POSITION_NOTE = 'Uncalibrated strip illustration: max-|signal| strip × pitch, not a calibrated position fit'
PLOTS = (DISPLAY + '03_strip_channels.svg', DISPLAY + '08_strip_position.svg')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def require_inputs(site):
    require(sha(ROOT / GENERATOR) == SOURCE_SHA256,
            'Saved plot repair source changed after import; restart with frozen source')
    for rel, expected in INPUT_HASHES.items():
        require((site / rel).is_file() and sha(site / rel) == expected,
                'Saved plot repair input differs from pinned original: ' + rel)


def channel_data(site, event):
    path = site / (BASE + f'events/{event}/channels.csv')
    with path.open(encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source)
        require(reader.fieldnames == ['time_ns', *CHANNEL_NAMES], 'GeGI channel order differs')
        rows = list(reader)
    require(len(rows) >= 2, 'Missing saved GeGI channel samples')
    time = [float(row['time_ns']) for row in rows]
    channels = {name: [float(row[name]) for row in rows] for name in CHANNEL_NAMES}
    require(all(math.isfinite(v) for v in time) and all(a < b for a, b in zip(time, time[1:])),
            'Invalid saved GeGI time grid')
    require(all(math.isfinite(v) for values in channels.values() for v in values),
            'Nonfinite saved GeGI signal')
    return time, channels


def selected_channels(channels):
    """Exactly the original selection, including stable transient-tie ordering."""
    final = [name for name, values in channels.items() if abs(values[-1]) >= .01]
    neighbours = sorted((name for name, values in channels.items()
                         if name not in final and max(map(abs, values)) >= .02),
                        key=lambda name: max(map(abs, channels[name])), reverse=True)[:2]
    return sorted(final + neighbours)


def channel_specifications(site):
    result = []
    for event in CHANNEL_EVENTS:
        time, channels = channel_data(site, event)
        selected = selected_channels(channels)
        result.append({'event': event, 'time_ns': time,
                       'channels': {name: channels[name] for name in selected}})
    return result


def position_specification(site):
    catalog = json.loads((site / 'models/catalog.json').read_text(encoding='utf-8'))
    detectors = [d for d in catalog['detectors'] if d['id'] == 'GeGI_3D']
    require(len(detectors) == 1, 'GeGI model catalog entry differs')
    contacts = detectors[0]['contacts']
    require([c['name'] for c in contacts] == list(CHANNEL_NAMES), 'GeGI contact order differs')
    with (site / (BASE + 'comparisons/event_summary.csv')).open(encoding='utf-8', newline='') as source:
        summary = list(csv.DictReader(source))
    result = []
    for event in POSITION_EVENTS:
        rows = [row for row in summary if row['event'] == event]
        require(len(rows) == 1, 'Missing or duplicate GeGI truth position: ' + event)
        truth = [float(rows[0]['first_x_mm']), float(rows[0]['first_y_mm'])]
        _, channels = channel_data(site, event)
        chosen, centre, final = [], [], []
        for axis, face in enumerate(('X', 'Y')):
            candidates = [c for c in contacts if c['name'].startswith(face) and 'guard' not in c['name']]
            contact = max(candidates, key=lambda c: abs(channels[c['name']][-1]))
            bounds = contact['bounds_mm']
            chosen.append(contact['name'])
            centre.append((bounds[axis * 2] + bounds[axis * 2 + 1]) / 2)
            final.append(channels[contact['name']][-1])
        require(all(math.isfinite(v) for v in truth + centre + final), 'Invalid GeGI position values')
        result.append({'event': event, 'truth_xy_mm': truth, 'estimate_xy_mm': centre,
                       'strips': chosen, 'selected_final_signed_signal': final,
                       'zero_signal_tie': [value == 0 for value in final]})
    return result


def svg_start(title, width, height, metadata):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="plot-title plot-desc">',
            f'<title id="plot-title">{html.escape(title)}</title>',
            '<desc id="plot-desc">Saved numerical data, unchanged signs and original sample times. Legends and explanatory notes sit outside the axes.</desc>',
            '<style>text{font-family:Arial,sans-serif;fill:#173047;font-size:17px}.grid{stroke:#e1e6eb;stroke-width:1}.axis{stroke:#536575;stroke-width:1.2;fill:none}.trace{fill:none;stroke-width:2;stroke-linejoin:round}</style>',
            '<rect width="100%" height="100%" fill="white"/>',
            '<metadata id="saved-plot-data">' + html.escape(canonical(metadata)) + '</metadata>',
            f'<text x="30" y="34" style="font-size:24px;font-weight:bold">{html.escape(title)}</text>']


def color(name):
    """Original strip hue rule, with no dependency on ParaView or numpy."""
    index = int(name[1:]) if name[1:].isdigit() else 0
    hue = (index * .61803398875 + (0 if name.startswith('X') else .35)) % 1
    rgb = colorsys.hls_to_rgb(hue, .40 + .07 * (index % 2), .72)
    return '#' + ''.join(f'{round(v * 255):02x}' for v in rgb)


def channels_svg(specs):
    out = svg_start('GeGI · complete saved strip-channel legends', 1040, 790,
                    {'selection_rule': CHANNEL_RULE, 'plots': specs})
    out.append('<text x="30" y="64">Signed induced-charge fraction (dimensionless) · all selected samples retained</text>')
    for panel, spec in enumerate(specs):
        top, bottom = (118, 304) if panel == 0 else (430, 616)
        left, right = 94, 720
        time, channels = spec['time_ns'], spec['channels']
        values = [v for channel in channels.values() for v in channel] + [0.0]
        lower, upper = min(values), max(values)
        pad = max((upper - lower) * .08, .02)
        lower, upper = lower - pad, upper + pad
        x = lambda v: left + (right - left) * (v - time[0]) / (time[-1] - time[0])
        y = lambda v: bottom - (bottom - top) * (v - lower) / (upper - lower)
        title = 'Gap sharing' if panel == 0 else 'Three-site response'
        out.append(f'<g id="{spec["event"]}"><text x="94" y="{top - 22}" style="font-size:20px;font-weight:bold">{title} · {len(time)} saved samples</text>')
        for i in range(5):
            value = lower + (upper - lower) * i / 4
            if abs(y(value) - y(0)) < 22:
                continue  # The explicit exact-zero label has priority over nearby ticks.
            out.append(f'<path class="grid" d="M{left},{y(value):.6f}H{right}"/><text x="84" y="{y(value) + 5:.6f}" text-anchor="end">{value:.3g}</text>')
        for i in range(6):
            value = time[0] + (time[-1] - time[0]) * i / 5
            out.append(f'<path class="grid" d="M{x(value):.6f},{top}V{bottom}"/><text x="{x(value):.6f}" y="{bottom + 25}" text-anchor="middle">{value:.4g}</text>')
        out.append(f'<path class="axis" d="M{left},{top}V{bottom}H{right}"/><path d="M{left},{y(0):.6f}H{right}" stroke="#718391" stroke-width="1.2"/>')
        out.append(f'<text x="84" y="{y(0) + 5:.6f}" text-anchor="end" style="font-weight:bold">0</text><text x="407" y="{bottom + 52}" text-anchor="middle">Time (ns)</text>')
        out.append(f'<text x="25" y="{(top + bottom) / 2}" text-anchor="middle" transform="rotate(-90 25 {(top + bottom) / 2})">Signed charge fraction</text>')
        out.append(f'<text x="756" y="{top - 2}" style="font-weight:bold">Selected channels</text>')
        for index, (name, signal) in enumerate(channels.items()):
            path = ' '.join(('M' if i == 0 else 'L') + f'{x(t):.6f},{y(v):.6f}' for i, (t, v) in enumerate(zip(time, signal)))
            ink = color(name)
            out.append(f'<path class="trace" data-channel="{name}" d="{path}" stroke="{ink}"><title>{name}: {len(signal)} original signed samples</title></path>')
            row = top + 25 + index * 27
            out.append(f'<g class="channel-legend" data-channel="{name}"><path d="M756,{row - 5}H789" stroke="{ink}" stroke-width="3"/><text x="800" y="{row}">{name}</text></g>')
        out.append('</g>')
    out.append('<text x="30" y="719">Selection: final |signal| ≥ 0.01 plus up to two strongest transient neighbours ≥ 0.02.</text>')
    out.append('<text x="30" y="748">Original time windows end at 98.5 ns and 144 ns; no display hold, resampling or sign reversal.</text>')
    out.append('<text x="30" y="776">Saved synthetic SSD examples; weighting-field images remain available in the original composite.</text></svg>')
    return ''.join(out)


def position_svg(rows):
    out = svg_start('GeGI · truth position and saved strip estimate', 1060, 760,
                    {'position_rule': POSITION_RULE, 'note': POSITION_NOTE, 'events': rows})
    out.append(f'<text x="30" y="69" style="font-size:18px">{html.escape(POSITION_NOTE)}</text>')
    out.append('<text x="30" y="96">Synthetic single-site examples · truth and estimate are distinct quantities</text>')
    left, right, top, bottom = 94, 624, 125, 655
    x = lambda v: left + (right - left) * (v + 50) / 100
    y = lambda v: bottom - (bottom - top) * (v + 50) / 100
    for value in range(-50, 51, 10):
        out.append(f'<path class="grid" d="M{x(value):.6f},{top}V{bottom} M{left},{y(value):.6f}H{right}"/>')
        out.append(f'<text x="{x(value):.6f}" y="682" text-anchor="middle">{value}</text><text x="84" y="{y(value) + 5:.6f}" text-anchor="end">{value}</text>')
    out.append(f'<path class="axis" d="M{left},{top}V{bottom}H{right}V{top}Z"/>')
    out.append('<text x="359" y="712" text-anchor="middle">x (mm)</text><text x="30" y="390" text-anchor="middle" transform="rotate(-90 30 390)">y (mm)</text>')
    groups = {}
    for row in rows:
        groups.setdefault(tuple(row['estimate_xy_mm']), []).append(row['event'])
    for row in rows:
        label = row['event'].split('_')[1]
        tx, ty = map(float, row['truth_xy_mm'])
        ex, ey = map(float, row['estimate_xy_mm'])
        out.append(f'<g data-event="{row["event"]}"><path d="M{x(tx):.6f},{y(ty):.6f}L{x(ex):.6f},{y(ey):.6f}" stroke="#a5b1bd" stroke-width="1.4"/>')
        out.append(f'<circle class="truth-marker" cx="{x(tx):.6f}" cy="{y(ty):.6f}" r="5" fill="#216aaf"/><text class="truth-label" x="{x(tx) + (10 if tx < 35 else -12):.6f}" y="{y(ty) - 16:.6f}" text-anchor="{"start" if tx < 35 else "end"}">{label} truth</text>')
        out.append(f'<path class="estimate-marker" d="M{x(ex) - 6:.6f},{y(ey) - 6:.6f}l12,12 M{x(ex) - 6:.6f},{y(ey) + 6:.6f}l12,-12" stroke="#d9573d" stroke-width="2.5"/>')
        stack = groups[(ex, ey)].index(row['event'])
        label_y = y(ey) + 26 + 25 * stack
        out.append(f'<path class="estimate-label-leader" d="M{x(ex) + 7:.6f},{y(ey):.6f}L{x(ex) + 17:.6f},{label_y - 5:.6f}" stroke="#d9573d"/><text class="estimate-label" x="{x(ex) + 22:.6f}" y="{label_y:.6f}">{label} estimate</text></g>')
    out.append('<circle cx="704" cy="148" r="5" fill="#216aaf"/><text x="723" y="154">Truth: saved deposition position</text>')
    out.append('<path d="M698,181l12,12 M698,193l12,-12" stroke="#d9573d" stroke-width="2.5"/><text x="723" y="193">Saved strongest-strip estimate</text>')
    out.append('<text x="704" y="237">Estimate rule: strongest |final signal|</text><text x="704" y="263">on each non-guard X/Y face; catalog</text><text x="704" y="289">contact-bound centres retain the pitch.</text>')
    out.append('<text x="704" y="332" style="font-weight:bold">Events 10 and 12 coincide</text><text x="704" y="358">Their non-guard final signals are zero.</text><text x="704" y="384">The original tie rule selects X01/Y01.</text><text x="704" y="410">Separate labels show both event IDs.</text>')
    out.append('<text x="30" y="744" style="font-size:14px">No radiation transport or calibrated reconstruction is inferred; guard collection and zero-signal ties remain unchanged.</text></svg>')
    return ''.join(out)


def expected_bundle(site):
    require_inputs(site)
    channels, positions = channel_specifications(site), position_specification(site)
    outputs = {PLOTS[0]: channels_svg(channels).encode('utf-8'),
               PLOTS[1]: position_svg(positions).encode('utf-8')}
    manifest = {'schema_version': 1, 'kind': 'saved-data-display-repairs',
                'generator': {GENERATOR: SOURCE_SHA256}, 'inputs': INPUT_HASHES,
                'rules': {'channels': CHANNEL_RULE, 'position': POSITION_RULE},
                'outputs': {rel: {'sha256': hashlib.sha256(data).hexdigest()} for rel, data in outputs.items()},
                'channel_plots': [{'event': s['event'], 'samples': len(s['time_ns']),
                                   'time_range_ns': [s['time_ns'][0], s['time_ns'][-1]],
                                   'selected_channels': list(s['channels'])} for s in channels],
                'position_events': positions,
                'limitation': POSITION_NOTE}
    return outputs, manifest


def validate(site):
    """Rebuild expected bytes from pinned inputs; rehashed edits cannot pass."""
    site = Path(site)
    outputs, manifest = expected_bundle(site)
    for rel, data in outputs.items():
        require((site / rel).is_file() and (site / rel).read_bytes() == data,
                'Saved plot repair rendered display differs: ' + rel)
    require((site / MANIFEST).is_file(), 'Saved plot repair manifest missing')
    require(json.loads((site / MANIFEST).read_text(encoding='utf-8')) == manifest,
            'Saved plot repair manifest differs from source/data-bound expectation')
    return manifest


def assemble(site):
    """Create only new derived SVGs/manifest, refusing unexpected managed edits."""
    site = Path(site)
    outputs, manifest = expected_bundle(site)
    outputs[MANIFEST] = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    for rel, data in outputs.items():
        require(not (site / rel).exists() or (site / rel).read_bytes() == data,
                'Unexpected managed saved plot repair edit: ' + rel)
    for rel, data in outputs.items():
        path = site / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return validate(site)


def patch_gallery(text):
    """Replace the two gallery image routes; retain explicit original-image links.

    The caller owns reading/writing gallery.html. This function reads no files.
    """
    for original, derived in (('runs/20260922_suite_v3/03_strip_channels.png', 'display/03_strip_channels.svg'),
                              ('runs/20260922_suite_v3/comparisons/08_strip_position.png', 'display/08_strip_position.svg')):
        if f'src="{derived}"' in text:
            require(text.count(f'src="{derived}"') == 1 and f'href="{original}"' in text,
                    'Saved plot gallery repair inventory differs')
            continue
        require(text.count(f'src="{original}"') == 1 and text.count(f'href="{original}"') in (0, 1),
                'Original GeGI gallery image inventory differs: ' + original)
        match = re.search(r'<img\b[^>]*\bsrc="' + re.escape(original) + r'"[^>]*>', text)
        require(match is not None, 'Original GeGI gallery image tag differs')
        image = match.group(0)
        target = image
        if f'href="{original}"' in text:
            target = f'<a href="{original}">{image}</a>'
            require(text.count(target) == 1, 'Original GeGI image wrapper differs')
        replacement = f'<a href="{derived}">' + image.replace(f'src="{original}"', f'src="{derived}"') + '</a>'
        label = 'Original field/channel composite (PNG)' if original.endswith('/03_strip_channels.png') else 'Original position illustration (PNG)'
        addition = f'<p><a href="{original}">{label}</a> · <a href="display/manifest.json">Saved-data display provenance</a></p>'
        text = text.replace(target, replacement + addition, 1)
    return text
