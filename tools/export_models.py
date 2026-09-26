"""Import exact SSD distribution snapshots explicitly; validate without source inputs.

Python 3.10+, stdlib only. No YAML rewriting, simulation, or cache copying.
"""
import argparse
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCE_CATALOG = ROOT / 'Additional_Simulations/Visualization_3D/catalog.json'
MODELS = ROOT / 'models'
# Reviewed original catalog hashes. Changes require deliberate scientific review.
ORIGINAL_HASHES = {
    'SAP16': '903aad272933aa6a2e2a744af0b6bfec486228633499f194c3fbe9b30d1486a4',
    'SAP17': '32c47ad227066358c2698a02ed5f69b221f256da1b6f1486f8ffadf9a4a4c6bd',
    'SAP22': '614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3',
    'AK01': '300fe2a86090da837e3c44489f8341929bdc32343331a40a43636c7ed503e830',
    'AK02': '793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa',
    'GeRC02': '7a655caeb660c07df8fcd9af51cc0998daea15f16e31f9c6afcacb89daf39218',
    'KMRC01_candidate': 'd4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6',
    'SAP18_ring08_scenario': 'a4078c32a0f0c357932b12dbd7a9e719ee4aa894268b76c755bf7c3dbbb5bb09',
    'KL01_3D': '84b215eecc13cf5f92aabc5e3c464910315dc71468533e53040cd30874d662ea',
    'BEGe_reference': '4456658ef2b8c777c3614ca4af5933f5a9e092ad18504aaa58754ad696215844',
    'ICPC_large_reference': '9bd9d1f58e5e6efb2fa5a11ab07a5db84126083fd1450b5d7f40edf23a72678d',
    'Bipolar_reference_3D': '804093cedd9e1953589c72d7bcb0e8c13efb48f708d45773d4882dda20665fa5',
    'COAX_ANG2_reference': '75a792c8e8105834b426733bab62bf4589866be35280102b01647a79992a736e',
    'PPC_PONaMa1_reference': '16959e508f82338a3c9f7d47076bb72a1b342abb9f6d337ef642555cfd2274a6',
    'BEGe_GD32B_reference': '7e651b974a5f46f9de084180c0195da047707d14084622994f56eac97a7ff913',
    'ICPC_48A_reference': 'a3b4acf6347b03c2b39e216bfdcf825e47b5c7b6f6293e8f9fd357862815f464',
    'GeGI_3D': '4b6c71c178c81e68bc1fe093d491b59ab99f19aed5adaba5fc61bba74d445c04',
}
DEPENDENCY_HASHES = {
    'ADLChargeDriftModel/drift_velocity_config.yaml':
        '642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6',
}
MAX_FILE = 2 * 1024**2
PRIVATE = re.compile(r'\b[A-Za-z]:[\\/]|file:/|/(?:home|Users|tmp|mnt)/|\\\\', re.I)
SECRET = re.compile(r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}')
README = """# Original SSD model snapshots

These 17 versioned YAML snapshots preserve the original source bytes, including
line endings. `catalog.json` preserves original model hashes, status, assumptions,
and portable provenance. Candidate, scenario and reference names are intentional;
dimension-based reference models are not calibrated replicas.

Nine models require `ADLChargeDriftModel/drift_velocity_config.yaml`, packaged
once here at its original relative path. Keep it alongside the model YAMLs.
The other eight models contain their configuration inline. A per-detector ZIP
contains its YAML, all required includes, this README and its catalog metadata;
the all-model ZIP contains this complete distribution.

These are SSD constructive geometry, material, bias and carrier configurations,
not CAD/STL files, numerical field caches, event data, or readout electronics.
They do not establish numerical convergence or agreement with experiment.
The GeGI source comment refers to its original private README; that source
document is not included. Public provenance and limitations are in the catalog.

Validate from the repository with `python tools/export_models.py --validate`.
Maintainers may explicitly import the recorded local sources with
`python tools/export_models.py --import`. Import checks original hashes first,
copies only models and discovered includes, and refuses differing existing files.
Source files and caches are never changed. Python 3.10+ stdlib is sufficient.
""".encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def public_text(data, name):
    text = data.decode('utf-8-sig')
    # Decode JSON escapes too, so metadata cannot hide paths/keys as \uXXXX.
    decoded = json.dumps(json.loads(text), ensure_ascii=False) if name.endswith('.json') else text
    if PRIVATE.search(text) or SECRET.search(text) or PRIVATE.search(decoded) or SECRET.search(decoded):
        raise ValueError('Private path or possible credential: ' + name)
    return text


def safe_path(name):
    """Canonical portable relative paths only, including on Windows extractors."""
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name):
        raise ValueError('Unsafe path: ' + repr(name))
    for part in name.split('/'):
        if part in ('.', '..') or part.endswith('.') or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', part, re.I):
            raise ValueError('Unsafe path: ' + name)
    return name


def no_links(path):
    for component in (path, *path.parents):
        if component.is_symlink() or (component.exists() and
                getattr(component.stat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Symlink/reparse point is not a model input: ' + str(component))


def read_file(path):
    no_links(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Oversize model distribution file: ' + str(path))
    return path.read_bytes()


def includes(data):
    """Read only the plain block YAML subset used by these exact originals.

    This is a dependency reader, not a scientific YAML parser. Reject quoted
    keys/scalars, flow syntax, tags, anchors, aliases, block scalars, directives,
    explicit keys and continuation lines rather than risk hiding an include.
    """
    found = []
    for number, raw in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        line = raw.split('#', 1)[0].rstrip()
        if not line.strip():
            continue
        if '\t' in line or any(char in line for char in '{}[]\\\"\''):
            raise ValueError(f'Unsupported YAML syntax on line {number}')
        stripped = line.lstrip()
        if stripped.startswith('- '):
            stripped = stripped[2:]
        match = re.fullmatch(r'([\w]+):(?: +(.*))?', stripped)
        if not match:
            if not line.lstrip().startswith('- ') or not re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', stripped):
                raise ValueError(f'Unsupported YAML syntax on line {number}')
            continue
        key, value = match[1], match[2] or ''
        if value.startswith(('!', '&', '*', '|', '>', '?', '%')) or ': ' in value:
            raise ValueError(f'Unsupported YAML value on line {number}')
        if key == 'include':
            safe_path(value)
            if not value.endswith('.yaml'):
                raise ValueError('Only scalar YAML includes are supported')
            found.append(value)
    return found


def collect_model(source, approved_root, output_name, files, active=()):
    """Walk actual include edges under a single approved source model root."""
    safe_path(output_name)
    no_links(source)
    if not source.resolve().is_relative_to(approved_root.resolve()):
        raise ValueError('Include escapes approved model root')
    if source in active:
        raise ValueError('Include cycle: ' + output_name)
    data = read_file(source)
    public_text(data, output_name)
    if any(name.casefold() == output_name.casefold() and name != output_name for name in files):
        raise ValueError('Conflicting dependency path case: ' + output_name)
    if output_name in files and files[output_name] != data:
        raise ValueError('Conflicting dependency: ' + output_name)
    files[output_name] = data
    required = set()
    for include in includes(data):
        target = (PurePosixPath(output_name).parent / include).as_posix()
        required.add(target)
        required.update(collect_model(source.parent / include, approved_root,
                                      target, files, (*active, source)))
    return sorted(required)


def source_snapshot():
    """Only explicit --import calls this function or reads the local catalog."""
    original = json.loads(read_file(SOURCE_CATALOG))['detectors']
    if len(original) != len(ORIGINAL_HASHES) or {d['id'] for d in original} != set(ORIGINAL_HASHES):
        raise ValueError('Unexpected original detector inventory')
    files, detectors = {}, []
    for item in sorted(original, key=lambda d: d['id']):
        detector = item['id']
        source = Path(item['model'])
        if detector == 'GeGI_3D':
            # The sole external input is explicitly recorded and authorized.
            if source.name != 'GeGI_3D.yaml' or not source.is_absolute():
                raise ValueError('Unexpected GeGI source')
            provenance = 'External original GeGI model (private location omitted)'
        else:
            folder = (ROOT / 'Additional_Simulations/Visualization_3D/detectors' / detector / 'config'
                      if item['group'] == 'commercial_reference' else ROOT / 'Additional_Simulations/models')
            expected = folder / ('model.yaml' if item['group'] == 'commercial_reference' else detector + '.yaml')
            if source != expected:
                raise ValueError('Unexpected source model path: ' + detector)
            provenance = source.relative_to(ROOT).as_posix()
        if item['model_sha256'] != ORIGINAL_HASHES[detector] or digest(read_file(source)) != ORIGINAL_HASHES[detector]:
            raise ValueError('Changed original source hash: ' + detector)
        name = detector + '.yaml'
        dependencies = collect_model(source, source.parent, name, files)
        metadata = {key: value for key, value in item.items() if key not in ('model', 'cache', 'sources')}
        metadata.update(model=name, source=provenance, dependencies=dependencies)
        metadata['sources'] = (['Original GeGI model README (private source, not distributed)',
                                'GeGI dimension schematics (private source, not distributed)']
                               if detector == 'GeGI_3D' else item['sources'])
        detectors.append(metadata)
    catalog = {'schema_version': 1, 'description': 'Exact original SSD distribution snapshots; no convergence or experimental validation implied',
               'detectors': detectors,
               'dependencies': [{'path': name, 'sha256': digest(files[name])} for name in sorted(DEPENDENCY_HASHES)]}
    files['catalog.json'] = json_bytes(catalog)
    files['README.md'] = README
    validate_files(files)
    return files


def read_distribution(folder):
    no_links(folder)
    files = {}
    for path in sorted(folder.rglob('*')):
        no_links(path)
        if path.is_file():
            name = safe_path(path.relative_to(folder).as_posix())
            files[name] = read_file(path)
    validate_files(files)
    return files


def validate_files(files):
    for name, data in files.items():
        safe_path(name)
        public_text(data, name)
    catalog = json.loads(files['catalog.json'])
    detectors = catalog['detectors']
    if catalog['schema_version'] != 1 or len(detectors) != 17 or {d['id'] for d in detectors} != set(ORIGINAL_HASHES):
        raise ValueError('Unexpected model catalog inventory')
    expected = {key + '.yaml': value for key, value in ORIGINAL_HASHES.items()}
    expected.update(DEPENDENCY_HASHES)
    if set(files) != set(expected) | {'catalog.json', 'README.md'}:
        raise ValueError('Unexpected or missing model distribution files')
    for name, sha in expected.items():
        if digest(files[name]) != sha:
            raise ValueError('Changed original hash: ' + name)
    if catalog['dependencies'] != [{'path': name, 'sha256': sha} for name, sha in sorted(DEPENDENCY_HASHES.items())]:
        raise ValueError('Dependency metadata differs from original hashes')

    def closure(name, active=()):
        if name in active:
            raise ValueError('Include cycle: ' + name)
        result = set()
        for include in includes(files[name]):
            target = (PurePosixPath(name).parent / include).as_posix()
            if target not in files:
                raise ValueError('Missing include: ' + target)
            result.add(target)
            result.update(closure(target, (*active, name)))
        return result

    for item in detectors:
        name = item['id'] + '.yaml'
        if item['model'] != name or item['model_sha256'] != ORIGINAL_HASHES[item['id']]:
            raise ValueError('Model metadata differs from original hash')
        if item['dependencies'] != sorted(closure(name)):
            raise ValueError('Incomplete dependency metadata: ' + name)
        if not item['status'] or not isinstance(item['assumptions'], list):
            raise ValueError('Missing model limitations: ' + name)
    return catalog


def write_new_or_identical(folder, files):
    """Preflight every managed output before any writes; never overwrite edits."""
    no_links(folder)
    for name in files:
        path = folder / safe_path(name)
        no_links(path)
        if path.exists() and not path.is_file():
            raise ValueError('Existing managed output is not a file: ' + name)
    if folder.exists():
        for path in folder.rglob('*'):
            no_links(path)
            if path.is_file():
                name = path.relative_to(folder).as_posix()
                if name not in files or read_file(path) != files[name]:
                    raise ValueError('Existing managed output differs: ' + name)
    for name, data in sorted(files.items()):
        path = folder / safe_path(name)
        no_links(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(data)


def archive_bytes(files):
    """Stored ZIPs avoid compressor-version variation for this small distribution."""
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError('Conflicting archive path case')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(safe_path(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def validate_archive(data, expected):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = []
        for info in archive.infolist():
            # ZipInfo normalizes backslashes on Windows and truncates NULs.
            # Inspect the original header name before trusting that normalization.
            safe_path(info.orig_filename)
            safe_path(info.filename)
            if (info.orig_filename != info.filename or info.file_size > MAX_FILE or info.flag_bits & 1 or
                    stat.S_IFMT(info.external_attr >> 16) != stat.S_IFREG or
                    info.date_time != (1980, 1, 1, 0, 0, 0) or info.extra or info.comment):
                raise ValueError('Unsafe or noncanonical archive entry: ' + info.filename)
            names.append(info.filename)
        if names != sorted(expected) or archive.comment:
            raise ValueError('Archive inventory/dependencies differ')
        for name in names:
            contents = archive.read(name)
            public_text(contents, name)
            if contents != expected[name]:
                raise ValueError('Archive content differs: ' + name)
    if data != archive_bytes(expected):
        raise ValueError('Archive bytes are not reproducible')


def download_files(files):
    catalog = validate_files(files)
    output = {'models/' + name: data for name, data in files.items()}
    output['downloads/all-models.zip'] = archive_bytes(files)
    for item in catalog['detectors']:
        subset = {name: files[name] for name in [item['model'], *item['dependencies'], 'README.md']}
        metadata = dict(catalog, detectors=[item], dependencies=[d for d in catalog['dependencies'] if d['path'] in item['dependencies']])
        subset['catalog.json'] = json_bytes(metadata)
        output['downloads/' + item['id'] + '.zip'] = archive_bytes(subset)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--import', dest='do_import', action='store_true')
    mode.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    if args.do_import:
        write_new_or_identical(MODELS, source_snapshot())
    files = read_distribution(MODELS)
    catalog = validate_files(files)
    print(f"Validated {len(catalog['detectors'])} exact original models, "
          f"{len(catalog['dependencies'])} shared dependency; "
          f"{sum(bool(d['dependencies']) for d in catalog['detectors'])} models use includes.")


if __name__ == '__main__':
    main()
