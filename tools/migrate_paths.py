"""Repair a moved workspace's text paths; never modify numerical binary files."""
import argparse, hashlib, json, zipfile
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--old-root', required=True)
p.add_argument('--apply', action='store_true')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
old = a.old_root.replace('\\', '/').rstrip('/')
new = root.as_posix()
variants = [(old, new), (old.replace('/', '\\'), new.replace('/', '\\')),
            (old.replace('/', '\\\\'), new.replace('/', '\\\\'))]
variants.sort(key=lambda x: len(x[0]), reverse=True)
allowed = {'.json', '.pvsm', '.html', '.py', '.jl', '.ps1', '.cmd', '.toml'}
changes = []
for f in (root / 'Additional_Simulations').rglob('*'):
    if not f.is_file() or f.suffix.lower() not in allowed:
        continue
    if any(s in f.parts for s in ('history', 'maintenance', 'logs', 'audit', '__pycache__')):
        continue
    original = f.read_bytes()
    updated = original
    for before, after in variants:
        updated = updated.replace(before.encode(), after.encode())
    if updated != original:
        changes.append((f, original, updated))
print('Path-bearing files requiring repair:', len(changes), flush=True)
report = {'mode': 'applied' if a.apply else 'dry-run', 'files': []}
archive = root / '.local' / 'migration-originals.zip'
if a.apply and changes:
    if archive.exists():
        raise SystemExit('Backup already exists; inspect before another migration.')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for f, original, updated in changes:
            z.writestr(f.relative_to(root).as_posix(), original)
    for f, original, updated in changes:
        if f.read_bytes() != original:
            raise RuntimeError('File changed during audit: ' + str(f))
        f.write_bytes(updated)
        report['files'].append({'path': f.relative_to(root).as_posix(),
            'before_sha256': hashlib.sha256(original).hexdigest(),
            'after_sha256': hashlib.sha256(updated).hexdigest()})
    (root / '.local' / 'migration-report.json').write_text(json.dumps(report, indent=2))
    print('Saved originals in .local/migration-originals.zip; repaired', len(changes), flush=True)
else:
    for f, _, _ in changes[:25]:
        print(f.relative_to(root))
