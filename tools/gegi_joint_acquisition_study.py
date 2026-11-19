"""Fit two-strip ADC windows, with optional scoring against saved transport."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from time import perf_counter

from gegi_event_store import encoded, sha
import gegi_joint_calibration as portable


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / '.local/gegi-dual-source/cs37k-co37k-250ms-depth/report.json'
WINDOWS = ROOT / '.local/gegi-joint-two-site/cs37k-co37k-250ms-adc.npz'
REFERENCE = ROOT / '.local/gegi-continuous-pairing/study.json'
REFERENCE_SHA = '62c56967d2ea05984d0f94dff818acd0fd71361aa950086eea748167e0352735'
DEFAULT_REFERENCE = object()


def compare(positions, targets):
    from gegi_two_site_cfd_study import angle_error, axis_between

    return dict(depth_errors_mm=[a[2] - b[2] for a, b in zip(positions, targets, strict=True)],
                transverse_errors_mm=[math.dist(a[:2], b[:2]) for a, b in zip(positions, targets, strict=True)],
                axis_error_deg=angle_error(axis_between(*positions), axis_between(*targets)))


def scores(fitted, reference, geometry):
    match = reference['comparison']
    if match is None or not fitted['energy_compatible'] or fitted['index'] != match.get('truth_pairing_index'):
        return None
    sites = {tuple(s['cell']): s for s in reference['reference']['sites_in_birth_order']}
    cells = fitted['cells']
    centers = [[geometry[x]['strip_center_mm'], geometry[y]['strip_center_mm'], 0.] for x, y in cells]
    predictions = {'strip_centers_z0': centers}
    depths = fitted['apparent_depths_mm']
    if len(depths) == len(cells) and all(z is not None for z in depths):
        predictions['strip_centers_cfd'] = [xy[:2] + [z] for xy, z in zip(centers, depths)]
    for mode, models in fitted['fit'].get('fits', {}).items():
        for name, model in models.items():
            if model['optimizer_success']:
                predictions[f'{mode}_{name}'] = model['positions_mm']
    return {label: {method: compare(pos, [sites[tuple(cell)][coordinate] for cell in cells])
                    for method, pos in predictions.items()}
            for label, coordinate in [('charge_centroid', 'deposit_centroid_mm'), ('interaction_birth', 'birth_position_mm')]}


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        for pairing in row['pairings']:
            for target, methods in (pairing.get('score') or {}).items():
                for method, errors in methods.items():
                    grouped[target, method].append(errors)
    out = {}
    for (target, method), records in grouped.items():
        metrics = {}
        for k in ('axis_error_deg', 'depth_errors_mm', 'transverse_errors_mm'):
            values = [v for row in records for v in (row[k] if isinstance(row[k], list) else [row[k]]) if v is not None]
            metrics[k] = dict(n=len(values), rms=math.sqrt(math.fsum(v*v for v in values) / len(values)) if values else None)
        out.setdefault(target, {})[method] = metrics
    return out


def archived_calibration(inputs, acquisition, cells, lateral_captures=()):
    import gegi_joint_two_site_study as design
    import gegi_two_site_cfd_study as checks

    calibration = inputs.read(checks.CURVES, checks.CURVES_SHA)['provenance']
    portable.require_identity(acquisition, calibration)
    scales = inputs.read(design.SCALES, design.SCALES_SHA)['controls']['group_rms_scales']
    bank = inputs.read(checks.scan.FULL/'COMPLETE.json', checks.scan.FULL_COMPLETE_SHA)
    channels = inputs.read(checks.scan.FULL/'bound-request.json', bank['request_sha256'])['channels']
    if cells is None:
        cells = portable.detector_cells(channels)
    templates = design.load_templates(inputs, cells, calibration, channels, set(), lateral_captures=lateral_captures)
    return calibration, channels, scales, templates, cells


def implementation_hashes():
    runner = Path(__file__)
    modules = (runner, Path(portable.__file__), runner.with_name('gegi_joint_two_site.py'),
               runner.with_name('gegi_joint_two_site_study.py'))
    return {p.name: sha(p.read_bytes()) for p in modules}


def export_calibration(report_path, destination, *, all_cells=False):
    from gegi_pulse_scan import Inputs

    if destination.exists():
        raise FileExistsError(destination)
    report_bytes = report_path.read_bytes()
    acquisition = json.loads(report_bytes)
    cells = None if all_cells else portable.measured_selection(acquisition)[1]
    inputs = Inputs()
    identity, channels, scales, templates, cells = archived_calibration(inputs, acquisition, cells)
    provenance = {'selection': 'detector_geometry' if all_cells else 'measured_energy_compatible_cells',
                  'compatible_acquisition_sha256': sha(report_bytes), 'input_sha256': inputs.hashes,
                  'source_sha256': implementation_hashes()}
    manifest, digest = portable.save(destination, identity=identity, channels=channels, scales=scales,
                                     requested=cells, templates=templates, provenance=provenance)
    return {'content_sha256': digest, 'calibrated_cell_count': len(manifest['calibrated_cells']),
            'requested_cell_count': len(manifest['requested_cells']), 'missing_cells': manifest['missing_cells']}


def run(*, report_path=REPORT, windows_path=WINDOWS, reference_path=DEFAULT_REFERENCE, lateral_captures=(), calibration_path=None):
    """Return measured fits, with score records when a reference path is supplied."""
    if reference_path is DEFAULT_REFERENCE:
        reference_path = REFERENCE if calibration_path is None else None
    if calibration_path is not None and (lateral_captures or reference_path is not None):
        raise ValueError('Portable center calibration requires measured-only fitting')
    started = perf_counter()
    report_bytes = report_path.read_bytes()
    report_sha = sha(report_bytes)
    acquisition = json.loads(report_bytes)
    report_key = report_path.relative_to(ROOT).as_posix() if report_path.is_relative_to(ROOT) else report_path.as_posix()
    input_hashes = {report_key: report_sha}
    if calibration_path is not None:
        return portable.fit_portable_acquisition(acquisition, report_sha, windows_path, calibration_path)

    from gegi_pulse_scan import Inputs

    inputs = Inputs()
    inputs.hashes.update(input_hashes)
    records, cells = portable.measured_selection(acquisition)
    _, channels, scales, templates, _ = archived_calibration(inputs, acquisition, cells, lateral_captures)
    fits = portable.fit_windows(acquisition, report_sha, records, windows_path, channels, templates, scales)
    result = portable.measured_receipt(acquisition, report_sha, windows_path, fits, templates, inputs.hashes,
                                       implementation_hashes(), started)
    if reference_path is None:
        return result

    # Open the history only after every measured fit has been made.
    truth = inputs.read(reference_path, REFERENCE_SHA if reference_path == REFERENCE else sha(reference_path.read_bytes()))
    if truth['adc_sha256'] != acquisition['receipt']['known_component_adc_sha256']:
        raise ValueError('Truth association belongs to another acquisition')
    geometry = {c['id']: c for c in channels}
    for row, reference in zip(fits, truth['candidates'], strict=True):
        if row['time_ns'] != reference['trigger_time_ns']:
            raise ValueError('Truth association does not match the measured trigger')
        row['reference_groups'] = reference['deposit_groups']
        for pairing in row['pairings']:
            pairing['score'] = scores(pairing, reference, geometry)
    result.update(qualified_triggers=truth['qualified_trigger_denominator'], elapsed_s=perf_counter()-started,
                  score_scope='Repeated source-library occurrences. Both orders retained. Comparisons use the same X/Y cell ordering.',
                  summary=summarize(fits))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--windows', type=Path, default=WINDOWS)
    scoring = parser.add_mutually_exclusive_group()
    scoring.add_argument('--references', type=Path)
    scoring.add_argument('--measured-only', action='store_true', help='Fit ADC windows without opening a transport reference')
    calibration = parser.add_mutually_exclusive_group()
    calibration.add_argument('--calibration', type=Path,
                             help='Fit measured ADC windows with exported center templates')
    calibration.add_argument('--export-calibration', type=Path, metavar='NPZ',
                             help='Export the archived center templates for the report’s energy-compatible cells and exit')
    parser.add_argument('--all-cells', action='store_true', help='Export center templates for the entire detector geometry')
    parser.add_argument('--output', type=Path, help='New joint-fit report')
    parser.add_argument('--lateral-capture', nargs=2, action='append', default=[], metavar=('DIRECTORY', 'COMPLETE_SHA256'),
                        help='Supplement archived lateral templates using the sealed fit records of this capture')
    args = parser.parse_args()
    if args.all_cells and args.export_calibration is None:
        parser.error('--all-cells requires --export-calibration')
    if args.references is not None and args.calibration is not None:
        parser.error('--references requires fitting from the archived calibration bank')
    if args.lateral_capture and (args.calibration is not None or args.export_calibration is not None):
        parser.error('--lateral-capture requires fitting from the archived calibration bank')
    if args.export_calibration is not None:
        print(json.dumps(export_calibration(args.report.resolve(), args.export_calibration.resolve(), all_cells=args.all_cells)))
        return
    if args.output is None:
        parser.error('--output is required for fitting')
    if args.output.exists():
        raise FileExistsError(args.output)
    reference = args.references.resolve() if args.references else None
    if reference is None and not args.measured_only and args.calibration is None:
        reference = REFERENCE
    result = run(report_path=args.report.resolve(), windows_path=args.windows.resolve(),
                 reference_path=reference, calibration_path=args.calibration.resolve() if args.calibration else None,
                 lateral_captures=[(Path(folder).resolve(), digest) for folder, digest in args.lateral_capture])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as target:
        target.write(encoded(result) + b'\n')
    print(json.dumps({key: result[key] for key in ('two_strip_triggers', 'fitted_status_counts', 'elapsed_s', 'summary')}))


if __name__ == '__main__':
    main()
