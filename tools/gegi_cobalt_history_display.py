"""Add the two saved Co-60 transport/readout comparisons to the imaging exhibit."""

from gegi_shared_clock_display import read_study, table


REPORT_SHA256 = dict(ancestry='ffb04e70e175f60163dfc8ca9e8c3f5f4b8152c896ca115f37a3979cac111343',
                     readout='746ffdea588f5b7572d13d596cbc2bccd71f6a5bb39a27810e6dcd59bb91e601')
HISTORY_ID = ('source', 'campaign_initial_id', 'group_id')
TRIGGER_ID = ('block', 'trigger_index', 'two_strip_ordinal', 'trigger_time_ns')
INFLUENCE_FILE = 'independent-1s-intersection-influence.json.gz'
ENDPOINT_FILE = 'independent-1s-weak-endpoints.json.gz'


def values(data, keys):
    return tuple(data[key] for key in keys)


def validate_binding(data, diagnostic, windows):
    if (data['report_sha256'] != REPORT_SHA256
            or data['intersection_report_sha256'] != diagnostic['report_sha256']):
        raise ValueError('Co-60 history comparison belongs to different saved intersection reports')
    cobalt_windows = windows[1:]
    histories = data['histories']
    if [history['energy_window'] for history in histories] != cobalt_windows:
        raise ValueError('Co-60 history comparison must cover both saved cobalt line windows')
    for history, line in zip(histories, cobalt_windows, strict=True):
        expected = sorted(values(row, TRIGGER_ID) + values(row['native_group'], HISTORY_ID)
                          for row in diagnostic['selected_triggers'] if row['energy_window'] == line)
        actual = sorted(values(row, TRIGGER_ID) + values(row['native_group'], HISTORY_ID)
                        for row in history['occurrences'])
        if (len(actual) != 2 or actual != expected or
                any(row[len(TRIGGER_ID):] != values(history['identity'], HISTORY_ID) for row in actual)):
            raise ValueError(f'Co-60 history comparison changes the selected trigger identities in {line}')


def compact(ancestry_path, cone_path, diagnostic, windows):
    ancestry = read_study(ancestry_path, REPORT_SHA256['ancestry'])
    readout = read_study(cone_path, REPORT_SHA256['readout'])
    readout_inputs = diagnostic['input_sha256'] | {INFLUENCE_FILE: diagnostic['report_sha256']['influence']}
    ancestry_inputs = {key: readout_inputs[key] for key in (INFLUENCE_FILE, ENDPOINT_FILE)}
    for report, expected in ((ancestry, ancestry_inputs), (readout, readout_inputs)):
        hashes = {path.rsplit('/', 1)[-1]: checksum for path, checksum in report['input_sha256'].items()}
        if any(hashes.get(name) != digest for name, digest in expected.items()):
            raise ValueError('Co-60 history reports do not use the saved leave-two-out selection and endpoint labels')
    counts = diagnostic['views']['full']['all']['counts']['full']
    if any(counts[key] != value for key, value in readout['baseline'].items()):
        raise ValueError('Co-60 readout changes the full measured imaging census')
    history_fields = ('line_center_keV', 'identity', 'deposited_energy_keV', 'depositing_gamma_track_id',
                      'gamma_roots', 'interactions', 'photon_path', 'collection_cells', 'closure',
                      'assigned_interaction_energy_keV', 'unassigned_interaction_energy_keV',
                      'unassigned_interaction_collection_cells', 'unrooted_gamma_energy_keV')
    occurrence_fields = (*TRIGGER_ID, 'native_group', 'energy_keV', 'projected_mass', 'unresolved_mass',
                         'allowed_hypotheses', 'hypotheses', 'pairings', 'collector_slow_energies', 'endpoint_cells',
                         'missing_from_measured_x_keV', 'missing_from_measured_y_keV', 'weak_noncollector_contacts')
    histories = []
    consumed = 0
    for history in sorted(ancestry['histories'], key=lambda row: row['line_center_keV']):
        row = {key: history[key] for key in history_fields}
        identity = values(history['identity'], HISTORY_ID)
        matches = [occurrence for occurrence in readout['occurrences']
                   if values(occurrence['native_group'], HISTORY_ID) == identity]
        line_set = {occurrence['energy_window'] for occurrence in matches}
        if len(line_set) != 1:
            raise ValueError('A saved Co-60 history must match readout in one line window')
        row['energy_window'], = line_set
        matched_fields = (*TRIGGER_ID, 'energy_keV', 'energy_window')
        if (sorted(values(event, matched_fields) + (event['native_group']['occurrence_id'],) for event in matches) !=
                sorted(values(event, (*matched_fields, 'occurrence_id')) for event in history['occurrences'])):
            raise ValueError('Co-60 ancestry and readout report different trigger occurrences')
        row['occurrences'] = [{key: occurrence[key] for key in occurrence_fields} for occurrence in matches]
        for event in row['occurrences']:
            group = event['native_group']
            event['native_group'] = {key: group[key] for key in (*HISTORY_ID, 'chunk_index', 'raw_event_id',
                                                               'occurrence_id')}
        consumed += len(row['occurrences'])
        histories.append(row)
    if consumed != len(readout['occurrences']):
        raise ValueError('Co-60 readout includes occurrences outside the selected archived histories')
    result = dict(report_sha256=REPORT_SHA256, intersection_report_sha256=diagnostic['report_sha256'],
                  ancestry_method=ancestry['scope'], readout_method=readout['method'], histories=histories)
    validate_binding(result, diagnostic, windows)
    return result


def cell_label(cell):
    return f"X{cell['x_contact_id']:02d}/Y{cell['y_contact_id'] - 17:02d}"


def section(diagnostic, windows):
    data = diagnostic['cobalt_histories']
    validate_binding(data, diagnostic, windows)
    rows = []
    for history in data['histories']:
        occurrences = history['occurrences']
        block = int(occurrences[0]['block'].split('-b')[1].split('-')[0])
        triggers = ' and '.join(str(row['trigger_index']) for row in occurrences)
        deposits = '<br>'.join(f"{cell_label(cell)} {cell['deposited_energy_keV']:,.3f} keV"
                               for cell in sorted(history['collection_cells'],
                                                  key=lambda cell: -cell['deposited_energy_keV']))
        cones = []
        for occurrence in occurrences:
            for pairing in occurrence['pairings']:
                for order in pairing['orders']:
                    if order['projected_mass']:
                        cells = ' → '.join(cell_label(pairing['sites'][i]) for i in order['order'])
                        residual = f"{order['signed_source_residual_deg']:+.1f}°".replace('-', '−')
                        cones.append(f"#{occurrence['trigger_index']} {occurrence['energy_keV']:,.2f} keV<br>"
                                     f"{cells} ({residual})")
        rows.append((f"{history['line_center_keV']:,.0f} keV<br>Block {block}, triggers {triggers}",
                     f"{history['deposited_energy_keV']:,.3f} keV", deposits, '<br>'.join(cones)))
    comparison = table(rows, ('Recorded line window', 'Deposited in Ge', 'Energy by collection cell',
                              'Recorded energy and projected order (angle residual)'),
                       'Four recorded triggers from two archived Co-60 decays.')
    return f'''
<p>Each window had one pair from the same archived decay and block. In both decays one emitted Co-60 photon
deposited its entire line energy in germanium. The other line photon contributed zero to these deposits.</p>
{comparison}
<p>For the 1,173 keV photon, three Compton scatters fed X13/Y15. A fourth fed the weak X14/Y13 cell,
which was below threshold on both faces. At 1,332 keV, most of the first scatter fed X10/Y02. A small share,
including direct deposition by the photon, collected at adjacent X10/Y03. It contributed on X10 while Y03
was below threshold. A second scatter also fed X10/Y02.</p>
<p>In each trigger the reconstruction orders the final photoelectric absorption cell before the dominant cell
of the earlier scatters. Under the two-site, full-energy model, putting the high-energy cell first requires a
Compton cosine below −1. The other X/Y pairing fails the measured energy tolerance. The angular residual is
the angle between the cone axis and the direction to the programmed source, minus the energy-derived cone
half-angle. The four triggers contributed four projected orders and zero unresolved units. Both 662 keV
occurrences came from distinct histories. Pair comparisons can share triggers and archived histories.</p>'''
