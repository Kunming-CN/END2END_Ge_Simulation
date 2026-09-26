"""Lossless publication of saved native campaign results; no simulation entry points."""
import hashlib, io, json, re, subprocess, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ('AK02', 'SAP22')
ARCHIVE_NAMES = frozenset(('run.json', 'endpoints.csv', 'endpoints.jsonl', 'histograms.csv',
    'histograms.json', 'input-contract.json', 'input-prepared.json', 'native-failures.jsonl',
    'profile-input.json', 'profile.json', 'readout-config.json', 'scalars.csv', 'scalars.jsonl',
    'signals.csv', 'summary.html', 'traces.jsonl', 'truth.csv', 'truth.jsonl'))
COPY_NAMES = ('run.json', 'summary.html', 'scalars.csv', 'histograms.csv', 'histograms.json',
              'profile.json', 'readout-config.json', 'signals.csv')
PRIVATE = re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/', re.I)
SECRET = re.compile(rb'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')

def sha(data): return hashlib.sha256(data).hexdigest()
def load(file): return json.loads(Path(file).read_text(encoding='utf-8-sig'))
def require(ok, message):
    if not ok: raise ValueError(message)
def safe(data, label):
    require(not PRIVATE.search(data) and not SECRET.search(data), 'Private metadata: '+label)
    data.decode('utf-8-sig')
def file_hash(file):
    h = hashlib.sha256()
    with Path(file).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def validate_ledger_archive(data):
    """Only a fixed, portable text ledger inventory is allowed in these ZIPs."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        items = z.infolist()
        require(len(items)==len(ARCHIVE_NAMES) and set(z.namelist())==ARCHIVE_NAMES,
                'Unexpected/duplicate ledger archive inventory')
        require(sum(i.file_size for i in items)<=512*1024**2, 'Expanded archive too large')
        require(all(i.file_size<95*1024**2 and i.compress_type in (0,8) and
                    not i.flag_bits & 1 and (i.external_attr >> 16) & 0o170000 != 0o120000
                    for i in items), 'Unsafe ledger archive member')
        report = json.loads(z.read('run.json'))
        require(set(report['artifacts'])==ARCHIVE_NAMES-{'run.json'}, 'Archive receipt inventory')
        inventory = {}
        for i in items:
            body = z.read(i.filename); safe(body, i.filename)
            inventory[i.filename] = sha(body)
            if i.filename != 'run.json':
                require(inventory[i.filename]==report['artifacts'][i.filename], 'Archive receipt mismatch')
        return inventory

def write(file, body):
    file.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str): body = body.encode('utf-8')
    safe(body, file.name)
    with file.open('xb') as f: f.write(body)
def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def adapt_trace_page(text, note):
    for link in ('endpoints.csv', 'truth.jsonl', 'native-failures.jsonl'):
        pattern = r'href=([\x22\x27])'+re.escape(link)+r'\1'
        text, count = re.subn(pattern, lambda m: 'href='+m[1]+'ledgers.zip'+m[1], text)
        require(count==1, 'Unexpected trace page link: '+link)
    require(text.count('<h1>')==1, 'Unexpected trace page heading')
    return text.replace('<h1>', note+'<h1>', 1)

def assemble(campaign, output):
    """Validate the saved campaign, then create a new bounded public bundle."""
    campaign = Path(campaign).resolve(strict=True); output = Path(output)
    require(campaign.is_relative_to((ROOT/'.local').resolve()), 'Campaign outside project .local')
    require(not output.exists(), 'Publication output already exists')
    run = load(campaign/'run.json')
    require(run['events_per_model']==10000, 'This publication is the 10k/model campaign')
    for name, expected in run['source_sha256'].items():
        source = (ROOT/name).resolve(strict=True)
        require(source.is_relative_to(ROOT) and file_hash(source)==expected, 'Campaign source changed: '+name)
    command = ['node', str(ROOT/'tools/native_campaign_report.mjs'), str(campaign), '--verify-only']
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=True)
    verified = json.loads(result.stdout)
    original = load(campaign/'comparison.json')
    require(original['campaign_sha256']==file_hash(campaign/'run.json') and
            original['html_sha256']==file_hash(campaign/'comparison.html') and
            original['models']==verified['models'], 'Saved comparison changed')
    output.mkdir(parents=True)
    notes = ('Public copy of the saved 10,000-decay-per-detector engineering run. '
        'Every scalar event and pulse is retained. Each response/ledgers.zip contains ALL '
        'original response files, including every truth/deposit and endpoint record. '
        'Archive bytes and public derivatives have separate hashes. Original raw LH5, '
        'field caches and upstream geometry remain local; they are not in this public bundle. '
        'The two native failures and all trajectory limits remain unresolved. '
        'ADC acceptance is not proof of complete carrier collection or calibrated accuracy.')
    page_note = '<aside class="note"><strong>Publication scope.</strong> '+notes+'</aside>'
    archive_records = {}
    for model in MODELS:
        source = campaign/model/'response'; destination = output/model/'response'
        report = load(source/'run.json')
        require(set(report['artifacts'])==ARCHIVE_NAMES-{'run.json'}, 'Unreviewed response inventory')
        destination.mkdir(parents=True)
        archive = destination/'ledgers.zip'
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name in sorted(ARCHIVE_NAMES):
                file = source/name
                require(file.is_file() and not file.is_symlink(), 'Unsafe response file: '+name)
                body = file.read_bytes(); safe(body, name)
                if name != 'run.json': require(sha(body)==report['artifacts'][name], 'Response changed during export')
                member = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
                member.compress_type = zipfile.ZIP_DEFLATED; member.external_attr = 0o100644 << 16
                z.writestr(member, body)
        archive_records[model] = validate_ledger_archive(archive.read_bytes())
        for name in COPY_NAMES:
            body = (source/name).read_bytes()
            if name == 'summary.html':
                body = adapt_trace_page(body.decode('utf-8'), page_note).encode('utf-8')
            write(destination/name, body)
        failures = [json.loads(line) for line in (source/'native-failures.jsonl').read_text(encoding='utf-8').splitlines()]
        write(destination/'native-failures.json', json_bytes(failures))
        write(output/model/'transport'/'stream'/'manifest.json',
              (campaign/model/'transport'/'stream'/'manifest.json').read_bytes())
    page = (campaign/'comparison.html').read_text(encoding='utf-8')
    page = page.replace('response/native-failures.jsonl', 'response/native-failures.json')
    page = page.replace('href="comparison.json"', 'href="source-comparison.json"')
    page = page.replace('<h1>', page_note+'<h1>', 1)
    require(page.count('</html>')==1, 'Unexpected comparison document ending')
    page = page.replace('</html>', '<p><a href="publication.json">Public file hashes and lossless archive inventory</a></p></html>', 1)
    write(output/'comparison.html', page)
    write(output/'run.json', (campaign/'run.json').read_bytes())
    write(output/'source-comparison.json', (campaign/'comparison.json').read_bytes())
    write(output/'verification.json', json_bytes(verified))
    write(output/'README.md', '# Saved native Cs137 10k campaign\n\n'+notes+'\n\n'
        'Open comparison.html. In each detector folder, response/summary.html shows the first four '
        'pulse groups. The CSV tables and ZIP ledgers retain all records, including zero deposits '
        'and failures. Native groups are not 10,000 accepted detector pulses.\n\n'
        'The files run.json and source-comparison.json are original historical receipts; their '
        'artifact hashes bind originals inside the ZIP archives. publication.json separately '
        'binds the linked, adapted public HTML. No simulation or fit was run for publication.\n')
    entries = {f.relative_to(output).as_posix(): {'bytes': f.stat().st_size, 'sha256': file_hash(f)}
               for f in sorted(output.rglob('*')) if f.is_file()}
    metadata = dict(kind='native_publication_v1', status=run['status'],
        campaign_sha256=file_hash(campaign/'run.json'), notes=notes,
        publisher_sha256=file_hash(__file__), files=entries, archive_members=archive_records)
    write(output/'publication.json', json_bytes(metadata))
    require(file_hash(campaign/'run.json')==original['campaign_sha256'], 'Campaign changed during export')
    validate_bundle(output)
    return metadata

def validate_bundle(folder):
    folder = Path(folder)
    require(not folder.is_symlink(), 'Symlink publication folder')
    metadata = load(folder/'publication.json')
    require(metadata['kind']=='native_publication_v1', 'Unsupported publication schema')
    require(not any(f.is_symlink() for f in folder.rglob('*')), 'Symlink publication file')
    actual = {f.relative_to(folder).as_posix() for f in folder.rglob('*') if f.is_file()}
    require(actual==set(metadata['files'])|{'publication.json'}, 'Public bundle inventory mismatch')
    for name, entry in metadata['files'].items():
        require(not name.startswith('/') and '\\' not in name and '..' not in Path(name).parts,
                'Unsafe public file path')
        file = folder/name
        require(file.stat().st_size==entry['bytes'] and file_hash(file)==entry['sha256'], 'Public file changed: '+name)
        if file.suffix != '.zip': safe(file.read_bytes(), name)
    run = load(folder/'run.json'); verified = load(folder/'verification.json')
    require(file_hash(folder/'run.json')==metadata['campaign_sha256']==verified['campaign_sha256'], 'Campaign binding mismatch')
    require(run['status']==metadata['status']==verified['campaign_status'], 'Campaign public status mismatch')
    for model in MODELS:
        destination = folder/model/'response'; archive = (destination/'ledgers.zip').read_bytes()
        inventory = validate_ledger_archive(archive)
        require(inventory==metadata['archive_members'][model], 'Archive inventory changed')
        require(inventory['run.json']==file_hash(destination/'run.json')==run['models'][model]['response_report_sha256'], 'Archive source receipt changed')
        for name in COPY_NAMES:
            if name != 'summary.html': require(file_hash(destination/name)==inventory[name], 'Public numeric values changed')
    return metadata
