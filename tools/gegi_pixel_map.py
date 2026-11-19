"""Project measured GeGI strip intersections from an existing acquisition report."""

import argparse
import hashlib
import json
import math
from pathlib import Path


KIND = 'gegi_dual_source_pixel_map_v1'
REPORT_KIND = 'gegi_dual_source_acquisition_v1'
X_IDS = tuple(range(1, 17))
Y_IDS = tuple(range(18, 34))
_CENSUS = ('qualified_triggers', 'single_pixel_energies', 'additional_multi_strip_energies',
           'qualified_energies', 'triggers_without_energy')


def _map(status, reason=None, counts=None, totals=None):
    return {'kind': KIND, 'status': status, 'reason': reason,
            'axes': {'x_contact_ids': list(X_IDS), 'y_contact_ids': list(Y_IDS)},
            'counts': counts, 'totals': totals}


def unavailable(reason):
    return _map('unavailable', reason)


def _energy(value):
    return type(value) in (int, float) and 0 < value < math.inf


def _contact_pair(trigger):
    x, y = trigger['x_collecting_strips'], trigger['y_collecting_strips']
    if (type(x) is not list or type(y) is not list or len(x) != 1 or len(y) != 1
            or type(x[0]) is not int or type(y[0]) is not int
            or x[0] not in X_IDS or y[0] not in Y_IDS or trigger.get('guard_contact_ids')):
        raise ValueError('Invalid collecting pair for a qualified single-pixel trigger')
    return x[0], y[0]


def _project(report):
    if report.get('kind') != REPORT_KIND or report.get('status') != 'completed':
        raise ValueError('Select a completed GeGI dual-source acquisition report')
    samples = report['exposure']['qualified_live_adc_samples']
    saved = report['counts']
    triggers = report['triggers']
    if type(samples) is not int or samples < 0:
        raise ValueError('Invalid qualified ADC sample count')
    if samples == 0:
        if triggers is not None or any(saved[key] is not None for key in _CENSUS):
            raise ValueError('Trigger counts require a qualified ADC interval')
        return unavailable('no_qualified_adc_samples')
    if type(triggers) is not list:
        raise ValueError('Qualified acquisition has no trigger ledger')
    counts = [[0] * len(X_IDS) for _ in Y_IDS]
    single, multi, no_energy = 0, 0, 0
    seen = set()
    for trigger in triggers:
        time = trigger['trigger_time_ns']
        if type(time) not in (int, float) or not 0 <= time < math.inf or time in seen:
            raise ValueError('Invalid or duplicate acquisition trigger time')
        seen.add(time)
        measured = trigger['single_pixel_energy_keV']
        additional = trigger['additional_multi_strip_energy_keV']
        if measured is not None:
            if not _energy(measured) or additional is not None:
                raise ValueError('Invalid single-pixel trigger energy')
            x, y = _contact_pair(trigger)
            counts[y - Y_IDS[0]][x - X_IDS[0]] += 1
            single += 1
        elif additional is not None:
            if not _energy(additional):
                raise ValueError('Invalid multi-strip trigger energy')
            multi += 1
        else:
            no_energy += 1
    expected = {'qualified_triggers': len(triggers), 'single_pixel_energies': single,
                'additional_multi_strip_energies': multi, 'qualified_energies': single + multi,
                'triggers_without_energy': no_energy}
    if any(type(saved[key]) is not int or saved[key] != value for key, value in expected.items()):
        raise ValueError('Trigger ledger differs from its acquisition census')
    totals = {'qualified_triggers': len(triggers), 'mapped_single_pixel_triggers': single,
              'multi_strip_energy_triggers': multi, 'triggers_without_energy': no_energy,
              'occupied_pixels': sum(cell > 0 for row in counts for cell in row)}
    return _map('available' if single else 'empty', None if single else 'no_qualified_single_pixel_energies',
                counts, totals)


def project_pixel_map(report):
    """Count only measured single-pixel energies. Matrix rows are Y01 to Y16."""
    try:
        return _project(report)
    except (AttributeError, KeyError, TypeError, ValueError):
        return unavailable('invalid_report')


def read_pixel_map(path, *, expected_sha256=None):
    """Read a completed report and optionally enforce its saved whole-file SHA-256."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return unavailable('report_missing')
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        return unavailable('report_changed')
    try:
        report = json.loads(raw)
    except (UnicodeError, ValueError):
        return unavailable('invalid_report')
    return project_pixel_map(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='Existing dual-source acquisition JSON')
    parser.add_argument('--output', type=Path, help='New map JSON file; defaults to stdout')
    args = parser.parse_args()
    result = json.dumps(read_pixel_map(args.report), separators=(',', ':')) + '\n'
    if args.output is None:
        print(result, end='')
    else:
        try:
            with args.output.open('x', encoding='utf-8', newline='\n') as out:
                out.write(result)
        except OSError as error:
            parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
