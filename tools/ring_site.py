"""Current four-detector navigation over completed saved 10K publications."""
import hashlib
import json
from html import escape
from pathlib import Path

RING_FOLDER = 'examples/cs137-10k-rings'
RING_MODELS = ('GeRC02', 'KMRC01_candidate')
ALL_MODELS = ('AK02', 'SAP22') + RING_MODELS


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ring_manifest(site):
    folder = Path(site) / RING_FOLDER
    if not folder.exists():
        return None
    m = read(folder / 'manifest.json')
    require(m['kind'] == 'ring_saved_publication_v1' and m['status'] == 'complete'
            and m['schema_version'] == 1 and set(m['models']) == set(RING_MODELS),
            'Only a complete two-ring publication enables current ring pages')
    for model in RING_MODELS:
        item = m['models'][model]
        require(item['event_count'] == 10000 and item['counts']['initial_primaries'] == 10000,
                'Ring page requires all 10,000 initial decays')
        for field in ('scene', 'selected', 'response', 'response_report'):
            rel = item[field]
            require(isinstance(rel, str) and rel.startswith(model + '/')
                    and '\\' not in rel and '..' not in Path(rel).parts,
                    'Unsafe ring page asset binding')
            path = folder / rel
            require(sha(path) == m['files'][rel]['sha256']
                    and path.stat().st_size == m['files'][rel]['bytes'],
                    'Ring page source changed: ' + rel)
        report = read(folder / item['response_report'])
        require(report['current_counts'] == item['counts'], 'Ring page/current response census differs')
    return m


def source_files(site):
    """Extra numeric provenance for the common spectrum display."""
    m = ring_manifest(site)
    if m is None:
        return ()
    return (RING_FOLDER + '/manifest.json',) + tuple(
        RING_FOLDER + '/' + model + '/response/histograms.json' for model in RING_MODELS)


def cases(site):
    site = Path(site)
    m = ring_manifest(site)
    if m is None:
        return []
    result = []
    for model in ALL_MODELS:
        base = 'examples/cs137-10k/' + model if model not in RING_MODELS else RING_FOLDER + '/' + model
        report = read(site / base / 'response/run.json')
        c = report['current_counts' if model in RING_MODELS else 'counts']
        require(c['initial_primaries'] == c['initial_decays'] == 10000,
                'Four-detector page requires the initial-decay count convention')
        require(c['accepted'] + c['native_failed_groups'] + c['readout_rejected'] == c['groups'],
                'Four-detector pulse accounting differs')
        label = {'GeRC02': 'GeRC02 · Li 50 min', 'KMRC01_candidate': 'KMRC01 · candidate'}.get(model, model)
        note = {'AK02': 'Original Li-contact ICPC case.',
                'SAP22': 'Original non-Li ICPC cross-check; different geometry.',
                'GeRC02': 'Independent 280°C / 50-minute Li variant. Original 30-minute model retained.',
                'KMRC01_candidate': 'Unchanged −370 V candidate model. Raw negative charge; fixed −1 electronics input and independent negative injection calibration.'}[model]
        result.append({'model': model, 'label': label, 'note': note, 'counts': c, 'base': base})
    return result


def cards(items, up):
    out = []
    for case in items:
        c = case['counts']; model = case['model']; base = up + case['base']
        response = 'summary.html'
        out.append('<article class="card"><h2>' + escape(case['label']) + '</h2><p>'
                   + escape(case['note']) + '</p><p>10,000 initial decays · '
                   + f'{c["zero_deposit_primaries"]:,} zero-Ge decays · {c["groups"]:,} pulse groups.</p><p>'
                   + f'{c["accepted"]:,} accepted · {c["native_failed_groups"]:,} native failures · '
                   + f'{c["readout_rejected"]:,} electronics rejects.</p><p>'
                   + f'<a href="{up}viewers/events.html?model={model}&amp;view=positive">Events</a> · '
                   + f'<a href="{up}spectra/cs137-10k.html#tenk-{model}">Spectra</a> · '
                   + f'<a href="{base}/response/{response}">Charge &amp; readout</a> · '
                   + f'<a href="{base}/response/ledgers.zip">Data</a></p></article>')
    return '<div class="grid">' + ''.join(out) + '</div>'


def insert_section(path, section_id, section):
    from site_fragments import remove_sections
    path = Path(path)
    text = remove_sections(path.read_text(encoding='utf-8'), {section_id})
    end = text.find('</section>')
    require(end >= 0, 'Current page hero missing: ' + path.name)
    end += len('</section>')
    updated = text[:end] + section + text[end:]
    if path.read_text(encoding='utf-8') != updated:
        path.write_text(updated, encoding='utf-8', newline='\n')


def apply(site):
    """Called only by the maintained site build after ordinary navigation."""
    from site_restructure import write_page
    site = Path(site); items = cases(site)
    if not items:
        return None
    body = ('<section class="hero"><p class="muted">Four detector cases</p>'
            '<h1>Cs137 · 10K initial decays per detector</h1>'
            '<p>AK02, SAP22, GeRC02 Li50min and KMRC01 candidate. Each case retains all 10,000 initial identities, '
            'including zero-Ge events, delayed daughters and failed responses. These are separate saved engineering campaigns.</p></section>'
            + cards(items, '../../')
            + '<section class="panel"><h2>Counting and interpretation</h2>'
            '<p>40,000 initial decays across four cases is not 40,000 pulses or a simultaneous acquisition. '
            'Truth Edep, signed native charge and readout Erec remain separate. Unknown native response stays null; '
            'native failure and electronics rejection are distinct.</p>'
            '<p>Nominal mounting/source and isolated electronics windows; synthetic injection calibration. '
            'Processing completion does not establish calibrated Li CCE, experimental spectrum agreement or physical energy resolution.</p>'
            '<p><a href="../../scenarios/lbnl-cs137/index.html">Scenario context</a> · '
            '<a href="../../examples/cs137-10k/comparison.html">Original ICPC report</a> · '
            '<a href="../../examples/cs137-10k-rings/manifest.json">Ring provenance</a></p></section>')
    write_page(site / 'results/cs137-10k/index.html', 'Four-detector Cs137 10K · GeSignal', body, 2)
    for rel, up in (('index.html', ''), ('results/index.html', '../'), ('detectors/index.html', '../')):
        section = ('<section id="current-ring-10k" class="panel"><h2>Four-detector Cs137 10K</h2>'
                   '<p>ICPC: AK02, SAP22. Ring contact: GeRC02 Li50min, KMRC01 candidate. '
                   'Events, stage spectra, charge/readout and complete ledgers share one entry.</p>'
                   + f'<a class="button" href="{up}results/cs137-10k/index.html">Open all four cases →</a></section>')
        insert_section(site / rel, 'current-ring-10k', section)
    for case in items:
        page = site / 'detectors' / case['model'] / 'index.html'
        if not page.is_file():
            continue
        insert_section(page, 'current-ring-10k', '<section id="current-ring-10k" class="panel">'
                       '<h2>Current Cs137 10K result</h2>' + cards([case], '../../') + '</section>')
        text = page.read_text(encoding='utf-8')
        old = ('<p>LBNL end-to-end execution is not yet integrated for this model. '
               'Geometry viewing is available independently of cryostat placement and readout support.</p>')
        replacement = ('<p>The saved ring 10K used a separately checked bounded adapter. '
                       'The generic beginner new-run selection remains AK02/SAP22; '
                       'saved-result availability and fresh-machine reproduction are separate.</p>')
        if case['model'] in RING_MODELS and old in text:
            page.write_text(text.replace(old, replacement, 1), encoding='utf-8', newline='\n')
    return {'models': list(ALL_MODELS), 'initial_decays': 40000, 'new_simulations': 0}
