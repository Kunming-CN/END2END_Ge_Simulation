"""Current four-detector navigation over completed saved 10K publications."""
import hashlib
import gzip
import stat
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
CASE_VARIANTS = {'AK02': 'AK02', 'SAP22': 'SAP22', 'GeRC02': 'GeRC02_Li50min',
                 'KMRC01_candidate': 'KMRC01_candidate'}

READOUT_CONTROLLER = r'''(() => {
'use strict';
const data=JSON.parse(document.getElementById('saved-response-data').textContent),$=id=>document.getElementById(id);
let generation=0,selectedPulse=null,selectedTrace=null;
const query=(event,group)=>savedSelectionQuery({model:data.model,event,group});
function exact(value){return value===null||value===undefined?'Unavailable':String(value);}
function energy(value){return value===null||value===undefined?'Unavailable':Number(value).toLocaleString('en-US',{maximumSignificantDigits:6})+' keV';}
function fail(message){$('selected-identity').textContent='Requested saved selection: '+location.search;$('selected-status').textContent=message;$('selected-summary').replaceChildren();$('selected-plots').replaceChildren();$('selected-record').textContent='';}
function records(){if($('selected-details').open)$('selected-record').textContent=JSON.stringify({study:'cs137-10k',model:data.model,variant:data.variant,pulse:selectedPulse,saved_trace:selectedTrace},null,2);}
function write(event,group,replace){const url=location.pathname+'?'+query(event,group)+(location.hash||'');if(replace)history.replaceState(null,'',url);else if(url!==location.pathname+location.search+(location.hash||''))history.pushState(null,'',url);}
async function restore(replace=false){
 const ticket=++generation;selectedPulse=null;selectedTrace=null;$('selected-plots').replaceChildren();$('selected-record').textContent='';$('selected-summary').replaceChildren();$('selected-sampling').textContent='';$('selected-failure').textContent='';$('selected-3d').removeAttribute('href');$('selected-scalar-link').removeAttribute('href');$('selected-teaching').hidden=true;
 const q=new URLSearchParams(location.search);if(!q.has('model'))q.set('model',data.model);
 const identity=parseViewerQuery('?'+q);
 if(identity.invalid||identity.model!==data.model){fail('Unavailable selection: '+(identity.invalid||'The requested model does not match this saved case.'));return;}
 let event=identity.event,group=identity.group;
 if(event===null){const first=data.trace_keys[0]||data.pulses.map(p=>[p.event_id,p.group_id])[0];event=first?.[0]??0;group=first?.[1]??null;}
 const pulses=data.pulses.filter(p=>p.event_id===event);
 if(group===null&&pulses.length)group=pulses[0].group_id;
 const pulse=pulses.find(p=>p.group_id===group)||null;selectedPulse=pulse;
 const key=event+'/'+group,trace=data.traces[key];
 $('selected-event').value=data.pulses.some(p=>p.event_id===event&&p.group_id===group)?key:'';
 $('selected-identity').textContent='Saved study: cs137-10k / '+data.variant+' · original primary '+event+(group===null?'':' · pulse group '+group);
 const viewer='../../../viewers/events.html?'+query(event,group)+'&view='+(pulse?'positive':'assembly');
 $('selected-3d').href=viewer;$('selected-scalar-link').href=data.scalar_url;
 updateCaseNavigation({model:data.model,result:location.pathname+'?'+query(event,group),files:location.pathname+'?'+query(event,group)+'#data-files',events:viewer,spectrum:'../../../spectra/cs137-10k.html?'+query(event,group)+'#tenk-'+data.model},'Saved study: cs137-10k / '+data.variant+' · primary '+event+(group===null?'':' · group '+group));
 const teaching=data.teaching.some(k=>k[0]===event&&k[1]===group);$('selected-teaching').hidden=!teaching;
 if(teaching)$('selected-teaching').href='../../../spectra/pipeline.html?'+query(event,group);
 const list=$('selected-summary');list.replaceChildren();
 if(pulse){for(const [label,value]of [['Truth deposited energy',energy(pulse.deposited_energy_keV)],['Signed native induced equivalent',energy(pulse.final_induced_keV)],['Peak-ADC reconstructed energy',pulse.readout?.accepted?energy(pulse.readout.reconstructed_energy_keV):'Not accepted']]){const p=document.createElement('p');p.textContent=label+': '+value;list.append(p);}
  const flags=pulse.transport_flags,notices=[];
  if(pulse.native_error)notices.push('Native transport failed: '+pulse.native_error.message+'.');
  else if(pulse.readout&&!pulse.readout.accepted)notices.push('Readout rejected: '+exact(pulse.rejection_reason)+'.');
  if(flags?.step_limits)notices.push(flags.step_limits+' step-limit endpoints.');
  if(flags?.stopped_without_contact)notices.push(flags.stopped_without_contact+' endpoints stopped without contact.');
  $('selected-failure').textContent=notices.join(' ');
 }
 else{const p=document.createElement('p');p.textContent='No matching saved pulse group. The original primary remains available in the 3D radiation records and the complete scalar ledger.';list.append(p);}
 write(event,group,replace);
 if(!trace){$('selected-status').textContent='No published full waveform for this exact primary'+(group===null?'':' / group '+group)+'. '+(pulse?'Its saved scalar response and deposit identity are shown above. ':'')+'Choose a separately labelled saved model example below to view a waveform.';records();return;}
 $('selected-status').textContent='Loading the matching saved waveform…';
 try{
  const response=await fetch(trace.path);if(!response.ok)throw Error('HTTP '+response.status);
  const packed=await response.arrayBuffer();if(!globalThis.crypto?.subtle)throw Error('SHA-256 requires HTTPS or localhost.');
  const hash=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
  if(packed.byteLength!==trace.bytes||await hash(packed)!==trace.sha256)throw Error('Saved waveform compressed size or SHA-256 mismatch.');
  if(typeof DecompressionStream==='undefined')throw Error('Native gzip DecompressionStream is required.');
  const bytes=await new Response(new Blob([packed]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  if(bytes.byteLength!==trace.uncompressed_bytes||await hash(bytes)!==trace.uncompressed_sha256)throw Error('Saved waveform original size or SHA-256 mismatch.');
  const saved=JSON.parse(new TextDecoder().decode(bytes));if(ticket!==generation)return;
  if(saved.event_id!==event||saved.group_id!==group)throw Error('Saved waveform identity mismatch.');
  selectedTrace=saved;const t=saved.trace,charge=saved.raw_native_induced_charge_fC||t.induced_charge_fC,end=t.time_ns.at(-1);
  $('selected-sampling').textContent='Exact retained original analog samples: '+t.time_ns.length+' of '+pulse.readout.original_sample_count+'. Lines join retained samples; omitted samples are unavailable. Raw row IDs, absolute group origin and full-precision values remain in the records below.';
  const chargeEnd=SavedFocusPlots.focusEnd(t.time_ns,charge),peak={t:pulse.readout.peak_time_ns,v:pulse.readout.peak_V};
  const panels=[['Native signed induced charge · fC',charge],['Electronics-input current · nA',t.current_nA],['Saved analog preamp · V',t.preamp_V],['Saved analog shaper · V',t.shaped_V]].map(([title,values],i)=>({title,time_ns:t.time_ns,values,full_end_ns:end,focus_end_ns:i===3?SavedFocusPlots.shaperEnd(t.time_ns,values,peak,end):Math.min(end,chargeEnd),...(i===3?{peak}:{}),note:''}));
  SavedFocusPlots.draw($('selected-plots'),panels,'Time since selected group origin · ns');
  $('selected-status').textContent='Matching saved waveform: primary '+event+' / group '+group+'.'+(data.model==='KMRC01_candidate'?' Negative native charge uses the saved fixed −1 electronics wiring.':'');records();
 }catch(error){if(ticket===generation){selectedTrace=null;$('selected-status').textContent='Matching waveform unavailable: '+error.message;records();}}
}
for(const pulse of data.pulses){const option=document.createElement('option');option.value=pulse.event_id+'/'+pulse.group_id;option.textContent=data.variant+' · primary '+pulse.event_id+' / group '+pulse.group_id+(data.traces[option.value]?' · saved waveform':' · scalar only');$('selected-event').append(option);}
$('selected-event').onchange=()=>{if(!$('selected-event').value)return;const [event,group]=$('selected-event').value.split('/').map(Number);write(event,group,false);restore();};
$('selected-details').ontoggle=records;globalThis.addEventListener('popstate',()=>restore());globalThis.addEventListener('pageshow',()=>restore());
restore(true);
})();'''


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
    delivery = None
    marker = folder / 'web-delivery.json'
    if marker.exists() or marker.is_symlink():
        from result_web_delivery import validate_bundle
        # The exact complete manifest stays pinned. Its portable derivative
        # validator permits only the registered ZIP omissions and anchor tags.
        delivery = validate_bundle(folder)
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
            expected = m['files'][rel]
            if delivery is not None and rel in delivery['html_rewrites']:
                require(field == 'response' and rel == model + '/response/summary.html',
                        'Unregistered ring page source rewrite: ' + rel)
                expected = delivery['html_rewrites'][rel]['delivered']
            require(sha(path) == expected['sha256']
                    and path.stat().st_size == expected['bytes'],
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


def response_data_files(folder, case, current_path):
    """One existing-file inventory supplies both selected-event and data actions."""
    from site_routes import relative_url
    scalar = 'scalars.jsonl' if case['model'] in RING_MODELS else 'scalars.csv'
    require((folder / scalar).is_file(), 'Missing published scalar ledger: ' + case['model'])
    candidates = (('run.json', 'Settings, calibration and provenance'),
                  (scalar, 'All primary and pulse scalars (' + ('JSONL' if scalar.endswith('.jsonl') else 'CSV') + ')'),
                  ('histograms.csv', 'Exact stage histograms (CSV)'),
                  ('histograms.json', 'Exact stage histograms (JSON)'),
                  ('signals.csv', 'Available raw signed native signals'),
                  ('readout-input.csv', 'Recorded electronics input'))
    return {name: {'label': label, 'href': relative_url(case['base'] + '/response/' + name, current_path)}
            for name, label in candidates if (folder / name).is_file()}


def saved_report(site, case):
    """Directly readable scientific report and one accurate archive action."""
    from site_routes import case_result_path, relative_url
    model = case['model']; folder = Path(site) / case['base'] / 'response'
    source_path = case['base'] + '/response/summary.html'
    current_path = case_result_path(model)
    data_files = response_data_files(folder, case, current_path)
    scalar_name = 'scalars.jsonl' if model in RING_MODELS else 'scalars.csv'
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
        trace_lines = [(line, json.loads(line)) for line in bundle.open('traces.jsonl') if line.strip()]
        pulses = [record for line in bundle.open('scalars.jsonl') if line.strip()
                  if (record := json.loads(line)).get('record_kind') == 'pulse']
        report = read(folder / 'run.json')
        if 'trace_examples' in report:
            traces = report['trace_examples']['source_trace_records']
            keys = report['trace_examples']['displayed_trace_keys']
            require(keys == [[int(event), int(group)] for event, group in examples],
                    'Saved waveform display keys differ: ' + model)
        else:
            traces = len(trace_lines)
    require(traces == len(trace_lines), 'Saved trace record count differs: ' + model)
    pulse_keys = {(pulse['event_id'], pulse['group_id']) for pulse in pulses}
    require(len(pulse_keys) == len(pulses), 'Repeated saved pulse identity: ' + model)
    trace_files = {}
    destination = Path(site) / posixpath.dirname(current_path) / 'traces'
    destination.mkdir(parents=True, exist_ok=True)
    site_root = Path(site).absolute()
    require(destination.absolute().is_relative_to(site_root), 'Saved trace destination outside site')
    for parent in (destination.absolute(), *destination.absolute().parents):
        require(not parent.is_symlink() and not (getattr(parent.stat(follow_symlinks=False),
                'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                'Saved trace destination uses a reparse point')
        if parent == site_root:
            break
    for raw, trace in trace_lines:
        require(type(trace.get('event_id')) is int and 0 <= trace['event_id'] <= 9999
                and type(trace.get('group_id')) is int and trace['group_id'] >= 0,
                'Invalid saved waveform identity: ' + model)
        event, group = trace['event_id'], trace['group_id']; key = f'{event}/{group}'
        require((event, group) in pulse_keys, 'Saved waveform has no matching pulse scalar: ' + model)
        require(key not in trace_files, 'Repeated saved waveform identity: ' + model)
        packed = gzip.compress(raw, compresslevel=9, mtime=0)
        legacy = destination / f'{event}-{group}.json'
        if legacy.exists() or legacy.is_symlink():
            require(not legacy.is_symlink() and not (getattr(legacy.stat(follow_symlinks=False),
                    'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                    and legacy.is_file() and sha(legacy) == hashlib.sha256(raw).hexdigest(),
                    'Unrecognized earlier generated trace; preserved: ' + legacy.name)
            legacy.unlink()
        target = destination / f'{event}-{group}.json.gz'
        if not target.exists() or target.read_bytes() != packed:
            target.write_bytes(packed)
        trace_files[key] = {'path': f'traces/{event}-{group}.json.gz',
                            'sha256': hashlib.sha256(packed).hexdigest(), 'bytes': len(packed),
                            'uncompressed_sha256': hashlib.sha256(raw).hexdigest(),
                            'uncompressed_bytes': len(raw)}
    scope = (f'<p id="waveform-scope">{escape(case["label"])} has {traces} saved trace records. '
             f'The original report displays {len(examples)} pulse-group examples. '
             f'The archive contains {traces} saved trace records in <code>traces.jsonl</code>; '
             'complete scalar, truth and endpoint ledgers do not imply complete waveforms for all 10,000 decays. '
             'Zero-Ge primaries and unavailable native responses retain their recorded identities and flags.</p>')
    science = report_body(text, source_path, current_path)
    layout = ('<style>.saved-response-report{min-width:0}.saved-response-report figure{margin:16px 0;overflow-x:auto}'
              '.saved-response-report svg{width:100%;min-width:600px;height:auto}.saved-response-report pre{white-space:pre-wrap}'
              '.saved-response-report details{margin:18px 0}.saved-response-report summary{cursor:pointer;font-weight:600}'
              '#data-files{margin-top:20px}#selected-plots{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}'
              '#selected-plots figure{min-width:0;margin:8px 0}#selected-plots svg{max-width:100%;height:auto}'
              '#selected-event{max-width:100%;padding:9px}#selected-identity{font-weight:650}'
              '#selected-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}'
              '#selected-failure{color:#99551d}'
              '@media(max-width:750px){#selected-plots,#selected-summary{grid-template-columns:1fr}}[hidden]{display:none!important}</style>')
    variant = (report.get('model_contract') or {}).get('variant_id', CASE_VARIANTS[model])
    require(variant == CASE_VARIANTS[model], 'Saved case variant changed: ' + model)
    from teaching_examples import SELECTION
    selection = dict(model=model, variant=variant, pulses=pulses, traces=trace_files,
                     trace_keys=[[trace['event_id'], trace['group_id']] for _, trace in trace_lines],
                     scalar_url=data_files[scalar_name]['href'],
                     teaching=[[event, group] for selected_model, event, group, _, _ in SELECTION if selected_model == model])
    selection_json = json.dumps(selection, ensure_ascii=True, allow_nan=False, separators=(',', ':')).replace('<', '\\u003c')
    tools = Path(__file__).resolve().parent
    selected = ('<section id="selected-response" class="panel"><h2>One saved event through charge and readout</h2>'
                + '<p id="selected-identity" aria-live="polite"></p><p id="selected-status" role="status"></p>'
                '<div id="selected-summary"></div><p id="selected-failure"></p><p><a id="selected-3d">This original primary and deposits in 3D</a> · '
                '<a id="selected-scalar-link">Complete scalar ledger</a> · <a id="selected-teaching" hidden>This event in the teaching signal chain</a></p>'
                '<div id="selected-plots"></div><label for="selected-event">Saved model examples · selecting one changes the primary and group</label>'
                '<p><select id="selected-event"><option value="">Requested event is not a saved pulse example</option></select></p>'
                '<details id="selected-details"><summary>Exact selected records, sampling and waveform coverage</summary>'
                + scope + '<p id="selected-sampling"></p><pre id="selected-record"></pre></details>'
                '<noscript>Open the complete scalar ledger, saved original report or response archive below.</noscript></section>')
    scripts = ('<script id="saved-response-data" type="application/json">' + selection_json + '</script>'
               '<script>' + (tools / 'viewer_navigation.js').read_text(encoding='utf-8') + '</script>'
               '<script>' + (tools / 'focused_plots.js').read_text(encoding='utf-8') + '</script>'
               '<script id="saved-response-controller">' + READOUT_CONTROLLER + '</script>')
    body = (layout + '<section class="hero"><p class="muted">Saved Cs137 campaign · 10,000 initial decays</p>'
            '<h1>' + escape(case['label']) + ' · charge and readout</h1><p>' + escape(case['note']) + '</p></section>'
            + selected + '<details id="saved-waveforms" class="panel saved-response-report"><summary>Complete original report, settings and saved examples</summary>' + science + '</details>')
    data = '<section id="data-files" class="panel"><h2>Data and settings</h2><p>'
    data += '<a class="button" href="' + escape(relative_url(case['base'] + '/response/ledgers.zip', current_path), quote=True) + '">Complete response archive (ZIP)</a></p>'
    data += ('<p>Contains complete primary/pulse scalars, deposition truth, native endpoints, exact stage histograms, '
             'settings and the available saved signals/traces. Original zero events, signed quantities, native errors '
             'and electronics rejections are retained. Raw LH5 and field caches remain local.</p>')
    links = []
    for item in data_files.values():
        links.append('<a href="' + escape(item['href'], quote=True) + '">' + item['label'] + '</a>')
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
    from result_web_delivery import strip_archive_links
    return strip_archive_links(body + data + '</details></section>' + scripts, current_path)


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
        text = page.read_text(encoding='utf-8')
        if any(item['attrs'].get('id') == 'current-model-results' for item in ReportElements(text).openings):
            from site_fragments import remove_sections
            updated = remove_sections(text, {'current-ring-10k'})
            if updated != text:
                page.write_text(updated, encoding='utf-8', newline='\n')
            continue
        insert_section(page, 'current-ring-10k', '<section id="current-ring-10k">'
                       '<h3>Cs137 10K case</h3><p>'+escape(case['note'])+'</p>'
                       '<a href="../../'+case_result_path(case['model'])+'">Open this detector’s 10K result →</a></section>')
    return {'models': list(ALL_MODELS), 'initial_decays': 40000, 'new_simulations': 0}
