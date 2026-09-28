"""Windows maintainer acceptance: isolated source clone, no installs or physics.
Checks negative readiness, not clean-machine setup or positive end-to-end execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('Run.cmd', 'tools/scenario_cli.ps1', 'tools/run_native_campaign.ps1',
           'tools/verify_native_pilot.ps1', 'tools/test_scenario_cli.ps1',
           'transport/Run.cmd', 'transport/run.sh', 'transport/pixi.toml',
           'transport/pixi.lock', 'scenarios/lbnl-cs137.json',
           'simulation/Project.toml', 'simulation/Manifest.toml',
           'simulation/native_response_guarded.jl', 'simulation/native_response.jl')

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    require(os.name == 'nt', 'This acceptance exercises the Windows launcher.')
    out = args.output.resolve()
    require(out.is_relative_to(ROOT / '.local') and not out.exists(),
            'Choose a NEW test output below project .local; old evidence is preserved.')
    out.mkdir(parents=True)
    records: list[dict] = []
    def command(label: str, argv: list[str], cwd: Path = ROOT) -> tuple[int, str]:
        start = time.monotonic()
        with (out / (label + '.log')).open('wb') as log:
            result = subprocess.run(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=180, check=False)
        text = (out / (label + '.log')).read_text(encoding='utf-8', errors='replace')
        records.append(dict(label=label, exit_code=result.returncode,
                            seconds=time.monotonic()-start, command=argv))
        (out / 'commands.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        return result.returncode, text
    git = shutil.which('git')
    require(git is not None, 'Git is required.')
    base = subprocess.check_output([git, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    clone = out / 'isolated source clone'
    code, _ = command('clone', [git, 'clone', '--no-hardlinks', '--no-checkout', str(ROOT), str(clone)])
    require(code == 0, 'Local source clone failed; inspect clone.log.')
    for label, subargs in (
        ('sparse-init', ['sparse-checkout', 'init', '--cone']),
        ('sparse-set', ['sparse-checkout', 'set', 'tools', 'simulation', 'transport', 'models', 'scenarios']),
        ('checkout', ['checkout', '--detach', base]),
    ):
        code, _ = command(label, [git, '-C', str(clone), *subargs])
        require(code == 0, label + ' failed.')
    # A documented source-only candidate overlay permits validation before committing.
    # Never copy private data, package directories, field caches or supervisor state.
    for rel in SOURCES:
        shutil.copyfile(ROOT / rel, clone / rel)
    hashes = {rel: digest(ROOT / rel) for rel in SOURCES}
    require(all(digest(clone / rel) == h for rel, h in hashes.items()), 'Candidate source mismatch.')
    require(not (clone / '.local').exists(), 'Source clone unexpectedly contains private data.')
    powershell = shutil.which('powershell.exe')
    require(powershell is not None, 'Windows PowerShell is required.')
    run_path = str(clone / 'Run.cmd').replace("'", "''")
    def launcher(label: str, arguments: str) -> tuple[int, str]:
        # Invoke from OUTSIDE the clone, including a path with spaces.
        return command(label, [powershell, '-NoProfile', '-Command',
                       f"& '{run_path}' {arguments}; exit $LASTEXITCODE"], cwd=out)
    code, text = launcher('status', 'status')
    require(code == 0 and 'No .local/runs yet.' in text, 'Fresh-clone status failed.')
    code, text = launcher('check-missing', 'check')
    require(code == 2, f'Incomplete preflight must exit 2, received {code}.')
    require('Setup is incomplete' in text and 'transport/cryostat-source.json' in text,
            'Missing pinned-upstream acquisition guidance.')
    require('read_only_no_install' in text, 'Preflight mode was not reported.')
    code, _ = launcher('dry-run-missing', 'run -Preset demo -Detector AK02 -Name clone-preflight -DryRun')
    require(code != 0, 'Dry-run must reject missing prerequisites.')
    require(not (clone / '.local' / 'runs').exists(), 'Negative preflight created a campaign.')
    require(not (clone / '.local' / 'transport' / 'LBNL').exists(), 'Upstream was silently copied/fetched.')
    require(not (clone / '.local' / 'm2a').exists(), 'Exporter was silently built.')
    require(all(digest(clone / rel) == h for rel, h in hashes.items()), 'Preflight mutated checked sources.')
    result = dict(status='passed_negative_same_machine_source_clone_preflight',
                  base_commit=base, candidate_runtime_sha256=hashes,
                  candidate_overlay=list(SOURCES), source_clone=str(clone.relative_to(ROOT)),
                  calls=records, new_simulations=0, new_field_solves=0,
                  upstream_or_science_caches_copied=False, installers_or_builds_invoked=False,
                  scope='Actual isolated local Git clone with explicit candidate source overlay; inherited machine tools/package caches; missing-prerequisite rejection only, NOT ready setup or positive end-to-end reproduction')
    (out / 'acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('PASS: isolated source clone correctly rejects missing setup; no campaign, install or build.')

if __name__ == '__main__':
    main()
