"""Current four-detector navigation over completed saved 10K publications."""
import hashlib
import json
import posixpath
import re
import zipfile
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
    from site_routes import case_result_path
    out = []
    for case in items:
        c = case['counts']; model = case['model']
        out.append('<article class="card"><h2>' + escape(case['label']) + '</h2><p>'
                   + escape(case['note']) + '</p><p>10,000 initial decays · '
                   + f'{c["zero_deposit_primaries"]:,} zero-Ge decays · {c["groups"]:,} pulse groups.</p><p>'
                   + f'{c["accepted"]:,} accepted · {c["native_failed_groups"]:,} native failures · '
                   + f'{c["readout_rejected"]:,} electronics rejects.</p><p>'
                   + f'<a class="button" href="{up}{case_result_path(model)}">Open saved result →</a></p></article>')
    return '<div class="grid">' + ''.join(out) + '</div>'


def insert_section(path, section_id, section):
    from site_fragments import remove_sections
    path = Path(path)
    text = remove_sections(path.read_text(encoding='utf-8'), {section_id})
    sections = ReportElements(text).elements
    saved = next((item for item in sections if item['tag'] == 'section'
                  and item['attrs'].get('id') == 'saved-studies'), None)
    if saved:
        end = saved['close']
    else:
        end = text.rfind('</main>')
        require(end >= 0, 'Current detector content missing: ' + path.name)
        section = '<section id="saved-studies" class="panel"><h2>Saved studies</h2>' + section + '</section>'
    updated = text[:end] + section + text[end:]
    if path.read_text(encoding='utf-8') != updated:
        path.write_text(updated, encoding='utf-8', newline='\n')


class ReportElements(HTMLParser):
    """Locate source spans without serializing scientific markup or script data."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.offsets = [0]
        for line in text.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.elements = []
        self.openings = []
        self.stack = {}
        self.declarations = []
        self.feed(text)

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_decl(self, declaration):
        start = self.position()
        self.declarations.append((start, self.text.index('>', start) + 1))

    def handle_starttag(self, tag, attrs):
        start = self.position()
        item = {'tag': tag, 'attrs': dict(attrs), 'start': start,
                'open_end': start + len(self.get_starttag_text())}
        self.openings.append(item)
        if tag not in self.VOID:
            self.stack.setdefault(tag, []).append(item)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            item = self.stack[tag].pop()
            self.elements.append(dict(item, close=item['open_end'], end=item['open_end']))

    def handle_endtag(self, tag):
        if self.stack.get(tag):
            item = self.stack[tag].pop()
            start = self.position()
            self.elements.append(dict(item, close=start, end=self.text.index('>', start) + 1))


def report_body(text, source_path, current_path):
    """Adapt one frozen report's display; numerical elements remain source slices."""
    parsed = ReportElements(text)
    removals = list(parsed.declarations)
    changes = []
    for item in parsed.openings:
        tag = item['tag']; start = item['start']; end = item['open_end']
        opening = text[start:end]
        if tag in {'html', 'head', 'body', 'meta'}:
            removals.append((start, end))
            continue

        def resource(match):
            url = unescape(match.group(2)); parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
                return match.group(0)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), parts.path))
            relative = posixpath.relpath(target, posixpath.dirname(current_path))
            return match.group(1) + escape(urlunsplit(('', '', relative, parts.query, parts.fragment)), quote=True) + match.group(3)

        adapted = re.sub(r'((?:href|src|poster)\s*=\s*["\'])([^"\']*)(["\'])', resource, opening)
        if tag == 'h1':
            adapted = adapted.replace('<h1', '<h2', 1)
        if adapted != opening:
            changes.append((start, end, adapted))

    opened_example = False
    for item in parsed.elements:
        tag = item['tag']; start = item['start']; end = item['end']
        content = text[item['open_end']:item['close']]
        if tag in {'html', 'head', 'body'}:
            removals.append((item['close'], end))
        elif tag == 'title':
            removals.append((start, end))
        elif tag == 'style':
            # These saved report styles use ordinary selectors. Scope them to
            # the report so their body/nav rules cannot replace site navigation.
            require('@' not in content, 'Unsupported saved-report stylesheet')
            def scope(match):
                selectors = [s.strip() for s in match.group(2).split(',')]
                scoped = ['.saved-response-report' if s in {'html', 'body'}
                          else '.saved-response-report ' + s for s in selectors]
                return match.group(1) + ','.join(scoped) + '{'
            css = re.sub(r'(^|})([^{}]+){', scope, content)
            changes.append((start, end, text[start:item['open_end']] + css + text[item['close']:end]))
        elif tag in {'nav', 'p'}:
            hrefs = re.findall(r'href=["\']([^"\']*)["\']', content)
            if 'run.json' in hrefs and 'ledgers.zip' in hrefs:
                # Replace this identified data-action block with Data and
                # settings below; do not erase report references elsewhere.
                require(set(hrefs) <= {'run.json', 'ledgers.zip', 'scalars.csv', 'signals.csv', 'histograms.csv'},
                        'Unrecognized saved-report action block')
                removals.append((start, end))
        elif tag == 'a' and item['attrs'].get('href') == 'ledgers.zip':
            changes.append((start, end, unescape(re.sub('<[^>]*>', '', content))
                            + ' (included in the complete response archive)'))
        elif tag == 'h1':
            changes.append((item['close'], end, '</h2>'))
        elif tag == 'details' and not opened_example and re.match(r'<summary>Event \d+ / group \d+</summary>', content):
            opened_example = True
            if 'open' not in item['attrs']:
                changes.append((start, item['open_end'], text[start:item['open_end'] - 1] + ' open>'))

    # Enclosing removals take precedence over individual attribute edits.
    removals = [(start, end) for start, end in removals
                if not any(a <= start and end <= b and (a, b) != (start, end) for a, b in removals)]
    changes = [(start, end, value) for start, end, value in changes
               if not any(a <= start and end <= b for a, b in removals)]
    # A complete element replacement already contains its opening attributes.
    # Applying both edits would insert the old anchor into the replacement text.
    changes = [(start, end, value) for start, end, value in changes
               if not any(a <= start and end <= b and (a, b) != (start, end)
                          for a, b, _ in changes)]
    edits = changes + [(start, end, '') for start, end in removals]
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    obsolete = ('Complete truth, endpoints, scalar CSV, histogram CSV and saved traces are delivered byte-for-byte '
                'inside the complete ledger ZIP; these download links open that ZIP. '
                'Direct signed signals, JSONL scalars and JSON histograms remain available.')
    text = text.replace('<p>' + obsolete + '</p>', '')
    return text


def saved_report(site, case):
    """Directly readable scientific report and one accurate archive action."""
    from site_routes import case_result_path, relative_url
    model = case['model']; folder = Path(site) / case['base'] / 'response'
    source_path = case['base'] + '/response/summary.html'
    current_path = case_result_path(model)
    original = folder / 'summary.html'
    require(original.is_file(), 'Missing original charge/readout report: ' + model)
    text = original.read_text(encoding='utf-8')
    require('<h1' in text, 'Saved charge/readout heading missing: ' + model)
    examples = re.findall(r'<summary>Event (\d+) / group (\d+)</summary>', text)
    archive = folder / 'ledgers.zip'
    require(archive.is_file(), 'Missing complete response archive: ' + model)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        require({'truth.jsonl', 'scalars.jsonl', 'endpoints.jsonl', 'histograms.json', 'traces.jsonl', 'run.json'} <= set(names),
                'Incomplete response archive: ' + model)
        report = read(folder / 'run.json')
        if 'trace_examples' in report:
            traces = report['trace_examples']['source_trace_records']
            keys = report['trace_examples']['displayed_trace_keys']
            require(keys == [[int(event), int(group)] for event, group in examples],
                    'Saved waveform display keys differ: ' + model)
        else:
            with bundle.open('traces.jsonl') as stream:
                traces = sum(1 for line in stream if line.strip())
    scope = (f'<p id="waveform-scope">This report displays {len(examples)} saved pulse-group examples. '
             f'The archive contains {traces} saved trace records in <code>traces.jsonl</code>; '
             'complete scalar, truth and endpoint ledgers do not imply complete waveforms for all 10,000 decays. '
             'Zero-Ge primaries and unavailable native responses retain their recorded identities and flags.</p>')
    science = report_body(text, source_path, current_path)
    layout = ('<style>.saved-response-report{min-width:0}.saved-response-report figure{margin:16px 0;overflow-x:auto}'
              '.saved-response-report svg{width:100%;min-width:600px;height:auto}.saved-response-report pre{white-space:pre-wrap}'
              '.saved-response-report details{margin:18px 0}.saved-response-report summary{cursor:pointer;font-weight:600}'
              '#data-files{margin-top:20px}</style>')
    body = (layout + '<section class="hero"><p class="muted">Saved Cs137 campaign · 10,000 initial decays</p>'
            '<h1>' + escape(case['label']) + ' · charge and readout</h1><p>' + escape(case['note']) + '</p></section>'
            '<section id="saved-waveforms" class="panel saved-response-report">' + scope + science + '</section>')
    data = '<section id="data-files" class="panel"><h2>Data and settings</h2><p>'
    data += '<a class="button" href="' + escape(relative_url(case['base'] + '/response/ledgers.zip', current_path), quote=True) + '">Complete response archive (ZIP)</a></p>'
    data += ('<p>Contains complete primary/pulse scalars, deposition truth, native endpoints, exact stage histograms, '
             'settings and the available saved signals/traces. Original zero events, signed quantities, native errors '
             'and electronics rejections are retained. Raw LH5 and field caches remain local.</p>')
    links = []
    for name, label in (('run.json', 'Settings, calibration and provenance'),
                        ('scalars.csv', 'All primary and pulse scalars (CSV)'),
                        ('scalars.jsonl', 'All primary and pulse scalars (JSONL)'),
                        ('histograms.csv', 'Exact stage histograms (CSV)'),
                        ('histograms.json', 'Exact stage histograms (JSON)'),
                        ('signals.csv', 'Available raw signed native signals'),
                        ('readout-input.csv', 'Recorded electronics input')):
        if (folder / name).is_file():
            url = relative_url(case['base'] + '/response/' + name, current_path)
            links.append('<a href="' + escape(url, quote=True) + '">' + label + '</a>')
    data += '<p>' + ' · '.join(links) + '</p>'
    if (folder / 'native-failures.json').is_file():
        url = relative_url(case['base'] + '/response/native-failures.json', current_path)
        data += '<p><a href="' + escape(url, quote=True) + '">Independent saved native-failure diagnostics (JSON)</a></p>'
    data += '<details><summary>Exact archive member list</summary><ul>' + ''.join('<li><code>' + escape(name) + '</code></li>' for name in names) + '</ul></details>'
    original_url = relative_url(source_path, current_path)
    data += ('<details id="original-reports"><summary>Original reports (archive)</summary><p>'
             '<a href="' + escape(original_url, quote=True) + '">Original saved charge/readout report</a>. '
             'Preserved SHA256: <code>' + sha(original) + '</code>.</p>')
    if model == 'KMRC01_candidate':
        old = case['base'] + '/response/original-native/summary.html'
        require((Path(site) / old).is_file(), 'Original KM native rejection history missing')
        data += ('<p><a href="' + escape(relative_url(old, current_path), quote=True) + '">Original KM native response: 0/231 accepted (archive)</a>. '
                 'The original positive-peak readout rejected all 231 groups. The current fixed −1 wiring is a separate derivative; '
                 'raw negative native charge is preserved. The ZIP retains the complete original HTML and native records.</p>')
    return body + data + '</details></section>'


def apply(site):
    """Called only by the maintained site build after ordinary navigation."""
    from site_restructure import write_page
    from site_routes import page_navigation, case_result_path
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
            '<a data-original-report href="../../examples/cs137-10k/comparison.html">Original AK02/SAP22 comparison (archive)</a> · '
            '<a href="../../examples/cs137-10k-rings/manifest.json">Ring provenance</a></p></section>')
    write_page(site / 'results/cs137-10k/index.html', 'Four-detector Cs137 10K · GeSignal', body, 2,
               page_path='results/cs137-10k/index.html', dataset='tenk',
               nav_html=page_navigation('results/cs137-10k/index.html', dataset='tenk'))
    for case in items:
        model = case['model']
        write_page(site/'results/cs137-10k'/model/'charge-readout.html',
                   case['label']+' · Cs137 10K charge/readout · GeSignal', saved_report(site, case), 3,
                   page_path=case_result_path(model), dataset='tenk', model=model, model_label=case['label'],
                   nav_html=page_navigation(case_result_path(model), dataset='tenk', model=model, model_label=case['label']))
    for case in items:
        page = site / 'detectors' / case['model'] / 'index.html'
        if not page.is_file():
            continue
        insert_section(page, 'current-ring-10k', '<section id="current-ring-10k">'
                       '<h3>Cs137 10K case</h3><p>'+escape(case['note'])+'</p>'
                       '<a href="../../'+case_result_path(case['model'])+'">Open this detector’s 10K result →</a></section>')
    return {'models': list(ALL_MODELS), 'initial_decays': 40000, 'new_simulations': 0}
