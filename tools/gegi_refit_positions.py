"""Recalculate GeGI positions from a saved dual-source trigger report."""

import argparse
from collections import Counter
import json
from pathlib import Path

import gegi_dual_source as acquisition
from gegi_event_store import encoded, sha
import gegi_substrip as substrip
import gegi_pixel_depth as pixel_depth


def recorded_pulse(trigger, receipt):
    """Rebuild only the readout observables used by the position estimator."""
    features = trigger['single_pixel_features']
    channels = []
    pair = []
    for axis in ('x', 'y'):
        face = features[axis]
        if 'preamp_cfd50_ns' not in face:
            raise ValueError('This acquisition predates saved collector timing. Replay its charge libraries for positions.')
        cid = face['contact_id']
        pair.append(cid)
        channels.append(dict(contact_id=cid, slow_energy_keV=face['slow_energy_keV'],
                             preamp_cfd50_ns=face['preamp_cfd50_ns']))
        for side in ('low', 'high'):
            neighbor = face[side]
            if neighbor is not None:
                channels.append(dict(contact_id=neighbor['contact_id'], fast_signal_keV_equiv=neighbor['fast_keV_equiv']))
    return dict(channels=channels, contact_ids=pair, slow_energy_keV=trigger['single_pixel_energy_keV'],
                profile_sha256=receipt['digital_profile_sha256'], timing_sha256=receipt['digital_timing_sha256'])


def _geometry(report, geometry_report):
    geometry = report['design']['nominal_position'].get('channel_geometry')
    if geometry is not None:
        return geometry, None
    if geometry_report is None:
        raise ValueError('Supply --geometry-from from the same detector for this earlier timing report.')
    raw = geometry_report.read_bytes()
    donor = json.loads(raw)
    def identities(source_report):
        return {(s['original']['model_sha256'], s['original']['geometry_sha256']) for s in source_report['sources']}
    if identities(donor) != identities(report):
        raise ValueError('The channel geometry comes from a different detector or assembly.')
    return donor['design']['nominal_position']['channel_geometry'], sha(raw)


def refit(source, output, *, geometry_report=None):
    raw = source.read_bytes()
    report = json.loads(raw)
    if (report.get('kind') != acquisition.KIND or report.get('status') != 'completed'
            or 'nominal_position' not in report['design']):
        raise ValueError('Select a completed acquisition with recorded collector timing.')
    output = acquisition._report_path(output)
    if output.exists():
        raise FileExistsError(output)
    receipt = report['receipt']
    def observed_hash():
        return sha(encoded(dict(counts=report['counts'], spectra=report['spectra'],
                                triggers=report['triggers'], mask=report['exposure']['excluded_intervals_ns'])))
    if receipt['observed_result_sha256'] != observed_hash():
        raise ValueError('Trigger measurements differ from the saved acquisition receipt.')
    calibration = substrip.load_calibration()
    depth_calibration = pixel_depth.load_calibration()
    geometry, geometry_source_hash = _geometry(report, geometry_report)
    field = acquisition.position_field_identity(calibration, [s['original'] for s in report['sources']])
    family_transfer = substrip.prepare_family_transfer(calibration, geometry)
    for trigger in report['triggers'] or ():
        if trigger['single_pixel_energy_keV'] is not None:
            pulse = recorded_pulse(trigger, receipt)
            trigger['nominal_position'] = acquisition._continuous_position(pulse, calibration, geometry, field, family_transfer)
        acquisition.attach_pixel_depths(trigger, depth_calibration, field, receipt['digital_profile_sha256'],
                                        receipt['digital_timing_sha256'])
    for source_info in report['sources']:
        locators = source_info['input_directory']
        relative = locators['relative_to_report_directory']
        if relative:
            locators['relative_to_report_directory'] = acquisition._relative_input(source.parent / relative, output.parent)
    report['design']['nominal_position'].update(calibration_sha256=calibration['calibration_sha256'],
                                                channel_geometry=geometry, matching_fields=field is not None,
                                                lateral_transfer=substrip.FAMILY_TRANSFER_KIND)
    report['design']['pixel_depth'] = acquisition.depth_definition(depth_calibration)
    receipt['observed_result_sha256'] = observed_hash()
    receipt['position_reprocessing'] = dict(source_report_sha256=sha(raw), new_adc_samples=0,
                                           geometry_source_report_sha256=geometry_source_hash,
                                           refit_sha256=sha(Path(__file__).read_bytes()),
                                           position_code_sha256=sha(Path(substrip.__file__).read_bytes()),
                                           pixel_depth_code_sha256=sha(Path(pixel_depth.__file__).read_bytes()),
                                           runner_sha256=sha(Path(acquisition.__file__).read_bytes()))
    acquisition._publish(report, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New acquisition report to open in Control')
    parser.add_argument('--geometry-from', type=Path, help='Optional same-geometry report for older timing records')
    args = parser.parse_args()
    try:
        result = refit(args.report, args.output, geometry_report=args.geometry_from)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Error: {error}\n')
    print(json.dumps(Counter(t['nominal_position']['status'] for t in result['triggers'] or ()
                             if t['single_pixel_energy_keV'] is not None)))


if __name__ == '__main__':
    main()
