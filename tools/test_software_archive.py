"""Check a software source ZIP against its Git commit; no installs or physics.

Every tracked file except docs/ must retain its Git bytes, allowing only an EOL
conversion explicitly declared in that commit's attributes. Generate local ZIPs
with git -c core.autocrlf=false -c core.eol=lf archive to avoid machine-specific conversions.
This uses the commit tree rather than a second packaging allowlist. --candidate labels a
pre-commit archive made with git archive --worktree-attributes; its contents still
come from the named commit, so it does not validate uncommitted source changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(*args, data=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=data)


def validate(archive, ref='HEAD', candidate=False):
    archive = Path(archive).resolve()
    commit = git('rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    expected = {}
    for record in git('ls-tree', '-r', '-z', commit).split(b'\0'):
        if not record:
            continue
        metadata, path = record.split(b'\t', 1)
        path = path.decode('utf-8')
        if path.startswith('docs/'):
            continue
        mode, kind, blob = metadata.decode().split()
        require(kind == 'blob' and mode in ('100644', '100755'),
                'Unsupported software tree entry: ' + path)
        expected[path] = blob
    require(expected, 'Software tree is empty.')
    attribute_records = git('check-attr', '--source=' + commit, '-z', '--stdin',
                            'text', 'eol', data=('\0'.join(expected) + '\0').encode()).split(b'\0')
    attributes = {path: {} for path in expected}
    for index in range(0, len(attribute_records) - 1, 3):
        path, attribute, value = attribute_records[index:index + 3]
        attributes[path.decode()][attribute.decode()] = value.decode()
    directories = {str(parent) + '/' for path in expected for parent in
                   PurePosixPath(path).parents if str(parent) != '.'}
    batch = git('cat-file', '--batch', data=('\n'.join(expected.values()) + '\n').encode())
    cursor = 0
    digests = {}
    source_bytes = 0
    eol_converted = []
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        require(infos and len({item.filename for item in infos}) == len(infos),
                'Empty archive or duplicate ZIP member.')
        prefix = infos[0].filename.split('/')[0] + '/'
        files = {}
        for item in infos:
            name = item.filename
            require(name.startswith(prefix) and not name.startswith('/') and
                    '\\' not in name and '..' not in PurePosixPath(name).parts,
                    'Unsafe archive member: ' + name)
            relative = name[len(prefix):]
            if item.is_dir():
                require(not relative or relative in directories,
                        'Unexpected archive directory: ' + relative)
            else:
                files[relative] = item
        require(set(files) == set(expected),
                'Archive member mismatch: missing=' + repr(sorted(set(expected) - set(files))) +
                '; unexpected=' + repr(sorted(set(files) - set(expected))))
        for path, blob in expected.items():
            end = batch.index(b'\n', cursor)
            actual_blob, kind, size = batch[cursor:end].decode().split()
            size = int(size)
            cursor = end + 1
            original = batch[cursor:cursor + size]
            cursor += size + 1
            require(actual_blob == blob and kind == 'blob' and len(original) == size,
                    'Invalid Git blob response: ' + path)
            body = bundle.read(files[path])
            if body != original:
                attr = attributes[path]
                require(attr['text'] != 'unset' and attr['eol'] in ('lf', 'crlf'),
                        'Archive changed source bytes without a declared EOL conversion: ' + path)
                converted = original.replace(b'\r\n', b'\n')
                if attr['eol'] == 'crlf':
                    converted = converted.replace(b'\n', b'\r\n')
                require(body == converted, 'Archive changed source bytes: ' + path)
                eol_converted.append(path)
            source_bytes += size
            digests[path] = hashlib.sha256(body).hexdigest()
        require(cursor == len(batch), 'Unexpected trailing Git blob data.')
        compressed_payload_bytes = sum(item.compress_size for item in files.values())
    return {'status': 'passed', 'commit': commit, 'candidate_packaging_only': candidate,
            'archive_file': str(archive), 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'files': len(expected), 'source_bytes': source_bytes,
            'declared_eol_conversions': eol_converted,
            'archive_bytes': archive.stat().st_size, 'compressed_payload_bytes': compressed_payload_bytes,
            'payload_sha256': hashlib.sha256(json.dumps(digests, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest(),
            'scope': 'Committed software/model/source/lock/template bytes with only declared EOL conversions; excludes docs and all untracked files. No installation or simulation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--candidate', action='store_true')
    args = parser.parse_args()
    print(json.dumps(validate(args.archive, args.ref, args.candidate), indent=2))


if __name__ == '__main__':
    main()
