"""Build/verify the explicit student runtime ZIP; never install or run science.

Committed builds read Git blobs, independent of checkout EOL settings. --worktree
is an explicitly labelled development candidate and cannot be a release receipt.
Only the maintained guide is derived for standalone student use.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from urllib.parse import urljoin
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'tools/student_runtime_manifest.json'
METADATA = 'PACKAGE.json'
STAMP = (1980, 1, 1, 0, 0, 0)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def sha(body):
    return hashlib.sha256(body).hexdigest()


def git(root, *args, data=None):
    return subprocess.check_output(['git', *args], cwd=root, input=data)


def safe_relative(path):
    require(type(path) is str and path and '\\' not in path and ':' not in path,
            'Invalid package path: ' + repr(path))
    pure = PurePosixPath(path)
    require(not pure.is_absolute() and not any(p in ('', '.', '..') for p in path.split('/')),
            'Unsafe package path: ' + path)
    return path


def ordinary_file(root, relative):
    path = root
    for part in PurePosixPath(safe_relative(relative)).parts:
        path = path / part
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not
                getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400),
                'Linked package source refused: ' + relative)
    require(path.is_file(), 'Missing package source: ' + relative)
    return path


def tree(root, ref):
    commit = git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    entries = {}
    for record in git(root, 'ls-tree', '-r', '-z', commit).split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            entries[path.decode('utf-8')] = (mode, kind, oid)
    return commit, entries


def blobs(root, entries, paths):
    require(all(p in entries for p in paths), 'Manifest contains uncommitted/missing source paths.')
    require(all(entries[p][0] in ('100644', '100755') and entries[p][1] == 'blob' for p in paths),
            'Package sources must be ordinary Git files.')
    raw = git(root, 'cat-file', '--batch', data=('\n'.join(entries[p][2] for p in paths) + '\n').encode())
    result = {}; cursor = 0
    for path in paths:
        end = raw.index(b'\n', cursor)
        oid, kind, size = raw[cursor:end].decode().split(); size = int(size)
        require(oid == entries[path][2] and kind == 'blob', 'Invalid Git blob response.')
        cursor = end + 1; result[path] = raw[cursor:cursor + size]; cursor += size + 1
    require(cursor == len(raw), 'Unexpected trailing Git blob data.')
    return result


def manifest_paths(manifest):
    require(manifest.get('kind') == 'student_runtime_manifest_v1' and manifest.get('schema_version') == 1,
            'Unsupported student manifest.')
    safe_relative(manifest['archive_root'])
    require('/' not in manifest['archive_root'], 'Archive root must be one directory.')
    paths = [safe_relative(p) for members in manifest['groups'].values() for p in members]
    require(paths and len(set(paths)) == len(paths), 'Empty or duplicate manifest member.')
    for path in paths:
        parts = PurePosixPath(path).parts
        require(not any(p in ('docs', '.local', '.git', '.github', '__pycache__') for p in parts) and
                not any(p.startswith('test_') or p.startswith('diagnose_') for p in parts),
                'Development/results source excluded from student package: ' + path)
    require(MANIFEST in paths and manifest['guide']['path'] in paths,
            'Package must retain its contract and maintained guide.')
    return sorted(paths)


def frozen_sources(syntax, name):
    """Read a constant map/return expression without executing packaged Python."""
    assigned = {target.id: node.value for node in syntax.body if isinstance(node, ast.Assign)
                for target in node.targets if isinstance(target, ast.Name)}
    def constant(node, seen=()):
        if isinstance(node, ast.Name):
            require(node.id in assigned and node.id not in seen, 'Invalid frozen source constant.')
            return constant(assigned[node.id], (*seen, node.id))
        if isinstance(node, ast.Dict):
            value = {}
            for key, item in zip(node.keys, node.values):
                if key is None:
                    unpacked = constant(item, seen)
                    require(type(unpacked) is dict, 'Invalid frozen source map unpacking.')
                    value.update(unpacked)
                else:
                    value[ast.literal_eval(key)] = constant(item, seen)
            return value
        return ast.literal_eval(node)
    if name in assigned:
        value = constant(assigned[name], (name,))
    else:
        functions = [node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == name]
        require(len(functions) == 1 and len(functions[0].body) == 1 and
                isinstance(functions[0].body[0], ast.Return), 'Frozen source inventory must be a static return.')
        value = constant(functions[0].body[0].value)
    require(type(value) is dict and value and all(type(ref) is str and type(digest) is str and
            re.fullmatch('[0-9a-f]{64}', digest) for ref, digest in value.items()), 'Invalid frozen source inventory.')
    return value


def dependencies(manifest, bodies):
    """Small source-closure checks, plus explicit launcher/data dependencies."""
    modules = {PurePosixPath(p).stem: p for p in bodies if p.endswith('.py')}
    allowed = set(sys.stdlib_module_names) | set(manifest['external_python_modules'])
    checks = {'python_files': 0, 'julia_includes': 0, 'explicit_dependencies': 0,
              'models': 0, 'frozen_source_pins': 0}
    for owner, refs in manifest['entrypoint_dependencies'].items():
        require(owner in bodies, 'Missing entrypoint: ' + owner)
        for ref in refs:
            require(ref in bodies, 'Missing runtime dependency: ' + owner + ' -> ' + ref)
            checks['explicit_dependencies'] += 1
    for path, body in bodies.items():
        if path.endswith('.py'):
            syntax = ast.parse(body.decode('utf-8-sig'), filename=path)
            checks['python_files'] += 1
            contract = manifest.get('source_hash_contracts', {}).get(path)
            if contract:
                for ref, digest in frozen_sources(syntax, contract).items():
                    require(ref in bodies and sha(bodies[ref]) == digest,
                            'Missing/changed frozen runtime source: ' + path + ' -> ' + ref)
                    checks['frozen_source_pins'] += 1
            for node in ast.walk(syntax):
                names = ([a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else
                         [(node.module or '').split('.')[0]] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    require(not name or name in modules or name in allowed,
                            'Missing local/undeclared Python import: ' + path + ' -> ' + name)
        if path.endswith('.jl'):
            for ref in re.findall(r'\binclude\(\s*"([^"\n]+)"\s*\)', body.decode('utf-8-sig')):
                target = (PurePosixPath(path).parent / safe_relative(ref)).as_posix()
                require(target in bodies, 'Missing Julia include: ' + path + ' -> ' + target)
                checks['julia_includes'] += 1
    catalog = json.loads(bodies['models/catalog.json'])
    for item in catalog['detectors']:
        path = 'models/' + safe_relative(item['model'])
        require(path in bodies and sha(bodies[path]) == item['model_sha256'],
                'Missing/changed canonical model: ' + path)
        checks['models'] += 1
        for dep in item['dependencies']:
            require('models/' + safe_relative(dep) in bodies, 'Missing model include: ' + dep)
    for item in catalog['dependencies']:
        path = 'models/' + safe_relative(item['path'])
        require(path in bodies and sha(bodies[path]) == item['sha256'],
                'Missing/changed canonical model dependency: ' + path)
    require(checks['frozen_source_pins'] > 0, 'Frozen setup source contract was not checked.')
    return checks


def standalone_guide(body, guide):
    require(guide['derivation'] == 'standalone_guide_v1', 'Unsupported guide derivation.')
    text = body.decode('utf-8-sig').replace('__PAGE_NAVIGATION__', '')
    text, removed = re.subn(r'<section id="advanced-routes" aria-labelledby="advanced-title">.*?</section>',
                           '', text, count=1, flags=re.S)
    require(removed == 1, 'Maintained advanced guide section changed; update explicit derivation.')
    text = re.sub(r'<p>[^<]*<a href="#advanced-title">.*?</p>', '', text, count=1, flags=re.S)
    def link(match):
        quote, href = match.groups()
        return 'href=' + quote + (href if href.startswith(('#', 'http:', 'https:', 'mailto:')) else
                                  urljoin(guide['public_base'], href)) + quote
    text = re.sub(r'href=(["\'])(.*?)\1', link, text)
    return text.encode('utf-8')


def source(root=ROOT, ref='HEAD', worktree=False):
    root = Path(root).resolve(); commit, entries = tree(root, ref)
    contract = (ordinary_file(root, MANIFEST).read_bytes() if worktree else
                blobs(root, entries, [MANIFEST])[MANIFEST])
    manifest = json.loads(contract); paths = manifest_paths(manifest)
    committed = blobs(root, entries, [p for p in paths if p in entries])
    bodies = ({p: ordinary_file(root, p).read_bytes() for p in paths} if worktree else
              blobs(root, entries, paths))
    checks = dependencies(manifest, bodies)
    packaged = dict(bodies); guidepath = manifest['guide']['path']
    packaged[guidepath] = standalone_guide(bodies[guidepath], manifest['guide'])
    records = {}
    changed = []
    for path in paths:
        exact = path in committed and bodies[path] == committed[path]
        if not exact: changed.append(path)
        records[path] = {'source_sha256': sha(bodies[path]), 'source_bytes': len(bodies[path]),
                         'packaged_sha256': sha(packaged[path]), 'packaged_bytes': len(packaged[path]),
                         'git_blob_oid': entries[path][2] if exact else None,
                         'derivation': 'standalone_guide_v1' if path == guidepath else 'exact_git_bytes' if exact else 'candidate_worktree_bytes'}
    metadata = {'kind': 'student_runtime_package_v1', 'schema_version': 1,
                'source_commit': commit, 'source_mode': 'candidate_worktree' if worktree else 'committed_git',
                'manifest_sha256': sha(contract), 'members': records, 'dependency_checks': checks,
                'candidate_changed_paths': changed, 'guide_derivation':
                    'Remove site navigation placeholder and advanced/history routes; resolve non-anchor relative links against public_base.',
                'scope': manifest['scope']}
    packaged[METADATA] = encoded(metadata)
    modes = {p: 0o755 if entries.get(p, ('100644',))[0] == '100755' else 0o644 for p in packaged}
    return manifest, packaged, metadata, modes


def write_archive(path, manifest, bodies, modes):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    require(not temporary.exists(), 'An earlier incomplete ZIP exists; inspect before replacing.')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, body in sorted(bodies.items()):
                info = zipfile.ZipInfo(manifest['archive_root'] + '/' + name, STAMP)
                info.create_system = 3; info.external_attr = (stat.S_IFREG | modes[name]) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, body, compresslevel=9)
        temporary.replace(path)
    except BaseException:
        # Preserve the incomplete derivative as evidence; no scientific outputs involved.
        raise


def verify(archive, root=ROOT, ref='HEAD', worktree=False):
    manifest, expected, metadata, modes = source(root, ref, worktree)
    archive = Path(archive); prefix = manifest['archive_root'] + '/'
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        require(len(infos) == len(expected) and len({i.filename for i in infos}) == len(infos),
                'Unexpected or duplicate package member.')
        members = {}
        for item in infos:
            require(item.filename.startswith(prefix) and not item.is_dir(), 'Invalid package root/member.')
            path = safe_relative(item.filename[len(prefix):])
            require(path in expected, 'Unlisted package member: ' + path)
            require(item.date_time == STAMP and item.create_system == 3 and
                    item.external_attr >> 16 == stat.S_IFREG | modes[path], 'Unstable/linked ZIP member: ' + path)
            body = bundle.read(item)
            require(body == expected[path], 'Package bytes differ from declared source/derivation: ' + path)
            members[path] = body
        require(set(members) == set(expected), 'Missing runtime package member.')
    checks = dependencies(manifest, members)
    return {'kind': 'student_runtime_receipt_v1', 'status': 'passed',
            'source_commit': metadata['source_commit'], 'source_mode': metadata['source_mode'],
            'release_eligible': not worktree, 'archive_file': archive.name,
            'archive_sha256': sha(archive.read_bytes()), 'archive_bytes': archive.stat().st_size,
            'members': len(expected), 'source_files': len(metadata['members']),
            'source_bytes': sum(r['source_bytes'] for r in metadata['members'].values()),
            'manifest_sha256': metadata['manifest_sha256'], 'package_metadata_sha256': sha(expected[METADATA]),
            'dependency_checks': checks, 'candidate_changed_paths': metadata['candidate_changed_paths'],
            'scope': 'Manifest membership, exact Git/source bytes, explicit guide derivation and source dependency closure. No installation, transport, SSD or readout execution.'}


def build(archive, root=ROOT, ref='HEAD', worktree=False):
    manifest, bodies, _, modes = source(root, ref, worktree)
    write_archive(archive, manifest, bodies, modes)
    return verify(archive, root, ref, worktree)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('archive', type=Path)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--worktree', action='store_true', help='Explicit uncommitted development candidate; never release.')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    receipt = (build if args.action == 'build' else verify)(args.archive, ref=args.ref, worktree=args.worktree)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(encoded(receipt))
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
