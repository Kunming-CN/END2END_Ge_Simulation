// Publish only the reviewed static-site deliverable; never force-push.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = 'Kunming-CN/END2END_Ge_Simulation';
const git = process.platform === 'win32' ? 'C:/Program Files/Git/cmd/git.exe' : 'git';
const gh = process.platform === 'win32' ? 'C:/Program Files/GitHub CLI/gh.exe' : 'gh';
const python = process.env.SITE_PYTHON || (process.platform === 'win32' ? 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' : 'python3');
process.env.PATH = path.dirname(git) + path.delimiter + process.env.PATH;
function run(exe, args, capture = false, allowFailure = false) {
  const r = spawnSync(exe, args, { cwd: root, encoding: 'utf8', stdio: capture ? 'pipe' : 'inherit' });
  if (r.error) throw r.error;
  if (r.status !== 0 && !allowFailure) throw new Error(`${path.basename(exe)} failed (${r.status}). ${r.stderr || ''}`);
  return r;
}
function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(d => d.isDirectory() ? files(path.join(dir, d.name)) : [path.join(dir, d.name)]);
}
run(python, [path.join(root, 'tools/export_models.py'), '--validate']);
run(python, [path.join(root, 'tools/test_site.py')]);
run(python, [path.join(root, 'tools/test_contacts.py')]);
run(python, [path.join(root, 'tools/test_pipeline.py')]);
run(python, [path.join(root, 'tools/test_lithium_report.py')]);
run(python, [path.join(root, 'tools/build_site.py')]);
for (const f of files(path.join(root, 'docs'))) {
  if (fs.statSync(f).size >= 95 * 1024 ** 2 || /\.(jls|pvsm|vtr|bin|pdf|pptx)$/i.test(f)) throw new Error('Unapproved public file: ' + f);
  if (/\.(html|json|md)$/i.test(f) && /BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}/.test(fs.readFileSync(f, 'utf8'))) throw new Error('Potential credential in public output: ' + f);
}
if (process.argv.includes('--check-only')) { console.log('Publication preflight passed; no GitHub writes performed.'); process.exit(0); }
if (run(gh, ['auth', 'status', '--hostname', 'github.com'], true, true).status !== 0) run(gh, ['auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web']);
const login = run(gh, ['api', 'user', '--jq', '.login'], true).stdout.trim();
if (login !== 'Kunming-CN') throw new Error('Wrong GitHub account: ' + login);
if (!fs.existsSync(path.join(root, '.git'))) run(git, ['init', '-b', 'main']);
if (run(git, ['branch', '--show-current'], true).stdout.trim() !== 'main') throw new Error('Switch to reviewed main branch before publishing.');
run(git, ['config', 'user.name', 'Kunming Dong']);
run(git, ['config', 'user.email', '59462521+Kunming-CN@users.noreply.github.com']);
run(gh, ['auth', 'setup-git', '--hostname', 'github.com']);
const existing = run(gh, ['repo', 'view', repo, '--json', 'nameWithOwner'], true, true);
if (existing.status !== 0) run(gh, ['repo', 'create', repo, '--public', '--description', 'Precomputed germanium detector results and staged end-to-end simulation development']);
const origin = run(git, ['remote', 'get-url', 'origin'], true, true);
if (origin.status !== 0) run(git, ['remote', 'add', 'origin', `https://github.com/${repo}.git`]);
else if (![`https://github.com/${repo}.git`, `https://github.com/${repo}`, `git@github.com:${repo}.git`].includes(origin.stdout.trim())) throw new Error('Unexpected origin; stop and inspect.');
const simulationFiles = new Set(["simulation/Project.toml","simulation/Manifest.toml","simulation/run.jl","simulation/README.md","simulation/benchmark.jl","simulation/test_run.jl","simulation/gpu/Project.toml","simulation/gpu/Manifest.toml","simulation/replay.jl","simulation/test_replay.jl","simulation/diagnose_collection.jl","simulation/test_collection.jl","simulation/validate_transition.jl","simulation/test_transition.jl","simulation/PHYSICS.md","simulation/verify_electrostatics.jl","simulation/test_electrostatics.jl","simulation/verify_ssd_electrostatics.jl","simulation/test_ssd_electrostatics.jl","simulation/readout.jl","simulation/test_readout.jl","simulation/readout_demo.json","simulation/verify_readout.jl","simulation/test_verify_readout.jl","simulation/diagnose_lithium.jl","simulation/test_lithium.jl"]);
const transportFiles = new Set(["transport/README.md","transport/pixi.toml","transport/pixi.lock","transport/.pixi/config.toml","transport/cryostat-source.json","transport/Run.cmd","transport/run.sh","transport/smoke.gdml","transport/smoke.mac","transport/check_smoke.py","transport/handoff.py","transport/test_handoff.py","transport/geometry_probe.cc","transport/CMakeLists.txt","transport/experiment.json","transport/compare_em.py","transport/test_compare_em.py"]);
const approved = new Set(['.gitignore', '.gitattributes', 'README.md', 'PROGRESS.md', 'AGENTS.md', 'Publish.cmd']);
// build_site.py has already validated this exact, versioned model inventory.
const modelCatalog = JSON.parse(fs.readFileSync(path.join(root, 'models/catalog.json'), 'utf8'));
const modelFiles = new Set(['models/catalog.json', 'models/README.md',
  ...modelCatalog.detectors.map(d => 'models/' + d.model),
  ...modelCatalog.dependencies.map(d => 'models/' + d.path)]);
for (const f of run(git, ['diff', '--cached', '--name-only'], true).stdout.split('\n').filter(Boolean)) {
  if (!approved.has(f) && !f.startsWith('docs/') && !f.startsWith('tools/') && !modelFiles.has(f) && !simulationFiles.has(f) && !transportFiles.has(f)) throw new Error('Unreviewed staged file: ' + f);
}
run(git, ['add', '--', ...approved, 'docs', 'tools', ...modelFiles, ...simulationFiles, ...transportFiles]);
const changed = run(git, ['diff', '--cached', '--quiet'], true, true);
if (changed.status === 1) run(git, ['commit', '-m', 'Update reviewed detector results and project progress']);
else if (changed.status !== 0) throw new Error('Cannot inspect staged changes.');
run(git, ['push', '--set-upstream', 'origin', 'main']);
const endpoint = `repos/${repo}/pages`;
let page = run(gh, ['api', endpoint], true, true);
if (page.status !== 0) {
  const request = path.join(root, '.local/pages-request.json');
  fs.writeFileSync(request, JSON.stringify({ source: { branch: 'main', path: '/docs' } }));
  run(gh, ['api', '--method', 'POST', endpoint, '--input', request]);
  page = run(gh, ['api', endpoint], true);
}
const info = JSON.parse(page.stdout);
if (info.source?.branch !== 'main' || info.source?.path !== '/docs') throw new Error('Existing Pages configuration differs; inspect it rather than overwrite.');
console.log('Pushed successfully. Pages address:', info.html_url);
let live = false;
for (let attempt = 0; attempt < 24; attempt++) {
  try {
    const response = await fetch(info.html_url, { signal: AbortSignal.timeout(8000), cache: 'no-store' });
    if (response.ok && (await response.text()).includes('Simulation results online')) { live = true; break; }
  } catch { /* The initial Pages deployment can take a few minutes. */ }
  await new Promise(resolve => setTimeout(resolve, 5000));
}
fs.writeFileSync(path.join(root, '.local/publication.json'), JSON.stringify({ repo, url: info.html_url, reachable: live, checked_at: new Date().toISOString() }, null, 2));
console.log(live ? 'Verified: the website is reachable.' : 'Upload complete; Pages is still deploying. This is not yet a verified live site.');
const progressPath = path.join(root, 'PROGRESS.md');
let progress = fs.readFileSync(progressPath, 'utf8');
progress = progress.replace('Status: public website prepared locally; first GitHub push/Pages activation awaits GitHub CLI browser authorization.', live ? `Status: published and verified at ${info.html_url}` : `Status: repository pushed and Pages configured; live deployment verification pending at ${info.html_url}`);
progress = progress.replace('Ready locally; authorization pending', live ? 'Published; URL verified' : 'Pushed; deployment pending');
fs.writeFileSync(progressPath, progress);
const readmePath = path.join(root, 'README.md');
let readme = fs.readFileSync(readmePath, 'utf8');
readme = readme.replace("The first public deployment still requires completing the computer's GitHub CLI authorization. A linked ChatGPT GitHub account is a separate connection.", `GitHub CLI authorization is configured on the development computer. Pages address: ${info.html_url} (deployment ${live ? 'verified' : 'pending verification'}).`);
fs.writeFileSync(readmePath, readme);
run(git, ['add', '--', 'README.md', 'PROGRESS.md']);
const statusUpdate = run(git, ['diff', '--cached', '--quiet'], true, true);
if (statusUpdate.status === 1) { run(git, ['commit', '-m', 'Record initial publication status']); run(git, ['push']); }
else if (statusUpdate.status !== 0) throw new Error('Cannot check publication status update.');
